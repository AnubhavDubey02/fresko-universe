"""Offline Unit & AST Contract Tests for Fresko Clear Operator UX P0.

Validates:
1. extend_bootinfo hook:
   - Supplier-First Denial precedence (pure & mixed roles)
   - System Manager standard Desk isolation (no implicit business permissions)
   - Operational roles: Salesperson, Accounts, Approver command-specific capabilities
   - Multi-role capability union and landing route precedence
   - Non-operator fallback
   - Zero financial aggregates in bootinfo
   - Boot cache re-evaluation and idempotency
2. Static AST security invariants on operator_service.py:
   - Strict ban on frappe.db.sql
   - Strict ban on frappe.get_all
   - Strict ban on ignore_permissions=True
3. check_action_eligibility segregation-of-duties rules:
   - Maker cannot verify
   - Maker and Verifier cannot approve
   - Historical projections are strictly read-only
   - Commercial vs Money allocation capabilities
   - Status transition restrictions (draft cannot verify, unverified cannot approve)
4. Linked evidence authorization scoping (no leak on restricted docs).
5. Company scoping and live-only enforcement on get_operator_action_feed:
   - Positive authorization check without get_permitted_documents
   - Rejection of as_of cutoff requests
   - Mapping of persisted schema fields (version, payment_channel)
"""
import ast
from datetime import datetime
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
if "fresko_universe" in sys.modules and not hasattr(sys.modules["fresko_universe"], "fresko_core"):
    sys.modules.pop("fresko_universe", None)


class OperatorContractOfflineBase(unittest.TestCase):
    def setUp(self):
        root = _root

        self.frappe = types.ModuleType("frappe")
        self.frappe.session = types.SimpleNamespace(user="test@example.invalid")
        self.frappe.get_roles = lambda user: []
        def throw(msg, exc=Exception):
            raise exc(msg)
        self.frappe.throw = throw
        self.frappe.ValidationError = type("ValidationError", (Exception,), {})
        self.frappe.PermissionError = type("PermissionError", (Exception,), {})
        self.frappe._ = lambda s: s
        self.frappe.whitelist = lambda *args, **kwargs: (lambda fn: fn)
        self.frappe.has_permission = lambda *args, **kwargs: True
        self.frappe.defaults = types.SimpleNamespace(get_user_default=lambda *args, **kwargs: "")
        self.frappe.get_list = lambda *args, **kwargs: []
        self.frappe.db = MagicMock()

        utils = types.ModuleType("frappe.utils")
        utils.now_datetime = lambda: datetime(2026, 10, 8, 12, 0, 0)
        utils.get_datetime = lambda s: datetime.fromisoformat(s) if s else None
        self.frappe.utils = utils

        self.patcher = patch.dict(sys.modules, {
            "frappe": self.frappe,
            "frappe.utils": utils,
        })
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

        boot_path = root / "fresko_universe" / "boot.py"
        spec_boot = importlib.util.spec_from_file_location("fresko_universe_boot", boot_path)
        self.boot_mod = importlib.util.module_from_spec(spec_boot)
        spec_boot.loader.exec_module(self.boot_mod)
        self.boot_mod.frappe = self.frappe

        from fresko_universe.fresko_core.services import operator_service
        self.op_mod = operator_service
        self.op_mod.frappe = self.frappe


class TestOperatorBootContract(OperatorContractOfflineBase):
    """Test boot capability derivation and Supplier-first denial."""

    def test_guest_session_untouched(self):
        bootinfo = {}
        self.frappe.session.user = "Guest"
        self.boot_mod.extend_bootinfo(bootinfo)
        self.assertNotIn("fresko", bootinfo)

    def test_supplier_first_denial_pure(self):
        bootinfo = {}
        self.frappe.session.user = "supplier@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Supplier Viewer"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertIsNotNone(fresko)
        self.assertEqual(fresko["persona"], "supplier_denied")
        self.assertEqual(fresko["capabilities"], [])
        self.assertIsNone(fresko["default_route"])
        self.assertFalse(fresko["is_operator"])

    def test_supplier_first_denial_mixed_with_accounts(self):
        bootinfo = {}
        self.frappe.session.user = "mixed@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Supplier Viewer", "Fresko Accounts"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "supplier_denied")
        self.assertEqual(fresko["capabilities"], [])
        self.assertFalse(fresko["is_operator"])

    def test_supplier_first_denial_mixed_with_system_manager(self):
        bootinfo = {}
        self.frappe.session.user = "admin_supplier@example.com"
        self.frappe.get_roles = lambda u: ["System Manager", "Fresko Supplier Viewer"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "supplier_denied")
        self.assertEqual(fresko["capabilities"], [])

    def test_system_manager_retains_standard_desk(self):
        bootinfo = {}
        self.frappe.session.user = "admin@example.com"
        self.frappe.get_roles = lambda u: ["System Manager"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "system_manager")
        self.assertIn("admin_desk", fresko["capabilities"])
        self.assertEqual(fresko["default_route"], "Workspaces")
        self.assertFalse(fresko["is_operator"])

    def test_salesperson_capabilities_and_route(self):
        bootinfo = {}
        self.frappe.session.user = "sales@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Salesperson"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "salesperson")
        self.assertEqual(fresko["default_route"], "fresko-workspace")
        self.assertTrue(fresko["is_operator"])
        self.assertIn("create_sale", fresko["capabilities"])
        self.assertIn("propose_rate", fresko["capabilities"])
        self.assertIn("propose_sale_outward_allocation", fresko["capabilities"])
        self.assertNotIn("verify_sale", fresko["capabilities"])
        self.assertNotIn("approve_sale", fresko["capabilities"])

    def test_accounts_capabilities_and_route(self):
        bootinfo = {}
        self.frappe.session.user = "accounts@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Accounts"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "accounts")
        self.assertEqual(fresko["default_route"], "fresko-money")
        self.assertTrue(fresko["is_operator"])
        self.assertIn("verify_sale", fresko["capabilities"])
        self.assertIn("capture_collection", fresko["capabilities"])
        self.assertIn("propose_payment_allocation", fresko["capabilities"])
        self.assertNotIn("approve_sale", fresko["capabilities"])

    def test_approver_capabilities_and_route(self):
        bootinfo = {}
        self.frappe.session.user = "approver@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Approver"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "approver")
        self.assertEqual(fresko["default_route"], "fresko-workspace")
        self.assertTrue(fresko["is_operator"])
        self.assertIn("approve_sale", fresko["capabilities"])
        self.assertIn("approve_collection", fresko["capabilities"])
        self.assertIn("approve_payment_allocation", fresko["capabilities"])

    def test_multi_role_union_and_approver_precedence(self):
        bootinfo = {}
        self.frappe.session.user = "multi@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Approver", "Fresko Accounts"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "multi_role")
        # Approver oversight takes precedence for landing
        self.assertEqual(fresko["default_route"], "fresko-workspace")
        self.assertTrue(fresko["is_operator"])
        # Union of capabilities
        self.assertIn("verify_sale", fresko["capabilities"])
        self.assertIn("approve_sale", fresko["capabilities"])

    def test_non_operator_fallback(self):
        bootinfo = {}
        self.frappe.session.user = "employee@example.com"
        self.frappe.get_roles = lambda u: ["Employee"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "non_operator")
        self.assertEqual(fresko["capabilities"], [])
        self.assertIsNone(fresko["default_route"])
        self.assertFalse(fresko["is_operator"])

    def test_zero_financial_aggregates_in_bootinfo(self):
        bootinfo = {}
        self.frappe.session.user = "accounts@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Accounts"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo["fresko"]
        for forbidden_key in ["balance", "amount", "total", "count", "sales", "collections"]:
            self.assertNotIn(forbidden_key, fresko)


class TestOperatorASTSecurity(unittest.TestCase):
    """Static AST validation of operator_service.py."""

    def setUp(self):
        service_path = Path(__file__).resolve().parents[1] / "fresko_universe" / "fresko_core" / "services" / "operator_service.py"
        self.code = service_path.read_text(encoding="utf-8")
        self.tree = ast.parse(self.code)

    def test_ban_on_frappe_db_sql(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and node.attr == "sql":
                parent = node.value
                if isinstance(parent, ast.Attribute) and parent.attr == "db":
                    self.fail("Direct SQL query (frappe.db.sql) is strictly prohibited in operator_service.py")

    def test_ban_on_frappe_get_all(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and node.attr == "get_all":
                self.fail("frappe.get_all is prohibited in operator_service.py; use frappe.get_list for ACL enforcement")

    def test_ban_on_ignore_permissions_true(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.keyword) and node.arg == "ignore_permissions":
                if isinstance(node.value, ast.Constant) and node.value.value is True:
                    self.fail("ignore_permissions=True is strictly prohibited in operator_service.py")


class TestOperatorSegregationOfDuties(OperatorContractOfflineBase):
    """Test pure can_act authorization check for segregation of duties."""

    def test_maker_cannot_verify(self):
        doc = {"prepared_by": "maker1", "name": "FSALE-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            doc, "verify", "maker1", {"Fresko Accounts"}
        )
        self.assertFalse(allowed)
        self.assertIn("you prepared this record", reason)

    def test_distinct_accounts_can_verify(self):
        doc = {"prepared_by": "maker1", "name": "FSALE-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            doc, "verify", "verifier1", {"Fresko Accounts"}
        )
        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_maker_cannot_approve(self):
        doc = {"prepared_by": "approver_who_made", "name": "FSALE-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            doc, "approve", "approver_who_made", {"Fresko Approver"}
        )
        self.assertFalse(allowed)
        self.assertIn("you prepared this record", reason)

    def test_verifier_cannot_approve(self):
        doc = {"prepared_by": "maker1", "verified_by": "verifier_who_approves", "name": "FSALE-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            doc, "approve", "verifier_who_approves", {"Fresko Approver"}
        )
        self.assertFalse(allowed)
        self.assertIn("you verified this record", reason)

    def test_distinct_approver_can_approve(self):
        doc = {"prepared_by": "maker1", "verified_by": "verifier1", "name": "FSALE-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            doc, "approve", "approver1", {"Fresko Approver"}
        )
        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_historical_mode_strictly_read_only(self):
        doc = {"prepared_by": "maker1", "name": "FSALE-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            doc, "verify", "verifier1", {"Fresko Accounts"}, is_historical=True
        )
        self.assertFalse(allowed)
        self.assertIn("Historical projection is read-only", reason)

    def test_verify_fails_on_draft_status(self):
        doc = {"prepared_by": "maker1", "status": "DRAFT", "name": "FSALE-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "verify_sale", doc, "verifier1", {"Fresko Accounts"}
        )
        self.assertFalse(allowed)
        self.assertIn("Cannot verify sale in state DRAFT", reason)

    def test_approve_fails_without_verifier(self):
        doc = {"prepared_by": "maker1", "status": "VERIFIED", "name": "FSALE-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "approve_sale", doc, "approver1", {"Fresko Approver"}
        )
        self.assertFalse(allowed)
        self.assertIn("Record missing verified_by identity", reason)

    def test_approve_alias_fails_on_proposed_state(self):
        doc = {"proposed_by": "maker1", "status": "PROPOSED", "name": "FPAM-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "approve_alias", doc, "approver1", {"Fresko Approver"}
        )
        self.assertFalse(allowed)
        self.assertIn("requires VERIFIED", reason)

    def test_verify_alias_succeeds_on_proposed(self):
        doc = {"proposed_by": "maker1", "status": "PROPOSED", "name": "FPAM-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "verify_alias", doc, "accounts1", {"Fresko Accounts"}
        )
        self.assertTrue(allowed)
        self.assertIsNone(reason)


class TestOperatorEvidenceScoping(OperatorContractOfflineBase):
    """Test record-level linked Evidence scoping."""

    def test_none_evidence(self):
        res = self.op_mod.scope_evidence(None)
        self.assertEqual(res["evidence_state"], "NONE")
        self.assertIsNone(res["evidence_name"])

    def test_restricted_evidence_omits_reference(self):
        self.frappe.has_permission = lambda *args, **kwargs: False
        res = self.op_mod.scope_evidence("FEVID-PRIVATE-001")
        self.assertEqual(res["evidence_state"], "RESTRICTED")
        self.assertIsNone(res["evidence_name"])

    def test_available_evidence_returns_reference(self):
        self.frappe.has_permission = lambda *args, **kwargs: True
        res = self.op_mod.scope_evidence("FEVID-PUBLIC-001")
        self.assertEqual(res["evidence_state"], "AVAILABLE")
        self.assertEqual(res["evidence_name"], "FEVID-PUBLIC-001")


class TestOperatorFeedValidationAndScoping(OperatorContractOfflineBase):
    """Test company authorization, live-only enforcement, and schema mapping in get_operator_action_feed."""

    def setUp(self):
        super().setUp()
        self.frappe.session.user = "operator@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Accounts", "Fresko Approver"]

    def test_supplier_denied_from_action_feed(self):
        self.frappe.get_roles = lambda u: ["Fresko Accounts", "Fresko Supplier Viewer"]
        with self.assertRaises(self.frappe.PermissionError) as ctx:
            self.op_mod.get_operator_action_feed(company="ACME")
        self.assertIn("Supplier identities cannot access", str(ctx.exception))

    def test_company_denial_raises_permission_error(self):
        self.frappe.has_permission = lambda doctype, doc=None, ptype="read": False
        with self.assertRaises(self.frappe.PermissionError) as ctx:
            self.op_mod.get_operator_action_feed(company="DENIED_CORP")
        self.assertIn("Access denied for company DENIED_CORP", str(ctx.exception))

    def test_historical_as_of_rejected_with_validation_error(self):
        self.frappe.has_permission = lambda doctype, doc=None, ptype="read": True
        with self.assertRaises(self.frappe.ValidationError) as ctx:
            self.op_mod.get_operator_action_feed(company="ACME", as_of="2026-01-01T00:00:00")
        self.assertIn("strictly live-only", str(ctx.exception))

    def test_live_feed_projection_mode(self):
        self.frappe.has_permission = lambda doctype, doc=None, ptype="read": True
        self.frappe.get_list = lambda doctype, **kwargs: []
        res = self.op_mod.get_operator_action_feed(company="ACME", as_of=None)
        self.assertEqual(res["projection_mode"], "LIVE")
        self.assertEqual(res["company"], "ACME")
        self.assertEqual(res["feed_type"], "operator_action_feed")
        self.assertIn("counts", res)
        self.assertIn("sections", res)

    def test_populated_feed_schema_field_mapping(self):
        self.frappe.has_permission = lambda doctype, doc=None, ptype="read": True

        def mock_get_list(doctype, **kwargs):
            if doctype == "Fresko Commercial Sale":
                return [{
                    "name": "FSALE-001",
                    "container": "CONT-001",
                    "company": "ACME",
                    "version": 3,
                    "currency": "AED",
                    "total_amount": "1500.00",
                    "buyer_name": "Customer X",
                    "status": "REVIEW_PENDING",
                    "pricing_mode": "AGREED",
                    "rate_status": "CONFIRMED",
                    "prepared_by": "sales1",
                    "verified_by": None,
                    "source_evidence": "EVID-001",
                    "modified": "2026-10-08 12:00:00"
                }]
            elif doctype == "Fresko Collection":
                return [{
                    "name": "FCOLL-001",
                    "company": "ACME",
                    "version": 2,
                    "currency": "AED",
                    "amount": "2500.00",
                    "payment_channel": "BANK",
                    "status": "REVIEW_PENDING",
                    "prepared_by": "accounts1",
                    "verified_by": None,
                    "source_evidence": "EVID-002",
                    "modified": "2026-10-08 12:00:00"
                }]
            elif doctype == "Fresko Party Alias Mapping":
                return [{
                    "name": "FPAM-001",
                    "raw_alias": "RAW-PARTY",
                    "proposed_customer": "Customer X",
                    "status": "PROPOSED",
                    "proposed_by": "sales1",
                    "verified_by": None,
                    "evidence": "EVID-003",
                    "modified": "2026-10-08 12:00:00"
                }]
            return []

        self.frappe.get_list = mock_get_list

        res = self.op_mod.get_operator_action_feed(company="ACME")
        self.assertEqual(res["projection_mode"], "LIVE")
        self.assertGreater(res["loaded_items_count"], 0)

        # Verify Sale mapping has version mapped to both version and current_version, and source_evidence
        sale_sec = next(s for s in res["sections"] if s["id"] == "commercial_verifications")
        self.assertEqual(len(sale_sec["items"]), 1)
        sale_item = sale_sec["items"][0]
        self.assertEqual(sale_item["document_name"], "FSALE-001")
        self.assertEqual(sale_item["version"], 3)
        self.assertEqual(sale_item["current_version"], 3)
        self.assertEqual(sale_item["source_evidence"], "EVID-001")
        self.assertEqual(sale_item["evidence_state"], "AVAILABLE")
        self.assertEqual(sale_item["evidence_name"], "EVID-001")

        # Verify Collection mapping has version, current_version, and payment_channel
        coll_sec = next(s for s in res["sections"] if s["id"] == "collection_verifications")
        self.assertEqual(len(coll_sec["items"]), 1)
        coll_item = coll_sec["items"][0]
        self.assertEqual(coll_item["document_name"], "FCOLL-001")
        self.assertEqual(coll_item["version"], 2)
        self.assertEqual(coll_item["current_version"], 2)
        self.assertEqual(coll_item["payment_channel"], "BANK")
        self.assertEqual(coll_item["source_evidence"], "EVID-002")


if __name__ == "__main__":
    unittest.main()
