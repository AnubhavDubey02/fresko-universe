# Copyright (c) 2026, Anubhav Dubey and contributors
"""Frappe test cases — run via: bench --site <site> run-tests --app fresko_universe

Uses live APIs: fresko_universe.deals / fresko_universe.approvals (no fresko_universe.api).
"""

from __future__ import annotations

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


def _make_revision_approval(deal, reason="revision approved"):
    return frappe.get_doc(
        {
            "doctype": "Fresko Approval",
            "deal": deal.name,
            "decision": "APPROVE",
            "decision_rate": deal.approved_rate or deal.proposed_rate,
            "proposed_rate": deal.proposed_rate,
            "rate_floor": deal.rate_floor,
            "rate_ceiling": deal.rate_ceiling,
            "approver": frappe.session.user,
            "reason": reason,
        }
    ).insert(ignore_permissions=True)


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
        self.assertEqual(flt(deal.approved_rate), 11)
        ats = available_to_sell(self.container.name, "LOT-A", exclude_deal=None)
        self.assertEqual(ats, 100)
        deals_api.accept_counter(deal.name)
        deal.reload()
        self.assertEqual(deal.status, "Approved")
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
        apr = _make_revision_approval(deal, reason="approve rate revision")
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

