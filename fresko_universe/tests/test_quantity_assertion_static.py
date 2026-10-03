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
