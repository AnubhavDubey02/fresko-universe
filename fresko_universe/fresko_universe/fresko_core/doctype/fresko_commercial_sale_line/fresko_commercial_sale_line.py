"""Controlled commercial source and decision records."""
import frappe
from frappe.model.document import Document
from fresko_universe.fresko_core.services.commercial_service import validate_commercial_document


class FreskoCommercialSaleLine(Document):
    def before_insert(self):
        validate_commercial_document(self)

    def validate(self):
        validate_commercial_document(self)

    def on_trash(self):
        frappe.throw("Commercial history cannot be deleted; use an audited correction or reversal", frappe.PermissionError)

    def before_rename(self, old, new, merge=False):
        frappe.throw("Commercial source identity cannot be renamed", frappe.PermissionError)
