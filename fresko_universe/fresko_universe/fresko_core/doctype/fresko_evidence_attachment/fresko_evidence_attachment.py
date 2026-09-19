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
        if self.is_new():
            # Desk or raw API callers cannot inject CAPTURED status or forged hashes
            if not getattr(self.flags, "in_service", False):
                if self.capture_status in ("CAPTURED", "VERIFYING"):
                    frappe.throw(
                        "Cannot initialize attachment with CAPTURED or VERIFYING status",
                        frappe.PermissionError,
                    )
                if self.content_sha256 or self.readback_verified:
                    frappe.throw(
                        "Cannot supply precomputed hash or readback verification flag",
                        frappe.PermissionError,
                    )
                self.capture_status = "PENDING"
                self.content_sha256 = None
                self.content_byte_count = 0
                self.hash_algorithm = None
                self.readback_verified = 0
            return

        # Updates on existing documents
        if not getattr(self.flags, "in_service", False):
            frappe.throw(
                "Direct Desk/API modification of Fresko Evidence Attachment is forbidden",
                frappe.PermissionError,
            )

        # Even in service: captured fields are immutable once verified
        old_status = self.get_db_value("capture_status")
        if old_status == "CAPTURED":
            for field in (
                "file",
                "storage_ref",
                "content_sha256",
                "content_byte_count",
                "hash_algorithm",
                "logical_attachment_key",
                "scoped_attachment_version_key",
                "version",
                "evidence",
            ):
                if self.has_value_changed(field):
                    frappe.throw(
                        f"Attachment field '{field}' is immutable once CAPTURED",
                        frappe.PermissionError,
                    )

    def on_trash(self):
        frappe.throw(
            "Fresko Evidence Attachment records cannot be deleted. Use the superseding correction flow.",
            frappe.PermissionError,
        )
