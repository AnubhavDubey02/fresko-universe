"""Whitelist deal methods — apply_rate_rules, request_revision, accept_counter."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from fresko_universe.ats import available_to_sell, lock_container_for_update
from fresko_universe.constants import (
    COMMERCIAL_LOCK_STATUSES,
    MATERIAL_REVISION_FIELDS,
    REVISION_ELIGIBLE_FIELDS,
)
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
    # Probe only to identify the stable parent lock target. All authorization,
    # state validation and commercial reads are repeated from locking reads.
    probe = frappe.get_doc("Fresko Deal", deal_name)
    assert_can_apply_rate_rules(probe)
    locked_container = probe.container
    lock_container_for_update(locked_container)
    deal = frappe.get_doc("Fresko Deal", deal_name, for_update=True)
    if deal.container != locked_container:
        frappe.throw(_("Deal container changed while acquiring rate-policy lock"))
    assert_can_apply_rate_rules(deal)
    if deal.status != "Proposed":
        frappe.throw(_("apply_rate_rules only valid from Proposed (current: {0})").format(deal.status))

    container = frappe.get_doc("Fresko Container", locked_container, for_update=True)
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
        # Policy resolved but out of band — Approval Required + material exception.
        deal.approval_required = 1
        # Do not assign approved_rate=None here (commercial lock / Currency coerce).
        deal.set_status("Approval Required")
        _ensure_open_exception(
            deal,
            "RATE_FLOOR_BREACH",
            f"Proposed rate {deal.proposed_rate} is outside resolved band "
            f"{floor}..{ceiling} for lot={deal.lot_no!r} "
            f"count_size={deal.count_size!r}",
            severity="Material",
        )

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
    # Probe only for the stable parent lock target. Status, ownership and the
    # linked Approval are mutable decision state and must be consumed only
    # after the container-first locks have been acquired.
    probe = frappe.get_doc("Fresko Deal", deal_name)
    locked_container = probe.container
    lock_container_for_update(locked_container)
    deal = frappe.get_doc("Fresko Deal", deal_name, for_update=True)
    if deal.container != locked_container:
        frappe.throw(_("Deal container changed while acquiring counter-acceptance lock"))
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

    counter_approval = _load_counter_approval(deal)
    counter_rate = (
        flt(counter_approval.decision_rate)
        if counter_approval is not None
        and getattr(counter_approval, "decision_rate", None) is not None
        else None
    )
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
    _transition_rate_floor_breach(
        deal,
        counter_approval,
        "Resolved" if _rate_is_within_stored_band(deal, counter_rate) else "Waived",
        counter_rate,
        getattr(counter_approval, "reason", None) or "Counter accepted",
    )
    # FSEC-001 audit: ignore_permissions AFTER D4 ownership ACL above.
    deal.save(ignore_permissions=True)
    frappe.db.commit()
    return {"name": deal.name, "status": deal.status, "approved_rate": deal.approved_rate}


def _load_counter_approval(deal):
    """Latest COUNTER Approval for this deal; prefer the Deal's explicit link."""
    if deal.approval and frappe.db.exists("Fresko Approval", deal.approval):
        row = frappe.db.get_value(
            "Fresko Approval",
            deal.approval,
            ["name", "decision", "decision_rate", "reason", "exception"],
            as_dict=True,
        )
        if row and (row.decision or "").upper() == "COUNTER" and row.decision_rate is not None:
            return row
    rows = frappe.get_all(
        "Fresko Approval",
        filters={"deal": deal.name, "decision": "COUNTER"},
        fields=["name", "decision", "decision_rate", "reason", "exception"],
        order_by="creation desc",
        limit=1,
    )
    if not rows or rows[0].decision_rate is None:
        return None
    return rows[0]


def _load_counter_decision_rate(deal):
    """Compatibility helper returning the latest COUNTER decision rate."""
    approval = _load_counter_approval(deal)
    if approval is None or getattr(approval, "decision_rate", None) is None:
        return None
    return flt(approval.decision_rate)


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
def release_for_outward(deal_name: str):
    """Legacy-only API compatibility alias for the Phase 1 dispatch lifecycle.

    This does not record physical outward evidence and does not grant Phase 2A
    outward authorization. New outward workflows must not infer either fact.
    """
    return advance_to_legacy_outward_pending(deal_name)


def advance_to_legacy_outward_pending(deal_name: str):
    """Canonical legacy transition into ``Outward Pending``.

    Uses the operations role gate and container-first lock hierarchy. Replays
    are idempotent, but remain legacy lifecycle transitions only.
    """
    deal = frappe.get_doc("Fresko Deal", deal_name)
    assert_can_record_dispatch(deal)
    locked_container = deal.container
    lock_container_for_update(locked_container)
    deal = frappe.get_doc("Fresko Deal", deal_name, for_update=True)
    if deal.container != locked_container:
        frappe.throw(_("Legacy outward transition: deal container changed while acquiring lock"))

    if deal.status == "Outward Pending":
        return _legacy_dispatch_result(deal)
    if deal.status not in ("Approved", "Auto Approved"):
        frappe.throw(
            _("Legacy outward transition requires Approved or Auto Approved status (current: {0})").format(
                deal.status
            )
        )
    if flt(deal.dispatched_qty or 0) != 0:
        frappe.throw(_("Legacy outward transition cannot run after dispatched_qty was recorded"))

    deal.set_status("Outward Pending")
    deal.save(ignore_permissions=True)
    frappe.db.commit()
    return _legacy_dispatch_result(deal)


@frappe.whitelist()
def record_dispatch(deal_name: str, dispatched_qty):
    """Legacy-only monotonic cumulative dispatch transition.

    This compatibility API records neither physical outward evidence nor Phase
    2A outward authorization. It only advances the pre-Outward Deal lifecycle.
    Physical ceiling: dispatched_qty may never exceed deal qty or lot inward residual.
    """
    deal = frappe.get_doc("Fresko Deal", deal_name)
    assert_can_record_dispatch(deal)
    # D10: every physical dispatch for this container uses the same row lock.
    # The first Deal read only identifies that stable lock target. After a wait,
    # use locking reads throughout: under MariaDB REPEATABLE READ, a normal
    # reload/SELECT could otherwise keep the pre-lock transaction snapshot.
    locked_container = deal.container
    lock_container_for_update(locked_container)
    deal = frappe.get_doc("Fresko Deal", deal_name, for_update=True)
    if deal.container != locked_container:
        frappe.throw(_("Legacy dispatch transition: deal container changed while acquiring lock"))
    qty = flt(dispatched_qty)
    current_qty = flt(deal.dispatched_qty or 0)
    if qty < 0:
        frappe.throw(_("dispatched_qty cannot be negative"))
    if deal.status == "Dispatched":
        if qty == current_qty:
            return _legacy_dispatch_result(deal, current_qty)
        frappe.throw(_("Legacy Dispatched deal only accepts an exact idempotent quantity replay"))
    if deal.status not in ("Outward Pending", "Partially Dispatched"):
        frappe.throw(
            _("Legacy record_dispatch requires Outward Pending or Partially Dispatched status (current: {0})").format(
                deal.status
            )
        )
    if qty < current_qty:
        frappe.throw(
            _("dispatched_qty cannot decrease from {0} to {1}").format(current_qty, qty)
        )
    if qty == current_qty:
        return _legacy_dispatch_result(deal, current_qty)
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
        WHERE parent=%s AND parenttype='Fresko Container' AND lot_no=%s
        LIMIT 1 FOR UPDATE
        """,
        (deal.container, deal.lot_no),
    )
    if lot_inward:
        inward = flt(lot_inward[0][0])
        others = frappe.db.sql(
            """
            SELECT dispatched_qty FROM `tabFresko Deal`
            WHERE container=%s AND lot_no=%s AND name!=%s
            FOR UPDATE
            """,
            (deal.container, deal.lot_no, deal.name),
        )
        other_disp = sum(flt(row[0]) for row in others)
        if other_disp + qty > inward:
            frappe.throw(
                _(
                    "Physical dispatch ceiling: lot {0} inward {1}, other dispatched {2}, "
                    "requested {3}"
                ).format(deal.lot_no, inward, other_disp, qty)
            )

    deal.flags.allow_dispatch_write = True
    deal.dispatched_qty = qty
    if qty > 0 and qty < flt(deal.qty):
        deal.set_status("Partially Dispatched")
    elif qty >= flt(deal.qty):
        deal.set_status("Dispatched")
    # FSEC-001 audit: ignore_permissions AFTER assert_can_record_dispatch.
    # Rationale: dispatched_qty is server-only (Desk locked); whitelist is the sole writer.
    deal.save(ignore_permissions=True)
    frappe.db.commit()
    return _legacy_dispatch_result(deal)


def _legacy_dispatch_result(deal, dispatched_qty=None):
    """Make the limitations of every successful legacy response explicit."""
    return {
        "name": deal.name,
        "status": deal.status,
        "dispatched_qty": flt(
            deal.dispatched_qty if dispatched_qty is None else dispatched_qty
        ),
        "legacy_dispatch_transition": True,
        "physical_outward_recorded": False,
        "phase2a_outward_authorized": False,
    }


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
    if fieldname not in REVISION_ELIGIBLE_FIELDS:
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
    rev.flags.allow_controlled_insert = True
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
    # Serialize status + approval consumption. A second worker waits here and
    # then observes Applied instead of reusing a stale Pending snapshot.
    _lock_named_row("Fresko Revision", revision_name)
    rev = frappe.get_doc("Fresko Revision", revision_name)
    if rev.status != "Pending":
        frappe.throw(_("Revision {0} is not Pending").format(revision_name))
    if rev.parent_doctype != "Fresko Deal":
        frappe.throw(_("Only Fresko Deal revisions supported in Phase 1"))

    deal = frappe.get_doc("Fresko Deal", rev.parent_name)
    fieldname = rev.fieldname
    # Defense in depth: never trust that a persisted Revision came through
    # request_revision (legacy/import/privileged SQL records may exist).
    if fieldname not in REVISION_ELIGIBLE_FIELDS:
        frappe.throw(_("Field {0} is not revision-eligible").format(fieldname))
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
        _lock_named_row("Fresko Approval", approval_ref)
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


def _lock_named_row(doctype: str, name: str) -> None:
    """Lock an exact audit row; callers still perform normal not-found checks."""
    table = {
        "Fresko Revision": "`tabFresko Revision`",
        "Fresko Approval": "`tabFresko Approval`",
    }.get(doctype)
    if not table:
        frappe.throw(_("Unsupported lock target {0}").format(doctype))
    frappe.db.sql(f"SELECT name FROM {table} WHERE name=%s FOR UPDATE", (name,))


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


def _ensure_open_exception(
    deal,
    exception_type: str,
    description: str,
    severity: str = "Medium",
):
    """Reuse an existing open exception of this type, otherwise create one."""
    existing = frappe.get_all(
        "Fresko Exception",
        filters={
            "deal": deal.name,
            "exception_type": exception_type,
            "status": ("in", ["Open", "In Progress"]),
        },
        limit=1,
    )
    if existing:
        row = existing[0]
        name = row.get("name") if hasattr(row, "get") else getattr(row, "name", None)
        return frappe.get_doc("Fresko Exception", name)
    return _open_exception(deal, exception_type, description, severity=severity)


def _get_open_rate_floor_breach(deal):
    """Return the single unresolved rate-floor exception serialized by Deal locks."""
    rows = frappe.get_all(
        "Fresko Exception",
        filters={
            "deal": deal.name,
            "exception_type": "RATE_FLOOR_BREACH",
            "status": ("in", ["Open", "In Progress"]),
        },
        fields=["name"],
        order_by="creation asc",
        limit=1,
    )
    if not rows:
        return None
    row = rows[0]
    name = row.get("name") if hasattr(row, "get") else getattr(row, "name", None)
    return frappe.get_doc("Fresko Exception", name) if name else None


def _rate_is_within_stored_band(deal, rate) -> bool:
    """Classify a decision only against the immutable band stored on the Deal."""
    if not policy_resolved(deal.rate_floor, deal.rate_ceiling):
        return False
    return rate_in_band(rate, deal.rate_floor, deal.rate_ceiling)


def _transition_rate_floor_breach(deal, approval, status: str, rate, reason: str):
    """Advance the open rate-floor exception with a complete commercial audit note."""
    exception_doc = None
    exception_name = getattr(approval, "exception", None) if approval is not None else None
    if exception_name:
        candidate = frappe.get_doc("Fresko Exception", exception_name)
        if getattr(candidate, "exception_type", None) == "RATE_FLOOR_BREACH":
            exception_doc = candidate
    if exception_doc is None:
        exception_doc = _get_open_rate_floor_breach(deal)
    if exception_doc is None:
        return None

    approval_name = getattr(approval, "name", None) or getattr(deal, "approval", None)
    decision = getattr(approval, "decision", None) or "COUNTER"
    actor = getattr(getattr(frappe, "session", None), "user", None) or "UNKNOWN"
    exception_doc.status = status
    exception_doc.resolution_notes = (
        f"approval={approval_name}; decision={decision}; decision_rate={rate}; "
        f"stored_band={deal.rate_floor}..{deal.rate_ceiling}; actor={actor}; reason={reason}"
    )
    # FreskoException.validate owns resolved_at/resolved_by stamps for terminal states.
    exception_doc.save(ignore_permissions=True)
    return exception_doc


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
