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
