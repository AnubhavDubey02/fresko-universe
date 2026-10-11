"""FR-QA-001/012 actual-source regressions, with mocked Frappe persistence.

These establish projection contracts, not real permission/transaction claims.
Native maker A/B and concurrent writers remain pinned Bench acceptance gates.
"""
import copy
import json
import sys
import unittest
from datetime import datetime
from decimal import Decimal

from tests.test_commercial_version_contract import _subject, PermissionError


class Doc(dict):
    def __getattr__(self, key):
        return self.get(key)


class TestPhysicalCapacityContract(unittest.TestCase):
    def setUp(self):
        self.frappe, self.service, _, _, original = _subject()
        def restore():
            for name, value in original.items():
                if value is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = value
        self.addCleanup(restore)
        self.company = Doc(name="ACME")
        self.container = Doc(name="CON-1", company="ACME")
        self.physical = Doc(name="OUT-1", company="ACME", container="CON-1", status="Posted",
                            movement_type="OUTWARD", posted_at="2026-10-01 12:00:00",
                            movement_at="2026-10-01 11:00:00",
                            lines=[Doc(line_key="L1", qty="100", uom="BOX")])
        self.sale = Doc(name="HIDDEN-SALE", company="ACME", container="CON-1")
        self.allocations = []
        self.reversals = []
        self.sale_visible = False
        self.queries = []
        self.frappe.get_doc = self.get_doc
        self.frappe.db.exists = lambda doctype, name: True
        self.frappe.db.sql = self.sql
        self.frappe.get_list = lambda *args, **kwargs: []  # Reader sees NO allocations.
        self.service.permissions.outward_has_permission = lambda *args, **kwargs: True
        self.service.commercial_has_permission = lambda doc: self.sale_visible
        self.service._sale_projection = lambda *args, **kwargs: self.sale_view()
        self.service.get_sale_as_of = lambda *args, **kwargs: self.sale_view()

    def get_doc(self, doctype, name, **kwargs):
        if doctype == self.service.ALLOCATION:
            return next(row for row in self.allocations if row.name == name)
        return {"Company": self.company, "Fresko Container": self.container,
                "Fresko Outward": self.physical, self.service.SALE: self.sale}[doctype]

    def sql(self, query, args=(), **kwargs):
        self.queries.append((query, args))
        if "tabFresko Sale Outward Allocation" in query:
            if "SELECT DISTINCT sale" in query:
                return [Doc(sale=self.sale.name)] if self.allocations else []
            self.assertEqual(args, ("ACME", "CON-1", "OUT-1"))
            self.assertIn("FOR UPDATE", query)
            return [Doc(name=row.name) for row in self.allocations]
        if "tabFresko Commercial Sale" in query:
            return [Doc(name=self.sale.name)] if self.allocations else []
        if "tabFresko Outward" in query:
            return self.reversals if "reverses_outward" in query else [Doc(name=self.physical.name)]
        if "tabFresko Container" in query:
            return [Doc(company="ACME")]
        if "tabCompany" in query:
            return []
        self.fail("Unexpected query: " + query)

    def allocation(self, qty="100", state="APPROVED", **changes):
        row = Doc(name="HIDDEN-ALLOC-" + str(len(self.allocations)), doctype=self.service.ALLOCATION,
                  company="ACME", container="CON-1", outward="OUT-1", outward_line_key="L1",
                  sale=self.sale.name, sale_line_key="S1", qty=qty, uom="BOX", state=state,
                  reversed_by=None, decision_history="[]", creation="2026-10-02 10:00:00")
        row.update(changes)
        self.allocations.append(row)
        return row

    def sale_view(self):
        qty = sum((Decimal(row.qty) for row in self.allocations if row.state == "APPROVED"), Decimal(0))
        return {"exists": True, "name": self.sale.name, "sale_at": "2026-10-01 10:00:00",
                "status": "APPROVED", "customer": "CUSTOMER-1", "currency": "INR",
                "reconciliation_state": "CONFIRMED",
                "lines": [{"line_key": "S1", "uom": "BOX", "qty": "100", "qty_state": "KNOWN",
                           "allocated_qty": str(qty), "price_state": "FINAL", "rate": "2",
                           "amount": "200", "rate_basis": "RATE_ASSERTION", "lot_state": "KNOWN"}],
                "allocations": [{"name": row.name, "outward": row.outward, "outward_line_key": row.outward_line_key,
                                 "sale_line_key": row.sale_line_key, "qty": row.qty, "uom": row.uom} for row in self.allocations if row.state == "APPROVED"]}

    def test_hidden_sale_and_allocation_consume_in_both_commercial_paths(self):
        self.allocation()
        before = copy.deepcopy((self.physical, self.allocations))
        container = self.service.get_container_reconciliation("CON-1")
        outward = self.service.get_outward_reconciliation("OUT-1")
        self.assertEqual(container["totals_by_uom"]["BOX"]["physically_unallocated_qty"], "0")
        self.assertEqual(container["totals_by_uom"]["BOX"]["physically_allocated_qty"], "100")
        self.assertEqual(outward["lines"][0]["remaining_qty"], "0")
        self.assertEqual(outward["allocations"], [])
        self.assertEqual(outward["linked_sales"], [])
        self.assertNotEqual(outward["reconciliation_state"], "CONFIRMED")
        for result in (container, outward):
            self.assertNotIn("HIDDEN-SALE", json.dumps(result))
            self.assertNotIn("HIDDEN-ALLOC", json.dumps(result))
        self.assertEqual(before, (self.physical, self.allocations))

    def test_zero_partial_full_and_reversed_controls(self):
        for qty, state, remaining in [(None, None, "100"), ("40", "APPROVED", "60"),
                                      ("100", "APPROVED", "0"), ("100", "REVERSED", "100")]:
            with self.subTest(qty=qty, state=state):
                self.allocations.clear()
                if qty is not None:
                    self.allocation(qty, state)
                result = self.service.get_outward_capacity("OUT-1", "ACME")
                self.assertEqual(result["lines"][0]["remaining_qty"], remaining)

    def test_visible_details_do_not_change_physical_totals(self):
        self.allocation()
        hidden = self.service.get_outward_reconciliation("OUT-1")
        self.sale_visible = True
        visible = self.service.get_outward_reconciliation("OUT-1")
        self.assertEqual(hidden["totals_by_uom"], visible["totals_by_uom"])
        self.assertEqual(visible["allocations"][0]["name"], self.allocations[0].name)

    def test_frappe_sale_user_permission_redacts_details_without_releasing_stock(self):
        self.allocation()
        self.sale_visible = True
        self.frappe.has_permission = lambda doctype, *args, **kwargs: doctype != self.service.SALE
        result = self.service.get_outward_reconciliation("OUT-1")
        self.assertEqual(result["lines"][0]["remaining_qty"], "0")
        self.assertEqual(result["linked_sales"], [])
        self.assertNotIn(self.sale.name, str(result))

    def test_historical_reversal_preserves_earlier_consumption(self):
        row = self.allocation(state="REVERSED", reversed_by="checker")
        row.decision_history = json.dumps([
            {"recorded_at": "2026-10-02 10:00:00", "snapshot": {"state": "APPROVED", "reversed_by": None}},
            {"recorded_at": "2026-10-03 10:00:00", "snapshot": {"state": "REVERSED", "reversed_by": "checker"}},
        ])
        early = self.service.get_outward_reconciliation("OUT-1", "2026-10-02 12:00:00")
        later = self.service.get_outward_reconciliation("OUT-1", "2026-10-03 12:00:00")
        self.assertEqual(early["lines"][0]["remaining_qty"], "0")
        self.assertEqual(later["lines"][0]["remaining_qty"], "100")

    def test_historical_preapproval_does_not_consume(self):
        row = self.allocation()
        row["creation"] = "2026-10-03 10:00:00"
        row.decision_history = json.dumps([{"recorded_at": "2026-10-03 10:00:00", "snapshot": {"state": "APPROVED"}}])
        result = self.service.get_outward_reconciliation("OUT-1", "2026-10-02 12:00:00")
        self.assertEqual(result["lines"][0]["remaining_qty"], "100")

    def test_missing_historical_decisions_never_release_stock(self):
        self.allocation()
        result = self.service.get_outward_reconciliation("OUT-1", "2026-10-03 12:00:00")
        self.assertEqual(result["capacity_state"], "UNKNOWN")
        self.assertEqual(result["totals_by_uom"], {})

    def test_multiple_lines_and_uoms_never_cancel_or_combine(self):
        self.physical.lines.append(Doc(line_key="L2", qty="200", uom="KG"))
        self.allocation("40")
        self.allocation("120", outward_line_key="L2", uom="KG")
        result = self.service.get_outward_capacity("OUT-1", "ACME")
        self.assertEqual(result["totals_by_uom"]["BOX"]["remaining_qty"], "60")
        self.assertEqual(result["totals_by_uom"]["KG"]["remaining_qty"], "80")

    def test_hidden_physical_reversal_removes_capacity(self):
        self.reversals = [Doc(name="HIDDEN-REVERSAL", posted_at="2026-10-02 11:00:00", movement_at="2026-10-02 10:00:00")]
        result = self.service.get_outward_capacity("OUT-1", "ACME")
        self.assertFalse(result["physical_active"])
        self.assertEqual(result["lines"][0]["remaining_qty"], None)

    def test_invalid_consumption_fails_closed(self):
        for changes in ({"qty": None}, {"qty": "NaN"}, {"qty": "-1"}, {"uom": "KG"},
                        {"outward_line_key": "NOT-A-LINE"}, {"company": "OTHER"}, {"state": "INVALID"}):
            with self.subTest(changes=changes):
                self.allocations.clear()
                self.allocation(**changes)
                result = self.service.get_outward_capacity("OUT-1", "ACME")
                self.assertEqual(result["capacity_state"], "UNKNOWN")
                self.assertEqual(result["totals_by_uom"], {})

    def test_unknown_container_physical_aggregate_is_null_not_zero(self):
        self.allocation(qty=None)
        result = self.service.get_container_reconciliation("CON-1")
        self.assertIsNone(result["totals_by_uom"]["BOX"]["physically_unallocated_qty"])
        self.assertIn("DATA_INTEGRITY", result["exceptions"])

    def test_overdraw_is_conflict_not_available_stock(self):
        self.allocation("101")
        result = self.service.get_outward_capacity("OUT-1", "ACME")
        self.assertEqual(result["capacity_state"], "CONFLICT")

    def test_company_and_outward_authorization_precede_unfiltered_tally(self):
        for mode in ("company_mismatch", "denied_outward", "supplier"):
            with self.subTest(mode=mode):
                self.queries.clear()
                self.frappe.has_permission = lambda *args, **kwargs: mode != "denied_outward"
                self.frappe.roles = ["Fresko Salesperson", "Fresko Supplier Viewer"] if mode == "supplier" else ["Fresko Salesperson"]
                with self.assertRaises(PermissionError):
                    self.service.get_outward_capacity("OUT-1", "OTHER" if mode == "company_mismatch" else "ACME")
                self.assertFalse(any("tabFresko Sale Outward Allocation" in query for query, _ in self.queries))


if __name__ == "__main__":
    unittest.main()
