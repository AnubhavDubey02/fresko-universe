# Copyright (c) 2026, Anubhav Dubey and contributors
from __future__ import annotations

import hashlib
import os

import frappe
from frappe.tests.utils import FrappeTestCase

from fresko_universe.constants import (
    EVIDENCE_ATTACHMENT_CAPTURE_STATUSES,
    EVIDENCE_OVERALL_VERIFICATION_STATUSES,
    HASH_ALGORITHM_LEGACY_PATH_V0,
    HASH_ALGORITHM_LEGACY_UNVERIFIED,
    HASH_ALGORITHM_SHA256_V1,
)
from fresko_universe.fresko_core.services.evidence_service import (
    aggregate_parent_evidence_status,
    canonicalize_payload,
    compute_logical_attachment_key,
    compute_scoped_attachment_version_key,
    compute_scoped_message_key,
    ingest_attachment,
    ingest_message_evidence,
    supersede_attachment,
    verify_and_capture_attachment,
)


class TestFreskoEvidence(FrappeTestCase):
    """Bench test suite for FSEC-004 & FSEC-005 Evidence integrity and scoped identity."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_byte_hash_not_path_hash(self):
        """FSEC-004 fix: content_sha256 matches actual file bytes, not the file URL string."""
        sample_bytes = b"Actual binary bytes for test evidence 12345\n"
        expected_hash = hashlib.sha256(sample_bytes).hexdigest()

        # Write test file to private files directory
        file_name = "test_fsec004_bytes.txt"
        file_path = frappe.get_site_path("private", "files", file_name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(sample_bytes)

        file_url = f"/private/files/{file_name}"
        if not frappe.db.exists("File", {"file_url": file_url}):
            fdoc = frappe.get_doc(
                {
                    "doctype": "File",
                    "file_name": file_name,
                    "file_url": file_url,
                    "is_private": 1,
                }
            )
            fdoc.insert(ignore_permissions=True)

        ev, _ = ingest_message_evidence(
            provider="whatsapp-cloud",
            provider_account_id="ACC_BENCH",
            conversation_id="CONV_BENCH",
            provider_message_id="MSG_BENCH_1",
            raw_payload={
                "document": {
                    "file_size": len(sample_bytes),
                    "sha256": expected_hash,
                    "filename": file_name,
                }
            },
            manifest_status="FINALIZED",
            expected_attachment_count=1,
        )

        att, _ = ingest_attachment(
            evidence_name=ev.name,
            file_url=file_url,
            identity_type="ordinal",
            identity_value=0,
            provenance_type="PROVIDER_HEADER_CONTENT_LENGTH",
            expected_byte_count=len(sample_bytes),
            expected_sha256=expected_hash,
        )

        res = verify_and_capture_attachment(att.name)
        self.assertTrue(res.success)
        self.assertEqual(res.status, "CAPTURED")
        self.assertEqual(res.content_sha256, expected_hash)
        self.assertEqual(res.content_byte_count, len(sample_bytes))

        # Assert that content_sha256 is NOT the hash of the file URL string
        path_url_hash = hashlib.sha256(file_url.encode("utf-8")).hexdigest()
        self.assertNotEqual(res.content_sha256, path_url_hash)

        # Parent aggregation should be COMPLETE
        ev.reload()
        self.assertEqual(ev.overall_verification_status, "COMPLETE")
        self.assertEqual(ev.verified_attachment_count, 1)

    def test_missing_completeness_provenance_stays_unresolved(self):
        """Missing or untrusted provenance must never become CAPTURED."""
        sample_bytes = b"Some data"
        file_name = "test_untrusted.txt"
        file_path = frappe.get_site_path("private", "files", file_name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(sample_bytes)
        file_url = f"/private/files/{file_name}"

        ev, _ = ingest_message_evidence(
            provider="whatsapp-cloud",
            provider_account_id="ACC_BENCH",
            conversation_id="CONV_BENCH",
            provider_message_id="MSG_BENCH_PROV",
        )
        att, _ = ingest_attachment(
            evidence_name=ev.name,
            file_url=file_url,
            identity_type="ordinal",
            identity_value=0,
            provenance_type="UNTRUSTED_CALLER",
            expected_byte_count=len(sample_bytes),
        )

        res = verify_and_capture_attachment(att.name)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "PENDING")
        self.assertIn("untrusted", res.reason.lower())

    def test_stable_truncated_file_marked_partial(self):
        """A stably truncated file fails completeness verification and is marked PARTIAL."""
        truncated_bytes = b"Half of the expected file"
        expected_full_length = len(truncated_bytes) * 2

        file_name = "test_truncated.txt"
        file_path = frappe.get_site_path("private", "files", file_name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(truncated_bytes)
        file_url = f"/private/files/{file_name}"

        ev, _ = ingest_message_evidence(
            provider="whatsapp-cloud",
            provider_account_id="ACC_BENCH",
            conversation_id="CONV_BENCH",
            provider_message_id="MSG_BENCH_TRUNC",
            raw_payload={
                "document": {
                    "file_size": expected_full_length,
                    "filename": file_name,
                }
            },
            manifest_status="FINALIZED",
            expected_attachment_count=1,
        )
        att, _ = ingest_attachment(
            evidence_name=ev.name,
            file_url=file_url,
            identity_type="ordinal",
            identity_value=0,
            provenance_type="PROVIDER_HEADER_CONTENT_LENGTH",
            expected_byte_count=expected_full_length,
        )

        res = verify_and_capture_attachment(att.name)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "PARTIAL")

        ev.reload()
        self.assertEqual(ev.overall_verification_status, "PARTIAL")

    def test_idempotent_redelivery_and_payload_conflict(self):
        """Duplicate message with matching payload succeeds; differing payload sets CONFLICT."""
        payload_1 = {"text": "Original message"}
        ev1, outcome1 = ingest_message_evidence(
            provider="whatsapp-cloud",
            provider_account_id="ACC_BENCH",
            conversation_id="CONV_BENCH",
            provider_message_id="MSG_DUP_TEST",
            raw_payload=payload_1,
        )
        self.assertEqual(outcome1, "SUCCESS_NEW")

        # Replay exact same payload
        ev2, outcome2 = ingest_message_evidence(
            provider="whatsapp-cloud",
            provider_account_id="ACC_BENCH",
            conversation_id="CONV_BENCH",
            provider_message_id="MSG_DUP_TEST",
            raw_payload=payload_1,
        )
        self.assertEqual(outcome2, "SUCCESS_IDEMPOTENT_REDELIVERY")
        self.assertEqual(ev1.name, ev2.name)

        # Replay with differing payload
        ev3, outcome3 = ingest_message_evidence(
            provider="whatsapp-cloud",
            provider_account_id="ACC_BENCH",
            conversation_id="CONV_BENCH",
            provider_message_id="MSG_DUP_TEST",
            raw_payload={"text": "TAMPERED message content"},
        )
        self.assertEqual(outcome3, "CONFLICT_PAYLOAD_MISMATCH")
        ev1.reload()
        self.assertEqual(ev1.overall_verification_status, "CONFLICT")

    def test_supersede_correction_preserves_logical_identity(self):
        """Corrections increment version without altering logical identity."""
        sample_bytes_1 = b"Version 1 content"
        file_path_1 = frappe.get_site_path("private", "files", "v1.txt")
        os.makedirs(os.path.dirname(file_path_1), exist_ok=True)
        with open(file_path_1, "wb") as f:
            f.write(sample_bytes_1)

        ev, _ = ingest_message_evidence(
            provider="whatsapp-cloud",
            provider_account_id="ACC_BENCH",
            conversation_id="CONV_BENCH",
            provider_message_id="MSG_SUPERSEDE_TEST",
            raw_payload={
                "document": {
                    "file_size": len(sample_bytes_1),
                    "filename": "v1.txt",
                }
            },
            manifest_status="FINALIZED",
            expected_attachment_count=1,
        )
        att1, _ = ingest_attachment(
            evidence_name=ev.name,
            file_url="/private/files/v1.txt",
            identity_type="ordinal",
            identity_value=0,
            provenance_type="PROVIDER_HEADER_CONTENT_LENGTH",
            expected_byte_count=len(sample_bytes_1),
        )

        sample_bytes_2 = b"Version 2 corrected content"
        file_path_2 = frappe.get_site_path("private", "files", "v2.txt")
        with open(file_path_2, "wb") as f:
            f.write(sample_bytes_2)

        att2 = supersede_attachment(
            attachment_name=att1.name,
            new_file_url="/private/files/v2.txt",
            reason="Corrected corrupted original receipt",
            provenance_type="PROVIDER_HEADER_CONTENT_LENGTH",
            expected_byte_count=len(sample_bytes_2),
        )

        self.assertEqual(att2.version, 2)
        self.assertEqual(att2.logical_attachment_key, att1.logical_attachment_key)
        self.assertEqual(att2.is_current_version, 1)

        att1.reload()
        self.assertEqual(att1.is_current_version, 0)
        self.assertEqual(att1.is_superseded, 1)
        self.assertEqual(att1.superseded_by, att2.name)
        self.assertEqual(att1.capture_status, "SUPERSEDED")

    def test_manifest_completeness_provenance_binding(self):
        """Finding 1: Offline manifest contents must be parsed and bound to expected length/hash."""
        import json
        manifest_file = frappe.get_site_path("private", "files", "bench_manifest.json")
        sample_bytes = b"Manifest verified bytes 123"
        sample_hash = hashlib.sha256(sample_bytes).hexdigest()
        file_name = "manifest_doc.pdf"
        file_path = frappe.get_site_path("private", "files", file_name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(sample_bytes)

        with open(manifest_file, "w", encoding="utf-8") as mf:
            json.dump({
                "attachments": [
                    {
                        "file_name": file_name,
                        "expected_byte_count": len(sample_bytes),
                        "expected_sha256": sample_hash,
                    }
                ]
            }, mf)

        ev, _ = ingest_message_evidence(
            provider="whatsapp-cloud",
            provider_account_id="ACC_BENCH",
            conversation_id="CONV_BENCH",
            provider_message_id="MSG_BENCH_MF",
            manifest_status="FINALIZED",
            expected_attachment_count=1,
        )

        # Unbound file not in manifest must fail verification
        att_unbound, _ = ingest_attachment(
            evidence_name=ev.name,
            file_url="/private/files/unbound.pdf",
            identity_type="provider_id",
            identity_value="unbound_id",
            provenance_type="OFFLINE_IMPORT_MANIFEST",
            provenance_ref=manifest_file,
            expected_byte_count=100,
        )
        res_unbound = verify_and_capture_attachment(att_unbound.name)
        self.assertFalse(res_unbound.success)
        self.assertEqual(res_unbound.status, "PENDING")

        # Bound file in manifest succeeds
        att_bound, _ = ingest_attachment(
            evidence_name=ev.name,
            file_url=f"/private/files/{file_name}",
            identity_type="provider_id",
            identity_value="bound_id",
            provenance_type="OFFLINE_IMPORT_MANIFEST",
            provenance_ref=manifest_file,
            expected_byte_count=len(sample_bytes),
            expected_sha256=sample_hash,
        )
        res_bound = verify_and_capture_attachment(att_bound.name)
        self.assertTrue(res_bound.success)
        self.assertEqual(res_bound.status, "CAPTURED")

    def test_superseded_file_protection_and_verification_rejection(self):
        """Finding 2: Files backing SUPERSEDED attachments cannot be deleted or modified; superseded attachment cannot be verified."""
        from fresko_universe.fresko_core.services.evidence_service import (
            prevent_captured_file_deletion,
            prevent_captured_file_modification,
        )
        sample_bytes_1 = b"Original receipt bytes"
        file_name_1 = "bench_old_receipt.pdf"
        file_path_1 = frappe.get_site_path("private", "files", file_name_1)
        os.makedirs(os.path.dirname(file_path_1), exist_ok=True)
        with open(file_path_1, "wb") as f:
            f.write(sample_bytes_1)
        file_url_1 = f"/private/files/{file_name_1}"

        fdoc1 = frappe.get_doc({
            "doctype": "File",
            "file_name": file_name_1,
            "file_url": file_url_1,
            "is_private": 1,
        })
        fdoc1.insert(ignore_permissions=True)

        ev, _ = ingest_message_evidence(
            provider="whatsapp-cloud",
            provider_account_id="ACC_BENCH",
            conversation_id="CONV_BENCH",
            provider_message_id="MSG_BENCH_F2",
            raw_payload={
                "document": {
                    "file_size": len(sample_bytes_1),
                    "filename": file_name_1,
                }
            },
            manifest_status="FINALIZED",
            expected_attachment_count=1,
        )
        att1, _ = ingest_attachment(
            evidence_name=ev.name,
            file_url=file_url_1,
            identity_type="ordinal",
            identity_value=0,
            provenance_type="PROVIDER_HEADER_CONTENT_LENGTH",
            expected_byte_count=len(sample_bytes_1),
        )
        verify_and_capture_attachment(att1.name)

        # Supersede attachment 1
        sample_bytes_2 = b"Corrected receipt bytes"
        file_name_2 = "bench_new_receipt.pdf"
        file_path_2 = frappe.get_site_path("private", "files", file_name_2)
        with open(file_path_2, "wb") as f:
            f.write(sample_bytes_2)
        file_url_2 = f"/private/files/{file_name_2}"

        att2 = supersede_attachment(
            attachment_name=att1.name,
            new_file_url=file_url_2,
            reason="Corrected receipt with official stamp",
            provenance_type="PROVIDER_HEADER_CONTENT_LENGTH",
            expected_byte_count=len(sample_bytes_2),
        )

        att1.reload()
        self.assertEqual(att1.capture_status, "SUPERSEDED")
        self.assertEqual(att1.is_superseded, 1)

        # File deletion/modification guard must protect superseded file
        with self.assertRaises(frappe.PermissionError):
            prevent_captured_file_deletion(fdoc1)

        fdoc1.file_url = "/private/files/hacked.pdf"
        with self.assertRaises(frappe.PermissionError):
            prevent_captured_file_modification(fdoc1)

        # verify_and_capture_attachment on superseded version must be rejected
        res_old = verify_and_capture_attachment(att1.name)
        self.assertFalse(res_old.success)
        self.assertEqual(res_old.status, "SUPERSEDED")

    def test_path_containment_sibling_directory_blocked(self):
        """Finding 3: Sibling directory (e.g. private/files-backup) and traversal attacks are rejected."""
        from fresko_universe.fresko_core.services.evidence_service import get_validated_local_file_path

        sibling_dir = frappe.get_site_path("private", "files-backup")
        os.makedirs(sibling_dir, exist_ok=True)
        sibling_file = os.path.join(sibling_dir, "leak.txt")
        with open(sibling_file, "wb") as f:
            f.write(b"sensitive")

        with self.assertRaises(frappe.PermissionError):
            get_validated_local_file_path("/private/files-backup/leak.txt")

        with self.assertRaises(frappe.PermissionError):
            get_validated_local_file_path("/private/files/../../etc/passwd")

    def test_identity_contract_untrimmed_and_replay_content(self):
        """Finding 4: Provider IDs are untrimmed; replay checks content/provenance; ordinal identity requires stable ordering."""
        # Untrimmed opaque IDs
        key1 = compute_scoped_message_key(" whatsapp ", " ACC ", " CHAT ", " MSG ")
        key2 = compute_scoped_message_key("whatsapp", "ACC", "CHAT", "MSG")
        self.assertNotEqual(key1, key2)

        ev, _ = ingest_message_evidence(
            provider="whatsapp-cloud",
            provider_account_id="ACC_BENCH",
            conversation_id="CONV_BENCH",
            provider_message_id="MSG_BENCH_F4",
            manifest_status="FINALIZED",
            expected_attachment_count=1,
        )

        sample_bytes = b"File content for replay test"
        file_path = frappe.get_site_path("private", "files", "f4_file.pdf")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(sample_bytes)
        file_url = "/private/files/f4_file.pdf"

        att, outcome = ingest_attachment(
            evidence_name=ev.name,
            file_url=file_url,
            identity_type="provider_id",
            identity_value="att_id_f4",
            provenance_type="PROVIDER_PAYLOAD_DIGEST",
            expected_byte_count=len(sample_bytes),
        )
        self.assertEqual(outcome, "SUCCESS_NEW")

        # Replay with same content & provenance -> SUCCESS_IDEMPOTENT_REDELIVERY
        att_dup, outcome_dup = ingest_attachment(
            evidence_name=ev.name,
            file_url=file_url,
            identity_type="provider_id",
            identity_value="att_id_f4",
            provenance_type="PROVIDER_PAYLOAD_DIGEST",
            expected_byte_count=len(sample_bytes),
        )
        self.assertEqual(outcome_dup, "SUCCESS_IDEMPOTENT_REDELIVERY")
        self.assertEqual(att.name, att_dup.name)

        # Replay with different provenance -> rejected with ValidationError
        with self.assertRaises(frappe.ValidationError):
            ingest_attachment(
                evidence_name=ev.name,
                file_url=file_url,
                identity_type="provider_id",
                identity_value="att_id_f4",
                provenance_type="OFFLINE_IMPORT_MANIFEST",
                provenance_ref="/some/other/manifest.json",
                expected_byte_count=len(sample_bytes),
            )

        # Ordinal identity without trusted provenance -> rejected
        with self.assertRaises(frappe.ValidationError):
            ingest_attachment(
                evidence_name=ev.name,
                file_url=file_url,
                identity_type="ordinal",
                identity_value=1,
                provenance_type="UNTRUSTED_CALLER",
            )

    def test_conflict_audit_durability_across_rollback(self):
        """Finding 5: Conflict attempt records must persist in the database even across transaction rollback."""
        payload_1 = {"text": "Original message for conflict test"}
        ev1, _ = ingest_message_evidence(
            provider="whatsapp-cloud",
            provider_account_id="ACC_BENCH",
            conversation_id="CONV_BENCH",
            provider_message_id="MSG_BENCH_F5",
            raw_payload=payload_1,
        )

        # Ingest conflicting payload: it records attempt with outcome CONFLICT_PAYLOAD_MISMATCH and returns conflict
        ev_conf, outcome = ingest_message_evidence(
            provider="whatsapp-cloud",
            provider_account_id="ACC_BENCH",
            conversation_id="CONV_BENCH",
            provider_message_id="MSG_BENCH_F5",
            raw_payload={"text": "TAMPERED payload"},
        )
        self.assertEqual(outcome, "CONFLICT_PAYLOAD_MISMATCH")

        # Rollback outer transaction
        frappe.db.rollback()

        # Check that the CONFLICT_PAYLOAD_MISMATCH attempt row is committed and still exists
        attempts = frappe.db.sql(
            """
            SELECT name, outcome, reason
            FROM `tabFresko Evidence Attempt`
            WHERE evidence = %s AND outcome = 'CONFLICT_PAYLOAD_MISMATCH'
            """,
            (ev1.name,),
            as_dict=True,
        )
        self.assertTrue(len(attempts) > 0, "Conflict audit attempt must survive transaction rollback")

    def test_parent_aggregation_mariadb_current_read(self):
        """Finding 7: Parent aggregation child query must use current-read locking (LOCK IN SHARE MODE)."""
        import inspect
        src = inspect.getsource(aggregate_parent_evidence_status)
        self.assertTrue(
            "LOCK IN SHARE MODE" in src or "FOR UPDATE" in src,
            "Parent aggregation child attachment query must use current-read locking (LOCK IN SHARE MODE)",
        )

        ev, _ = ingest_message_evidence(
            provider="whatsapp-cloud",
            provider_account_id="ACC_BENCH",
            conversation_id="CONV_BENCH",
            provider_message_id="MSG_BENCH_F7",
            manifest_status="FINALIZED",
            expected_attachment_count=1,
        )

        parent_status_1 = aggregate_parent_evidence_status(ev.name)
        self.assertEqual(parent_status_1, "PENDING")

    def test_baseline_to_current_migration_and_legacy_hashes(self):
        """Migration verification: historical rows with legacy hashes remain unverified and do not become CAPTURED."""
        ev = frappe.get_doc({
            "doctype": "Fresko Evidence",
            "evidence_type": "WhatsApp Message",
            "provider": "whatsapp-cloud",
            "overall_verification_status": "PENDING",
            "manifest_status": "UNKNOWN",
        })
        ev.insert(ignore_permissions=True)

        att = frappe.get_doc({
            "doctype": "Fresko Evidence Attachment",
            "evidence": ev.name,
            "file": "/private/files/legacy.pdf",
            "file_url": "/private/files/legacy.pdf",
            "identity_type": "ordinal",
            "attachment_ordinal": 0,
            "logical_attachment_key": "legacy_key",
            "version": 1,
            "scoped_attachment_version_key": "legacy_ver_1",
            "capture_status": "PENDING",
            "hash_algorithm": HASH_ALGORITHM_LEGACY_UNVERIFIED,
            "provenance_type": "MISSING_PROVENANCE",
            "is_current_version": 1,
        })
        att.insert(ignore_permissions=True)

        # Cannot aggregate to COMPLETE because manifest is UNKNOWN and attachment is unverified
        agg_status = aggregate_parent_evidence_status(ev.name)
        self.assertEqual(agg_status, "PENDING")
