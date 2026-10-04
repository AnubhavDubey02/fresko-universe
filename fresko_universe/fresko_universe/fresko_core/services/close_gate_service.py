"""Private, read-only Container closure check over current accepted runtime.

The caller holds Company before Container, matching Commercial/Money writers.
This is an exception gate, not a zero-receivable or settlement assertion. Never
refresh ledgers or expose restricted receipt details from Document validation.
"""
from __future__ import annotations

import json

import frappe

from fresko_universe.fresko_core.services.close_policy import exception_is_material

CLOSE_DENIED = "Cannot set Fully Reconciled while open material Exceptions exist on this container"


def lock_close_gate_company(company: str) -> None:
    if not frappe.db.sql("SELECT name FROM `tabCompany` WHERE name=%s FOR UPDATE", (company,)):
        frappe.throw("A valid Company is required for Fully Reconciled")


def assert_container_can_fully_reconcile(container: str, company: str) -> None:
    """Inspect current state without granting the caller access to Money records."""
    current = frappe.db.sql(
        "SELECT company FROM `tabFresko Container` WHERE name=%s FOR UPDATE",
        (container,), as_dict=True,
    )
    if current and current[0].company != company:
        frappe.throw("Container Company cannot change while setting Fully Reconciled")

    direct = frappe.db.sql(
        """SELECT exception_type, severity FROM `tabFresko Exception`
        WHERE container=%s AND status IN ('Open', 'In Progress')
        ORDER BY name FOR UPDATE""", (container,), as_dict=True,
    )
    if any(exception_is_material(row.exception_type, row.severity) for row in direct):
        frappe.throw(CLOSE_DENIED)

    # Allocation proposals identify receipt-level problems, not ownership of a
    # pooled receipt's remaining funds. Terminal allocations establish no scope.
    allocations = frappe.db.sql(
        """SELECT collection FROM `tabFresko Payment Allocation`
        WHERE company=%s AND container=%s
        AND status IN ('DRAFT', 'REVIEW_PENDING', 'VERIFIED', 'APPROVED')
        ORDER BY name FOR UPDATE""", (company, container), as_dict=True,
    )
    linked_collections = {row.collection for row in allocations}
    receipts = frappe.db.sql(
        """SELECT ex.exception_type, ex.severity, c.name AS collection, c.evidence_snapshot
        FROM `tabFresko Exception` ex
        INNER JOIN `tabFresko Collection` c ON c.name=ex.collection
        WHERE ex.money_company=%s AND c.company=%s
        AND ex.status IN ('Open', 'In Progress')
        ORDER BY ex.name FOR UPDATE""", (company, company), as_dict=True,
    )
    for row in receipts:
        try:
            snapshot = json.loads(row.evidence_snapshot or "null")
        except (ValueError, TypeError):
            snapshot = None
        source_container = snapshot.get("container") if isinstance(snapshot, dict) else None
        attributed = source_container == container or (
            row.exception_type != "MONEY_UNALLOCATED" and row.collection in linked_collections
        )
        if attributed and exception_is_material(row.exception_type, row.severity):
            frappe.throw(CLOSE_DENIED)
