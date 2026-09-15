"""Blueprint §I acceptance tests — run via: bench --site <site> run-tests --app fresko_universe"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from fresko_universe.fresko_core.ats import available_to_sell
from fresko_universe.deals import (
    accept_counter,
    apply_rate_rules,
    apply_revision,
    cancel_deal,
    request_revision,
)
from fresko_universe.approvals import decide
from fresko_universe.tests.utils import ensure_masters, make_container, make_deal


class TestPhase1Acceptance(FrappeTestCase):
    def setUp(self):
        self.masters = ensure_masters()
        frappe.set_user("Administrator")

    def test_duplicate_message_id_does_not_create_second_deal(self):
        c = make_container(self.masters, container_no=f"DUP-MSG-{frappe.generate_hash(length=6)}")
        d1 = make_deal(c, source_message_id="msg-unique-1")
        with self.assertRaises(frappe.ValidationError):
            make_deal(c, buyer_alias="Other", source_message_id="msg-unique-1")
        self.assertTrue(frappe.db.exists("Fresko Deal", d1.name))

    def test_duplicate_fingerprint_attaches_evidence_not_new_deal(self):
        c = make_container(self.masters, container_no=f"DUP-FP-{frappe.generate_hash(length=6)}")
        d1 = make_deal(c, buyer_alias="SameBuyer", qty=5, proposed_rate=110)
        fp = d1.duplicate_fingerprint
        self.assertTrue(fp)
        before_ev = frappe.db.count("Fresko Evidence", {"deal": d1.name})
        with self.assertRaises(frappe.ValidationError):
            make_deal(c, buyer_alias="SameBuyer", qty=5, proposed_rate=110)
        after_ex = frappe.get_all(
            "Fresko Exception",
            filters={"deal": d1.name, "exception_type": "DUPLICATE_MESSAGE"},
        )
        self.assertTrue(after_ex or frappe.db.count("Fresko Evidence", {"deal": d1.name}) >= before_ev)

    def test_deal_rejects_lot_not_on_container(self):
        c = make_container(self.masters, container_no=f"LOT-BAD-{frappe.generate_hash(length=6)}")
        with self.assertRaises(frappe.ValidationError):
            make_deal(c, lot_no="NOT-A-REAL-LOT")

    def test_below_floor_sets_approval_required(self):
        c = make_container(self.masters, container_no=f"FLOOR-{frappe.generate_hash(length=6)}", rate_floor=100)
        d = make_deal(c, proposed_rate=50)
        result = apply_rate_rules(d.name)
        self.assertEqual(result["status"], "Approval Required")
        self.assertEqual(result["approval_required"], 1)
        d.reload()
        self.assertEqual(flt_status(d.rate_floor), 100)

    def test_approval_sets_approved_rate_keeps_proposed_rate(self):
        c = make_container(self.masters, container_no=f"APR-{frappe.generate_hash(length=6)}", rate_floor=100)
        d = make_deal(c, proposed_rate=50, qty=5)
        apply_rate_rules(d.name)
        result = decide(d.name, "APPROVE", decision_rate=90, reason="ok below floor")
        self.assertEqual(result["status"], "Approved")
        self.assertEqual(result["approved_rate"], 90)
        self.assertEqual(result["proposed_rate"], 50)
        d.reload()
        self.assertEqual(d.proposed_rate, 50)
        self.assertEqual(d.approved_rate, 90)

    def test_desk_edit_approved_rate_rejected(self):
        c = make_container(self.masters, container_no=f"DESK-{frappe.generate_hash(length=6)}", rate_floor=10)
        d = make_deal(c, proposed_rate=50, qty=5)
        apply_rate_rules(d.name)  # auto approve in band
        d.reload()
        self.assertEqual(d.status, "Auto Approved")
        d.approved_rate = 999
        with self.assertRaises(frappe.ValidationError):
            d.save()

    def test_revision_plus_approval_changes_rate_with_trail(self):
        c = make_container(self.masters, container_no=f"REV-{frappe.generate_hash(length=6)}", rate_floor=10)
        d = make_deal(c, proposed_rate=50, qty=5)
        apply_rate_rules(d.name)
        d.reload()
        ev = frappe.get_doc(
            {
                "doctype": "Fresko Evidence",
                "evidence_type": "Note",
                "deal": d.name,
                "container": c.name,
                "notes": "rate revision evidence",
            }
        ).insert(ignore_permissions=True)
        rev = request_revision(
            d.name,
            "approved_rate",
            55,
            reason="price correction",
            supporting_evidence=ev.name,
        )
        self.assertIn("revision", rev)
        apr = frappe.get_doc(
            {
                "doctype": "Fresko Approval",
                "deal": d.name,
                "decision": "APPROVE",
                "decision_rate": 55,
                "proposed_rate": d.proposed_rate,
                "rate_floor": d.rate_floor,
                "rate_ceiling": d.rate_ceiling,
                "approver": frappe.session.user,
                "reason": "approve commercial revision",
            }
        ).insert(ignore_permissions=True)
        applied = apply_revision(rev["revision"], approval_name=apr.name)
        self.assertEqual(applied["status"], "Applied")
        self.assertEqual(applied["approval_reference"], apr.name)
        self.assertEqual(applied["supporting_evidence"], ev.name)
        d.reload()
        self.assertEqual(d.approved_rate, 55)
        trail = frappe.get_doc("Fresko Revision", rev["revision"])
        self.assertEqual(trail.approval_reference, apr.name)
        self.assertEqual(trail.supporting_evidence, ev.name)
        self.assertEqual(trail.old_value, "50.0" if trail.old_value == "50.0" else trail.old_value)
        # freeze: cannot alter historical fields after Applied
        trail.old_value = "hacked"
        with self.assertRaises(frappe.ValidationError):
            trail.save(ignore_permissions=True)

    def test_unresolved_buyer_blocks_reconciled(self):
        c = make_container(self.masters, container_no=f"BUY-{frappe.generate_hash(length=6)}", rate_floor=10)
        d = make_deal(c, proposed_rate=50, qty=5, customer=None)
        apply_rate_rules(d.name)
        d.reload()
        self.assertFalse(d.customer)
        for st in ("Outward Pending", "Dispatched", "Payment Pending", "Paid"):
            d.reload()
            d.flags.allow_status_transition = True
            d.status = st
            d.save(ignore_permissions=True)
        d.reload()
        d.flags.allow_status_transition = True
        d.status = "Reconciled"
        with self.assertRaises(frappe.ValidationError):
            d.save(ignore_permissions=True)
        ex = frappe.get_all(
            "Fresko Exception",
            filters={"deal": d.name, "exception_type": "BUYER_UNRESOLVED"},
        )
        self.assertTrue(ex)

    def test_illegal_status_transition_rejected(self):
        c = make_container(self.masters, container_no=f"IL-{frappe.generate_hash(length=6)}", rate_floor=10)
        d = make_deal(c, proposed_rate=50, qty=5)
        d.status = "Reconciled"
        with self.assertRaises(frappe.ValidationError):
            d.save()

    def test_available_to_sell_excludes_cancelled_includes_approved(self):
        c = make_container(
            self.masters,
            container_no=f"ATS-{frappe.generate_hash(length=6)}",
            inward_qty=100,
            rate_floor=10,
        )
        d1 = make_deal(c, qty=30, proposed_rate=50, buyer_alias="A1")
        apply_rate_rules(d1.name)
        d1.reload()
        self.assertIn(d1.status, ("Auto Approved", "Approved"))
        ats1 = available_to_sell(c.name, "LOT-A")
        self.assertEqual(ats1, 70)

        d2 = make_deal(c, qty=20, proposed_rate=50, buyer_alias="A2")
        apply_rate_rules(d2.name)
        cancel_deal(d2.name, cancel_reason="test cancel")
        ats2 = available_to_sell(c.name, "LOT-A")
        self.assertEqual(ats2, 70)  # cancelled excluded

        # Proposed does not reduce ATS (D3)
        d3 = make_deal(c, qty=40, proposed_rate=50, buyer_alias="A3")
        ats3 = available_to_sell(c.name, "LOT-A")
        self.assertEqual(ats3, 70)
        self.assertEqual(d3.status, "Proposed")

    def test_concurrent_deals_cannot_over_approve_lot_stock(self):
        # Soft-route second deal to Approval Required; decide(APPROVE) throws without override
        c = make_container(
            self.masters,
            container_no=f"CONC-{frappe.generate_hash(length=6)}",
            inward_qty=50,
            rate_floor=10,
        )
        d1 = make_deal(c, qty=40, proposed_rate=50, buyer_alias="C1")
        d2 = make_deal(c, qty=40, proposed_rate=50, buyer_alias="C2")
        apply_rate_rules(d1.name)
        d1.reload()
        self.assertEqual(d1.status, "Auto Approved")
        apply_rate_rules(d2.name)
        d2.reload()
        self.assertEqual(d2.status, "Approval Required")
        with self.assertRaises(frappe.ValidationError):
            decide(d2.name, "APPROVE", reason="should fail ATS")

    def test_container_fully_reconciled_blocked_with_open_exception(self):
        c = make_container(self.masters, container_no=f"CL-{frappe.generate_hash(length=6)}")
        frappe.get_doc(
            {
                "doctype": "Fresko Exception",
                "exception_type": "DATA_INTEGRITY",
                "severity": "Material",
                "status": "Open",
                "container": c.name,
                "description": "open material exception",
            }
        ).insert(ignore_permissions=True)
        c.reload()
        # Whitelist-style status moves (no db.set_value)
        for st in ("Closing", "Closed"):
            c.reload()
            c.status = st
            c.save(ignore_permissions=True)
        c.closing_status = "Fully Reconciled"
        with self.assertRaises(frappe.ValidationError):
            c.save(ignore_permissions=True)

    def test_d4_counter_requires_accept_before_approved(self):
        c = make_container(self.masters, container_no=f"D4-{frappe.generate_hash(length=6)}", rate_floor=100)
        d = make_deal(c, proposed_rate=50, qty=5)
        apply_rate_rules(d.name)
        decide(d.name, "COUNTER", decision_rate=80, reason="counter offer")
        d.reload()
        self.assertEqual(d.status, "Countered")
        self.assertEqual(d.approved_rate, 80)
        self.assertEqual(d.proposed_rate, 50)
        # F-C1: decide(APPROVE) from Countered must fail
        with self.assertRaises(frappe.ValidationError):
            decide(d.name, "APPROVE", decision_rate=80, reason="bypass")
        # Illegal: Desk jump Countered → Outward Pending
        d.reload()
        d.status = "Outward Pending"
        with self.assertRaises(frappe.ValidationError):
            d.save()
        # Accept path
        d.reload()
        result = accept_counter(d.name)
        self.assertEqual(result["status"], "Approved")

    def test_decide_rejects_from_proposed(self):
        c = make_container(self.masters, container_no=f"H2-{frappe.generate_hash(length=6)}", rate_floor=100)
        d = make_deal(c, proposed_rate=50, qty=5)
        with self.assertRaises(frappe.ValidationError):
            decide(d.name, "APPROVE", decision_rate=90, reason="skip apply_rate_rules")


def flt_status(v):
    from frappe.utils import flt
    return flt(v)
