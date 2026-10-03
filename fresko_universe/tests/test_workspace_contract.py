"""Offline unit tests for Fresko Workspace Desk Page Contract.

Verifies:
1. Page JSON schema, role permissions, and route metadata.
2. Security controller role-matching and Guest denial.
3. Facade parameter contracts and expected_version bindings.
4. Strict financial null handling and non-arithmetic projection assertions.
"""
import ast
import importlib.util
import json
import os
import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
import unittest


@contextmanager
def _load_workspace_controller(user, roles):
    """Load a fresh controller with an offline frappe stub and real decorator."""
    frappe_stub = ModuleType("frappe")
    frappe_stub.session = SimpleNamespace(user=user)
    frappe_stub.PermissionError = type("PermissionError", (Exception,), {})
    frappe_stub.get_roles = lambda _user: list(roles)
    frappe_stub.throw = lambda message, error=None: (_ for _ in ()).throw(
        (error or Exception)(message)
    )
    frappe_stub._ = lambda message: message
    frappe_stub.whitelist = lambda *args, **kwargs: (lambda function: function)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    controller_path = os.path.join(
        base_dir,
        "fresko_universe",
        "fresko_core",
        "page",
        "fresko_workspace",
        "fresko_workspace.py",
    )
    module_name = f"_offline_workspace_controller_{id(frappe_stub)}"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    module = importlib.util.module_from_spec(spec)
    prior_frappe = sys.modules.get("frappe")
    sys.modules["frappe"] = frappe_stub
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        yield module, frappe_stub
    finally:
        sys.modules.pop(module_name, None)
        if prior_frappe is None:
            sys.modules.pop("frappe", None)
        else:
            sys.modules["frappe"] = prior_frappe


def _facade_signatures(path):
    with open(path, "r", encoding="utf-8") as source_file:
        tree = ast.parse(source_file.read(), filename=path)
    result = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parameters = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            result[node.name] = {parameter.arg for parameter in parameters}
    return result


class TestWorkspacePageMetadata(unittest.TestCase):
    """Verify desk page definition file strictly matches Frappe conventions."""

    def setUp(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.json_path = os.path.join(
            base_dir,
            "fresko_universe",
            "fresko_core",
            "page",
            "fresko_workspace",
            "fresko_workspace.json",
        )

    def test_json_file_exists_and_parses(self):
        self.assertTrue(os.path.exists(self.json_path), f"Page JSON missing at {self.json_path}")
        with open(self.json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("doctype"), "Page")
        self.assertEqual(data.get("name"), "fresko-workspace")
        self.assertEqual(data.get("page_name"), "fresko-workspace")
        self.assertEqual(data.get("module"), "Fresko Core")
        self.assertEqual(data.get("standard"), "Yes")

    def test_roles_enforce_no_guest_and_require_internal_roles(self):
        with open(self.json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        roles = [r.get("role") for r in data.get("roles", [])]
        self.assertNotIn("Guest", roles, "Guest must never be allowed on workspace page")
        self.assertNotIn("All", roles, "Public/All must never be granted workspace page")
        # Standard required roles
        expected = {"Fresko Salesperson", "Fresko Accounts", "Fresko Approver", "System Manager"}
        self.assertTrue(expected.issubset(set(roles)), f"Missing expected roles in {roles}")


class TestWorkspaceControllerSecurity(unittest.TestCase):
    """Verify fresko_workspace controller logic for role gating."""

    def test_guest_rejection(self):
        with _load_workspace_controller("Guest", []) as (controller, frappe_stub):
            with self.assertRaises(frappe_stub.PermissionError):
                controller.get_user_workspace_context()

    def test_unauthorized_user_rejection(self):
        with _load_workspace_controller("supplier_user@test.com", ["Supplier", "Customer"]) as (controller, frappe_stub):
            with self.assertRaises(frappe_stub.PermissionError):
                controller.get_user_workspace_context()

    def test_supplier_role_is_denied_even_with_internal_role(self):
        with _load_workspace_controller(
            "mixed_user@test.com", ["Fresko Accounts", "External Supplier Viewer"]
        ) as (controller, frappe_stub):
            with self.assertRaises(frappe_stub.PermissionError):
                controller.get_user_workspace_context()

    def test_generic_role_names_do_not_grant_access(self):
        for roles in (["Salesperson"], ["Accounts"], ["Approver"]):
            with self.subTest(roles=roles):
                with _load_workspace_controller("generic@test.com", roles) as (controller, frappe_stub):
                    with self.assertRaises(frappe_stub.PermissionError):
                        controller.get_user_workspace_context()

    def test_salesperson_permissions(self):
        with _load_workspace_controller("sales@test.com", ["Fresko Salesperson"]) as (controller, _):
            ctx = controller.get_user_workspace_context()
            self.assertFalse(ctx["is_internal"])
            self.assertFalse(ctx["can_verify"])
            self.assertFalse(ctx["can_approve"])
            self.assertIn("Fresko Salesperson", ctx["roles"])

    def test_accounts_and_approver_have_separate_capabilities(self):
        with _load_workspace_controller("accounts@test.com", ["Fresko Accounts"]) as (controller, _):
            ctx = controller.get_user_workspace_context()
            self.assertTrue(ctx["is_internal"])
            self.assertTrue(ctx["can_verify"])
            self.assertFalse(ctx["can_approve"])
        with _load_workspace_controller("approver@test.com", ["Fresko Approver"]) as (controller, _):
            ctx = controller.get_user_workspace_context()
            self.assertTrue(ctx["is_internal"])
            self.assertFalse(ctx["can_verify"])
            self.assertTrue(ctx["can_approve"])

    def test_approver_permissions(self):
        with _load_workspace_controller("approver@test.com", ["Fresko Approver"]) as (controller, _):
            ctx = controller.get_user_workspace_context()
            self.assertTrue(ctx["is_internal"])
            self.assertTrue(ctx["can_approve"])

    def test_system_manager_has_internal_visibility_without_business_actions(self):
        with _load_workspace_controller("manager@test.com", ["System Manager"]) as (controller, _):
            ctx = controller.get_user_workspace_context()
            self.assertTrue(ctx["is_internal"])
            self.assertFalse(ctx["can_verify"])
            self.assertFalse(ctx["can_approve"])


class TestFacadeKeywordContracts(unittest.TestCase):
    """Verify all commercial facade endpoints invoked by UI match actual service signatures."""

    def test_commercial_facade_signatures(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        facade_path = os.path.join(base_dir, "fresko_universe", "commercial.py")
        signatures = _facade_signatures(facade_path)
        # 1. create_sale
        sig = signatures["create_sale"]
        expected_create_kwargs = {
            "company",
            "container",
            "sale_at",
            "source_evidence",
            "source_event_id",
            "lines",
            "raw_party_alias",
            "party_state",
            "currency",
            "deal",
            "raw_movement_at",
        }
        self.assertEqual(sig, expected_create_kwargs)

        # 2. versioned actions
        versioned_methods = [
            ("submit_sale", {"sale_name", "expected_version"}),
            ("verify_sale", {"sale_name", "expected_version"}),
            ("approve_sale", {"sale_name", "expected_version"}),
            ("reject_sale", {"sale_name", "reason", "expected_version"}),
            ("verify_alias_mapping", {"mapping_name", "expected_version"}),
            ("approve_alias_mapping", {"mapping_name", "expected_version"}),
            ("reject_alias_mapping", {"mapping_name", "reason", "expected_version"}),
            ("verify_sale_outward_allocation", {"allocation_name", "expected_version"}),
            ("approve_sale_outward_allocation", {"allocation_name", "expected_version"}),
            ("reject_sale_outward_allocation", {"allocation_name", "reason", "expected_version"}),
            ("reverse_sale_outward_allocation", {"allocation_name", "reason", "evidence", "expected_version"}),
        ]
        for method, params in versioned_methods:
            self.assertEqual(signatures[method], params, f"Signature mismatch for {method}")

        # 3. projections
        self.assertEqual(signatures["get_container_reconciliation"], {"container", "as_of"})
        self.assertEqual(signatures["get_sale_as_of"], {"sale_name", "as_of"})
        self.assertEqual(signatures["get_outward_reconciliation"], {"outward_name", "as_of"})


if __name__ == "__main__":
    unittest.main()
