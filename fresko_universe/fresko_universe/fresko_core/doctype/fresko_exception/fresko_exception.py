# Copyright (c) 2026, Anubhav Dubey and contributors
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

QUANTITY_SCOPE_FIELDS = (
    "declared_quantity_assertion",
    "operating_quantity_assertion",
    "variance_quantity",
    "variance_uom",
    "variance_key",
)


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

        self._validate_scope()
        self._validate_immutability()

    def _validate_scope(self):
        outward_exception_types = {
            "OUTWARD_UNPRICED",
            "OUTWARD_WITHOUT_DEAL",
            "LOT_UNRESOLVED",
            "DUPLICATE_GATEPASS",
            "PHYSICAL_VARIANCE",
        }

        has_outward = bool(getattr(self, "outward", None))
        # Any quantity-scope field marks the row as quantity-scoped, so a Desk
        # row of another type cannot squat a variance_key or assertion links.
        has_quantity_links = any(
            getattr(self, fieldname, None) for fieldname in QUANTITY_SCOPE_FIELDS
        )

        # Mutual exclusion: a row may not carry both outward and quantity links.
        if has_outward and has_quantity_links:
            frappe.throw(
                "A Fresko Exception cannot carry both Outward and quantity assertion links"
            )
        if has_quantity_links and self.exception_type != "PHYSICAL_VARIANCE":
            frappe.throw(
                "Quantity assertion scope fields are allowed only on PHYSICAL_VARIANCE",
                frappe.PermissionError,
            )

        if self.exception_type == "PHYSICAL_VARIANCE":
            if has_outward:
                # Outward-scoped PHYSICAL_VARIANCE — existing behaviour
                self._validate_outward_scoped()
            elif has_quantity_links:
                # Quantity-scoped PHYSICAL_VARIANCE
                self._validate_quantity_scoped()
            else:
                frappe.throw(
                    "PHYSICAL_VARIANCE requires either a linked Outward or quantity assertion scope"
                )
            return

        if self.exception_type in outward_exception_types:
            self._validate_outward_scoped()

    def _validate_outward_scoped(self):
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

    def _validate_quantity_scoped(self):
        declared = getattr(self, "declared_quantity_assertion", None)
        operating = getattr(self, "operating_quantity_assertion", None)
        if not declared or not operating or declared == operating:
            frappe.throw(
                "Quantity-scoped PHYSICAL_VARIANCE requires two distinct quantity assertion links"
            )
        if not getattr(self, "container", None):
            frappe.throw(
                "Quantity-scoped PHYSICAL_VARIANCE requires a linked Container"
            )
        vq = getattr(self, "variance_quantity", None)
        if not vq or not str(vq).strip():
            frappe.throw(
                "Quantity-scoped PHYSICAL_VARIANCE requires non-empty variance_quantity"
            )
        try:
            parsed = Decimal(str(vq).strip())
        except InvalidOperation:
            frappe.throw(
                "variance_quantity must be a valid decimal number"
            )
        if not parsed.is_finite():
            frappe.throw("variance_quantity must be a finite decimal number")
        if parsed == 0:
            frappe.throw(
                "Quantity-scoped PHYSICAL_VARIANCE requires non-zero variance_quantity"
            )
        if not getattr(self, "variance_uom", None):
            frappe.throw(
                "Quantity-scoped PHYSICAL_VARIANCE requires variance_uom"
            )
        if not getattr(self, "variance_key", None):
            frappe.throw(
                "Quantity-scoped PHYSICAL_VARIANCE requires variance_key"
            )
        if not getattr(self.flags, "in_quantity_service", False):
            frappe.throw(
                "Quantity variance Exceptions can be changed only by the controlled quantity service",
                frappe.PermissionError,
            )

    def _validate_immutability(self):
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

        # Quantity assertion links and variance fields are immutable once set.
        for fieldname in QUANTITY_SCOPE_FIELDS:
            if not self.is_new() and self.has_value_changed(fieldname):
                existing = self.get_db_value(fieldname)
                if existing:
                    frappe.throw(
                        f"{fieldname} is immutable once set on a Fresko Exception",
                        frappe.PermissionError,
                    )
        # The Container is the lock root of a quantity-scoped variance.
        if (
            not self.is_new()
            and self.get_db_value("variance_key")
            and self.has_value_changed("container")
        ):
            frappe.throw(
                "Container is immutable on a quantity-scoped PHYSICAL_VARIANCE",
                frappe.PermissionError,
            )

    def on_trash(self):
        # Deleting would silently clear the Container close gate; resolve or waive instead.
        if any(getattr(self, fieldname, None) for fieldname in QUANTITY_SCOPE_FIELDS):
            frappe.throw(
                "Quantity-scoped PHYSICAL_VARIANCE cannot be deleted; resolve or waive it",
                frappe.PermissionError,
            )
