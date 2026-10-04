# Copyright (c) 2026, Fresko and contributors
# License: MIT

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


_PAYLOAD_FIELDS = (
    "outward",
    "outward_line_key",
    "asserted_field",
    "assertion_basis",
    "raw_value",
    "rate",
    "currency",
    "rate_uom",
    "evidence",
    "effective_at",
    "reason",
    "supersedes",
    "assertion_key",
    "payload_sha256",
)


class FreskoFieldAssertion(Document):
    """Immutable source-backed claim with controlled review transitions."""

    def before_insert(self):
        if not self.flags.get("in_service"):
            frappe.throw(
                "Fresko Field Assertion can only be created through controlled assertion services",
                frappe.PermissionError,
            )
        if self.status != "Draft":
            frappe.throw("New Fresko Field Assertion records must start in Draft")
        self.prepared_by = frappe.session.user
        self.prepared_at = now_datetime()
        self.asserted_by = None
        self.asserted_at = None
        self.reviewed_by = None
        self.reviewed_at = None
        self.activated_by = None
        self.activated_at = None
        self.superseded_by = None
        self.rate = _canonical_decimal_or_none(self.rate)
        if self.rate is not None and (
            not self.currency or not self.rate_uom or not self.effective_at
        ):
            frappe.throw(
                "A known Normalized Rate requires Rate Currency, Rate UOM, and Effective At"
            )

    def validate(self):
        self._validate_payload()
        if self.is_new():
            self._validate_supersession()
            return

        if not self.flags.get("in_service"):
            frappe.throw(
                "Direct modification of Fresko Field Assertion is forbidden; use controlled assertion services",
                frappe.PermissionError,
            )
        for fieldname in _PAYLOAD_FIELDS:
            if self.has_value_changed(fieldname):
                frappe.throw(
                    f"Field Assertion payload field '{fieldname}' is immutable",
                    frappe.PermissionError,
                )

        old_status = self.get_db_value("status")
        if self.status == old_status:
            frappe.throw("Field Assertion can be saved only for a controlled status transition")

        actor = frappe.session.user
        if old_status == "Draft" and self.status == "Review Pending":
            if actor != self.prepared_by:
                frappe.throw("Only the assertion preparer may submit it for review", frappe.PermissionError)
            self.asserted_by = actor
            self.asserted_at = now_datetime()
            return

        if old_status == "Review Pending" and self.status in ("Active", "Rejected"):
            if actor in {self.prepared_by, self.asserted_by}:
                frappe.throw("Assertion maker and reviewer must be different users", frappe.PermissionError)
            self.reviewed_by = actor
            self.reviewed_at = now_datetime()
            if self.status == "Active":
                self.activated_by = actor
                self.activated_at = self.reviewed_at
            return

        if old_status == "Active" and self.status == "Superseded":
            if not self.superseded_by:
                frappe.throw("Active assertion can be superseded only by a controlled successor")
            return

        frappe.throw(f"Invalid Field Assertion status transition {old_status} → {self.status}")

    def on_trash(self):
        frappe.throw(
            "Fresko Field Assertion records cannot be deleted; append a superseding assertion",
            frappe.PermissionError,
        )

    def _validate_payload(self):
        if self.asserted_field != "rate":
            frappe.throw("Phase 2A foundation supports only rate assertions")
        if not str(self.raw_value or "").strip():
            frappe.throw("Raw Source Value is required, including when normalized rate is unknown")
        if not str(self.assertion_key or "").strip():
            frappe.throw("Assertion Key must be assigned by the controlled service")
        if not str(self.payload_sha256 or "").strip():
            frappe.throw("Payload SHA256 must be assigned by the controlled service")
        self.rate = _canonical_decimal_or_none(self.rate)
        if self.outward_line_key and not frappe.db.exists(
            "Fresko Outward Line",
            {
                "parent": self.outward,
                "parenttype": "Fresko Outward",
                "line_key": self.outward_line_key,
            },
        ):
            frappe.throw(
                f"Outward line key {self.outward_line_key!r} does not belong to {self.outward}"
            )

    def _validate_supersession(self):
        if not self.supersedes:
            return
        if self.supersedes == self.name:
            frappe.throw("A field assertion cannot supersede itself")
        predecessor = frappe.db.get_value(
            "Fresko Field Assertion",
            self.supersedes,
            ["outward", "outward_line_key", "asserted_field", "status"],
            as_dict=True,
        )
        if not predecessor:
            frappe.throw(f"Superseded assertion {self.supersedes} does not exist")
        if (
            predecessor.outward != self.outward
            or predecessor.outward_line_key != self.outward_line_key
            or predecessor.asserted_field != self.asserted_field
        ):
            frappe.throw("A superseding assertion must target the same Outward line and field")
        if predecessor.status != "Active":
            frappe.throw("Only an Active Field Assertion can be superseded")
        # Multiple Draft candidates may cite the same active predecessor. The
        # Container lock and current reads serialize activation; exactly one
        # candidate can become Active and supersede the predecessor.


def _canonical_decimal_or_none(value) -> str | None:
    """Keep unknown as SQL NULL and a known zero as canonical text '0'."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        decimal_value = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        frappe.throw("Normalized Rate must be a valid decimal value or blank")
    if not decimal_value.is_finite() or decimal_value < 0:
        frappe.throw("Normalized Rate must be finite and non-negative")
    normalized = format(decimal_value.normalize(), "f")
    return "0" if normalized in ("-0", "") else normalized
