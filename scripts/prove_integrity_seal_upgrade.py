"""Phase 1-to-current upgrade proof for the Fresko Integrity Seal DocType.

Verifies that the new DocType and table are created by migration with the
correct schema, a unique index on seal_key, zero seal rows (migration must
not seal/bless anything), and that the DATA_INTEGRITY exception count is
unchanged by migration.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import frappe


SEAL_DOCTYPE = "Fresko Integrity Seal"
EXCEPTION_DOCTYPE = "Fresko Exception"
STATE_FILENAME = "integrity_seal_upgrade_seed.json"
FIRST_MIGRATE_FILENAME = "integrity_seal_upgrade_first.json"

EXPECTED_FIELDS = {
    "record_doctype": "Select",
    "record_name": "Data",
    "seal_key": "Data",
    "seal_version": "Data",
    "container": "Link",
    "payload_sha256": "Data",
    "sealed_at": "Datetime",
    "terminal_status": "Data",
    "terminal_sha256": "Data",
    "terminal_sealed_at": "Datetime",
    "mismatch_kind": "Select",
    "mismatch_observed_sha256": "Data",
    "mismatch_detected_at": "Datetime",
    "mismatch_exception": "Link",
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
    _require(path.is_file(), f"Integrity seal upgrade proof state is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def seed_phase1() -> None:
    """On the Phase 1 baseline, assert the Integrity Seal DocType does not exist."""
    _require(
        not frappe.db.exists("DocType", SEAL_DOCTYPE),
        f"Phase 1 baseline unexpectedly contains {SEAL_DOCTYPE} DocType",
    )
    # Also confirm no table exists.
    tables = [
        row[0]
        for row in frappe.db.sql("SHOW TABLES LIKE 'tabFresko Integrity Seal'")
    ]
    _require(
        not tables,
        f"Phase 1 baseline unexpectedly contains tabFresko Integrity Seal table",
    )

    # Record the count of DATA_INTEGRITY exceptions for comparison after migration.
    di_count = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabFresko Exception` WHERE exception_type = 'DATA_INTEGRITY'"
    )[0][0]

    state = {
        "doctype_exists": False,
        "table_exists": False,
        "data_integrity_exception_count": di_count,
    }
    _write_json(_private_path(STATE_FILENAME), state)
    frappe.db.commit()
    print(f"Integrity seal upgrade seed: DocType absent, DATA_INTEGRITY count={di_count}")


def _current_snapshot(seed: dict[str, Any]) -> dict[str, Any]:
    # 1. DocType and table exist.
    _require(
        frappe.db.exists("DocType", SEAL_DOCTYPE),
        f"Migrated schema is missing {SEAL_DOCTYPE} DocType",
    )
    tables = [
        row[0]
        for row in frappe.db.sql("SHOW TABLES LIKE 'tabFresko Integrity Seal'")
    ]
    _require(tables, "Migrated schema is missing tabFresko Integrity Seal table")

    # 2. All fields exist with expected types.
    frappe.clear_cache(doctype=SEAL_DOCTYPE)
    meta = frappe.get_meta(SEAL_DOCTYPE, cached=False)
    for fieldname, expected_type in EXPECTED_FIELDS.items():
        field = meta.get_field(fieldname)
        _require(field, f"Migrated schema is missing {SEAL_DOCTYPE}.{fieldname}")
        _require(
            field.fieldtype == expected_type,
            f"Migrated {SEAL_DOCTYPE}.{fieldname} type is {field.fieldtype!r}, "
            f"expected {expected_type!r}",
        )

    # 3. seal_key has a unique index.
    index_rows = frappe.db.sql(
        "SHOW INDEX FROM `tabFresko Integrity Seal` WHERE Column_name = 'seal_key'",
        as_dict=True,
    )
    _require(
        any(not int(row.get("Non_unique", 1)) for row in index_rows),
        "seal_key must have a unique database index",
    )

    # 4. ZERO seal rows (migration must not seal/bless anything).
    seal_count = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabFresko Integrity Seal`"
    )[0][0]
    _require(
        seal_count == 0,
        f"Migration fabricated {seal_count} integrity seal(s)",
    )

    # 5. DATA_INTEGRITY exception count unchanged.
    di_count = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabFresko Exception` WHERE exception_type = 'DATA_INTEGRITY'"
    )[0][0]
    _require(
        di_count == seed["data_integrity_exception_count"],
        f"Migration changed DATA_INTEGRITY exception count: "
        f"was {seed['data_integrity_exception_count']}, now {di_count}",
    )

    return {
        "doctype_exists": True,
        "table_exists": True,
        "field_types": dict(sorted(EXPECTED_FIELDS.items())),
        "seal_count": 0,
        "data_integrity_exception_count": di_count,
    }


def verify_first_migrate() -> None:
    seed = _read_json(_private_path(STATE_FILENAME))
    snapshot = _current_snapshot(seed)
    _write_json(_private_path(FIRST_MIGRATE_FILENAME), snapshot)
    print("First integrity seal schema proof passed")


def verify_second_migrate() -> None:
    seed = _read_json(_private_path(STATE_FILENAME))
    first = _read_json(_private_path(FIRST_MIGRATE_FILENAME))
    second = _current_snapshot(seed)
    _require(
        second == first,
        "Second migrate changed the verified integrity seal upgrade snapshot",
    )
    print("Second integrity seal migration proof passed; state is idempotent")
