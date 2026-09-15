# Copyright (c) 2026, Anubhav Dubey and contributors
from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class FreskoException(Document):
    def validate(self):
        if not self.opened_by:
            self.opened_by = frappe.session.user
        if not self.opened_at:
            self.opened_at = now_datetime()
        if self.status in ("Resolved", "Waived") and not self.resolved_at:
            self.resolved_at = now_datetime()
            self.resolved_by = self.resolved_by or frappe.session.user
