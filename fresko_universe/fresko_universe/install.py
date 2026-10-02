import frappe


ROLES = ("Fresko Salesperson", "Fresko Approver", "Fresko Accounts")

# Gate 1 snapshots on Fresko Deal — must distinguish unset from 0.0
_GATE1_NULLABLE_RATE_COLS = ("approved_rate", "rate_floor", "rate_ceiling")


def after_install():
    _ensure_roles()
    _ensure_gate1_nullable_rate_snapshots()
    frappe.clear_cache()


def after_migrate():
    _ensure_roles()
    _ensure_gate1_nullable_rate_snapshots()


def _ensure_roles():
    for role in ROLES:
        if not frappe.db.exists("Role", role):
            doc = frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1})
            doc.insert(ignore_permissions=True)


def _ensure_gate1_nullable_rate_snapshots():
    """Allow SQL NULL on Deal rate snapshot Currency columns (Gate 1).

    Frappe Currency fields sync as NOT NULL DEFAULT 0, which conflates "unset"
    with a literal zero. Gate 1 requires empty policy / unset approved_rate to
    persist as NULL (see deals.apply_rate_rules post-save set_value). Runs after
    DocType sync so the ALTER sticks for this migrate.
    """
    if not frappe.db.table_exists("Fresko Deal"):
        return
    table = "tabFresko Deal"
    for col in _GATE1_NULLABLE_RATE_COLS:
        meta = frappe.db.sql(
            """
            SELECT IS_NULLABLE, COLUMN_TYPE
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
            """,
            (table, col),
            as_dict=True,
        )
        if not meta:
            continue
        if (meta[0].get("IS_NULLABLE") or "").upper() == "YES":
            continue
        col_type = meta[0].get("COLUMN_TYPE") or "decimal(21,9)"
        # Keep existing precision/scale; only drop NOT NULL + default 0.
        frappe.db.sql(
            f"ALTER TABLE `{table}` MODIFY `{col}` {col_type} NULL DEFAULT NULL"
        )
