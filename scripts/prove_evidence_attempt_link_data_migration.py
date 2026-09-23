"""Two-revision CI proof for the Evidence Attempt Link-to-Data migration.

This module is intentionally outside the application package.  The bench job
runs it with the bench virtualenv so the same verifier can seed an exact Phase 1
site and inspect it after the candidate application revision is installed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import frappe


ATTEMPT_DOCTYPE = "Fresko Evidence Attempt"
EVIDENCE_DOCTYPE = "Fresko Evidence"
ATTACHMENT_DOCTYPE = "Fresko Evidence Attachment"
PATCH_NAME = "fresko_universe.patches.v1_0.backfill_evidence_attempt_durability_state"
STATE_FILENAME = "evidence_attempt_link_data_migration_seed.json"
FIRST_MIGRATE_FILENAME = "evidence_attempt_link_data_migration_first.json"
APPROVER_USER = "migration-proof-approver@example.invalid"
ORPHAN_EVIDENCE = "  phase1-orphan-evidence::preserve-exactly  "
ORPHAN_ATTACHMENT = "  phase1-orphan-attachment::preserve-exactly  "
ORPHAN_REASON = "phase1 migration proof orphan attempt"
EXISTING_ATTACHMENT_REASON = "phase1 migration proof existing attachment attempt"


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
    _require(path.is_file(), f"Migration proof state is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _stored_field(fieldname: str) -> dict[str, Any]:
    row = frappe.db.get_value(
        "DocField",
        {"parent": ATTEMPT_DOCTYPE, "fieldname": fieldname},
        ["fieldtype", "options"],
        as_dict=True,
    )
    _require(row, f"Stored DocField is missing: {ATTEMPT_DOCTYPE}.{fieldname}")
    return {"fieldtype": row.fieldtype, "options": row.options or None}


def _assert_field_contract(expected_type: str, expected_options: dict[str, str | None]) -> None:
    frappe.clear_cache(doctype=ATTEMPT_DOCTYPE)
    meta = frappe.get_meta(ATTEMPT_DOCTYPE, cached=False)
    for fieldname, expected_option in expected_options.items():
        runtime = meta.get_field(fieldname)
        _require(runtime, f"Runtime field is missing: {ATTEMPT_DOCTYPE}.{fieldname}")
        _require(
            runtime.fieldtype == expected_type,
            f"Runtime {fieldname} type is {runtime.fieldtype!r}, expected {expected_type!r}",
        )
        _require(
            (runtime.options or None) == expected_option,
            f"Runtime {fieldname} options are {runtime.options!r}, expected {expected_option!r}",
        )

        stored = _stored_field(fieldname)
        _require(
            stored == {"fieldtype": expected_type, "options": expected_option},
            f"Stored {fieldname} contract is {stored!r}",
        )


def _attempt_row(name: str) -> dict[str, Any]:
    rows = frappe.db.sql(
        """
        SELECT name,
               HEX(evidence) AS evidence_hex,
               HEX(evidence_attachment) AS evidence_attachment_hex,
               durability_state,
               audit_payload_sha256,
               delivery_received_at
        FROM `tabFresko Evidence Attempt`
        WHERE name = %s
        """,
        (name,),
        as_dict=True,
    )
    _require(len(rows) == 1, f"Expected exactly one migrated attempt named {name!r}")
    row = rows[0]
    return {
        "name": row.name,
        "evidence_hex": row.evidence_hex,
        "evidence_attachment_hex": row.evidence_attachment_hex,
        "durability_state": row.durability_state,
        "audit_payload_sha256": row.audit_payload_sha256,
        "delivery_received_at": str(row.delivery_received_at) if row.delivery_received_at else None,
    }


def _seed_row(name: str) -> dict[str, Any]:
    rows = frappe.db.sql(
        """
        SELECT name,
               HEX(evidence) AS evidence_hex,
               HEX(evidence_attachment) AS evidence_attachment_hex
        FROM `tabFresko Evidence Attempt`
        WHERE name = %s
        """,
        (name,),
        as_dict=True,
    )
    _require(len(rows) == 1, f"Expected exactly one Phase 1 attempt named {name!r}")
    return dict(rows[0])


def seed_phase1() -> None:
    """Seed realistic Link-era rows while the exact Phase 1 app is installed."""
    from fresko_universe.fresko_core.services.evidence_service import (
        _record_attempt,
        compute_logical_attachment_key,
        compute_scoped_attachment_version_key,
        ingest_message_evidence,
    )

    _assert_field_contract(
        "Link",
        {
            "evidence": EVIDENCE_DOCTYPE,
            "evidence_attachment": ATTACHMENT_DOCTYPE,
        },
    )
    for column in ("durability_state", "audit_payload_sha256", "delivery_received_at"):
        _require(
            not frappe.db.has_column(ATTEMPT_DOCTYPE, column),
            f"Phase 1 unexpectedly already has {ATTEMPT_DOCTYPE}.{column}",
        )
    _require(frappe.db.count(ATTEMPT_DOCTYPE) == 0, "Upgrade site is not a clean Phase 1 fixture")

    evidence, outcome = ingest_message_evidence(
        provider="migration-proof-provider",
        provider_account_id="account::phase1",
        conversation_id="conversation::phase1",
        provider_message_id="message::phase1",
        raw_payload={"fixture": "phase1-link-era", "version": 1},
        notes="Created by the two-revision migration proof",
    )
    _require(outcome == "SUCCESS_NEW", f"Unexpected Phase 1 ingest outcome: {outcome!r}")

    logical_key = compute_logical_attachment_key(
        evidence.provider,
        evidence.provider_account_id,
        evidence.conversation_id,
        evidence.provider_message_id,
        "provider_id",
        "attachment::phase1",
    )
    version_key = compute_scoped_attachment_version_key(logical_key, 1)
    attachment = frappe.new_doc(ATTACHMENT_DOCTYPE)
    attachment.flags.in_service = True
    attachment.evidence = evidence.name
    attachment.provider = evidence.provider
    attachment.provider_account_id = evidence.provider_account_id
    attachment.conversation_id = evidence.conversation_id
    attachment.provider_message_id = evidence.provider_message_id
    attachment.identity_type = "provider_id"
    attachment.provider_attachment_id = "attachment::phase1"
    attachment.attachment_ordinal = 0
    attachment.logical_attachment_key = logical_key
    attachment.version = 1
    attachment.scoped_attachment_version_key = version_key
    attachment.file = "/private/files/phase1-migration-proof.txt"
    attachment.file_url = "/private/files/phase1-migration-proof.txt"
    attachment.provenance_type = "MISSING_PROVENANCE"
    attachment.expected_byte_count = -1
    attachment.content_byte_count = 0
    attachment.capture_status = "PENDING"
    attachment.readback_verified = 0
    attachment.is_current_version = 1
    attachment.is_superseded = 0
    attachment.insert(ignore_permissions=True)

    _record_attempt(
        evidence=evidence.name,
        evidence_attachment=attachment.name,
        operation="ATTACHMENT_INGEST",
        outcome="SUCCESS_NEW",
        logical_attachment_key=logical_key,
        scoped_attachment_version_key=version_key,
        reason=EXISTING_ATTACHMENT_REASON,
    )
    frappe.db.commit()

    # The Phase 1 independent-write path used raw SQL and could truthfully retain
    # identifiers whose parent transaction rolled back.  Seed that exact state.
    _record_attempt(
        evidence=ORPHAN_EVIDENCE,
        evidence_attachment=ORPHAN_ATTACHMENT,
        operation="ATTACHMENT_INGEST",
        outcome="FAILED_DB_WRITE",
        reason=ORPHAN_REASON,
        isolated=True,
    )
    frappe.db.commit()
    _ensure_approver_user()

    orphan_name = frappe.db.get_value(ATTEMPT_DOCTYPE, {"reason": ORPHAN_REASON}, "name")
    _require(orphan_name, "Phase 1 independent-write path did not persist the orphan attempt")
    existing_names = frappe.get_all(
        ATTEMPT_DOCTYPE,
        filters={"evidence": evidence.name},
        pluck="name",
        order_by="name asc",
    )
    _require(len(existing_names) == 2, f"Expected two parent-backed attempts, found {existing_names!r}")

    names = sorted([*existing_names, orphan_name])
    state = {
        "attempt_count": frappe.db.count(ATTEMPT_DOCTYPE),
        "attempt_names": names,
        "existing_attempt_names": sorted(existing_names),
        "orphan_attempt_name": orphan_name,
        "existing_evidence": evidence.name,
        "existing_attachment": attachment.name,
        "orphan_evidence": ORPHAN_EVIDENCE,
        "orphan_attachment": ORPHAN_ATTACHMENT,
        "evidence_names": sorted(frappe.get_all(EVIDENCE_DOCTYPE, pluck="name")),
        "attachment_names": sorted(frappe.get_all(ATTACHMENT_DOCTYPE, pluck="name")),
        "rows": [_seed_row(name) for name in names],
    }
    _require(state["attempt_count"] == 3, f"Expected exactly three seeded attempts, found {state['attempt_count']}")
    _require(not frappe.db.exists(EVIDENCE_DOCTYPE, ORPHAN_EVIDENCE), "Orphan Evidence unexpectedly exists")
    _require(
        not frappe.db.exists(ATTACHMENT_DOCTYPE, ORPHAN_ATTACHMENT),
        "Orphan Evidence Attachment unexpectedly exists",
    )
    _write_json(_private_path(STATE_FILENAME), state)
    print(f"Phase 1 migration fixture seeded: {names}")


def _ensure_approver_user() -> str:
    if not frappe.db.exists("User", APPROVER_USER):
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": APPROVER_USER,
                "first_name": "Migration Proof",
                "enabled": 1,
                "user_type": "System User",
                "send_welcome_email": 0,
            }
        )
        user.flags.no_welcome_mail = True
        user.insert(ignore_permissions=True)
    else:
        user = frappe.get_doc("User", APPROVER_USER)

    if "Fresko Approver" not in frappe.get_roles(APPROVER_USER):
        user.add_roles("Fresko Approver")
    frappe.db.commit()
    frappe.clear_cache(user=APPROVER_USER)
    return APPROVER_USER


def _foreign_key_count() -> int:
    return int(
        frappe.db.sql(
            """
            SELECT COUNT(*)
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'tabFresko Evidence Attempt'
              AND COLUMN_NAME IN ('evidence', 'evidence_attachment')
              AND REFERENCED_TABLE_NAME IS NOT NULL
            """
        )[0][0]
    )


def _permission_snapshot(seed: dict[str, Any]) -> dict[str, Any]:
    from fresko_universe.permissions import evidence_attempt_has_permission

    approver = APPROVER_USER
    _require(frappe.db.exists("User", approver), "Phase 1 Approver fixture is missing")
    _require("Fresko Approver" in frappe.get_roles(approver), "Approver fixture lost its role")
    existing_names = seed["existing_attempt_names"]
    orphan_name = seed["orphan_attempt_name"]

    for name in existing_names:
        doc = frappe.get_doc(ATTEMPT_DOCTYPE, name)
        _require(
            evidence_attempt_has_permission(name, "read", user=approver),
            f"Approver hook rejects parent-backed migrated attempt {name}",
        )
        _require(
            frappe.has_permission(ATTEMPT_DOCTYPE, ptype="read", doc=doc, user=approver),
            f"Frappe ACL rejects parent-backed migrated attempt {name}",
        )

    orphan_doc = frappe.get_doc(ATTEMPT_DOCTYPE, orphan_name)
    _require(
        not evidence_attempt_has_permission(orphan_name, "read", user=approver),
        "Approver hook accepts a migrated attempt whose Evidence parent is absent",
    )
    _require(
        not frappe.has_permission(
            ATTEMPT_DOCTYPE, ptype="read", doc=orphan_doc, user=approver
        ),
        "Frappe ACL lets Approver read a migrated attempt whose Evidence parent is absent",
    )
    _require(
        evidence_attempt_has_permission(orphan_name, "read", user="Administrator"),
        "Administrator hook cannot inspect the orphan audit attempt",
    )
    _require(
        frappe.has_permission(
            ATTEMPT_DOCTYPE, ptype="read", doc=orphan_doc, user="Administrator"
        ),
        "Frappe ACL prevents Administrator from inspecting the orphan audit attempt",
    )

    previous_user = frappe.session.user
    try:
        frappe.set_user(approver)
        visible = set(
            frappe.get_list(
                ATTEMPT_DOCTYPE,
                pluck="name",
                limit_page_length=1000,
                order_by="name asc",
            )
        )
    finally:
        frappe.set_user(previous_user)

    _require(set(existing_names).issubset(visible), "Approver list omits parent-backed migrated attempts")
    _require(orphan_name not in visible, "Approver list exposes the orphan migrated attempt")
    return {
        "approver_existing_visible": sorted(set(existing_names).intersection(visible)),
        "approver_orphan_visible": orphan_name in visible,
        "framework_acl_checked": True,
        "administrator_orphan_readable": True,
    }


def _current_snapshot(seed: dict[str, Any]) -> dict[str, Any]:
    _assert_field_contract("Data", {"evidence": None, "evidence_attachment": None})
    for column in ("durability_state", "audit_payload_sha256", "delivery_received_at"):
        _require(
            frappe.db.has_column(ATTEMPT_DOCTYPE, column),
            f"Migrated schema is missing {ATTEMPT_DOCTYPE}.{column}",
        )

    _require(
        frappe.db.count(ATTEMPT_DOCTYPE) == seed["attempt_count"],
        "Migration changed the number of historical attempt rows",
    )
    rows = [_attempt_row(name) for name in seed["attempt_names"]]
    seed_rows = {row["name"]: row for row in seed["rows"]}
    for row in rows:
        original = seed_rows[row["name"]]
        _require(row["evidence_hex"] == original["evidence_hex"], f"Evidence bytes changed for {row['name']}")
        _require(
            row["evidence_attachment_hex"] == original["evidence_attachment_hex"],
            f"Evidence Attachment bytes changed for {row['name']}",
        )
        _require(row["durability_state"] == "UNKNOWN", f"Legacy durability was fabricated for {row['name']}")
        _require(row["audit_payload_sha256"] is None, f"Legacy audit fingerprint was fabricated for {row['name']}")
        _require(row["delivery_received_at"] is None, f"Legacy delivery receipt was fabricated for {row['name']}")

    current_evidence_names = sorted(frappe.get_all(EVIDENCE_DOCTYPE, pluck="name"))
    current_attachment_names = sorted(frappe.get_all(ATTACHMENT_DOCTYPE, pluck="name"))
    _require(
        current_evidence_names == seed["evidence_names"],
        "Migration changed the complete Evidence parent-name set",
    )
    _require(
        current_attachment_names == seed["attachment_names"],
        "Migration changed the complete Evidence Attachment parent-name set",
    )
    _require(
        bool(frappe.db.exists(EVIDENCE_DOCTYPE, seed["existing_evidence"])),
        "Migration deleted the existing Evidence parent",
    )
    _require(
        bool(frappe.db.exists(ATTACHMENT_DOCTYPE, seed["existing_attachment"])),
        "Migration deleted the existing Evidence Attachment parent",
    )
    _require(
        not frappe.db.exists(EVIDENCE_DOCTYPE, seed["orphan_evidence"]),
        "Migration fabricated an Evidence parent for an identifier snapshot",
    )
    _require(
        not frappe.db.exists(ATTACHMENT_DOCTYPE, seed["orphan_attachment"]),
        "Migration fabricated an Evidence Attachment parent for an identifier snapshot",
    )
    fk_count = _foreign_key_count()
    _require(fk_count == 0, f"Migrated identifier snapshots have {fk_count} foreign-key constraints")
    _require(
        bool(frappe.db.exists("Patch Log", {"patch": PATCH_NAME})),
        f"Patch Log is missing {PATCH_NAME}",
    )

    return {
        "attempt_count": seed["attempt_count"],
        "rows": rows,
        "evidence_names": current_evidence_names,
        "attachment_names": current_attachment_names,
        "existing_evidence_present": True,
        "existing_attachment_present": True,
        "orphan_evidence_present": False,
        "orphan_attachment_present": False,
        "foreign_key_count": fk_count,
        "patch_logged": True,
        "permissions": _permission_snapshot(seed),
    }


def verify_first_migrate() -> None:
    """Verify the first real Phase 1-to-current migration and persist its snapshot."""
    seed = _read_json(_private_path(STATE_FILENAME))
    snapshot = _current_snapshot(seed)
    _write_json(_private_path(FIRST_MIGRATE_FILENAME), snapshot)
    print("First Phase 1-to-current migration proof passed")


def verify_second_migrate() -> None:
    """Verify a second migrate is an exact no-op for the asserted state."""
    seed = _read_json(_private_path(STATE_FILENAME))
    first = _read_json(_private_path(FIRST_MIGRATE_FILENAME))
    second = _current_snapshot(seed)
    _require(second == first, "Second migrate changed the verified migration snapshot")
    print("Second migration proof passed; asserted state is idempotent")

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

    # Frappe's file logger resolves ../logs and <site>/logs from the process
    # working directory, so direct site-aware CLIs must run from sites/.
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
