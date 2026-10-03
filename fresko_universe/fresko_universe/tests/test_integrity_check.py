"""Bench integration tests for the periodic protected-record integrity checker.

Run with: bench --site <site> run-tests --app fresko_universe --module
fresko_universe.tests.test_integrity_check
"""
from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from fresko_universe import integrity, outward, quantity_assertion
from fresko_universe.fresko_core.services import integrity_service
from fresko_universe.tests.test_phase2a_outward import _ensure_user
from fresko_universe.tests.utils import ensure_masters, make_container


class TestIntegrityCheck(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.masters = ensure_masters()
        cls.maker = _ensure_user(
            "integrity_maker@example.com", ["Fresko Salesperson", "Fresko Approver"]
        )
        cls.checker = _ensure_user(
            "integrity_checker@example.com", ["Fresko Approver"]
        )
        cls.salesperson_only = _ensure_user(
            "integrity_salesperson_only@example.com", ["Fresko Salesperson"]
        )

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")

    def _evidence(self, container, label):
        return frappe.get_doc({
            "doctype": "Fresko Evidence",
            "evidence_type": "Note",
            "container": container.name,
            "notes": f"integrity test: {label}",
        }).insert(ignore_permissions=True)

    def _line(self, qty, *, lot_no, source_line_ref="1"):
        return {
            "source_line_ref": source_line_ref,
            "raw_lot_text": lot_no or "UNMAPPED",
            "lot_no": lot_no,
            "qty": qty,
            "uom": self.masters["uom"],
            "raw_qty_text": str(qty),
            "raw_uom_text": self.masters["uom"],
            "raw_rate_text": None,
        }

    def _create_posted_outward(self, container, evidence, event_id, qty, *, lot_no):
        frappe.set_user(self.maker)
        result = outward.create(
            container=container.name,
            movement_at="2026-10-03 10:00:00",
            source_evidence=evidence.name,
            source_event_id=event_id,
            lines=[self._line(qty, lot_no=lot_no)],
        )
        doc = frappe.get_doc("Fresko Outward", result["name"])
        outward.submit_for_review(doc.name)
        frappe.set_user(self.checker)
        outward.post(doc.name)
        doc.reload()
        return doc

    def _create_active_quantity_assertion(self, container, evidence, source_id, quantity="100"):
        frappe.set_user(self.maker)
        result = quantity_assertion.create(
            container=container.name, basis="DECLARED_SHIPPING",
            raw_value=str(quantity), quantity=quantity,
            uom=self.masters["uom"], raw_uom=self.masters["uom"],
            evidence=evidence.name, effective_at="2026-10-03 10:00:00",
            provenance="SOURCE_EXTRACTED", reason="integrity test",
            source_fact_id=source_id,
        )
        quantity_assertion.submit(result["name"])
        frappe.set_user(self.checker)
        quantity_assertion.review(result["name"], "ACTIVATE")
        return frappe.get_doc("Fresko Container Quantity Assertion", result["name"])

    def _cleanup_seals(self, *record_names):
        frappe.set_user("Administrator")
        for name in record_names:
            frappe.db.delete("Fresko Integrity Seal", {
                "record_name": name,
            })

    def _seals_for(self, record_name):
        return frappe.get_all(
            "Fresko Integrity Seal",
            filters={"record_name": record_name},
            fields=["name", "payload_sha256", "terminal_sha256", "terminal_status",
                     "mismatch_kind", "mismatch_exception", "mismatch_observed_sha256"],
        )

    def _di_exceptions_for_container(self, container_name):
        return frappe.get_all(
            "Fresko Exception",
            filters={
                "container": container_name,
                "exception_type": "DATA_INTEGRITY",
                "status": "Open",
            },
            fields=["name", "description"],
        )

    def test_a_first_run_seals_and_second_run_finds_unchanged(self):
        container = make_container(
            self.masters,
            container_no=f"IC-SEAL-{frappe.generate_hash(length=6)}",
            lot_no="IC-LOT", inward_qty=500,
        )
        evidence = self._evidence(container, "seal baseline")
        ow = self._create_posted_outward(container, evidence, "ic-seal-1", 10, lot_no="IC-LOT")
        qa = self._create_active_quantity_assertion(container, evidence, "ic-qa-1", "100")
        frappe.set_user("Administrator")
        self.addCleanup(lambda: self._cleanup_seals(ow.name, qa.name))

        s1 = integrity_service.run_integrity_check()
        ow_seals = self._seals_for(ow.name)
        self.assertEqual(len(ow_seals), 1)
        self.assertTrue(ow_seals[0].payload_sha256)
        self.assertTrue(ow_seals[0].terminal_sha256)  # Posted -> terminal sealed
        self.assertEqual(ow_seals[0].terminal_status, "Posted")
        qa_seals = self._seals_for(qa.name)
        self.assertEqual(len(qa_seals), 1)

        s2 = integrity_service.run_integrity_check()
        ow_seals2 = self._seals_for(ow.name)
        self.assertEqual(len(ow_seals2), 1)
        self.assertEqual(ow_seals2[0].name, ow_seals[0].name)
        di = self._di_exceptions_for_container(container.name)
        di_for_ow = [e for e in di if ow.name in (e.description or "")]
        self.assertEqual(len(di_for_ow), 0)

    def test_b_payload_tamper_outward_header(self):
        container = make_container(
            self.masters,
            container_no=f"IC-TAMPER-{frappe.generate_hash(length=6)}",
            lot_no="IC-T-LOT", inward_qty=500,
        )
        evidence = self._evidence(container, "tamper")
        ow = self._create_posted_outward(container, evidence, "ic-tamper-1", 10, lot_no="IC-T-LOT")
        frappe.set_user("Administrator")
        self.addCleanup(lambda: self._cleanup_seals(ow.name))
        integrity_service.run_integrity_check()

        frappe.db.sql(
            "UPDATE `tabFresko Outward` SET vehicle_no='TAMPERED' WHERE name=%s",
            (ow.name,),
        )

        s = integrity_service.run_integrity_check()
        ow_seals = self._seals_for(ow.name)
        self.assertEqual(ow_seals[0].mismatch_kind, "PAYLOAD_CHANGED")
        di = self._di_exceptions_for_container(container.name)
        di_for_ow = [e for e in di if ow.name in (e.description or "")]
        self.assertEqual(len(di_for_ow), 1)
        self.assertIn(container.name, di_for_ow[0].description)

        s2 = integrity_service.run_integrity_check()
        already = [
            m for m in s2["mismatches_already_reported"]
            if m["record_name"] == ow.name
        ]
        self.assertTrue(already)
        ow_seals2 = self._seals_for(ow.name)
        self.assertEqual(ow_seals2[0].mismatch_exception, ow_seals[0].mismatch_exception)

        # cleanup the tampered exception
        frappe.db.delete("Fresko Exception", {"name": ow_seals[0].mismatch_exception})

    def test_c_payload_tamper_outward_line(self):
        container = make_container(
            self.masters,
            container_no=f"IC-LINE-{frappe.generate_hash(length=6)}",
            lot_no="IC-L-LOT", inward_qty=500,
        )
        evidence = self._evidence(container, "line tamper")
        ow = self._create_posted_outward(container, evidence, "ic-line-1", 10, lot_no="IC-L-LOT")
        frappe.set_user("Administrator")
        self.addCleanup(lambda: self._cleanup_seals(ow.name))
        integrity_service.run_integrity_check()

        frappe.db.sql(
            "UPDATE `tabFresko Outward Line` SET qty=999 WHERE parent=%s",
            (ow.name,),
        )

        integrity_service.run_integrity_check()
        ow_seals = self._seals_for(ow.name)
        self.assertEqual(ow_seals[0].mismatch_kind, "PAYLOAD_CHANGED")
        frappe.db.delete("Fresko Exception", {"name": ow_seals[0].mismatch_exception})

    def test_d_terminal_tamper(self):
        container = make_container(
            self.masters,
            container_no=f"IC-TERM-{frappe.generate_hash(length=6)}",
            lot_no="IC-TERM-LOT", inward_qty=500,
        )
        evidence = self._evidence(container, "terminal tamper")
        ow = self._create_posted_outward(container, evidence, "ic-term-1", 10, lot_no="IC-TERM-LOT")
        frappe.set_user("Administrator")
        self.addCleanup(lambda: self._cleanup_seals(ow.name))
        integrity_service.run_integrity_check()

        frappe.db.sql(
            "UPDATE `tabFresko Outward` SET status='Draft' WHERE name=%s",
            (ow.name,),
        )

        integrity_service.run_integrity_check()
        ow_seals = self._seals_for(ow.name)
        self.assertEqual(ow_seals[0].mismatch_kind, "TERMINAL_CHANGED")
        frappe.db.delete("Fresko Exception", {"name": ow_seals[0].mismatch_exception})

    def test_e_record_missing(self):
        container = make_container(
            self.masters,
            container_no=f"IC-MISS-{frappe.generate_hash(length=6)}",
            lot_no="IC-M-LOT", inward_qty=500,
        )
        evidence = self._evidence(container, "missing record")
        qa = self._create_active_quantity_assertion(container, evidence, "ic-miss-qa", "100")
        frappe.set_user("Administrator")
        self.addCleanup(lambda: self._cleanup_seals(qa.name))
        integrity_service.run_integrity_check()

        frappe.db.sql(
            "DELETE FROM `tabFresko Container Quantity Assertion` WHERE name=%s",
            (qa.name,),
        )

        integrity_service.run_integrity_check()
        seals = self._seals_for(qa.name)
        self.assertEqual(seals[0].mismatch_kind, "RECORD_MISSING")
        frappe.db.delete("Fresko Exception", {"name": seals[0].mismatch_exception})

    def test_f_draft_then_post_is_legit_lifecycle(self):
        container = make_container(
            self.masters,
            container_no=f"IC-LIFECYCLE-{frappe.generate_hash(length=6)}",
            lot_no="IC-LIFE-LOT", inward_qty=500,
        )
        evidence = self._evidence(container, "lifecycle")
        frappe.set_user(self.maker)
        result = outward.create(
            container=container.name,
            movement_at="2026-10-03 10:00:00",
            source_evidence=evidence.name,
            source_event_id="ic-lifecycle-1",
            lines=[self._line(10, lot_no="IC-LIFE-LOT")],
        )
        doc = frappe.get_doc("Fresko Outward", result["name"])
        frappe.set_user("Administrator")
        self.addCleanup(lambda: self._cleanup_seals(doc.name))
        integrity_service.run_integrity_check()
        seals = self._seals_for(doc.name)
        self.assertEqual(len(seals), 1)
        self.assertFalse(seals[0].terminal_sha256)  # Draft, no terminal yet

        # Legitimate post through the service.
        outward.submit_for_review(doc.name)
        frappe.set_user(self.checker)
        outward.post(doc.name)
        frappe.set_user("Administrator")

        integrity_service.run_integrity_check()
        seals2 = self._seals_for(doc.name)
        self.assertEqual(len(seals2), 1)
        self.assertTrue(seals2[0].terminal_sha256)
        self.assertEqual(seals2[0].terminal_status, "Posted")
        self.assertFalse(seals2[0].mismatch_kind)

    def test_g_close_gate_blocked_by_data_integrity(self):
        container = make_container(
            self.masters,
            container_no=f"IC-GATE-{frappe.generate_hash(length=6)}",
            lot_no="IC-GATE-LOT", inward_qty=500,
        )
        evidence = self._evidence(container, "close gate")
        ow = self._create_posted_outward(container, evidence, "ic-gate-1", 10, lot_no="IC-GATE-LOT")
        frappe.set_user("Administrator")
        self.addCleanup(lambda: self._cleanup_seals(ow.name))
        integrity_service.run_integrity_check()

        frappe.db.sql(
            "UPDATE `tabFresko Outward` SET vehicle_no='TAMPERED' WHERE name=%s",
            (ow.name,),
        )
        integrity_service.run_integrity_check()
        ow_seals = self._seals_for(ow.name)
        self.assertTrue(ow_seals[0].mismatch_exception)

        # Resolve all non-DATA_INTEGRITY exceptions on this container.
        other_open = frappe.get_all(
            "Fresko Exception",
            filters={
                "container": container.name,
                "status": ("in", ["Open", "In Progress"]),
                "exception_type": ("!=", "DATA_INTEGRITY"),
            },
            pluck="name",
        )
        for exc_name in other_open:
            exc = frappe.get_doc("Fresko Exception", exc_name)
            exc.status = "Resolved"
            exc.resolution_notes = "Test cleanup"
            if hasattr(exc.flags, "in_outward_service"):
                exc.flags.in_outward_service = True
            exc.save(ignore_permissions=True)

        container.reload()
        container.status = "Closing"
        container.save(ignore_permissions=True)
        container.reload()
        container.status = "Closed"
        container.save(ignore_permissions=True)
        container.reload()
        container.closing_status = "Fully Reconciled"
        with self.assertRaisesRegex(frappe.ValidationError, "open material Exceptions"):
            container.save(ignore_permissions=True)

        frappe.db.delete("Fresko Exception", {"name": ow_seals[0].mismatch_exception})

    def test_h_seal_immutability(self):
        container = make_container(
            self.masters,
            container_no=f"IC-IMM-{frappe.generate_hash(length=6)}",
            lot_no="IC-IMM-LOT", inward_qty=500,
        )
        evidence = self._evidence(container, "immutability")
        ow = self._create_posted_outward(container, evidence, "ic-imm-1", 10, lot_no="IC-IMM-LOT")
        frappe.set_user("Administrator")
        self.addCleanup(lambda: self._cleanup_seals(ow.name))
        integrity_service.run_integrity_check()

        seals = self._seals_for(ow.name)
        seal = frappe.get_doc("Fresko Integrity Seal", seals[0].name)
        seal.flags.in_integrity_service = True
        seal.payload_sha256 = "TAMPERED"
        with self.assertRaises(frappe.PermissionError):
            seal.save(ignore_permissions=True)

        # Insert without flag.
        seal2 = frappe.get_doc({
            "doctype": "Fresko Integrity Seal",
            "record_doctype": "Fresko Outward",
            "record_name": "FAKE",
            "seal_key": "FAKE",
            "seal_version": "test",
            "payload_sha256": "FAKE",
            "sealed_at": "2026-01-01",
        })
        with self.assertRaises(frappe.PermissionError):
            seal2.insert(ignore_permissions=True)

        # Delete.
        with self.assertRaises(frappe.PermissionError):
            frappe.delete_doc("Fresko Integrity Seal", seals[0].name, ignore_permissions=True)

    def test_canonical_numbers_are_driver_independent(self):
        from decimal import Decimal

        canonical = integrity_service._canonicalize
        self.assertEqual(canonical(10.0), "10")
        self.assertEqual(canonical(Decimal("10.000000000")), "10")
        self.assertEqual(canonical(10.5), canonical(Decimal("10.500000000")))
        self.assertEqual(canonical(0.0), canonical(Decimal("0E-9")))
        self.assertNotEqual(canonical(10.0), canonical(10.5))

    def test_i_role_gate(self):
        frappe.set_user(self.salesperson_only)
        with self.assertRaises(frappe.PermissionError):
            integrity.run_check()

        frappe.set_user(self.checker)
        summary = integrity.run_check()
        self.assertIn("checked", summary)
