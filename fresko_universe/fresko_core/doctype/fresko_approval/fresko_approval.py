# Copyright (c) 2026, Fresko and contributors
# License: MIT — append-only approvals

import frappe
from frappe.model.document import Document

from fresko_universe.constants import OVERSELL_OVERRIDE_ROLES


class FreskoApproval(Document):
    def before_insert(self):
        if not self.flags.get("allow_controlled_insert"):
            frappe.throw(
                "Fresko Approval can only be created through controlled approval methods",
                frappe.PermissionError,
            )
        # Client-supplied provenance never wins, even on ignore_permissions inserts.
        self.approver = frappe.session.user
        self.decided_at = frappe.utils.now_datetime()
        if self.consumed is None:
            self.consumed = 0
        if self.decision == "OVERSELL_OVERRIDE" or int(self.oversell_override or 0):
            if not (set(frappe.get_roles()) & OVERSELL_OVERRIDE_ROLES):
                frappe.throw("Oversell override restricted to System Manager (D10)")

    def validate(self):
        if self.revision:
            if not frappe.db.exists("Fresko Revision", self.revision):
                frappe.throw(f"Fresko Revision {self.revision} not found")
            parent_doctype, parent_name = frappe.db.get_value(
                "Fresko Revision", self.revision, ["parent_doctype", "parent_name"]
            )
            if parent_doctype != "Fresko Deal":
                frappe.throw("Approval.revision must point at a Fresko Deal revision")
            if self.deal and str(parent_name) != str(self.deal):
                frappe.throw(
                    f"Approval.revision {self.revision} belongs to deal {parent_name}, "
                    f"not {self.deal}"
                )

        if not self.is_new():
            frappe.throw("Fresko Approval is append-only; edits are not allowed")

    def on_trash(self):
        if "System Manager" not in frappe.get_roles():
            frappe.throw("Only System Manager may delete Approval records")
