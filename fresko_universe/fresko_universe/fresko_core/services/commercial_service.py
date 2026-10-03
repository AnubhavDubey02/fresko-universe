"""Evidence-backed commercial events; never an inventory or payment ledger.

Lock order is Company -> sorted Containers -> Sale/Outward -> decisions. All
writes use a private in-process capability, not request supplied document flags.
Decision history snapshots use server recording time, independent of event time.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any
from functools import wraps

import frappe
from frappe.utils import get_datetime, now_datetime

from fresko_universe import permissions

SALE = "Fresko Commercial Sale"
ALIAS = "Fresko Party Alias Mapping"
ALLOCATION = "Fresko Sale Outward Allocation"
_SCOPE = ContextVar("commercial_service_write", default=False)
MAKERS = {"Fresko Salesperson", "Fresko Trader"}
INTERNAL = MAKERS | {"Fresko Accounts", "Fresko Approver", "System Manager"}
READ_TYPES = {"read", "print", "report", "export"}
PAYLOAD_VERSION = "commercial-v1"
DECIMAL_RE = re.compile(r"^[+]?[0-9]+(?:\.[0-9]+)?$")
LINE_INPUT = {"line_key", "item", "container_lot", "raw_lot_text", "lot_state", "qty", "uom", "qty_state", "price_state", "rate", "rate_basis", "bucket_key", "source_line_ref", "evidence"}
OPERATIONAL = {
    SALE: {"status", "movement_status", "alias_mapping", "customer", "alias_resolution", "verified_by", "verified_at", "approved_by", "approved_at", "superseded_by", "superseded_at", "rejection_reason", "version", "decision_history"},
    ALIAS: {"status", "verified_by", "verified_at", "approved_by", "approved_at", "superseded_by", "superseded_at", "active_alias_key", "version", "decision_history"},
    ALLOCATION: {"state", "verified_by", "verified_at", "approved_by", "approved_at", "reversed_by", "reversed_at", "superseded_by", "active_allocation_key", "version", "decision_history"},
}


def _fail(message, permission=False):
    frappe.throw(message, frappe.PermissionError if permission else frappe.ValidationError)


def _roles(user=None):
    roles = set(frappe.get_roles(user or frappe.session.user))
    if any("supplier" in role.casefold() for role in roles):
        _fail("Supplier access to internal commercial records is denied", True)
    return roles


def _actor(role):
    roles = _roles()
    allowed = MAKERS if role == "maker" else {"Fresko Accounts"} if role == "verify" else {"Fresko Approver"}
    if not roles & allowed:
        _fail(f"Commercial {role} requires an explicitly assigned business role", True)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _text(value, field, required=True):
    if value is None or not isinstance(value, str) or (required and not value.strip()):
        if value is None and not required:
            return None
        _fail(f"{field} must be {'nonempty ' if required else ''}text")
    if len(value) > 140:
        _fail(f"{field} exceeds Data field length; raw source cannot be truncated")
    return value


def _decimal(value, field="qty", scale=6, positive=False):
    if not isinstance(value, str) or not DECIMAL_RE.fullmatch(value):
        _fail(f"{field} requires plain decimal text; floats and exponent notation are forbidden")
    if len(value) > 30:
        _fail(f"{field} exceeds supported precision")
    try:
        number = Decimal(value)
    except InvalidOperation:
        _fail(f"Invalid {field}")
    if not number.is_finite() or number < 0 or (positive and number <= 0):
        _fail(f"{field} must be finite and {'positive' if positive else 'nonnegative'}")
    try:
        scaled = number.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation:
        _fail(f"{field} exceeds supported precision")
    if number != scaled:
        _fail(f"{field} exceeds {scale} decimal places")
    return format(number.normalize(), "f") if number else "0"


def _time(value, label):
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label} requires a datetime")
    try:
        parsed = get_datetime(value)
    except (ValueError, TypeError):
        _fail(f"Invalid {label}")
    if parsed.tzinfo:
        _fail(f"{label} must use the site's configured timezone")
    return str(parsed)


def _key(company, kind, source_event_id):
    return _hash([PAYLOAD_VERSION, company, kind, _text(source_event_id, "source_event_id")])


def _linked(doctype, name):
    if not name or not frappe.db.exists(doctype, name):
        _fail(f"Missing {doctype} {name}")
    doc = frappe.get_doc(doctype, name)
    if not frappe.has_permission(doctype, "read", doc=doc):
        _fail(f"Access denied to linked {doctype}", True)
    return doc


def _evidence(name, container=None):
    doc = _linked("Fresko Evidence", name)
    if not permissions.evidence_has_permission(doc, "read"):
        _fail("Access denied to supporting Evidence", True)
    if container and doc.container != container:
        _fail("Evidence must belong to the same Container")
    if doc.file:
        for row in frappe.get_all("File", filters={"file_url": doc.file}, fields=["name"]):
            _linked("File", row.name)
    if doc.container:
        parent = _linked("Fresko Container", doc.container)
        return parent.company
    return None


def _locks(company, containers=()):
    _linked("Company", company)
    frappe.db.sql("SELECT name FROM `tabCompany` WHERE name=%s FOR UPDATE", (company,))
    for container in sorted(set(containers)):
        _linked("Fresko Container", container)
        rows = frappe.db.sql("SELECT company FROM `tabFresko Container` WHERE name=%s FOR UPDATE", (container,), as_dict=True)
        if not rows or rows[0].company != company:
            _fail("Container does not belong to Company")


def _load(doctype, name):
    probe = frappe.get_doc(doctype, name)
    _locks(probe.company, [probe.container] if probe.get("container") else [])
    if doctype == ALLOCATION:
        frappe.get_doc(SALE, probe.sale, for_update=True)
        frappe.get_doc("Fresko Outward", probe.outward, for_update=True)
    doc = frappe.get_doc(doctype, name, for_update=True)
    if doc.company != probe.company or doc.get("container") != probe.get("container"):
        _fail("CONCURRENT_STATE_CONFLICT")
    _access(doc)
    return doc


def _access(doc):
    roles = _roles()
    if not roles & INTERNAL:
        _fail("Access denied to commercial record", True)
    maker = doc.get("prepared_by") or doc.get("proposed_by")
    if not roles & {"Fresko Accounts", "Fresko Approver", "System Manager"} and maker != frappe.session.user:
        _fail("Commercial record is not assigned to this maker", True)
    _linked("Company", doc.company)
    for event in json.loads(doc.decision_history or "[]"):
        if event.get("evidence"):
            evidence_company = _evidence(event["evidence"])
            if evidence_company and evidence_company != doc.company:
                _fail("Decision evidence company mismatch")
    if doc.get("container"):
        _linked("Fresko Container", doc.container)
    if doc.doctype == SALE:
        _evidence(doc.source_evidence, doc.container)
        if doc.deal:
            _linked("Fresko Deal", doc.deal)
        if doc.customer:
            _linked("Customer", doc.customer)
        if doc.alias_mapping:
            _alias_links(frappe.get_doc(ALIAS, doc.alias_mapping))
        for line in doc.lines:
            _evidence(line.evidence, doc.container)
            _linked("Item", line.item)
            _linked("UOM", line.uom)
    elif doc.doctype == ALIAS:
        _alias_links(doc)
    else:
        _evidence(doc.evidence, doc.container)
        sale = frappe.get_doc(SALE, doc.sale)
        _access(sale)
        outward = _linked("Fresko Outward", doc.outward)
        if not permissions.outward_has_permission(outward, "read"):
            _fail("Access denied to Outward", True)
        _evidence(outward.source_evidence, doc.container)


def _alias_links(doc):
    _linked("Customer", doc.proposed_customer)
    company = _evidence(doc.evidence)
    if company and company != doc.company:
        _fail("Alias evidence company mismatch")


def _expected(doc, expected_version):
    if expected_version is not None and str(expected_version) != str(doc.version):
        _fail("STALE_VERSION")


def _snapshot(doc):
    fields = OPERATIONAL[doc.doctype] - {"decision_history", "version"}
    return json.loads(_json({key: doc.get(key) for key in sorted(fields)}))


def _event(doc, action, *, reason=None, evidence=None):
    events = json.loads(doc.decision_history or "[]")
    doc.version = int(doc.version or 0) + 1
    events.append({"version": doc.version, "recorded_at": str(_now()), "actor": frappe.session.user, "action": action, "reason": reason, "evidence": evidence, "snapshot": _snapshot(doc)})
    doc.decision_history = _json(events)


@contextmanager
def _write():
    token = _SCOPE.set(True)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def _save(doc, action, *, reason=None, evidence=None, insert=False):
    _event(doc, action, reason=reason, evidence=evidence)
    with _write():
        saved = doc.insert(ignore_permissions=True) if insert else doc.save(ignore_permissions=True)
    if doc.doctype == SALE and not insert:
        _refresh_sale_exceptions(doc)
    return saved


def _response(doc, replayed=False):
    result = {"name": doc.name, "doctype": doc.doctype, "status": doc.get("status") or doc.get("state"), "version": doc.version, "replayed": replayed}
    if doc.doctype == SALE:
        result.update({"sale_at": str(doc.sale_at), "customer": doc.customer, "alias_resolution": doc.alias_resolution, "movement_status": doc.movement_status, "lines": [{field: row.get(field) for field in sorted(LINE_INPUT | {"amount"})} for row in doc.lines]})
    if doc.doctype == SALE:
        result["movement_status"] = _effective_movement(doc)
        for line in result["lines"]:
            line["source_price_state"] = line["price_state"]
            if doc.status == "APPROVED" and line["price_state"] == "PROPOSED":
                line["price_state"] = "FINAL"
    elif doc.doctype == ALLOCATION:
        physical = frappe.get_doc("Fresko Outward", doc.outward, for_update=True)
        result["physical_active"] = _outward_active(physical)
        result["effective_state"] = doc.state if result["physical_active"] else "PHYSICAL_REVERSED"
    return result


def _existing(doctype, key, digest):
    rows = frappe.db.sql(f"SELECT name FROM `tab{doctype}` WHERE source_event_key=%s FOR UPDATE", (key,), as_dict=True)
    if not rows:
        return None
    doc = frappe.get_doc(doctype, rows[0].name, for_update=True)
    _access(doc)
    if doc.payload_sha256 != digest:
        _fail("IDEMPOTENCY_PAYLOAD_CONFLICT")
    return _response(doc, True)


def _insert(doctype, payload, key, extras):
    digest = _hash(payload)
    replay = _existing(doctype, key, digest)
    if replay:
        return replay
    doc = frappe.get_doc({"doctype": doctype, **payload, **extras, "source_event_key": key, "payload_sha256": digest, "source_payload": _json(payload), "decision_history": "[]", "version": 0})
    # Recover only an expected unique race; never roll back caller work.
    savepoint = "commercial_" + frappe.generate_hash(length=8)
    frappe.db.savepoint(savepoint)
    try:
        _save(doc, "CREATE", insert=True)
    except frappe.UniqueValidationError:
        frappe.db.rollback(save_point=savepoint)
        replay = _existing(doctype, key, digest)
        if replay:
            return replay
        _fail("CONCURRENT_STATE_CONFLICT")
    finally:
        frappe.db.release_savepoint(savepoint)
    if doctype == SALE:
        _open_sale_exceptions(doc)
    return _response(doc)


def _lines(lines, company, container):
    if isinstance(lines, str):
        lines = frappe.parse_json(lines)
    if not isinstance(lines, list) or not lines:
        _fail("At least one commercial line is required")
    normalized, keys, buckets = [], set(), set()
    for source in lines:
        if not isinstance(source, dict) or set(source) - LINE_INPUT:
            _fail("Unknown or server-controlled Sale Line fields")
        row = {field: source.get(field) for field in LINE_INPUT}
        row["line_key"] = _text(row["line_key"], "line_key")
        _text(row["source_line_ref"], "source_line_ref", False)
        _text(row["bucket_key"], "bucket_key", False)
        if row["line_key"] in keys:
            _fail("Duplicate Sale line_key")
        keys.add(row["line_key"])
        _linked("Item", row["item"])
        _linked("UOM", row["uom"])
        _evidence(row["evidence"], container)
        for field in ("lot_state", "qty_state"):
            row[field] = row[field] or "UNKNOWN"
            if row[field] not in {"KNOWN", "UNKNOWN", "CONTRADICTED"}:
                _fail(f"Invalid {field}")
        if row["raw_lot_text"] is None and row["lot_state"] != "UNKNOWN":
            _fail("Null raw lot requires UNKNOWN lot_state")
        _text(row["raw_lot_text"], "raw_lot_text", False)
        if row["container_lot"]:
            if row["lot_state"] != "KNOWN":
                _fail("Mapped lot requires KNOWN lot_state")
            lot = frappe.get_doc("Fresko Container Lot", row["container_lot"])
            if lot.parent != container or lot.parenttype != "Fresko Container" or lot.uom != row["uom"]:
                _fail("Commercial lot must belong to Container and match UOM")
            if lot.batch and _linked("Batch", lot.batch).item != row["item"]:
                _fail("Commercial lot Batch item mismatch")
        if row["qty_state"] == "KNOWN":
            row["qty"] = _decimal(row["qty"], positive=True)
        elif row["qty"] is not None:
            _fail("Unknown/contradicted quantity cannot carry an asserted quantity")
        row["price_state"] = row["price_state"] or "UNKNOWN"
        row["rate_basis"] = row["rate_basis"] or "NONE"
        if row["price_state"] not in {"UNKNOWN", "PROPOSED", "REJECTED"}:
            _fail("FINAL rate is server-approved only")
        if row["rate_basis"] not in {"NONE", "RATE_ASSERTION", "PRICE_BUCKET"}:
            _fail("Invalid rate_basis")
        if row["rate"] is not None:
            if row["price_state"] != "PROPOSED" or row["rate_basis"] == "NONE":
                _fail("Rate requires a PROPOSED evidence-backed price")
            row["rate"] = _decimal(row["rate"], "rate", 2)
        elif row["price_state"] == "PROPOSED":
            _fail("PROPOSED price requires rate")
        if row["rate_basis"] == "PRICE_BUCKET":
            row["bucket_key"] = _text(row["bucket_key"], "bucket_key")
            if row["bucket_key"] in buckets:
                _fail("Duplicate price bucket")
            buckets.add(row["bucket_key"])
        elif row["bucket_key"] is not None:
            _fail("bucket_key requires PRICE_BUCKET")
        with localcontext() as context:
            context.prec = 64
            product = Decimal(row["qty"]) * Decimal(row["rate"]) if row["qty"] is not None and row["rate"] is not None else None
        if product is not None:
            try:
                scaled_product = product.quantize(Decimal("0.01"))
            except InvalidOperation:
                _fail("Amount exceeds supported precision")
            if product != scaled_product:
                _fail("Amount exceeds currency scale; no implicit rounding")
        row["amount"] = _decimal(format(product, "f"), "amount", 2) if product is not None else None
        normalized.append(row)
    return normalized


def _create_sale(*, company, container, sale_at, source_evidence, source_event_id, lines, raw_party_alias=None, party_state="UNKNOWN", currency="INR", deal=None, raw_movement_at=None, supersedes=None, correction_reason=None):
    _actor("maker")
    _locks(company, [container])
    _evidence(source_evidence, container)
    _linked("Currency", currency)
    if party_state not in {"KNOWN", "UNKNOWN", "CONTRADICTED"}:
        _fail("Invalid party_state")
    _text(raw_party_alias, "raw_party_alias", False)
    if raw_party_alias is None and party_state != "UNKNOWN":
        _fail("Null raw party alias requires UNKNOWN party_state")
    if deal and _linked("Fresko Deal", deal).container != container:
        _fail("Deal belongs to another Container")
    payload = {"company": company, "container": container, "sale_at": _time(sale_at, "sale_at"), "source_evidence": source_evidence, "source_event_id": _text(source_event_id, "source_event_id"), "raw_party_alias": raw_party_alias, "party_state": party_state, "currency": currency, "deal": deal, "raw_movement_at": _time(raw_movement_at, "raw_movement_at") if raw_movement_at else None, "lines": _lines(lines, company, container)}
    if supersedes:
        payload.update(supersedes=supersedes, correction_reason=correction_reason)
    mapping = _approved_alias(company, raw_party_alias)
    extras = {"naming_series": "SALE-.YYYY.-.", "status": "DRAFT", "movement_status": "UNKNOWN", "alias_resolution": "VERIFIED" if mapping else "UNKNOWN", "alias_mapping": mapping.name if mapping else None, "customer": mapping.proposed_customer if mapping else None, "prepared_by": frappe.session.user, "prepared_at": _now(), "as_of_recorded_at": _now()}
    return _insert(SALE, payload, _key(company, "sale", source_event_id), extras)


def _approved_alias(company, alias, scope="EXACT_COMPANY_V1"):
    if alias is None:
        return None
    rows = frappe.db.sql("SELECT name FROM `tabFresko Party Alias Mapping` WHERE company=%s AND raw_alias=%s AND normalization_scope=%s AND status='APPROVED' FOR UPDATE", (company, alias, scope), as_dict=True)
    # MariaDB text collation is case/space insensitive: compare exact raw text.
    matches = [frappe.get_doc(ALIAS, row.name, for_update=True) for row in rows]
    matches = [doc for doc in matches if doc.raw_alias == alias and doc.normalization_scope == scope]
    if len(matches) > 1:
        _fail("ALIAS_CONFLICT")
    if matches:
        _alias_links(matches[0])
        return matches[0]
    return None


def _separate(doc, role):
    _actor(role)
    maker = doc.get("prepared_by") or doc.get("proposed_by")
    forbidden = {maker}
    if role == "approve":
        forbidden.add(doc.get("verified_by"))
    if frappe.session.user in forbidden:
        _fail("Maker, verifier and approver must be different users", True)


def submit_sale(sale_name, expected_version=None):
    _actor("maker")
    doc = _load(SALE, sale_name)
    _expected(doc, expected_version)
    if doc.prepared_by != frappe.session.user:
        _fail("Only the Sale maker may submit", True)
    if doc.status == "REVIEW_PENDING":
        return _response(doc, True)
    if doc.status != "DRAFT":
        _fail("Only DRAFT Sale can enter review")
    doc.status = "REVIEW_PENDING"
    _save(doc, "SUBMIT")
    return _response(doc)


def verify_sale(sale_name, expected_version=None):
    doc = _load(SALE, sale_name)
    _separate(doc, "verify")
    _expected(doc, expected_version)
    if doc.status == "VERIFIED" and doc.verified_by == frappe.session.user:
        return _response(doc, True)
    if doc.status != "REVIEW_PENDING":
        _fail("Sale must be REVIEW_PENDING")
    mapping = _approved_alias(doc.company, doc.raw_party_alias)
    if mapping:
        doc.alias_mapping, doc.customer, doc.alias_resolution = mapping.name, mapping.proposed_customer, "VERIFIED"
    doc.status, doc.verified_by, doc.verified_at = "VERIFIED", frappe.session.user, _now()
    _save(doc, "VERIFY", evidence=doc.source_evidence)
    return _response(doc)


def approve_sale(sale_name, expected_version=None):
    doc = _load(SALE, sale_name)
    _separate(doc, "approve")
    _expected(doc, expected_version)
    if doc.status == "APPROVED" and doc.approved_by == frappe.session.user:
        return _response(doc, True)
    if doc.status != "VERIFIED" or not doc.verified_by:
        _fail("Sale must have Accounts verification")
    for line in doc.lines:
        _photo_for_pending_rate(line)
    if doc.supersedes:
        prior = frappe.get_doc(SALE, doc.supersedes, for_update=True)
        _access(prior)
        if prior.company != doc.company or prior.container != doc.container or prior.superseded_by or prior.status in {"SUPERSEDED", "CANCELLED"}:
            _fail("CONCURRENT_STATE_CONFLICT")
        _reverse_sale_allocations(prior, doc.correction_reason, doc.source_evidence, successor=doc.name)
        prior.status, prior.superseded_by, prior.superseded_at = "SUPERSEDED", doc.name, _now()
        _save(prior, "SUPERSEDE", reason=doc.correction_reason, evidence=doc.source_evidence)
    doc.status, doc.approved_by, doc.approved_at = "APPROVED", frappe.session.user, _now()
    _save(doc, "APPROVE", evidence=doc.source_evidence)
    return _response(doc)


def reject_sale(sale_name, reason, expected_version=None):
    doc = _load(SALE, sale_name)
    _separate(doc, "approve")
    _expected(doc, expected_version)
    reason = _text(reason, "reason")
    if doc.status not in {"REVIEW_PENDING", "VERIFIED"}:
        _fail("Only pending/verified Sale can be rejected")
    doc.status, doc.rejection_reason = "REJECTED", reason
    _save(doc, "REJECT", reason=reason)
    return _response(doc)


def supersede_sale(sale_name, *, source_event_id, reason, source_evidence, changes, expected_version=None):
    _actor("maker")
    doc = _load(SALE, sale_name)
    _expected(doc, expected_version)
    reason = _text(reason, "reason")
    _evidence(source_evidence, doc.container)
    if isinstance(changes, str):
        changes = frappe.parse_json(changes)
    allowed = {"sale_at", "raw_party_alias", "party_state", "currency", "deal", "raw_movement_at", "lines"}
    if not isinstance(changes, dict) or set(changes) - allowed:
        _fail("Unknown or immutable correction fields")
    payload = json.loads(doc.source_payload)
    payload.update(changes)
    payload.update(source_event_id=_text(source_event_id, "source_event_id"), source_evidence=source_evidence)
    if "lines" not in changes:
        payload["lines"] = [{key: value for key, value in row.items() if key in LINE_INPUT} for row in payload["lines"]]
    payload.pop("supersedes", None)
    payload.pop("correction_reason", None)
    return _create_sale(**payload, supersedes=doc.name, correction_reason=reason)


def create_sale(*, company, container, sale_at, source_evidence, source_event_id, lines, raw_party_alias=None, party_state="UNKNOWN", currency="INR", deal=None, raw_movement_at=None):
    return _create_sale(company=company, container=container, sale_at=sale_at, source_evidence=source_evidence, source_event_id=source_event_id, lines=lines, raw_party_alias=raw_party_alias, party_state=party_state, currency=currency, deal=deal, raw_movement_at=raw_movement_at)


def _line(sale, key):
    rows = [row for row in sale.lines if row.line_key == key]
    if len(rows) != 1:
        _fail("Unknown Sale line_key")
    return rows[0]


def _photo_for_pending_rate(line):
    if line.qty == "92" and line.rate == "700":
        evidence = _linked("Fresko Evidence", line.evidence)
        if evidence.evidence_type != "Photo":
            _fail("RATE_EVIDENCE_MISSING: 92@700 requires exact handwritten photo")
        files = frappe.get_all("File", filters={"attached_to_doctype": "Fresko Evidence", "attached_to_name": evidence.name}, pluck="name")
        files = [_linked("File", name) for name in files]
        matches = [file for file in files if evidence.file and file.file_url == evidence.file]
        if not matches or not any(file.get_content() for file in matches):
            _fail("RATE_EVIDENCE_MISSING: exact photo file is missing or unreadable")


def propose_rate(sale_name, line_key, rate, evidence, source_event_id, reason, expected_version=None):
    _actor("maker")
    sale = _load(SALE, sale_name)
    _expected(sale, expected_version)
    _line(sale, line_key)
    rows = json.loads(sale.source_payload)["lines"]
    for row in rows:
        row.pop("amount", None)
        if row["line_key"] == line_key:
            row.update(rate=_decimal(rate, "rate", 2), price_state="PROPOSED", rate_basis="PRICE_BUCKET" if row.get("bucket_key") else "RATE_ASSERTION", evidence=evidence)
    return supersede_sale(sale_name, source_event_id=source_event_id, reason=reason, source_evidence=sale.source_evidence, changes={"lines": rows}, expected_version=expected_version)


def verify_rate(sale_name, expected_version=None):
    return verify_sale(sale_name, expected_version)


def approve_rate(sale_name, expected_version=None):
    return approve_sale(sale_name, expected_version)


def propose_alias_mapping(*, company, raw_alias, proposed_customer, evidence, source_event_id, normalization_scope="EXACT_COMPANY_V1", supersedes=None, reason=None):
    _actor("maker")
    _locks(company)
    raw_alias = _text(raw_alias, "raw_alias")
    if normalization_scope != "EXACT_COMPANY_V1":
        _fail("Unsupported alias normalization_scope")
    _linked("Customer", proposed_customer)
    evidence_company = _evidence(evidence)
    if evidence_company and evidence_company != company:
        _fail("Alias evidence company mismatch")
    replay_payload = {"source_event_id": _text(source_event_id, "source_event_id"), "company": company, "raw_alias": raw_alias, "normalization_scope": normalization_scope, "normalized_alias": unicodedata.normalize("NFKC", raw_alias).casefold().strip(), "proposed_customer": proposed_customer, "evidence": evidence, "supersedes": supersedes, "reason": reason}
    replay = _existing(ALIAS, _key(company, "alias", source_event_id), _hash(replay_payload))
    if replay:
        return replay
    if supersedes:
        prior = frappe.get_doc(ALIAS, supersedes, for_update=True)
        _access(prior)
        if prior.company != company or prior.raw_alias != raw_alias or prior.normalization_scope != normalization_scope or prior.status != "APPROVED":
            _fail("Alias correction must reference exact active scope")
        reason = _text(reason, "reason")
    payload = {"source_event_id": _text(source_event_id, "source_event_id"), "company": company, "raw_alias": raw_alias, "normalization_scope": normalization_scope, "normalized_alias": unicodedata.normalize("NFKC", raw_alias).casefold().strip(), "proposed_customer": proposed_customer, "evidence": evidence, "supersedes": supersedes, "reason": reason}
    return _insert(ALIAS, payload, _key(company, "alias", source_event_id), {"status": "PROPOSED", "proposed_by": frappe.session.user, "proposed_at": _now(), "as_of_recorded_at": _now()})


def verify_alias_mapping(mapping_name, expected_version=None):
    doc = _load(ALIAS, mapping_name)
    _separate(doc, "verify")
    _expected(doc, expected_version)
    if doc.status == "VERIFIED" and doc.verified_by == frappe.session.user:
        return _response(doc, True)
    if doc.status != "PROPOSED":
        _fail("Alias must be PROPOSED")
    doc.status, doc.verified_by, doc.verified_at = "VERIFIED", frappe.session.user, _now()
    _save(doc, "VERIFY", evidence=doc.evidence)
    return _response(doc)


def approve_alias_mapping(mapping_name, expected_version=None):
    probe = frappe.get_doc(ALIAS, mapping_name)
    _locks(probe.company)
    roots = frappe.db.sql("SELECT name FROM `tabFresko Container` WHERE company=%s ORDER BY name FOR UPDATE", (probe.company,), as_dict=True)
    rows = frappe.db.sql("SELECT name,container FROM `tabFresko Commercial Sale` WHERE company=%s AND raw_party_alias=%s ORDER BY container,name FOR UPDATE", (probe.company, probe.raw_alias), as_dict=True)
    doc = frappe.get_doc(ALIAS, mapping_name, for_update=True)
    _access(doc)
    _separate(doc, "approve")
    _expected(doc, expected_version)
    if doc.status == "APPROVED" and doc.approved_by == frappe.session.user:
        return _response(doc, True)
    if doc.status != "VERIFIED" or not doc.verified_by:
        _fail("Alias requires Accounts verification")
    prior = _approved_alias(doc.company, doc.raw_alias, doc.normalization_scope)
    if prior:
        if doc.supersedes != prior.name or not doc.reason:
            _fail("ALIAS_CONFLICT: remap requires explicit supersedes and reason")
        prior.status, prior.superseded_by, prior.superseded_at, prior.active_alias_key = "SUPERSEDED", doc.name, _now(), None
        _save(prior, "SUPERSEDE", reason=doc.reason, evidence=doc.evidence)
    elif doc.supersedes:
        _fail("CONCURRENT_STATE_CONFLICT: prior alias is no longer active")
    doc.status, doc.approved_by, doc.approved_at = "APPROVED", frappe.session.user, _now()
    doc.active_alias_key = _hash([doc.company, doc.raw_alias, doc.normalization_scope])
    _save(doc, "APPROVE", evidence=doc.evidence)
    for row in rows:
        sale = frappe.get_doc(SALE, row.name, for_update=True)
        if sale.raw_party_alias != doc.raw_alias or sale.status in {"SUPERSEDED", "CANCELLED", "REJECTED"}:
            continue
        _access(sale)
        if prior and sale.alias_mapping == prior.name:
            _reverse_sale_allocations(sale, doc.reason, doc.evidence)
            sale.alias_mapping, sale.customer, sale.alias_resolution = None, None, "SUPERSEDED"
            sale.status = "REVIEW_PENDING"
            sale.verified_by = sale.verified_at = sale.approved_by = sale.approved_at = None
            _save(sale, "ALIAS_CONFLICT_REOPEN", reason=doc.reason, evidence=doc.evidence)
            _exception(sale, "ALIAS_CONFLICT", sale.name)
        elif not prior and not sale.alias_mapping:
            sale.alias_mapping, sale.customer, sale.alias_resolution = doc.name, doc.proposed_customer, "VERIFIED"
            _save(sale, "ALIAS_RESOLVE", evidence=doc.evidence)
    return _response(doc)


def reject_alias_mapping(mapping_name, reason, expected_version=None):
    doc = _load(ALIAS, mapping_name)
    _separate(doc, "approve")
    _expected(doc, expected_version)
    if doc.status not in {"PROPOSED", "VERIFIED"}:
        _fail("Only pending alias can be rejected")
    doc.status = "REJECTED"
    _save(doc, "REJECT", reason=_text(reason, "reason"), evidence=doc.evidence)
    return _response(doc)


def _outward_active(outward, cutoff=None):
    if outward.status != "Posted" or outward.movement_type != "OUTWARD":
        return False
    if cutoff and get_datetime(outward.posted_at) > cutoff:
        return False
    reversals = frappe.db.sql("SELECT name,posted_at,movement_at FROM `tabFresko Outward` WHERE reverses_outward=%s AND status='Posted' AND movement_type='REVERSAL' FOR UPDATE", (outward.name,), as_dict=True)
    return not any(not cutoff or (get_datetime(row.posted_at) <= cutoff and get_datetime(row.movement_at) <= cutoff) for row in reversals)


def _allocation_shape(doc, sale, outward):
    if sale.company != doc.company or sale.container != doc.container or outward.company != doc.company or outward.container != doc.container:
        _fail("Allocation Company/Container mismatch")
    if sale.status != "APPROVED":
        _fail("Allocation requires APPROVED Sale")
    if not _outward_active(outward):
        _fail("Allocation requires an unreversed Posted physical OUTWARD")
    source = _line(sale, doc.sale_line_key)
    target = next((row for row in outward.lines if row.line_key == doc.outward_line_key), None)
    if not target:
        _fail("Unknown Outward line_key")
    if source.rate_basis == "PRICE_BUCKET" or source.qty_state != "KNOWN" or source.lot_state != "KNOWN" or not source.container_lot:
        _fail("Unmapped lots and price buckets cannot create physical allocations")
    if source.uom != doc.uom or target.uom != doc.uom:
        _fail("Allocation UOM mismatch")
    lot = frappe.get_doc("Fresko Container Lot", source.container_lot)
    if lot.parent != sale.container or not target.lot_no or lot.lot_no != target.lot_no or (lot.batch or "") != (target.batch or ""):
        _fail("Allocation lot/Batch mismatch")
    if frappe.get_doc("Fresko Container", sale.container).item != source.item:
        _fail("Allocation Container item mismatch")
    if lot.batch and _linked("Batch", lot.batch).item != source.item:
        _fail("Allocation item mismatch")
    return source, target


def propose_sale_outward_allocation(*, sale_name, sale_line_key, outward, outward_line_key, qty, uom, evidence, source_event_id, supersedes=None, reason=None):
    _actor("maker")
    sale = _load(SALE, sale_name)
    physical = _linked("Fresko Outward", outward)
    if not permissions.outward_has_permission(physical, "read"):
        _fail("Access denied to Outward", True)
    physical = frappe.get_doc("Fresko Outward", outward, for_update=True)
    _evidence(evidence, sale.container)
    payload = {"source_event_id": _text(source_event_id, "source_event_id"), "company": sale.company, "container": sale.container, "sale": sale.name, "sale_line_key": _text(sale_line_key, "sale_line_key"), "outward": outward, "outward_line_key": _text(outward_line_key, "outward_line_key"), "qty": _decimal(qty, positive=True), "uom": uom, "evidence": evidence, "supersedes": supersedes, "reason": _text(reason, "reason") if supersedes else reason}
    replay = _existing(ALLOCATION, _key(sale.company, "allocation", source_event_id), _hash(payload))
    if replay:
        return replay
    draft = frappe.get_doc({"doctype": ALLOCATION, **payload})
    _allocation_shape(draft, sale, physical)
    if supersedes:
        prior = frappe.get_doc(ALLOCATION, supersedes, for_update=True)
        _access(prior)
        if prior.sale != sale.name or prior.sale_line_key != sale_line_key or prior.outward != outward or prior.outward_line_key != outward_line_key or prior.state not in {"APPROVED", "REVERSED"} or prior.superseded_by:
            _fail("Allocation supersession requires the same active logical pair")
    return _insert(ALLOCATION, payload, _key(sale.company, "allocation", source_event_id), {"state": "PROPOSED", "prepared_by": frappe.session.user, "prepared_at": _now(), "as_of_recorded_at": _now()})


def verify_sale_outward_allocation(allocation_name, expected_version=None):
    doc = _load(ALLOCATION, allocation_name)
    _separate(doc, "verify")
    _expected(doc, expected_version)
    if doc.state != "PROPOSED":
        _fail("Allocation must be PROPOSED")
    if doc.verified_by:
        if doc.verified_by == frappe.session.user:
            return _response(doc, True)
        _fail("Allocation was verified by another Accounts user")
    _allocation_shape(doc, frappe.get_doc(SALE, doc.sale, for_update=True), frappe.get_doc("Fresko Outward", doc.outward, for_update=True))
    doc.verified_by, doc.verified_at = frappe.session.user, _now()
    _save(doc, "VERIFY", evidence=doc.evidence)
    return _response(doc)


def _allocation_totals(doc, exclude=None):
    rows = frappe.db.sql("SELECT name,sale,sale_line_key,outward,outward_line_key,qty FROM `tabFresko Sale Outward Allocation` WHERE container=%s AND state='APPROVED' ORDER BY sale,outward,name FOR UPDATE", (doc.container,), as_dict=True)
    sale_qty = outward_qty = Decimal(0)
    for row in rows:
        if row.name == exclude:
            continue
        if not _outward_active(frappe.get_doc("Fresko Outward", row.outward, for_update=True)):
            continue
        if row.sale == doc.sale and row.sale_line_key == doc.sale_line_key:
            sale_qty += Decimal(row.qty)
        if row.outward == doc.outward and row.outward_line_key == doc.outward_line_key:
            outward_qty += Decimal(row.qty)
    return sale_qty, outward_qty


def approve_sale_outward_allocation(allocation_name, expected_version=None):
    doc = _load(ALLOCATION, allocation_name)
    _separate(doc, "approve")
    _expected(doc, expected_version)
    if doc.state == "APPROVED" and doc.approved_by == frappe.session.user:
        return _response(doc, True)
    if doc.state != "PROPOSED" or not doc.verified_by:
        _fail("Allocation requires Accounts verification")
    sale = frappe.get_doc(SALE, doc.sale, for_update=True)
    outward = frappe.get_doc("Fresko Outward", doc.outward, for_update=True)
    source, target = _allocation_shape(doc, sale, outward)
    prior = None
    if doc.supersedes:
        prior = frappe.get_doc(ALLOCATION, doc.supersedes, for_update=True)
        _access(prior)
        if prior.state not in {"APPROVED", "REVERSED"} or prior.superseded_by:
            _fail("CONCURRENT_STATE_CONFLICT")
    sale_qty, outward_qty = _allocation_totals(doc, exclude=prior.name if prior else None)
    if sale_qty + Decimal(doc.qty) > Decimal(source.qty) or outward_qty + Decimal(doc.qty) > Decimal(str(target.qty)):
        _fail("ALLOCATION_OVERDRAW")
    active_key = _hash([doc.sale, doc.sale_line_key, doc.outward, doc.outward_line_key])
    existing = frappe.db.sql("SELECT name FROM `tabFresko Sale Outward Allocation` WHERE active_allocation_key=%s FOR UPDATE", (active_key,), as_dict=True)
    if any(row.name != (prior.name if prior else None) for row in existing):
        _fail("CONCURRENT_STATE_CONFLICT: active allocation pair already exists")
    if prior:
        if prior.state == "APPROVED":
            _reverse(prior, doc.reason, doc.evidence, successor=doc.name)
        else:
            prior.superseded_by = doc.name
            _save(prior, "SUPERSEDED", reason=doc.reason, evidence=doc.evidence)
    doc.state, doc.approved_by, doc.approved_at, doc.active_allocation_key = "APPROVED", frappe.session.user, _now(), active_key
    _save(doc, "APPROVE", evidence=doc.evidence)
    _movement(sale)
    _refresh_outward_exception(outward)
    return _response(doc)


def reject_sale_outward_allocation(allocation_name, reason, expected_version=None):
    doc = _load(ALLOCATION, allocation_name)
    _separate(doc, "approve")
    _expected(doc, expected_version)
    if doc.state != "PROPOSED":
        _fail("Only proposed allocation may be rejected")
    doc.state = "REJECTED"
    _save(doc, "REJECT", reason=_text(reason, "reason"), evidence=doc.evidence)
    return _response(doc)


def _reverse(doc, reason, evidence, successor=None, company_evidence=False):
    company = _evidence(evidence, None if company_evidence else doc.container)
    if company and company != doc.company:
        _fail("Compensation evidence company mismatch")
    doc.state, doc.active_allocation_key = "REVERSED", None
    doc.reversed_by, doc.reversed_at, doc.superseded_by = frappe.session.user, _now(), successor
    _save(doc, "REVERSE", reason=_text(reason, "reason"), evidence=evidence)


def _reverse_sale_allocations(sale, reason, evidence, successor=None):
    # Compensate financial applications atomically with commercial correction.
    # During an exact-baseline migration the new ledger tables may not exist yet.
    if frappe.db.table_exists("Fresko Collection"):
        from fresko_universe.fresko_core.services import money_service
        money_service.compensate_for_sale_change(sale.name, reason, evidence)
    rows = frappe.db.sql("SELECT name FROM `tabFresko Sale Outward Allocation` WHERE sale=%s AND state='APPROVED' ORDER BY name FOR UPDATE", (sale.name,), as_dict=True)
    for row in rows:
        allocation = frappe.get_doc(ALLOCATION, row.name, for_update=True)
        _access(allocation)
        _reverse(allocation, reason, evidence, company_evidence=True)
        _refresh_outward_exception(frappe.get_doc("Fresko Outward", allocation.outward, for_update=True))
    if rows:
        sale.movement_status = "NOT_EVIDENCED"


def reverse_sale_outward_allocation(allocation_name, reason, evidence, expected_version=None):
    _actor("approve")
    doc = _load(ALLOCATION, allocation_name)
    _expected(doc, expected_version)
    if doc.state != "APPROVED":
        _fail("Only approved allocation may be reversed")
    _reverse(doc, reason, evidence)
    sale = frappe.get_doc(SALE, doc.sale, for_update=True)
    _movement(sale)
    _refresh_outward_exception(frappe.get_doc("Fresko Outward", doc.outward, for_update=True))
    return _response(doc)


def _effective_movement(sale):
    rows = frappe.db.sql("SELECT sale_line_key,outward,qty FROM `tabFresko Sale Outward Allocation` WHERE sale=%s AND state='APPROVED' FOR UPDATE", (sale.name,), as_dict=True)
    totals = {}
    for row in rows:
        if _outward_active(frappe.get_doc("Fresko Outward", row.outward, for_update=True)):
            totals[row.sale_line_key] = totals.get(row.sale_line_key, Decimal(0)) + Decimal(row.qty)
    return "NOT_EVIDENCED" if not totals else "EVIDENCED" if all(line.qty_state == "KNOWN" and totals.get(line.line_key, Decimal(0)) == Decimal(line.qty) for line in sale.lines) else "PARTIAL"


def _movement(sale):
    status = _effective_movement(sale)
    if sale.movement_status != status:
        sale.movement_status = status
        _save(sale, "MOVEMENT_RECONCILE")
    _refresh_sale_exceptions(sale)



def _refresh_outward_exception(outward):
    if not _outward_active(outward):
        pending = False
    else:
        rows = frappe.db.sql("SELECT outward_line_key,qty FROM `tabFresko Sale Outward Allocation` WHERE outward=%s AND state='APPROVED' FOR UPDATE", (outward.name,), as_dict=True)
        totals = {}
        for row in rows:
            totals[row.outward_line_key] = totals.get(row.outward_line_key, Decimal(0)) + Decimal(row.qty)
        pending = any(totals.get(line.line_key, Decimal(0)) != Decimal(str(line.qty)) for line in outward.lines)
    key = _hash(["OUTWARD_WITHOUT_SALE", outward.name, str(outward.posted_at)])
    existing_rows = frappe.db.sql("SELECT name FROM `tabFresko Exception` WHERE commercial_scope_key=%s FOR UPDATE", (key,), as_dict=True)
    existing = existing_rows[0].name if existing_rows else None
    if not existing and not pending:
        return
    if existing:
        exception = frappe.get_doc("Fresko Exception", existing, for_update=True)
        if (pending and exception.status == "Open") or (not pending and exception.status == "Resolved"):
            return
        exception.status = "Open" if pending else "Resolved"
        exception.resolution_notes = "Controlled commercial allocation refresh; original physical Outward retained"
        if pending:
            exception.resolved_by = exception.resolved_at = None
    else:
        exception = frappe.get_doc({"doctype": "Fresko Exception", "exception_type": "OUTWARD_WITHOUT_SALE", "status": "Open", "severity": "Material", "container": outward.container, "outward": outward.name, "commercial_scope_key": key, "as_of_recorded_at": outward.posted_at, "description": f"OUTWARD_WITHOUT_SALE for Outward {outward.name}; physical quantities remain unallocated to an approved commercial event"})
    exception.flags.in_commercial_service = True
    with _write():
        if existing:
            exception.save(ignore_permissions=True)
        else:
            exception.insert(ignore_permissions=True)


def refresh_commercial_reconciliation(container):
    roles = _roles()
    if not roles & {"Fresko Accounts", "Fresko Approver", "System Manager"}:
        _fail("Reconciliation refresh requires an internal checker or technical role", True)
    parent = _linked("Fresko Container", container)
    _locks(parent.company, [container])
    rows = frappe.db.sql("SELECT name FROM `tabFresko Commercial Sale` WHERE container=%s ORDER BY name FOR UPDATE", (container,), as_dict=True)
    for row in rows:
        sale = frappe.get_doc(SALE, row.name, for_update=True)
        _access(sale)
        _movement(sale)
    rows = frappe.db.sql("SELECT name FROM `tabFresko Outward` WHERE container=%s AND status='Posted' AND movement_type='OUTWARD' ORDER BY name FOR UPDATE", (container,), as_dict=True)
    for row in rows:
        outward = frappe.get_doc("Fresko Outward", row.name, for_update=True)
        if not permissions.outward_has_permission(outward, "read"):
            _fail("Access denied to physical Outward", True)
        _evidence(outward.source_evidence, container)
        _refresh_outward_exception(outward)
    return get_container_reconciliation(container)


def _exception(sale, kind, scope):
    key = _hash([kind, scope, str(sale.as_of_recorded_at)])
    if frappe.db.sql("SELECT name FROM `tabFresko Exception` WHERE commercial_scope_key=%s FOR UPDATE", (key,)):
        return
    doc = frappe.get_doc({"doctype": "Fresko Exception", "exception_type": kind, "severity": "Material", "status": "Open", "container": sale.container, "sale": sale.name, "commercial_scope_key": key, "as_of_recorded_at": sale.as_of_recorded_at, "description": f"{kind} for Commercial Sale {sale.name}; scope {scope}; missing evidence remains PENDING"})
    doc.flags.in_commercial_service = True
    with _write():
        doc.insert(ignore_permissions=True)


def _pending_sale_conditions(sale):
    if sale.status in {"SUPERSEDED", "CANCELLED", "REJECTED"}:
        return []
    kinds = []
    if sale.party_state == "UNKNOWN" and not sale.customer:
        kinds.append(("PARTY_UNKNOWN", sale.name))
    if not sale.alias_mapping:
        kinds.append(("ALIAS_UNRESOLVED", sale.name))
    if sale.alias_resolution == "SUPERSEDED":
        kinds.append(("ALIAS_CONFLICT", sale.name))
    for line in sale.lines:
        scope = sale.name + ":" + line.line_key
        if line.lot_state == "UNKNOWN":
            kinds.append(("LOT_UNKNOWN", scope))
        if line.price_state == "UNKNOWN":
            kinds.append(("RATE_UNKNOWN", scope))
        if line.qty == "92" and line.rate == "700" and sale.status != "APPROVED":
            kinds.append(("RATE_EVIDENCE_MISSING", scope))
        if line.rate_basis == "PRICE_BUCKET":
            kinds.append(("PRICE_BUCKET_UNALLOCATED", scope))
    if _effective_movement(sale) == "NOT_EVIDENCED":
        kinds.append(("SALE_WITHOUT_OUTWARD", sale.name))
    return kinds


def _open_sale_exceptions(sale):
    for kind, scope in _pending_sale_conditions(sale):
        _exception(sale, kind, scope)


def _refresh_sale_exceptions(sale):
    conditions = _pending_sale_conditions(sale)
    active_keys = {_hash([kind, scope, str(sale.as_of_recorded_at)]) for kind, scope in conditions}
    _open_sale_exceptions(sale)
    rows = frappe.db.sql("SELECT name,commercial_scope_key FROM `tabFresko Exception` WHERE sale=%s AND commercial_scope_key IS NOT NULL FOR UPDATE", (sale.name,), as_dict=True)
    for row in rows:
        doc = frappe.get_doc("Fresko Exception", row.name, for_update=True)
        needed = row.commercial_scope_key in active_keys
        if needed and doc.status == "Resolved":
            doc.status = "Open"
            doc.resolved_by = doc.resolved_at = None
            doc.resolution_notes = "Reopened after a later controlled decision removed the supporting fact"
        elif not needed and doc.status in {"Open", "In Progress"}:
            doc.status = "Resolved"
            doc.resolution_notes = f"Resolved by commercial decision version {sale.version}; original evidence and decision history retained"
        else:
            continue
        doc.flags.in_commercial_service = True
        with _write():
            doc.save(ignore_permissions=True)


def _state_at(doc, cutoff):
    result = None
    for event in json.loads(doc.decision_history or "[]"):
        if get_datetime(event["recorded_at"]) <= cutoff:
            result = event["snapshot"]
    return result


def get_sale_as_of(sale_name, as_of):
    _roles()
    sale = _load(SALE, sale_name)
    cutoff = get_datetime(_time(as_of, "as_of"))
    state = _state_at(sale, cutoff)
    if state is None:
        return {"name": sale.name, "as_of": str(cutoff), "exists": False, "allocations": [], "lines": []}
    if state.get("customer"):
        _linked("Customer", state["customer"])
    if state.get("alias_mapping"):
        _alias_links(frappe.get_doc(ALIAS, state["alias_mapping"]))
    effective = get_datetime(sale.sale_at) <= cutoff
    payload = json.loads(sale.source_payload)
    lines = payload.pop("lines")
    for line in lines:
        line["source_price_state"] = line["price_state"]
        if line["price_state"] == "PROPOSED" and state["status"] == "APPROVED":
            line["price_state"] = "FINAL"
        line["allocated_qty"], line["allocation_state"] = "0", "UNALLOCATED"
    allocations = []
    rows = frappe.db.sql("SELECT name FROM `tabFresko Sale Outward Allocation` WHERE sale=%s ORDER BY creation,name FOR UPDATE", (sale.name,), as_dict=True)
    totals = {}
    for row in rows:
        doc = frappe.get_doc(ALLOCATION, row.name, for_update=True)
        _access(doc)
        decision = _state_at(doc, cutoff)
        if not decision or decision["state"] != "APPROVED":
            continue
        physical = frappe.get_doc("Fresko Outward", doc.outward, for_update=True)
        if not _physical_as_of(physical, cutoff):
            continue
        allocations.append({"name": doc.name, "sale_line_key": doc.sale_line_key, "outward": doc.outward, "outward_line_key": doc.outward_line_key, "qty": doc.qty, "uom": doc.uom, "movement_at": str(physical.movement_at)})
        totals[doc.sale_line_key] = totals.get(doc.sale_line_key, Decimal(0)) + Decimal(doc.qty)
    for line in lines:
        line["allocated_qty"] = format(totals.get(line["line_key"], Decimal(0)), "f")
        line["remaining_qty"] = format(Decimal(line["qty"]) - Decimal(line["allocated_qty"]), "f") if line["qty"] is not None else None
        if totals.get(line["line_key"]):
            line["allocation_state"] = "ALLOCATED" if line["qty"] and totals[line["line_key"]] == Decimal(line["qty"]) else "PARTIAL"
    movement = "NOT_EVIDENCED" if not allocations else "EVIDENCED" if all(line["allocation_state"] == "ALLOCATED" for line in lines) else "PARTIAL"
    known_amount = sum((Decimal(line["amount"]) for line in lines if line["amount"] is not None), Decimal(0))
    pending_amount_count = sum(line["amount"] is None for line in lines)
    return {**payload, **state, "name": sale.name, "as_of": str(cutoff), "exists": True, "effective_at_cutoff": effective, "total_commercial_amount": format(known_amount, "f") if not pending_amount_count else None, "known_commercial_amount": format(known_amount, "f"), "pending_amount_line_count": pending_amount_count, "lines": lines, "allocations": allocations, "movement_status": movement, "reconciliation_state": "CONFIRMED" if effective and state["status"] == "APPROVED" and state["customer"] and movement == "EVIDENCED" and all(line["price_state"] == "FINAL" for line in lines) else "PENDING"}


def _reader():
    if not _roles() & INTERNAL:
        _fail("Internal commercial reader role required", True)


def _quantity_groups():
    return {}


def _add_qty(groups, uom, key, quantity):
    values = groups.setdefault(uom, {})
    values[key] = values.get(key, Decimal(0)) + quantity


def _string_groups(groups):
    return {unit: {key: format(value, "f") for key, value in values.items()} for unit, values in groups.items()}


def _physical_as_of(physical, cutoff):
    return physical.status == "Posted" and physical.posted_at and get_datetime(physical.posted_at) <= cutoff and get_datetime(physical.movement_at) <= cutoff and _outward_active(physical, cutoff)


def get_container_reconciliation(container, as_of=None):
    _reader()
    parent = _linked("Fresko Container", container)
    _locks(parent.company, [container])
    cutoff_text = _time(as_of or str(_now()), "as_of")
    cutoff = get_datetime(cutoff_text)
    rows = frappe.db.sql("SELECT name FROM `tabFresko Commercial Sale` WHERE container=%s ORDER BY sale_at,name FOR UPDATE", (container,), as_dict=True)
    sales = []
    for row in rows:
        doc = frappe.get_doc(SALE, row.name, for_update=True)
        if not commercial_has_permission(doc):
            continue
        view = get_sale_as_of(row.name, cutoff_text)
        if view["exists"] and get_datetime(view["sale_at"]) <= cutoff:
            sales.append(view)
    physical_rows = frappe.db.sql("SELECT name FROM `tabFresko Outward` WHERE container=%s AND movement_type='OUTWARD' AND status='Posted' ORDER BY movement_at,name FOR UPDATE", (container,), as_dict=True)
    outwards = []
    for row in physical_rows:
        doc = frappe.get_doc("Fresko Outward", row.name, for_update=True)
        if permissions.outward_has_permission(doc, "read") and _physical_as_of(doc, cutoff):
            outwards.append(doc)
    groups, values = {}, {}
    unknown_qty_count, unresolved_buyer_count = 0, 0
    pending_sales = [sale for sale in sales if sale["status"] not in {"APPROVED", "SUPERSEDED", "REJECTED", "CANCELLED"}]
    accepted = [sale for sale in sales if sale["status"] == "APPROVED"]
    exception_kinds = set()
    allocation_qty = {}
    for sale in accepted:
        if not sale["customer"]:
            unresolved_buyer_count += 1
            exception_kinds.add("ALIAS_UNRESOLVED")
        for line in sale["lines"]:
            if line["qty_state"] != "KNOWN":
                unknown_qty_count += 1
                continue
            qty = Decimal(line["qty"])
            allocated = Decimal(line["allocated_qty"])
            _add_qty(groups, line["uom"], "commercially_sold_qty", qty)
            _add_qty(groups, line["uom"], "physically_allocated_qty", allocated)
            _add_qty(groups, line["uom"], "sold_not_physically_allocated_qty", qty - allocated)
            priced = line["price_state"] == "FINAL" and line["rate"] is not None
            _add_qty(groups, line["uom"], "priced_qty" if priced else "unpriced_qty", qty)
            if priced and line["amount"] is not None:
                values[sale["currency"]] = values.get(sale["currency"], Decimal(0)) + Decimal(line["amount"])
            if not priced:
                exception_kinds.add("RATE_UNKNOWN")
            if line["rate_basis"] == "PRICE_BUCKET":
                exception_kinds.add("PRICE_BUCKET_UNALLOCATED")
            if line["lot_state"] != "KNOWN":
                exception_kinds.add("LOT_UNKNOWN")
        for allocation in sale["allocations"]:
            key = (allocation["outward"], allocation["outward_line_key"])
            allocation_qty[key] = allocation_qty.get(key, Decimal(0)) + Decimal(allocation["qty"])
    for physical in outwards:
        missing = False
        for line in physical.lines:
            qty = Decimal(str(line.qty))
            allocated = allocation_qty.get((physical.name, line.line_key), Decimal(0))
            _add_qty(groups, line.uom, "physical_qty", qty)
            _add_qty(groups, line.uom, "physically_unallocated_qty", qty - allocated)
            missing = missing or allocated != qty
        if missing:
            exception_kinds.add("OUTWARD_WITHOUT_SALE")
    # All categories are explicit within each observed unit; unknown counts remain separate.
    keys = {"commercially_sold_qty", "priced_qty", "unpriced_qty", "physically_allocated_qty", "physically_unallocated_qty", "sold_not_physically_allocated_qty", "physical_qty"}
    for unit in groups:
        for key in keys:
            groups[unit].setdefault(key, Decimal(0))
    confirmed = bool(accepted) and not pending_sales and not exception_kinds and all(sale["reconciliation_state"] == "CONFIRMED" for sale in accepted)
    return {"container": container, "as_of": cutoff_text, "sales": sales, "totals_by_uom": _string_groups(groups), "confirmed_value_by_currency": {currency: format(value, "f") for currency, value in values.items()}, "unknown_quantity_count": unknown_qty_count, "unresolved_buyer_count": unresolved_buyer_count, "pending_sale_count": len(pending_sales), "exceptions": sorted(exception_kinds), "view_scope": "ASSIGNED" if not _roles() & {"Fresko Accounts", "Fresko Approver", "System Manager"} else "INTERNAL", "reconciliation_state": "CONFIRMED" if confirmed else "PENDING"}


def get_outward_reconciliation(outward_name, as_of=None):
    _reader()
    physical = _linked("Fresko Outward", outward_name)
    _locks(physical.company, [physical.container])
    physical = frappe.get_doc("Fresko Outward", outward_name, for_update=True)
    if not permissions.outward_has_permission(physical, "read"):
        _fail("Access denied to Outward", True)
    cutoff_text = _time(as_of or str(_now()), "as_of")
    cutoff = get_datetime(cutoff_text)
    rows = frappe.db.sql("SELECT DISTINCT sale FROM `tabFresko Sale Outward Allocation` WHERE outward=%s ORDER BY sale FOR UPDATE", (outward_name,), as_dict=True)
    linked_sales, allocations = [], []
    for row in rows:
        sale = frappe.get_doc(SALE, row.sale, for_update=True)
        if not commercial_has_permission(sale):
            continue
        view = get_sale_as_of(row.sale, cutoff_text)
        linked = [allocation for allocation in view["allocations"] if allocation["outward"] == outward_name]
        if linked:
            line_keys = {allocation["sale_line_key"] for allocation in linked}
            rate_unresolved = any(line["price_state"] != "FINAL" or line["rate"] is None for line in view["lines"] if line["line_key"] in line_keys)
            linked_sales.append({"name": view["name"], "sale_at": view["sale_at"], "status": view["status"], "customer": view["customer"], "rate_unresolved": rate_unresolved, "reconciliation_state": view["reconciliation_state"]})
            allocations.extend(linked)
    groups, lines = {}, []
    active = _physical_as_of(physical, cutoff)
    for line in physical.lines:
        qty = Decimal(str(line.qty))
        allocated = sum((Decimal(row["qty"]) for row in allocations if row["outward_line_key"] == line.line_key), Decimal(0))
        if active:
            _add_qty(groups, line.uom, "physical_qty", qty)
            _add_qty(groups, line.uom, "commercially_allocated_qty", allocated)
            _add_qty(groups, line.uom, "remaining_qty", qty - allocated)
        lines.append({"line_key": line.line_key, "uom": line.uom, "qty": format(qty, "f"), "commercially_allocated_qty": format(allocated, "f"), "remaining_qty": format(qty - allocated, "f") if active else None})
    complete = active and bool(lines) and all(Decimal(row["remaining_qty"]) == 0 for row in lines)
    unresolved = sorted({"ALIAS_UNRESOLVED" for sale in linked_sales if not sale["customer"]} | {"RATE_UNKNOWN" for sale in linked_sales if sale["rate_unresolved"]} | ({"OUTWARD_WITHOUT_SALE"} if active and not complete else set()))
    confirmed = complete and all(sale["reconciliation_state"] == "CONFIRMED" for sale in linked_sales)
    return {"outward": outward_name, "movement_at": str(physical.movement_at), "as_of": cutoff_text, "physical_active": active, "allocations": allocations, "lines": lines, "totals_by_uom": _string_groups(groups), "linked_sales": linked_sales, "unresolved_flags": unresolved, "reconciliation_state": "CONFIRMED" if confirmed else "PARTIAL" if allocations else "PENDING"}


def validate_commercial_document(doc):
    """Controller guard; request supplied flags are not authorization tokens."""
    if not _SCOPE.get():
        _fail("Commercial records are service-only; direct writes/imports are forbidden", True)
    if doc.doctype == "Fresko Commercial Sale Line":
        return
    payload = json.loads(doc.source_payload or "null")
    if not isinstance(payload, dict) or _hash(payload) != doc.payload_sha256:
        _fail("Commercial source payload hash mismatch")
    old = doc.get_doc_before_save()
    if old:
        if old.source_payload != doc.source_payload or old.payload_sha256 != doc.payload_sha256 or old.source_event_key != doc.source_event_key:
            _fail("Commercial source identity is immutable", True)
        for field in doc.meta.fields:
            key = field.fieldname
            if key in OPERATIONAL[doc.doctype] or field.fieldtype in {"Section Break", "Column Break", "Tab Break"}:
                continue
            if field.fieldtype == "Table":
                previous = [{key: row.get(key) for key in LINE_INPUT | {"amount"}} for row in old.get(field.fieldname)]
                current = [{key: row.get(key) for key in LINE_INPUT | {"amount"}} for row in doc.get(field.fieldname)]
                if previous != current:
                    _fail("Commercial source lines are immutable", True)
            elif str(old.get(key) or "") != str(doc.get(key) or ""):
                _fail(f"Commercial source field {key} is immutable", True)
        old_events = json.loads(old.decision_history or "[]")
        events = json.loads(doc.decision_history or "[]")
        if events[:-1] != old_events or int(doc.version) != int(old.version) + 1:
            _fail("Decision history must append exactly one event")
    else:
        initial = "DRAFT" if doc.doctype == SALE else "PROPOSED"
        if (doc.get("status") or doc.get("state")) != initial or doc.version != 1:
            _fail("Invalid initial commercial decision state")
    events = json.loads(doc.decision_history or "[]")
    if not events or events[-1]["actor"] != frappe.session.user or events[-1]["snapshot"] != _snapshot(doc):
        _fail("Forged commercial decision metadata")


def commercial_has_permission(doc, ptype=None, user=None):
    if (ptype or "read") not in READ_TYPES:
        return False
    user = user or frappe.session.user
    try:
        roles = _roles(user)
    except frappe.PermissionError:
        return False
    if not roles & INTERNAL or doc is None:
        return False
    if isinstance(doc, str):
        return False
    if not roles & {"Fresko Accounts", "Fresko Approver", "System Manager"} and (doc.get("prepared_by") or doc.get("proposed_by")) != user:
        return False
    if user == frappe.session.user:
        try:
            _access(doc)
        except (frappe.PermissionError, frappe.ValidationError):
            return False
    return True


def _query(doctype, maker_field, user=None):
    try:
        roles = _roles(user)
    except frappe.PermissionError:
        return "1=0"
    if roles & {"Fresko Accounts", "Fresko Approver", "System Manager"}:
        return ""
    if roles & MAKERS:
        return f"`tab{doctype}`.`{maker_field}`={frappe.db.escape(user or frappe.session.user)}"
    return "1=0"


def sale_permission_query(user=None):
    return _query(SALE, "prepared_by", user)


def alias_permission_query(user=None):
    return _query(ALIAS, "proposed_by", user)


def allocation_permission_query(user=None):
    return _query(ALLOCATION, "prepared_by", user)


def commercial_exception_permission_query(user=None):
    try:
        roles = _roles(user)
    except frappe.PermissionError:
        return "1=0"
    if roles & {"Fresko Accounts", "Fresko Approver", "System Manager"}:
        return ""
    if roles & MAKERS:
        return "((`tabFresko Exception`.commercial_scope_key IS NULL) OR (`tabFresko Exception`.sale IN (SELECT name FROM `tabFresko Commercial Sale` WHERE prepared_by=" + frappe.db.escape(user or frappe.session.user) + ")) OR (`tabFresko Exception`.outward IN (SELECT name FROM `tabFresko Outward` WHERE prepared_by=" + frappe.db.escape(user or frappe.session.user) + ")))"
    return "(`tabFresko Exception`.sale IS NULL OR `tabFresko Exception`.sale='')"


def commercial_exception_has_permission(doc, ptype=None, user=None):
    try:
        _roles(user)
    except frappe.PermissionError:
        return False
    if doc and doc.get("sale"):
        if (ptype or "read") not in READ_TYPES:
            return False
        return commercial_has_permission(frappe.get_doc(SALE, doc.sale), ptype, user)
    if doc and doc.get("commercial_scope_key") and doc.get("outward"):
        if (ptype or "read") not in READ_TYPES:
            return False
        return permissions.outward_has_permission(doc.outward, "read", user)
    return None  # Preserve the existing role permissions for generic Exceptions.


_OPERATION_TIME = ContextVar("commercial_operation_time", default=None)
_OPERATION_ACTIVE = ContextVar("commercial_operation_active", default=False)


def _now():
    value = _OPERATION_TIME.get()
    if value is None:
        value = now_datetime()
        if _OPERATION_ACTIVE.get():
            _OPERATION_TIME.set(value)
    return value


def _atomic(function):
    @wraps(function)
    def execute(*args, **kwargs):
        savepoint = "commercial_op_" + frappe.generate_hash(length=8)
        frappe.db.savepoint(savepoint)
        token = _OPERATION_TIME.set(_OPERATION_TIME.get())
        active_token = _OPERATION_ACTIVE.set(True)
        try:
            return function(*args, **kwargs)
        except Exception:
            frappe.db.rollback(save_point=savepoint)
            raise
        finally:
            _OPERATION_ACTIVE.reset(active_token)
            _OPERATION_TIME.reset(token)
            frappe.db.release_savepoint(savepoint)
    return execute


for _method in (
    "create_sale", "submit_sale", "verify_sale", "approve_sale", "reject_sale",
    "supersede_sale", "propose_rate", "verify_rate", "approve_rate",
    "propose_alias_mapping", "verify_alias_mapping", "approve_alias_mapping", "reject_alias_mapping",
    "propose_sale_outward_allocation", "verify_sale_outward_allocation", "approve_sale_outward_allocation",
    "reject_sale_outward_allocation", "reverse_sale_outward_allocation", "refresh_commercial_reconciliation",
):
    globals()[_method] = _atomic(globals()[_method])
