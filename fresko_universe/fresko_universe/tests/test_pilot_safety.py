"""Pinned-site pilot safety regressions. All records here are synthetic.

The policy matrix fixtures bypass Exception scope validation solely to isolate
the Container gate. Receipt cases use the real three-person Money workflow.
"""
from __future__ import annotations

import json
import threading
from queue import Queue

import frappe
from frappe.tests.utils import FrappeTestCase

from fresko_universe import money, outward
from fresko_universe.fresko_core.services import evidence_service
from fresko_universe.fresko_core.services.close_policy import CLOSE_EXCEPTION_POLICY
from fresko_universe.tests import test_money_reconciliation as money_tests
from fresko_universe.tests.test_commercial_sale import _ensure_user
from fresko_universe.tests.utils import ensure_masters, make_container


class TestPilotSafety(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.masters = ensure_masters()
        cls.maker = _ensure_user("pilot_maker@example.com", ["Fresko Accounts"])
        cls.checker = _ensure_user("pilot_checker@example.com", ["Fresko Accounts"])
        cls.approver = _ensure_user("pilot_approver@example.com", ["Fresko Approver"])
        cls.salesperson = _ensure_user("pilot_sales@example.com", ["Fresko Salesperson"])
        frappe.db.commit()

    def setUp(self):
        # Compose existing acceptance builders without inheriting their tests.
        self.runtime = money_tests.TestMoneyReconciliation(methodName="runTest")
        for field in ("masters", "maker", "checker", "approver", "salesperson"):
            setattr(self.runtime, field, getattr(self, field))
        self.runtime.setUp()
        self.container = self.runtime.container

    def tearDown(self):
        frappe.set_user("Administrator")

    def _closed(self, container=None):
        frappe.set_user("Administrator")
        container = container or self.container
        for status in ("Closing", "Closed"):
            container.reload()
            container.status = status
            container.save(ignore_permissions=True)
        return container

    def _reconcile(self, container=None):
        frappe.set_user("Administrator")
        container = container or self.container
        container.reload()
        container.closing_status = "Fully Reconciled"
        container.save(ignore_permissions=True)

    def _policy_fixture(self, kind, status="Open", severity="Low", container=None):
        # Only the close policy is under test, not creation/approval authority.
        doc = frappe.get_doc({
            "doctype": "Fresko Exception", "name": "PILOT-EX-" + frappe.generate_hash(length=12),
            "exception_type": kind, "status": status, "severity": severity,
            "container": (container or self.container).name,
            "description": "Synthetic isolated closure-policy fixture",
        })
        doc.db_insert()
        return doc.name

    def test_every_material_enum_blocks_both_open_states_and_preserves_rows(self):
        self._closed()
        before = self.container.as_dict()
        for kind, policy in CLOSE_EXCEPTION_POLICY.items():
            severity = "Material" if policy == "severity" else "Low"
            for status in ("Open", "In Progress"):
                with self.subTest(kind=kind, status=status):
                    name = self._policy_fixture(kind, status, severity)
                    with self.assertRaisesRegex(frappe.ValidationError, "open material Exceptions"):
                        self._reconcile()
                    self.assertEqual(frappe.db.get_value("Fresko Exception", name, "status"), status)
                    self.container.reload()
                    self.assertEqual(self.container.closing_status, before["closing_status"])
                    self.assertEqual(self.container.inward_qty, before["inward_qty"])
                    frappe.db.delete("Fresko Exception", {"name": name})

    def test_nonmaterial_and_terminal_exceptions_allow_closure(self):
        self._closed()
        for kind in ("OTHER", "IDEMPOTENCY_PAYLOAD_CONFLICT", "CONCURRENT_STATE_CONFLICT"):
            self._policy_fixture(kind, severity="High")
        for kind in CLOSE_EXCEPTION_POLICY:
            for status in ("Resolved", "Waived", "Cancelled"):
                self._policy_fixture(kind, status=status, severity="Critical")
        self._reconcile()
        self.container.reload()
        self.assertEqual(self.container.closing_status, "Fully Reconciled")

    def test_unrelated_container_material_exception_does_not_block(self):
        other = make_container(self.masters)
        self._policy_fixture("DATA_INTEGRITY", container=other)
        self._closed()
        self._reconcile()

    def test_real_money_exceptions_use_preserved_receipt_context(self):
        cases = (
            ("MONEY_UNALLOCATED", "100", {}),
            ("BANK_PENDING", "350000", {"payment_channel": "BANK", "bank_state": "AUTHORIZATION_INPROCESS", "source_classification": "RTGS_NEFT", "rail": "RTGS", "bank_reference": "SYNTHETIC-PENDING"}),
            ("RECEIPT_AMOUNT_UNKNOWN", None, {"direction": "UNKNOWN", "payment_channel": "UNKNOWN", "source_classification": "NONE"}),
            ("RECEIPT_DIRECTION_UNKNOWN", "101", {"direction": "UNKNOWN"}),
        )
        self._closed()
        for kind, amount, changes in cases:
            with self.subTest(kind=kind):
                receipt = self.runtime._approve(self.runtime._collection(amount, event=kind, **changes), "collection")
                self.assertTrue(frappe.db.exists("Fresko Exception", {"collection": receipt.name, "exception_type": kind, "status": "Open"}))
                before = receipt.as_dict()
                with self.assertRaisesRegex(frappe.ValidationError, "open material Exceptions"):
                    self._reconcile()
                receipt.reload()
                self.assertEqual(receipt.as_dict(), before)
                frappe.set_user(self.approver)
                money.reverse_collection(receipt.name, reason="Synthetic case completed", evidence=self.runtime.evidence.name)

    def test_live_evidence_retarget_does_not_move_receipt_exception(self):
        receipt = self.runtime._approve(self.runtime._collection("100"), "collection")
        original_snapshot = receipt.evidence_snapshot
        other = make_container(self.masters)
        frappe.set_user("Administrator")
        self.runtime.evidence.container = other.name
        self.runtime.evidence.save(ignore_permissions=True)
        self._closed()
        with self.assertRaisesRegex(frappe.ValidationError, "open material Exceptions"):
            self._reconcile()
        self._closed(other)
        self._reconcile(other)
        receipt.reload()
        self.assertEqual(receipt.evidence_snapshot, original_snapshot)

    def test_pooled_receipt_remainder_is_not_assigned_by_allocation_proposal(self):
        frappe.set_user("Administrator")
        self.runtime.evidence.container = None
        self.runtime.evidence.save(ignore_permissions=True)
        receipt = self.runtime._approve(self.runtime._collection("150"), "collection")
        self.runtime._allocation(receipt, "100")
        self.assertIsNone(json.loads(receipt.evidence_snapshot)["container"])
        self._closed()
        self._reconcile()
        receipt.reload()
        self.assertEqual(receipt.unallocated_amount, "150.00")

    def test_pending_bank_proposal_context_blocks_until_rejected(self):
        frappe.set_user("Administrator")
        self.runtime.evidence.container = None
        self.runtime.evidence.save(ignore_permissions=True)
        receipt = self.runtime._approve(self.runtime._collection(
            "100", payment_channel="BANK", bank_state="AUTHORIZATION_INPROCESS",
            source_classification="RTGS_NEFT", rail="RTGS", bank_reference="SYNTHETIC-CONTEXT",
        ), "collection")
        allocation = self.runtime._allocation(receipt, "100")
        self._closed()
        with self.assertRaisesRegex(frappe.ValidationError, "open material Exceptions"):
            self._reconcile()
        frappe.set_user(self.approver)
        money.reject_payment_allocation(allocation.name, reason="Unrelated proposal withdrawn")
        self._reconcile()
        receipt.reload()
        self.assertEqual(receipt.bank_state, "AUTHORIZATION_INPROCESS")

    def test_close_gate_never_edits_posted_physical_commercial_or_money_truth(self):
        sale = self.runtime._sale()
        receipt = self.runtime._approve(self.runtime._collection("1000"), "collection")
        frappe.set_user(self.salesperson)
        result = outward.create(container=self.container.name, movement_at="2026-09-21 12:00:00",
            source_evidence=self.runtime.evidence.name, source_event_id=self.runtime.token + ":physical",
            lines=[{"source_line_ref": "1", "lot_no": "MONEY-LOT", "raw_lot_text": "MONEY-LOT",
                "qty": 1, "uom": self.masters["uom"], "raw_qty_text": "1", "raw_uom_text": self.masters["uom"]}])
        outward.submit_for_review(result["name"])
        frappe.set_user(self.approver)
        outward.post(result["name"])
        physical = frappe.get_doc("Fresko Outward", result["name"])
        self._closed()
        before = [doc.as_dict() for doc in (physical, sale, receipt)]
        # Even callers with broad technical visibility see only the generic gate.
        with self.assertRaisesRegex(frappe.ValidationError, "open material Exceptions") as error:
            self._reconcile()
        self.assertNotIn(receipt.name, str(error.exception))
        for doc, original in zip((physical, sale, receipt), before):
            doc.reload()
            self.assertEqual(doc.as_dict(), original)

    def test_current_read_catches_exception_committed_after_snapshot(self):
        self._closed()
        frappe.db.commit()
        frappe.db.sql("SELECT COUNT(*) FROM `tabFresko Exception`")
        site, sites_path = frappe.local.site, frappe.local.sites_path
        container, company = self.container.name, self.container.company
        outcome = Queue()

        def writer():
            try:
                frappe.init(site=site, sites_path=sites_path)
                frappe.connect()
                frappe.set_user("Administrator")
                frappe.db.sql("SELECT name FROM `tabCompany` WHERE name=%s FOR UPDATE", (company,))
                frappe.db.sql("SELECT name FROM `tabFresko Container` WHERE name=%s FOR UPDATE", (container,))
                ex = frappe.get_doc({"doctype": "Fresko Exception", "container": container,
                    "exception_type": "DATA_INTEGRITY", "severity": "Material", "status": "Open",
                    "description": "Synthetic concurrent exception"}).insert(ignore_permissions=True)
                frappe.db.commit()
                outcome.put((ex.name, None))
            except Exception as exc:
                outcome.put((None, str(exc)))
            finally:
                frappe.destroy()

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        thread.join(timeout=15)
        self.assertFalse(thread.is_alive(), "Concurrent fixture writer did not finish")
        name, error = outcome.get_nowait()
        self.assertIsNone(error)
        try:
            with self.assertRaisesRegex(frappe.ValidationError, "open material Exceptions"):
                self._reconcile()
        finally:
            frappe.db.delete("Fresko Exception", {"name": name})
            frappe.db.commit()

    def test_provider_contract_rejects_before_any_rows_and_legacy_remains_valid(self):
        frappe.set_user("Administrator")
        before = (frappe.db.count("Fresko Evidence"), frappe.db.count("Fresko Evidence Attempt"))
        for field in ("provider", "provider_account_id", "conversation_id", "provider_message_id"):
            for value in (None, "", 0, False):
                args = dict(provider="whatsapp-cloud", provider_account_id="SYNTHETIC", conversation_id="SYNTHETIC", provider_message_id="SYNTHETIC")
                args[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(frappe.ValidationError):
                    evidence_service.ingest_provider_message_evidence(**args)
        self.assertEqual(before, (frappe.db.count("Fresko Evidence"), frappe.db.count("Fresko Evidence Attempt")))
        legacy, _ = evidence_service.ingest_message_evidence(provider="whatsapp-cloud", raw_payload="Historical export without transport IDs")
        self.assertFalse(legacy.scoped_message_key)

    def test_provider_entry_cannot_assert_a_complete_zero_attachment_manifest(self):
        frappe.set_user("Administrator")
        args = dict(provider="whatsapp-cloud", provider_account_id="SYNTHETIC", conversation_id="SYNTHETIC",
            provider_message_id=frappe.generate_hash(length=12), raw_payload={"text": "synthetic"})
        before = frappe.db.count("Fresko Evidence")
        with self.assertRaises(TypeError):
            evidence_service.ingest_provider_message_evidence(**args, manifest_status="FINALIZED", expected_attachment_count=0)
        self.assertEqual(frappe.db.count("Fresko Evidence"), before)
        doc, _ = evidence_service.ingest_provider_message_evidence(**args)
        self.assertEqual(doc.manifest_status, "UNKNOWN")
        self.assertEqual(doc.expected_attachment_count, -1)
        self.assertEqual(evidence_service.aggregate_parent_evidence_status(doc.name), "PENDING")

    def test_provider_contract_exact_identity_replay_and_parent_conflict(self):
        frappe.set_user("Administrator")
        args = dict(provider=" WhatsApp ", provider_account_id="0", conversation_id="Scope \u2705 ",
            provider_message_id=" Message " + frappe.generate_hash(length=8), raw_payload={"text": "synthetic"})
        first, _ = evidence_service.ingest_provider_message_evidence(**args)
        second, _ = evidence_service.ingest_provider_message_evidence(**args)
        self.assertEqual(first.name, second.name)
        first.reload()
        for field in ("provider", "provider_account_id", "conversation_id", "provider_message_id"):
            self.assertEqual(first.get(field), args[field])
        _, outcome = evidence_service.ingest_provider_message_evidence(**{**args, "raw_payload": {"text": "conflicting synthetic"}})
        self.assertEqual(outcome, "CONFLICT_PAYLOAD_MISMATCH")
        self.assertEqual(evidence_service.aggregate_parent_evidence_status(first.name), "CONFLICT")
