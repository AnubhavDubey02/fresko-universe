import frappe


ROLES = ("Fresko Salesperson", "Fresko Approver", "Fresko Accounts")

# Gate 1 snapshots on Fresko Deal — must distinguish unset from 0.0
_GATE1_NULLABLE_RATE_COLS = ("approved_rate", "rate_floor", "rate_ceiling")


def after_install():
    _ensure_roles()
    _ensure_gate1_nullable_rate_snapshots()
    _ensure_commercial_indexes()
    _ensure_commercial_master_reads()
    _ensure_money_master_reads()
    frappe.clear_cache()


def after_migrate():
    _ensure_roles()
    _ensure_gate1_nullable_rate_snapshots()
    _ensure_commercial_indexes()
    _ensure_commercial_master_reads()
    _ensure_money_master_reads()


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


def _ensure_commercial_indexes():
    """DDL only after synchronization; never infer or backfill commercial rows."""
    indexes = {
        "Fresko Commercial Sale": [("container", "sale_at"), ("alias_mapping", "sale_at"), ("customer", "sale_at"), ("status", "sale_at"), ("source_evidence",)],
        "Fresko Commercial Sale Line": [("parent", "line_key"), ("parent", "bucket_key"), ("container_lot", "price_state"), ("price_state", "source_line_ref")],
        "Fresko Party Alias Mapping": [("company", "normalized_alias", "status")],
        "Fresko Sale Outward Allocation": [("sale", "state"), ("outward", "state")],
    }
    for doctype, definitions in indexes.items():
        if not frappe.db.table_exists(doctype):
            continue
        for columns in definitions:
            frappe.db.add_index(doctype, list(columns), index_name="commercial_" + "_".join(columns))
    # Child identity uniqueness is parent scoped, and NULL buckets remain unknown.
    if frappe.db.table_exists("Fresko Commercial Sale Line"):
        frappe.db.add_unique("Fresko Commercial Sale Line", ["parent", "line_key"], constraint_name="commercial_line_identity")
        frappe.db.add_unique("Fresko Commercial Sale Line", ["parent", "bucket_key"], constraint_name="commercial_bucket_identity")


def _ensure_commercial_master_reads():
    """Grant only master reads needed by authenticated commercial actors.

    Frappe's supported helper preserves upstream permissions when creating
    Custom DocPerm rows. Existing operator-managed rules are left intact.
    Linked-document and user/company permissions are still checked at runtime.
    """
    from frappe.permissions import add_permission

    for doctype in ("Company", "Customer", "Currency", "Item", "UOM", "Batch"):
        if not frappe.db.exists("DocType", doctype):
            continue
        for role in ROLES:
            if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}):
                add_permission(doctype, role, ptype="read")


def _ensure_money_master_reads():
    """Financial actors need bank master reads; business permissions remain checked."""
    from frappe.permissions import add_permission
    for doctype in ("Bank Account", "User"):
        if not frappe.db.exists("DocType", doctype):
            continue
        for role in ("Fresko Accounts", "Fresko Approver"):
            if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}):
                add_permission(doctype, role, ptype="read")
