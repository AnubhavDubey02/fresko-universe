# Copyright (c) 2026, Anubhav Dubey and contributors
from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class FreskoException(Document):
    def validate(self):
        # Audit fields (opened_by/opened_at/resolved_*) live on the DocType JSON.
        # getattr keeps validate safe if a site is mid-migrate.
        if not getattr(self, "opened_by", None):
            self.opened_by = frappe.session.user
        if not getattr(self, "opened_at", None):
            self.opened_at = now_datetime()
        if self.status in ("Resolved", "Waived") and not getattr(self, "resolved_at", None):
            self.resolved_at = now_datetime()
            self.resolved_by = getattr(self, "resolved_by", None) or frappe.session.user

        outward_exception_types = {
            "OUTWARD_UNPRICED",
            "OUTWARD_WITHOUT_DEAL",
            "LOT_UNRESOLVED",
            "DUPLICATE_GATEPASS",
            "PHYSICAL_VARIANCE",
        }
        if self.exception_type in outward_exception_types:
            if not getattr(self, "outward", None):
                frappe.throw(f"{self.exception_type} requires a linked Fresko Outward")
            if self.exception_type == "DUPLICATE_GATEPASS":
                related = getattr(self, "related_outward", None)
                if not related or related == self.outward:
                    frappe.throw(
                        "DUPLICATE_GATEPASS requires two distinct linked Outwards"
                    )
            if not getattr(self.flags, "in_outward_service", False):
                frappe.throw(
                    "Outward control Exceptions can be changed only by the controlled outward service",
                    frappe.PermissionError,
                )

        if not self.is_new() and self.has_value_changed("outward"):
            existing_outward = self.get_db_value("outward")
            if existing_outward:
                frappe.throw(
                    "Linked Outward is immutable once set on a Fresko Exception",
                    frappe.PermissionError,
                )
        if not self.is_new() and self.has_value_changed("related_outward"):
            existing_related = self.get_db_value("related_outward")
            if existing_related:
                frappe.throw(
                    "Related Outward is immutable once set on a Fresko Exception",
                    frappe.PermissionError,
                )
