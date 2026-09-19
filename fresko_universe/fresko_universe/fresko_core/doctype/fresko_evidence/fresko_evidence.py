# Copyright (c) 2026, Anubhav Dubey and contributors
from __future__ import annotations

import frappe
from frappe.model.document import Document

from fresko_universe.constants import SCOPED_MESSAGE_KEY_VERSION


class FreskoEvidence(Document):
    """Message and operational evidence container.

    Enforces immutability of identity, payload, and verified integrity fields.
    Does not hash path or URL strings into content_sha256 — content hashes are
    computed from actual file bytes. This is one repair contributing to FSEC-004;
    it does not close it. FSEC-004 remains OPEN as a Phase 2 entry gate (see
    docs/security/SECURITY_FINDINGS.md).
    """

    def before_insert(self):
        # Default operational statuses if not set
        if not self.overall_verification_status:
            self.overall_verification_status = "PENDING"
        if not self.manifest_status:
            self.manifest_status = "UNKNOWN"
        if self.expected_attachment_count is None:
            self.expected_attachment_count = -1
        if self.verified_attachment_count is None:
            self.verified_attachment_count = 0

        # Compute scoped_message_key if all 4 scope fields are present
        if not self.scoped_message_key:
            scope = [
                self.provider,
                self.provider_account_id,
                self.conversation_id,
                self.provider_message_id,
            ]
            if all(isinstance(v, str) and v.strip() for v in scope):
                import hashlib
                import json

                payload = json.dumps(
                    [
                        SCOPED_MESSAGE_KEY_VERSION,
                        self.provider.strip(),
                        self.provider_account_id.strip(),
                        self.conversation_id.strip(),
                        self.provider_message_id.strip(),
                    ],
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                self.scoped_message_key = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def validate(self):
        if self.is_new():
            # Desk/API callers cannot forge verified state
            if not getattr(self.flags, "in_service", False):
                if self.overall_verification_status in ("COMPLETE", "CONFLICT"):
                    frappe.throw(
                        "Cannot initialize Evidence with COMPLETE or CONFLICT verification status",
                        frappe.PermissionError,
                    )
            return

        # Direct Desk/API changes to operational aggregation/identity fields are blocked
        if not getattr(getattr(self, "flags", None), "in_service", False):
            for f in (
                "overall_verification_status",
                "verified_attachment_count",
                "manifest_status",
                "scoped_message_key",
                "message_payload_sha256",
            ):
                if self.has_value_changed(f):
                    frappe.throw(
                        f"Direct modification of '{f}' is forbidden; use system services",
                        frappe.PermissionError,
                    )

        # Immutability once set
        immutable_fields = (
            "content_sha256",
            "message_id",
            "file",
            "external_ref",
            "scoped_message_key",
            "provider",
            "provider_account_id",
            "conversation_id",
            "provider_message_id",
            "message_payload_sha256",
        )
        for f in immutable_fields:
            if self.has_value_changed(f) and self.get_db_value(f):
                frappe.throw(
                    f"Evidence field '{f}' is immutable once set",
                    title="Evidence Immutable",
                )

    def on_trash(self):
        from fresko_universe.fresko_core.services.evidence_service import prevent_captured_evidence_deletion

        prevent_captured_evidence_deletion(self)
