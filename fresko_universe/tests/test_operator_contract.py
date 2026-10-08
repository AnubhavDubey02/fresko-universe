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
   - Missing status fails closed (no synthesized defaults)
   - Commercial allocation verification & approval requires prior verified_by
   - Historical projections are strictly read-only
4. Outward canonical capacity (FR-QA-012):
   - Zero allocations (fully available)
   - Partial allocations (remaining capacity accurate)
   - Fully allocated (excluded from unassigned outwards)
   - Reversed allocation (frees capacity)
   - Inaccessible linked Sale (consumes capacity without leaking identity)
5. Action feed response contract & unique record counts (FR-QA-015):
   - records_loaded, actionable_records, blocked_records, informational_records, truncated
   - All Clear only when actionable == 0 and not truncated
6. Confidential sale redaction in allocation reviews (FR-QA-019)
7. Login CSS scoping & HTTP 403 denial assertions (FR-QA-008)
"""
import ast
from datetime import datetime
from decimal import Decimal
import importlib.util
from pathlib import Path
import re
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

    def test_supplier_denial_precedence_over_all_roles(self):
        bootinfo = {}
        self.frappe.session.user = "mixed@example.com"
        self.frappe.get_roles = lambda u: [
            "Fresko Salesperson",
            "Fresko Accounts",
            "Fresko Approver",
            "System Manager",
            "Supplier",
        ]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "supplier_denied")
        self.assertEqual(fresko["capabilities"], [])
        self.assertIsNone(fresko["default_route"])
        self.assertFalse(fresko["is_operator"])

    def test_system_manager_retains_standard_desk(self):
        bootinfo = {}
        self.frappe.session.user = "admin@example.com"
        self.frappe.get_roles = lambda u: ["System Manager"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "system_manager")
        self.assertEqual(fresko["capabilities"], ["admin_desk", "view_audit"])
        self.assertEqual(fresko["default_route"], "Workspaces")
        self.assertFalse(fresko["is_operator"])

    def test_salesperson_capabilities_and_route(self):
        bootinfo = {}
        self.frappe.session.user = "sales@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Salesperson"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "salesperson")
        self.assertIn("create_sale", fresko["capabilities"])
        self.assertIn("propose_rate", fresko["capabilities"])
        self.assertNotIn("verify_sale", fresko["capabilities"])
        self.assertNotIn("view_money", fresko["capabilities"])
        self.assertEqual(fresko["default_route"], "fresko-workspace")
        self.assertTrue(fresko["is_operator"])
        self.assertEqual(fresko["allowed_routes"], ["fresko-workspace"])

    def test_accounts_capabilities_and_route(self):
        bootinfo = {}
        self.frappe.session.user = "accounts@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Accounts"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "accounts")
        self.assertIn("verify_sale", fresko["capabilities"])
        self.assertIn("view_money", fresko["capabilities"])
        self.assertIn("capture_collection", fresko["capabilities"])
        self.assertNotIn("approve_sale", fresko["capabilities"])
        self.assertEqual(fresko["default_route"], "fresko-money")
        self.assertTrue(fresko["is_operator"])
        self.assertIn("fresko-money", fresko["allowed_routes"])

    def test_approver_capabilities_and_route_precedence(self):
        bootinfo = {}
        self.frappe.session.user = "approver@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Approver"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "approver")
        self.assertIn("approve_sale", fresko["capabilities"])
        self.assertIn("view_money", fresko["capabilities"])
        self.assertEqual(fresko["default_route"], "fresko-workspace")
        self.assertTrue(fresko["is_operator"])

    def test_multi_role_capability_union(self):
        bootinfo = {}
        self.frappe.session.user = "dual@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Salesperson", "Fresko Accounts"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "multi_role")
        self.assertIn("create_sale", fresko["capabilities"])
        self.assertIn("verify_sale", fresko["capabilities"])
        self.assertEqual(fresko["default_route"], "fresko-money")
        self.assertIn("fresko-workspace", fresko["allowed_routes"])
        self.assertIn("fresko-money", fresko["allowed_routes"])

    def test_approver_precedence_over_accounts_for_route(self):
        bootinfo = {}
        self.frappe.session.user = "dual@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Approver", "Fresko Accounts"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["default_route"], "fresko-workspace")

    def test_non_operator_fallback(self):
        bootinfo = {}
        self.frappe.session.user = "hr@example.com"
        self.frappe.get_roles = lambda u: ["HR User", "Employee"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        self.assertEqual(fresko["persona"], "non_operator")
        self.assertEqual(fresko["capabilities"], [])
        self.assertIsNone(fresko["default_route"])
        self.assertFalse(fresko["is_operator"])

    def test_zero_financial_aggregates_in_boot(self):
        bootinfo = {}
        self.frappe.session.user = "accounts@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Accounts", "Fresko Approver"]
        self.boot_mod.extend_bootinfo(bootinfo)
        fresko = bootinfo.get("fresko")
        forbidden_keys = {"balance", "total", "outstanding", "receivable", "count", "aggregate"}
        for k in fresko.keys():
            self.assertFalse(any(bad in k.lower() for bad in forbidden_keys), f"Financial data leaked in key: {k}")

    def test_bootinfo_caching_idempotency(self):
        bootinfo1 = {}
        self.frappe.session.user = "sales@example.com"
        self.frappe.get_roles = lambda u: ["Fresko Salesperson"]
        self.boot_mod.extend_bootinfo(bootinfo1)

        bootinfo2 = {}
        self.boot_mod.extend_bootinfo(bootinfo2)
        self.assertEqual(bootinfo1, bootinfo2)


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
    """Test pure check_action_eligibility authorization for segregation of duties."""

    def test_missing_status_fails_closed(self):
        doc = {"prepared_by": "maker1", "name": "FSALE-001"}  # Missing status/state
        allowed, reason = self.op_mod.check_action_eligibility(
            "verify_sale", doc, "verifier1", {"Fresko Accounts"}
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "Missing workflow status")

    def test_maker_cannot_verify(self):
        doc = {"prepared_by": "maker1", "status": "REVIEW_PENDING", "name": "FSALE-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "verify_sale", doc, "maker1", {"Fresko Accounts"}
        )
        self.assertFalse(allowed)
        self.assertIn("you prepared this record", reason)

    def test_distinct_accounts_can_verify(self):
        doc = {"prepared_by": "maker1", "status": "REVIEW_PENDING", "name": "FSALE-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "verify_sale", doc, "verifier1", {"Fresko Accounts"}
        )
        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_maker_cannot_approve(self):
        doc = {"prepared_by": "approver_who_made", "verified_by": "verifier1", "status": "VERIFIED", "name": "FSALE-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "approve_sale", doc, "approver_who_made", {"Fresko Approver"}
        )
        self.assertFalse(allowed)
        self.assertIn("you prepared this record", reason)

    def test_verifier_cannot_approve(self):
        doc = {"prepared_by": "maker1", "verified_by": "verifier_who_approves", "status": "VERIFIED", "name": "FSALE-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "approve_sale", doc, "verifier_who_approves", {"Fresko Approver"}
        )
        self.assertFalse(allowed)
        self.assertIn("you verified this record", reason)

    def test_distinct_approver_can_approve(self):
        doc = {"prepared_by": "maker1", "verified_by": "verifier1", "status": "VERIFIED", "name": "FSALE-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "approve_sale", doc, "approver1", {"Fresko Approver"}
        )
        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_historical_mode_strictly_read_only(self):
        doc = {"prepared_by": "maker1", "status": "REVIEW_PENDING", "name": "FSALE-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "verify_sale", doc, "verifier1", {"Fresko Accounts"}, is_historical=True
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

    # FR-QA-011: Commercial allocation segregation tests
    def test_commercial_allocation_approve_fails_without_verifier(self):
        doc = {"prepared_by": "maker1", "state": "PROPOSED", "verified_by": None, "name": "FALLOC-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "approve_sale_outward_allocation", doc, "approver1", {"Fresko Approver"}
        )
        self.assertFalse(allowed)
        self.assertIn("missing verified_by", reason)

    def test_commercial_allocation_approve_fails_if_maker_equals_verifier(self):
        doc = {"prepared_by": "same_user", "verified_by": "same_user", "state": "PROPOSED", "name": "FALLOC-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "approve_sale_outward_allocation", doc, "approver1", {"Fresko Approver"}
        )
        self.assertFalse(allowed)
        self.assertIn("Maker and verifier cannot be the same user", reason)

    def test_commercial_allocation_approve_fails_if_approver_is_maker(self):
        doc = {"prepared_by": "user1", "verified_by": "user2", "state": "PROPOSED", "name": "FALLOC-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "approve_sale_outward_allocation", doc, "user1", {"Fresko Approver"}
        )
        self.assertFalse(allowed)
        self.assertIn("you prepared this allocation", reason)

    def test_commercial_allocation_approve_fails_if_approver_is_verifier(self):
        doc = {"prepared_by": "user1", "verified_by": "user2", "state": "PROPOSED", "name": "FALLOC-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "approve_sale_outward_allocation", doc, "user2", {"Fresko Approver"}
        )
        self.assertFalse(allowed)
        self.assertIn("you verified this allocation", reason)

    def test_commercial_allocation_approve_succeeds_with_distinct_trio(self):
        doc = {"prepared_by": "user1", "verified_by": "user2", "state": "PROPOSED", "name": "FALLOC-001"}
        allowed, reason = self.op_mod.check_action_eligibility(
            "approve_sale_outward_allocation", doc, "user3", {"Fresko Approver"}
        )
        self.assertTrue(allowed)
        self.assertIsNone(reason)


class TestOperatorOutwardCapacity(OperatorContractOfflineBase):
    """Test FR-QA-012 canonical Outward capacity calculations."""

    def test_posted_outward_zero_allocations_eligible(self):
        self.frappe.get_list = lambda doctype, **kwargs: (
            [{"line_key": "L1", "qty": "100", "uom": "BOX"}] if doctype == "Fresko Outward Line" else []
        )
        cap = self.op_mod.compute_outward_capacity("OUT-001", "ACME")
        self.assertTrue(cap["is_allocatable"])
        self.assertEqual(cap["capacity_state"], "UNALLOCATED")
        self.assertEqual(cap["remaining_qty"], Decimal("100"))
        self.assertEqual(cap["total_qty"], Decimal("100"))

    def test_partially_allocated_outward_reflects_remaining(self):
        def mock_get_list(doctype, **kwargs):
            if doctype == "Fresko Outward Line":
                return [{"line_key": "L1", "qty": "100", "uom": "BOX"}]
            elif doctype == "Fresko Sale Outward Allocation":
                return [{"outward_line_key": "L1", "qty": "40", "state": "APPROVED", "reversed_by": None}]
            return []
        self.frappe.get_list = mock_get_list
        cap = self.op_mod.compute_outward_capacity("OUT-001", "ACME")
        self.assertTrue(cap["is_allocatable"])
        self.assertEqual(cap["capacity_state"], "PARTIAL")
        self.assertEqual(cap["remaining_qty"], Decimal("60"))
        self.assertEqual(cap["allocated_qty"], Decimal("40"))

    def test_fully_allocated_outward_excluded(self):
        def mock_get_list(doctype, **kwargs):
            if doctype == "Fresko Outward Line":
                return [{"line_key": "L1", "qty": "100", "uom": "BOX"}]
            elif doctype == "Fresko Sale Outward Allocation":
                return [{"outward_line_key": "L1", "qty": "100", "state": "APPROVED", "reversed_by": None}]
            return []
        self.frappe.get_list = mock_get_list
        cap = self.op_mod.compute_outward_capacity("OUT-001", "ACME")
        self.assertFalse(cap["is_allocatable"])
        self.assertEqual(cap["capacity_state"], "EXHAUSTED")
        self.assertEqual(cap["remaining_qty"], Decimal("0"))

    def test_reversed_allocation_frees_capacity(self):
        def mock_get_list(doctype, **kwargs):
            if doctype == "Fresko Outward Line":
                return [{"line_key": "L1", "qty": "100", "uom": "BOX"}]
            elif doctype == "Fresko Sale Outward Allocation":
                return [
                    {"outward_line_key": "L1", "qty": "40", "state": "REVERSED", "reversed_by": "user1"},
                    {"outward_line_key": "L1", "qty": "30", "state": "APPROVED", "reversed_by": None},
                ]
            return []
        self.frappe.get_list = mock_get_list
        cap = self.op_mod.compute_outward_capacity("OUT-001", "ACME")
        self.assertTrue(cap["is_allocatable"])
        self.assertEqual(cap["capacity_state"], "PARTIAL")
        self.assertEqual(cap["remaining_qty"], Decimal("70"))
        self.assertEqual(cap["allocated_qty"], Decimal("30"))

    def test_inaccessible_sale_allocation_consumes_capacity(self):
        # Even if linked Sale cannot be read by operator, the allocation still reduces remaining stock!
        def mock_get_list(doctype, **kwargs):
            if doctype == "Fresko Outward Line":
                return [{"line_key": "L1", "qty": "100", "uom": "BOX"}]
            elif doctype == "Fresko Sale Outward Allocation":
                return [{"sale": "CONFIDENTIAL-SALE", "outward_line_key": "L1", "qty": "50", "state": "APPROVED", "reversed_by": None}]
            return []
        self.frappe.get_list = mock_get_list
        cap = self.op_mod.compute_outward_capacity("OUT-001", "ACME")
        self.assertTrue(cap["is_allocatable"])
        self.assertEqual(cap["remaining_qty"], Decimal("50"))

    def test_reversed_outward_movement_excluded(self):
        def mock_get_list(doctype, filters=None, **kwargs):
            if doctype == "Fresko Outward" and filters and filters.get("movement_type") == "REVERSAL":
                return [{"name": "OUT-REV-001"}]
            return []
        self.frappe.get_list = mock_get_list
        cap = self.op_mod.compute_outward_capacity("OUT-001", "ACME")
        self.assertFalse(cap["is_allocatable"])
        self.assertEqual(cap["capacity_state"], "REVERSED")


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
    """Test company authorization, live-only enforcement, schema mapping, and counts."""

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

    def test_live_feed_projection_mode_and_response_contract(self):
        self.frappe.has_permission = lambda doctype, doc=None, ptype="read": True
        self.frappe.get_list = lambda doctype, **kwargs: []
        res = self.op_mod.get_operator_action_feed(company="ACME", as_of=None)
        self.assertEqual(res["projection_mode"], "LIVE")
        self.assertEqual(res["company"], "ACME")
        self.assertEqual(res["feed_type"], "operator_action_feed")
        self.assertIn("counts", res)
        self.assertIn("sections", res)
        self.assertEqual(res["records_loaded"], 0)
        self.assertEqual(res["actionable_records"], 0)
        self.assertTrue(res["all_clear"])
        self.assertEqual(res["completeness_state"], "COMPLETE")

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

        sale_sec = next(s for s in res["sections"] if s["id"] == "commercial_verifications")
        self.assertEqual(len(sale_sec["items"]), 1)
        sale_item = sale_sec["items"][0]
        self.assertEqual(sale_item["document_name"], "FSALE-001")
        self.assertEqual(sale_item["version"], 3)
        self.assertEqual(sale_item["current_version"], 3)
        self.assertEqual(sale_item["source_evidence"], "EVID-001")
        self.assertEqual(sale_item["evidence_state"], "AVAILABLE")
        self.assertEqual(sale_item["evidence_name"], "EVID-001")

        coll_sec = next(s for s in res["sections"] if s["id"] == "collection_verifications")
        self.assertEqual(len(coll_sec["items"]), 1)
        coll_item = coll_sec["items"][0]
        self.assertEqual(coll_item["document_name"], "FCOLL-001")
        self.assertEqual(coll_item["version"], 2)
        self.assertEqual(coll_item["current_version"], 2)
        self.assertEqual(coll_item["payment_channel"], "BANK")
        self.assertEqual(coll_item["source_evidence"], "EVID-002")

    def test_confidential_sale_redacted_in_allocation_title(self):
        # FR-QA-019: Suppress confidential linked Sale identifier if unauthorized
        def perm_check(doctype, doc=None, ptype="read"):
            if doctype == "Fresko Commercial Sale" and doc == "SECRET-SALE-99":
                return False
            return True
        self.frappe.has_permission = perm_check

        def mock_get_list(doctype, **kwargs):
            if doctype == "Fresko Sale Outward Allocation":
                return [{
                    "name": "FALLOC-001",
                    "company": "ACME",
                    "sale": "SECRET-SALE-99",
                    "outward": "OUT-001",
                    "state": "PROPOSED",
                    "prepared_by": "user1",
                    "verified_by": None,
                    "qty": "50",
                    "uom": "BOX",
                    "version": 1,
                    "modified": "2026-10-08 12:00:00"
                }]
            return []
        self.frappe.get_list = mock_get_list

        res = self.op_mod.get_operator_action_feed(company="ACME")
        alloc_sec = next(s for s in res["sections"] if s["id"] == "commercial_allocation_reviews")
        item = alloc_sec["items"][0]
        self.assertNotIn("SECRET-SALE-99", item["human_title"])
        self.assertIn("[Restricted Sale]", item["human_title"])

    def test_fresko_login_css_does_not_decorate_403(self):
        # FR-QA-008: Verify .page-card-head::after is strictly scoped to login page
        css_path = _root / "fresko_universe" / "public" / "css" / "fresko_login.css"
        css_text = css_path.read_text(encoding="utf-8")
        # Ensure there is NO bare unscoped .page-card-head::after
        matches = [line for line in css_text.splitlines() if line.strip().startswith(".page-card-head::after")]
        self.assertEqual(len(matches), 0, "Bare .page-card-head::after rule found; must be scoped to login DOM")


if __name__ == "__main__":
    unittest.main()
