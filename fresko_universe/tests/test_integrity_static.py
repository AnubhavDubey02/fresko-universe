"""Offline static checks for the integrity checker implementation."""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEAL_DT = ROOT / "fresko_universe" / "fresko_core" / "doctype" / "fresko_integrity_seal" / "fresko_integrity_seal.json"
SEAL_PY = ROOT / "fresko_universe" / "fresko_core" / "doctype" / "fresko_integrity_seal" / "fresko_integrity_seal.py"
SERVICE = ROOT / "fresko_universe" / "fresko_core" / "services" / "integrity_service.py"
OUTWARD_DT = ROOT / "fresko_universe" / "fresko_core" / "doctype" / "fresko_outward" / "fresko_outward.json"
OUTWARD_LINE_DT = ROOT / "fresko_universe" / "fresko_core" / "doctype" / "fresko_outward_line" / "fresko_outward_line.json"
FA_DT = ROOT / "fresko_universe" / "fresko_core" / "doctype" / "fresko_field_assertion" / "fresko_field_assertion.json"
QA_DT = ROOT / "fresko_universe" / "fresko_core" / "doctype" / "fresko_container_quantity_assertion" / "fresko_container_quantity_assertion.json"
HOOKS = ROOT / "fresko_universe" / "hooks.py"
PROOF = ROOT.parent / "scripts" / "prove_integrity_seal_upgrade.py"
PROOFS_JSON = ROOT.parent / "scripts" / "schema_migration_proofs.json"


def _parse_tuple_from_source(filepath: Path, varname: str) -> tuple[str, ...]:
    """Parse a module-level tuple assignment from a Python source file using ast."""
    tree = ast.parse(filepath.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == varname:
                    if isinstance(node.value, ast.Tuple):
                        return tuple(
                            elt.value for elt in node.value.elts
                            if isinstance(elt, ast.Constant)
                        )
    return ()


class TestIntegritySealStaticContract(unittest.TestCase):
    def test_seal_json_fields_types_readonly_unique(self):
        definition = json.loads(SEAL_DT.read_text(encoding="utf-8"))
        self.assertEqual(definition["name"], "Fresko Integrity Seal")
        self.assertEqual(definition["autoname"], "hash")
        fields = {f["fieldname"]: f for f in definition["fields"]}
        for fieldname in fields:
            self.assertTrue(fields[fieldname].get("read_only"),
                            f"{fieldname} must be read_only")
        self.assertTrue(fields["seal_key"].get("unique"))
        self.assertTrue(fields["record_doctype"]["reqd"])
        self.assertTrue(fields["record_name"]["reqd"])
        self.assertTrue(fields["seal_key"]["reqd"])
        self.assertTrue(fields["seal_version"]["reqd"])
        self.assertTrue(fields["payload_sha256"]["reqd"])
        self.assertTrue(fields["sealed_at"]["reqd"])
        self.assertEqual(fields["record_doctype"]["fieldtype"], "Select")
        self.assertIn("Fresko Outward", fields["record_doctype"]["options"])
        self.assertIn("Fresko Field Assertion", fields["record_doctype"]["options"])
        self.assertIn("Fresko Container Quantity Assertion", fields["record_doctype"]["options"])
        self.assertEqual(fields["container"]["fieldtype"], "Link")
        self.assertEqual(fields["container"]["options"], "Fresko Container")
        self.assertEqual(fields["mismatch_kind"]["fieldtype"], "Select")
        self.assertIn("PAYLOAD_CHANGED", fields["mismatch_kind"]["options"])
        self.assertIn("TERMINAL_CHANGED", fields["mismatch_kind"]["options"])
        self.assertIn("RECORD_MISSING", fields["mismatch_kind"]["options"])
        self.assertEqual(fields["mismatch_exception"]["fieldtype"], "Link")
        self.assertEqual(fields["mismatch_exception"]["options"], "Fresko Exception")
        # Permissions: no write/create/delete for any role.
        for perm in definition["permissions"]:
            self.assertFalse(perm.get("write"))
            self.assertFalse(perm.get("create"))
            self.assertFalse(perm.get("delete"))

    def test_outward_payload_fields_exist_in_doctype_json(self):
        ow_def = json.loads(OUTWARD_DT.read_text(encoding="utf-8"))
        ow_fields = {f["fieldname"] for f in ow_def["fields"]}
        payload_fields = _parse_tuple_from_source(SERVICE, "OUTWARD_PAYLOAD_FIELDS")
        self.assertTrue(payload_fields, "Could not parse OUTWARD_PAYLOAD_FIELDS")
        for field in payload_fields:
            self.assertIn(field, ow_fields, f"OUTWARD_PAYLOAD_FIELDS contains {field} not in Outward JSON")

    def test_outward_line_fields_exist_in_doctype_json(self):
        line_def = json.loads(OUTWARD_LINE_DT.read_text(encoding="utf-8"))
        line_fields = {f["fieldname"] for f in line_def["fields"]}
        line_fields.add("idx")  # Frappe implicit
        service_fields = _parse_tuple_from_source(SERVICE, "OUTWARD_LINE_FIELDS")
        self.assertTrue(service_fields, "Could not parse OUTWARD_LINE_FIELDS")
        for field in service_fields:
            self.assertIn(field, line_fields, f"OUTWARD_LINE_FIELDS contains {field} not in Outward Line JSON")

    def test_terminal_fields_exist_in_doctype_jsons(self):
        ow_def = json.loads(OUTWARD_DT.read_text(encoding="utf-8"))
        ow_fields = {f["fieldname"] for f in ow_def["fields"]}
        for field in _parse_tuple_from_source(SERVICE, "OUTWARD_TERMINAL_FIELDS"):
            self.assertIn(field, ow_fields, f"OUTWARD_TERMINAL_FIELDS: {field} not in Outward")

        fa_def = json.loads(FA_DT.read_text(encoding="utf-8"))
        fa_fields = {f["fieldname"] for f in fa_def["fields"]}
        for field in _parse_tuple_from_source(SERVICE, "FA_TERMINAL_FIELDS"):
            self.assertIn(field, fa_fields, f"FA_TERMINAL_FIELDS: {field} not in Field Assertion")

        qa_def = json.loads(QA_DT.read_text(encoding="utf-8"))
        qa_fields = {f["fieldname"] for f in qa_def["fields"]}
        for field in _parse_tuple_from_source(SERVICE, "QA_TERMINAL_FIELDS"):
            self.assertIn(field, qa_fields, f"QA_TERMINAL_FIELDS: {field} not in Quantity Assertion")

    def test_hooks_registers_daily_scheduler(self):
        hooks = HOOKS.read_text(encoding="utf-8")
        self.assertIn("fresko_universe.integrity.scheduled_integrity_check", hooks)
        self.assertIn("daily", hooks)

    def test_controller_has_on_trash_guard(self):
        code = SEAL_PY.read_text(encoding="utf-8")
        self.assertIn("on_trash", code)
        self.assertIn("Integrity seals cannot be deleted", code)
        self.assertIn("in_integrity_service", code)

    def test_proof_registered(self):
        self.assertTrue(PROOF.exists(), "prove_integrity_seal_upgrade.py missing")
        code = PROOF.read_text(encoding="utf-8")
        for stage in ("seed_phase1", "verify_first_migrate", "verify_second_migrate"):
            self.assertIn(f"def {stage}", code)
        registry = json.loads(PROOFS_JSON.read_text(encoding="utf-8"))
        ids = [p["id"] for p in registry["proofs"]]
        self.assertIn("integrity_seal_ledger", ids)
        self.assertEqual(ids[-1], "integrity_seal_ledger")


if __name__ == "__main__":
    unittest.main()
