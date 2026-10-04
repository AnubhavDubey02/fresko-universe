"""Offline contract checks for the Container Quantity Assertion implementation."""
from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DT = ROOT / "fresko_universe" / "fresko_core" / "doctype" / "fresko_container_quantity_assertion" / "fresko_container_quantity_assertion.json"
SERVICE = ROOT / "fresko_universe" / "fresko_core" / "services" / "quantity_assertion_service.py"
CONTROLLER = ROOT / "fresko_universe" / "fresko_core" / "doctype" / "fresko_container_quantity_assertion" / "fresko_container_quantity_assertion.py"
UPGRADE_PROOF = ROOT.parent / "scripts" / "prove_phase2a_outward_upgrade.py"
EXCEPTION_DT = ROOT / "fresko_universe" / "fresko_core" / "doctype" / "fresko_exception" / "fresko_exception.json"
EXCEPTION_PY = ROOT / "fresko_universe" / "fresko_core" / "doctype" / "fresko_exception" / "fresko_exception.py"
VARIANCE_PROOF = ROOT.parent / "scripts" / "prove_physical_variance_upgrade.py"
WRAPPERS = ROOT / "fresko_universe" / "quantity_assertion.py"
HOOKS = ROOT / "fresko_universe" / "hooks.py"
PERMISSIONS = ROOT / "fresko_universe" / "permissions.py"


class TestQuantityAssertionStaticContract(unittest.TestCase):
    def test_schema_and_service_keep_quantity_as_an_immutable_fact(self):
        definition = json.loads(DT.read_text(encoding="utf-8"))
        fields = {field["fieldname"]: field for field in definition["fields"]}
        self.assertEqual(definition["name"], "Fresko Container Quantity Assertion")
        self.assertTrue(fields["container"]["reqd"])
        self.assertTrue(fields["raw_value"]["reqd"])
        self.assertTrue(fields["evidence"]["reqd"])
        self.assertTrue(fields["source_fact_id"]["reqd"])
        self.assertTrue(fields["assertion_key"]["unique"])
        self.assertIn("DECLARED_SHIPPING", fields["basis"]["options"])
        self.assertIn("OPERATING_INWARD", fields["basis"]["options"])
        service = SERVICE.read_text(encoding="utf-8")
        controller = CONTROLLER.read_text(encoding="utf-8")
        for token in ("canonical_quantity", "lock_container_for_update", "superseded_by", "OPEN_VARIANCE", "UNRESOLVED", '"evidence": evidence'):
            self.assertIn(token, service)
        self.assertIn("Quantity exponent notation is not permitted", controller)
        self.assertNotIn("inward_qty =", service)

    def test_upgrade_proof_preserves_operational_scalars(self):
        proof = UPGRADE_PROOF.read_text(encoding="utf-8")
        for token in ("QUANTITY_ASSERTION_DOCTYPE", "container_snapshot", "assertion_key", "Migration changed existing Container.inward_qty"):
            self.assertIn(token, proof)

    def test_permission_hooks_are_service_only_and_maker_scoped(self):
        hooks, permissions = HOOKS.read_text(encoding="utf-8"), PERMISSIONS.read_text(encoding="utf-8")
        self.assertIn("quantity_assertion_permission_query", hooks)
        self.assertIn("quantity_assertion_has_permission", hooks)
        for token in ("def quantity_assertion_permission_query", "prepared_by", "flags, \"in_service\"", "ptype == \"delete\""):
            self.assertIn(token, permissions)


class TestPhysicalVarianceStaticContract(unittest.TestCase):
    def test_exception_schema_has_variance_fields(self):
        definition = json.loads(EXCEPTION_DT.read_text(encoding="utf-8"))
        fields = {field["fieldname"]: field for field in definition["fields"]}
        for fieldname in ("declared_quantity_assertion", "operating_quantity_assertion", "variance_quantity", "variance_uom", "variance_key"):
            self.assertIn(fieldname, fields, f"Missing field: {fieldname}")
            self.assertTrue(fields[fieldname].get("read_only"), f"{fieldname} must be read_only")
        self.assertEqual(fields["declared_quantity_assertion"]["fieldtype"], "Link")
        self.assertEqual(fields["declared_quantity_assertion"]["options"], "Fresko Container Quantity Assertion")
        self.assertEqual(fields["operating_quantity_assertion"]["fieldtype"], "Link")
        self.assertEqual(fields["operating_quantity_assertion"]["options"], "Fresko Container Quantity Assertion")
        self.assertEqual(fields["variance_quantity"]["fieldtype"], "Data")
        self.assertEqual(fields["variance_uom"]["fieldtype"], "Link")
        self.assertEqual(fields["variance_uom"]["options"], "UOM")
        self.assertEqual(fields["variance_key"]["fieldtype"], "Data")
        self.assertEqual(fields["variance_key"]["unique"], 1)

    def test_exception_controller_has_quantity_service_guard(self):
        code = EXCEPTION_PY.read_text(encoding="utf-8")
        self.assertIn("in_quantity_service", code)
        self.assertIn("Quantity variance Exceptions can be changed only by the controlled quantity service", code)
        self.assertIn("variance_quantity", code)
        self.assertIn("variance_key", code)
        self.assertIn("is immutable once set", code)

    def test_service_has_physical_variance_functions(self):
        code = SERVICE.read_text(encoding="utf-8")
        self.assertIn("def _ensure_physical_variance", code)
        self.assertIn("def ensure_physical_variance", code)
        self.assertIn("def resolve_physical_variance", code)
        self.assertIn("VARIANCE_KEY_VERSION", code)
        self.assertIn("fresko-physical-variance:v1", code)
        self.assertIn("physical_variance_exception", code)
        self.assertIn("_variance_key", code)

    def test_wrappers_expose_ensure_and_resolve(self):
        code = WRAPPERS.read_text(encoding="utf-8")
        self.assertIn("def ensure_physical_variance", code)
        self.assertIn("def resolve_physical_variance", code)
        self.assertIn("@frappe.whitelist()", code)

    def test_variance_upgrade_proof_exists_and_has_stages(self):
        self.assertTrue(VARIANCE_PROOF.exists(), "prove_physical_variance_upgrade.py is missing")
        code = VARIANCE_PROOF.read_text(encoding="utf-8")
        for stage in ("seed_phase1", "verify_first_migrate", "verify_second_migrate"):
            self.assertIn(f"def {stage}", code)
        self.assertIn("variance_key", code)
        self.assertIn("PHYVAR-UPGRADE", code)

    def test_projection_includes_physical_variance_exception_key(self):
        code = SERVICE.read_text(encoding="utf-8")
        self.assertIn('"physical_variance_exception"', code)
        self.assertNotIn("Outward-linked service and is intentionally not invoked", code)

    def test_service_never_mutates_inward_qty(self):
        code = SERVICE.read_text(encoding="utf-8")
        self.assertNotIn("inward_qty =", code)
