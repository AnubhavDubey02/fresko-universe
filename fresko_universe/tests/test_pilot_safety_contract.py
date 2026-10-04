"""Offline behavior of pilot safety policy and real extracted service functions."""
import __future__
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

APP_ROOT = Path(__file__).resolve().parents[1]
INNER_PKG = APP_ROOT / "fresko_universe"
CLOSE_POLICY_PATH = INNER_PKG / "fresko_core" / "services" / "close_policy.py"
EVIDENCE_SERVICE_PATH = INNER_PKG / "fresko_core" / "services" / "evidence_service.py"
EXCEPTION_DOCTYPE_JSON = INNER_PKG / "fresko_core" / "doctype" / "fresko_exception" / "fresko_exception.json"
ATTACHMENT_DOCTYPE_JSON = INNER_PKG / "fresko_core" / "doctype" / "fresko_evidence_attachment" / "fresko_evidence_attachment.json"


def _load_close_policy():
    spec = importlib.util.spec_from_file_location("pure_close_policy_test_mod", CLOSE_POLICY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _extract_and_exec_fn(file_path: Path, fn_name: str, exec_globals: dict):
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    fn_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    mod_ast = ast.Module(body=[fn_node], type_ignores=[])
    ast.fix_missing_locations(mod_ast)
    compiled = compile(mod_ast, filename=f"<ast_{fn_name}>", mode="exec", flags=__future__.annotations.compiler_flag)
    exec(compiled, exec_globals)
    return exec_globals[fn_name]


class TestPilotSafetyContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = _load_close_policy()

    def test_close_exception_policy_covers_doctype_enums_exactly(self):
        with open(EXCEPTION_DOCTYPE_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        field = next(f for f in data["fields"] if f["fieldname"] == "exception_type")
        options = set(line.strip() for line in field["options"].strip().split("\n") if line.strip())
        policy_keys = set(self.policy.CLOSE_EXCEPTION_POLICY.keys())
        self.assertEqual(policy_keys, options)

    def test_materiality_rules(self):
        for kind in self.policy.MATERIAL_EXCEPTION_TYPES:
            for sev in ["Info", "Low", "Medium", "High", "Material", "Critical"]:
                self.assertTrue(self.policy.exception_is_material(kind, sev))

        contextual = set(self.policy.CLOSE_EXCEPTION_POLICY.keys()) - self.policy.MATERIAL_EXCEPTION_TYPES
        self.assertEqual(contextual, {"OTHER", "IDEMPOTENCY_PAYLOAD_CONFLICT", "CONCURRENT_STATE_CONFLICT"})
        for kind in contextual:
            for sev in ["Info", "Low", "Medium", "High"]:
                self.assertFalse(self.policy.exception_is_material(kind, sev))
            for sev in ["Material", "Critical"]:
                self.assertTrue(self.policy.exception_is_material(kind, sev))

        self.assertFalse(self.policy.exception_is_material("FUTURE_UNKNOWN_TYPE", "Medium"))
        self.assertTrue(self.policy.exception_is_material("FUTURE_UNKNOWN_TYPE", "Critical"))
        self.assertEqual(self.policy.EXCEPTION_OPEN_STATUSES, frozenset({"Open", "In Progress"}))

    def test_ingest_provider_message_evidence_validation_and_forwarding(self):
        mock_frappe = MagicMock()
        mock_frappe.ValidationError = type("ValidationError", (Exception,), {})
        mock_frappe.throw.side_effect = lambda msg, exc=None: (_ for _ in ()).throw(exc(msg) if exc else Exception(msg))
        legacy_mock = MagicMock(return_value="legacy_sentinel")

        g = {"frappe": mock_frappe, "ingest_message_evidence": legacy_mock, "str": str, "dict": dict, "int": int}
        fn = _extract_and_exec_fn(EVIDENCE_SERVICE_PATH, "ingest_provider_message_evidence", g)

        # Unapproved server kwarg or unknown kwarg rejected
        with self.assertRaises(TypeError):
            fn(provider="p", provider_account_id="a", conversation_id="c", provider_message_id="m", readback_verified=True)
        self.assertEqual(legacy_mock.call_count, 0)

        with self.assertRaises(TypeError):
            fn(provider="p", provider_account_id="a", conversation_id="c", provider_message_id="m",
               manifest_status="FINALIZED", expected_attachment_count=0)
        legacy_mock.assert_not_called()

        # Empty / non-str ID validations
        bad_values = [None, "", 0, False, {}, []]
        id_kwargs = ["provider", "provider_account_id", "conversation_id", "provider_message_id"]
        for kw in id_kwargs:
            for bad in bad_values:
                call_kwargs = {"provider": "p", "provider_account_id": "a", "conversation_id": "c", "provider_message_id": "m"}
                call_kwargs[kw] = bad
                with self.assertRaises((mock_frappe.ValidationError, TypeError)):
                    fn(**call_kwargs)
        self.assertEqual(legacy_mock.call_count, 0)

        for kw in id_kwargs:
            remaining = {key: "opaque" for key in id_kwargs if key != kw}
            with self.assertRaises(TypeError):
                fn(**remaining)
        legacy_mock.assert_not_called()

        # Exact forwarding without strip/trimming
        res = fn(provider=" WhatsApp ", provider_account_id="0", conversation_id="conv\u2705", provider_message_id="123")
        self.assertEqual(res, "legacy_sentinel")
        legacy_mock.assert_called_once_with(
            provider=" WhatsApp ", provider_account_id="0", conversation_id="conv\u2705", provider_message_id="123",
            raw_payload=None, deal=None, container=None, notes=None, manifest_status="UNKNOWN",
            expected_attachment_count=-1, source_sender_id=None, source_sent_at=None, received_at=None
        )

    def test_aggregation_ast_and_behavior(self):
        tree = ast.parse(EVIDENCE_SERVICE_PATH.read_text(encoding="utf-8"))
        fn_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "aggregate_parent_evidence_status")

        # Ensure capture_status literals match attachment doctype options exactly
        with open(ATTACHMENT_DOCTYPE_JSON, "r", encoding="utf-8") as f:
            att_data = json.load(f)
        status_field = next(f for f in att_data["fields"] if f["fieldname"] == "capture_status")
        valid_child_statuses = set(line.strip() for line in status_field["options"].strip().split("\n") if line.strip())

        for node in ast.walk(fn_node):
            if isinstance(node, ast.Compare) and any(isinstance(a, ast.Attribute) and a.attr == "capture_status" for a in [node.left] + node.comparators):
                for comp in [node.left] + node.comparators:
                    if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                        self.assertIn(comp.value, valid_child_statuses)

        # Execute fn and verify logic
        mock_frappe = MagicMock()
        lock_mock = MagicMock()
        g = {"frappe": mock_frappe, "_lock_parent_evidence": lock_mock, "SimpleNamespace": SimpleNamespace}
        fn = _extract_and_exec_fn(EVIDENCE_SERVICE_PATH, "aggregate_parent_evidence_status", g)

        # Parent CONFLICT sticky: returns CONFLICT without querying child records or setting value
        lock_mock.return_value = SimpleNamespace(name="P1", overall_verification_status="CONFLICT", manifest_status="FINALIZED", expected_attachment_count=1)
        self.assertEqual(fn("P1"), "CONFLICT")
        mock_frappe.db.sql.assert_not_called()
        mock_frappe.db.set_value.assert_not_called()

        # COMPLETE when manifest FINALIZED, expected count matches readback_verified CAPTURED
        lock_mock.return_value = SimpleNamespace(name="P1", overall_verification_status="PENDING", manifest_status="FINALIZED", expected_attachment_count=1)
        mock_frappe.db.sql.return_value = [SimpleNamespace(capture_status="CAPTURED", readback_verified=1)]
        self.assertEqual(fn("P1"), "COMPLETE")

        # PENDING when readback is 0
        mock_frappe.db.sql.return_value = [SimpleNamespace(capture_status="CAPTURED", readback_verified=0)]
        self.assertEqual(fn("P1"), "PENDING")

        for state in ["PENDING", "VERIFYING", "FAILED_RETRYABLE", "SUPERSEDED"]:
            mock_frappe.db.sql.return_value = [SimpleNamespace(capture_status=state, readback_verified=0)]
            self.assertEqual(fn("P1"), "PENDING")

        # PARTIAL when child failure statuses exist
        for fail_status in ["PARTIAL", "FAILED_PERMANENT", "HASH_MISMATCH"]:
            mock_frappe.db.sql.return_value = [SimpleNamespace(capture_status=fail_status, readback_verified=0)]
            self.assertEqual(fn("P1"), "PARTIAL")

        # Never COMPLETE when manifest status UNKNOWN or expected count -1
        lock_mock.return_value = SimpleNamespace(name="P1", overall_verification_status="PENDING", manifest_status="UNKNOWN", expected_attachment_count=-1)
        mock_frappe.db.sql.return_value = [SimpleNamespace(capture_status="CAPTURED", readback_verified=1)]
        self.assertNotEqual(fn("P1"), "COMPLETE")
