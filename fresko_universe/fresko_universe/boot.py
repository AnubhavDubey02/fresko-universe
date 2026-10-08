"""Fresko Desk Bootinfo Hook & Session Capability Derivation.

Governed by PR #19 Operator UX P0 contract:
- Injected via single extend_bootinfo hook (executes on fresh and cached boots).
- Strict Supplier-First denial precedence.
- Zero financial aggregates or transaction counts in boot data.
- Authoritative command-specific capabilities and deterministic landing routes:
  Precedence: Approver (fresko-workspace) > Accounts (fresko-money) > Salesperson/Trader (fresko-workspace).
"""
from __future__ import annotations

import frappe

# Command-specific capabilities mapped to operational roles
SALESPERSON_CAPABILITIES = frozenset({
    "view_operations",
    "create_sale",
    "supersede_sale",
    "propose_rate",
    "create_outward",
    "submit_outward",
    "propose_sale_outward_allocation",
    "propose_alias",
    "attach_evidence",
    "view_evidence",
})

ACCOUNTS_CAPABILITIES = frozenset({
    "view_operations",
    "verify_sale",
    "verify_rate",
    "verify_sale_outward_allocation",
    "verify_alias",
    "view_money",
    "capture_collection",
    "verify_collection",
    "propose_payment_allocation",
    "verify_payment_allocation",
    "propose_adjustment",
    "verify_adjustment",
    "resolve_exception",
    "attach_evidence",
    "view_evidence",
})

APPROVER_CAPABILITIES = frozenset({
    "view_operations",
    "approve_sale",
    "approve_rate",
    "reject_sale",
    "post_outward",
    "approve_sale_outward_allocation",
    "reject_sale_outward_allocation",
    "reverse_sale_outward_allocation",
    "approve_alias",
    "reject_alias",
    "view_money",
    "approve_collection",
    "reject_collection",
    "approve_payment_allocation",
    "reject_payment_allocation",
    "approve_adjustment",
    "reject_adjustment",
    "resolve_exception",
    "view_audit",
    "attach_evidence",
    "view_evidence",
})


def extend_bootinfo(bootinfo: dict | None = None, **kwargs) -> None:
    """Attach immutable Fresko operator capabilities and persona to Desk session.

    CRITICAL INVARIANTS:
    1. Supplier-First Denial: If user bears any Supplier role, immediate denial.
    2. System Manager: Standard Frappe desk; no implicit business permissions; no operator chrome.
    3. Multi-role Union: Combines command-specific operational capabilities.
    4. Deterministic Route Precedence: Approver > Accounts > Salesperson/Trader.
    5. Zero Financial Data: Never attaches financial aggregates or counts.
    """
    if bootinfo is None:
        bootinfo = kwargs.get("bootinfo")
    if not isinstance(bootinfo, dict):
        return

    session_user = getattr(getattr(frappe, "session", None), "user", None)
    if not session_user or session_user in ("", "Guest"):
        return

    roles_getter = getattr(frappe, "get_roles", None)
    if callable(roles_getter):
        user_roles = set(roles_getter(session_user))
    else:
        user_roles = set()

    # 1. Supplier-First Denial Precedence
    if any("supplier" in r.casefold() for r in user_roles):
        bootinfo["fresko"] = {
            "persona": "supplier_denied",
            "capabilities": [],
            "default_route": None,
            "is_operator": False,
        }
        return

    # 2. System Manager retains standard technical Frappe Desk without operator chrome
    if "System Manager" in user_roles:
        bootinfo["fresko"] = {
            "persona": "system_manager",
            "capabilities": ["admin_desk", "view_audit"],
            "default_route": "Workspaces",
            "is_operator": False,
        }
        return

    # 3. Fresko Operational Roles: Union of command-specific capabilities
    caps = set()
    persona = "non_operator"

    if "Fresko Salesperson" in user_roles or "Fresko Trader" in user_roles:
        caps.update(SALESPERSON_CAPABILITIES)
        persona = "salesperson"

    if "Fresko Accounts" in user_roles:
        caps.update(ACCOUNTS_CAPABILITIES)
        persona = "accounts" if persona == "non_operator" else "multi_role"

    if "Fresko Approver" in user_roles:
        caps.update(APPROVER_CAPABILITIES)
        persona = "approver" if persona in ("non_operator", "salesperson") else "multi_role"

    # Route precedence: Approver (operations) > Accounts (money) > Salesperson/Trader (operations)
    if "Fresko Approver" in user_roles:
        primary_route = "fresko-workspace"
    elif "Fresko Accounts" in user_roles:
        primary_route = "fresko-money"
    elif "Fresko Salesperson" in user_roles or "Fresko Trader" in user_roles:
        primary_route = "fresko-workspace"
    else:
        primary_route = None

    bootinfo["fresko"] = {
        "persona": persona,
        "capabilities": sorted(list(caps)),
        "default_route": primary_route,
        "is_operator": bool(caps),
    }
