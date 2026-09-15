"""Whitelist deal methods — apply_rate_rules, request_revision, accept_counter."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from fresko_universe.ats import available_to_sell
from fresko_universe.constants import COMMERCIAL_LOCK_STATUSES, MATERIAL_REVISION_FIELDS
from fresko_universe.permissions import (
    assert_approval_bound_for_revision,
    assert_approval_not_consumed,
    assert_approval_not_stale,
    assert_can_apply_rate_rules,
    assert_can_apply_revision,
    assert_can_cancel_deal,
    assert_can_record_dispatch,
    assert_can_request_revision,
)
from fresko_universe.rate_rules import policy_resolved, rate_in_band, resolve_rate_band


@frappe.whitelist()
def apply_rate_rules(deal_name: str):
    """
    Snapshot floor/ceiling; fail-closed if policy missing (Gate 1).
    Resolved + in-band → Auto Approved (ATS re-read under lock, D3).
    Resolved + out-of-band → Approval Required (RATE_FLOOR_BREACH path).
    """
    deal = frappe.get_doc("Fresko Deal", deal_name)
    assert_can_apply_rate_rules(deal)
    if deal.status != "Proposed":
        frappe.throw(_("apply_rate_rules only valid from Proposed (current: {0})").format(deal.status))

    container = frappe.get_doc("Fresko Container", deal.container)
    floor, ceiling = resolve_rate_band(container, deal.lot_no, deal.count_size)
    # Snapshot even when null (Gate 1: empty policy must be visible on Deal)
    deal.rate_floor = floor
    deal.rate_ceiling = ceiling

    if not policy_resolved(floor, ceiling):
        # Fail-closed: empty band must never auto-approve (F-M7 / Gate 1)
        deal.approval_required = 1
        deal.set_status("Approval Required")
        # Do not assign approved_rate on the Document: Currency None→0.0 plus
        # has_value_changed trips commercial lock without allow_approval_write.
        # Preserve proposed_rate; force SQL NULL after save (Gate 1; cols nullable
        # via install.after_migrate).
        _open_exception(
            deal,
            "RATE_POLICY_MISSING",
            f"No applicable rate policy (floor/ceiling unresolved) for lot={deal.lot_no!r} "
            f"count_size={deal.count_size!r}; proposed_rate={deal.proposed_rate} preserved",
            severity="Material",
        )
    elif rate_in_band(deal.proposed_rate, floor, ceiling):
        # ATS check under lock before auto-approve
        ats = available_to_sell(deal.container, deal.lot_no, exclude_deal=deal.name, for_update=True)
        if flt(deal.qty) > ats:
            deal.approval_required = 1
            deal.set_status("Approval Required")
            # Keep approved_rate untouched on Document; SQL NULL via post-save set_value.
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
        # Policy resolved but out of band — Approval Required (RATE_FLOOR_BREACH path as today)
        deal.approval_required = 1
        # Do not assign approved_rate=None here (commercial lock / Currency coerce).
        deal.set_status("Approval Required")

    # FSEC-001 audit: ignore_permissions AFTER assert_can_apply_rate_rules.
    # Rationale: status / approved_rate writes use Document flags that Role Permission
    # Manager cannot express; ACL above is the authorization SoR.
    deal.save(ignore_permissions=True)
    # Currency fields coerce None→0.0 on Document.save. Force SQL NULL where
    # commercial semantics require "unset" (Gate 1 approved_rate; empty snapshots).
    null_fields = {}
    if deal.status == "Approval Required":
        null_fields["approved_rate"] = None
    if not policy_resolved(floor, ceiling):
        null_fields["rate_floor"] = None
        null_fields["rate_ceiling"] = None
        null_fields["approved_rate"] = None
    if null_fields:
        frappe.db.set_value(
            "Fresko Deal",
            deal.name,
            null_fields,
            update_modified=False,
        )
        for k, v in null_fields.items():
            setattr(deal, k, v)
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
    ACL: deal.owner or deal.salesperson_user only — never System Manager / Approver on behalf.

    RC: load COUNTER Approval.decision_rate → copy to Deal.approved_rate (Countered leaves
    approved_rate NULL so amount stays on proposed_rate until accept).
    """
    deal = frappe.get_doc("Fresko Deal", deal_name)
    if deal.status != "Countered":
        frappe.throw(_("accept_counter only valid from Countered (current: {0})").format(deal.status))

    user = frappe.session.user
    # D4 tighter: ONLY owner or assigned salesperson_user. If salesperson empty → owner only.
    allowed = {deal.owner}
    if deal.salesperson_user:
        allowed.add(deal.salesperson_user)
    if user not in allowed:
        frappe.throw(
            _("Only the deal owner or assigned salesperson_user may accept a counter (D4)")
        )

    counter_rate = _load_counter_decision_rate(deal)
    if counter_rate is None:
        frappe.throw(_("Countered deal has no COUNTER Approval.decision_rate to accept"))

    # ATS re-check under lock before becoming Approved
    ats = available_to_sell(deal.container, deal.lot_no, exclude_deal=deal.name, for_update=True)
    if flt(deal.qty) > ats:
        frappe.throw(_("Cannot accept counter: qty {0} > ATS {1}").format(deal.qty, ats))

    deal.flags.allow_approval_write = True
    deal.approved_rate = counter_rate
    deal.set_status("Approved")
    _maybe_open_buyer_unresolved(deal)
    # FSEC-001 audit: ignore_permissions AFTER D4 ownership ACL above.
    deal.save(ignore_permissions=True)
    frappe.db.commit()
    return {"name": deal.name, "status": deal.status, "approved_rate": deal.approved_rate}


def _load_counter_decision_rate(deal):
    """Latest/open COUNTER Approval for this deal; prefer deal.approval if it is COUNTER."""
    if deal.approval and frappe.db.exists("Fresko Approval", deal.approval):
        row = frappe.db.get_value(
            "Fresko Approval",
            deal.approval,
            ["decision", "decision_rate"],
            as_dict=True,
        )
        if row and (row.decision or "").upper() == "COUNTER" and row.decision_rate is not None:
            return flt(row.decision_rate)
    rows = frappe.get_all(
        "Fresko Approval",
        filters={"deal": deal.name, "decision": "COUNTER"},
        fields=["name", "decision_rate"],
        order_by="creation desc",
        limit=1,
    )
    if not rows or rows[0].decision_rate is None:
        return None
    return flt(rows[0].decision_rate)


@frappe.whitelist()
def cancel_deal(deal_name: str, cancel_reason: str):
    """Whitelist cancel — reason required. ATS keeps dispatched_qty after cancel."""
    if not cancel_reason:
        frappe.throw(_("cancel_reason is required"))
    deal = frappe.get_doc("Fresko Deal", deal_name)
    assert_can_cancel_deal(deal)
    if deal.status == "Cancelled":
        return {
            "name": deal.name,
            "status": deal.status,
            "dispatched_qty": deal.dispatched_qty,
        }
    deal.cancel_reason = cancel_reason
    deal.set_status("Cancelled")
    # FSEC-001 audit: ignore_permissions AFTER assert_can_cancel_deal.
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
    assert_can_record_dispatch(deal)
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
    # FSEC-001 audit: ignore_permissions AFTER assert_can_record_dispatch.
    # Rationale: dispatched_qty is server-only (Desk locked); whitelist is the sole writer.
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
    assert_can_request_revision(deal)
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
    # FSEC-001 audit: ignore_permissions AFTER assert_can_request_revision.
    rev.insert(ignore_permissions=True)

    return {
        "revision": rev.name,
        "status": rev.status,
        "message": (
            "Revision pending — call approvals.create_revision_approval then apply_revision"
            if fieldname in MATERIAL_REVISION_FIELDS
            else "Revision pending approval — call apply_revision after Approval"
        ),
    }


@frappe.whitelist()
def apply_revision(revision_name: str, approval_name: str | None = None):
    """Apply a Pending Fresko Revision onto its parent Deal.

    Material fields require a Fresko Approval bound to this deal AND this revision
    (approvals.create_revision_approval) with APPROVE / OVERSELL_OVERRIDE.
    Deal-only Approvals are rejected. Approval is marked consumed (replay fails).
    Caller must be Fresko Approver or System Manager (FSEC-002).
    """
    assert_can_apply_revision()
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

    approval = None
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
        approval = frappe.get_doc("Fresko Approval", approval_ref)
        assert_approval_bound_for_revision(approval, deal, revision=rev)
        assert_approval_not_consumed(approval)
        assert_approval_not_stale(approval, rev.name)
        _assert_revision_old_value_matches_deal(deal, rev)
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
    # FSEC-001/002 audit: ignore_permissions AFTER role + Approval↔Deal↔Revision bind checks.
    deal.save(ignore_permissions=True)

    if approval_name:
        rev.approval_reference = approval_name
    rev.status = "Applied"
    rev.flags.allow_revision_apply = True
    rev.save(ignore_permissions=True)

    if approval is not None:
        _mark_approval_consumed(approval)

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


def _assert_revision_old_value_matches_deal(deal, rev) -> None:
    """Stale guard: Deal field must still equal revision.old_value at apply time."""
    current = deal.get(rev.fieldname)
    if rev.fieldname in ("approved_rate", "qty"):
        if flt(current) != flt(rev.old_value or 0):
            frappe.throw(
                _(
                    "Revision {0} is stale: deal.{1} is {2}, revision.old_value is {3}"
                ).format(rev.name, rev.fieldname, current, rev.old_value)
            )
        return
    cur_s = "" if current is None else str(current)
    old_s = "" if rev.old_value is None else str(rev.old_value)
    if cur_s != old_s:
        frappe.throw(
            _(
                "Revision {0} is stale: deal.{1} is {2!r}, revision.old_value is {3!r}"
            ).format(rev.name, rev.fieldname, cur_s, old_s)
        )


def _mark_approval_consumed(approval) -> None:
    # Append-only DocType: flag via SQL after apply succeeds (Document.validate blocks edits).
    frappe.db.set_value(
        "Fresko Approval",
        approval.name,
        "consumed",
        1,
        update_modified=False,
    )
    approval.consumed = 1


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
    # System side-effect of an already-authorized commercial path (FSEC-001).
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
