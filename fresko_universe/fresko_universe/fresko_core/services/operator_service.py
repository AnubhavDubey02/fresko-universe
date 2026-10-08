"""Unified Read-Only Operator Action-Feed Service.

Governed by PR #19 Operator UX P0 contract & Sol High review invariants:
1. Strict Supplier-First Denial: Immediately rejects any role containing 'supplier'.
2. AST Enforcement: NO raw SQL (frappe.db.sql), NO frappe.get_all, NO ignore_permissions=True.
3. Permission Query Scoping: All direct queries execute via frappe.get_list.
4. Positive Company Authorization: Validates explicit, default, or discovered companies positively.
5. Record & Evidence Authorization: Individual doc read permissions checked before output.
   Restricted records or evidence NEVER leak names, hashes, or counts.
6. Live-Only Operational Invariant: Task feeds are strictly live; historical cutoffs rejected.
7. Transition-Specific Segregation of Duties: Actions fail closed if workflow state or actors missing.
8. Reuses existing authorized financial projections (bank pending, unallocated receipts, open exceptions).
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
import frappe
from frappe import _
from frappe.utils import now_datetime


def _deny_supplier_and_unauthorized() -> tuple[str, set[str]]:
    """Assert session user is not guest, not supplier, and return roles."""
    session_user = frappe.session.user
    if not session_user or session_user in ("", "Guest"):
        frappe.throw(_("Authentication required to access operator action feeds"), frappe.PermissionError)

    user_roles = set(frappe.get_roles(session_user))
    if any("supplier" in r.casefold() for r in user_roles):
        frappe.throw(_("Supplier identities cannot access operator action feeds"), frappe.PermissionError)

    operational_roles = user_roles & {
        "Fresko Salesperson",
        "Fresko Trader",
        "Fresko Accounts",
        "Fresko Approver",
        "System Manager",
    }
    if not operational_roles:
        frappe.throw(_("Access denied: You do not have operator roles"), frappe.PermissionError)

    return session_user, user_roles


def _row(doc: Any) -> Any:
    """Safe wrapper allowing attribute notation on standard dict or _dict objects."""
    if isinstance(doc, dict):
        class _Row(dict):
            def __getattr__(self, attr):
                return self.get(attr)
        return _Row(doc)
    return doc


def _validate_company(company: str | None) -> str:
    """Validate requested company positively against user's permitted access.

    Uses only pinned Frappe APIs: has_permission and get_list.
    """
    if company:
        if not frappe.has_permission("Company", doc=company, ptype="read"):
            frappe.throw(_("Access denied for company {0}").format(company), frappe.PermissionError)
        return company

    default_company = frappe.defaults.get_user_default("Company")
    if default_company and frappe.has_permission("Company", doc=default_company, ptype="read"):
        return default_company

    comps = frappe.get_list("Company", fields=["name"], limit_page_length=1)
    if comps and frappe.has_permission("Company", doc=_row(comps[0]).name, ptype="read"):
        return _row(comps[0]).name

    frappe.throw(_("No authorized company available for operator feeds"), frappe.PermissionError)


def check_action_eligibility(
    action: str | dict,
    doc: dict | str | None = None,
    actor: str | None = None,
    user_roles: set[str] | None = None,
    is_historical: bool = False,
) -> tuple[bool, str | None]:
    """Transition-specific authorization check matching commercial and money segregation rules.

    Fails closed if target state is wrong or required maker/verifier actors are missing.
    Returns (allowed: bool, blocked_reason: str | None).
    """
    if isinstance(action, dict) and isinstance(doc, str):
        action, doc = doc, action

    if is_historical:
        return False, "Historical projection is read-only"

    if action == "verify":
        action = "verify_sale"
    elif action == "approve":
        action = "approve_sale"

    if doc is None:
        doc = {}
    if user_roles is None:
        user_roles = set()

    # FR-QA-010: Fail closed if status/state is missing. Do not synthesize status fallback.
    status = doc.get("status") or doc.get("state")
    if status is None:
        return False, "Missing workflow status"

    maker = doc.get("prepared_by") or doc.get("proposed_by")
    verifier = doc.get("verified_by")

    # Commercial Sales
    if action == "propose_rate":
        if not (user_roles & {"Fresko Salesperson", "Fresko Trader"}):
            return False, "Requires Fresko Salesperson or Trader role"
        if status not in ("DRAFT", "REVIEW_PENDING", "APPROVED"):
            return False, f"Cannot propose rate in state {status}"
        return True, None

    if action == "verify_sale":
        if "Fresko Accounts" not in user_roles:
            return False, "Requires Fresko Accounts role"
        if status != "REVIEW_PENDING":
            return False, f"Cannot verify sale in state {status}"
        if not maker:
            return False, "Record missing prepared_by identity"
        if actor == maker:
            return False, "Awaiting another verifier — you prepared this record"
        return True, None

    if action == "approve_sale":
        if "Fresko Approver" not in user_roles:
            return False, "Requires Fresko Approver role"
        if status != "VERIFIED":
            return False, f"Cannot approve sale in state {status}"
        if not maker:
            return False, "Record missing prepared_by identity"
        if not verifier:
            return False, "Record missing verified_by identity"
        if maker == verifier:
            return False, "Maker and verifier cannot be the same user"
        if actor == maker:
            return False, "Awaiting another approver — you prepared this record"
        if actor == verifier:
            return False, "Awaiting another approver — you verified this record"
        return True, None

    # Collections
    if action == "verify_collection":
        if "Fresko Accounts" not in user_roles:
            return False, "Requires Fresko Accounts role"
        if status != "REVIEW_PENDING":
            return False, f"Cannot verify collection in state {status}"
        if not maker:
            return False, "Record missing prepared_by identity"
        if actor == maker:
            return False, "Awaiting another verifier — you prepared this record"
        return True, None

    if action == "approve_collection":
        if "Fresko Approver" not in user_roles:
            return False, "Requires Fresko Approver role"
        if status != "VERIFIED":
            return False, f"Cannot approve collection in state {status}"
        if not maker:
            return False, "Record missing prepared_by identity"
        if not verifier:
            return False, "Record missing verified_by identity"
        if maker == verifier:
            return False, "Maker and verifier cannot be the same user"
        if actor in (maker, verifier):
            return False, "Awaiting another approver — self-approval prohibited"
        return True, None

    # Party Aliases
    if action == "propose_alias":
        if not (user_roles & {"Fresko Salesperson", "Fresko Accounts", "Fresko Trader"}):
            return False, "Requires Salesperson or Accounts role"
        return True, None

    if action == "verify_alias":
        if "Fresko Accounts" not in user_roles:
            return False, "Requires Fresko Accounts role"
        if status != "PROPOSED":
            return False, f"Cannot verify alias mapping in state {status}"
        if not maker:
            return False, "Record missing proposed_by identity"
        if actor == maker:
            return False, "Awaiting another verifier — you proposed this mapping"
        return True, None

    if action == "approve_alias":
        if "Fresko Approver" not in user_roles:
            return False, "Requires Fresko Approver role"
        if status != "VERIFIED":
            return False, f"Cannot approve alias mapping in state {status} (requires VERIFIED)"
        if not maker:
            return False, "Record missing proposed_by identity"
        if not verifier:
            return False, "Record missing verified_by identity"
        if maker == verifier:
            return False, "Maker and verifier cannot be the same user"
        if actor in (maker, verifier):
            return False, "Awaiting another approver — self-approval prohibited"
        return True, None

    # Commercial Sale Outward Allocations
    if action == "propose_commercial_allocation":
        if not (user_roles & {"Fresko Salesperson", "Fresko Trader"}):
            return False, "Requires Fresko Salesperson or Trader role"
        return True, None

    if action == "verify_sale_outward_allocation":
        if "Fresko Accounts" not in user_roles:
            return False, "Requires Fresko Accounts role"
        if status != "PROPOSED":
            return False, f"Cannot verify allocation in state {status}"
        if not maker:
            return False, "Record missing prepared_by identity"
        if actor == maker:
            return False, "Awaiting another verifier — you prepared this allocation"
        return True, None

    # FR-QA-011: Require recorded verification, distinct maker/verifier/approver
    if action == "approve_sale_outward_allocation":
        if "Fresko Approver" not in user_roles:
            return False, "Requires Fresko Approver role"
        if status != "PROPOSED":
            return False, f"Cannot approve allocation in state {status} (requires PROPOSED)"
        if not maker:
            return False, "Record missing prepared_by identity"
        if not verifier:
            return False, "Allocation requires Accounts verification (missing verified_by)"
        if maker == verifier:
            return False, "Maker and verifier cannot be the same user"
        if actor == maker:
            return False, "Awaiting another approver — you prepared this allocation"
        if actor == verifier:
            return False, "Awaiting another approver — you verified this allocation"
        return True, None

    # Payment Allocations
    if action == "propose_payment_allocation":
        if "Fresko Accounts" not in user_roles and "Fresko Approver" not in user_roles:
            return False, "Requires Fresko Accounts or Approver role"
        return True, None

    if action == "verify_payment_allocation":
        if "Fresko Accounts" not in user_roles:
            return False, "Requires Fresko Accounts role"
        if status != "REVIEW_PENDING":
            return False, f"Cannot verify payment allocation in state {status}"
        if not maker:
            return False, "Record missing prepared_by identity"
        if actor == maker:
            return False, "Awaiting another verifier — you prepared this allocation"
        return True, None

    if action == "approve_payment_allocation":
        if "Fresko Approver" not in user_roles:
            return False, "Requires Fresko Approver role"
        if status != "VERIFIED":
            return False, f"Cannot approve payment allocation in state {status}"
        if not maker:
            return False, "Record missing prepared_by identity"
        if not verifier:
            return False, "Record missing verified_by identity"
        if maker == verifier:
            return False, "Maker and verifier cannot be the same user"
        if actor in (maker, verifier):
            return False, "Awaiting another approver — self-approval prohibited"
        return True, None

    return False, "Action not recognized"


def scope_evidence(evidence_name: str | None) -> dict:
    """Check record-level read authorization for linked Evidence.

    Does not leak evidence names or contents if unauthorized.
    """
    if not evidence_name:
        return {"evidence_state": "NONE", "evidence_name": None}

    if not frappe.has_permission("Fresko Evidence", doc=evidence_name, ptype="read"):
        return {"evidence_state": "RESTRICTED", "evidence_name": None}

    return {"evidence_state": "AVAILABLE", "evidence_name": evidence_name}


def compute_outward_capacity(outward_name: str, active_company: str) -> dict:
    """Compute canonical remaining allocatable quantity for a posted Outward.

    Governed by PR #19 / FR-QA-012 capacity invariants:
    1. Only unreversed 'Posted' physical OUTWARD movements have capacity.
    2. Physical quantity is derived from Outward Line items.
    3. Allocations with state='APPROVED' (and not reversed) consume physical capacity.
    4. Reversed allocations (state='REVERSED' or reversed_by set) do NOT consume capacity.
    5. Inaccessible linked Sales consume capacity without leaking their identity.
    6. If physical quantity is missing or unparseable, returns capacity_state='UNKNOWN'.
    7. Fully allocated outwards (remaining <= 0) have capacity_state='EXHAUSTED'.
    8. Unallocated or partially allocated outwards have capacity_state='AVAILABLE'.
    """
    reversals = frappe.get_list(
        "Fresko Outward",
        filters={
            "reverses_outward": outward_name,
            "status": "Posted",
            "movement_type": "REVERSAL",
        },
        fields=["name"],
    )
    if reversals:
        return {
            "capacity_state": "REVERSED",
            "remaining_qty": Decimal("0"),
            "total_qty": Decimal("0"),
            "allocated_qty": Decimal("0"),
            "uom": None,
            "is_allocatable": False,
            "reason": "Outward physical movement was reversed",
        }

    lines = frappe.get_list(
        "Fresko Outward Line",
        filters={"parent": outward_name},
        fields=["line_key", "qty", "uom"],
    )
    if not lines and hasattr(frappe, "get_doc"):
        try:
            odoc = frappe.get_doc("Fresko Outward", outward_name)
            lines = [
                {"line_key": l.line_key, "qty": l.qty, "uom": l.uom}
                for l in getattr(odoc, "lines", [])
            ]
        except Exception:
            lines = []

    if not lines:
        return {
            "capacity_state": "UNKNOWN",
            "remaining_qty": None,
            "total_qty": None,
            "allocated_qty": None,
            "uom": None,
            "is_allocatable": False,
            "reason": "No physical lines recorded on Outward",
        }

    total_qty = Decimal("0")
    primary_uom = None

    for line in lines:
        l_qty = line.get("qty")
        if l_qty is None:
            return {
                "capacity_state": "UNKNOWN",
                "remaining_qty": None,
                "total_qty": None,
                "allocated_qty": None,
                "uom": line.get("uom"),
                "is_allocatable": False,
                "reason": "Physical line quantity is UNKNOWN",
            }
        try:
            val = Decimal(str(l_qty))
        except Exception:
            return {
                "capacity_state": "UNKNOWN",
                "remaining_qty": None,
                "total_qty": None,
                "allocated_qty": None,
                "uom": line.get("uom"),
                "is_allocatable": False,
                "reason": "Invalid physical line quantity",
            }
        total_qty += val
        if not primary_uom:
            primary_uom = line.get("uom")

    allocs = frappe.get_list(
        "Fresko Sale Outward Allocation",
        filters={"outward": outward_name, "company": active_company},
        fields=["name", "sale", "outward_line_key", "qty", "uom", "state", "reversed_by"],
    )

    total_allocated = Decimal("0")
    for al in allocs:
        state = al.get("state")
        reversed_by = al.get("reversed_by")
        if state == "APPROVED" and not reversed_by:
            try:
                al_qty = Decimal(str(al.get("qty") or "0"))
                total_allocated += al_qty
            except Exception:
                pass

    remaining_qty = total_qty - total_allocated
    if remaining_qty <= Decimal("0"):
        return {
            "capacity_state": "EXHAUSTED",
            "remaining_qty": Decimal("0"),
            "total_qty": total_qty,
            "allocated_qty": total_allocated,
            "uom": primary_uom,
            "is_allocatable": False,
            "reason": "Outward fully allocated",
        }
    elif total_allocated > Decimal("0"):
        return {
            "capacity_state": "PARTIAL",
            "remaining_qty": remaining_qty,
            "total_qty": total_qty,
            "allocated_qty": total_allocated,
            "uom": primary_uom,
            "is_allocatable": True,
            "reason": f"Partially allocated ({total_allocated} {primary_uom or ''} allocated of {total_qty} {primary_uom or ''})".strip(),
        }
    else:
        return {
            "capacity_state": "UNALLOCATED",
            "remaining_qty": remaining_qty,
            "total_qty": total_qty,
            "allocated_qty": Decimal("0"),
            "uom": primary_uom,
            "is_allocatable": True,
            "reason": f"Unallocated physical movement ({remaining_qty} {primary_uom or ''} available)".strip(),
        }


@frappe.whitelist()
def get_operator_action_feed(
    company: str | None = None,
    as_of: str | None = None,
    limit: int = 50,
) -> dict:
    """Return bounded, permission-scoped operational action feed.

    Live-only: rejects historical cutoffs. Uses only frappe.get_list and authorized services.
    """
    actor, user_roles = _deny_supplier_and_unauthorized()

    # Invariant: Action Inbox is strictly live-only
    if as_of:
        frappe.throw(
            _("Operator action feed is strictly live-only. Historical cutoffs are not supported for operational task inboxes."),
            frappe.ValidationError,
        )

    active_company = _validate_company(company)
    limit = min(max(int(limit), 1), 100)

    sections = []
    counts = {
        "unpriced_sales": 0,
        "draft_sales": 0,
        "unresolved_buyers": 0,
        "commercial_verifications": 0,
        "commercial_approvals": 0,
        "commercial_allocation_reviews": 0,
        "unassigned_outwards": 0,
        "unresolved_aliases": 0,
        "verified_aliases": 0,
        "collection_verifications": 0,
        "collection_approvals": 0,
        "bank_pending": 0,
        "unallocated_collections": 0,
        "payment_allocation_verifications": 0,
        "payment_allocation_approvals": 0,
        "exceptions": 0,
        "total_actionable": 0,
    }
    truncated = False

    # 1 & 2. Sales: Unpriced Sales & Draft Sales
    if user_roles & {"Fresko Salesperson", "Fresko Trader", "Fresko Approver"}:
        candidate_sales = frappe.get_list(
            "Fresko Commercial Sale",
            filters={
                "status": ["in", ["DRAFT", "REVIEW_PENDING", "APPROVED"]],
                "company": active_company,
            },
            fields=["name", "company", "container", "status", "prepared_by", "verified_by", "version", "source_payload", "source_evidence", "modified"],
            order_by="modified desc",
            limit_page_length=limit,
        )
        if len(candidate_sales) == limit:
            truncated = True

        unpriced_items = []
        draft_items = []

        for s in candidate_sales:
            s = _row(s)
            if not frappe.has_permission("Fresko Commercial Sale", doc=s.name, ptype="read"):
                continue

            lines = []
            if s.get("source_payload"):
                try:
                    payload = json.loads(s.source_payload)
                    lines = payload.get("lines", [])
                except Exception:
                    lines = []

            has_unpriced = any(
                line.get("price_state") in (None, "", "UNKNOWN") or line.get("rate") is None
                for line in lines
            )
            ev_info = scope_evidence(s.get("source_evidence"))
            allowed, blocked_reason = check_action_eligibility(
                "propose_rate", s, actor, user_roles
            )

            item = {
                "kind": "unpriced_sale" if has_unpriced else "draft_sale",
                "doc_ref": s.name,
                "document_name": s.name,
                "human_title": f"Sale {s.name}",
                "subtitle": f"Container {s.container or '—'} • Prepared by {s.prepared_by or 'UNKNOWN'}",
                "amount_string": "PENDING (Rate Unassigned)" if has_unpriced else "PENDING / UNKNOWN",
                "qty_string": f"{len(lines)} line(s)",
                "state": s.status,
                "state_reason": "Price awaiting proposal" if has_unpriced else "Draft sale awaiting submission",
                "container": s.container,
                "version": s.version,
                "current_version": s.version,
                "evidence_state": ev_info["evidence_state"],
                "evidence_name": ev_info["evidence_name"],
                "source_evidence": ev_info["evidence_name"],
                "actions": [
                    {
                        "action": "propose_rate",
                        "label": "Propose Rate",
                        "allowed": allowed,
                        "blocked_reason": blocked_reason,
                    }
                ],
            }

            if has_unpriced:
                unpriced_items.append(item)
            elif s.status == "DRAFT":
                draft_items.append(item)

        counts["unpriced_sales"] = len(unpriced_items)
        counts["draft_sales"] = len(draft_items)
        if unpriced_items:
            sections.append({
                "id": "unpriced_sales",
                "section_id": "unpriced_sales",
                "title": "Unpriced Sales",
                "count": len(unpriced_items),
                "items": unpriced_items,
            })
        if draft_items:
            sections.append({
                "id": "draft_sales",
                "section_id": "draft_sales",
                "title": "Draft Sales",
                "count": len(draft_items),
                "items": draft_items,
            })

    # 3. Unresolved Buyer Aliases (Sales with unresolved buyers)
    if user_roles & {"Fresko Salesperson", "Fresko Accounts", "Fresko Trader"}:
        unresolved_sales = frappe.get_list(
            "Fresko Commercial Sale",
            filters={
                "party_state": "UNRESOLVED",
                "company": active_company,
            },
            fields=["name", "company", "container", "party_state", "raw_party_alias", "customer", "status", "prepared_by", "version", "source_evidence", "modified"],
            order_by="modified desc",
            limit_page_length=limit,
        )
        if len(unresolved_sales) == limit:
            truncated = True

        unresolved_buyer_items = []
        for s in unresolved_sales:
            s = _row(s)
            if not frappe.has_permission("Fresko Commercial Sale", doc=s.name, ptype="read"):
                continue
            ev_info = scope_evidence(s.get("source_evidence"))
            can_propose, p_reason = check_action_eligibility("propose_alias", s, actor, user_roles)
            unresolved_buyer_items.append({
                "kind": "unresolved_buyer_alias",
                "doc_ref": s.name,
                "document_name": s.name,
                "human_title": f"Unresolved Buyer: {s.raw_party_alias or s.name}",
                "subtitle": f"Sale {s.name} • Container {s.container or '—'}",
                "amount_string": "—",
                "qty_string": "—",
                "state": s.party_state or "UNRESOLVED",
                "state_reason": "Raw party alias requires customer mapping proposal",
                "container": s.container,
                "version": s.version,
                "current_version": s.version,
                "evidence_state": ev_info["evidence_state"],
                "evidence_name": ev_info["evidence_name"],
                "source_evidence": ev_info["evidence_name"],
                "actions": [
                    {
                        "action": "propose_alias",
                        "label": "Propose Alias",
                        "allowed": can_propose,
                        "blocked_reason": p_reason,
                    }
                ],
            })
        counts["unresolved_buyers"] = len(unresolved_buyer_items)
        if unresolved_buyer_items:
            sections.append({
                "id": "unresolved_buyers",
                "section_id": "unresolved_buyers",
                "title": "Unresolved Buyer Aliases",
                "count": len(unresolved_buyer_items),
                "items": unresolved_buyer_items,
            })

    # 4. Commercial Sale Verifications (Accounts: REVIEW_PENDING)
    if "Fresko Accounts" in user_roles:
        review_sales = frappe.get_list(
            "Fresko Commercial Sale",
            filters={
                "status": "REVIEW_PENDING",
                "company": active_company,
            },
            fields=["name", "company", "container", "status", "prepared_by", "verified_by", "version", "source_evidence", "modified"],
            order_by="modified desc",
            limit_page_length=limit,
        )
        if len(review_sales) == limit:
            truncated = True

        comm_verifications = []
        for s in review_sales:
            s = _row(s)
            if not frappe.has_permission("Fresko Commercial Sale", doc=s.name, ptype="read"):
                continue
            allowed, blocked_reason = check_action_eligibility("verify_sale", s, actor, user_roles)
            ev_info = scope_evidence(s.get("source_evidence"))
            comm_verifications.append({
                "kind": "commercial_verification",
                "doc_ref": s.name,
                "document_name": s.name,
                "human_title": f"Sale Verification: {s.name}",
                "subtitle": f"Container {s.container or '—'} • Prepared by {s.prepared_by or 'UNKNOWN'}",
                "amount_string": "PENDING / UNKNOWN",
                "qty_string": "—",
                "state": "REVIEW_PENDING",
                "state_reason": "Awaiting verification by Accounts",
                "container": s.container,
                "version": s.version,
                "current_version": s.version,
                "evidence_state": ev_info["evidence_state"],
                "evidence_name": ev_info["evidence_name"],
                "source_evidence": ev_info["evidence_name"],
                "actions": [
                    {
                        "action": "verify_sale",
                        "label": "Verify Sale",
                        "allowed": allowed,
                        "blocked_reason": blocked_reason,
                    }
                ],
            })
        counts["commercial_verifications"] = len(comm_verifications)
        if comm_verifications:
            sections.append({
                "id": "commercial_verifications",
                "section_id": "commercial_verifications",
                "title": "Commercial Verifications",
                "count": len(comm_verifications),
                "items": comm_verifications,
            })

    # 5. Commercial Sale Approvals (Approver: VERIFIED)
    if "Fresko Approver" in user_roles:
        verified_sales = frappe.get_list(
            "Fresko Commercial Sale",
            filters={
                "status": "VERIFIED",
                "company": active_company,
            },
            fields=["name", "company", "container", "status", "prepared_by", "verified_by", "version", "source_evidence", "modified"],
            order_by="modified desc",
            limit_page_length=limit,
        )
        if len(verified_sales) == limit:
            truncated = True

        comm_approvals = []
        for s in verified_sales:
            s = _row(s)
            if not frappe.has_permission("Fresko Commercial Sale", doc=s.name, ptype="read"):
                continue
            allowed, blocked_reason = check_action_eligibility("approve_sale", s, actor, user_roles)
            ev_info = scope_evidence(s.get("source_evidence"))
            comm_approvals.append({
                "kind": "commercial_approval",
                "doc_ref": s.name,
                "document_name": s.name,
                "human_title": f"Sale Approval: {s.name}",
                "subtitle": f"Container {s.container or '—'} • Prepared by {s.prepared_by or 'UNKNOWN'}",
                "amount_string": "PENDING / UNKNOWN",
                "qty_string": "—",
                "state": "VERIFIED",
                "state_reason": "Verified by Accounts; awaiting final approval",
                "container": s.container,
                "version": s.version,
                "current_version": s.version,
                "evidence_state": ev_info["evidence_state"],
                "evidence_name": ev_info["evidence_name"],
                "source_evidence": ev_info["evidence_name"],
                "actions": [
                    {
                        "action": "approve_sale",
                        "label": "Approve Sale",
                        "allowed": allowed,
                        "blocked_reason": blocked_reason,
                    }
                ],
            })
        counts["commercial_approvals"] = len(comm_approvals)
        if comm_approvals:
            sections.append({
                "id": "commercial_approvals",
                "section_id": "commercial_approvals",
                "title": "Commercial Approvals",
                "count": len(comm_approvals),
                "items": comm_approvals,
            })

    # 6. Commercial Allocation Reviews (Fresko Sale Outward Allocation: state == PROPOSED)
    if "Fresko Accounts" in user_roles or "Fresko Approver" in user_roles:
        proposed_allocs = frappe.get_list(
            "Fresko Sale Outward Allocation",
            filters={
                "state": "PROPOSED",
                "company": active_company,
            },
            fields=["name", "company", "sale", "sale_line_key", "outward", "outward_line_key", "prepared_by", "prepared_at", "verified_by", "verified_at", "qty", "uom", "evidence", "state", "version", "modified"],
            order_by="modified desc",
            limit_page_length=limit,
        )
        if len(proposed_allocs) == limit:
            truncated = True

        alloc_items = []
        for al in proposed_allocs:
            al = _row(al)
            if not frappe.has_permission("Fresko Sale Outward Allocation", doc=al.name, ptype="read"):
                continue
            can_v, v_reason = check_action_eligibility("verify_sale_outward_allocation", al, actor, user_roles)
            can_a, a_reason = check_action_eligibility("approve_sale_outward_allocation", al, actor, user_roles)
            ev_info = scope_evidence(al.get("evidence"))

            # FR-QA-019: Suppress confidential linked Sale identifier if unauthorized
            can_read_sale = frappe.has_permission("Fresko Commercial Sale", doc=al.sale, ptype="read")
            sale_label = al.sale if can_read_sale else "[Restricted Sale]"

            actions = []
            if "Fresko Accounts" in user_roles:
                actions.append({"action": "verify_sale_outward_allocation", "label": "Verify Allocation", "allowed": can_v, "blocked_reason": v_reason})
            if "Fresko Approver" in user_roles:
                actions.append({"action": "approve_sale_outward_allocation", "label": "Approve Allocation", "allowed": can_a, "blocked_reason": a_reason})

            alloc_items.append({
                "kind": "commercial_allocation_review",
                "doc_ref": al.name,
                "document_name": al.name,
                "human_title": f"Allocation: {sale_label} ➔ {al.outward}",
                "subtitle": f"Prepared by {al.prepared_by or 'UNKNOWN'}" + (f" • Verified by {al.verified_by}" if al.verified_by else " • Awaiting verification"),
                "amount_string": "—",
                "qty_string": f"{al.qty or '—'} {al.uom or ''}".strip(),
                "state": al.state or "PROPOSED",
                "state_reason": "Proposed commercial allocation awaiting verification/approval",
                "container": None,
                "sale": sale_label,
                "outward": al.outward,
                "version": al.version,
                "current_version": al.version,
                "evidence_state": ev_info["evidence_state"],
                "evidence_name": ev_info["evidence_name"],
                "source_evidence": ev_info["evidence_name"],
                "actions": actions,
            })
        counts["commercial_allocation_reviews"] = len(alloc_items)
        if alloc_items:
            sections.append({
                "id": "commercial_allocation_reviews",
                "section_id": "commercial_allocation_reviews",
                "title": "Commercial Allocation Reviews",
                "count": len(alloc_items),
                "items": alloc_items,
            })

    # 7. Unassigned Outwards (Posted outwards with remaining unallocated capacity)
    # FR-QA-009: Removed nonexistent 'version' field from Outward query.
    # FR-QA-012: Checked canonical capacity; fully allocated outwards are excluded.
    if user_roles & {"Fresko Salesperson", "Fresko Trader"}:
        posted_outwards = frappe.get_list(
            "Fresko Outward",
            filters={
                "status": "Posted",
                "movement_type": "OUTWARD",
                "company": active_company,
            },
            fields=["name", "company", "container", "movement_type", "status", "prepared_by", "source_evidence", "modified"],
            order_by="modified desc",
            limit_page_length=limit,
        )
        if len(posted_outwards) == limit:
            truncated = True

        unassigned_outwards = []
        for o in posted_outwards:
            o = _row(o)
            if not frappe.has_permission("Fresko Outward", doc=o.name, ptype="read"):
                continue

            cap = compute_outward_capacity(o.name, active_company)
            if not cap["is_allocatable"]:
                continue

            ev_info = scope_evidence(o.get("source_evidence"))
            allowed, blocked_reason = check_action_eligibility(
                "propose_commercial_allocation", o, actor, user_roles
            )

            rem_str = f"{cap['remaining_qty']} {cap['uom'] or ''}".strip()
            tot_str = f"{cap['total_qty']} {cap['uom'] or ''}".strip()
            qty_label = f"{rem_str} remaining of {tot_str}" if cap["capacity_state"] == "PARTIAL" else f"{rem_str} available"

            unassigned_outwards.append({
                "kind": "unassigned_outward",
                "doc_ref": o.name,
                "document_name": o.name,
                "human_title": f"Outward {o.name}",
                "subtitle": f"Container {o.container or '—'} • {cap['reason']}",
                "amount_string": "—",
                "qty_string": qty_label,
                "state": "Posted",
                "state_reason": cap["reason"],
                "container": o.container,
                "version": None,
                "current_version": None,
                "evidence_state": ev_info["evidence_state"],
                "evidence_name": ev_info["evidence_name"],
                "source_evidence": ev_info["evidence_name"],
                "actions": [
                    {
                        "action": "propose_commercial_allocation",
                        "label": "Allocate Outward",
                        "allowed": allowed,
                        "blocked_reason": blocked_reason,
                    }
                ],
            })
        counts["unassigned_outwards"] = len(unassigned_outwards)
        if unassigned_outwards:
            sections.append({
                "id": "unassigned_outwards",
                "section_id": "unassigned_outwards",
                "title": "Unassigned Outwards",
                "count": len(unassigned_outwards),
                "items": unassigned_outwards,
            })

    # 8. Unresolved Aliases & Mapping Reviews (Separate PROPOSED from VERIFIED)
    if user_roles & {"Fresko Salesperson", "Fresko Accounts", "Fresko Approver", "Fresko Trader"}:
        proposed_aliases = frappe.get_list(
            "Fresko Party Alias Mapping",
            filters={
                "status": "PROPOSED",
                "company": active_company,
            },
            fields=["name", "company", "raw_alias", "proposed_customer", "status", "proposed_by", "proposed_at", "verified_by", "verified_at", "version", "evidence", "modified"],
            order_by="modified desc",
            limit_page_length=limit,
        )
        proposed_items = []
        for a in proposed_aliases:
            a = _row(a)
            if not frappe.has_permission("Fresko Party Alias Mapping", doc=a.name, ptype="read"):
                continue
            can_v, v_reason = check_action_eligibility("verify_alias", a, actor, user_roles)
            ev_info = scope_evidence(a.get("evidence"))
            proposed_items.append({
                "kind": "unresolved_alias",
                "doc_ref": a.name,
                "document_name": a.name,
                "human_title": f"Proposed Alias: {a.raw_alias or '—'}",
                "subtitle": f"Proposed for {a.proposed_customer or 'UNKNOWN'} • By {a.proposed_by or 'UNKNOWN'}",
                "amount_string": "—",
                "qty_string": "—",
                "state": "PROPOSED",
                "state_reason": "Proposed alias mapping awaiting verification",
                "container": None,
                "version": a.version,
                "current_version": a.version,
                "evidence_state": ev_info["evidence_state"],
                "evidence_name": ev_info["evidence_name"],
                "source_evidence": ev_info["evidence_name"],
                "actions": [
                    {
                        "action": "verify_alias",
                        "label": "Verify Mapping",
                        "allowed": can_v,
                        "blocked_reason": v_reason,
                    }
                ],
            })
        counts["unresolved_aliases"] = len(proposed_items)
        if proposed_items:
            sections.append({
                "id": "unresolved_aliases",
                "section_id": "unresolved_aliases",
                "title": "Proposed Alias Mappings",
                "count": len(proposed_items),
                "items": proposed_items,
            })

        if "Fresko Approver" in user_roles:
            verified_aliases = frappe.get_list(
                "Fresko Party Alias Mapping",
                filters={
                    "status": "VERIFIED",
                    "company": active_company,
                },
                fields=["name", "company", "raw_alias", "proposed_customer", "status", "proposed_by", "proposed_at", "verified_by", "verified_at", "version", "evidence", "modified"],
                order_by="modified desc",
                limit_page_length=limit,
            )
            verified_items = []
            for a in verified_aliases:
                a = _row(a)
                if not frappe.has_permission("Fresko Party Alias Mapping", doc=a.name, ptype="read"):
                    continue
                can_a, a_reason = check_action_eligibility("approve_alias", a, actor, user_roles)
                ev_info = scope_evidence(a.get("evidence"))
                verified_items.append({
                    "kind": "verified_alias",
                    "doc_ref": a.name,
                    "document_name": a.name,
                    "human_title": f"Verified Alias: {a.raw_alias or '—'}",
                    "subtitle": f"Customer: {a.proposed_customer or 'UNKNOWN'} • Verified by {a.verified_by or 'UNKNOWN'}",
                    "amount_string": "—",
                    "qty_string": "—",
                    "state": "VERIFIED",
                    "state_reason": "Verified alias mapping awaiting approval",
                    "container": None,
                    "version": a.version,
                    "current_version": a.version,
                    "evidence_state": ev_info["evidence_state"],
                    "evidence_name": ev_info["evidence_name"],
                    "source_evidence": ev_info["evidence_name"],
                    "actions": [
                        {
                            "action": "approve_alias",
                            "label": "Approve Mapping",
                            "allowed": can_a,
                            "blocked_reason": a_reason,
                        }
                    ],
                })
            counts["verified_aliases"] = len(verified_items)
            if verified_items:
                sections.append({
                    "id": "verified_aliases",
                    "section_id": "verified_aliases",
                    "title": "Verified Aliases for Approval",
                    "count": len(verified_items),
                    "items": verified_items,
                })

    # 9. Collection Verifications (Accounts: REVIEW_PENDING)
    if "Fresko Accounts" in user_roles:
        review_cols = frappe.get_list(
            "Fresko Collection",
            filters={
                "status": "REVIEW_PENDING",
                "company": active_company,
            },
            fields=["name", "company", "customer", "prepared_by", "prepared_at", "verified_by", "status", "payment_channel", "bank_state", "version", "source_evidence", "modified"],
            order_by="modified desc",
            limit_page_length=limit,
        )
        if len(review_cols) == limit:
            truncated = True

        col_verifications = []
        for c in review_cols:
            c = _row(c)
            if not frappe.has_permission("Fresko Collection", doc=c.name, ptype="read"):
                continue
            allowed, blocked_reason = check_action_eligibility("verify_collection", c, actor, user_roles)
            ev_info = scope_evidence(c.get("source_evidence") or c.get("evidence"))
            col_verifications.append({
                "kind": "collection_verification",
                "payment_channel": c.payment_channel,
                "doc_ref": c.name,
                "document_name": c.name,
                "human_title": f"Collection Verification: {c.customer or c.name}",
                "subtitle": f"Channel: {c.payment_channel or 'UNKNOWN'} • Bank State: {c.bank_state or 'NONE'}",
                "amount_string": "PENDING / UNKNOWN",
                "qty_string": "—",
                "state": "REVIEW_PENDING",
                "state_reason": "Captured collection awaiting Accounts verification",
                "container": None,
                "version": c.version,
                "current_version": c.version,
                "evidence_state": ev_info["evidence_state"],
                "evidence_name": ev_info["evidence_name"],
                "source_evidence": ev_info["evidence_name"],
                "actions": [
                    {
                        "action": "verify_collection",
                        "label": "Verify Collection",
                        "allowed": allowed,
                        "blocked_reason": blocked_reason,
                    }
                ],
            })
        counts["collection_verifications"] = len(col_verifications)
        if col_verifications:
            sections.append({
                "id": "collection_verifications",
                "section_id": "collection_verifications",
                "title": "Collection Verifications",
                "count": len(col_verifications),
                "items": col_verifications,
            })

    # 10. Collection Approvals (Approver: VERIFIED)
    if "Fresko Approver" in user_roles:
        verified_cols = frappe.get_list(
            "Fresko Collection",
            filters={
                "status": "VERIFIED",
                "company": active_company,
            },
            fields=["name", "company", "customer", "prepared_by", "prepared_at", "verified_by", "verified_at", "status", "payment_channel", "bank_state", "version", "source_evidence", "modified"],
            order_by="modified desc",
            limit_page_length=limit,
        )
        if len(verified_cols) == limit:
            truncated = True

        col_approvals = []
        for c in verified_cols:
            c = _row(c)
            if not frappe.has_permission("Fresko Collection", doc=c.name, ptype="read"):
                continue
            allowed, blocked_reason = check_action_eligibility("approve_collection", c, actor, user_roles)
            ev_info = scope_evidence(c.get("source_evidence") or c.get("evidence"))
            col_approvals.append({
                "kind": "collection_approval",
                "payment_channel": c.payment_channel,
                "doc_ref": c.name,
                "document_name": c.name,
                "human_title": f"Collection Approval: {c.customer or c.name}",
                "subtitle": f"Channel: {c.payment_channel or 'UNKNOWN'} • Bank State: {c.bank_state or 'NONE'}",
                "amount_string": "PENDING / UNKNOWN",
                "qty_string": "—",
                "state": "VERIFIED",
                "state_reason": "Verified collection awaiting Approver sign-off",
                "container": None,
                "version": c.version,
                "current_version": c.version,
                "evidence_state": ev_info["evidence_state"],
                "evidence_name": ev_info["evidence_name"],
                "source_evidence": ev_info["evidence_name"],
                "actions": [
                    {
                        "action": "approve_collection",
                        "label": "Approve Collection",
                        "allowed": allowed,
                        "blocked_reason": blocked_reason,
                    }
                ],
            })
        counts["collection_approvals"] = len(col_approvals)
        if col_approvals:
            sections.append({
                "id": "collection_approvals",
                "section_id": "collection_approvals",
                "title": "Collection Approvals",
                "count": len(col_approvals),
                "items": col_approvals,
            })

    # 11. Bank-Pending Receipts (Non-cash receipts awaiting bank clearance)
    if "Fresko Accounts" in user_roles or "Fresko Approver" in user_roles:
        pending_bank_cols = frappe.get_list(
            "Fresko Collection",
            filters={
                "bank_state": ["in", ["PENDING", "AUTHORIZATION_INPROCESS"]],
                "company": active_company,
            },
            fields=["name", "company", "customer", "status", "bank_state", "payment_channel", "version", "source_evidence", "modified"],
            order_by="modified desc",
            limit_page_length=limit,
        )
        bank_pending_items = []
        for c in pending_bank_cols:
            c = _row(c)
            # Exclude cash and terminal states
            if c.payment_channel == "CASH":
                continue
            if c.status in ("REJECTED", "CANCELLED", "REVERSED"):
                continue
            if c.bank_state in ("CLEARED", "REJECTED", "CANCELLED", "SETTLED", "NONE", ""):
                continue
            if not frappe.has_permission("Fresko Collection", doc=c.name, ptype="read"):
                continue
            ev_info = scope_evidence(c.get("source_evidence") or c.get("evidence"))
            bank_pending_items.append({
                "kind": "bank_pending_receipt",
                "payment_channel": c.payment_channel,
                "doc_ref": c.name,
                "document_name": c.name,
                "human_title": f"Bank Clearance Pending: {c.customer or c.name}",
                "subtitle": f"Bank State: {c.bank_state} • Channel: {c.payment_channel or 'UNKNOWN'}",
                "amount_string": "PENDING / UNKNOWN",
                "qty_string": "—",
                "state": c.bank_state,
                "state_reason": f"Awaiting bank credit confirmation ({c.bank_state})",
                "container": None,
                "version": c.version,
                "current_version": c.version,
                "evidence_state": ev_info["evidence_state"],
                "evidence_name": ev_info["evidence_name"],
                "source_evidence": ev_info["evidence_name"],
                "actions": [],
            })
        counts["bank_pending"] = len(bank_pending_items)
        if bank_pending_items:
            sections.append({
                "id": "bank_pending",
                "section_id": "bank_pending",
                "title": "Bank-Pending Receipts",
                "count": len(bank_pending_items),
                "items": bank_pending_items,
            })

    # 12. Unallocated Collections (Approved collections with unallocated funds)
    if "Fresko Accounts" in user_roles or "Fresko Approver" in user_roles:
        unalloc_cols = frappe.get_list(
            "Fresko Collection",
            filters={
                "status": "APPROVED",
                "company": active_company,
            },
            fields=["name", "company", "customer", "status", "payment_channel", "unallocated_amount", "amount", "currency", "version", "source_evidence", "modified"],
            order_by="modified desc",
            limit_page_length=limit,
        )
        unalloc_items = []
        for c in unalloc_cols:
            c = _row(c)
            try:
                unalloc_amt = Decimal(str(c.unallocated_amount or "0"))
            except Exception:
                unalloc_amt = Decimal("0")
            if unalloc_amt <= Decimal("0"):
                continue
            if not frappe.has_permission("Fresko Collection", doc=c.name, ptype="read"):
                continue
            ev_info = scope_evidence(c.get("source_evidence"))
            can_act, reason = check_action_eligibility("propose_payment_allocation", c, actor, user_roles)
            unalloc_items.append({
                "kind": "unallocated_collection",
                "payment_channel": c.payment_channel,
                "doc_ref": c.name,
                "document_name": c.name,
                "human_title": f"Unallocated Collection: {c.customer or c.name}",
                "subtitle": f"Unallocated: {unalloc_amt} {c.currency or ''} • Channel: {c.payment_channel or 'UNKNOWN'}".strip(),
                "amount_string": f"{unalloc_amt} {c.currency or ''}".strip(),
                "qty_string": "—",
                "state": "APPROVED",
                "state_reason": "Approved collection awaiting payment allocation to sale",
                "container": None,
                "version": c.version,
                "current_version": c.version,
                "evidence_state": ev_info["evidence_state"],
                "evidence_name": ev_info["evidence_name"],
                "source_evidence": ev_info["evidence_name"],
                "actions": [
                    {
                        "action": "propose_payment_allocation",
                        "label": "Allocate Payment",
                        "allowed": can_act,
                        "blocked_reason": reason,
                    }
                ],
            })
        counts["unallocated_collections"] = len(unalloc_items)
        if unalloc_items:
            sections.append({
                "id": "unallocated_collections",
                "section_id": "unallocated_collections",
                "title": "Unallocated Collections",
                "count": len(unalloc_items),
                "items": unalloc_items,
            })

    # 13. Payment Allocation Reviews (REVIEW_PENDING and VERIFIED)
    if "Fresko Accounts" in user_roles or "Fresko Approver" in user_roles:
        review_allocs = frappe.get_list(
            "Fresko Payment Allocation",
            filters={
                "status": "REVIEW_PENDING",
                "company": active_company,
            },
            fields=["name", "company", "collection", "sale", "prepared_by", "prepared_at", "status", "version", "evidence", "modified"],
            order_by="modified desc",
            limit_page_length=limit,
        )
        pay_verifications = []
        for pa in review_allocs:
            pa = _row(pa)
            if not frappe.has_permission("Fresko Payment Allocation", doc=pa.name, ptype="read"):
                continue
            can_v, v_reason = check_action_eligibility("verify_payment_allocation", pa, actor, user_roles)
            ev_info = scope_evidence(pa.get("evidence"))
            pay_verifications.append({
                "kind": "payment_allocation_verification",
                "doc_ref": pa.name,
                "document_name": pa.name,
                "human_title": f"Allocation Verification: {pa.collection} ➔ {pa.sale}",
                "subtitle": f"Prepared by {pa.prepared_by or 'UNKNOWN'}",
                "amount_string": "PENDING / UNKNOWN",
                "qty_string": "—",
                "state": "REVIEW_PENDING",
                "state_reason": "Payment allocation awaiting Accounts verification",
                "container": None,
                "version": pa.version,
                "current_version": pa.version,
                "evidence_state": ev_info["evidence_state"],
                "evidence_name": ev_info["evidence_name"],
                "source_evidence": ev_info["evidence_name"],
                "actions": [
                    {
                        "action": "verify_payment_allocation",
                        "label": "Verify Allocation",
                        "allowed": can_v,
                        "blocked_reason": v_reason,
                    }
                ],
            })
        counts["payment_allocation_verifications"] = len(pay_verifications)
        if pay_verifications:
            sections.append({
                "id": "payment_allocation_verifications",
                "section_id": "payment_allocation_verifications",
                "title": "Payment Allocation Verifications",
                "count": len(pay_verifications),
                "items": pay_verifications,
            })

        if "Fresko Approver" in user_roles:
            verified_allocs = frappe.get_list(
                "Fresko Payment Allocation",
                filters={
                    "status": "VERIFIED",
                    "company": active_company,
                },
                fields=["name", "company", "collection", "sale", "prepared_by", "prepared_at", "verified_by", "verified_at", "status", "version", "evidence", "modified"],
                order_by="modified desc",
                limit_page_length=limit,
            )
            pay_approvals = []
            for pa in verified_allocs:
                pa = _row(pa)
                if not frappe.has_permission("Fresko Payment Allocation", doc=pa.name, ptype="read"):
                    continue
                can_a, a_reason = check_action_eligibility("approve_payment_allocation", pa, actor, user_roles)
                ev_info = scope_evidence(pa.get("evidence"))
                pay_approvals.append({
                    "kind": "payment_allocation_approval",
                    "doc_ref": pa.name,
                    "document_name": pa.name,
                    "human_title": f"Allocation Approval: {pa.collection} ➔ {pa.sale}",
                    "subtitle": f"Prepared by {pa.prepared_by or 'UNKNOWN'} • Verified by {pa.verified_by or 'UNKNOWN'}",
                    "amount_string": "PENDING / UNKNOWN",
                    "qty_string": "—",
                    "state": "VERIFIED",
                    "state_reason": "Verified payment allocation awaiting approval",
                    "container": None,
                    "version": pa.version,
                    "current_version": pa.version,
                    "evidence_state": ev_info["evidence_state"],
                    "evidence_name": ev_info["evidence_name"],
                    "source_evidence": ev_info["evidence_name"],
                    "actions": [
                        {
                            "action": "approve_payment_allocation",
                            "label": "Approve Allocation",
                            "allowed": can_a,
                            "blocked_reason": a_reason,
                        }
                    ],
                })
            counts["payment_allocation_approvals"] = len(pay_approvals)
            if pay_approvals:
                sections.append({
                    "id": "payment_allocation_approvals",
                    "section_id": "payment_allocation_approvals",
                    "title": "Payment Allocation Approvals",
                    "count": len(pay_approvals),
                    "items": pay_approvals,
                })

    # 14. Active Exceptions (Scoped through money_company for financial, or linked records for commercial/physical)
    if "Fresko Accounts" in user_roles or "Fresko Approver" in user_roles:
        open_exceptions = frappe.get_list(
            "Fresko Exception",
            filters={
                "status": ["in", ["Open", "In Progress"]],
            },
            fields=["name", "exception_type", "severity", "status", "container", "outward", "sale", "money_company", "money_scope_key", "commercial_scope_key", "description", "modified"],
            order_by="modified desc",
            limit_page_length=limit,
        )
        exception_items = []
        for ex in open_exceptions:
            ex = _row(ex)
            if not frappe.has_permission("Fresko Exception", doc=ex.name, ptype="read"):
                continue

            # Scope to active company
            if ex.money_company:
                if ex.money_company != active_company:
                    continue
            elif ex.sale:
                if not frappe.has_permission("Fresko Commercial Sale", doc=ex.sale, ptype="read"):
                    continue
            elif ex.outward:
                if not frappe.has_permission("Fresko Outward", doc=ex.outward, ptype="read"):
                    continue
            elif ex.container:
                if not frappe.has_permission("Fresko Container", doc=ex.container, ptype="read"):
                    continue

            exception_items.append({
                "kind": "exception",
                "doc_ref": ex.name,
                "document_name": ex.name,
                "human_title": f"Exception: {ex.exception_type}",
                "subtitle": f"Container {ex.container or '—'} • Status: {ex.status}",
                "amount_string": "CONFLICT / PENDING",
                "qty_string": "—",
                "state": ex.status,
                "state_reason": ex.description or f"Operational exception ({ex.exception_type}) requires resolution",
                "container": ex.container,
                "version": None,
                "current_version": None,
                "evidence_state": "NONE",
                "evidence_name": None,
                "actions": [],
            })
        counts["exceptions"] = len(exception_items)
        if exception_items:
            sections.append({
                "id": "exceptions",
                "section_id": "exceptions",
                "title": "Active Exceptions",
                "count": len(exception_items),
                "items": exception_items,
            })

    # FR-QA-015: Separate loaded records, actionable records, blocked tasks, and informational records
    # Unique records counting across all sections:
    seen_records = {}
    for sec in sections:
        for item in sec.get("items", []):
            d_ref = item.get("doc_ref") or item.get("document_name")
            if not d_ref:
                continue
            acts = item.get("actions", [])
            has_act = bool(acts)
            has_allowed = any(bool(a.get("allowed")) for a in acts)
            if d_ref in seen_records:
                seen_records[d_ref]["has_allowed"] = seen_records[d_ref]["has_allowed"] or has_allowed
                seen_records[d_ref]["has_act"] = seen_records[d_ref]["has_act"] or has_act
            else:
                seen_records[d_ref] = {"has_allowed": has_allowed, "has_act": has_act}

    records_loaded = len(seen_records)
    actionable_records = sum(1 for v in seen_records.values() if v["has_allowed"])
    blocked_records = sum(1 for v in seen_records.values() if v["has_act"] and not v["has_allowed"])
    informational_records = sum(1 for v in seen_records.values() if not v["has_act"])
    loaded_items_count = sum(len(sec.get("items", [])) for sec in sections)

    counts["records_loaded"] = records_loaded
    counts["actionable_records"] = actionable_records
    counts["blocked_records"] = blocked_records
    counts["informational_records"] = informational_records
    counts["total_actionable"] = actionable_records

    all_clear = (actionable_records == 0 and not truncated)

    return {
        "feed_type": "operator_action_feed",
        "as_of": now_datetime().isoformat() if callable(now_datetime) else "",
        "company": active_company,
        "projection_mode": "LIVE",
        "counts": counts,
        "records_loaded": records_loaded,
        "actionable_records": actionable_records,
        "blocked_records": blocked_records,
        "informational_records": informational_records,
        "loaded_items_count": loaded_items_count,
        "truncated": truncated,
        "completeness_state": "INCOMPLETE" if truncated else "COMPLETE",
        "all_clear": all_clear,
        "sections": sections,
    }
