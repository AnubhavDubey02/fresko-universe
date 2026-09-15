"""Whitelist deal methods — apply_rate_rules, request_revision, accept_counter."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from fresko_universe.ats import available_to_sell
from fresko_universe.rate_rules import rate_in_band, resolve_rate_band


@frappe.whitelist()
def apply_rate_rules(deal_name: str):
    """
    Snapshot floor/ceiling; in-band → Auto Approved; else Approval Required.
    Re-reads ATS under lock before Auto Approve (D3).
    """
    deal = frappe.get_doc("Fresko Deal", deal_name)
    if deal.status != "Proposed":
        frappe.throw(_("apply_rate_rules only valid from Proposed (current: {0})").format(deal.status))

    container = frappe.get_doc("Fresko Container", deal.container)
    floor, ceiling = resolve_rate_band(container, deal.lot_no, deal.count_size)
    deal.rate_floor = floor
    deal.rate_ceiling = ceiling

    in_band = rate_in_band(deal.proposed_rate, floor, ceiling)

    if in_band:
        # ATS check under lock before auto-approve
        ats = available_to_sell(deal.container, deal.lot_no, exclude_deal=deal.name, for_update=True)
        if flt(deal.qty) > ats:
            deal.approval_required = 1
            deal.set_status("Approval Required")
            _open_exception(
                deal,
                "STOCK_SHORTFALL",
                f"Auto-approve blocked: qty {deal.qty} > ATS {ats}",
                severity="Material",
            )
        else:
            deal.flags.allow_approval_write = True
            deal.approved_rate = deal.proposed_rate
            deal.approval_required = 0
            deal.set_status("Auto Approved")
            _maybe_open_buyer_unresolved(deal)
    else:
        deal.approval_required = 1
        deal.set_status("Approval Required")

    deal.save(ignore_permissions=True)
    frappe.db.commit()
    return {
        "name": deal.name,
        "status": deal.status,
        "rate_floor": deal.rate_floor,
        "rate_ceiling": deal.rate_ceiling,
        "approved_rate": deal.approved_rate,
        "approval_required": deal.approval_required,
    }


@frappe.whitelist()
def accept_counter(deal_name: str):
    """
    D4: salesperson/originator explicitly accepts COUNTER → Approved.
    """
    deal = frappe.get_doc("Fresko Deal", deal_name)
    if deal.status != "Countered":
        frappe.throw(_("accept_counter only valid from Countered (current: {0})").format(deal.status))

    user = frappe.session.user
    is_originator = user == deal.owner or user == (deal.salesperson_user or "")
    roles = set(frappe.get_roles())
    if not is_originator and "System Manager" not in roles and "Fresko Approver" not in roles:
        # Approver may also accept on behalf in ops; salesperson/originator preferred
        if "Fresko Salesperson" not in roles:
            frappe.throw(_("Only deal originator/salesperson (or Approver/SM) may accept a counter"))
        if deal.salesperson_user and user != deal.salesperson_user and user != deal.owner:
            frappe.throw(_("Only the deal originator/salesperson may accept this counter (D4)"))

    if deal.approved_rate is None:
        frappe.throw(_("Countered deal has no approved_rate (decision_rate) to accept"))

    # ATS re-check under lock before becoming Approved
    ats = available_to_sell(deal.container, deal.lot_no, exclude_deal=deal.name, for_update=True)
    if flt(deal.qty) > ats:
        frappe.throw(_("Cannot accept counter: qty {0} > ATS {1}").format(deal.qty, ats))

    deal.set_status("Approved")
    deal.save(ignore_permissions=True)
    frappe.db.commit()
    return {"name": deal.name, "status": deal.status, "approved_rate": deal.approved_rate}


@frappe.whitelist()
def request_revision(
    deal_name: str,
    fieldname: str,
    new_value,
    reason: str,
    supporting_evidence: str | None = None,
):
    """
    Controlled post-approval change. Rate/qty/lot revisions require subsequent Approval
    before apply; non-rate customer mapping may apply with Approver role.
    """
    if not reason:
        frappe.throw(_("Revision reason is mandatory"))

    deal = frappe.get_doc("Fresko Deal", deal_name)
    allowed_fields = {
        "approved_rate",
        "qty",
        "lot_no",
        "container_lot",
        "customer",
        "item",
        "count_size",
    }
    if fieldname not in allowed_fields:
        frappe.throw(_("Field {0} is not revision-eligible").format(fieldname))

    old_value = deal.get(fieldname)
    rev = frappe.get_doc(
        {
            "doctype": "Fresko Revision",
            "parent_doctype": "Fresko Deal",
            "parent_name": deal.name,
            "fieldname": fieldname,
            "old_value": str(old_value) if old_value is not None else "",
            "new_value": str(new_value) if new_value is not None else "",
            "reason": reason,
            "supporting_evidence": supporting_evidence,
            "status": "Pending",
        }
    )
    rev.insert(ignore_permissions=True)

    # Customer mapping alone: Approver/SM may apply immediately (helps D6 resolve)
    if fieldname == "customer":
        roles = set(frappe.get_roles())
        if "Fresko Approver" in roles or "System Manager" in roles:
            return apply_revision(rev.name)

    return {
        "revision": rev.name,
        "status": rev.status,
        "message": "Revision pending approval — call approvals.decide or apply_revision after Approval",
    }


@frappe.whitelist()
def apply_revision(revision_name: str, approval_name: str | None = None):
    """Apply a Pending Fresko Revision onto its parent Deal (requires allow flags)."""
    rev = frappe.get_doc("Fresko Revision", revision_name)
    if rev.status != "Pending":
        frappe.throw(_("Revision {0} is not Pending").format(revision_name))
    if rev.parent_doctype != "Fresko Deal":
        frappe.throw(_("Only Fresko Deal revisions supported in Phase 1"))

    deal = frappe.get_doc("Fresko Deal", rev.parent_name)
    fieldname = rev.fieldname
    new_value = rev.new_value

    # Coerce numeric fields
    if fieldname in ("approved_rate", "qty"):
        new_value = flt(new_value)

    if fieldname in ("approved_rate", "qty", "lot_no", "container_lot"):
        # Requires Approval reference for commercial fields
        if not approval_name and not rev.approval_reference:
            roles = set(frappe.get_roles())
            if "Fresko Approver" not in roles and "System Manager" not in roles:
                frappe.throw(_("Commercial revision requires Approval or Approver role"))
        # ATS if qty/lot change
        if fieldname in ("qty", "lot_no", "container_lot"):
            probe_lot = new_value if fieldname == "lot_no" else deal.lot_no
            probe_qty = new_value if fieldname == "qty" else deal.qty
            ats = available_to_sell(deal.container, probe_lot, exclude_deal=deal.name, for_update=True)
            if flt(probe_qty) > ats:
                frappe.throw(_("Revision blocked: qty {0} > ATS {1}").format(probe_qty, ats))

    deal.flags.allow_commercial_revision = True
    if fieldname == "approved_rate":
        deal.flags.allow_approval_write = True
    deal.set(fieldname, new_value)

    # If lot_no changes, re-validate membership on save
    deal.save(ignore_permissions=True)

    if approval_name:
        rev.approval_reference = approval_name
    rev.status = "Applied"
    rev.save(ignore_permissions=True)

    # Resolve BUYER_UNRESOLVED when customer set
    if fieldname == "customer" and new_value:
        _resolve_buyer_exceptions(deal.name)

    frappe.db.commit()
    return {"deal": deal.name, "revision": rev.name, "fieldname": fieldname, "status": "Applied"}


def _maybe_open_buyer_unresolved(deal):
    if deal.customer:
        return
    existing = frappe.get_all(
        "Fresko Exception",
        filters={
            "deal": deal.name,
            "exception_type": "BUYER_UNRESOLVED",
            "status": ("in", ["Open", "In Progress"]),
        },
        limit=1,
    )
    if existing:
        return
    _open_exception(
        deal,
        "BUYER_UNRESOLVED",
        f"Deal approved with unresolved buyer_alias={deal.buyer_alias!r}; "
        "block RECONCILED until Customer mapped (D6).",
        severity="Material",
    )


def _open_exception(deal, exception_type: str, description: str, severity: str = "Medium"):
    ex = frappe.get_doc(
        {
            "doctype": "Fresko Exception",
            "exception_type": exception_type,
            "severity": severity,
            "status": "Open",
            "deal": deal.name,
            "container": deal.container,
            "description": description,
        }
    )
    ex.insert(ignore_permissions=True)
    return ex


def _resolve_buyer_exceptions(deal_name: str):
    for row in frappe.get_all(
        "Fresko Exception",
        filters={
            "deal": deal_name,
            "exception_type": "BUYER_UNRESOLVED",
            "status": ("in", ["Open", "In Progress"]),
        },
    ):
        doc = frappe.get_doc("Fresko Exception", row.name)
        doc.status = "Resolved"
        doc.resolution_notes = "Customer mapped via revision"
        doc.save(ignore_permissions=True)
