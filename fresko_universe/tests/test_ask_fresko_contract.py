"""Offline contract tests for the deterministic read-only assistant boundary."""

import importlib.util
import os
import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
import unittest


@contextmanager
def _load_boundary(roles, user="reader@example.test"):
    frappe_stub = ModuleType("frappe")
    frappe_stub.session = SimpleNamespace(user=user)
    frappe_stub.PermissionError = type("PermissionError", (Exception,), {})
    frappe_stub.ValidationError = type("ValidationError", (Exception,), {})
    frappe_stub.get_roles = lambda _user: list(roles)

    calls = []
    commercial = ModuleType("fresko_universe.commercial")
    money = ModuleType("fresko_universe.money")
    for module, names in (
        (commercial, ("get_container_reconciliation", "get_sale_as_of", "get_outward_reconciliation")),
                 (money, ("get_sale_receivable", "get_container_receivable", "get_customer_receivable",
                 "get_unallocated_collections", "get_bank_pending_collections", "get_open_money_exceptions",
                 "get_collection_position")),
    ):
        for name in names:
            def reader(_name, **kwargs):
                calls.append((_name, kwargs))
                return {"read": _name}
            setattr(module, name, lambda _reader_name=name, **kwargs: reader(_reader_name, **kwargs))
    package = ModuleType("fresko_universe")
    package.commercial, package.money = commercial, money
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "fresko_universe", "ask_fresko.py")
    module_name = f"_offline_ask_fresko_{id(package)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    names = ("frappe", "fresko_universe", "fresko_universe.commercial", "fresko_universe.money", module_name)
    prior = {name: sys.modules.get(name) for name in names}
    sys.modules.update({
        "frappe": frappe_stub,
        "fresko_universe": package,
        "fresko_universe.commercial": commercial,
        "fresko_universe.money": money,
        module_name: module,
    })
    try:
        spec.loader.exec_module(module)
        yield module, frappe_stub, calls
    finally:
        for name, old in prior.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


class TestAskFreskoContract(unittest.TestCase):
    def test_fixed_catalog_and_safe_dispatch(self):
        with _load_boundary(["Fresko Salesperson"]) as (api, _, calls):
            names = {tool["name"] for tool in api.list_tools()}
            self.assertEqual(names, {"container_reconciliation", "sale_as_of", "outward_reconciliation"})
            result = api.run_tool("container_reconciliation", {"container": "CONT-1"})
            self.assertEqual(result, {"read": "get_container_reconciliation"})
            self.assertEqual(calls, [("get_container_reconciliation", {"container": "CONT-1"})])

    def test_unknown_tool_and_extra_or_missing_arguments_are_rejected(self):
        with _load_boundary(["Fresko Accounts"]) as (api, frappe_stub, calls):
            for name, args in (("anything", {}), ("submit_sale", {"sale_name": "S-1"}),
                               ("sale_as_of", {"sale_name": "S-1", "as_of": "2026-01-01", "mode": "write"}),
                               ("sale_as_of", {"sale_name": "S-1"}),
                               ("open_money_exceptions", {"company": "Fresko Co", "as_of": "2026-01-01"})):
                with self.subTest(name=name, args=args):
                    with self.assertRaises(frappe_stub.ValidationError):
                        api.run_tool(name, args)
            self.assertEqual(calls, [])

    def test_supplier_and_mixed_supplier_roles_are_denied(self):
        for roles in (["Supplier"], ["Fresko Accounts", "External Supplier Viewer"]):
            with self.subTest(roles=roles):
                with _load_boundary(roles) as (api, frappe_stub, _):
                    with self.assertRaises(frappe_stub.PermissionError):
                        api.list_tools()
                    with self.assertRaises(frappe_stub.PermissionError):
                        api.run_tool("container_reconciliation", {"container": "CONT-1"})

    def test_money_tools_are_only_listed_and_runnable_for_accounts_or_approver(self):
        for roles in (["Fresko Salesperson"], ["System Manager"]):
            with _load_boundary(roles) as (api, frappe_stub, _):
                self.assertFalse({tool["name"] for tool in api.list_tools()} & {"sale_receivable", "collection_position"})
                with self.assertRaises(frappe_stub.PermissionError):
                    api.run_tool("sale_receivable", {"sale": "SALE-1"})
        for role in ("Fresko Accounts", "Fresko Approver"):
            with _load_boundary([role]) as (api, _, calls):
                names = {tool["name"] for tool in api.list_tools()}
                self.assertTrue({"sale_receivable", "collection_position", "open_money_exceptions"}.issubset(names))
                api.run_tool("sale_receivable", {"sale": "SALE-1"})
                api.run_tool("open_money_exceptions", {"company": "Fresko Co"})
                self.assertEqual(calls, [
                    ("get_sale_receivable", {"sale": "SALE-1"}),
                    ("get_open_money_exceptions", {"company": "Fresko Co"}),
                ])


if __name__ == "__main__":
    unittest.main()
