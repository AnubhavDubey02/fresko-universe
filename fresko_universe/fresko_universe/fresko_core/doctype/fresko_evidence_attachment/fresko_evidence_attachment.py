# Copyright (c) 2026, Anubhav Dubey and contributors
from __future__ import annotations

import frappe
from frappe.model.document import Document


class FreskoEvidenceAttachment(Document):
    """Attachment record linked to a parent Fresko Evidence message.

    Enforces immutability of identity, versioned content, and hashes.
    Creation and capture state updates are server-method only.
    """

    def validate(self):
        from fresko_universe.constants import TRUSTED_PROVENANCE_TYPES

        if self.is_new():
            # Desk or raw API callers cannot inject CAPTURED status, forged hashes, or trusted provenance
            if not getattr(self.flags, "in_service", False):
                if getattr(self, "capture_status", None) in ("CAPTURED", "VERIFYING"):
                    frappe.throw(
                        "Cannot initialize attachment with CAPTURED or VERIFYING status",
                        frappe.PermissionError,
                    )
                if getattr(self, "content_sha256", None) or getattr(self, "readback_verified", None):
                    frappe.throw(
                        "Cannot supply precomputed hash or readback verification flag",
                        frappe.PermissionError,
                    )
                if getattr(self, "provenance_type", None) in TRUSTED_PROVENANCE_TYPES:
                    frappe.throw(
                        "Cannot set trusted completeness provenance via direct Desk/API; server-controlled service required",
                        frappe.PermissionError,
                    )
                self.capture_status = "PENDING"
                self.content_sha256 = None
                self.content_byte_count = 0
                self.hash_algorithm = None
                self.readback_verified = 0
                self.provenance_type = "UNTRUSTED_CALLER"
            return

        # Updates on existing documents
        if not getattr(self.flags, "in_service", False):
            frappe.throw(
                "Direct Desk/API modification of Fresko Evidence Attachment is forbidden",
                frappe.PermissionError,
            )

        # Immutability of identity fields
        for field in (
            "logical_attachment_key",
            "scoped_attachment_version_key",
            "version",
            "evidence",
            "identity_type",
            "provider_attachment_id",
            "attachment_ordinal",
            "provider",
            "provider_account_id",
            "conversation_id",
            "provider_message_id",
        ):
            if self.has_value_changed(field) and self.get_db_value(field):
                frappe.throw(
                    f"Attachment identity field '{field}' is immutable once set",
                    frappe.PermissionError,
                )

        # Even in service: captured fields are immutable once verified
        old_status = self.get_db_value("capture_status")
        if old_status == "CAPTURED":
            for field in (
                "file",
                "file_url",
                "storage_ref",
                "content_sha256",
                "content_byte_count",
                "hash_algorithm",
                "readback_verified",
            ):
                if self.has_value_changed(field):
                    frappe.throw(
                        f"Attachment content field '{field}' is immutable once CAPTURED",
                        frappe.PermissionError,
                    )

    def on_trash(self):
        frappe.throw(
            "Fresko Evidence Attachment records cannot be deleted. Use the superseding correction flow.",
            frappe.PermissionError,
        )
