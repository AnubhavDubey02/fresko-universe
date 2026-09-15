# Copyright (c) 2026, Fresko and contributors
# License: MIT

import frappe
from frappe.model.document import Document


class FreskoRevision(Document):
    def before_insert(self):
        if not self.changed_by:
            self.changed_by = frappe.session.user
        if not self.changed_at:
            self.changed_at = frappe.utils.now_datetime()
        if not self.reason:
            frappe.throw("Revision reason is mandatory")

    def validate(self):
        if not self.is_new() and self.has_value_changed("old_value"):
            frappe.throw("Cannot alter historical revision old_value")
