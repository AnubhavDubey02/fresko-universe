"""Whitelist approval decisions — fresko_universe.approvals.decide."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from fresko_universe.ats import available_to_sell
from fresko_universe.constants import OVERSELL_OVERRIDE_ROLES
from fresko_universe.deals import _maybe_open_buyer_unresolved, _open_exception
from fresko_universe.permissions import (
    assert_can_create_revision_approval,
)


@frappe.whitelist()
def decide(
    deal_name: str,
    decision: str,
    decision_rate=None,
    reason: str | None = None,
    oversell_override: int | bool = 0,
):
    """
    Approver decision path.
    APPROVE with decision_rate → Approved (immediate different rate; not COUNTER).
    COUNTER → Countered (D4: requires accept_counter before Approved).
      decision_rate lives on Approval only; Deal.approved_rate stays NULL until accept.
    REJECT → Rejected.
    OVERSELL_OVERRIDE → System Manager only (D10); commercial commitment + Exception.

    Allowed only from Approval Required (F-H2 / F-C1): not Proposed, not Countered.
    Countered → Approved exclusively via deals.accept_counter.
    """
    decision = (decision or "").upper().strip()
    if decision not in {"APPROVE", "COUNTER", "REJECT", "OVERSELL_OVERRIDE"}:
        frappe.throw(_("Invalid decision {0}").format(decision))
    if not reason:
        frappe.throw(_("Reason is required for approval decisions"))

    roles = set(frappe.get_roles())
    if "Fresko Approver" not in roles and "System Manager" not in roles:
        frappe.throw(_("Only Fresko Approver / System Manager may decide"))

    deal = frappe.get_doc("Fresko Deal", deal_name)

    # F-C1 / F-H2: decide only from Approval Required
    if deal.status != "Approval Required":
        if deal.status == "Countered":
            frappe.throw(
                _(
                    "Cannot decide from Countered — use deals.accept_counter "
                    "for originator accept (D4). Approver who wants an immediate "
                    "rate must APPROVE with decision_rate from Approval Required."
                )
            )
        if deal.status == "Proposed":
            frappe.throw(
                _(
                    "Cannot decide from Proposed — call deals.apply_rate_rules "
                    "first so floor/ceiling are snapshotted (F-H2)."
                )
            )
        frappe.throw(_("Cannot decide deal in status {0}").format(deal.status))

    oversell_override = int(oversell_override or 0)
    if decision == "OVERSELL_OVERRIDE":
        if not (roles & OVERSELL_OVERRIDE_ROLES):
            frappe.throw(_("Oversell override restricted to System Manager (D10)"))
        oversell_override = 1
        decision = "APPROVE"  # commercial approve with override flag
    elif oversell_override:
        # Plain APPROVE with oversell_override=1 still needs D10 roles
        if not (roles & OVERSELL_OVERRIDE_ROLES):
            frappe.throw(_("Oversell override restricted to System Manager (D10)"))

    # Snapshot rates on Approval row
    rate = flt(decision_rate) if decision_rate is not None else None

    if decision == "APPROVE":
        if rate is None:
            rate = flt(deal.proposed_rate)
        # ATS under lock (D3)
        ats = available_to_sell(deal.container, deal.lot_no, exclude_deal=deal.name, for_update=True)
        if flt(deal.qty) > ats and not oversell_override:
            frappe.throw(
                _("Cannot approve: qty {0} > ATS {1}. Use OVERSELL_OVERRIDE (D10) if authorized.").format(
                    deal.qty, ats
                )
            )
        if flt(deal.qty) > ats and oversell_override:
            ex = _open_exception(
                deal,
                "OVERSELL_OVERRIDE",
                f"Commercial oversell override: qty {deal.qty} > ATS {ats}. Reason: {reason}",
                severity="Critical",
            )
        else:
            ex = None

        approval = _insert_approval(
            deal,
            "OVERSELL_OVERRIDE" if oversell_override else "APPROVE",
            rate,
            reason,
            oversell_override,
            ex,
        )
        deal.flags.allow_approval_write = True
        deal.approved_rate = rate
        deal.approval = approval.name
        deal.approval_required = 0
        deal.set_status("Approved")
        _maybe_open_buyer_unresolved(deal)
        # FSEC-001 audit: ignore_permissions AFTER Approver/SM role gate + D10 checks above.
        deal.save(ignore_permissions=True)
        frappe.db.commit()
        return _result(deal, approval)

    if decision == "COUNTER":
        if rate is None:
            frappe.throw(_("COUNTER requires decision_rate"))
        # RC: store counter on Approval.decision_rate only; Deal.approved_rate stays NULL
        # until accept_counter copies it (avoids silent commercial certainty while Countered).
        approval = _insert_approval(deal, "COUNTER", rate, reason, 0, None)
        deal.flags.allow_approval_write = True
        deal.approval = approval.name
        deal.set_status("Countered")
        deal.save(ignore_permissions=True)
        # Currency coerce may turn unset into 0.0 — force SQL NULL (same Gate 1 pattern).
        frappe.db.set_value(
            "Fresko Deal",
            deal.name,
            {"approved_rate": None},
            update_modified=False,
        )
        deal.approved_rate = None
        frappe.db.commit()
        return _result(deal, approval)

    if decision == "REJECT":
        approval = _insert_approval(deal, "REJECT", rate, reason, 0, None)
        deal.approval = approval.name
        deal.set_status("Rejected")
        deal.save(ignore_permissions=True)
        frappe.db.commit()
        return _result(deal, approval)


@frappe.whitelist()
def create_revision_approval(
    revision_name: str,
    decision: str,
    decision_rate=None,
    reason: str | None = None,
):
    """Create a Fresko Approval bound to a Pending Fresko Revision (deal + revision).

    Material apply_revision requires this bind; Deal-only Approvals are not accepted.
    """
    assert_can_create_revision_approval()
    decision = (decision or "").upper().strip()
    # Phase 1 revisions fail closed on ATS and have no valid oversell-apply path.
    # Do not mint misleading OVERSELL_OVERRIDE evidence for this endpoint.
    if decision != "APPROVE":
        frappe.throw(
            _("create_revision_approval decision must be APPROVE in Phase 1 "
              "(got {0})").format(decision or "(empty)")
        )
    if not reason:
        frappe.throw(_("Reason is required for revision approvals"))

    rev = frappe.get_doc("Fresko Revision", revision_name)
    if rev.status != "Pending":
        frappe.throw(_("Revision {0} is not Pending").format(revision_name))
    if rev.parent_doctype != "Fresko Deal":
        frappe.throw(_("Only Fresko Deal revisions supported in Phase 1"))

    deal = frappe.get_doc("Fresko Deal", rev.parent_name)
    rate = flt(decision_rate) if decision_rate is not None else None
    if rate is None:
        rate = flt(deal.approved_rate if deal.approved_rate is not None else deal.proposed_rate)

    approval = _insert_approval(
        deal,
        decision,
        rate,
        reason,
        1 if decision == "OVERSELL_OVERRIDE" else 0,
        None,
        revision=rev.name,
    )
    # Link without Document.save (Pending trail stays append-friendly)
    frappe.db.set_value(
        "Fresko Revision",
        rev.name,
        "approval_reference",
        approval.name,
        update_modified=False,
    )
    rev.approval_reference = approval.name
    frappe.db.commit()
    return {
        "approval": approval.name,
        "revision": rev.name,
        "deal": deal.name,
        "decision": approval.decision,
        "decision_rate": approval.decision_rate,
    }


def _insert_approval(deal, decision, rate, reason, oversell_override, exception_doc, revision=None):
    ap = frappe.get_doc(
        {
            "doctype": "Fresko Approval",
            "deal": deal.name,
            "revision": revision,
            "decision": decision,
            "decision_rate": rate,
            "proposed_rate": deal.proposed_rate,
            "rate_floor": deal.rate_floor,
            "rate_ceiling": deal.rate_ceiling,
            "approver": frappe.session.user,
            "reason": reason,
            "oversell_override": oversell_override,
            "exception": exception_doc.name if exception_doc else None,
            "consumed": 0,
        }
    )
    ap.flags.allow_controlled_insert = True
    # Append-only Approval row; insert after decide() role gate (FSEC-001).
    ap.insert(ignore_permissions=True)
    return ap


def _result(deal, approval):
    return {
        "deal": deal.name,
        "status": deal.status,
        "approved_rate": deal.approved_rate,
        "proposed_rate": deal.proposed_rate,
        "approval": approval.name,
        "decision": approval.decision,
        "decision_rate": approval.decision_rate,
    }


# Alias matching blueprint naming
apply_approval_decision = decide
