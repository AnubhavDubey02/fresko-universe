# Copyright (c) 2026, Anubhav Dubey and contributors
"""Frappe test cases — run via: bench --site <site> run-tests --app fresko_universe

Uses live APIs: fresko_universe.deals / fresko_universe.approvals (no fresko_universe.api).
"""

from __future__ import annotations

import threading
from queue import Queue

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from fresko_universe import deals as deals_api
from fresko_universe import approvals as approvals_api
from fresko_universe.fresko_core.ats import available_to_sell


def _ensure_masters():
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        company = frappe.db.get_value("Company", {}, "name")
    if not company:
        frappe.throw("No Company found — create one before running Fresko tests")

    currency = frappe.db.get_value("Company", company, "default_currency") or "INR"
    if not frappe.db.exists("UOM", "Crate"):
        frappe.get_doc({"doctype": "UOM", "uom_name": "Crate"}).insert(ignore_permissions=True)

    if not frappe.db.exists("Item", "FRESKO-TEST-APPLE"):
        frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": "FRESKO-TEST-APPLE",
                "item_name": "Fresko Test Apple",
                "item_group": frappe.db.get_value("Item Group", {}, "name") or "All Item Groups",
                "stock_uom": "Crate",
                "is_stock_item": 1,
                "has_batch_no": 1,
            }
        ).insert(ignore_permissions=True)

    if not frappe.db.exists("Supplier", "FRESKO-TEST-SUPPLIER"):
        frappe.get_doc(
            {
                "doctype": "Supplier",
                "supplier_name": "FRESKO-TEST-SUPPLIER",
                "supplier_group": frappe.db.get_value("Supplier Group", {}, "name") or "All Supplier Groups",
            }
        ).insert(ignore_permissions=True)

    return company, currency


def _make_container(company, currency, inward=100, floor=10, ceiling=50, lot_no="LOT-A"):
    doc = frappe.get_doc(
        {
            "doctype": "Fresko Container",
            "naming_series": "CON-.YYYY.-.",
            "company": company,
            "container_no": f"TEST-{frappe.generate_hash(length=8)}",
            "supplier": "FRESKO-TEST-SUPPLIER",
            "item": "FRESKO-TEST-APPLE",
            "arrival_date": today(),
            "inward_qty": inward,
            "uom": "Crate",
            "currency": currency,
            "status": "Selling",
            "closing_status": "Open",
            "default_rate_floor": floor,
            "default_rate_ceiling": ceiling,
            "lots": [
                {
                    "lot_no": lot_no,
                    "inward_qty": inward,
                    "uom": "Crate",
                    "count_size": "16/20",
                }
            ],
        }
    )
    doc.insert(ignore_permissions=True)
    return doc


def _make_deal(container, qty=10, rate=20, alias="Buyer X", lot_no="LOT-A", **extra):
    lot_row = container.lots[0].name
    doc = frappe.get_doc(
        {
            "doctype": "Fresko Deal",
            "naming_series": "DEAL-.YYYY.-.",
            "company": container.company,
            "container": container.name,
            "buyer_alias": alias,
            "item": container.item,
            "container_lot": lot_row,
            "lot_no": lot_no,
            "qty": qty,
            "uom": container.uom,
            "proposed_rate": rate,
            "currency": container.currency,
            "status": "Proposed",
            **extra,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc


def _make_evidence(deal):
    return frappe.get_doc(
        {
            "doctype": "Fresko Evidence",
            "evidence_type": "Note",
            "deal": deal.name,
            "container": deal.container,
            "notes": "revision evidence",
        }
    ).insert(ignore_permissions=True)


def _make_revision_approval(deal, revision_name, reason="revision approved"):
    """Prefer approvals.create_revision_approval; fallback insert with revision bind."""
    from fresko_universe.approvals import create_revision_approval

    result = create_revision_approval(
        revision_name,
        "APPROVE",
        decision_rate=deal.approved_rate or deal.proposed_rate,
        reason=reason,
    )
    return frappe.get_doc("Fresko Approval", result["approval"])


class TestFreskoDeal(FrappeTestCase):
    def setUp(self):
        self.company, self.currency = _ensure_masters()
        self.container = _make_container(self.company, self.currency)

    def test_deal_rejects_lot_not_on_container(self):
        with self.assertRaises(frappe.ValidationError):
            _make_deal(self.container, lot_no="NO-SUCH-LOT")

    def test_below_floor_sets_approval_required(self):
        deal = _make_deal(self.container, rate=5)  # floor=10
        result = deals_api.apply_rate_rules(deal.name)
        self.assertEqual(result["status"], "Approval Required")
        self.assertEqual(result["approval_required"], 1)
        deal.reload()
        self.assertFalse(deal.approved_rate)

    def test_in_band_auto_approves(self):
        deal = _make_deal(self.container, rate=20)
        result = deals_api.apply_rate_rules(deal.name)
        self.assertEqual(result["status"], "Auto Approved")
        deal.reload()
        self.assertEqual(flt(deal.approved_rate), 20)

    def test_approval_sets_approved_rate_keeps_proposed_rate(self):
        deal = _make_deal(self.container, rate=5)
        deals_api.apply_rate_rules(deal.name)
        result = approvals_api.decide(
            deal.name, "APPROVE", decision_rate=12, reason="ok"
        )
        deal.reload()
        self.assertEqual(deal.status, "Approved")
        self.assertEqual(flt(deal.proposed_rate), 5)
        self.assertEqual(flt(deal.approved_rate), 12)
        self.assertEqual(result["approval"], deal.approval)

    def test_decide_rejects_from_proposed(self):
        # F-H2
        deal = _make_deal(self.container, rate=5, alias="PropSkip")
        with self.assertRaises(frappe.ValidationError):
            approvals_api.decide(deal.name, "APPROVE", decision_rate=12, reason="skip rules")

    def test_decide_cannot_approve_from_countered_must_use_accept_counter(self):
        # F-C1
        deal = _make_deal(self.container, rate=5, alias="CounterBypass")
        deals_api.apply_rate_rules(deal.name)
        approvals_api.decide(deal.name, "COUNTER", decision_rate=11, reason="counter")
        deal.reload()
        self.assertEqual(deal.status, "Countered")
        with self.assertRaises(frappe.ValidationError):
            approvals_api.decide(deal.name, "APPROVE", decision_rate=11, reason="bypass D4")
        deals_api.accept_counter(deal.name)
        deal.reload()
        self.assertEqual(deal.status, "Approved")

    def test_desk_edit_approved_rate_rejected(self):
        deal = _make_deal(self.container, rate=20)
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        deal.approved_rate = 99
        with self.assertRaises(frappe.ValidationError):
            deal.save(ignore_permissions=True)

    def test_qty_frozen_in_approval_required(self):
        # F-H4
        deal = _make_deal(self.container, rate=5, alias="FreezeAR")
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        self.assertEqual(deal.status, "Approval Required")
        deal.qty = flt(deal.qty) + 5
        with self.assertRaises(frappe.ValidationError):
            deal.save(ignore_permissions=True)

    def test_illegal_status_transition_rejected(self):
        deal = _make_deal(self.container, rate=20)
        deal.status = "Reconciled"
        with self.assertRaises(frappe.ValidationError):
            deal.save(ignore_permissions=True)

    def test_duplicate_message_id_does_not_create_second_deal(self):
        d1 = _make_deal(self.container, alias="A-unique-1", source_message_id="wa-msg-1")
        with self.assertRaises(frappe.ValidationError):
            _make_deal(
                self.container,
                alias="A-unique-2",
                source_message_id="wa-msg-1",
            )
        self.assertTrue(d1.name)

    def test_available_to_sell_excludes_cancelled_includes_approved(self):
        d1 = _make_deal(self.container, qty=30, rate=20, alias="ATS1")
        deals_api.apply_rate_rules(d1.name)
        ats = available_to_sell(self.container.name, "LOT-A")
        self.assertEqual(ats, 70)  # 100-30

        d2 = _make_deal(self.container, qty=10, rate=5, alias="ATS2")
        deals_api.apply_rate_rules(d2.name)
        # still Approval Required — must NOT reduce ATS
        ats2 = available_to_sell(self.container.name, "LOT-A")
        self.assertEqual(ats2, 70)

        d3 = _make_deal(self.container, qty=20, rate=20, alias="ATS3")
        deals_api.apply_rate_rules(d3.name)
        deals_api.cancel_deal(d3.name, cancel_reason="test cancel")
        ats3 = available_to_sell(self.container.name, "LOT-A")
        self.assertEqual(ats3, 70)  # cancelled excluded; d1 still 30

    def test_concurrent_deals_soft_route_then_approve_throws(self):
        # Controls B3: soft-route to Approval Required, then decide APPROVE throws without override
        d1 = _make_deal(self.container, qty=80, rate=20, alias="C1")
        d2 = _make_deal(self.container, qty=80, rate=20, alias="C2")
        deals_api.apply_rate_rules(d1.name)
        d1.reload()
        self.assertEqual(d1.status, "Auto Approved")
        deals_api.apply_rate_rules(d2.name)
        d2.reload()
        self.assertEqual(d2.status, "Approval Required")
        with self.assertRaises(frappe.ValidationError):
            approvals_api.decide(d2.name, "APPROVE", reason="should fail ATS")

    def test_unresolved_buyer_blocks_reconciled(self):
        deal = _make_deal(self.container, rate=20, alias="UnresolvedBuyer")
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        if deal.status == "Approval Required":
            approvals_api.decide(
                deal.name, "APPROVE", decision_rate=deal.proposed_rate, reason="test advance"
            )
            deal.reload()
        self.assertIn(deal.status, ("Auto Approved", "Approved"))
        self.assertFalse(deal.customer)
        for st in (
            "Outward Pending",
            "Dispatched",
            "Payment Pending",
            "Paid",
        ):
            deal.reload()
            deal.flags.allow_status_transition = True
            deal.status = st
            deal.save(ignore_permissions=True)
        deal.reload()
        deal.flags.allow_status_transition = True
        deal.status = "Reconciled"
        with self.assertRaises(frappe.ValidationError):
            deal.save(ignore_permissions=True)

    def test_counter_requires_accept(self):
        deal = _make_deal(self.container, rate=5, alias="CounterBuyer")
        deals_api.apply_rate_rules(deal.name)
        approvals_api.decide(
            deal.name, "COUNTER", decision_rate=11, reason="counter"
        )
        deal.reload()
        self.assertEqual(deal.status, "Countered")
        # RC: Countered must not set approved_rate; amount uses proposed_rate
        self.assertFalse(deal.approved_rate)
        self.assertEqual(flt(deal.amount), flt(deal.qty) * flt(deal.proposed_rate))
        ats = available_to_sell(self.container.name, "LOT-A", exclude_deal=None)
        self.assertEqual(ats, 100)
        deals_api.accept_counter(deal.name)
        deal.reload()
        self.assertEqual(deal.status, "Approved")
        self.assertEqual(flt(deal.approved_rate), 11)
        self.assertEqual(available_to_sell(self.container.name, "LOT-A"), 90)

    def test_accept_counter_empty_customer_opens_buyer_unresolved(self):
        """D6: Countered→Approved via accept_counter must open BUYER_UNRESOLVED when customer empty."""
        deal = _make_deal(self.container, rate=5, alias="D6EmptyCust")
        self.assertFalse(deal.customer)
        deals_api.apply_rate_rules(deal.name)
        approvals_api.decide(
            deal.name, "COUNTER", decision_rate=11, reason="counter"
        )
        deal.reload()
        self.assertEqual(deal.status, "Countered")
        before = frappe.get_all(
            "Fresko Exception",
            filters={
                "deal": deal.name,
                "exception_type": "BUYER_UNRESOLVED",
                "status": ("in", ["Open", "In Progress"]),
            },
        )
        self.assertFalse(before)
        deals_api.accept_counter(deal.name)
        deal.reload()
        self.assertEqual(deal.status, "Approved")
        self.assertFalse(deal.customer)
        ex = frappe.get_all(
            "Fresko Exception",
            filters={
                "deal": deal.name,
                "exception_type": "BUYER_UNRESOLVED",
                "status": ("in", ["Open", "In Progress"]),
            },
        )
        self.assertTrue(ex, "accept_counter must open BUYER_UNRESOLVED when customer empty (D6)")

    def test_accept_counter_with_customer_no_buyer_unresolved(self):
        """D6: accept_counter with customer set must not open BUYER_UNRESOLVED."""
        if not frappe.db.exists("Customer", "FRESKO-TEST-CUSTOMER"):
            group = frappe.db.get_value("Customer Group", {}, "name") or "All Customer Groups"
            frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": "FRESKO-TEST-CUSTOMER",
                    "customer_group": group,
                    "territory": frappe.db.get_value("Territory", {}, "name") or "All Territories",
                }
            ).insert(ignore_permissions=True)
        deal = _make_deal(
            self.container, rate=5, alias="D6WithCust", customer="FRESKO-TEST-CUSTOMER"
        )
        self.assertEqual(deal.customer, "FRESKO-TEST-CUSTOMER")
        deals_api.apply_rate_rules(deal.name)
        approvals_api.decide(
            deal.name, "COUNTER", decision_rate=11, reason="counter"
        )
        deal.reload()
        self.assertEqual(deal.status, "Countered")
        deals_api.accept_counter(deal.name)
        deal.reload()
        self.assertEqual(deal.status, "Approved")
        self.assertEqual(deal.customer, "FRESKO-TEST-CUSTOMER")
        ex = frappe.get_all(
            "Fresko Exception",
            filters={"deal": deal.name, "exception_type": "BUYER_UNRESOLVED"},
        )
        self.assertFalse(ex, "accept_counter must not open BUYER_UNRESOLVED when customer set")

    def test_revision_plus_approval_changes_rate_with_trail(self):
        deal = _make_deal(self.container, rate=20, alias="RevBuyer")
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        ev = _make_evidence(deal)
        rev = deals_api.request_revision(
            deal.name,
            "approved_rate",
            "18",
            reason="customer negotiation",
            supporting_evidence=ev.name,
        )
        apr = _make_revision_approval(deal, rev["revision"], reason="approve rate revision")
        applied = deals_api.apply_revision(rev["revision"], approval_name=apr.name)
        deal.reload()
        self.assertEqual(flt(deal.approved_rate), 18)
        self.assertEqual(applied["status"], "Applied")
        self.assertEqual(applied["approval_reference"], apr.name)
        self.assertEqual(applied["supporting_evidence"], ev.name)
        trail = frappe.get_doc("Fresko Revision", rev["revision"])
        self.assertEqual(trail.status, "Applied")
        self.assertEqual(trail.approval_reference, apr.name)
        self.assertEqual(trail.supporting_evidence, ev.name)

    def test_qty_revision_requires_approval_document(self):
        deal = _make_deal(self.container, rate=20, alias="RevQty")
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        ev = _make_evidence(deal)
        rev = deals_api.request_revision(
            deal.name, "qty", "8", reason="qty cut", supporting_evidence=ev.name
        )
        with self.assertRaises(frappe.ValidationError):
            deals_api.apply_revision(rev["revision"])  # no approval_reference

    def test_container_fully_reconciled_blocked_with_open_exception(self):
        frappe.get_doc(
            {
                "doctype": "Fresko Exception",
                "exception_type": "DATA_INTEGRITY",
                "severity": "High",
                "status": "Open",
                "container": self.container.name,
                "description": "open blocker",
            }
        ).insert(ignore_permissions=True)
        self.container.status = "Closing"
        self.container.save(ignore_permissions=True)
        self.container.status = "Closed"
        self.container.save(ignore_permissions=True)
        self.container.closing_status = "Fully Reconciled"
        with self.assertRaises(frappe.ValidationError):
            self.container.save(ignore_permissions=True)

    def test_oversell_override_creates_exception(self):
        # D10: System Manager (Administrator) may override; Approver alone cannot
        d1 = _make_deal(self.container, qty=100, rate=20, alias="Fill")
        deals_api.apply_rate_rules(d1.name)
        d2 = _make_deal(self.container, qty=10, rate=5, alias="Over")
        deals_api.apply_rate_rules(d2.name)
        with self.assertRaises(frappe.ValidationError):
            approvals_api.decide(d2.name, "APPROVE", reason="no")
        result = approvals_api.decide(
            d2.name,
            "OVERSELL_OVERRIDE",
            reason="Owner committed commercially",
            oversell_override=1,
        )
        d2.reload()
        self.assertEqual(d2.status, "Approved")
        self.assertTrue(
            frappe.db.exists(
                "Fresko Exception",
                {"deal": d2.name, "exception_type": "OVERSELL_OVERRIDE"},
            )
        )
        self.assertTrue(result["approval"])

    def test_lot_inward_cannot_drop_below_approved_sold(self):
        # F-H1
        deal = _make_deal(self.container, qty=80, rate=20, alias="InwardFloor")
        deals_api.apply_rate_rules(deal.name)
        self.container.reload()
        self.container.flags.inward_qty_change_reason = "test shrink"
        self.container.inward_qty = 50
        self.container.lots[0].inward_qty = 50
        with self.assertRaises(frappe.ValidationError):
            self.container.save(ignore_permissions=True)

    def test_dispatched_qty_desk_edit_rejected(self):
        deal = _make_deal(self.container, rate=20, alias="DispLock")
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        deal.dispatched_qty = 5
        with self.assertRaises(frappe.ValidationError):
            deal.save(ignore_permissions=True)

    def test_concurrent_dispatches_cannot_exceed_lot_inward(self):
        """D10: independent transactions serialize before the physical ceiling read."""
        d1 = _make_deal(self.container, qty=60, rate=20, alias="DispatchRaceA")
        deals_api.apply_rate_rules(d1.name)
        d2 = _make_deal(self.container, qty=60, rate=5, alias="DispatchRaceB")
        deals_api.apply_rate_rules(d2.name)
        approvals_api.decide(
            d2.name,
            "OVERSELL_OVERRIDE",
            reason="test setup: commercial oversell only",
            oversell_override=1,
        )
        frappe.db.commit()  # make setup visible to the two independent connections

        deal_names = [d1.name, d2.name]

        def cleanup_committed_rows():
            frappe.set_user("Administrator")
            frappe.db.rollback()
            for doctype in (
                "Fresko Approval",
                "Fresko Evidence",
                "Fresko Exception",
            ):
                frappe.db.delete(doctype, {"deal": ("in", deal_names)})
            frappe.db.delete(
                "Fresko Revision", {"parent_name": ("in", deal_names)}
            )
            frappe.db.delete("Fresko Deal", {"name": ("in", deal_names)})
            frappe.db.delete("Fresko Container Lot", {"parent": self.container.name})
            frappe.db.delete("Fresko Container", {"name": self.container.name})
            frappe.db.commit()

        self.addCleanup(cleanup_committed_rows)

        site = frappe.local.site
        barrier = threading.Barrier(2)
        outcomes = Queue()

        def dispatch_worker(deal_name):
            frappe.init(site=site)
            frappe.connect()
            frappe.set_user("Administrator")
            try:
                barrier.wait(timeout=20)
                deals_api.record_dispatch(deal_name, 60)
                outcomes.put((deal_name, "OK", ""))
            except Exception as exc:
                frappe.db.rollback()
                outcomes.put((deal_name, "DENIED", str(exc)))
            finally:
                frappe.destroy()

        workers = [
            threading.Thread(target=dispatch_worker, args=(d1.name,)),
            threading.Thread(target=dispatch_worker, args=(d2.name,)),
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        self.assertFalse(any(worker.is_alive() for worker in workers), "dispatch worker hung")

        results = [outcomes.get_nowait(), outcomes.get_nowait()]
        self.assertEqual([r[1] for r in results].count("OK"), 1, results)
        self.assertEqual([r[1] for r in results].count("DENIED"), 1, results)
        denied = next(r for r in results if r[1] == "DENIED")
        self.assertIn("Physical dispatch ceiling", denied[2])

        # End the main connection's old snapshot before reading worker commits.
        frappe.db.rollback()
        dispatched = frappe.get_all(
            "Fresko Deal",
            filters={"name": ("in", [d1.name, d2.name])},
            pluck="dispatched_qty",
        )
        self.assertEqual(sum(flt(value) for value in dispatched), 60)

    def test_concurrent_apply_revision_consumes_approval_once(self):
        """Independent transactions: exactly one worker may apply a Pending Revision."""
        deal = _make_deal(self.container, rate=20, alias="RevisionRace")
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        ev = _make_evidence(deal)
        rev = deals_api.request_revision(
            deal.name,
            "approved_rate",
            "19",
            reason="concurrent consume",
            supporting_evidence=ev.name,
        )
        apr = _make_revision_approval(deal, rev["revision"], reason="single-use approval")
        frappe.db.commit()

        def cleanup_committed_rows():
            frappe.set_user("Administrator")
            frappe.db.rollback()
            frappe.db.delete("Fresko Approval", {"deal": deal.name})
            frappe.db.delete("Fresko Revision", {"parent_name": deal.name})
            frappe.db.delete("Fresko Evidence", {"deal": deal.name})
            frappe.db.delete("Fresko Exception", {"deal": deal.name})
            frappe.db.delete("Fresko Deal", {"name": deal.name})
            frappe.db.delete("Fresko Container Lot", {"parent": self.container.name})
            frappe.db.delete("Fresko Container", {"name": self.container.name})
            frappe.db.commit()

        self.addCleanup(cleanup_committed_rows)

        site = frappe.local.site
        barrier = threading.Barrier(2)
        outcomes = Queue()

        def apply_worker():
            frappe.init(site=site)
            frappe.connect()
            frappe.set_user("Administrator")
            try:
                barrier.wait(timeout=20)
                deals_api.apply_revision(rev["revision"], approval_name=apr.name)
                outcomes.put(("OK", ""))
            except Exception as exc:
                frappe.db.rollback()
                outcomes.put(("DENIED", str(exc)))
            finally:
                frappe.destroy()

        workers = [threading.Thread(target=apply_worker) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        self.assertFalse(any(worker.is_alive() for worker in workers), "revision worker hung")

        results = [outcomes.get_nowait(), outcomes.get_nowait()]
        self.assertEqual([r[0] for r in results].count("OK"), 1, results)
        self.assertEqual([r[0] for r in results].count("DENIED"), 1, results)
        self.assertIn("not Pending", next(r[1] for r in results if r[0] == "DENIED"))

        frappe.db.rollback()
        self.assertEqual(
            frappe.db.get_value("Fresko Revision", rev["revision"], "status"),
            "Applied",
        )
        self.assertEqual(
            int(frappe.db.get_value("Fresko Approval", apr.name, "consumed") or 0),
            1,
        )


    def test_gate1_no_rate_rule_rate_policy_missing(self):
        """Gate 1: no applicable floor/rule → Approval Required + RATE_POLICY_MISSING."""
        company, currency = _ensure_masters()
        c = _make_container(company, currency, inward=100, floor=None, ceiling=None)
        # Clear defaults if Currency None coerced
        c.default_rate_floor = None
        c.default_rate_ceiling = None
        c.save(ignore_permissions=True)
        deal = _make_deal(c, rate=50, alias="NoPolicy")
        result = deals_api.apply_rate_rules(deal.name)
        self.assertEqual(result["status"], "Approval Required")
        deal.reload()
        # Gate 1: approved_rate / floor / ceiling must stay unset (NULL, not 0.0)
        self.assertFalse(deal.approved_rate)
        self.assertIsNone(deal.rate_floor)
        self.assertIsNone(deal.rate_ceiling)
        self.assertEqual(flt(deal.proposed_rate), 50)
        self.assertTrue(
            frappe.db.exists(
                "Fresko Exception",
                {"deal": deal.name, "exception_type": "RATE_POLICY_MISSING"},
            )
        )

    def test_gate1_mismatched_count_size_no_default_policy_missing(self):
        company, currency = _ensure_masters()
        c = _make_container(company, currency, inward=100, floor=None, ceiling=None)
        c.default_rate_floor = None
        c.default_rate_ceiling = None
        c.append("rate_rules", {"count_size": "32/36", "rate_floor": 90, "rate_ceiling": 140})
        c.save(ignore_permissions=True)
        deal = _make_deal(c, rate=100, alias="MismatchCS")
        # deal count_size from lot is 16/20 — no match
        result = deals_api.apply_rate_rules(deal.name)
        self.assertEqual(result["status"], "Approval Required")
        self.assertTrue(
            frappe.db.exists(
                "Fresko Exception",
                {"deal": deal.name, "exception_type": "RATE_POLICY_MISSING"},
            )
        )

    def test_gate1_lot_override_auto_approves_in_band(self):
        company, currency = _ensure_masters()
        c = _make_container(company, currency, inward=100, floor=100, ceiling=200)
        c.lots[0].rate_floor_override = 80
        c.lots[0].rate_ceiling_override = 150
        c.save(ignore_permissions=True)
        deal = _make_deal(c, rate=85, alias="LotOv")
        result = deals_api.apply_rate_rules(deal.name)
        self.assertEqual(result["status"], "Auto Approved")
        deal.reload()
        self.assertEqual(flt(deal.rate_floor), 80)
        self.assertEqual(flt(deal.approved_rate), 85)

    def test_system_manager_cannot_accept_counter_unless_owner(self):
        """D4: SM who is not owner/salesperson cannot accept_counter."""
        deal = _make_deal(self.container, rate=5, alias="D4SM")
        deals_api.apply_rate_rules(deal.name)
        approvals_api.decide(deal.name, "COUNTER", decision_rate=11, reason="counter")
        deal.reload()
        # Test-only ACL fixture (DV9: db.set_value residual — not a production path)
        frappe.db.set_value("Fresko Deal", deal.name, "owner", "Guest")
        frappe.db.set_value("Fresko Deal", deal.name, "salesperson_user", None)
        deal.reload()
        # Administrator is System Manager but not owner → must throw
        with self.assertRaises(frappe.ValidationError):
            deals_api.accept_counter(deal.name)


    def test_countered_approved_rate_null_until_accept(self):
        """RC: COUNTER stores decision_rate on Approval; Deal.approved_rate None until accept."""
        deal = _make_deal(self.container, rate=5, alias="RCCounterNull")
        deals_api.apply_rate_rules(deal.name)
        result = approvals_api.decide(
            deal.name, "COUNTER", decision_rate=11.5, reason="counter null rate"
        )
        deal.reload()
        self.assertEqual(deal.status, "Countered")
        self.assertIsNone(deal.approved_rate)
        self.assertEqual(flt(result["decision_rate"]), 11.5)
        self.assertFalse(result["approved_rate"])
        self.assertEqual(flt(deal.amount), flt(deal.qty) * 5)
        apr = frappe.get_doc("Fresko Approval", result["approval"])
        self.assertEqual(apr.decision, "COUNTER")
        self.assertEqual(flt(apr.decision_rate), 11.5)
        deals_api.accept_counter(deal.name)
        deal.reload()
        self.assertEqual(deal.status, "Approved")
        self.assertEqual(flt(deal.approved_rate), 11.5)
        self.assertEqual(flt(deal.amount), flt(deal.qty) * 11.5)

    def test_cancelled_after_approved_blocks_direct_qty_edit(self):
        deal = _make_deal(self.container, rate=20, alias="LockCancelQty")
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        deals_api.cancel_deal(deal.name, cancel_reason="buyer backed out")
        deal.reload()
        self.assertEqual(deal.status, "Cancelled")
        deal.qty = flt(deal.qty) + 1
        with self.assertRaises(frappe.ValidationError):
            deal.save(ignore_permissions=True)

    def test_cancelled_blocks_direct_lot_customer_container(self):
        deal = _make_deal(self.container, rate=20, alias="LockCancelLot")
        deals_api.apply_rate_rules(deal.name)
        deals_api.cancel_deal(deal.name, cancel_reason="cancel freeze")
        deal.reload()
        for field, value in (
            ("lot_no", "NOPE"),
            ("customer", "SOME-CUST"),
            ("container", "NOPE-CON"),
        ):
            deal.reload()
            setattr(deal, field, value)
            with self.assertRaises(frappe.ValidationError):
                deal.save(ignore_permissions=True)

    def test_rejected_blocks_direct_commercial_edit(self):
        deal = _make_deal(self.container, rate=5, alias="LockReject")
        deals_api.apply_rate_rules(deal.name)
        approvals_api.decide(deal.name, "REJECT", reason="no deal")
        deal.reload()
        self.assertEqual(deal.status, "Rejected")
        deal.qty = flt(deal.qty) + 2
        with self.assertRaises(frappe.ValidationError):
            deal.save(ignore_permissions=True)
        deal.reload()
        deal.proposed_rate = 99
        with self.assertRaises(frappe.ValidationError):
            deal.save(ignore_permissions=True)

    def test_disputed_blocks_direct_commercial_edit(self):
        deal = _make_deal(self.container, rate=20, alias="LockDispute")
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        deal.flags.allow_status_transition = True
        deal.status = "Disputed"
        deal.save(ignore_permissions=True)
        deal.reload()
        self.assertEqual(deal.status, "Disputed")
        deal.qty = flt(deal.qty) + 1
        with self.assertRaises(frappe.ValidationError):
            deal.save(ignore_permissions=True)

    def test_apply_revision_still_succeeds_with_revision_bound_approval(self):
        deal = _make_deal(self.container, rate=20, alias="RevBoundOk")
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        ev = _make_evidence(deal)
        rev = deals_api.request_revision(
            deal.name,
            "approved_rate",
            "17",
            reason="legit revision",
            supporting_evidence=ev.name,
        )
        apr = _make_revision_approval(deal, rev["revision"], reason="approve bound")
        applied = deals_api.apply_revision(rev["revision"], approval_name=apr.name)
        deal.reload()
        self.assertEqual(flt(deal.approved_rate), 17)
        self.assertEqual(applied["status"], "Applied")
        apr.reload()
        self.assertEqual(int(apr.consumed or 0), 1)

    def test_apply_revision_rejects_deal_only_unbound_approval(self):
        deal = _make_deal(self.container, rate=20, alias="RevUnbound")
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        ev = _make_evidence(deal)
        rev = deals_api.request_revision(
            deal.name,
            "approved_rate",
            "16",
            reason="needs revision bind",
            supporting_evidence=ev.name,
        )
        # Deal-only Approval (no revision link) — must fail
        apr = frappe.get_doc(
            {
                "doctype": "Fresko Approval",
                "deal": deal.name,
                "decision": "APPROVE",
                "decision_rate": 16,
                "proposed_rate": deal.proposed_rate,
                "rate_floor": deal.rate_floor,
                "rate_ceiling": deal.rate_ceiling,
                "approver": frappe.session.user,
                "reason": "unbound deal-only",
            }
        )
        apr.flags.allow_controlled_insert = True  # simulate legacy unbound Approval
        apr.insert(ignore_permissions=True)
        with self.assertRaises(frappe.PermissionError):
            deals_api.apply_revision(rev["revision"], approval_name=apr.name)

    def test_apply_revision_rejects_mismatched_revision_bind(self):
        deal = _make_deal(self.container, rate=20, alias="RevMismatch")
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        ev = _make_evidence(deal)
        rev1 = deals_api.request_revision(
            deal.name, "approved_rate", "15", reason="r1", supporting_evidence=ev.name
        )
        rev2 = deals_api.request_revision(
            deal.name, "qty", "8", reason="r2", supporting_evidence=ev.name
        )
        apr = _make_revision_approval(deal, rev1["revision"], reason="bound to rev1")
        with self.assertRaises(frappe.PermissionError):
            deals_api.apply_revision(rev2["revision"], approval_name=apr.name)

    def test_apply_revision_replay_consumed_fails(self):
        deal = _make_deal(self.container, rate=20, alias="RevReplay")
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        ev = _make_evidence(deal)
        rev = deals_api.request_revision(
            deal.name,
            "approved_rate",
            "14",
            reason="first apply",
            supporting_evidence=ev.name,
        )
        apr = _make_revision_approval(deal, rev["revision"], reason="consume me")
        deals_api.apply_revision(rev["revision"], approval_name=apr.name)
        # Second Pending revision trying to reuse consumed Approval
        rev2 = deals_api.request_revision(
            deal.name,
            "approved_rate",
            "13",
            reason="replay",
            supporting_evidence=ev.name,
        )
        with self.assertRaises(frappe.PermissionError):
            deals_api.apply_revision(rev2["revision"], approval_name=apr.name)

    def test_apply_revision_stale_old_value_fails(self):
        deal = _make_deal(self.container, rate=20, alias="RevStale")
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        ev = _make_evidence(deal)
        rev = deals_api.request_revision(
            deal.name,
            "approved_rate",
            "19",
            reason="stale check",
            supporting_evidence=ev.name,
        )
        apr = _make_revision_approval(deal, rev["revision"], reason="stale")
        # Drift deal field under commercial revision flag before apply
        deal.flags.allow_commercial_revision = True
        deal.flags.allow_approval_write = True
        deal.approved_rate = 18
        deal.save(ignore_permissions=True)
        with self.assertRaises(frappe.ValidationError):
            deals_api.apply_revision(rev["revision"], approval_name=apr.name)

    def test_decide_oversell_rolls_back_when_deal_save_fails(self):
        """Atomicity: Exception+Approval must not remain if path errors before commit.

        Injects after Approval insert (OVERSELL opens Exception first). Uses a DB
        savepoint rollback to emulate request-abort before decide()'s frappe.db.commit().
        Harness limit: does not simulate crash after an explicit commit has succeeded.
        """
        d1 = _make_deal(self.container, qty=100, rate=20, alias="AtomFill")
        deals_api.apply_rate_rules(d1.name)
        d2 = _make_deal(self.container, qty=10, rate=5, alias="AtomOver")
        deals_api.apply_rate_rules(d2.name)
        d2.reload()
        self.assertEqual(d2.status, "Approval Required")

        from fresko_universe import approvals as approvals_mod

        real_insert = approvals_mod._insert_approval

        def insert_then_fail(*args, **kwargs):
            ap = real_insert(*args, **kwargs)
            raise RuntimeError("forced failure after Approval insert")

        before_ex = frappe.db.count("Fresko Exception", {"deal": d2.name})
        before_ap = frappe.db.count("Fresko Approval", {"deal": d2.name})
        frappe.db.savepoint("fresko_atomicity_probe")
        approvals_mod._insert_approval = insert_then_fail
        try:
            with self.assertRaises(RuntimeError):
                approvals_api.decide(
                    d2.name,
                    "OVERSELL_OVERRIDE",
                    reason="atomicity probe",
                    oversell_override=1,
                )
        finally:
            approvals_mod._insert_approval = real_insert
            frappe.db.rollback(save_point="fresko_atomicity_probe")

        d2.reload()
        self.assertEqual(d2.status, "Approval Required")
        self.assertEqual(
            frappe.db.count("Fresko Approval", {"deal": d2.name}),
            before_ap,
        )
        self.assertEqual(
            frappe.db.count("Fresko Exception", {"deal": d2.name}),
            before_ex,
        )
