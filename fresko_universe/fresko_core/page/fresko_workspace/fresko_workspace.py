"""Fresko Workspace Desk Page Controller and Security Context."""
from __future__ import annotations

import frappe
from frappe import _

ALLOWED_ROLES = {
    "Fresko Salesperson",
    "Fresko Accounts",
    "Fresko Approver",
    "System Manager",
}

INTERNAL_ROLES = {
    "Fresko Accounts",
    "Fresko Approver",
    "System Manager",
}

APPROVER_ROLES = {
    "Fresko Approver",
}

VERIFIER_ROLES = {
    "Fresko Accounts",
}


@frappe.whitelist()
def get_user_workspace_context() -> dict:
    """Return user role permissions for client-side visibility and security checks.

    Enforces that Guest and unauthorized external roles are rejected at the server.
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Authentication required to access Fresko Workspace"), frappe.PermissionError)

    user_roles = set(frappe.get_roles(frappe.session.user))
    if any("supplier" in role.casefold() for role in user_roles):
        frappe.throw(_("Supplier roles cannot access Fresko Workspace"), frappe.PermissionError)
    matched = user_roles & ALLOWED_ROLES
    if not matched:
        frappe.throw(_("Access denied: You do not have permissions for Fresko Workspace"), frappe.PermissionError)

    return {
        "user": frappe.session.user,
        "is_internal": bool(user_roles & INTERNAL_ROLES),
        "can_verify": bool(user_roles & VERIFIER_ROLES),
        "can_approve": bool(user_roles & APPROVER_ROLES),
        "roles": sorted(list(matched)),
    }
