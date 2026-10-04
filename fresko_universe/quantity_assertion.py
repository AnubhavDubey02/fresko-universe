"""Whitelisted facade for controlled Container Quantity Assertion operations."""
from __future__ import annotations

import frappe

from fresko_universe.fresko_core.services import quantity_assertion_service as service


@frappe.whitelist()
def create(
    container,
    basis,
    raw_value,
    quantity,
    uom,
    raw_uom,
    evidence,
    effective_at,
    provenance,
    reason,
    source_fact_id,
    supersedes=None,
):
    """Client actor, audit timestamps, hashes, and status are intentionally not accepted."""
    return service.create_quantity_assertion(
        container=container, basis=basis, raw_value=raw_value, quantity=quantity,
        uom=uom, raw_uom=raw_uom, evidence=evidence, effective_at=effective_at,
        provenance=provenance, reason=reason, source_fact_id=source_fact_id,
        supersedes=supersedes,
    )


@frappe.whitelist()
def submit(name: str):
    return service.submit_quantity_assertion(name)


@frappe.whitelist()
def review(name: str, decision: str):
    return service.review_quantity_assertion(name, decision)


@frappe.whitelist()
def reconciliation_projection(container: str):
    return service.quantity_reconciliation_projection(container)


@frappe.whitelist()
def ensure_physical_variance(container: str):
    return service.ensure_physical_variance(container)


@frappe.whitelist()
def resolve_physical_variance(name: str, decision: str, notes: str):
    return service.resolve_physical_variance(name, decision, notes)
