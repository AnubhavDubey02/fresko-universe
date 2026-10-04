# Copyright (c) 2026, Fresko and contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


class FreskoOutward(Document):
    """Source-backed physical movement, immutable after posting."""

    def before_insert(self):
        if not self.flags.get("in_service"):
            frappe.throw(
                "Fresko Outward can only be created through controlled outward services",
                frappe.PermissionError,
            )
        if self.status != "Draft":
            frappe.throw("New Fresko Outward records must start in Draft")
        self.prepared_by = frappe.session.user
        self.prepared_at = now_datetime()
        self.submitted_by = None
        self.submitted_at = None
        self.posted_by = None
        self.posted_at = None

    def validate(self):
        self._validate_movement_shape()
        self._validate_lines()
        if self.is_new():
            return
        if not self.flags.get("in_service"):
            frappe.throw(
                "Direct modification of Fresko Outward is forbidden; use controlled outward services",
                frappe.PermissionError,
            )

        old_status = self.get_db_value("status")
        if old_status == "Posted":
            frappe.throw(
                "Posted Fresko Outward records are immutable; create a compensating reversal",
                frappe.PermissionError,
            )
        if self.status == old_status:
            frappe.throw(
                "Outward payload is immutable after creation; only controlled status transitions are allowed"
            )

        actor = frappe.session.user
        if old_status == "Draft" and self.status == "Review Pending":
            if not self.flags.get("allow_submit_for_review"):
                frappe.throw("Outward can enter Review Pending only through the controlled review service")
            if actor != self.prepared_by:
                frappe.throw("Only the Outward preparer may submit it for review", frappe.PermissionError)
            self.submitted_by = actor
            self.submitted_at = now_datetime()
            return

        if old_status == "Review Pending" and self.status == "Posted":
            if not self.flags.get("allow_post"):
                frappe.throw("Outward can be posted only through the controlled posting service")
            if actor in {self.prepared_by, self.submitted_by}:
                frappe.throw("Outward maker and poster must be different users", frappe.PermissionError)
            self.posted_by = actor
            self.posted_at = now_datetime()
            return

        frappe.throw(f"Invalid outward status transition {old_status} → {self.status}")

    def on_trash(self):
        frappe.throw(
            "Fresko Outward records cannot be deleted; posted truth requires a compensating reversal",
            frappe.PermissionError,
        )

    def _validate_movement_shape(self):
        if self.movement_type not in ("OUTWARD", "REVERSAL"):
            frappe.throw("Movement Type must be OUTWARD or REVERSAL")
        if self.movement_type == "REVERSAL" and not self.reverses_outward:
            frappe.throw("REVERSAL outward requires Reverses Outward")
        if self.movement_type == "OUTWARD" and self.reverses_outward:
            frappe.throw("OUTWARD movement cannot set Reverses Outward")
        if self.reverses_outward and self.reverses_outward == self.name:
            frappe.throw("An outward cannot reverse itself")

    def _validate_lines(self):
        lines = self.get("lines") or []
        if not lines:
            frappe.throw("Fresko Outward requires at least one physical line")
        seen_keys = set()
        for row in lines:
            line_key = str(getattr(row, "line_key", "") or "").strip()
            if not line_key:
                frappe.throw("Every outward line requires a server-assigned Line Key")
            if line_key in seen_keys:
                frappe.throw(f"Duplicate outward line key {line_key!r}")
            seen_keys.add(line_key)
            if flt(getattr(row, "qty", None)) <= 0:
                frappe.throw(f"Outward line {line_key}: Qty must be greater than zero")
            if not getattr(row, "uom", None):
                frappe.throw(f"Outward line {line_key}: UOM is required")
            if not str(getattr(row, "raw_qty_text", "") or "").strip():
                frappe.throw(f"Outward line {line_key}: Raw Qty Text is required")
            if not str(getattr(row, "raw_uom_text", "") or "").strip():
                frappe.throw(f"Outward line {line_key}: Raw UOM Text is required")
