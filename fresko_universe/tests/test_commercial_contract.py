"""Offline behavioral checks for commercial decimal/source truth boundaries."""
from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "fresko_universe/fresko_universe/fresko_core/services/commercial_service.py"


class ValidationError(Exception):
    pass


def _throw(message, exception=ValidationError):
    raise exception(message)


def _subject():
    frappe = types.ModuleType("frappe")
    frappe.throw = _throw
    frappe.ValidationError = ValidationError
    frappe.PermissionError = PermissionError
    frappe.session = types.SimpleNamespace(user="maker@example.invalid")
    frappe.get_roles = lambda user: ["Fresko Salesperson"]
    frappe.parse_json = json.loads
    utils = types.ModuleType("frappe.utils")
    utils.get_datetime = datetime.fromisoformat
    utils.now_datetime = datetime.now
    package = types.ModuleType("fresko_universe")
    permissions = types.ModuleType("fresko_universe.permissions")
    package.permissions = permissions
    with patch.dict(sys.modules, {"frappe": frappe, "frappe.utils": utils,
                                 "fresko_universe": package,
                                 "fresko_universe.permissions": permissions}):
        spec = importlib.util.spec_from_file_location("commercial_contract_subject", SERVICE)
        subject = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(subject)
    return subject


class TestCommercialContract(unittest.TestCase):
    def setUp(self):
        self.service = _subject()

    def _line(self, **changes):
        row = {"line_key": "raw-line", "item": "Synthetic Item", "uom": "Crate",
               "raw_lot_text": None, "lot_state": "UNKNOWN", "qty_state": "KNOWN",
               "qty": "80", "price_state": "PROPOSED", "rate": "825",
               "rate_basis": "RATE_ASSERTION", "evidence": "synthetic-evidence"}
        row.update(changes)
        return row

    def _lines(self, rows):
        with patch.object(self.service, "_linked"), patch.object(self.service, "_evidence"):
            return self.service._lines(rows, "synthetic-company", "synthetic-container")

    def test_equivalent_decimal_text_has_one_canonical_value(self):
        values = ["01.000", "+1.0", "1"]
        self.assertEqual({self.service._decimal(x) for x in values}, {"1"})

    def test_decimal_rejects_unsafe_or_implicit_numeric_inputs(self):
        for value in [1, 1.0, True, "1e3", "NaN", "Infinity", "-1", " 1", "1,000", "0.0000001"]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.service._decimal(value, positive=True)

    def test_decimal_overflow_is_validation_not_arithmetic_exception(self):
        with self.assertRaises(ValidationError):
            self.service._decimal("9" * 30)

    def test_raw_alias_preserves_spaces_case_and_unicode(self):
        raw = "  SOH / \u212a buyer  "
        self.assertEqual(self.service._text(raw, "raw_alias"), raw)

    def test_company_and_raw_event_are_part_of_replay_identity(self):
        keys = [self.service._key("C1", "sale", " event "),
                self.service._key("C1", "sale", "event"),
                self.service._key("C2", "sale", " event "),
                self.service._key("C1", "alias", " event ")]
        self.assertEqual(len(set(keys)), 4)

    def test_multilot_decimal_amount_is_commercial_not_physical(self):
        rows = self._lines([self._line(qty="80", raw_lot_text="42076"),
                            self._line(line_key="second", qty="20", raw_lot_text="42074")])
        self.assertEqual([r["amount"] for r in rows], ["66000", "16500"])
        self.assertEqual(sum(int(r["qty"]) for r in rows), 100)

    def test_unknown_quantity_and_price_remain_null(self):
        row = self._lines([self._line(qty=None, qty_state="UNKNOWN", rate=None,
                                      price_state="UNKNOWN", rate_basis="NONE")])[0]
        self.assertIsNone(row["qty"])
        self.assertIsNone(row["rate"])
        self.assertIsNone(row["amount"])

    def test_unknown_quantity_cannot_be_silently_filled(self):
        with self.assertRaises(ValidationError):
            self._lines([self._line(qty_state="UNKNOWN")])

    def test_null_lot_with_claimed_known_identity_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._lines([self._line(lot_state="KNOWN")])

    def test_caller_cannot_forge_final_rate_or_derived_amount(self):
        for changes in [{"price_state": "FINAL"}, {"amount": "1"}, {"approved_by": "Administrator"}]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self._lines([self._line(**changes)])

    def test_buckets_preserve_unmapped_lots_and_do_not_create_allocations(self):
        rows = self._lines([self._line(qty="47", rate="1350", rate_basis="PRICE_BUCKET", bucket_key="a"),
                            self._line(line_key="b", qty="133", rate="1300", rate_basis="PRICE_BUCKET", bucket_key="b")])
        self.assertEqual([r["amount"] for r in rows], ["63450", "172900"])
        self.assertTrue(all(r["container_lot"] is None for r in rows))
        self.assertTrue(all("outward" not in r for r in rows))

    def test_duplicate_bucket_or_line_identity_is_rejected(self):
        for rows in [[self._line(), self._line()],
                     [self._line(rate_basis="PRICE_BUCKET", bucket_key="a"),
                      self._line(line_key="b", rate_basis="PRICE_BUCKET", bucket_key="a")]]:
            with self.subTest(rows=rows), self.assertRaises(ValidationError):
                self._lines(rows)

    def test_amount_does_not_round_unsupported_fractional_money(self):
        with self.assertRaises(ValidationError):
            self._lines([self._line(qty="0.001", rate="1")])

    def test_system_manager_is_not_routine_business_approver(self):
        self.service.frappe.get_roles = lambda user: ["System Manager"]
        with self.assertRaises(PermissionError):
            self.service._actor("approve")

    def test_supplier_role_cannot_gain_access_through_mixed_internal_roles(self):
        self.service.frappe.get_roles = lambda user: ["Supplier", "Fresko Approver"]
        with self.assertRaises(PermissionError):
            self.service._actor("approve")

    def test_private_service_capability_resets_after_failure(self):
        self.assertFalse(self.service._SCOPE.get())
        with self.assertRaises(RuntimeError):
            with self.service._write():
                self.assertTrue(self.service._SCOPE.get())
                raise RuntimeError("failed transaction")
        self.assertFalse(self.service._SCOPE.get())

    def test_audit_snapshot_matches_fresh_datetime_fields_after_json_roundtrip(self):
        values = {"status": "VERIFIED", "verified_by": "accounts@example.invalid",
                  "verified_at": datetime(2026, 10, 3, 12, 0)}
        doc = types.SimpleNamespace(doctype=self.service.SALE, version=1,
                                    decision_history="[]", get=lambda key: values.get(key))
        self.service._event(doc, "VERIFY")
        event = json.loads(doc.decision_history)[-1]
        self.assertEqual(event["snapshot"], self.service._snapshot(doc))


if __name__ == "__main__":
    unittest.main()
