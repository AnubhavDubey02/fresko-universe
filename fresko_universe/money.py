"""Strict authenticated money and reconciliation API facade; implementation lives in services."""
from __future__ import annotations
from typing import Any
import frappe
from fresko_universe.fresko_core.services import money_service as service

def _reject_unexpected(fields):
    # Frappe RPC adds cmd when dispatching form_dict; it is transport metadata.
    fields.pop("cmd", None)
    if fields:
        frappe.throw('Unexpected money API fields; server decision metadata cannot be supplied', frappe.ValidationError)

@frappe.whitelist(methods=['POST'])
def create_collection(*, company: str, source_namespace: str, source_event_id: str, direction: str='INFLOW', amount: str | None=None, currency: str='INR', amount_state: str | None=None, payment_channel: str='BANK', bank_state: str='NONE', source_classification: str='NONE', bank_account: str | None=None, bank_reference: str | None=None, rail: str | None=None, cash_custodian: str | None=None, effective_at: str | None=None, payer_raw: str | None=None, customer: str | None=None, source_evidence: str | None=None, supersedes: str | None=None, reason: str | None=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.create_collection(company=company, source_namespace=source_namespace, source_event_id=source_event_id, direction=direction, amount=amount, currency=currency, amount_state=amount_state, payment_channel=payment_channel, bank_state=bank_state, source_classification=source_classification, bank_account=bank_account, bank_reference=bank_reference, rail=rail, cash_custodian=cash_custodian, effective_at=effective_at, payer_raw=payer_raw, customer=customer, source_evidence=source_evidence, supersedes=supersedes, reason=reason)

@frappe.whitelist(methods=['POST'])
def submit_collection(collection_name: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.submit_collection(collection_name=collection_name, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def verify_collection(collection_name: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.verify_collection(collection_name=collection_name, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def approve_collection(collection_name: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.approve_collection(collection_name=collection_name, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def reject_collection(collection_name: str, reason: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.reject_collection(collection_name=collection_name, reason=reason, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def reverse_collection(collection_name: str, reason: str, evidence: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.reverse_collection(collection_name=collection_name, reason=reason, evidence=evidence, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def supersede_collection(collection_name: str, *, source_event_id: str, reason: str, source_evidence: str, changes: dict[str, Any] | str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.supersede_collection(collection_name=collection_name, source_event_id=source_event_id, reason=reason, source_evidence=source_evidence, changes=changes, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def propose_payment_allocation(*, collection: str, allocation_type: str, amount: str, currency: str, evidence: str, source_event_id: str, sale: str | None=None, container: str | None=None, customer: str | None=None, supersedes: str | None=None, reason: str | None=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.propose_payment_allocation(collection=collection, allocation_type=allocation_type, amount=amount, currency=currency, evidence=evidence, source_event_id=source_event_id, sale=sale, container=container, customer=customer, supersedes=supersedes, reason=reason)

@frappe.whitelist(methods=['POST'])
def submit_payment_allocation(allocation_name: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.submit_payment_allocation(allocation_name=allocation_name, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def verify_payment_allocation(allocation_name: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.verify_payment_allocation(allocation_name=allocation_name, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def approve_payment_allocation(allocation_name: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.approve_payment_allocation(allocation_name=allocation_name, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def reject_payment_allocation(allocation_name: str, reason: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.reject_payment_allocation(allocation_name=allocation_name, reason=reason, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def reverse_payment_allocation(allocation_name: str, reason: str, evidence: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.reverse_payment_allocation(allocation_name=allocation_name, reason=reason, evidence=evidence, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def propose_adjustment(*, company: str, customer: str, adjustment_type: str, amount: str, currency: str='INR', evidence: str, source_event_id: str, agreement_reference: str | None=None, supersedes: str | None=None, reason: str | None=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.propose_adjustment(company=company, customer=customer, adjustment_type=adjustment_type, amount=amount, currency=currency, evidence=evidence, source_event_id=source_event_id, agreement_reference=agreement_reference, supersedes=supersedes, reason=reason)

@frappe.whitelist(methods=['POST'])
def submit_adjustment(adjustment_name: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.submit_adjustment(adjustment_name=adjustment_name, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def verify_adjustment(adjustment_name: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.verify_adjustment(adjustment_name=adjustment_name, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def approve_adjustment(adjustment_name: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.approve_adjustment(adjustment_name=adjustment_name, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def reject_adjustment(adjustment_name: str, reason: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.reject_adjustment(adjustment_name=adjustment_name, reason=reason, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def reverse_adjustment(adjustment_name: str, reason: str, evidence: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.reverse_adjustment(adjustment_name=adjustment_name, reason=reason, evidence=evidence, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def propose_adjustment_application(*, receivable_adjustment: str, sale: str, amount: str, currency: str, evidence: str, source_event_id: str, supersedes: str | None=None, reason: str | None=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.propose_adjustment_application(receivable_adjustment=receivable_adjustment, sale=sale, amount=amount, currency=currency, evidence=evidence, source_event_id=source_event_id, supersedes=supersedes, reason=reason)

@frappe.whitelist(methods=['POST'])
def submit_adjustment_application(application_name: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.submit_adjustment_application(application_name=application_name, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def verify_adjustment_application(application_name: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.verify_adjustment_application(application_name=application_name, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def approve_adjustment_application(application_name: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.approve_adjustment_application(application_name=application_name, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def reject_adjustment_application(application_name: str, reason: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.reject_adjustment_application(application_name=application_name, reason=reason, expected_version=expected_version)

@frappe.whitelist(methods=['POST'])
def reverse_adjustment_application(application_name: str, reason: str, evidence: str, expected_version: Any=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.reverse_adjustment_application(application_name=application_name, reason=reason, evidence=evidence, expected_version=expected_version)

@frappe.whitelist()
def get_collection_position(name: str, as_of: str | None=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.get_collection_position(name=name, as_of=as_of)

@frappe.whitelist()
def get_sale_receivable(sale: str, as_of: str | None=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.get_sale_receivable(sale=sale, as_of=as_of)

@frappe.whitelist()
def get_container_receivable(container: str, as_of: str | None=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.get_container_receivable(container=container, as_of=as_of)

@frappe.whitelist()
def get_customer_receivable(customer: str, company: str, as_of: str | None=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.get_customer_receivable(customer=customer, company=company, as_of=as_of)

@frappe.whitelist()
def get_unallocated_collections(company: str, as_of: str | None=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.get_unallocated_collections(company=company, as_of=as_of)

@frappe.whitelist()
def get_bank_pending_collections(company: str, as_of: str | None=None, **unexpected):
    _reject_unexpected(unexpected)
    return service.get_bank_pending_collections(company=company, as_of=as_of)

@frappe.whitelist(methods=['POST'])
def refresh_money_reconciliation(company: str, **unexpected):
    _reject_unexpected(unexpected)
    return service.refresh_money_reconciliation(company=company)

@frappe.whitelist(methods=['GET', 'POST'])
def get_open_money_exceptions(company: str, **unexpected):
    _reject_unexpected(unexpected)
    return service.get_open_money_exceptions(company)
