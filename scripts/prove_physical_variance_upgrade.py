"""Phase 1-to-current upgrade proof for the persistent PHYSICAL_VARIANCE schema.

The verifier seeds a legacy non-outward Exception (type OTHER) through the
Phase 1 schema, then proves that first and second migrations add the five
new variance columns without fabricating any Exception or filling any field.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import frappe
from frappe.utils import now_datetime


EXCEPTION_DOCTYPE = "Fresko Exception"
LEGACY_EXCEPTION_NAME = "PHYVAR-UPGRADE-LEGACY-EXCEPTION"
STATE_FILENAME = "physical_variance_upgrade_seed.json"
FIRST_MIGRATE_FILENAME = "physical_variance_upgrade_first.json"

NEW_COLUMNS = {
    "declared_quantity_assertion": "Link",
    "operating_quantity_assertion": "Link",
    "variance_quantity": "Data",
    "variance_uom": "Link",
    "variance_key": "Data",
}


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
    _require(path.is_file(), f"Physical variance upgrade proof state is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _exception_snapshot(name: str) -> dict[str, Any]:
    rows = frappe.db.sql(
        """
        SELECT name, exception_type, severity, status, container, deal,
               description, resolution_notes
        FROM `tabFresko Exception`
        WHERE name = %s
        """,
        (name,),
        as_dict=True,
    )
    _require(len(rows) == 1, f"Expected one legacy Exception named {name!r}")
    return dict(rows[0])


def seed_phase1() -> None:
    """Seed one synthetic legacy non-outward Exception on the Phase 1 baseline."""
    _require(
        frappe.db.exists("DocType", EXCEPTION_DOCTYPE),
        "Phase 1 Fresko Exception DocType is missing",
    )
    # Phase 1 exception schema must not already have the new columns.
    for col in NEW_COLUMNS:
        _require(
            not frappe.db.has_column(EXCEPTION_DOCTYPE, col),
            f"Phase 1 unexpectedly contains {EXCEPTION_DOCTYPE}.{col}",
        )
    _require(
        not frappe.db.exists(EXCEPTION_DOCTYPE, LEGACY_EXCEPTION_NAME),
        "Legacy Exception seed already exists",
    )

    timestamp = now_datetime()
    frappe.db.sql(
        """
        INSERT INTO `tabFresko Exception`
            (name, creation, modified, modified_by, owner, docstatus, idx,
             exception_type, severity, status, container, deal,
             description, opened_by, opened_at)
        VALUES
            (%s, %s, %s, 'Administrator', 'Administrator', 0, 0,
             'OTHER', 'Low', 'Open', NULL, NULL,
             'Legacy non-outward exception for physical variance upgrade proof',
             'Administrator', %s)
        """,
        (LEGACY_EXCEPTION_NAME, timestamp, timestamp, timestamp),
    )
    frappe.db.commit()

    state = {
        "legacy_exception": _exception_snapshot(LEGACY_EXCEPTION_NAME),
        "exception_count": frappe.db.count(EXCEPTION_DOCTYPE),
    }
    _write_json(_private_path(STATE_FILENAME), state)
    print(
        "Physical variance upgrade fixture seeded: "
        f"{LEGACY_EXCEPTION_NAME} type=OTHER"
    )


def _current_snapshot(seed: dict[str, Any]) -> dict[str, Any]:
    # 1. Five new columns exist with correct types.
    frappe.clear_cache(doctype=EXCEPTION_DOCTYPE)
    meta = frappe.get_meta(EXCEPTION_DOCTYPE, cached=False)
    for col, expected_type in NEW_COLUMNS.items():
        field = meta.get_field(col)
        _require(field, f"Migrated schema is missing {EXCEPTION_DOCTYPE}.{col}")
        _require(
            field.fieldtype == expected_type,
            f"Migrated {EXCEPTION_DOCTYPE}.{col} type is {field.fieldtype!r}, expected {expected_type!r}",
        )

    # 2. variance_key has a unique index.
    index_rows = frappe.db.sql(
        "SHOW INDEX FROM `tabFresko Exception` WHERE Column_name = 'variance_key'",
        as_dict=True,
    )
    _require(
        any(not int(row.get("Non_unique", 1)) for row in index_rows),
        "variance_key must have a unique database index",
    )

    # 3. Seeded row original fields identical and new columns are NULL.
    current = _exception_snapshot(LEGACY_EXCEPTION_NAME)
    _require(
        current == seed["legacy_exception"],
        f"Migration changed the seeded legacy Exception: {current!r}",
    )
    new_values = frappe.db.sql(
        """
        SELECT declared_quantity_assertion, operating_quantity_assertion,
               variance_quantity, variance_uom, variance_key
        FROM `tabFresko Exception`
        WHERE name = %s
        """,
        (LEGACY_EXCEPTION_NAME,),
        as_dict=True,
    )
    _require(len(new_values) == 1, "Seeded exception row is missing")
    for col in NEW_COLUMNS:
        _require(
            new_values[0].get(col) is None,
            f"Migration populated {col} on the seeded legacy exception",
        )

    # 4. Zero rows with non-null variance_key.
    filled = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabFresko Exception` WHERE variance_key IS NOT NULL",
    )[0][0]
    _require(
        filled == 0,
        f"Migration fabricated {filled} exception(s) with variance_key",
    )

    # 5. Count unchanged.
    _require(
        frappe.db.count(EXCEPTION_DOCTYPE) == seed["exception_count"],
        "Migration changed the number of Fresko Exception rows",
    )

    return {
        "new_columns": {col: ftype for col, ftype in NEW_COLUMNS.items()},
        "legacy_exception": current,
        "exception_count": seed["exception_count"],
    }


def verify_first_migrate() -> None:
    seed = _read_json(_private_path(STATE_FILENAME))
    snapshot = _current_snapshot(seed)
    _write_json(_private_path(FIRST_MIGRATE_FILENAME), snapshot)
    print("First physical variance schema proof passed")


def verify_second_migrate() -> None:
    seed = _read_json(_private_path(STATE_FILENAME))
    first = _read_json(_private_path(FIRST_MIGRATE_FILENAME))
    second = _current_snapshot(seed)
    _require(second == first, "Second migrate changed the verified physical variance upgrade snapshot")
    print("Second physical variance migration proof passed; populated state is idempotent")


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
