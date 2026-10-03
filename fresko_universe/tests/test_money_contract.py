"""Isolated behavioral contract tests for Money and Reconciliation backend slice."""
import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path
import hashlib
import json
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch


class MoneyContractOfflineTest(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType("frappe")
        def throw(message, exception=ValueError):
            raise exception(message)
        self.frappe.throw = throw
        self.frappe.ValidationError = ValueError
        self.frappe.PermissionError = PermissionError
        self.frappe.session = types.SimpleNamespace(user="test@example.invalid")
        self.frappe.get_roles = lambda user: ["Fresko Accounts"]
        self.frappe.generate_hash = lambda length=8: "a" * length
        self.frappe.db = MagicMock()
        utils = types.ModuleType("frappe.utils")
        utils.get_datetime = datetime.fromisoformat
        utils.now_datetime = datetime.now
        package = types.ModuleType("fresko_universe")
        permissions = types.ModuleType("fresko_universe.permissions")
        package.permissions = permissions
        self.modules = patch.dict(sys.modules, {"frappe": self.frappe, "frappe.utils": utils,
            "fresko_universe": package, "fresko_universe.permissions": permissions})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        path = Path(__file__).resolve().parents[1] / "fresko_universe/fresko_core/services/money_service.py"
        spec = importlib.util.spec_from_file_location("money_contract_subject", path)
        self.service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.service)

    def test_decimal_text_parsing_and_scale(self):
        money_service = self.service
        self.assertEqual(money_service._decimal("100.50"), "100.50")
        self.assertEqual(money_service._decimal("350000.00"), "350000.00")
        with self.assertRaises(Exception):
            money_service._decimal("100.555")
        with self.assertRaises(Exception):
            money_service._decimal("1e5")
        with self.assertRaises(Exception):
            money_service._decimal("-10.00")

    def test_role_and_supplier_substring_denial(self):
        money_service = self.service
        with patch("frappe.get_roles", return_value=["Supplier User", "Fresko Accounts"]):
            with self.assertRaises(Exception) as ctx:
                money_service._roles("test@example.com")
            self.assertIn("Supplier access to internal money records is denied", str(ctx.exception))

    def test_actor_role_separation(self):
        money_service = self.service
        with patch("frappe.get_roles", return_value=["Fresko Salesperson"]):
            with self.assertRaises(Exception):
                money_service._actor("maker")
        with patch("frappe.get_roles", return_value=["Fresko Accounts"]):
            money_service._actor("maker")
            money_service._actor("verify")
            with self.assertRaises(Exception):
                money_service._actor("approve")
        with patch("frappe.get_roles", return_value=["Fresko Approver"]):
            money_service._actor("approve")
            with self.assertRaises(Exception):
                money_service._actor("maker")

    def test_distinct_maker_verifier_approver(self):
        money_service = self.service
        doc = MagicMock()
        doc.get.side_effect = lambda k: "user1" if k == "prepared_by" else "user2" if k == "verified_by" else None
        with patch("frappe.get_roles", return_value=["Fresko Accounts"]):
            with patch("frappe.session.user", "user1"):
                with self.assertRaises(Exception):
                    money_service._separate(doc, "verify")
            with patch("frappe.session.user", "user2"):
                money_service._separate(doc, "verify")
        with patch("frappe.get_roles", return_value=["Fresko Approver"]):
            with patch("frappe.session.user", "user1"):
                with self.assertRaises(Exception):
                    money_service._separate(doc, "approve")
            with patch("frappe.session.user", "user2"):
                with self.assertRaises(Exception):
                    money_service._separate(doc, "approve")
            with patch("frappe.session.user", "user3"):
                money_service._separate(doc, "approve")

    def test_file_protection_hooks(self):
        money_service = self.service
        file_doc = MagicMock(doctype="File", name="FILE-001", file_url="/files/test.pdf")
        file_doc.get_doc_before_save.return_value = MagicMock()
        with patch("frappe.db.sql", return_value=[{"name": "COLL-001"}]):
            with self.assertRaises(Exception) as ctx:
                money_service.protect_money_file_before_save(file_doc)
            self.assertIn("referenced by immutable money record", str(ctx.exception))

    def test_unclassified_adjustment_ineligible_for_approval(self):
        money_service = self.service
        doc = MagicMock(
            adjustment_type="UNCLASSIFIED",
            verified_by="user2",
            status="VERIFIED",
            version=2,
            evidence="EV-001",
            agreement_reference=None
        )
        doc.get.side_effect = lambda k: "user1" if k == "prepared_by" else "user2" if k == "verified_by" else None
        with patch.object(money_service, "_load", return_value=doc):
            with patch.object(money_service, "_separate"):
                with self.assertRaises(Exception) as ctx:
                    money_service.approve_adjustment("ADJ-001")
                self.assertIn("UNCLASSIFIED adjustment cannot be approved", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

class EligibilityRegressionTest(unittest.TestCase):
    setUp = MoneyContractOfflineTest.setUp
    def test_unknown_channel_and_undeclared_cash_are_ineligible(self):
        doc = types.SimpleNamespace(status="APPROVED", direction="INFLOW", amount_state="KNOWN", amount="101.00",
            payment_channel="UNKNOWN", source_classification="OTHER", receipt_state="UNKNOWN")
        self.assertFalse(self.service._collection_eligible(doc))
        doc.payment_channel = "CASH"
        self.assertFalse(self.service._collection_eligible(doc))
        doc.source_classification = "CASH_DECLARATION"
        doc.receipt_state = "RECEIVED"
        self.assertTrue(self.service._collection_eligible(doc))
        doc.direction = "INTERNAL_TRANSFER"
        self.assertFalse(self.service._collection_eligible(doc))

    def test_pending_bank_is_received_but_not_eligible(self):
        doc = types.SimpleNamespace(status="APPROVED", direction="INFLOW", amount_state="KNOWN", amount="350000.00",
            payment_channel="BANK", bank_state="AUTHORIZATION_INPROCESS", receipt_state="RECEIVED",
            bank_account="Synthetic Bank", bank_reference="OPAQUE-350", source_evidence="Synthetic Evidence")
        self.assertFalse(self.service._collection_eligible(doc))
        doc.bank_state = "BANK_CLEARED"
        self.assertTrue(self.service._collection_eligible(doc))
        doc.source_evidence = None
        self.assertFalse(self.service._collection_eligible(doc))

    def test_history_cutoff_preserves_accepted_before_reversal(self):
        history = [{"recorded_at": "2026-09-15 12:00:00", "snapshot": {"status": "APPROVED"}},
            {"recorded_at": "2026-09-22 12:00:00", "snapshot": {"status": "REVERSED"}}]
        doc = types.SimpleNamespace(decision_history=json.dumps(history))
        self.assertEqual(self.service._state_at(doc, datetime(2026, 9, 18))["status"], "APPROVED")
        self.assertEqual(self.service._state_at(doc, datetime(2026, 9, 23))["status"], "REVERSED")
        self.assertIsNone(self.service._state_at(doc, datetime(2026, 9, 1)))
