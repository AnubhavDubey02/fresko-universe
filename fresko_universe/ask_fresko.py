"""Deterministic, read-only tool boundary for asking about Fresko records."""

import frappe
from fresko_universe import commercial, money


_COMMERCIAL = {
    "container_reconciliation": (commercial.get_container_reconciliation, ("container",), ("as_of",)),
    "sale_as_of": (commercial.get_sale_as_of, ("sale_name", "as_of"), ()),
    "outward_reconciliation": (commercial.get_outward_reconciliation, ("outward_name",), ("as_of",)),
}
_MONEY = {
    "sale_receivable": (money.get_sale_receivable, ("sale",), ("as_of",)),
    "container_receivable": (money.get_container_receivable, ("container",), ("as_of",)),
    "customer_receivable": (money.get_customer_receivable, ("customer", "company"), ("as_of",)),
    "unallocated_collections": (money.get_unallocated_collections, ("company",), ("as_of",)),
    "bank_pending_collections": (money.get_bank_pending_collections, ("company",), ("as_of",)),
    "open_money_exceptions": (money.get_open_money_exceptions, ("company",), ()),
    "collection_position": (money.get_collection_position, ("name",), ("as_of",)),
}
_COMMERCIAL_ROLES = {"Fresko Salesperson", "Fresko Accounts", "Fresko Approver", "System Manager"}
_MONEY_ROLES = {"Fresko Accounts", "Fresko Approver"}


def _roles():
    user = getattr(getattr(frappe, "session", None), "user", None)
    roles = set(frappe.get_roles(user)) if user else set()
    if not user or user == "Guest" or any("supplier" in role.casefold() for role in roles):
        raise frappe.PermissionError("Access to this read-only assistant is denied")
    return roles


def _catalog(group):
    return [
        {"name": name, "required": list(required), "optional": list(optional)}
        for name, (_, required, optional) in group.items()
    ]


def list_tools():
    """Return only tools available to the current internal role."""
    roles = _roles()
    if not roles & _COMMERCIAL_ROLES:
        raise frappe.PermissionError("Access to this read-only assistant is denied")
    tools = _catalog(_COMMERCIAL)
    if roles & _MONEY_ROLES:
        tools.extend(_catalog(_MONEY))
    return tools


def run_tool(tool_name, arguments):
    """Validate a fixed tool name and argument set, then call its read API."""
    roles = _roles()
    if not roles & _COMMERCIAL_ROLES:
        raise frappe.PermissionError("Access to this read-only assistant is denied")
    if not isinstance(tool_name, str):
        raise frappe.ValidationError("Unknown read-only tool")
    if tool_name in _COMMERCIAL:
        function, required, optional = _COMMERCIAL[tool_name]
    elif tool_name in _MONEY:
        if not roles & _MONEY_ROLES:
            raise frappe.PermissionError("Money read tools require Fresko Accounts or Fresko Approver")
        function, required, optional = _MONEY[tool_name]
    else:
        raise frappe.ValidationError("Unknown read-only tool")
    if not isinstance(arguments, dict):
        raise frappe.ValidationError("Tool arguments must be an object")
    keys = set(arguments)
    allowed = set(required) | set(optional)
    if keys - allowed or set(required) - keys:
        raise frappe.ValidationError("Invalid tool arguments")
    return function(**arguments)
