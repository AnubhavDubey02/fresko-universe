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
            raw_payload={"text": "Bench test message"},
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
