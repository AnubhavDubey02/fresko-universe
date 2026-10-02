"""Bench integration gates for the immutable Container Quantity Assertion ledger.

Run with: bench --site <site> run-tests --app fresko_universe --module
fresko_universe.tests.test_container_quantity_assertion
"""
from __future__ import annotations

import frappe
import threading
from queue import Queue
from frappe.tests.utils import FrappeTestCase

from fresko_universe import quantity_assertion
from fresko_universe.tests.test_phase2a_outward import _ensure_user
from fresko_universe.tests.utils import ensure_masters, make_container


class TestContainerQuantityAssertion(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.masters = ensure_masters()
        cls.maker = _ensure_user("quantity_assertion_maker@example.com", ["Fresko Salesperson", "Fresko Approver"])
        cls.checker = _ensure_user("quantity_assertion_checker@example.com", ["Fresko Approver"])

    def setUp(self):
        frappe.set_user("Administrator")

    def _evidence(self, container, label):
        return frappe.get_doc({"doctype": "Fresko Evidence", "evidence_type": "Note", "container": container.name, "notes": f"quantity assertion: {label}"}).insert(ignore_permissions=True)

    def _create(self, container, evidence, source_id, *, basis="DECLARED_SHIPPING", quantity="3060", uom=None, supersedes=None):
        frappe.set_user(self.maker)
        return quantity_assertion.create(
            container=container.name, basis=basis, raw_value=str(quantity) if quantity is not None else "unknown from source",
            quantity=quantity, uom=uom if uom is not None else self.masters["uom"], raw_uom=self.masters["uom"],
            evidence=evidence.name, effective_at="2026-10-03 10:00:00", provenance="SOURCE_EXTRACTED",
            reason="integration assertion", source_fact_id=source_id, supersedes=supersedes,
        )

    def _submit(self, name):
        frappe.set_user(self.maker)
        return quantity_assertion.submit(name)

    def _activate(self, name):
        frappe.set_user(self.checker)
        return quantity_assertion.review(name, "ACTIVATE")

    def _two_connection_workers(self, worker):
        site, barrier, outcomes = frappe.local.site, threading.Barrier(2), Queue()
        def run(name):
            frappe.init(site=site)
            frappe.connect()
            try:
                frappe.set_user(self.checker)
                barrier.wait(timeout=20)
                worker(name)
                frappe.db.commit()
                outcomes.put((name, "OK"))
            except Exception:
                frappe.db.rollback()
                outcomes.put((name, "DENIED"))
            finally:
                frappe.destroy()
        return outcomes, run

    def test_lifecycle_replay_unknown_and_uom_gate(self):
        container = make_container(self.masters, container_no=f"QTY-{frappe.generate_hash(length=6)}", inward_qty=3056)
        evidence = self._evidence(container, "lifecycle")
        created = self._create(container, evidence, "shipping-1")
        self.assertEqual(frappe.db.get_value("Fresko Container Quantity Assertion", created["name"], "status"), "Draft")
        self.assertTrue(self._submit(created["name"]))
        frappe.set_user(self.maker)
        with self.assertRaises(frappe.PermissionError):
            quantity_assertion.review(created["name"], "ACTIVATE")
        self._activate(created["name"])
        self.assertEqual(frappe.db.get_value("Fresko Container Quantity Assertion", created["name"], "status"), "Active")
        frappe.set_user(self.maker)
        self.assertTrue(self._create(container, evidence, "shipping-1")["replayed"])
        with self.assertRaises(frappe.UniqueValidationError):
            self._create(container, evidence, "shipping-1", quantity="3061")
        unknown = self._create(container, evidence, "customs-unknown", basis="CUSTOMS_DECLARED", quantity=None, uom=None)
        self.assertIsNone(frappe.db.get_value("Fresko Container Quantity Assertion", unknown["name"], "quantity"))
        with self.assertRaises(frappe.ValidationError):
            self._create(container, evidence, "customs-no-uom", basis="CUSTOMS_DECLARED", quantity="1", uom="")

    def test_projection_supersession_and_cross_uom(self):
        container = make_container(self.masters, container_no=f"QTY-{frappe.generate_hash(length=6)}", inward_qty=3056)
        original_inward = frappe.db.get_value("Fresko Container", container.name, "inward_qty")
        evidence = self._evidence(container, "projection")
        declared = self._create(container, evidence, "shipping-3060", quantity="3060")
        operating = self._create(container, evidence, "operating-3056", basis="OPERATING_INWARD", quantity="3056")
        self._submit(declared["name"]); self._activate(declared["name"])
        self._submit(operating["name"]); self._activate(operating["name"])
        frappe.set_user("Administrator")
        projection = quantity_assertion.reconciliation_projection(container.name)
        self.assertEqual(projection["variance"], "4")
        self.assertEqual(projection["reconciliation_status"], "OPEN_VARIANCE")
        self.assertEqual(frappe.db.get_value("Fresko Container", container.name, "inward_qty"), original_inward)
        successor = self._create(container, evidence, "shipping-3060-corrected", quantity="3060", supersedes=declared["name"])
        self._submit(successor["name"]); self._activate(successor["name"])
        self.assertEqual(frappe.db.get_value("Fresko Container Quantity Assertion", declared["name"], "status"), "Superseded")
        self.assertEqual(frappe.db.count("Fresko Container Quantity Assertion", {"container": container.name, "basis": "DECLARED_SHIPPING", "uom": self.masters["uom"], "status": "Active"}), 1)
        other_uom = frappe.get_doc({"doctype": "UOM", "uom_name": f"QTY-UOM-{frappe.generate_hash(length=6)}", "must_be_whole_number": 0}).insert(ignore_permissions=True)
        cross_container = make_container(self.masters, container_no=f"QTY-{frappe.generate_hash(length=6)}", inward_qty=1)
        cross_evidence = self._evidence(cross_container, "cross-uom")
        cross_declared = self._create(cross_container, cross_evidence, "shipping-cross", quantity="2")
        cross_operating = self._create(cross_container, cross_evidence, "operating-cross", basis="OPERATING_INWARD", quantity="2", uom=other_uom.name)
        self._submit(cross_declared["name"]); self._activate(cross_declared["name"])
        self._submit(cross_operating["name"]); self._activate(cross_operating["name"])
        frappe.set_user("Administrator")
        self.assertEqual(quantity_assertion.reconciliation_projection(cross_container.name)["reconciliation_status"], "UNRESOLVED")

    def test_two_connection_competing_activation_leaves_one_active(self):
        container = make_container(self.masters, container_no=f"QTY-{frappe.generate_hash(length=6)}", inward_qty=1)
        evidence = self._evidence(container, "concurrent activation")
        first = self._create(container, evidence, "race-1", quantity="1")
        second = self._create(container, evidence, "race-2", quantity="2")
        self._submit(first["name"]); self._submit(second["name"])
        # Worker connections need committed candidates; cleanup below removes these explicit rows.
        frappe.db.commit()
        outcomes, worker = self._two_connection_workers(lambda name: quantity_assertion.review(name, "ACTIVATE"))
        threads = [threading.Thread(target=worker, args=(name,)) for name in (first["name"], second["name"])]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=30)
        result = [outcomes.get(timeout=5)[1] for _ in threads]
        frappe.set_user("Administrator")
        self.assertEqual(result.count("OK"), 1)
        self.assertEqual(frappe.db.count("Fresko Container Quantity Assertion", {"container": container.name, "basis": "DECLARED_SHIPPING", "uom": self.masters["uom"], "status": "Active"}), 1)
        frappe.db.delete("Fresko Container Quantity Assertion", {"container": container.name})
        frappe.db.delete("Fresko Evidence", evidence.name)
        frappe.db.delete("Fresko Container Lot", {"parent": container.name})
        frappe.db.delete("Fresko Container", {"name": container.name})
        frappe.db.commit()
