# Copyright (c) 2026, Anubhav Dubey and contributors
"""Frappe test cases — run via: bench --site <site> run-tests --app fresko_universe

These tests expect ERPNext masters (Company, Item, UOM, Currency, Supplier).
Helpers create minimal fixtures when missing.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from fresko_universe.api import deals as deals_api
from fresko_universe.fresko_core.ats import available_to_sell


def _ensure_masters():
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        # pick any company
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
        result = deals_api.apply_approval_decision(
            deal.name, "APPROVE", decision_rate=12, reason="ok"
        )
        deal.reload()
        self.assertEqual(deal.status, "Approved")
        self.assertEqual(flt(deal.proposed_rate), 5)
        self.assertEqual(flt(deal.approved_rate), 12)
        self.assertEqual(result["approval"], deal.approval)

    def test_desk_edit_approved_rate_rejected(self):
        deal = _make_deal(self.container, rate=20)
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        deal.approved_rate = 99
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

    def test_duplicate_fingerprint_attaches_evidence_not_new_deal(self):
        d1 = _make_deal(self.container, alias="SameBuyer", qty=10, rate=20)
        with self.assertRaises(frappe.ValidationError):
            _make_deal(self.container, alias="SameBuyer", qty=10, rate=20)
        # Evidence path (manual) — create evidence linked to d1
        ev = frappe.get_doc(
            {
                "doctype": "Fresko Evidence",
                "evidence_type": "WhatsApp Message",
                "message_id": "dup-1",
                "linked_doctype": "Fresko Deal",
                "linked_name": d1.name,
                "notes": "duplicate attempt",
            }
        ).insert(ignore_permissions=True)
        ex = frappe.get_doc(
            {
                "doctype": "Fresko Exception",
                "exception_type": "DUPLICATE_MESSAGE",
                "severity": "Medium",
                "status": "Open",
                "deal": d1.name,
                "container": self.container.name,
                "description": "Duplicate fingerprint blocked second deal",
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(ev.name)
        self.assertTrue(ex.name)

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
        deals_api.transition_deal(d3.name, "Cancelled", cancel_reason="test cancel")
        ats3 = available_to_sell(self.container.name, "LOT-A")
        self.assertEqual(ats3, 70)  # cancelled excluded; d1 still 30

    def test_concurrent_deals_cannot_over_approve_lot_stock(self):
        # Two deals that together exceed inward
        d1 = _make_deal(self.container, qty=80, rate=20, alias="C1")
        d2 = _make_deal(self.container, qty=80, rate=20, alias="C2")
        deals_api.apply_rate_rules(d1.name)
        with self.assertRaises(frappe.ValidationError):
            deals_api.apply_rate_rules(d2.name)

    def test_unresolved_buyer_blocks_reconciled(self):
        deal = _make_deal(self.container, rate=20, alias="UnresolvedBuyer")
        deals_api.apply_rate_rules(deal.name)
        deal.reload()
        self.assertFalse(deal.customer)
        # force through statuses with flag for test of reconcile gate
        for st in (
            "Outward Pending",
            "Dispatched",
            "Payment Pending",
            "Paid",
        ):
            deals_api.transition_deal(deal.name, st)
        with self.assertRaises(frappe.ValidationError):
            deals_api.transition_deal(deal.name, "Reconciled")

    def test_counter_requires_accept(self):
        deal = _make_deal(self.container, rate=5, alias="CounterBuyer")
        deals_api.apply_rate_rules(deal.name)
        deals_api.apply_approval_decision(
            deal.name, "COUNTER", decision_rate=11, reason="counter"
        )
        deal.reload()
        self.assertEqual(deal.status, "Countered")
        self.assertEqual(flt(deal.approved_rate), 11)
        # ATS should NOT yet include this deal
        ats = available_to_sell(self.container.name, "LOT-A", exclude_deal=None)
        # no other approved deals
        self.assertEqual(ats, 100)
        deals_api.accept_counter(deal.name)
        deal.reload()
        self.assertEqual(deal.status, "Approved")
        self.assertEqual(available_to_sell(self.container.name, "LOT-A"), 90)

    def test_revision_plus_approval_changes_rate_with_trail(self):
        deal = _make_deal(self.container, rate=20, alias="RevBuyer")
        deals_api.apply_rate_rules(deal.name)
        rev = deals_api.request_revision(
            deal.name, "approved_rate", "18", reason="customer negotiation"
        )
        applied = deals_api.apply_revision_approval(rev["revision"], "APPROVE")
        deal.reload()
        self.assertEqual(flt(deal.approved_rate), 18)
        self.assertEqual(applied["status"], "Applied")
        self.assertTrue(
            frappe.db.exists(
                "Fresko Revision",
                {"parent_name": deal.name, "status": "Applied"},
            )
        )

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
        d1 = _make_deal(self.container, qty=100, rate=20, alias="Fill")
        deals_api.apply_rate_rules(d1.name)
        d2 = _make_deal(self.container, qty=10, rate=5, alias="Over")
        deals_api.apply_rate_rules(d2.name)
        # normal approve should fail ATS
        with self.assertRaises(frappe.ValidationError):
            deals_api.apply_approval_decision(d2.name, "APPROVE", reason="no")
        # oversell path
        result = deals_api.apply_approval_decision(
            d2.name,
            "OVERSELL_OVERRIDE",
            reason="Owner committed commercially",
            allow_oversell=1,
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
