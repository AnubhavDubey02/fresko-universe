"""Seeded Phase 1 and exact pre-commercial-main upgrade/rerun proofs.

Synthetic legacy records remain legacy records: migration creates no sale,
alias, allocation, Customer mapping, or price from them.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import frappe
from frappe.utils import now_datetime

BASELINE_SHA = "579a8465f363105eb6e78c15cb173156e2c0df93"
DOCTYPES = {
    "Fresko Commercial Sale": { "source_event_key": "Data", "payload_sha256": "Data", "source_payload": "Long Text", "decision_history": "Long Text", "lines": "Table", "customer": "Link", "version": "Int"},
    "Fresko Commercial Sale Line": {"qty": "Data", "rate": "Data", "amount": "Data", "line_key": "Data", "container_lot": "Link"},
    "Fresko Party Alias Mapping": {"raw_alias": "Data", "proposed_customer": "Link", "source_event_key": "Data", "active_alias_key": "Data", "source_payload": "Long Text", "decision_history": "Long Text", "version": "Int"},
    "Fresko Sale Outward Allocation": {"qty": "Data", "sale": "Link", "outward": "Link", "source_event_key": "Data", "active_allocation_key": "Data", "source_payload": "Long Text", "decision_history": "Long Text", "version": "Int"},
}
STATE = "commercial_upgrade_seed.json"
FIRST = "commercial_upgrade_first.json"


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
    return json.loads(_path(name).read_text())


def _legacy_snapshot():
    """Compare all pre-commercial columns, including physical child rows."""
    columns = {
        "Fresko Deal": "name,buyer_alias,customer,container,lot_no,qty,dispatched_qty,approved_rate,status",
        "Fresko Container": "name,inward_qty,uom,status",
        "Fresko Container Lot": "name,parent,lot_no,inward_qty,uom",
        "Fresko Exception": "name,exception_type,status,description,container,deal",
    }
    if frappe.db.table_exists("Fresko Outward"):
        columns["Fresko Outward"] = "name,company,container,status,movement_type,movement_at,source_evidence,source_event_id,source_event_key,payload_sha256,raw_party_name"
        columns["Fresko Outward Line"] = "name,parent,line_key,qty,uom,raw_lot_text,lot_no,raw_rate_text"
    rows = {
        dt: [dict(r) for r in frappe.db.sql(f"SELECT {cols} FROM `tab{dt}` ORDER BY name", as_dict=True)]
        for dt, cols in columns.items()
    }
    # Normalize DB driver datetimes/Decimals identically on every comparison.
    return json.loads(json.dumps(rows, default=str, sort_keys=True))


def _seed(existing_main=False):
    for dt in DOCTYPES:
        _require(not frappe.db.exists("DocType", dt), f"Baseline already contains {dt}")
        _require(not frappe.db.table_exists(dt), f"Baseline already contains table {dt}")
    timestamp = now_datetime()
    # Earlier registered proofs own their legacy Deal count. Reuse that seed
    # on Phase 1; the independent main site receives its own unresolved row.
    if existing_main:
        frappe.db.sql("""INSERT INTO `tabFresko Deal`
            (name,creation,modified,modified_by,owner,docstatus,idx,naming_series,
             company,container,buyer_alias,item,lot_no,qty,uom,dispatched_qty,
             proposed_rate,approved_rate,currency,status,approval_required)
            VALUES ('COMMERCIAL-UPGRADE-LEGACY-DEAL',%s,%s,'Administrator','Administrator',0,0,
             'DEAL-.YYYY.-.','COMMERCIAL-UPGRADE-COMPANY','COMMERCIAL-UPGRADE-CONTAINER',
             '  RAW / UNRESOLVED  ','COMMERCIAL-UPGRADE-ITEM','RAW / LOT',10,'Crate',3.25,
             0,NULL,'INR','Partially Dispatched',0)""", (timestamp, timestamp))
    if existing_main:
        _require(frappe.db.table_exists("Fresko Outward"), "Current-main physical schema absent")
        # Synthetic unresolved physical source, deliberately no commercial record.
        frappe.db.sql("""INSERT INTO `tabFresko Outward`
            (name,creation,modified,modified_by,owner,docstatus,idx,naming_series,
             company,container,movement_type,movement_at,source_evidence,
             source_event_id,source_event_key,payload_sha256,status,raw_party_name,
             prepared_by,prepared_at)
            VALUES ('COMMERCIAL-UPGRADE-OUTWARD',%s,%s,'Administrator','Administrator',0,0,
             'OUT-.YYYY.-.','COMMERCIAL-UPGRADE-COMPANY','COMMERCIAL-UPGRADE-CONTAINER',
             'OUTWARD',%s,'COMMERCIAL-UPGRADE-EVIDENCE','RAW / EVENT',%s,%s,'Posted',
             '  RAW / UNRESOLVED  ','Administrator',%s)""",
            (timestamp, timestamp, timestamp, "c" * 64, "d" * 64, timestamp))
        frappe.db.sql("""INSERT INTO `tabFresko Outward Line`
            (name,creation,modified,modified_by,owner,docstatus,idx,parent,parenttype,
             parentfield,line_key,source_line_ref,raw_lot_text,qty,uom,
             raw_qty_text,raw_uom_text,raw_rate_text)
            VALUES ('COMMERCIAL-UPGRADE-OUTWARD-LINE',%s,%s,'Administrator','Administrator',0,1,
             'COMMERCIAL-UPGRADE-OUTWARD','Fresko Outward','lines',%s,'RAW / ROW',
             'LOT / UNMAPPED',7,'Crate','7','Crate',NULL)""",
            (timestamp, timestamp, "e" * 64))
    _require(frappe.db.count("Fresko Deal") > 0, "Legacy Deal fixture is missing")
    snapshot = _legacy_snapshot()
    _write(STATE, {"baseline": BASELINE_SHA if existing_main else "phase1", "legacy": snapshot})
    frappe.db.commit()
    print("Commercial migration seed: legacy raw alias and dispatched truth preserved; no mapped buyer")


def seed_phase1():
    _seed()


def seed_current_main():
    _seed(existing_main=True)


def _snapshot():
    seed = _read(STATE)
    current = _legacy_snapshot()
    # Phase 1 did not have Outward tables; new empty tables are expected.
    for dt, rows in seed["legacy"].items():
        _require(current[dt] == rows, f"Migration changed legacy {dt}")
    counts = {}
    for dt, fields in DOCTYPES.items():
        _require(frappe.db.exists("DocType", dt), f"Missing migrated {dt}")
        _require(frappe.db.table_exists(dt), f"Missing table {dt}")
        frappe.clear_cache(doctype=dt)
        meta = frappe.get_meta(dt, cached=False)
        for fieldname, kind in fields.items():
            if kind is None:
                continue
            field = meta.get_field(fieldname)
            _require(field and field.fieldtype == kind, f"Wrong {dt}.{fieldname} schema")
        count = frappe.db.count(dt)
        _require(count == 0, f"Migration fabricated {dt}: {count} rows")
        counts[dt] = count
    for dt, fieldnames in {
        "Fresko Commercial Sale": ("source_event_key",),
        "Fresko Party Alias Mapping": ("source_event_key", "active_alias_key"),
        "Fresko Sale Outward Allocation": ("source_event_key", "active_allocation_key"),
        "Fresko Exception": ("commercial_scope_key",),
    }.items():
        indexes = frappe.db.sql(f"SHOW INDEX FROM `tab{dt}`", as_dict=True)
        for name in fieldnames:
            _require(any(r.Column_name == name and not int(r.Non_unique) for r in indexes), f"Missing unique index {dt}.{name}")
    unknowns = frappe.db.sql("""SELECT COUNT(*) FROM `tabFresko Exception`
        WHERE sale IS NOT NULL OR commercial_scope_key IS NOT NULL OR as_of_recorded_at IS NOT NULL""")[0][0]
    _require(unknowns == 0, "Migration fabricated commercial Exception scope")
    return {"baseline": seed["baseline"], "legacy": current, "commercial_counts": counts}


def verify_first_migrate():
    _write(FIRST, _snapshot())
    print("Commercial first migration: unchanged legacy truth and zero commercial rows")


def verify_second_migrate():
    _require(_snapshot() == _read(FIRST), "Commercial second migration is not idempotent")
    print("Commercial second migration: identical snapshot")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True)
    parser.add_argument("stage", choices=("seed_current_main", "verify_first_migrate", "verify_second_migrate"))
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
