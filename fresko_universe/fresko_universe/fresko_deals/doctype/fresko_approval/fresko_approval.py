# Copyright (c) 2026, Fresko and contributors
# License: MIT — append-only approvals

import frappe
from frappe.model.document import Document


class FreskoApproval(Document):
    def before_insert(self):
        if not self.approver:
            self.approver = frappe.session.user
        if not self.decided_at:
            self.decided_at = frappe.utils.now_datetime()

    def validate(self):
        if not self.is_new():
            frappe.throw("Fresko Approval is append-only; edits are not allowed")

    def on_trash(self):
        if "System Manager" not in frappe.get_roles():
            frappe.throw("Only System Manager may delete Approval records")
