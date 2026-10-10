"""Service-owned append-only intake metadata; never a posting document."""
import frappe
from frappe.model.document import Document


class FreskoIntakeRevision(Document):
    def validate(self):
        if not getattr(self.flags, 'intake_service', False) or not self.is_new():
            frappe.throw('Intake changes require authenticated server service', frappe.PermissionError)
        if self.get('can_post'):
            frappe.throw('Intake cannot post', frappe.PermissionError)

    def on_trash(self):
        frappe.throw('Intake history cannot be deleted', frappe.PermissionError)

    def before_rename(self, *args, **kwargs):
        frappe.throw('Intake history cannot be renamed', frappe.PermissionError)
