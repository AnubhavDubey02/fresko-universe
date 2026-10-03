"""Baseline-ledger integrity checker for protected Fresko records.

Design: the first time the checker observes a record it seals a canonical hash of
its immutable stored fields *as read from the DB*; later runs re-read with the
SAME reader and compare.  Detects post-baseline change only (documented
limitation).  Migration never seals anything.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import frappe
from frappe.utils import now_datetime

from fresko_universe.fresko_core.doctype.fresko_field_assertion.fresko_field_assertion import (
    _PAYLOAD_FIELDS as FA_PAYLOAD_FIELDS,
)
from fresko_universe.fresko_core.doctype.fresko_container_quantity_assertion.fresko_container_quantity_assertion import (
    _PAYLOAD_FIELDS as QA_PAYLOAD_FIELDS,
)

SEAL_VERSION = "fresko-integrity-seal:v1"

# ---------------------------------------------------------------------------
# Single source of truth: field lists
# ---------------------------------------------------------------------------

OUTWARD_PAYLOAD_FIELDS = (
    "company",
    "container",
    "deal",
    "gatepass_no",
    "gatepass_comparison_key",
    "vehicle_no",
    "raw_party_name",
    "movement_type",
    "movement_at",
    "source_evidence",
    "source_event_id",
    "source_event_key",
    "payload_sha256",
    "reverses_outward",
    "posting_reason",
    "prepared_by",
    "prepared_at",
)

OUTWARD_LINE_FIELDS = (
    "idx",
    "line_key",
    "raw_lot_text",
    "lot_no",
    "batch",
    "qty",
    "uom",
    "raw_qty_text",
    "raw_uom_text",
    "raw_rate_text",
    "source_line_ref",
)

# Terminal sets: status values that mark a record as terminal.
OUTWARD_TERMINAL_STATUSES = frozenset({"Posted"})
OUTWARD_TERMINAL_FIELDS = ("status", "submitted_by", "submitted_at", "posted_by", "posted_at")

FA_TERMINAL_STATUSES = frozenset({"Rejected", "Superseded"})
QA_TERMINAL_STATUSES = frozenset({"Rejected", "Superseded"})

# Derived from inspecting the DocType JSON for which terminal-phase fields exist.
FA_TERMINAL_FIELDS = (
    "status",
    "reviewed_by",
    "reviewed_at",
    "activated_by",
    "activated_at",
    "asserted_by",
    "asserted_at",
    "superseded_by",
)

QA_TERMINAL_FIELDS = (
    "status",
    "reviewed_by",
    "reviewed_at",
    "activated_by",
    "activated_at",
    "superseded_by",
)

# Collected config per DocType.
CHECKED_DOCTYPES = {
    "Fresko Outward": {
        "payload_fields": OUTWARD_PAYLOAD_FIELDS,
        "has_lines": True,
        "line_table": "tabFresko Outward Line",
        "line_fields": OUTWARD_LINE_FIELDS,
        "terminal_statuses": OUTWARD_TERMINAL_STATUSES,
        "terminal_fields": OUTWARD_TERMINAL_FIELDS,
        "container_field": "container",
    },
    "Fresko Field Assertion": {
        "payload_fields": FA_PAYLOAD_FIELDS,
        "has_lines": False,
        "terminal_statuses": FA_TERMINAL_STATUSES,
        "terminal_fields": FA_TERMINAL_FIELDS,
        "container_field": None,  # derived from outward
    },
    "Fresko Container Quantity Assertion": {
        "payload_fields": QA_PAYLOAD_FIELDS,
        "has_lines": False,
        "terminal_statuses": QA_TERMINAL_STATUSES,
        "terminal_fields": QA_TERMINAL_FIELDS,
        "container_field": "container",
    },
}


# ---------------------------------------------------------------------------
# Canonical value serialization
# ---------------------------------------------------------------------------

def _canonicalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, (Decimal, float)):
        # One normalized decimal text for both, so a driver returning Decimal
        # instead of float (10.000000000 vs 10.0) cannot raise a false alarm.
        number = Decimal(repr(value)) if isinstance(value, float) else value
        if not number.is_finite():
            return str(number)
        if number == 0:
            return "0"
        return format(number.normalize(), "f")
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return str(value)


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Canonical record reader
# ---------------------------------------------------------------------------

def _read_payload_hash(doctype: str, name: str, config: dict) -> str | None:
    row = frappe.db.get_value(doctype, name, list(config["payload_fields"]), as_dict=True)
    if not row:
        return None
    fields = {k: _canonicalize(v) for k, v in row.items()}
    lines = None
    if config.get("has_lines"):
        line_rows = frappe.get_all(
            config["line_table"],
            filters={"parent": name, "parenttype": doctype},
            fields=list(config["line_fields"]),
            order_by="idx asc",
        )
        lines = [
            {k: _canonicalize(v) for k, v in lr.items() if k in config["line_fields"]}
            for lr in line_rows
        ]
    payload = {
        "version": SEAL_VERSION,
        "doctype": doctype,
        "name": name,
        "fields": fields,
    }
    if lines is not None:
        payload["lines"] = lines
    return _sha256(_canonical_json(payload))


def _read_terminal_hash(doctype: str, name: str, config: dict) -> tuple[str | None, str | None]:
    """Return (status, hash) if the record is in a terminal state, else (None, None)."""
    row = frappe.db.get_value(doctype, name, list(config["terminal_fields"]), as_dict=True)
    if not row:
        return None, None
    status = row.get("status")
    if status not in config["terminal_statuses"]:
        return None, None
    return status, _terminal_fields_hash(doctype, name, row)


def _read_terminal_hash_unconditional(doctype: str, name: str, config: dict) -> str | None:
    """Hash the terminal fields whatever the current status.

    Once a terminal state is sealed, leaving it (for example Posted -> Draft by a
    direct write) must compare as changed rather than look non-terminal.
    """
    row = frappe.db.get_value(doctype, name, list(config["terminal_fields"]), as_dict=True)
    if not row:
        return None
    return _terminal_fields_hash(doctype, name, row)


def _terminal_fields_hash(doctype: str, name: str, row: dict) -> str:
    fields = {k: _canonicalize(v) for k, v in row.items()}
    payload = {
        "version": SEAL_VERSION,
        "doctype": doctype,
        "name": name,
        "terminal_fields": fields,
    }
    return _sha256(_canonical_json(payload))


def _seal_key(doctype: str, name: str) -> str:
    return _sha256(_canonical_json([SEAL_VERSION, doctype, name]))


def _derive_container(doctype: str, name: str, config: dict) -> str | None:
    cfield = config.get("container_field")
    if cfield:
        return frappe.db.get_value(doctype, name, cfield)
    # Field Assertion: derive from its outward's container.
    if doctype == "Fresko Field Assertion":
        outward_name = frappe.db.get_value("Fresko Field Assertion", name, "outward")
        if outward_name:
            return frappe.db.get_value("Fresko Outward", outward_name, "container")
    return None


# ---------------------------------------------------------------------------
# Core check loop
# ---------------------------------------------------------------------------

def run_integrity_check(limit: int | None = None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "checked": 0,
        "sealed_new": 0,
        "terminal_sealed": 0,
        "unchanged": 0,
        "mismatches_new": [],
        "mismatches_already_reported": [],
    }

    for doctype, config in CHECKED_DOCTYPES.items():
        _check_doctype(doctype, config, summary, limit=limit)

    # Check for RECORD_MISSING: seals whose records no longer exist.
    all_seals = frappe.get_all(
        "Fresko Integrity Seal",
        filters={"mismatch_kind": ("is", "not set")},
        fields=["name", "record_doctype", "record_name", "container", "payload_sha256"],
    )
    for seal_row in all_seals:
        if not frappe.db.exists(seal_row.record_doctype, seal_row.record_name):
            _record_mismatch(
                seal_row.name,
                "RECORD_MISSING",
                observed_sha256=None,
                container=seal_row.container,
                doctype=seal_row.record_doctype,
                record_name=seal_row.record_name,
                sealed_hash=seal_row.payload_sha256,
                summary=summary,
            )

    # Also check seals that already have a mismatch for records that are now missing.
    existing_mismatched = frappe.get_all(
        "Fresko Integrity Seal",
        filters={"mismatch_kind": ("is", "set")},
        fields=["name", "record_doctype", "record_name", "mismatch_kind"],
    )
    for seal_row in existing_mismatched:
        if not frappe.db.exists(seal_row.record_doctype, seal_row.record_name):
            summary["mismatches_already_reported"].append({
                "seal": seal_row.name,
                "kind": seal_row.mismatch_kind,
                "record_doctype": seal_row.record_doctype,
                "record_name": seal_row.record_name,
            })

    return summary


def _check_doctype(
    doctype: str,
    config: dict,
    summary: dict,
    *,
    limit: int | None = None,
) -> None:
    filters: dict[str, Any] = {}
    names = frappe.get_all(
        doctype,
        filters=filters,
        fields=["name"],
        order_by="creation asc, name asc",
        limit_page_length=limit or 0,
        pluck="name",
    )
    for name in names:
        summary["checked"] += 1
        seal_key = _seal_key(doctype, name)
        existing_seal = frappe.db.get_value(
            "Fresko Integrity Seal",
            {"seal_key": seal_key},
            ["name", "payload_sha256", "terminal_sha256", "mismatch_kind"],
            as_dict=True,
        )

        if not existing_seal:
            # First observation: seal the record.
            _create_seal(doctype, name, config, seal_key, summary)
            continue

        # Seal exists: compare.
        if existing_seal.mismatch_kind:
            # Already has a mismatch recorded. Report and skip.
            summary["mismatches_already_reported"].append({
                "seal": existing_seal.name,
                "kind": existing_seal.mismatch_kind,
                "record_doctype": doctype,
                "record_name": name,
            })
            continue

        current_payload = _read_payload_hash(doctype, name, config)
        if current_payload is None:
            # Record disappeared since we fetched names.
            _record_mismatch(
                existing_seal.name,
                "RECORD_MISSING",
                observed_sha256=None,
                container=frappe.db.get_value("Fresko Integrity Seal", existing_seal.name, "container"),
                doctype=doctype,
                record_name=name,
                sealed_hash=existing_seal.payload_sha256,
                summary=summary,
            )
            continue

        if current_payload != existing_seal.payload_sha256:
            _record_mismatch(
                existing_seal.name,
                "PAYLOAD_CHANGED",
                observed_sha256=current_payload,
                container=frappe.db.get_value("Fresko Integrity Seal", existing_seal.name, "container"),
                doctype=doctype,
                record_name=name,
                sealed_hash=existing_seal.payload_sha256,
                summary=summary,
            )
            continue

        # Payload matches. Check terminal state.
        if existing_seal.terminal_sha256:
            # A sealed terminal state is compared whatever the current status.
            observed_terminal = _read_terminal_hash_unconditional(doctype, name, config)
            if observed_terminal != existing_seal.terminal_sha256:
                _record_mismatch(
                    existing_seal.name,
                    "TERMINAL_CHANGED",
                    observed_sha256=observed_terminal,
                    container=frappe.db.get_value("Fresko Integrity Seal", existing_seal.name, "container"),
                    doctype=doctype,
                    record_name=name,
                    sealed_hash=existing_seal.terminal_sha256,
                    summary=summary,
                )
                continue
            summary["unchanged"] += 1
            continue

        terminal_status, terminal_hash = _read_terminal_hash(doctype, name, config)
        if terminal_hash:
            # Seal lacks terminal hash but record is now terminal: seal it.
            seal_doc = frappe.get_doc("Fresko Integrity Seal", existing_seal.name)
            seal_doc.flags.in_integrity_service = True
            seal_doc.terminal_status = terminal_status
            seal_doc.terminal_sha256 = terminal_hash
            seal_doc.terminal_sealed_at = now_datetime()
            seal_doc.save(ignore_permissions=True)
            summary["terminal_sealed"] += 1
            continue

        summary["unchanged"] += 1


def _create_seal(
    doctype: str,
    name: str,
    config: dict,
    seal_key: str,
    summary: dict,
) -> None:
    payload_hash = _read_payload_hash(doctype, name, config)
    if payload_hash is None:
        return  # Record vanished.

    container = _derive_container(doctype, name, config)
    terminal_status, terminal_hash = _read_terminal_hash(doctype, name, config)

    seal = frappe.get_doc({
        "doctype": "Fresko Integrity Seal",
        "record_doctype": doctype,
        "record_name": name,
        "seal_key": seal_key,
        "seal_version": SEAL_VERSION,
        "container": container,
        "payload_sha256": payload_hash,
        "sealed_at": now_datetime(),
        "terminal_status": terminal_status,
        "terminal_sha256": terminal_hash,
        "terminal_sealed_at": now_datetime() if terminal_hash else None,
    })
    seal.flags.in_integrity_service = True

    savepoint = "sp_seal_" + frappe.generate_hash(length=8)
    frappe.db.savepoint(savepoint)
    try:
        seal.insert(ignore_permissions=True)
        frappe.db.release_savepoint(savepoint)
    except frappe.UniqueValidationError:
        frappe.db.rollback(save_point=savepoint)
        # Race: another process sealed it first. Re-read and proceed as existing.
        existing = frappe.db.get_value(
            "Fresko Integrity Seal",
            {"seal_key": seal_key},
            ["name", "payload_sha256"],
            as_dict=True,
        )
        if not existing:
            raise
        if existing.payload_sha256 != payload_hash:
            _record_mismatch(
                existing.name,
                "PAYLOAD_CHANGED",
                observed_sha256=payload_hash,
                container=container,
                doctype=doctype,
                record_name=name,
                sealed_hash=existing.payload_sha256,
                summary=summary,
            )
        return

    summary["sealed_new"] += 1
    if terminal_hash:
        summary["terminal_sealed"] += 1


def _record_mismatch(
    seal_name: str,
    kind: str,
    *,
    observed_sha256: str | None,
    container: str | None,
    doctype: str,
    record_name: str,
    sealed_hash: str,
    summary: dict,
) -> None:
    seal = frappe.get_doc("Fresko Integrity Seal", seal_name)
    if seal.mismatch_kind:
        summary["mismatches_already_reported"].append({
            "seal": seal_name,
            "kind": seal.mismatch_kind,
            "record_doctype": doctype,
            "record_name": record_name,
        })
        return

    # Create a DATA_INTEGRITY exception.
    description = (
        f"Integrity check detected {kind} on {doctype} {record_name}. "
        f"Sealed hash: {sealed_hash}. "
        f"Observed hash: {observed_sha256 or '(record missing)'}. "
        f"Seal: {seal_name}."
    )
    exc = frappe.get_doc({
        "doctype": "Fresko Exception",
        "exception_type": "DATA_INTEGRITY",
        "severity": "Critical",
        "status": "Open",
        "container": container,
        "description": description,
    })
    exc.insert(ignore_permissions=True)

    seal.flags.in_integrity_service = True
    seal.mismatch_kind = kind
    seal.mismatch_observed_sha256 = observed_sha256
    seal.mismatch_detected_at = now_datetime()
    seal.mismatch_exception = exc.name
    seal.save(ignore_permissions=True)

    summary["mismatches_new"].append({
        "seal": seal_name,
        "kind": kind,
        "record_doctype": doctype,
        "record_name": record_name,
        "exception": exc.name,
    })
