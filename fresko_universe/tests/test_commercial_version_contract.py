"""Offline behavioral contract for commercial HTTP version tokens and projections."""
from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = ROOT / "fresko_universe/fresko_universe/fresko_core/services/commercial_service.py"
FACADE_PATH = ROOT / "fresko_universe/fresko_universe/commercial.py"


class ValidationError(Exception):
    pass


class PermissionError(Exception):
    pass


def _subject():
    frappe = types.ModuleType("frappe")
    frappe.local = types.SimpleNamespace(request=object())
    frappe.session = types.SimpleNamespace(user="synthetic@example.invalid")
    frappe.roles = ["Fresko Salesperson"]
    frappe.get_roles = lambda user: list(frappe.roles)
    frappe.ValidationError = ValidationError
    frappe.PermissionError = PermissionError

    def throw(message, exception=ValidationError):
        raise exception(message)

    frappe.throw = throw
    frappe.whitelist = lambda **kwargs: (lambda fn: fn)
    frappe.db = types.SimpleNamespace(sql=lambda *args, **kwargs: [])
    frappe.get_doc = lambda *args, **kwargs: None
    frappe.has_permission = lambda *args, **kwargs: True
    frappe.parse_json = json.loads
    utils = types.ModuleType("frappe.utils")
    utils.get_datetime = datetime.fromisoformat
    utils.now_datetime = lambda: datetime.fromisoformat("2026-10-04T12:00:00")

    package = types.ModuleType("fresko_universe")
    package.__path__ = []
    permissions = types.ModuleType("fresko_universe.permissions")
    permissions.evidence_has_permission = lambda *args, **kwargs: True
    core = types.ModuleType("fresko_universe.fresko_core")
    core.__path__ = []
    services = types.ModuleType("fresko_universe.fresko_core.services")
    services.__path__ = []
    package.permissions = permissions

    modules = {
        "frappe": frappe,
        "frappe.utils": utils,
        "fresko_universe": package,
        "fresko_universe.permissions": permissions,
        "fresko_universe.fresko_core": core,
        "fresko_universe.fresko_core.services": services,
    }
    dynamic_modules = (
        "fresko_universe.fresko_core.services.commercial_service",
        "fresko_universe.commercial",
    )
    original = {name: sys.modules.get(name) for name in (*modules, *dynamic_modules)}
    sys.modules.update(modules)
    try:
        service_spec = importlib.util.spec_from_file_location(
            "fresko_universe.fresko_core.services.commercial_service", SERVICE_PATH
        )
        service = importlib.util.module_from_spec(service_spec)
        sys.modules[service_spec.name] = service
        service_spec.loader.exec_module(service)
        services.commercial_service = service

        facade_spec = importlib.util.spec_from_file_location("fresko_universe.commercial", FACADE_PATH)
        facade = importlib.util.module_from_spec(facade_spec)
        sys.modules[facade_spec.name] = facade
        facade_spec.loader.exec_module(facade)
    except Exception:
        for name, previous in original.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        raise
    return frappe, service, facade, modules, original


class TestCommercialVersionContract(unittest.TestCase):
    def setUp(self):
        self.frappe, self.service, self.api, self.modules, self.original = _subject()
        self.addCleanup(self._restore_modules)
        self.specs = [
            ("submit_sale", "maker", ("SALE-1",), {}),
            ("verify_sale", "verify", ("SALE-1",), {}),
            ("approve_sale", "approve", ("SALE-1",), {}),
            ("reject_sale", "approve", ("SALE-1", "synthetic reason"), {}),
            ("supersede_sale", "maker", ("SALE-1",), {"source_event_id": "evt-1", "reason": "correction", "source_evidence": "EVIDENCE-1", "changes": {"customer": None}}),
            ("propose_rate", "maker", ("SALE-1", "line-1", "10", "EVIDENCE-1", "evt-rate", "reason"), {}),
            ("verify_rate", "verify", ("SALE-1",), {}),
            ("approve_rate", "approve", ("SALE-1",), {}),
            ("verify_alias_mapping", "verify", ("ALIAS-1",), {}),
            ("approve_alias_mapping", "approve", ("ALIAS-1",), {}),
            ("reject_alias_mapping", "approve", ("ALIAS-1", "synthetic reason"), {}),
            ("verify_sale_outward_allocation", "verify", ("ALLOC-1",), {}),
            ("approve_sale_outward_allocation", "approve", ("ALLOC-1",), {}),
            ("reject_sale_outward_allocation", "approve", ("ALLOC-1", "synthetic reason"), {}),
            ("reverse_sale_outward_allocation", "approve", ("ALLOC-1", "synthetic reason", "EVIDENCE-1"), {}),
        ]
        for name, _role, _args, _kwargs in self.specs:
            setattr(self.service, name, Mock(return_value={"accepted": True}))

    def _restore_modules(self):
        for name, previous in self.original.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    def _role_for(self, role):
        return {"maker": ["Fresko Salesperson"], "verify": ["Fresko Accounts"], "approve": ["Fresko Approver"]}[role]

    def _invoke(self, spec, token, *, token_as_positional=False):
        name, role, args, kwargs = spec
        self.frappe.roles = self._role_for(role)
        function = getattr(self.api, name)
        if token_as_positional:
            return function(*args, token, **kwargs)
        return function(*args, expected_version=token, **kwargs)

    def test_every_versioned_http_facade_accepts_canonical_tokens_and_forwards_unchanged(self):
        for spec in self.specs:
            name = spec[0]
            for token in (1, "1", 27, "27"):
                with self.subTest(endpoint=name, token=token):
                    target = getattr(self.service, name)
                    target.reset_mock()
                    self.assertEqual(self._invoke(spec, token), {"accepted": True})
                    target.assert_called_once()
                    self.assertEqual(target.call_args.kwargs["expected_version"], token)

        self.service.submit_sale.reset_mock()
        self._invoke(self.specs[0], "28", token_as_positional=True)
        self.assertEqual(self.service.submit_sale.call_args.kwargs["expected_version"], "28")

    def test_every_versioned_http_facade_rejects_missing_blank_and_malformed_tokens(self):
        invalid = (None, "", " ", "\t", True, False, 0, -1, 1.0, "0", "01", "1.0", "1e2", "+1", "-1", "١", "２")
        for spec in self.specs:
            name = spec[0]
            target = getattr(self.service, name)
            for token in invalid:
                with self.subTest(endpoint=name, token=repr(token)):
                    target.reset_mock()
                    with self.assertRaises(ValidationError):
                        self._invoke(spec, token)
                    target.assert_not_called()

    def test_actor_and_supplier_checks_precede_token_validation(self):
        self.frappe.roles = ["Fresko Approver"]
        self.service.submit_sale.reset_mock()
        with self.assertRaises(PermissionError):
            self.api.submit_sale("SALE-1", expected_version=None)
        self.service.submit_sale.assert_not_called()

        self.frappe.roles = ["Supplier User", "Fresko Approver"]
        self.service.approve_sale.reset_mock()
        with self.assertRaises(PermissionError):
            self.api.approve_sale("SALE-1", expected_version=" ")
        self.service.approve_sale.assert_not_called()

    def test_valid_stale_token_reaches_existing_service_comparison(self):
        doc = types.SimpleNamespace(version=9)
        self.service.submit_sale.side_effect = lambda *, sale_name, expected_version: self.service._expected(doc, expected_version)
        with self.assertRaisesRegex(ValidationError, "STALE_VERSION"):
            self.api.submit_sale("SALE-1", expected_version="8")

    def test_direct_python_omitted_token_remains_optional(self):
        self.frappe.local.request = None
        self.frappe.roles = []
        self.api.submit_sale("SALE-1")
        self.service.submit_sale.assert_called_once_with(sale_name="SALE-1", expected_version=None)

    def test_actual_projection_helpers_keep_current_token_separate_from_history(self):
        sale_at = "2026-10-01T10:00:00"
        events = [
            {"version": 1, "recorded_at": "2026-10-01T11:00:00", "snapshot": {"status": "DRAFT", "customer": None, "alias_mapping": None}},
            {"version": 2, "recorded_at": "2026-10-02T11:00:00", "snapshot": {"status": "REVIEW_PENDING", "customer": None, "alias_mapping": None}},
            {"version": 3, "recorded_at": "2026-10-03T11:00:00", "snapshot": {"status": "VERIFIED", "customer": None, "alias_mapping": None}},
        ]
        values = {
            "name": "SALE-1", "company": "COMPANY-1", "container": "CONTAINER-1", "sale_at": sale_at,
            "status": "VERIFIED", "movement_status": "NOT_EVIDENCED", "alias_mapping": None,
            "customer": None, "alias_resolution": "UNRESOLVED", "verified_by": "accounts@example.invalid",
            "verified_at": "2026-10-03T11:00:00", "approved_by": None, "approved_at": None,
            "superseded_by": None, "superseded_at": None, "rejection_reason": None,
            "version": 3, "decision_history": json.dumps(events),
            "source_payload": json.dumps({"lines": [{"line_key": "line-1", "price_state": "UNKNOWN", "qty": None, "amount": None}]}),
        }
        sale = types.SimpleNamespace(doctype=self.service.SALE, name="SALE-1", sale_at=sale_at,
                                     version=3, decision_history=values["decision_history"],
                                     source_payload=values["source_payload"], get=lambda key: values.get(key))
        self.service._roles = lambda *args: {"Fresko Salesperson"}
        self.service._load = lambda doctype, name: sale
        self.service._linked = lambda *args, **kwargs: None
        before = sale.decision_history

        historical = self.service.get_sale_as_of("SALE-1", "2026-10-02T12:00:00")
        self.assertEqual(historical["projection_mode"], "HISTORICAL")
        self.assertEqual(historical["status"], "REVIEW_PENDING")
        self.assertEqual(historical["version_at_cutoff"], 2)
        self.assertNotIn("current_version", historical)

        before_history = self.service.get_sale_as_of("SALE-1", "2026-10-01T10:30:00")
        self.assertFalse(before_history["exists"])
        self.assertIsNone(before_history["version_at_cutoff"])
        self.assertNotIn("current_version", before_history)

        order = []
        original_now = self.service._now
        self.service._load = lambda doctype, name: (order.append("load"), sale)[1]
        self.service._now = lambda: (order.append("now"), original_now())[1]
        current = self.service.get_sale_current("SALE-1")
        self.assertEqual(current["projection_mode"], "LIVE")
        self.assertEqual(current["status"], "VERIFIED")
        self.assertEqual(current["current_version"], 3)
        self.assertEqual(current["version_at_cutoff"], 3)
        self.assertLess(order.index("load"), order.index("now"), "Current cutoff must be captured after the Sale is locked")
        self.assertEqual(sale.decision_history, before, "Projection reads must not append or rewrite history")


if __name__ == "__main__":
    unittest.main()
