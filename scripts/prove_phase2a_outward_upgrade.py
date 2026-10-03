"""Phase 1-to-current upgrade proof for the Phase 2A physical-ledger schema.

The verifier seeds a legacy Fresko Deal through the Phase 1 schema, then proves
that first and second migrations install the three Phase 2A DocTypes without
fabricating physical truth or changing the legacy dispatched quantity.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import frappe
from frappe.utils import now_datetime


OUTWARD_DOCTYPE = "Fresko Outward"
OUTWARD_LINE_DOCTYPE = "Fresko Outward Line"
ASSERTION_DOCTYPE = "Fresko Field Assertion"
QUANTITY_ASSERTION_DOCTYPE = "Fresko Container Quantity Assertion"
DEAL_DOCTYPE = "Fresko Deal"
LEGACY_DEAL_NAME = "PHASE2A-UPGRADE-DEAL"
LEGACY_DISPATCHED_QTY = "3.25"
STATE_FILENAME = "phase2a_outward_upgrade_seed.json"
FIRST_MIGRATE_FILENAME = "phase2a_outward_upgrade_first.json"


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _private_path(filename: str) -> Path:
    return Path(frappe.get_site_path("private", filename))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    _require(path.is_file(), f"Phase 2A upgrade proof state is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _table_exists(doctype: str) -> bool:
    count = frappe.db.sql(
        """
        SELECT COUNT(*)
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        """,
        (f"tab{doctype}",),
    )[0][0]
    return bool(count)


def _deal_snapshot(name: str) -> dict[str, Any]:
    rows = frappe.db.sql(
        """
        SELECT name,
               status,
               container,
               lot_no,
               CAST(qty AS CHAR) AS qty,
               CAST(dispatched_qty AS CHAR) AS dispatched_qty,
               HEX(CAST(dispatched_qty AS CHAR)) AS dispatched_qty_hex
        FROM `tabFresko Deal`
        WHERE name = %s
        """,
        (name,),
        as_dict=True,
    )
    _require(len(rows) == 1, f"Expected one legacy Fresko Deal named {name!r}")
    return dict(rows[0])


def _container_snapshot() -> list[dict[str, Any]]:
    """Only snapshot pre-existing operational scalars; migration must never rewrite them."""
    return [dict(row) for row in frappe.db.sql(
        """SELECT name, CAST(inward_qty AS CHAR) AS inward_qty,
                  HEX(CAST(inward_qty AS CHAR)) AS inward_qty_hex, uom
             FROM `tabFresko Container` ORDER BY name""",
        as_dict=True,
    )]


def seed_phase1() -> None:
    """Seed one populated legacy Deal while the exact Phase 1 app is installed."""
    for doctype in (OUTWARD_DOCTYPE, OUTWARD_LINE_DOCTYPE, ASSERTION_DOCTYPE, QUANTITY_ASSERTION_DOCTYPE):
        _require(
            not frappe.db.exists("DocType", doctype),
            f"Phase 1 unexpectedly contains DocType {doctype}",
        )
        _require(not _table_exists(doctype), f"Phase 1 unexpectedly contains table tab{doctype}")

    _require(frappe.db.exists("DocType", DEAL_DOCTYPE), "Phase 1 Fresko Deal DocType is missing")
    _require(frappe.db.has_column(DEAL_DOCTYPE, "dispatched_qty"), "Legacy dispatched_qty is missing")
    _require(not frappe.db.exists(DEAL_DOCTYPE, LEGACY_DEAL_NAME), "Legacy Deal seed already exists")

    timestamp = now_datetime()
    frappe.db.sql(
        """
        INSERT INTO `tabFresko Deal`
            (name, creation, modified, modified_by, owner, docstatus, idx,
             naming_series, company, container, buyer_alias, item, lot_no,
             qty, uom, dispatched_qty, proposed_rate, currency, status,
             approval_required)
        VALUES
            (%s, %s, %s, 'Administrator', 'Administrator', 0, 0,
             'DEAL-.YYYY.-.', 'PHASE2A-UPGRADE-COMPANY',
             'PHASE2A-UPGRADE-CONTAINER', 'Phase2A Upgrade Buyer',
             'PHASE2A-UPGRADE-ITEM', 'PHASE2A-UPGRADE-LOT',
             10, 'Crate', %s, 125, 'INR', 'Partially Dispatched', 0)
        """,
        (LEGACY_DEAL_NAME, timestamp, timestamp, LEGACY_DISPATCHED_QTY),
    )
    frappe.db.commit()

    state = {
        "legacy_deal": _deal_snapshot(LEGACY_DEAL_NAME),
        "legacy_deal_count": frappe.db.count(DEAL_DOCTYPE),
        "container_snapshot": _container_snapshot(),
    }
    _write_json(_private_path(STATE_FILENAME), state)
    print(
        "Phase 1 physical-ledger migration fixture seeded: "
        f"{LEGACY_DEAL_NAME} dispatched_qty={state['legacy_deal']['dispatched_qty']}"
    )


def _assert_field(doctype: str, fieldname: str, fieldtype: str) -> None:
    frappe.clear_cache(doctype=doctype)
    field = frappe.get_meta(doctype, cached=False).get_field(fieldname)
    _require(field, f"Migrated schema is missing {doctype}.{fieldname}")
    _require(
        field.fieldtype == fieldtype,
        f"Migrated {doctype}.{fieldname} type is {field.fieldtype!r}, expected {fieldtype!r}",
    )


def _current_snapshot(seed: dict[str, Any]) -> dict[str, Any]:
    for doctype in (OUTWARD_DOCTYPE, OUTWARD_LINE_DOCTYPE, ASSERTION_DOCTYPE, QUANTITY_ASSERTION_DOCTYPE):
        _require(frappe.db.exists("DocType", doctype), f"Migrated DocType is missing: {doctype}")
        _require(_table_exists(doctype), f"Migrated table is missing: tab{doctype}")

    required_fields = {
        OUTWARD_DOCTYPE: {
            "deal": "Link",
            "gatepass_no": "Data",
            "gatepass_comparison_key": "Data",
            "vehicle_no": "Data",
            "raw_party_name": "Small Text",
            "source_event_id": "Data",
            "source_event_key": "Data",
            "payload_sha256": "Data",
            "status": "Select",
            "lines": "Table",
            "reverses_outward": "Link",
        },
        OUTWARD_LINE_DOCTYPE: {
            "line_key": "Data",
            "qty": "Float",
            "uom": "Link",
        },
        ASSERTION_DOCTYPE: {
            "assertion_key": "Data",
            "payload_sha256": "Data",
            "rate": "Data",
            "currency": "Link",
            "rate_uom": "Link",
            "status": "Select",
            "supersedes": "Link",
        },
        QUANTITY_ASSERTION_DOCTYPE: {
            "container": "Link",
            "basis": "Select",
            "quantity": "Data",
            "uom": "Link",
            "evidence": "Link",
            "source_fact_id": "Data",
            "assertion_key": "Data",
            "payload_sha256": "Data",
            "status": "Select",
            "supersedes": "Link",
        },
    }
    for doctype, fields in required_fields.items():
        for fieldname, fieldtype in fields.items():
            _assert_field(doctype, fieldname, fieldtype)

    outward_meta = frappe.get_meta(OUTWARD_DOCTYPE, cached=False)
    _require(
        bool(outward_meta.get_field("reverses_outward").unique),
        "Migrated reversal link must have a unique database constraint",
    )
    quantity_meta = frappe.get_meta(QUANTITY_ASSERTION_DOCTYPE, cached=False)
    _require(
        bool(quantity_meta.get_field("assertion_key").unique),
        "Migrated quantity assertion key must have a unique database constraint",
    )
    _require(
        {"DECLARED_SHIPPING", "CUSTOMS_DECLARED", "OPERATING_INWARD"}.issubset(
            set((quantity_meta.get_field("basis").options or "").splitlines())
        ),
        "Migrated quantity assertion basis options are incomplete",
    )
    exception_options = set(
        (frappe.get_meta("Fresko Exception", cached=False)
         .get_field("exception_type").options or "").splitlines()
    )
    _require(
        "OUTWARD_WITHOUT_DEAL" in exception_options,
        "Migrated Exception options are missing OUTWARD_WITHOUT_DEAL",
    )
    _require(
        "DUPLICATE_GATEPASS" in exception_options,
        "Migrated Exception options are missing DUPLICATE_GATEPASS",
    )
    _assert_field("Fresko Exception", "related_outward", "Link")

    row_counts = {
        OUTWARD_DOCTYPE: frappe.db.count(OUTWARD_DOCTYPE),
        OUTWARD_LINE_DOCTYPE: frappe.db.count(OUTWARD_LINE_DOCTYPE),
        ASSERTION_DOCTYPE: frappe.db.count(ASSERTION_DOCTYPE),
        QUANTITY_ASSERTION_DOCTYPE: frappe.db.count(QUANTITY_ASSERTION_DOCTYPE),
    }
    _require(
        row_counts == {OUTWARD_DOCTYPE: 0, OUTWARD_LINE_DOCTYPE: 0, ASSERTION_DOCTYPE: 0, QUANTITY_ASSERTION_DOCTYPE: 0},
        f"Migration fabricated Phase 2A physical truth: {row_counts!r}",
    )

    current_deal = _deal_snapshot(LEGACY_DEAL_NAME)
    _require(
        current_deal == seed["legacy_deal"],
        f"Migration changed the seeded legacy Deal: {current_deal!r}",
    )
    _require(
        frappe.db.count(DEAL_DOCTYPE) == seed["legacy_deal_count"],
        "Migration changed the number of legacy Fresko Deal rows",
    )
    _require(
        _container_snapshot() == seed["container_snapshot"],
        "Migration changed existing Container.inward_qty or UOM values",
    )
    return {
        "doctypes_present": [OUTWARD_DOCTYPE, OUTWARD_LINE_DOCTYPE, ASSERTION_DOCTYPE, QUANTITY_ASSERTION_DOCTYPE],
        "row_counts": row_counts,
        "legacy_deal": current_deal,
        "legacy_deal_count": seed["legacy_deal_count"],
        "container_snapshot": seed["container_snapshot"],
    }


def verify_first_migrate() -> None:
    seed = _read_json(_private_path(STATE_FILENAME))
    snapshot = _current_snapshot(seed)
    _write_json(_private_path(FIRST_MIGRATE_FILENAME), snapshot)
    print("First Phase 1-to-current Phase 2A schema proof passed")


def verify_second_migrate() -> None:
    seed = _read_json(_private_path(STATE_FILENAME))
    first = _read_json(_private_path(FIRST_MIGRATE_FILENAME))
    second = _current_snapshot(seed)
    _require(second == first, "Second migrate changed the verified Phase 2A upgrade snapshot")
    print("Second Phase 2A migration proof passed; populated state is idempotent")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True, help="Bench site name")
    parser.add_argument(
        "stage",
        choices=("seed_phase1", "verify_first_migrate", "verify_second_migrate"),
    )
    args = parser.parse_args()

    cwd = Path.cwd()
    sites_path = cwd / "sites" if (cwd / "sites").is_dir() else cwd
    site_config = sites_path / args.site / "site_config.json"
    _require(site_config.is_file(), f"Site configuration is missing: {site_config}")

    os.chdir(sites_path)
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


if __name__ == "__main__":
    main()
