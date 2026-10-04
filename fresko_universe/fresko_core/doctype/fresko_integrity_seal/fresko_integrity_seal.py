from __future__ import annotations

import frappe
from frappe.model.document import Document


# Fields that form the immutable baseline once inserted.
_BASELINE_FIELDS = frozenset({
    "record_doctype",
    "record_name",
    "seal_key",
    "seal_version",
    "container",
    "payload_sha256",
    "sealed_at",
})

# Fields that may transition from empty to set exactly once.
_TERMINAL_FIELDS = frozenset({
    "terminal_status",
    "terminal_sha256",
    "terminal_sealed_at",
})

_MISMATCH_FIELDS = frozenset({
    "mismatch_kind",
    "mismatch_observed_sha256",
    "mismatch_detected_at",
    "mismatch_exception",
})


class FreskoIntegritySeal(Document):
    def before_insert(self):
        if not getattr(self.flags, "in_integrity_service", False):
            frappe.throw(
                "Integrity seals can only be created by the integrity service",
                frappe.PermissionError,
            )

    def validate(self):
        if not getattr(self.flags, "in_integrity_service", False):
            frappe.throw(
                "Integrity seals can only be modified by the integrity service",
                frappe.PermissionError,
            )
        if not self.is_new():
            self._validate_immutability()

    def on_trash(self):
        frappe.throw(
            "Integrity seals cannot be deleted",
            frappe.PermissionError,
        )

    def _validate_immutability(self):
        for fieldname in _BASELINE_FIELDS:
            if self.has_value_changed(fieldname):
                frappe.throw(
                    f"Integrity seal field '{fieldname}' is immutable",
                    frappe.PermissionError,
                )
        for fieldname in _TERMINAL_FIELDS | _MISMATCH_FIELDS:
            if self.has_value_changed(fieldname):
                old = self.get_db_value(fieldname)
                if old not in (None, ""):
                    frappe.throw(
                        f"Integrity seal field '{fieldname}' cannot be overwritten once set",
                        frappe.PermissionError,
                    )
