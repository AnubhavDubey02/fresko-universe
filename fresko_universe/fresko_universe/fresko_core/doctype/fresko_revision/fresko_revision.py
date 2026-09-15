# Copyright (c) 2026, Fresko and contributors
# License: MIT

import frappe
from frappe.model.document import Document

from fresko_universe.constants import REVISION_ELIGIBLE_FIELDS

_HISTORICAL_FIELDS = (
    "old_value",
    "new_value",
    "reason",
    "fieldname",
    "parent_doctype",
    "parent_name",
    "supporting_evidence",
    "approval_reference",
    "changed_by",
    "changed_at",
)


class FreskoRevision(Document):
    def before_insert(self):
        if not self.flags.get("allow_controlled_insert"):
            frappe.throw(
                "Fresko Revision can only be created through deals.request_revision",
                frappe.PermissionError,
            )
        # Client-supplied provenance never wins, even on ignore_permissions inserts.
        self.changed_by = frappe.session.user
        self.changed_at = frappe.utils.now_datetime()
        if not self.reason:
            frappe.throw("Revision reason is mandatory")
        if self.parent_doctype != "Fresko Deal":
            frappe.throw("Only Fresko Deal revisions are supported in Phase 1")
        if self.fieldname not in REVISION_ELIGIBLE_FIELDS:
            frappe.throw(f"Field {self.fieldname} is not revision-eligible")
        if self.status != "Pending":
            frappe.throw("New Fresko Revision must start Pending")

    def validate(self):
        if self.is_new():
            return
        old_status = self.get_db_value("status")
        # After Applied: freeze all historical trail fields (Controls B2)
        if old_status == "Applied" or self.status == "Applied":
            if self.has_value_changed("status") and old_status == "Applied":
                frappe.throw("Cannot change status of an Applied revision")
            for f in _HISTORICAL_FIELDS:
                if self.has_value_changed(f):
                    # Allow linking approval_reference only while transitioning Pending → Applied
                    if (
                        f == "approval_reference"
                        and old_status == "Pending"
                        and self.status == "Applied"
                        and self.flags.get("allow_revision_apply")
                    ):
                        continue
                    frappe.throw(f"Cannot alter historical revision field '{f}' after Applied")
            if old_status == "Pending" and self.status == "Applied":
                if not self.flags.get("allow_revision_apply"):
                    frappe.throw("Revision status Applied only via deals.apply_revision")
            return
        # Pending: still freeze old_value trail seed
        if self.has_value_changed("old_value"):
            frappe.throw("Cannot alter historical revision old_value")
        for f in ("fieldname", "parent_doctype", "parent_name"):
            if self.has_value_changed(f):
                frappe.throw(f"Cannot alter revision identity field '{f}'")
