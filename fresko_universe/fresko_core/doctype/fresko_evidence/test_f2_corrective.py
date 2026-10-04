"""Persisted-state tests: pinned Frappe/MariaDB, not offline mocks."""
import uuid
from unittest.mock import patch

import frappe
import pymysql
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_datetime
from fresko_universe.fresko_core.services import evidence_service as svc


class TestF2Corrective(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.entities, self.attempts = [], []
        self.kw = dict(provider="whatsapp-cloud", provider_account_id="F2_TEST",
                       conversation_id="F2_TEST", provider_message_id=uuid.uuid4().hex,
                       raw_payload={"text": "unchanged"}, source_sender_id="sender",
                       source_sent_at="2026-09-19 10:00:00", received_at="2026-09-19 10:01:00")
        self.addCleanup(self.cleanup)

    def cleanup(self):
        frappe.db.rollback()
        for name in self.attempts:
            frappe.db.delete("Fresko Evidence Attempt", {"name": name})
        for name in self.entities:
            frappe.db.delete("Fresko Evidence Attempt", {"evidence": name})
            frappe.db.delete("Fresko Evidence Attachment", {"evidence": name})
            frappe.db.delete("Fresko Evidence", {"name": name})
        frappe.db.commit()

    def message(self, commit=True, **changes):
        self.kw.update(changes)
        doc, _ = svc.ingest_message_evidence(**self.kw)
        self.entities.append(doc.name)
        if commit:
            frappe.db.commit()
        return doc

    def envelope(self, evidence):
        with patch.object(svc, "_persist_attempt_independently", return_value=True) as capture:
            svc._record_attempt(evidence=evidence, operation="MESSAGE_INGEST",
                                outcome="CONFLICT_PAYLOAD_MISMATCH", isolated=True, reason="F2 test")
        fields = capture.call_args.args[0]
        self.attempts.append(fields["name"])
        return fields

    def test_later_receipt_is_idempotent_and_audited(self):
        doc = self.message()
        later = "2026-09-19 10:05:00"
        other, outcome = svc.ingest_message_evidence(**{**self.kw, "received_at": later})
        frappe.db.commit()
        self.assertEqual(outcome, "SUCCESS_IDEMPOTENT_REDELIVERY")
        self.assertEqual(other.name, doc.name)
        receipt = frappe.db.get_value("Fresko Evidence Attempt", {
            "evidence": doc.name, "outcome": outcome}, "delivery_received_at")
        self.assertEqual(get_datetime(receipt), get_datetime(later))
        doc.reload()
        self.assertEqual(get_datetime(doc.received_at), get_datetime(self.kw["received_at"]))
        print(f"F2-005 persisted: first={doc.received_at} redelivery={receipt} outcome={outcome}")

    def test_sender_difference_remains_conflict(self):
        self.provenance_conflict("source_sender_id", "different-sender")

    def test_sent_time_difference_remains_conflict(self):
        self.provenance_conflict("source_sent_at", "2026-09-19 11:00:00")

    def provenance_conflict(self, field, value):
        doc = self.message()
        with self.assertRaises(svc.IntegrityConflictError):
            svc.ingest_message_evidence(**{**self.kw, field: value, "received_at": "2026-09-19 12:00:00"})
        frappe.db.rollback()
        self.assertEqual(frappe.db.count("Fresko Evidence Attempt", {
            "evidence": doc.name, "outcome": "CONFLICT_PROVENANCE_MISMATCH"}), 1)
        doc.reload()
        self.assertEqual(str(doc.get(field)), self.kw[field])
        print(f"F2-005 {field}: conflict audit survives rollback; original unchanged")

    def test_redelivery_does_not_overwrite_original_receipt(self):
        doc = self.message()
        for receipt in (None, "2026-09-20 10:01:00"):
            _, outcome = svc.ingest_message_evidence(**{**self.kw, "received_at": receipt})
            self.assertEqual(outcome, "SUCCESS_IDEMPOTENT_REDELIVERY")
        frappe.db.commit()
        doc.reload()
        self.assertEqual(get_datetime(doc.received_at), get_datetime(self.kw["received_at"]))

    def test_historical_null_receipt_is_not_backfilled(self):
        doc = self.message(received_at=None)
        _, outcome = svc.ingest_message_evidence(**{**self.kw, "received_at": "2026-09-21 12:00:00"})
        self.assertEqual(outcome, "SUCCESS_IDEMPOTENT_REDELIVERY")
        frappe.db.commit()
        doc.reload()
        self.assertIsNone(doc.received_at)
        doc.flags.in_service = True
        doc.received_at = "2026-09-21 12:00:00"
        with self.assertRaises(frappe.ValidationError):
            doc.save()
        print("F2-005 historical received_at=NULL remains NULL after later receipt")

    def test_uncommitted_entity_rollback_retains_identifier_snapshot(self):
        doc = self.message(commit=False)
        attachment = frappe.new_doc("Fresko Evidence Attachment")
        attachment.flags.in_service = True
        attachment.evidence = doc.name
        attachment.file = attachment.file_url = "/private/files/f2-not-captured.txt"
        attachment.capture_status = "PENDING"
        attachment.insert(ignore_permissions=True)
        fields = self.envelope(doc.name)
        fields["evidence_attachment"] = attachment.name
        self.assertTrue(svc._persist_attempt_independently(fields))
        frappe.db.rollback()
        row = frappe.db.get_value("Fresko Evidence Attempt", fields["name"],
                                  ["evidence", "evidence_attachment", "durability_state"], as_dict=True)
        self.assertIsNotNone(row)
        self.assertFalse(frappe.db.exists("Fresko Evidence", doc.name))
        self.assertFalse(frappe.db.exists("Fresko Evidence Attachment", attachment.name))
        self.assertEqual(row.evidence, doc.name)
        self.assertEqual(row.evidence_attachment, attachment.name)
        for field in ("evidence", "evidence_attachment"):
            self.assertEqual(frappe.get_meta("Fresko Evidence Attempt").get_field(field).fieldtype, "Data")
        fks = frappe.db.sql("""SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tabFresko Evidence Attempt'
            AND COLUMN_NAME IN ('evidence','evidence_attachment') AND REFERENCED_TABLE_NAME IS NOT NULL""")
        self.assertEqual(len(fks), 0)
        print("F2-006 persisted: attempt=1 canonical_evidence=0 canonical_attachment=0 "
              "references=IDENTIFIER_SNAPSHOTS relational_FKs=0 no_parent_fabricated")

    def test_first_independent_write_succeeds(self):
        fields = self.envelope(self.message().name)
        with patch.object(pymysql, "connect", wraps=pymysql.connect) as connect:
            self.assertTrue(svc._persist_attempt_independently(fields))
        self.assertEqual(connect.call_count, 1)
        self.assertEqual(frappe.db.count("Fresko Evidence Attempt", {"name": fields["name"]}), 1)

    def test_transient_failure_then_retry_succeeds(self):
        fields = self.envelope(self.message().name)
        real_connect, calls = pymysql.connect, []
        def connect(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise pymysql.OperationalError(2003, "test connection failure")
            return real_connect(**kwargs)
        with patch.object(pymysql, "connect", side_effect=connect), patch.object(svc.time, "sleep") as sleep:
            self.assertTrue(svc._persist_attempt_independently(fields))
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once_with(0.05)
        frappe.db.rollback()
        self.assertTrue(frappe.db.exists("Fresko Evidence Attempt", fields["name"]))
        print("F2-007 transient: connections=2 persisted_attempts=1 after_caller_rollback")

    def test_all_three_fail_conflict_fails_closed(self):
        doc = self.message()
        with patch.object(pymysql, "connect", side_effect=pymysql.OperationalError(2003, "offline")) as connect, \
                patch.object(svc.time, "sleep") as sleep:
            with self.assertRaises(svc.IntegrityConflictError):
                svc.ingest_message_evidence(**{**self.kw, "raw_payload": {"text": "conflict"}})
        self.assertEqual(connect.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [0.05, 0.1])
        frappe.db.rollback()
        self.assertEqual(frappe.db.count("Fresko Evidence Attempt", {
            "evidence": doc.name, "outcome": "CONFLICT_PAYLOAD_MISMATCH"}), 0)
        print("F2-007 exhausted: connections=3 retries=2 conflict_failed_closed=True durable_rows=0")

    def test_ambiguous_insert_and_repeated_persistence_are_idempotent(self):
        fields = self.envelope(self.message().name)
        real_connect, lost_ack = pymysql.connect, []
        class CursorProxy:
            def __init__(self, cursor): self.cursor = cursor
            def __enter__(self): self.cursor.__enter__(); return self
            def __exit__(self, *args): return self.cursor.__exit__(*args)
            def fetchone(self): return self.cursor.fetchone()
            def execute(self, sql, args=None):
                result = self.cursor.execute(sql, args)
                if sql.startswith("INSERT INTO") and not lost_ack:
                    lost_ack.append(True)
                    raise pymysql.OperationalError(2013, "test lost acknowledgement AFTER real INSERT")
                return result
        class ConnectionProxy:
            def __init__(self, conn): self.conn = conn
            def cursor(self): return CursorProxy(self.conn.cursor())
            def close(self): self.conn.close()
        with patch.object(pymysql, "connect", side_effect=lambda **kw: ConnectionProxy(real_connect(**kw))) as connect, \
                patch.object(svc.time, "sleep"):
            self.assertTrue(svc._persist_attempt_independently(fields))
        self.assertEqual(connect.call_count, 2)
        self.assertTrue(svc._persist_attempt_independently(fields))
        self.assertFalse(svc._persist_attempt_independently({**fields, "reason": "different event"}))
        frappe.db.rollback()
        self.assertEqual(frappe.db.count("Fresko Evidence Attempt", {"name": fields["name"]}), 1)
        print("F2-007 ambiguous INSERT committed then acknowledgement lost: rows=1 "
              "identical_replay=True mismatched_duplicate=False")

    def test_independent_write_does_not_commit_caller(self):
        doc = self.message()
        original = frappe.db.get_value("Fresko Evidence", doc.name, "notes")
        frappe.db.set_value("Fresko Evidence", doc.name, "notes", "UNCOMMITTED_F2_MARKER")
        fields = self.envelope(doc.name)
        self.assertTrue(svc._persist_attempt_independently(fields))
        self.assertEqual(frappe.db.get_value("Fresko Evidence", doc.name, "notes"), "UNCOMMITTED_F2_MARKER")
        frappe.db.rollback()
        self.assertEqual(frappe.db.get_value("Fresko Evidence", doc.name, "notes"), original)
        self.assertTrue(frappe.db.exists("Fresko Evidence Attempt", fields["name"]))
        print("F2-007 caller mutation rolled back; independent conflict attempt still committed")
