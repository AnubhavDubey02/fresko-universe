"""Whitelist deal methods — apply_rate_rules, request_revision, accept_counter."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from fresko_universe.ats import available_to_sell
from fresko_universe.constants import COMMERCIAL_LOCK_STATUSES, MATERIAL_REVISION_FIELDS
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
    Only path from Countered → Approved (F-C1).
    """
    deal = frappe.get_doc("Fresko Deal", deal_name)
    if deal.status != "Countered":
        frappe.throw(_("accept_counter only valid from Countered (current: {0})").format(deal.status))

    user = frappe.session.user
    roles = set(frappe.get_roles())
    # F-M6 / D4: owner, assigned salesperson_user, or System Manager only.
    # When salesperson_user empty, non-originator Salesperson (and Approver) cannot accept.
    allowed = {deal.owner}
    if deal.salesperson_user:
        allowed.add(deal.salesperson_user)
    if user not in allowed and "System Manager" not in roles:
        frappe.throw(
            _("Only the deal originator/salesperson (or System Manager) may accept a counter (D4)")
        )

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
def cancel_deal(deal_name: str, cancel_reason: str):
    """Whitelist cancel — reason required. ATS keeps dispatched_qty after cancel."""
    if not cancel_reason:
        frappe.throw(_("cancel_reason is required"))
    deal = frappe.get_doc("Fresko Deal", deal_name)
    if deal.status == "Cancelled":
        return {
            "name": deal.name,
            "status": deal.status,
            "dispatched_qty": deal.dispatched_qty,
        }
    deal.cancel_reason = cancel_reason
    deal.set_status("Cancelled")
    deal.save(ignore_permissions=True)
    frappe.db.commit()
    return {
        "name": deal.name,
        "status": deal.status,
        "dispatched_qty": deal.dispatched_qty,
    }


@frappe.whitelist()
def record_dispatch(deal_name: str, dispatched_qty):
    """
    Server-only dispatched_qty update (Phase 1 stub).
    Physical ceiling: dispatched_qty may never exceed deal qty or lot inward residual.
    """
    deal = frappe.get_doc("Fresko Deal", deal_name)
    qty = flt(dispatched_qty)
    if qty < 0:
        frappe.throw(_("dispatched_qty cannot be negative"))
    if qty > flt(deal.qty):
        frappe.throw(
            _("dispatched_qty {0} cannot exceed deal qty {1} (physical ceiling)").format(
                qty, deal.qty
            )
        )
    # Lot physical: sum of dispatched on lot cannot exceed lot inward
    lot_inward = frappe.db.sql(
        """
        SELECT inward_qty FROM `tabFresko Container Lot`
        WHERE parent=%s AND parenttype='Fresko Container' AND lot_no=%s LIMIT 1
        """,
        (deal.container, deal.lot_no),
    )
    if lot_inward:
        inward = flt(lot_inward[0][0])
        others = frappe.db.sql(
            """
            SELECT COALESCE(SUM(dispatched_qty), 0) FROM `tabFresko Deal`
            WHERE container=%s AND lot_no=%s AND name!=%s
            """,
            (deal.container, deal.lot_no, deal.name),
        )
        other_disp = flt(others[0][0]) if others else 0.0
        if other_disp + qty > inward:
            frappe.throw(
                _(
                    "Physical dispatch ceiling: lot {0} inward {1}, other dispatched {2}, "
                    "requested {3}"
                ).format(deal.lot_no, inward, other_disp, qty)
            )

    deal.flags.allow_dispatch_write = True
    deal.dispatched_qty = qty
    if qty > 0 and qty < flt(deal.qty) and deal.status in (
        "Approved",
        "Auto Approved",
        "Outward Pending",
        "Dispatched",
    ):
        deal.set_status("Partially Dispatched")
    elif qty >= flt(deal.qty) and deal.status in (
        "Approved",
        "Auto Approved",
        "Outward Pending",
        "Partially Dispatched",
    ):
        deal.set_status("Dispatched")
    deal.save(ignore_permissions=True)
    frappe.db.commit()
    return {"name": deal.name, "dispatched_qty": deal.dispatched_qty, "status": deal.status}


@frappe.whitelist()
def request_revision(
    deal_name: str,
    fieldname: str,
    new_value,
    reason: str,
    supporting_evidence: str | None = None,
):
    """
    Controlled post-approval change.
    Material fields (rate/qty/lot/customer) require Approval + evidence before apply.
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

    if fieldname in MATERIAL_REVISION_FIELDS and not supporting_evidence:
        # Require evidence when commercially locked (post-approval)
        if deal.status in COMMERCIAL_LOCK_STATUSES:
            frappe.throw(
                _("Material revision of {0} requires supporting_evidence").format(fieldname)
            )

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

    return {
        "revision": rev.name,
        "status": rev.status,
        "message": (
            "Revision pending — link Fresko Approval then call apply_revision"
            if fieldname in MATERIAL_REVISION_FIELDS
            else "Revision pending approval — call apply_revision after Approval"
        ),
    }


@frappe.whitelist()
def apply_revision(revision_name: str, approval_name: str | None = None):
    """Apply a Pending Fresko Revision onto its parent Deal.

    Material fields require a Fresko Approval reference — role alone is insufficient.
    """
    rev = frappe.get_doc("Fresko Revision", revision_name)
    if rev.status != "Pending":
        frappe.throw(_("Revision {0} is not Pending").format(revision_name))
    if rev.parent_doctype != "Fresko Deal":
        frappe.throw(_("Only Fresko Deal revisions supported in Phase 1"))

    deal = frappe.get_doc("Fresko Deal", rev.parent_name)
    fieldname = rev.fieldname
    new_value = rev.new_value

    if fieldname in ("approved_rate", "qty"):
        new_value = flt(new_value)

    if fieldname in MATERIAL_REVISION_FIELDS:
        approval_ref = approval_name or rev.approval_reference
        if not approval_ref:
            frappe.throw(
                _(
                    "Material revision of {0} requires a Fresko Approval reference "
                    "(Approver role alone cannot apply)"
                ).format(fieldname)
            )
        if not frappe.db.exists("Fresko Approval", approval_ref):
            frappe.throw(_("Fresko Approval {0} not found").format(approval_ref))
        if not rev.supporting_evidence:
            if deal.status in COMMERCIAL_LOCK_STATUSES:
                frappe.throw(
                    _("Material revision of {0} requires supporting_evidence").format(fieldname)
                )
        rev.approval_reference = approval_ref

        if fieldname in ("qty", "lot_no", "container_lot"):
            probe_lot = new_value if fieldname == "lot_no" else deal.lot_no
            probe_qty = new_value if fieldname == "qty" else deal.qty
            ats = available_to_sell(
                deal.container, probe_lot, exclude_deal=deal.name, for_update=True
            )
            if flt(probe_qty) > ats:
                frappe.throw(
                    _("Revision blocked: qty {0} > ATS {1}").format(probe_qty, ats)
                )

    deal.flags.allow_commercial_revision = True
    if fieldname == "approved_rate":
        deal.flags.allow_approval_write = True
    deal.set(fieldname, new_value)
    deal.save(ignore_permissions=True)

    if approval_name:
        rev.approval_reference = approval_name
    rev.status = "Applied"
    rev.flags.allow_revision_apply = True
    rev.save(ignore_permissions=True)

    if fieldname == "customer" and new_value:
        _resolve_buyer_exceptions(deal.name)

    frappe.db.commit()
    return {
        "deal": deal.name,
        "revision": rev.name,
        "fieldname": fieldname,
        "status": "Applied",
        "approval_reference": rev.approval_reference,
        "supporting_evidence": rev.supporting_evidence,
    }


@frappe.whitelist()
def set_dispatched_qty(deal_name: str, dispatched_qty):
    """Compat shim — prefer record_dispatch; same allow_dispatch_write flag (F-H6)."""
    return record_dispatch(deal_name, dispatched_qty)


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
