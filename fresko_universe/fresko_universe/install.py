import frappe


ROLES = ("Fresko Salesperson", "Fresko Approver", "Fresko Accounts")


def after_install():
    _ensure_roles()
    frappe.clear_cache()


def after_migrate():
    _ensure_roles()


def _ensure_roles():
    for role in ROLES:
        if not frappe.db.exists("Role", role):
            doc = frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1})
            doc.insert(ignore_permissions=True)
