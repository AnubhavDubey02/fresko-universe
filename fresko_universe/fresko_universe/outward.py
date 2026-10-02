"""Public Phase 2A Outward and Field Assertion API facade."""

from __future__ import annotations

import frappe

from fresko_universe.fresko_core.services import outward_service


@frappe.whitelist()
def create(
    container,
    movement_at,
    source_evidence,
    source_event_id,
    lines,
    posting_reason=None,
    deal=None,
    gatepass_no=None,
    vehicle_no=None,
    raw_party_name=None,
):
    return outward_service.create_outward(
        container=container,
        movement_at=movement_at,
        source_evidence=source_evidence,
        source_event_id=source_event_id,
        lines=lines,
        posting_reason=posting_reason,
        deal=deal,
        gatepass_no=gatepass_no,
        vehicle_no=vehicle_no,
        raw_party_name=raw_party_name,
    )


@frappe.whitelist()
def submit_for_review(outward_name: str):
    return outward_service.submit_outward_for_review(outward_name)


@frappe.whitelist()
def post(outward_name: str):
    return outward_service.post_outward(outward_name)


@frappe.whitelist()
def reverse(outward_name, movement_at, source_evidence, source_event_id, reason):
    return outward_service.create_outward_reversal(
        outward_name=outward_name,
        movement_at=movement_at,
        source_evidence=source_evidence,
        source_event_id=source_event_id,
        reason=reason,
    )


@frappe.whitelist()
def create_rate_assertion(
    outward_name,
    outward_line_key,
    assertion_basis,
    raw_value,
    rate,
    evidence,
    effective_at,
    reason,
    supersedes=None,
    currency=None,
    rate_uom=None,
):
    return outward_service.create_rate_assertion(
        outward_name=outward_name,
        outward_line_key=outward_line_key,
        assertion_basis=assertion_basis,
        raw_value=raw_value,
        rate=rate,
        evidence=evidence,
        effective_at=effective_at,
        reason=reason,
        supersedes=supersedes,
        currency=currency,
        rate_uom=rate_uom,
    )


@frappe.whitelist()
def submit_assertion(assertion_name: str):
    return outward_service.submit_field_assertion(assertion_name)


@frappe.whitelist()
def review_assertion(assertion_name: str, decision: str):
    return outward_service.review_field_assertion(assertion_name, decision)
