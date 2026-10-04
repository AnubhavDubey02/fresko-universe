# Copyright (c) 2026, Anubhav Dubey and contributors
from __future__ import annotations

import frappe
from frappe.model.document import Document


class FreskoEvidenceAttempt(Document):
    """Structured append-only audit trail for evidence operations.

    Strictly immutable once written; can only be inserted via server services.
    """

    def before_insert(self):
        if not getattr(self.flags, "in_service", False):
            frappe.throw(
                "Fresko Evidence Attempt records can only be created by system services",
                frappe.PermissionError,
            )

    def validate(self):
        if not self.is_new():
            frappe.throw(
                "Fresko Evidence Attempt records are append-only and cannot be modified",
                frappe.PermissionError,
            )

    def on_trash(self):
        frappe.throw(
            "Fresko Evidence Attempt records cannot be deleted",
            frappe.PermissionError,
        )
