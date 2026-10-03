"""Strict authenticated commercial API facade; implementation lives in services."""
import frappe
from fresko_universe.fresko_core.services import commercial_service as service


@frappe.whitelist(methods=["POST"])
def submit_sale(sale_name, expected_version=None):
    return service.submit_sale(sale_name=sale_name, expected_version=expected_version)


@frappe.whitelist(methods=["POST"])
def verify_sale(sale_name, expected_version=None):
    return service.verify_sale(sale_name=sale_name, expected_version=expected_version)


@frappe.whitelist(methods=["POST"])
def approve_sale(sale_name, expected_version=None):
    return service.approve_sale(sale_name=sale_name, expected_version=expected_version)


@frappe.whitelist(methods=["POST"])
def reject_sale(sale_name, reason, expected_version=None):
    return service.reject_sale(sale_name=sale_name, reason=reason, expected_version=expected_version)


@frappe.whitelist(methods=["POST"])
def supersede_sale(sale_name, *, source_event_id, reason, source_evidence, changes, expected_version=None):
    return service.supersede_sale(sale_name=sale_name, source_event_id=source_event_id, reason=reason, source_evidence=source_evidence, changes=changes, expected_version=expected_version)


@frappe.whitelist(methods=["POST"])
def create_sale(*, company, container, sale_at, source_evidence, source_event_id, lines, raw_party_alias=None, party_state='UNKNOWN', currency='INR', deal=None, raw_movement_at=None):
    return service.create_sale(company=company, container=container, sale_at=sale_at, source_evidence=source_evidence, source_event_id=source_event_id, lines=lines, raw_party_alias=raw_party_alias, party_state=party_state, currency=currency, deal=deal, raw_movement_at=raw_movement_at)


@frappe.whitelist(methods=["POST"])
def propose_rate(sale_name, line_key, rate, evidence, source_event_id, reason, expected_version=None):
    return service.propose_rate(sale_name=sale_name, line_key=line_key, rate=rate, evidence=evidence, source_event_id=source_event_id, reason=reason, expected_version=expected_version)


@frappe.whitelist(methods=["POST"])
def verify_rate(sale_name, expected_version=None):
    return service.verify_rate(sale_name=sale_name, expected_version=expected_version)


@frappe.whitelist(methods=["POST"])
def approve_rate(sale_name, expected_version=None):
    return service.approve_rate(sale_name=sale_name, expected_version=expected_version)


@frappe.whitelist(methods=["POST"])
def propose_alias_mapping(*, company, raw_alias, proposed_customer, evidence, source_event_id, normalization_scope='EXACT_COMPANY_V1', supersedes=None, reason=None):
    return service.propose_alias_mapping(company=company, raw_alias=raw_alias, proposed_customer=proposed_customer, evidence=evidence, source_event_id=source_event_id, normalization_scope=normalization_scope, supersedes=supersedes, reason=reason)


@frappe.whitelist(methods=["POST"])
def verify_alias_mapping(mapping_name, expected_version=None):
    return service.verify_alias_mapping(mapping_name=mapping_name, expected_version=expected_version)


@frappe.whitelist(methods=["POST"])
def approve_alias_mapping(mapping_name, expected_version=None):
    return service.approve_alias_mapping(mapping_name=mapping_name, expected_version=expected_version)


@frappe.whitelist(methods=["POST"])
def reject_alias_mapping(mapping_name, reason, expected_version=None):
    return service.reject_alias_mapping(mapping_name=mapping_name, reason=reason, expected_version=expected_version)


@frappe.whitelist(methods=["POST"])
def propose_sale_outward_allocation(*, sale_name, sale_line_key, outward, outward_line_key, qty, uom, evidence, source_event_id, supersedes=None, reason=None):
    return service.propose_sale_outward_allocation(sale_name=sale_name, sale_line_key=sale_line_key, outward=outward, outward_line_key=outward_line_key, qty=qty, uom=uom, evidence=evidence, source_event_id=source_event_id, supersedes=supersedes, reason=reason)


@frappe.whitelist(methods=["POST"])
def verify_sale_outward_allocation(allocation_name, expected_version=None):
    return service.verify_sale_outward_allocation(allocation_name=allocation_name, expected_version=expected_version)


@frappe.whitelist(methods=["POST"])
def approve_sale_outward_allocation(allocation_name, expected_version=None):
    return service.approve_sale_outward_allocation(allocation_name=allocation_name, expected_version=expected_version)


@frappe.whitelist(methods=["POST"])
def reject_sale_outward_allocation(allocation_name, reason, expected_version=None):
    return service.reject_sale_outward_allocation(allocation_name=allocation_name, reason=reason, expected_version=expected_version)


@frappe.whitelist(methods=["POST"])
def reverse_sale_outward_allocation(allocation_name, reason, evidence, expected_version=None):
    return service.reverse_sale_outward_allocation(allocation_name=allocation_name, reason=reason, evidence=evidence, expected_version=expected_version)


@frappe.whitelist()
def get_sale_as_of(sale_name, as_of):
    return service.get_sale_as_of(sale_name=sale_name, as_of=as_of)


@frappe.whitelist()
def get_container_reconciliation(container, as_of=None):
    return service.get_container_reconciliation(container=container, as_of=as_of)


@frappe.whitelist()
def get_outward_reconciliation(outward_name, as_of=None):
    return service.get_outward_reconciliation(outward_name=outward_name, as_of=as_of)


@frappe.whitelist(methods=["POST"])
def refresh_commercial_reconciliation(container):
    return service.refresh_commercial_reconciliation(container)
