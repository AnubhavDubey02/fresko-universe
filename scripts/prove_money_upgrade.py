"""Prove money-ledger schema upgrade preservation without creating ledger rows.

The current-main seed is explicitly synthetic legacy state for migration testing.
Its Sale amount and physical source values are preservation sentinels, not
financial acceptance or operating evidence.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import frappe
from frappe.utils import now_datetime

BASELINE_SHA = "b140b800b021c4317931e37a723a140740b2fc4c"
MONEY_DOCTYPES = (
    "Fresko Collection",
    "Fresko Payment Allocation",
    "Fresko Receivable Adjustment",
    "Fresko Adjustment Application",
)
SHARED_FIELDS = {
    "source_payload": "Long Text",
    "payload_sha256": "Data",
    "source_event_key": "Data",
    "decision_history": "Long Text",
    "version": "Int",
}
UNIQUE_FIELDS = {
    doctype: ["source_event_key"] for doctype in MONEY_DOCTYPES
}
UNIQUE_FIELDS["Fresko Collection"].append("active_transaction_key")
STATE = "money_upgrade_seed.json"
FIRST = "money_upgrade_first.json"

LEGACY_COLUMNS = {
    "Fresko Deal": "name,buyer_alias,customer,container,lot_no,qty,dispatched_qty,approved_rate,status",
    "Fresko Container": "name,inward_qty,uom,status",
    "Fresko Container Lot": "name,parent,lot_no,inward_qty,uom",
    "Fresko Commercial Sale": "name,company,container,sale_at,raw_party_alias,party_state,currency,status,source_event_id,source_event_key,payload_sha256,source_payload,decision_history,version,approved_by,approved_at",
    "Fresko Commercial Sale Line": "name,parent,parenttype,parentfield,idx,line_key,item,container_lot,raw_lot_text,lot_state,qty,uom,qty_state,price_state,rate,rate_basis,amount,bucket_key,source_line_ref,evidence",
    "Fresko Party Alias Mapping": "name,company,raw_alias,normalized_alias,normalization_scope,proposed_customer,status,source_event_key,payload_sha256,source_payload,decision_history,version,active_alias_key",
    "Fresko Sale Outward Allocation": "name,company,container,sale,sale_line_key,outward,outward_line_key,qty,uom,evidence,state,source_event_key,payload_sha256,source_payload,decision_history,version,active_allocation_key",
    "Fresko Outward": "name,company,container,movement_type,movement_at,status,source_evidence,source_event_id,source_event_key,payload_sha256,raw_party_name,posted_at,reverses_outward",
    "Fresko Outward Line": "name,parent,parenttype,parentfield,idx,line_key,source_line_ref,raw_lot_text,qty,uom,raw_qty_text,raw_uom_text,raw_rate_text,lot_no,batch",
}


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _path(name):
    return Path(frappe.get_site_path("private", name))


def _write(name, value):
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, default=str) + "\n")


def _read(name):
    return json.loads(_path(name).read_text(encoding="utf-8"))


def _column_names(doctype):
    rows = frappe.db.sql(f"SHOW COLUMNS FROM `tab{doctype}`", as_dict=True)
    return {row["Field"] if isinstance(row, dict) else row.Field for row in rows}


def _legacy_snapshot():
    """Snapshot selected legacy truth, normalizing absent columns to null."""
    result = {}
    for doctype, selected in LEGACY_COLUMNS.items():
        if not frappe.db.table_exists(doctype):
            result[doctype] = []
            continue
        fields = selected.split(",")
        present = _column_names(doctype)
        query_fields = [field for field in fields if field in present]
        if not query_fields:
            result[doctype] = []
            continue
        order = "name" if "name" in query_fields else query_fields[0]
        records = frappe.db.sql(
            f"SELECT {','.join(f'`{field}`' for field in query_fields)} "
            f"FROM `tab{doctype}` ORDER BY `{order}`",
            as_dict=True,
        )
        result[doctype] = [
            {field: (row[field] if field in query_fields else None) for field in fields}
            for row in records
        ]
    return json.loads(json.dumps(result, default=str, sort_keys=True))


def _assert_money_doctypes_absent():
    for doctype in MONEY_DOCTYPES:
        _require(not frappe.db.exists("DocType", doctype), f"Baseline already contains {doctype}")
        _require(not frappe.db.table_exists(doctype), f"Baseline already contains table {doctype}")


def _insert_synthetic_commercial_source(timestamp):
    """Insert distinctive migration sentinels into the disposable baseline."""
    source_payload = {
        "synthetic_migration_fixture": True,
        "source_event_id": "MONEY-UPGRADE-SYNTHETIC-EVENT",
        "raw_party_alias": "  SYNTHETIC / UNRESOLVED  ",
        "lines": [{"line_key": "SYNTHETIC-LINE", "qty": "7", "rate": "111.00", "amount": "777.00"}],
    }
    source_json = json.dumps(source_payload, sort_keys=True, separators=(",", ":"))
    history = [{
        "version": 1,
        "recorded_at": str(timestamp),
        "actor": "Administrator",
        "action": "SYNTHETIC_MIGRATION_SEED",
        "reason": "Test preservation only; not financial acceptance",
        "evidence": "SYNTHETIC-MIGRATION-EVIDENCE",
        "snapshot": {"status": "DRAFT", "version": 1},
    }]
    frappe.db.sql("""INSERT INTO `tabFresko Commercial Sale`
        (name,creation,modified,modified_by,owner,docstatus,idx,naming_series,
         company,container,sale_at,movement_status,raw_party_alias,party_state,
         alias_resolution,currency,status,source_evidence,source_event_id,
         source_event_key,payload_sha256,source_payload,decision_history,version,
         prepared_by,prepared_at,as_of_recorded_at)
        VALUES ('MONEY-UPGRADE-SYNTHETIC-SALE',%s,%s,'Administrator','Administrator',0,0,
         'SALE-.YYYY.-.','MONEY-UPGRADE-SYNTHETIC-COMPANY',
         'MONEY-UPGRADE-SYNTHETIC-CONTAINER',%s,'UNKNOWN',
         '  SYNTHETIC / UNRESOLVED  ','UNKNOWN','UNKNOWN','INR','DRAFT',
         'SYNTHETIC-MIGRATION-EVIDENCE','MONEY-UPGRADE-SYNTHETIC-EVENT',%s,%s,%s,%s,1,
         'Administrator',%s,%s)""",
        (timestamp, timestamp, timestamp, "f" * 64, "1" * 64, source_json,
         json.dumps(history, sort_keys=True), timestamp, timestamp))
    frappe.db.sql("""INSERT INTO `tabFresko Commercial Sale Line`
        (name,creation,modified,modified_by,owner,docstatus,idx,parent,parenttype,
         parentfield,line_key,item,raw_lot_text,lot_state,qty,uom,qty_state,
         price_state,rate,rate_basis,amount,bucket_key,source_line_ref,evidence)
        VALUES ('MONEY-UPGRADE-SYNTHETIC-LINE',%s,%s,'Administrator','Administrator',0,1,
         'MONEY-UPGRADE-SYNTHETIC-SALE','Fresko Commercial Sale','lines',
         'SYNTHETIC-LINE','SYNTHETIC-ITEM','SYNTHETIC-LOT','UNKNOWN','7','Crate',
         'KNOWN','PROPOSED','111.00','RATE_ASSERTION','777.00',NULL,
         'SYNTHETIC-SOURCE-LINE','SYNTHETIC-MIGRATION-EVIDENCE')""", (timestamp, timestamp))


def _insert_synthetic_physical_source(timestamp):
    """Preserve physical source columns using the existing outward seed shape."""
    frappe.db.sql("""INSERT INTO `tabFresko Outward`
        (name,creation,modified,modified_by,owner,docstatus,idx,naming_series,
         company,container,movement_type,movement_at,source_evidence,
         source_event_id,source_event_key,payload_sha256,status,raw_party_name,
         prepared_by,prepared_at)
        VALUES ('MONEY-UPGRADE-SYNTHETIC-OUTWARD',%s,%s,'Administrator','Administrator',0,0,
         'OUT-.YYYY.-.','MONEY-UPGRADE-SYNTHETIC-COMPANY',
         'MONEY-UPGRADE-SYNTHETIC-CONTAINER','OUTWARD',%s,
         'SYNTHETIC-MIGRATION-EVIDENCE','MONEY-UPGRADE-PHYSICAL-EVENT',%s,%s,
         'Posted','  SYNTHETIC PHYSICAL PARTY  ','Administrator',%s)""",
        (timestamp, timestamp, timestamp, "2" * 64, "3" * 64, timestamp))
    frappe.db.sql("""INSERT INTO `tabFresko Outward Line`
        (name,creation,modified,modified_by,owner,docstatus,idx,parent,parenttype,
         parentfield,line_key,source_line_ref,raw_lot_text,qty,uom,
         raw_qty_text,raw_uom_text,raw_rate_text)
        VALUES ('MONEY-UPGRADE-SYNTHETIC-OUTWARD-LINE',%s,%s,'Administrator','Administrator',0,1,
         'MONEY-UPGRADE-SYNTHETIC-OUTWARD','Fresko Outward','lines',
         'SYNTHETIC-PHYSICAL-LINE','SYNTHETIC-PHYSICAL-ROW','SYNTHETIC-LOT',7,
         'Crate','7','Crate','SYNTHETIC-RATE-TEXT')""", (timestamp, timestamp))


def seed_phase1():
    """Reuse prior registered Phase 1 seeds; do not add legacy fixture rows."""
    _assert_money_doctypes_absent()
    _write(STATE, {"baseline": "phase1", "legacy": _legacy_snapshot()})
    frappe.db.commit()
    print("Money migration seed: reused existing Phase 1 fixtures; added no legacy rows")


def seed_current_main():
    """Seed synthetic commercial/physical sentinels on exact merged-main baseline."""
    _assert_money_doctypes_absent()
    for table, name in (
        ("Fresko Commercial Sale", "MONEY-UPGRADE-SYNTHETIC-SALE"),
        ("Fresko Outward", "MONEY-UPGRADE-SYNTHETIC-OUTWARD"),
    ):
        _require(not frappe.db.exists(table, name), f"Synthetic baseline record already exists: {name}")
    timestamp = now_datetime()
    _insert_synthetic_commercial_source(timestamp)
    _insert_synthetic_physical_source(timestamp)
    snapshot = _legacy_snapshot()
    _write(STATE, {"baseline": BASELINE_SHA, "legacy": snapshot})
    frappe.db.commit()
    print("Money migration seed: captured synthetic commercial and physical source sentinels only")


def _verify():
    seed = _read(STATE)
    current = _legacy_snapshot()
    _require(current == seed["legacy"], "Migration changed selected legacy commercial/physical state")
    counts = {}
    for doctype in MONEY_DOCTYPES:
        _require(frappe.db.exists("DocType", doctype), f"Missing migrated {doctype}")
        _require(frappe.db.table_exists(doctype), f"Missing migrated table {doctype}")
        frappe.clear_cache(doctype=doctype)
        meta = frappe.get_meta(doctype, cached=False)
        expected_fields = dict(SHARED_FIELDS)
        if doctype == "Fresko Collection":
            expected_fields["active_transaction_key"] = "Data"
        for fieldname, fieldtype in expected_fields.items():
            field = meta.get_field(fieldname)
            _require(field and field.fieldtype == fieldtype, f"Wrong {doctype}.{fieldname} schema")
        count = frappe.db.count(doctype)
        _require(count == 0, f"Migration fabricated {doctype}: {count} rows")
        counts[doctype] = count
        indexes = frappe.db.sql(f"SHOW INDEX FROM `tab{doctype}`", as_dict=True)
        for fieldname in UNIQUE_FIELDS[doctype]:
            _require(
                any(row.Column_name == fieldname and not int(row.Non_unique) for row in indexes),
                f"Missing unique index {doctype}.{fieldname}",
            )
    return {"baseline": seed["baseline"], "legacy": current, "money_counts": counts}


def verify_first_migrate():
    _write(FIRST, _verify())
    print("Money first migration: legacy commercial/physical snapshots unchanged; four ledgers empty")


def verify_second_migrate():
    _require(_verify() == _read(FIRST), "Money second migration is not idempotent")
    print("Money second migration: identical snapshot and empty money ledgers")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True)
    parser.add_argument("stage", choices=("seed_phase1", "seed_current_main", "verify_first_migrate", "verify_second_migrate"))
    args = parser.parse_args()
    cwd = Path.cwd()
    sites = cwd / "sites"
    os.chdir(sites)
    frappe.init(site=args.site, sites_path=".")
    frappe.connect()
    try:
        globals()[args.stage]()
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise
    finally:
        frappe.destroy()
        os.chdir(cwd)


if __name__ == "__main__":
    main()
