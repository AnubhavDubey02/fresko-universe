"""Server-side ACL for Fresko whitelist methods and DocType permission hooks.

FSEC-001 / FSEC-002 / FSEC-003 — role + ownership gates are the source of truth for
sensitive mutators. DocType Role Permission Manager is coarse; whitelist paths must
not rely on it alone (especially where ignore_permissions is required after checks).
"""

from __future__ import annotations

import frappe
from frappe import _

ROLE_SALESPERSON = "Fresko Salesperson"
ROLE_APPROVER = "Fresko Approver"
ROLE_ACCOUNTS = "Fresko Accounts"
ROLE_SYSTEM_MANAGER = "System Manager"

FRESKO_ROLES = frozenset({ROLE_SALESPERSON, ROLE_APPROVER, ROLE_ACCOUNTS})

# Phase 1 revision apply has no oversell path: ATS always fails closed.
APPROVAL_APPLY_DECISIONS = frozenset({"APPROVE"})


def current_roles(user: str | None = None) -> set[str]:
    return set(frappe.get_roles(user or frappe.session.user))


def is_system_manager(roles: set[str] | None = None) -> bool:
    return ROLE_SYSTEM_MANAGER in (roles or current_roles())


def is_approver(roles: set[str] | None = None) -> bool:
    roles = roles or current_roles()
    return ROLE_APPROVER in roles or is_system_manager(roles)


def is_deal_owner_or_salesperson(deal, user: str | None = None) -> bool:
    """Match D4 ownership surface: owner or assigned salesperson_user."""
    user = user or frappe.session.user
    if getattr(deal, "owner", None) == user:
        return True
    sp = getattr(deal, "salesperson_user", None)
    if sp and sp == user:
        return True
    return False


def _throw_denied(action: str, detail: str | None = None) -> None:
    msg = _("Not permitted to {0}").format(action)
    if detail:
        msg = f"{msg}: {detail}"
    frappe.throw(msg, frappe.PermissionError)


def assert_can_apply_rate_rules(deal) -> None:
    """Salesperson on own deal, Approver, or System Manager. Accounts denied."""
    roles = current_roles()
    if is_system_manager(roles) or ROLE_APPROVER in roles:
        return
    if ROLE_SALESPERSON in roles and is_deal_owner_or_salesperson(deal):
        return
    _throw_denied(
        "apply_rate_rules",
        _("requires deal owner/salesperson, Fresko Approver, or System Manager"),
    )


def assert_can_cancel_deal(deal) -> None:
    """Owner/salesperson, Approver, or System Manager. Accounts-only denied."""
    roles = current_roles()
    if is_system_manager(roles) or ROLE_APPROVER in roles:
        return
    if ROLE_SALESPERSON in roles and is_deal_owner_or_salesperson(deal):
        return
    _throw_denied(
        "cancel_deal",
        _("requires deal owner/salesperson, Fresko Approver, or System Manager"),
    )


def assert_can_record_dispatch(_deal=None) -> None:
    """Physical dispatch is ops: Approver or System Manager only (not Accounts/Salesperson)."""
    roles = current_roles()
    if is_system_manager(roles) or ROLE_APPROVER in roles:
        return
    _throw_denied(
        "record_dispatch",
        _("requires Fresko Approver or System Manager"),
    )


def assert_can_request_revision(deal) -> None:
    """Owner/salesperson, Approver, or System Manager. Accounts-only denied."""
    roles = current_roles()
    if is_system_manager(roles) or ROLE_APPROVER in roles:
        return
    if ROLE_SALESPERSON in roles and is_deal_owner_or_salesperson(deal):
        return
    _throw_denied(
        "request_revision",
        _("requires deal owner/salesperson, Fresko Approver, or System Manager"),
    )


def assert_can_apply_revision() -> None:
    """FSEC-002: only Fresko Approver or System Manager may apply a revision."""
    if is_approver():
        return
    _throw_denied(
        "apply_revision",
        _("requires Fresko Approver or System Manager"),
    )


def assert_can_create_revision_approval() -> None:
    """Only Fresko Approver or System Manager may mint revision-bound Approvals."""
    if is_approver():
        return
    _throw_denied(
        "create_revision_approval",
        _("requires Fresko Approver or System Manager"),
    )


def assert_approval_bound_for_revision(approval, deal, revision=None) -> None:
    """FSEC-002 + blocker 2: Approval must bind deal + revision + allowlisted decision."""
    approval_deal = getattr(approval, "deal", None)
    if str(approval_deal or "") != str(deal.name or ""):
        frappe.throw(
            _("Fresko Approval {0} is bound to deal {1}, not {2}").format(
                approval.name, approval_deal, deal.name
            ),
            frappe.PermissionError,
        )
    decision = (getattr(approval, "decision", None) or "").upper().strip()
    if decision not in APPROVAL_APPLY_DECISIONS:
        frappe.throw(
            _(
                "Fresko Approval {0} decision {1} cannot apply a material revision "
                "(need APPROVE)"
            ).format(approval.name, decision or "(empty)"),
            frappe.PermissionError,
        )
    if revision is not None:
        approval_revision = getattr(approval, "revision", None)
        if not approval_revision:
            frappe.throw(
                _(
                    "Fresko Approval {0} is Deal-only (no revision bind); "
                    "material apply_revision requires approvals.create_revision_approval"
                ).format(approval.name),
                frappe.PermissionError,
            )
        if str(approval_revision) != str(revision.name):
            frappe.throw(
                _("Fresko Approval {0} is bound to revision {1}, not {2}").format(
                    approval.name, approval_revision, revision.name
                ),
                frappe.PermissionError,
            )


def assert_approval_not_consumed(approval) -> None:
    """Reject Approvals already consumed by a successful apply_revision."""
    if int(getattr(approval, "consumed", 0) or 0):
        frappe.throw(
            _("Fresko Approval {0} already consumed (replay blocked)").format(approval.name),
            frappe.PermissionError,
        )


def assert_approval_not_stale(approval, revision_name: str) -> None:
    """Reject Approvals already consumed by a different Applied revision."""
    if int(getattr(approval, "consumed", 0) or 0):
        frappe.throw(
            _("Fresko Approval {0} already consumed (stale)").format(approval.name),
            frappe.PermissionError,
        )
    used = frappe.get_all(
        "Fresko Revision",
        filters={
            "approval_reference": approval.name,
            "status": "Applied",
            "name": ("!=", revision_name),
        },
        limit=1,
        pluck="name",
    )
    if used:
        frappe.throw(
            _("Fresko Approval {0} already applied on revision {1} (stale)").format(
                approval.name, used[0]
            ),
            frappe.PermissionError,
        )


def assert_can_read_ats_snapshot() -> None:
    """ATS snapshot: any Fresko role or System Manager (authenticated Desk)."""
    roles = current_roles()
    if is_system_manager(roles) or (roles & FRESKO_ROLES):
        return
    _throw_denied("container snapshot", _("requires a Fresko role or System Manager"))


# --- DocType hooks (FSEC-003) -------------------------------------------------


def deal_permission_query(user: str | None = None) -> str:
    """Row filter: Salesperson sees own / assigned deals; others unrestricted by this hook."""
    user = user or frappe.session.user
    if user == "Administrator" or is_system_manager(current_roles(user)):
        return ""
    roles = current_roles(user)
    if ROLE_APPROVER in roles or ROLE_ACCOUNTS in roles:
        return ""
    if ROLE_SALESPERSON in roles:
        user_esc = frappe.db.escape(user)
        return (
            f"(`tabFresko Deal`.owner = {user_esc} "
            f"OR IFNULL(`tabFresko Deal`.salesperson_user, '') = {user_esc})"
        )
    # No Fresko role: deny list via impossible predicate (Desk still respects DocType JSON)
    return "1=0"


def deal_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
    """
    Align Desk access with D4 / COMMERCIAL_LOCK / DOCTYPE v1:
    - Accounts: read only (never write, including Cancelled/Rejected/Disputed)
    - Salesperson: create; read/write only on own (owner|salesperson_user); write only while Proposed
    - Approver: Desk write only while Proposed (post-Proposed via whitelist + flags)
    - System Manager: unrestricted
    Locked statuses (COMMERCIAL_LOCK including Cancelled/Rejected/Disputed): non-SM Desk write denied.
    """
    user = user or frappe.session.user
    ptype = ptype or "read"
    if user == "Administrator":
        return True

    roles = current_roles(user)
    if is_system_manager(roles):
        return True

    if ROLE_ACCOUNTS in roles and ROLE_APPROVER not in roles and ROLE_SALESPERSON not in roles:
        return ptype == "read"

    if ROLE_APPROVER in roles:
        if ptype == "delete":
            return False
        if ptype == "write":
            # Blocker 1: no free Desk write of commercial fields once past Proposed;
            # whitelist + allow_commercial_revision / allow_approval_write is the SoR.
            status = _deal_status(doc)
            if status and status != "Proposed":
                return False
            return True
        return ptype in {"read", "create", "print", "email", "report", "export", "share"}

    if ROLE_SALESPERSON in roles:
        if ptype == "create":
            return True
        if ptype == "delete":
            return False
        if ptype in {"print", "email", "report", "export", "share"}:
            return _deal_is_assigned(doc, user)
        if ptype == "read":
            return _deal_is_assigned(doc, user)
        if ptype == "write":
            if not _deal_is_assigned(doc, user):
                return False
            status = _deal_status(doc)
            # Desk coarse-write only while Proposed; Cancelled/Rejected/Disputed/Approved/… denied
            if status and status != "Proposed":
                return False
            return True
        return False

    return False


def _deal_is_assigned(doc, user: str) -> bool:
    if doc is None:
        return False
    if isinstance(doc, str):
        row = frappe.db.get_value(
            "Fresko Deal",
            doc,
            ["owner", "salesperson_user"],
            as_dict=True,
        )
        if not row:
            return False
        return row.owner == user or (row.salesperson_user and row.salesperson_user == user)
    return is_deal_owner_or_salesperson(doc, user)


def _deal_status(doc) -> str | None:
    if doc is None:
        return None
    if isinstance(doc, str):
        return frappe.db.get_value("Fresko Deal", doc, "status")
    return getattr(doc, "status", None) or (doc.get("status") if hasattr(doc, "get") else None)


def evidence_permission_query(user: str | None = None) -> str:
    """Salesperson: evidence linked to own deals; Approver/Accounts/SM: unrestricted."""
    user = user or frappe.session.user
    if user == "Administrator" or is_system_manager(current_roles(user)):
        return ""
    roles = current_roles(user)
    if ROLE_APPROVER in roles or ROLE_ACCOUNTS in roles:
        return ""
    if ROLE_SALESPERSON in roles:
        user_esc = frappe.db.escape(user)
        return (
            "(`tabFresko Evidence`.deal IS NULL OR `tabFresko Evidence`.deal IN ("
            f"SELECT name FROM `tabFresko Deal` WHERE owner = {user_esc} "
            f"OR IFNULL(salesperson_user, '') = {user_esc})"
            ")"
        )
    return "1=0"


def evidence_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
    user = user or frappe.session.user
    ptype = ptype or "read"
    if user == "Administrator" or is_system_manager(current_roles(user)):
        return True
    roles = current_roles(user)
    if ROLE_ACCOUNTS in roles and ROLE_APPROVER not in roles and ROLE_SALESPERSON not in roles:
        return ptype == "read"
    if ROLE_APPROVER in roles:
        return ptype != "delete"
    if ROLE_SALESPERSON in roles:
        if ptype == "delete":
            return False
        deal_name = None
        if isinstance(doc, str):
            deal_name = frappe.db.get_value("Fresko Evidence", doc, "deal")
        elif doc is not None:
            deal_name = getattr(doc, "deal", None) or (doc.get("deal") if hasattr(doc, "get") else None)
        if not deal_name:
            # Creating evidence without deal yet / container-level notes: allow create/read
            return ptype in {"read", "create", "write", "print", "report", "export"}
        return _deal_is_assigned(deal_name, user)
    return False
