"""Authenticated Frappe boundary for v0.3 read proposals (not native-tested).

Only question and explicitly untrusted source are callable inputs; session roles
and Company User Permissions are re-read on every dispatch. This never performs
ledger writes. Await native signed-in validation before enabling in production.
"""
from __future__ import annotations

import frappe
from fresko_universe import ask_fresko, ask_fresko_router_v03

_RECORD_TOOLS = {
    'container_reconciliation': ('Fresko Container', 'container'),
    'container_receivable': ('Fresko Container', 'container'),
    'sale_as_of': ('Fresko Commercial Sale', 'sale_name'),
    'sale_receivable': ('Fresko Commercial Sale', 'sale'),
    'outward_reconciliation': ('Fresko Outward', 'outward_name'),
    'collection_position': ('Fresko Collection', 'name'),
    'customer_receivable': ('Customer', 'customer'),
}
_ALLOWED_ROLES = {'Fresko Salesperson', 'Fresko Accounts', 'Fresko Approver'}


def _deny():
    # Deliberately no entity ID, tenant or existence signal in errors.
    frappe.throw('Ask Fresko authorization unavailable', frappe.PermissionError)


def _session_scope():
    user = getattr(getattr(frappe, 'session', None), 'user', None)
    if not user or user == 'Guest':
        _deny()
    # Read the User row and role children afresh; get_roles can use cached
    # permissions after a revocation while an authenticated session survives.
    try:
        account = frappe.get_doc('User', user)
    except frappe.DoesNotExistError:
        _deny()
    if not account.enabled:
        _deny()
    roles = {row.role for row in account.roles}
    if any('supplier' in r.casefold() for r in roles) or not roles & _ALLOWED_ROLES:
        _deny()
    tenants = set(frappe.get_all('User Permission', filters={'user': user, 'allow': 'Company'}, pluck='for_value'))
    if len(tenants) != 1:
        _deny()
    return roles, next(iter(tenants))


def _resolve_record(tool, arguments, company):
    spec = _RECORD_TOOLS.get(tool)
    if not spec:
        return arguments
    doctype, arg = spec
    identifier = arguments[arg]
    try:
        if doctype == 'Fresko Container':
            # Shipping IDs can be container_no rather than DocType name.
            rows = frappe.get_all(doctype, filters={'company': company, 'container_no': identifier},
                                  fields=['name'], limit_page_length=2)
            if len(rows) == 1:
                document = frappe.get_doc(doctype, rows[0].name)
            elif not rows:
                # Internal synthetic/legacy aliases may already be docnames.
                document = frappe.get_doc(doctype, identifier)
            else:
                _deny()
        else:
            document = frappe.get_doc(doctype, identifier)
    except frappe.DoesNotExistError:
        _deny()
    if not frappe.has_permission(doctype, ptype='read', doc=document, user=frappe.session.user):
        _deny()
    if doctype != 'Customer' and getattr(document, 'company', None) != company:
        _deny()
    result = dict(arguments)
    result[arg] = document.name
    return result


@frappe.whitelist()
def ask(question: str, untrusted_source: str | None = None):
    """Authenticates on the server; no caller-provided roles or tenant accepted.

    All ID resolution is exact, has row ACL, and rejects ambiguous lookup. The
    canonical domain read APIs still enforce their own roles/record permissions.
    """
    roles, company = _session_scope()
    def _tools():
        fresh_roles, fresh_company = _session_scope()
        if fresh_company != company or fresh_roles != roles:
            _deny()
        return ask_fresko.list_tools()
    def _run(tool, arguments):
        fresh_roles, fresh_company = _session_scope()
        if fresh_company != company or fresh_roles != roles:
            _deny()
        current_catalog = {x['name'] for x in ask_fresko.list_tools()}
        if tool not in current_catalog:
            _deny()
        safe_args = _resolve_record(tool, dict(arguments), company)
        if safe_args.get('company', company) != company:
            _deny()
        return ask_fresko.run_tool(tool, safe_args)
    return ask_fresko_router_v03.authorized_dispatch(
        question,server_roles=sorted(roles),server_company=company,
        server_list_tools=_tools,server_run_tool=_run,untrusted_source=untrusted_source)
