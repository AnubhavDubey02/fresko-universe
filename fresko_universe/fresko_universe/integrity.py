"""Public entry points for the periodic integrity checker."""
from __future__ import annotations

import frappe

from fresko_universe.fresko_core.services import integrity_service
from fresko_universe.permissions import assert_can_run_integrity_check


@frappe.whitelist()
def run_check():
    assert_can_run_integrity_check()
    return integrity_service.run_integrity_check()


def scheduled_integrity_check():
    summary = integrity_service.run_integrity_check()
    frappe.db.commit()
    return summary
