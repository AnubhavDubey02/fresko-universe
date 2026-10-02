"""Controlled Phase 2A physical Outward and Field Assertion workflows."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from fresko_universe import permissions
from fresko_universe.fresko_core.ats import lock_container_for_update
from fresko_universe.fresko_core.physical import (
    assert_container_capacity,
    assert_mapped_lot_capacity,
)


OUTWARD_PAYLOAD_VERSION = "fresko-outward:v1"
ASSERTION_PAYLOAD_VERSION = "fresko-field-assertion:v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        value = frappe.parse_json(value)
    if not isinstance(value, list) or not value:
        frappe.throw(_("At least one Outward line is required"))
    if not all(isinstance(row, dict) for row in value):
        frappe.throw(_("Every Outward line must be an object"))
    return value


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _raw_text(value: Any, label: str, *, required: bool = False) -> str | None:
    """Preserve source-reported text exactly while validating required content."""
    if value is None:
        if required:
            frappe.throw(_("{0} is required").format(label))
        return None
    text = str(value)
    if required and not text.strip():
        frappe.throw(_("{0} is required").format(label))
    return text


def _identity_text(value: Any, label: str) -> str:
    """Validate an identity without trimming or normalizing source-reported bytes."""
    if value is None or not str(value).strip():
        frappe.throw(_("{0} is required").format(label))
    return str(value)


def _normalise_lines(source_event_key: str, lines: Any) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for index, source in enumerate(_as_list(lines), start=1):
        qty = flt(source.get("qty"))
        if not math.isfinite(qty) or qty <= 0:
            frappe.throw(_("Outward line {0}: qty must be greater than zero").format(index))
        uom = _clean_text(source.get("uom"))
        if not uom:
            frappe.throw(_("Outward line {0}: uom is required").format(index))
        source_line_ref = _identity_text(source.get("source_line_ref"), "source_line_ref")
        raw_qty_text = _raw_text(
            source.get("raw_qty_text"),
            _("Outward line {0}: raw_qty_text").format(index),
            required=True,
        )
        raw_uom_text = _raw_text(
            source.get("raw_uom_text"),
            _("Outward line {0}: raw_uom_text").format(index),
            required=True,
        )
        if source_line_ref in seen_refs:
            frappe.throw(_("Duplicate source_line_ref {0}").format(source_line_ref))
        seen_refs.add(source_line_ref)
        line_key = _sha256(f"{source_event_key}|line|{source_line_ref}")
        normalised.append(
            {
                "line_key": line_key,
                "source_line_ref": source_line_ref,
                "raw_lot_text": _raw_text(source.get("raw_lot_text"), "raw_lot_text"),
                "lot_no": _clean_text(source.get("lot_no")),
                "batch": _clean_text(source.get("batch")),
                "qty": qty,
                "uom": uom,
                "raw_qty_text": raw_qty_text,
                "raw_uom_text": raw_uom_text,
                "raw_rate_text": _raw_text(source.get("raw_rate_text"), "raw_rate_text"),
            }
        )
    return normalised


def _assert_evidence_container(evidence: str, container: str) -> None:
    if not frappe.db.exists("Fresko Evidence", evidence):
        frappe.throw(_("Fresko Evidence {0} does not exist").format(evidence))
    if not permissions.evidence_has_permission(
        evidence, "read", user=frappe.session.user
    ):
        frappe.throw(_("Access denied to supporting Evidence"), frappe.PermissionError)
    evidence_container = frappe.db.get_value("Fresko Evidence", evidence, "container")
    if evidence_container is None:
        frappe.throw(
            _("Fresko Evidence {0} is not scoped to a Container").format(evidence)
        )
    if str(evidence_container) != str(container):
        frappe.throw(
            _("Fresko Evidence {0} belongs to container {1}, not {2}").format(
                evidence, evidence_container, container
            )
        )
def _current_outward_name_by_source_event(source_event_key: str) -> str | None:
    """Use a locking current read so an RR snapshot cannot hide a race winner."""
    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabFresko Outward`
        WHERE source_event_key=%s
        LIMIT 1 FOR UPDATE
        """,
        (source_event_key,),
        as_dict=True,
    )
    return rows[0].name if rows else None


def _current_reversal_name(outward_name: str, *, exclude: str | None = None) -> str | None:
    conditions = "reverses_outward=%s"
    values: list[Any] = [outward_name]
    if exclude:
        conditions += " AND name<>%s"
        values.append(exclude)
    rows = frappe.db.sql(
        f"""
        SELECT name
        FROM `tabFresko Outward`
        WHERE {conditions}
        LIMIT 1 FOR UPDATE
        """,
        tuple(values),
        as_dict=True,
    )
    return rows[0].name if rows else None


def _current_assertion_name_by_key(assertion_key: str) -> str | None:
    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabFresko Field Assertion`
        WHERE assertion_key=%s
        LIMIT 1 FOR UPDATE
        """,
        (assertion_key,),
        as_dict=True,
    )
    return rows[0].name if rows else None


def _outward_response(doc, *, replayed: bool = False) -> dict[str, Any]:
    return {
        "name": doc.name,
        "container": doc.container,
        "deal": doc.deal,
        "movement_type": doc.movement_type,
        "status": doc.status,
        "source_event_key": doc.source_event_key,
        "gatepass_no": doc.gatepass_no,
        "vehicle_no": doc.vehicle_no,
        "raw_party_name": doc.raw_party_name,
        "replayed": replayed,
        "physical_outward_recorded": doc.status == "Posted",
        "commercial_deal_required": False,
    }


def _load_outward_for_update(name: str):
    probe = frappe.get_doc("Fresko Outward", name)
    locked_container = probe.container
    lock_container_for_update(locked_container)
    doc = frappe.get_doc("Fresko Outward", name, for_update=True)
    if doc.container != locked_container:
        frappe.throw(_("Outward container changed while acquiring the parent lock"))
    return doc


def create_outward(
    *,
    container: str,
    movement_at: str,
    source_evidence: str,
    source_event_id: str,
    lines: Any,
    posting_reason: str | None = None,
    deal: str | None = None,
    gatepass_no: str | None = None,
    vehicle_no: str | None = None,
    raw_party_name: str | None = None,
) -> dict[str, Any]:
    """Create an evidence-linked Draft Outward without requiring Deal/buyer/rate."""
    permissions.assert_can_prepare_outward()
    source_event_id = _identity_text(source_event_id, "source_event_id")
    if not frappe.db.exists("Fresko Container", container):
        frappe.throw(_("Fresko Container {0} does not exist").format(container))
    _assert_evidence_container(source_evidence, container)
    deal = _clean_text(deal)
    if deal:
        deal_container = frappe.db.get_value("Fresko Deal", deal, "container")
        if deal_container is None:
            if not frappe.db.exists("Fresko Deal", deal):
                frappe.throw(_("Fresko Deal {0} does not exist").format(deal))
            frappe.throw(_("Fresko Deal {0} is not scoped to a Container").format(deal))
        if not permissions.deal_has_permission(
            deal, "read", user=frappe.session.user
        ):
            frappe.throw(_("Access denied to Fresko Deal {0}").format(deal), frappe.PermissionError)
        if str(deal_container) != str(container):
            frappe.throw(
                _("Fresko Deal {0} belongs to container {1}, not {2}").format(
                    deal, deal_container, container
                )
            )

    company = frappe.db.get_value("Fresko Container", container, "company")
    source_event_key = _sha256(
        _canonical_json(
            [OUTWARD_PAYLOAD_VERSION, container, source_evidence, source_event_id]
        )
    )
    normalised_lines = _normalise_lines(source_event_key, lines)
    payload = {
        "version": OUTWARD_PAYLOAD_VERSION,
        "company": company,
        "container": container,
        "deal": deal,
        # These are raw logistics context, not Customer/buyer resolution inputs.
        "gatepass_no": _raw_text(gatepass_no, "gatepass_no"),
        "vehicle_no": _raw_text(vehicle_no, "vehicle_no"),
        "raw_party_name": _raw_text(raw_party_name, "raw_party_name"),
        "movement_type": "OUTWARD",
        "movement_at": str(movement_at),
        "source_evidence": source_evidence,
        "source_event_id": source_event_id,
        "posting_reason": _clean_text(posting_reason),
        "lines": normalised_lines,
    }
    payload_sha256 = _sha256(_canonical_json(payload))

    existing_name = frappe.db.get_value(
        "Fresko Outward", {"source_event_key": source_event_key}, "name"
    )
    if existing_name:
        return _outward_replay(existing_name, payload_sha256)

    doc = frappe.get_doc(
        {
            "doctype": "Fresko Outward",
            **{k: v for k, v in payload.items() if k not in {"version", "lines"}},
            "source_event_key": source_event_key,
            "payload_sha256": payload_sha256,
            "status": "Draft",
            "prepared_by": frappe.session.user,
            "prepared_at": now_datetime(),
            "lines": normalised_lines,
        }
    )
    doc.flags.in_service = True
    savepoint = "sp_outward_" + frappe.generate_hash(length=8)
    frappe.db.savepoint(savepoint)
    try:
        doc.insert(ignore_permissions=True)
        frappe.db.release_savepoint(savepoint)
    except frappe.UniqueValidationError:
        frappe.db.rollback(save_point=savepoint)
        existing_name = _current_outward_name_by_source_event(source_event_key)
        if not existing_name:
            raise
        return _outward_replay(existing_name, payload_sha256)
    return _outward_response(doc)


def _outward_replay(name: str, payload_sha256: str) -> dict[str, Any]:
    if not permissions.outward_has_permission(name, "read", user=frappe.session.user):
        frappe.throw(_("Access denied"), frappe.PermissionError)
    existing = frappe.get_doc("Fresko Outward", name)
    if existing.payload_sha256 != payload_sha256:
        from fresko_universe.fresko_core.services.evidence_service import (
            _record_attempt,
        )

        durability = _record_attempt(
            existing.source_evidence,
            "OUTWARD_CREATE",
            "CONFLICT_PAYLOAD_MISMATCH",
            scoped_message_key=existing.source_event_key,
            payload_sha256=payload_sha256,
            existing_payload_sha256=existing.payload_sha256,
            old_doc_ref=existing.name,
            reason="Source event identity was replayed with a changed Outward payload",
            isolated=True,
        )
        if durability != "COMMITTED_INDEPENDENT":
            frappe.throw(
                _(
                    "Source event payload conflict failed closed, but its audit "
                    "could not be durably recorded ({0})"
                ).format(durability),
                frappe.UniqueValidationError,
            )
        frappe.throw(
            _(
                "Source event identity already exists with a different Outward "
                "payload; the conflict was durably recorded"
            ),
            frappe.UniqueValidationError,
        )
    return _outward_response(existing, replayed=True)


def submit_outward_for_review(outward_name: str) -> dict[str, Any]:
    permissions.assert_can_prepare_outward()
    doc = _load_outward_for_update(outward_name)
    if doc.prepared_by != frappe.session.user:
        frappe.throw(_("Only the Outward maker may submit it for review"), frappe.PermissionError)
    if doc.status == "Review Pending":
        return _outward_response(doc, replayed=True)
    if doc.status != "Draft":
        frappe.throw(_("Only a Draft Outward may be submitted for review"))
    doc.flags.in_service = True
    doc.flags.allow_submit_for_review = True
    doc.status = "Review Pending"
    doc.submitted_by = frappe.session.user
    doc.submitted_at = now_datetime()
    doc.save(ignore_permissions=True)
    return _outward_response(doc)


def post_outward(outward_name: str) -> dict[str, Any]:
    """Post physical truth under the Container lock; no commercial fields are read."""
    permissions.assert_can_post_outward()
    doc = _load_outward_for_update(outward_name)
    if doc.status == "Posted":
        return _outward_response(doc, replayed=True)
    if doc.status != "Review Pending":
        frappe.throw(_("Only a Review Pending Outward may be posted"))
    if doc.prepared_by == frappe.session.user:
        frappe.throw(_("Outward maker cannot post their own movement"), frappe.PermissionError)

    reversed_outward = None
    if doc.movement_type == "REVERSAL":
        reversed_outward = _validate_reversal_for_post(doc)
    else:
        assert_container_capacity(
            doc.container,
            sum(flt(line.qty) for line in doc.lines),
            {line.uom for line in doc.lines},
        )
        quantities: dict[str, float] = defaultdict(float)
        uom_by_lot: dict[str, str] = {}
        for line in doc.lines:
            if line.lot_no:
                prior_uom = uom_by_lot.setdefault(line.lot_no, line.uom)
                if prior_uom != line.uom:
                    frappe.throw(
                        _("Outward lines for mapped lot {0} use inconsistent UOMs").format(
                            line.lot_no
                        ),
                        title=_("Physical UOM Mismatch"),
                    )
                quantities[line.lot_no] += flt(line.qty)
        for lot_no, quantity in quantities.items():
            assert_mapped_lot_capacity(
                doc.container, lot_no, quantity, uom_by_lot[lot_no]
            )

    doc.flags.in_service = True
    doc.flags.allow_post = True
    doc.status = "Posted"
    doc.posted_by = frappe.session.user
    doc.posted_at = now_datetime()
    doc.save(ignore_permissions=True)

    opened = []
    if doc.movement_type == "OUTWARD":
        opened.append(
            _ensure_open_exception(
                doc,
                "OUTWARD_UNPRICED",
                "Physical Outward posted without an active authorized rate assertion",
                severity="Material",
            )
        )
        if not doc.deal:
            opened.append(
                _ensure_open_exception(
                    doc,
                    "OUTWARD_WITHOUT_DEAL",
                    "Physical Outward posted without an associated commercial Deal",
                    severity="Material",
                )
            )
        if any(not line.lot_no for line in doc.lines):
            opened.append(
                _ensure_open_exception(
                    doc,
                    "LOT_UNRESOLVED",
                    "Physical Outward includes source-backed quantity without an authorized mapped lot",
                    severity="Material",
                )
            )
    elif reversed_outward is not None:
        _resolve_reversed_outward_exceptions(reversed_outward, doc)
    response = _outward_response(doc)
    response["opened_exceptions"] = [name for name in opened if name]
    return response


def create_outward_reversal(
    *,
    outward_name: str,
    movement_at: str,
    source_evidence: str,
    source_event_id: str,
    reason: str,
) -> dict[str, Any]:
    """Create a full compensating Draft reversal; partial reversal is deferred."""
    permissions.assert_can_prepare_outward()
    reason = _clean_text(reason)
    if not reason:
        frappe.throw(_("A reversal reason is required"))
    original = _load_outward_for_update(outward_name)
    if not permissions.outward_has_permission(
        original, "read", user=frappe.session.user
    ):
        frappe.throw(_("Access denied"), frappe.PermissionError)
    if original.status != "Posted" or original.movement_type != "OUTWARD":
        frappe.throw(_("Only a posted OUTWARD movement can be reversed"))
    _assert_evidence_container(source_evidence, original.container)
    source_event_id = _identity_text(source_event_id, "source_event_id")

    source_event_key = _sha256(
        _canonical_json(
            [OUTWARD_PAYLOAD_VERSION, original.container, source_evidence, source_event_id]
        )
    )
    copied_lines = [
        {
            "line_key": _sha256(f"{source_event_key}|line|{line.source_line_ref or line.idx}"),
            "source_line_ref": line.source_line_ref or str(line.idx),
            "raw_lot_text": line.raw_lot_text,
            "lot_no": line.lot_no,
            "batch": line.batch,
            "qty": flt(line.qty),
            "uom": line.uom,
            "raw_qty_text": line.raw_qty_text,
            "raw_uom_text": line.raw_uom_text,
            "raw_rate_text": line.raw_rate_text,
        }
        for line in original.lines
    ]
    payload = {
        "version": OUTWARD_PAYLOAD_VERSION,
        "company": original.company,
        "container": original.container,
        "deal": original.deal,
        # Preserve the source-reported context on a compensating movement;
        # these fields remain raw context and are never resolved to Customer.
        "gatepass_no": original.gatepass_no,
        "vehicle_no": original.vehicle_no,
        "raw_party_name": original.raw_party_name,
        "movement_type": "REVERSAL",
        "movement_at": str(movement_at),
        "source_evidence": source_evidence,
        "source_event_id": source_event_id,
        "posting_reason": reason,
        "reverses_outward": original.name,
        "lines": copied_lines,
    }
    payload_sha256 = _sha256(_canonical_json(payload))
    existing_name = _current_outward_name_by_source_event(source_event_key)
    if existing_name:
        return _outward_replay(existing_name, payload_sha256)
    if _current_reversal_name(original.name):
        frappe.throw(_("A reversal already exists for this Outward"))

    reversal = frappe.get_doc(
        {
            "doctype": "Fresko Outward",
            **{k: v for k, v in payload.items() if k not in {"version", "lines"}},
            "source_event_key": source_event_key,
            "payload_sha256": payload_sha256,
            "status": "Draft",
            "prepared_by": frappe.session.user,
            "prepared_at": now_datetime(),
            "lines": copied_lines,
        }
    )
    reversal.flags.in_service = True
    savepoint = "sp_reversal_" + frappe.generate_hash(length=8)
    frappe.db.savepoint(savepoint)
    try:
        reversal.insert(ignore_permissions=True)
        frappe.db.release_savepoint(savepoint)
    except frappe.UniqueValidationError:
        frappe.db.rollback(save_point=savepoint)
        existing_name = _current_outward_name_by_source_event(source_event_key)
        if existing_name:
            return _outward_replay(existing_name, payload_sha256)
        if _current_reversal_name(original.name):
            frappe.throw(_("A reversal already exists for this Outward"))
        raise
    return _outward_response(reversal)


def _validate_reversal_for_post(reversal):
    original = frappe.get_doc(
        "Fresko Outward", reversal.reverses_outward, for_update=True
    )
    if original.status != "Posted" or original.movement_type != "OUTWARD":
        frappe.throw(_("Reversal target is not a posted OUTWARD movement"))
    posted_other = _current_reversal_name(original.name, exclude=reversal.name)
    if posted_other:
        frappe.throw(_("The original Outward is already reversed"))
    original_shape = [
        (line.lot_no or "", line.uom, flt(line.qty)) for line in original.lines
    ]
    reversal_shape = [
        (line.lot_no or "", line.uom, flt(line.qty)) for line in reversal.lines
    ]
    if original_shape != reversal_shape:
        frappe.throw(_("A full reversal must exactly mirror the original physical lines"))
    return original


def _resolve_reversed_outward_exceptions(original, reversal) -> None:
    names = frappe.get_all(
        "Fresko Exception",
        filters={
            "outward": original.name,
            "exception_type": (
                "in",
                ["OUTWARD_UNPRICED", "OUTWARD_WITHOUT_DEAL", "LOT_UNRESOLVED"],
            ),
            "status": ("in", ["Open", "In Progress"]),
        },
        pluck="name",
    )
    for name in names:
        exception = frappe.get_doc("Fresko Exception", name)
        exception.flags.in_outward_service = True
        exception.status = "Resolved"
        exception.resolution_notes = (
            f"Resolved by full compensating reversal {reversal.name}; "
            "the original source truth remains immutable"
        )
        exception.save(ignore_permissions=True)


def create_rate_assertion(
    *,
    outward_name: str,
    outward_line_key: str | None,
    assertion_basis: str,
    raw_value: str,
    rate: Any,
    evidence: str,
    effective_at: str,
    reason: str,
    supersedes: str | None = None,
    currency: str | None = None,
    rate_uom: str | None = None,
) -> dict[str, Any]:
    permissions.assert_can_prepare_field_assertion()
    outward = _load_outward_for_update(outward_name)
    if not permissions.outward_has_permission(
        outward, "read", user=frappe.session.user
    ):
        frappe.throw(_("Access denied"), frappe.PermissionError)
    if outward.status != "Posted" or outward.movement_type != "OUTWARD":
        frappe.throw(_("Rate assertions require a posted OUTWARD movement"))
    _assert_evidence_container(evidence, outward.container)
    line_key = _clean_text(outward_line_key)
    if line_key and line_key not in {line.line_key for line in outward.lines}:
        frappe.throw(_("outward_line_key is not present on the Outward"))
    rate_text = _canonical_decimal(rate)
    currency = _clean_text(currency)
    rate_uom = _clean_text(rate_uom)
    effective_at_text = str(effective_at) if effective_at is not None else None
    if rate_text is not None and (not currency or not rate_uom or not effective_at_text):
        frappe.throw(
            _("A known rate requires currency, rate_uom, and effective_at")
        )
    _assert_rate_uom_matches_outward(outward, line_key, rate_text, rate_uom)
    if raw_value is None or not str(raw_value).strip():
        frappe.throw(_("raw_value is required"))
    payload = {
        "version": ASSERTION_PAYLOAD_VERSION,
        "outward": outward.name,
        "outward_line_key": line_key,
        "asserted_field": "rate",
        "assertion_basis": assertion_basis,
        "raw_value": str(raw_value),
        "rate": rate_text,
        "currency": currency,
        "rate_uom": rate_uom,
        "evidence": evidence,
        "effective_at": effective_at_text,
        "reason": _clean_text(reason),
        "supersedes": _clean_text(supersedes),
    }
    assertion_key = _sha256(_canonical_json(payload))
    payload_sha256 = _sha256(_canonical_json(payload))
    existing_name = frappe.db.get_value(
        "Fresko Field Assertion", {"assertion_key": assertion_key}, "name"
    )
    if existing_name:
        return _assertion_replay(existing_name, payload_sha256)
    doc = frappe.get_doc(
        {
            "doctype": "Fresko Field Assertion",
            **{k: v for k, v in payload.items() if k != "version"},
            "assertion_key": assertion_key,
            "payload_sha256": payload_sha256,
            "status": "Draft",
            "prepared_by": frappe.session.user,
            "prepared_at": now_datetime(),
        }
    )
    doc.flags.in_service = True
    savepoint = "sp_assertion_" + frappe.generate_hash(length=8)
    frappe.db.savepoint(savepoint)
    try:
        doc.insert(ignore_permissions=True)
        frappe.db.release_savepoint(savepoint)
    except frappe.UniqueValidationError:
        frappe.db.rollback(save_point=savepoint)
        existing_name = _current_assertion_name_by_key(assertion_key)
        if not existing_name:
            raise
        return _assertion_replay(existing_name, payload_sha256)
    return _assertion_response(doc)


def _canonical_decimal(value: Any) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        frappe.throw(_("rate must be a decimal value"))
    if not number.is_finite() or number < 0:
        frappe.throw(_("rate must be finite and non-negative"))
    normalised = format(number.normalize(), "f")
    return "0" if normalised in {"-0", ""} else normalised


def _assertion_response(doc, *, replayed: bool = False) -> dict[str, Any]:
    return {
        "name": doc.name,
        "outward": doc.outward,
        "outward_line_key": doc.outward_line_key,
        "status": doc.status,
        "rate": doc.rate,
        "currency": doc.currency,
        "rate_uom": doc.rate_uom,
        "replayed": replayed,
    }


def _assertion_replay(name: str, payload_sha256: str) -> dict[str, Any]:
    if not permissions.field_assertion_has_permission(
        name, "read", user=frappe.session.user
    ):
        frappe.throw(_("Access denied"), frappe.PermissionError)
    existing = frappe.get_doc("Fresko Field Assertion", name)
    if existing.payload_sha256 != payload_sha256:
        frappe.throw(
            _("Assertion identity already exists with a different payload"),
            frappe.UniqueValidationError,
        )
    return _assertion_response(existing, replayed=True)


def submit_field_assertion(assertion_name: str) -> dict[str, Any]:
    permissions.assert_can_prepare_field_assertion()
    assertion, _outward = _load_assertion_under_container_lock(assertion_name)
    if assertion.prepared_by != frappe.session.user:
        frappe.throw(_("Only the assertion maker may submit it"), frappe.PermissionError)
    if assertion.status == "Review Pending":
        return _assertion_response(assertion, replayed=True)
    if assertion.status != "Draft":
        frappe.throw(_("Only a Draft Field Assertion may be submitted"))
    assertion.flags.in_service = True
    assertion.flags.allow_submit_for_review = True
    assertion.status = "Review Pending"
    assertion.asserted_by = frappe.session.user
    assertion.asserted_at = now_datetime()
    assertion.save(ignore_permissions=True)
    return _assertion_response(assertion)


def review_field_assertion(assertion_name: str, decision: str) -> dict[str, Any]:
    permissions.assert_can_activate_field_assertion()
    assertion, outward = _load_assertion_under_container_lock(assertion_name)
    decision = (decision or "").strip().upper()
    if decision not in {"ACTIVATE", "REJECT"}:
        frappe.throw(_("decision must be ACTIVATE or REJECT"))
    if assertion.status in {"Active", "Rejected"}:
        expected = "Active" if decision == "ACTIVATE" else "Rejected"
        if assertion.status == expected:
            return _assertion_response(assertion, replayed=True)
        frappe.throw(_("Assertion already has a different terminal review decision"))
    if assertion.status != "Review Pending":
        frappe.throw(_("Only a Review Pending assertion may be reviewed"))
    if assertion.prepared_by == frappe.session.user:
        frappe.throw(_("Assertion maker cannot review their own assertion"), frappe.PermissionError)
    assertion.flags.in_service = True
    assertion.reviewed_by = frappe.session.user
    assertion.reviewed_at = now_datetime()
    if decision == "REJECT":
        assertion.flags.allow_reject = True
        assertion.status = "Rejected"
        assertion.save(ignore_permissions=True)
        return _assertion_response(assertion)

    _activate_assertion(assertion, outward)
    assertion.flags.allow_activate = True
    assertion.status = "Active"
    assertion.activated_by = frappe.session.user
    assertion.activated_at = now_datetime()
    assertion.save(ignore_permissions=True)
    _resolve_unpriced_when_complete(outward)
    return _assertion_response(assertion)


def _load_assertion_under_container_lock(assertion_name: str):
    probe = frappe.get_doc("Fresko Field Assertion", assertion_name)
    outward_probe = frappe.get_doc("Fresko Outward", probe.outward)
    lock_container_for_update(outward_probe.container)
    assertion = frappe.get_doc(
        "Fresko Field Assertion", assertion_name, for_update=True
    )
    outward = frappe.get_doc("Fresko Outward", assertion.outward, for_update=True)
    if outward.container != outward_probe.container:
        frappe.throw(_("Assertion Outward changed while acquiring the parent lock"))
    return assertion, outward


def _assert_rate_uom_matches_outward(outward, line_key, rate, rate_uom) -> None:
    if rate is None:
        return
    target_lines = [
        line
        for line in outward.lines
        if not line_key or line.line_key == line_key
    ]
    if not target_lines:
        frappe.throw(_("Rate assertion target line is not present on the Outward"))
    mismatched = sorted({line.uom for line in target_lines if line.uom != rate_uom})
    if mismatched:
        scope = line_key or "header"
        frappe.throw(
            _("Rate UOM {0} does not match Outward {1} target UOM(s): {2}").format(
                rate_uom, scope, ", ".join(mismatched)
            ),
            title=_("Rate UOM Mismatch"),
        )


def _activate_assertion(assertion, outward) -> None:
    _assert_rate_uom_matches_outward(
        outward,
        assertion.outward_line_key,
        assertion.rate,
        assertion.rate_uom,
    )
    active = frappe.db.sql(
        """
        SELECT name
        FROM `tabFresko Field Assertion`
        WHERE outward=%s
          AND IFNULL(outward_line_key, '')=%s
          AND asserted_field=%s
          AND status='Active'
        ORDER BY creation, name
        FOR UPDATE
        """,
        (
            assertion.outward,
            assertion.outward_line_key or "",
            assertion.asserted_field,
        ),
        as_dict=True,
    )
    if assertion.supersedes:
        prior = frappe.get_doc(
            "Fresko Field Assertion", assertion.supersedes, for_update=True
        )
        if prior.status != "Active":
            frappe.throw(_("supersedes must reference the active prior assertion"))
        if (
            prior.outward != assertion.outward
            or (prior.outward_line_key or "") != (assertion.outward_line_key or "")
            or prior.asserted_field != assertion.asserted_field
        ):
            frappe.throw(_("Superseded assertion scope does not match"))
        if any(row.name != prior.name for row in active):
            frappe.throw(_("Assertion scope has an ambiguous active value"))
        successors = frappe.db.sql(
            """
            SELECT name
            FROM `tabFresko Field Assertion`
            WHERE supersedes=%s
              AND status IN ('Active', 'Superseded')
            LIMIT 1 FOR UPDATE
            """,
            (prior.name,),
            as_dict=True,
        )
        if successors:
            frappe.throw(_("The prior assertion already has an activated successor"))
        prior.flags.in_service = True
        prior.flags.allow_supersede = True
        prior.status = "Superseded"
        prior.superseded_by = assertion.name
        prior.save(ignore_permissions=True)
    elif active:
        frappe.throw(_("An active assertion already exists; correction must supersede it"))


def _resolve_unpriced_when_complete(outward) -> None:
    line_keys = {line.line_key for line in outward.lines}
    active = frappe.db.sql(
        """
        SELECT outward_line_key, rate, currency, rate_uom, effective_at
        FROM `tabFresko Field Assertion`
        WHERE outward=%s AND asserted_field='rate' AND status='Active'
        ORDER BY creation, name
        FOR UPDATE
        """,
        (outward.name,),
        as_dict=True,
    )
    priced = [
        row
        for row in active
        if row.rate not in (None, "")
        and row.currency
        and row.rate_uom
        and row.effective_at
    ]
    header_rate = any(not row.outward_line_key for row in priced)
    covered = {row.outward_line_key for row in priced if row.outward_line_key}
    if not header_rate and not line_keys.issubset(covered):
        return
    open_rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabFresko Exception`
        WHERE outward=%s
          AND exception_type='OUTWARD_UNPRICED'
          AND status IN ('Open', 'In Progress')
        FOR UPDATE
        """,
        (outward.name,),
        as_dict=True,
    )
    for row in open_rows:
        exception = frappe.get_doc("Fresko Exception", row.name)
        exception.flags.in_outward_service = True
        exception.status = "Resolved"
        exception.resolution_notes = (
            "Resolved after every Outward line received an active authorized rate assertion"
        )
        exception.save(ignore_permissions=True)


def _ensure_open_exception(
    outward, exception_type: str, description: str, *, severity: str
) -> str:
    existing = frappe.get_all(
        "Fresko Exception",
        filters={
            "outward": outward.name,
            "exception_type": exception_type,
            "status": ("in", ["Open", "In Progress"]),
        },
        pluck="name",
        limit=1,
    )
    if existing:
        return existing[0]
    exception = frappe.get_doc(
        {
            "doctype": "Fresko Exception",
            "exception_type": exception_type,
            "severity": severity,
            "status": "Open",
            "container": outward.container,
            "outward": outward.name,
            "description": description,
        }
    )
    exception.flags.in_outward_service = True
    exception.insert(ignore_permissions=True)
    return exception.name
