# Copyright (c) 2026, Anubhav Dubey and contributors
from __future__ import annotations

import hashlib

import frappe
from frappe.model.document import Document


class FreskoEvidence(Document):
    """Immutable originals once content_sha256 / message_id set.

    Canonical fieldname matches DocType JSON: content_sha256 everywhere.
    """

    def before_insert(self):
        if self.file and not self.content_sha256:
            # Best-effort hash of file URL/path string if binary not available
            self.content_sha256 = hashlib.sha256(
                (self.file or self.external_ref or "").encode("utf-8")
            ).hexdigest()

    def validate(self):
        if self.is_new():
            return
        for f in ("content_sha256", "message_id", "file", "external_ref"):
            if self.has_value_changed(f) and self.get_db_value(f):
                frappe.throw(
                    f"Evidence field '{f}' is immutable once set",
                    title="Evidence Immutable",
                )
