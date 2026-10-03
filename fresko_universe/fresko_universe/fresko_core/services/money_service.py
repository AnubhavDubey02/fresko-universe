"""Evidence-backed money and financial reconciliation service.

Lock order is Company -> sorted Containers -> Collections / Sales / Adjustments -> decisions.
Deterministic calculations only; floats, exponents, and implicit rounding are forbidden.
All writes use private in-process capability guards.
"""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import Any

import frappe
from frappe.utils import get_datetime, now_datetime
from fresko_universe import permissions

COLLECTION = "Fresko Collection"
ALLOCATION = "Fresko Payment Allocation"
ADJUSTMENT = "Fresko Receivable Adjustment"
APPLICATION = "Fresko Adjustment Application"
SALE = "Fresko Commercial Sale"

_SCOPE = ContextVar("money_service_write", default=False)
_OPERATION_TIME = ContextVar("money_operation_time", default=None)
_OPERATION_ACTIVE = ContextVar("money_operation_active", default=False)
_OPERATION_ID = ContextVar("money_operation_id", default=None)

PAYLOAD_VERSION = "money-v1"
DECIMAL_RE = re.compile(r"^[+]?[0-9]+(?:\.[0-9]+)?$")
READ_TYPES = {"read", "print", "report", "export"}

OPERATIONAL = {
    COLLECTION: {
        "status", "verified_by", "verified_at", "approved_by", "approved_at",
        "superseded_by", "superseded_at", "reversed_by", "reversed_at",
        "active_transaction_key", "version", "decision_history", "allocated_amount",
        "unallocated_amount", "container_parked_amount", "last_operation_id", "reason"
    },
    ALLOCATION: {
        "status", "verified_by", "verified_at", "approved_by", "approved_at",
        "superseded_by", "superseded_at", "reversed_by", "reversed_at",
        "active_allocation_key", "version", "decision_history", "last_operation_id", "reason"
    },
    ADJUSTMENT: {
        "status", "verified_by", "verified_at", "approved_by", "approved_at",
        "superseded_by", "superseded_at", "reversed_by", "reversed_at",
        "active_adjustment_key", "version", "decision_history", "applied_amount",
        "unapplied_amount", "last_operation_id", "reason"
    },
    APPLICATION: {
        "status", "verified_by", "verified_at", "approved_by", "approved_at",
        "superseded_by", "superseded_at", "reversed_by", "reversed_at",
        "active_application_key", "version", "decision_history", "last_operation_id", "reason"
    },
}


def _fail(message: str, permission: bool = False):
    frappe.throw(message, frappe.PermissionError if permission else frappe.ValidationError)


def _roles(user: str | None = None) -> set[str]:
    roles = set(frappe.get_roles(user or frappe.session.user))
    if any("supplier" in role.casefold() for role in roles):
        _fail("Supplier access to internal money records is denied", True)
    return roles


def _actor(role: str):
    roles = _roles()
    if role in ("maker", "prepare", "propose"):
        if "Fresko Accounts" not in roles:
            _fail("Money preparation requires Fresko Accounts role", True)
    elif role == "verify":
        if "Fresko Accounts" not in roles:
            _fail("Money verification requires Fresko Accounts role", True)
    elif role in ("approve", "reject", "reverse"):
        if "Fresko Approver" not in roles:
            _fail("Money approval/reversal requires Fresko Approver role", True)
    else:
        _fail(f"Unknown actor role requirement: {role}")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str, required: bool = True) -> str | None:
    if value is None or not isinstance(value, str) or (required and not value.strip()):
        if value is None and not required:
            return None
        _fail(f"{field} must be {'nonempty ' if required else ''}text")
    if len(value) > 140:
        _fail(f"{field} exceeds Data field length; raw source cannot be truncated")
    return value


def _decimal(value: Any, field: str = "amount", scale: int = 2, positive: bool = False) -> str:
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
    return f"{number:.{scale}f}"


def _time(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label} requires a datetime")
    try:
        parsed = get_datetime(value)
    except (ValueError, TypeError):
        _fail(f"Invalid {label}")
    if parsed.tzinfo:
        _fail(f"{label} must use the site's configured timezone")
    return str(parsed)


def _now():
    try:
        from fresko_universe.fresko_core.services import commercial_service
        comm_time = commercial_service._OPERATION_TIME.get()
        if comm_time is not None:
            return comm_time
    except ImportError:
        pass
    val = _OPERATION_TIME.get()
    if val is None:
        val = now_datetime()
        if _OPERATION_ACTIVE.get():
            _OPERATION_TIME.set(val)
    return val


def _operation_id() -> str:
    val = _OPERATION_ID.get()
    if not val:
        val = "mop_" + frappe.generate_hash(length=12)
        _OPERATION_ID.set(val)
    return val


def _key(company: str, kind: str, source_event_id: str) -> str:
    return _hash([PAYLOAD_VERSION, company, kind, _text(source_event_id, "source_event_id")])


def _linked(doctype: str, name: str):
    if not name or not frappe.db.exists(doctype, name):
        _fail(f"Missing {doctype} {name}")
    doc = frappe.get_doc(doctype, name)
    if not frappe.has_permission(doctype, "read", doc=doc):
        _fail(f"Access denied to linked {doctype}", True)
    return doc


def _evidence(name: str, container: str | None = None) -> str | None:
    doc = _linked("Fresko Evidence", name)
    if not permissions.evidence_has_permission(doc, "read"):
        _fail("Access denied to supporting Evidence", True)
    if container and doc.container and doc.container != container:
        _fail("Evidence must belong to the same Container")
    if doc.file:
        for row in frappe.get_all("File", filters={"file_url": doc.file}, fields=["name"]):
            _linked("File", row.name)
    if doc.container:
        parent = _linked("Fresko Container", doc.container)
        return parent.company
    return None


def _inspect_evidence(name: str | None, container: str | None = None):
    if not name:
        return None, None, None, None
    evidence = _linked("Fresko Evidence", name)
    if not permissions.evidence_has_permission(evidence, "read"):
        _fail("Access denied to supporting Evidence", True)
    if container and evidence.container and evidence.container != container:
        _fail("Evidence must belong to the same Container")
    file_doc_name = None
    file_sha256 = None
    if evidence.file:
        file_rows = frappe.get_all("File", filters={"file_url": evidence.file}, fields=["name", "file_url"])
        if file_rows:
            fdoc = _linked("File", file_rows[0].name)
            file_doc_name = fdoc.name
            content = fdoc.get_content()
            if isinstance(content, str):
                content = content.encode("utf-8")
            if content is not None:
                file_sha256 = hashlib.sha256(content).hexdigest()
    snapshot = {
        "evidence": evidence.name,
        "evidence_type": evidence.get("evidence_type"),
        "notes": evidence.get("notes"),
        "container": evidence.get("container"),
        "file_url": evidence.get("file"),
        "file_name": file_doc_name,
        "file_sha256": file_sha256,
        "captured_at": str(_now())
    }
    evidence_company = None
    if evidence.container:
        parent = _linked("Fresko Container", evidence.container)
        evidence_company = parent.company
    return file_doc_name, file_sha256, _json(snapshot), evidence_company


def _locks(company: str, containers: Any = ()):
    _linked("Company", company)
    frappe.db.sql("SELECT name FROM `tabCompany` WHERE name=%s FOR UPDATE", (company,))
    for container in sorted(set(containers or [])):
        if container:
            _linked("Fresko Container", container)
            rows = frappe.db.sql("SELECT company FROM `tabFresko Container` WHERE name=%s FOR UPDATE", (container,), as_dict=True)
            if not rows or rows[0].company != company:
                _fail("Container does not belong to Company")


def _load(doctype: str, name: str):
    probe = frappe.get_doc(doctype, name)
    containers = [probe.container] if probe.get("container") else []
    _locks(probe.company, containers)
    doc = frappe.get_doc(doctype, name, for_update=True)
    if doc.company != probe.company or doc.get("container") != probe.get("container"):
        _fail("CONCURRENT_STATE_CONFLICT")
    _access(doc)
    return doc


def _access(doc):
    roles = _roles()
    if not roles & {"Fresko Accounts", "Fresko Approver"}:
        _fail("Access denied to internal money record", True)
    if "Fresko Salesperson" in roles and not (roles & {"Fresko Accounts", "Fresko Approver"}):
        _fail("Salesperson access to pooled money records is denied", True)
    _linked("Company", doc.company)
    if doc.get("currency"):
        _linked("Currency", doc.currency)
    if doc.get("customer"):
        _linked("Customer", doc.customer)
    if doc.get("container"):
        _linked("Fresko Container", doc.container)
    if doc.get("bank_account"):
        ba = _linked("Bank Account", doc.bank_account)
        if ba.company != doc.company:
            _fail("Bank Account does not belong to Company")
    if doc.get("source_evidence"):
        ev_co = _evidence(doc.source_evidence, doc.get("container"))
        if ev_co and ev_co != doc.company:
            _fail("Evidence company mismatch")
    if doc.get("evidence"):
        ev_co = _evidence(doc.evidence, doc.get("container"))
        if ev_co and ev_co != doc.company:
            _fail("Evidence company mismatch")
    if doc.doctype in {ALLOCATION, APPLICATION}:
        if doc.get("sale"):
            sale_doc = _linked(SALE, doc.sale)
            if sale_doc.company != doc.company:
                _fail("Linked Sale company mismatch")
        parent_type = COLLECTION if doc.doctype == ALLOCATION else ADJUSTMENT
        parent_name = doc.collection if doc.doctype == ALLOCATION else doc.receivable_adjustment
        _linked(parent_type, parent_name)
    for event in json.loads(doc.decision_history or "[]"):
        if event.get("evidence"):
            ev_co = _evidence(event["evidence"])
            if ev_co and ev_co != doc.company:
                _fail("Decision evidence company mismatch")


def _expected(doc, expected_version: Any):
    if expected_version is not None and str(expected_version) != str(doc.version):
        _fail("STALE_VERSION")


def _snapshot(doc):
    fields = OPERATIONAL[doc.doctype] - {"decision_history", "version"}
    return json.loads(_json({key: doc.get(key) for key in sorted(fields)}))


def _event(doc, action: str, *, reason: str | None = None, evidence: str | None = None, operation_id: str | None = None):
    binding = _inspect_evidence(evidence) if evidence else (None, None, None, None)
    if binding[3] and binding[3] != doc.company:
        _fail("Decision evidence company mismatch")
    events = json.loads(doc.decision_history or "[]")
    doc.version = int(doc.version or 0) + 1
    doc.last_operation_id = operation_id or _operation_id()
    events.append({
        "version": doc.version,
        "recorded_at": str(_now()),
        "actor": frappe.session.user,
        "action": action,
        "reason": reason,
        "evidence": evidence,
        "evidence_snapshot": json.loads(binding[2]) if binding[2] else None,
        "operation_id": doc.last_operation_id,
        "snapshot": _snapshot(doc)
    })
    doc.decision_history = _json(events)


@contextmanager
def _write():
    token = _SCOPE.set(True)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def _save(doc, action: str, *, reason: str | None = None, evidence: str | None = None, operation_id: str | None = None, insert: bool = False):
    _event(doc, action, reason=reason, evidence=evidence, operation_id=operation_id)
    with _write():
        saved = doc.insert(ignore_permissions=True) if insert else doc.save(ignore_permissions=True)
    if doc.doctype == COLLECTION:
        _refresh_collection_exceptions(doc)
    return saved


def _response(doc, replayed: bool = False) -> dict[str, Any]:
    res = {
        "name": doc.name,
        "doctype": doc.doctype,
        "status": doc.get("status"),
        "version": doc.version,
        "replayed": replayed,
        "company": doc.company,
        "effective_at": str(doc.effective_at) if doc.get("effective_at") else None,
        "last_operation_id": doc.get("last_operation_id")
    }
    if doc.doctype == COLLECTION:
        res.update({
            "amount": doc.amount,
            "currency": doc.currency,
            "amount_state": doc.amount_state,
            "payment_channel": doc.payment_channel,
            "bank_state": doc.bank_state,
            "allocated_amount": doc.allocated_amount,
            "unallocated_amount": doc.unallocated_amount,
            "container_parked_amount": doc.container_parked_amount,
            "active_transaction_key": doc.active_transaction_key
        })
    elif doc.doctype == ALLOCATION:
        res.update({
            "collection": doc.collection,
            "allocation_type": doc.allocation_type,
            "sale": doc.sale,
            "container": doc.container,
            "customer": doc.customer,
            "amount": doc.amount,
            "currency": doc.currency
        })
    elif doc.doctype == ADJUSTMENT:
        res.update({
            "customer": doc.customer,
            "adjustment_type": doc.adjustment_type,
            "amount": doc.amount,
            "applied_amount": doc.applied_amount,
            "unapplied_amount": doc.unapplied_amount
        })
    elif doc.doctype == APPLICATION:
        res.update({
            "receivable_adjustment": doc.receivable_adjustment,
            "sale": doc.sale,
            "customer": doc.customer,
            "amount": doc.amount
        })
    return res


def _existing(doctype: str, key: str, digest: str):
    rows = frappe.db.sql(f"SELECT name FROM `tab{doctype}` WHERE source_event_key=%s FOR UPDATE", (key,), as_dict=True)
    if not rows:
        return None
    doc = frappe.get_doc(doctype, rows[0].name, for_update=True)
    _access(doc)
    if doc.payload_sha256 != digest:
        _fail("IDEMPOTENCY_PAYLOAD_CONFLICT")
    return _response(doc, True)


def _replay_proposal(doctype, key, supplied, derived=()):
    """A redelivery reads its immutable event even after parents are corrected.

    Check original record ACL and every caller-controlled source field before
    returning. Optional server-derived Customer/Container values are recovered
    from the original payload, never recomputed from a later commercial state.
    """
    rows = frappe.db.sql(f"SELECT name FROM `tab{doctype}` WHERE source_event_key=%s FOR UPDATE", (key,), as_dict=True)
    if not rows:
        return None
    doc = frappe.get_doc(doctype, rows[0].name, for_update=True)
    _access(doc)
    payload = json.loads(doc.source_payload)
    if _hash(payload) != doc.payload_sha256:
        _fail("Money source payload hash mismatch")
    for field, value in supplied.items():
        if field in derived and value in (None, ""):
            continue
        if payload.get(field) != value:
            _fail("IDEMPOTENCY_PAYLOAD_CONFLICT")
    return _response(doc, True)


def _insert(doctype: str, payload: dict[str, Any], key: str, extras: dict[str, Any]):
    digest = _hash(payload)
    replay = _existing(doctype, key, digest)
    if replay:
        return replay
    doc = frappe.get_doc({
        "doctype": doctype,
        **payload,
        **extras,
        "source_event_key": key,
        "payload_sha256": digest,
        "source_payload": _json(payload),
        "decision_history": "[]",
        "version": 0
    })
    savepoint = "money_sp_" + frappe.generate_hash(length=8)
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
    return _response(doc)


def _separate(doc, role: str):
    _actor(role)
    maker = doc.get("prepared_by")
    if role == "verify":
        if frappe.session.user == maker:
            _fail("Maker and verifier must be different users", True)
    elif role in ("approve", "reject", "reverse"):
        forbidden = {maker}
        if doc.get("verified_by"):
            forbidden.add(doc.get("verified_by"))
        if frappe.session.user in forbidden:
            _fail("Maker, verifier and approver must be different users", True)


def _collection_eligible(doc) -> bool:
    if doc.status != "APPROVED" or doc.direction != "INFLOW" or doc.amount_state != "KNOWN" or not doc.amount:
        return False
    if getattr(doc, "effective_at", None) and get_datetime(doc.effective_at) > get_datetime(_now()):
        return False
    if doc.payment_channel == "CASH":
        return doc.source_classification == "CASH_DECLARATION" and doc.receipt_state == "RECEIVED"
    if doc.payment_channel == "BANK":
        return (doc.bank_state == "BANK_CLEARED" and doc.receipt_state == "RECEIVED"
                and bool(doc.bank_account and doc.bank_reference and doc.source_evidence))
    return False


def _sale_gross(sale_doc, *, company, currency, customer):
    from fresko_universe.fresko_core.services import commercial_service
    view = commercial_service.get_sale_as_of(sale_doc.name, str(_now()))
    if (not view.get("exists") or not view.get("effective_at_cutoff")
            or view.get("status") != "APPROVED" or not view.get("customer")):
        _fail("Sale must be current, approved, effective and Customer-resolved")
    if view["company"] != company or view["currency"] != currency or view["customer"] != customer:
        _fail("Sale Company, currency or Customer mismatch")
    if (view.get("total_commercial_amount") is None
            or any(line["price_state"] != "FINAL" for line in view["lines"])):
        _fail("SALE_GROSS_INCOMPLETE: Sale has unpriced or pending amount lines")
    return Decimal(view["total_commercial_amount"])


def _collection_active_key(doc) -> str:
    if doc.payment_channel == "BANK":
        return _hash([
            "BANK",
            doc.company,
            doc.bank_account or "",
            doc.bank_reference or doc.source_event_id,
            doc.currency,
            doc.direction
        ])
    return _hash([
        "CASH",
        doc.company,
        doc.source_namespace,
        doc.source_event_id,
        doc.currency,
        doc.direction
    ])


def _reverse_payment_allocation(alloc, reason: str | None, evidence: str | None, successor: str | None = None, operation_id: str | None = None):
    alloc.status = "REVERSED"
    alloc.reversed_by = frappe.session.user
    alloc.reversed_at = _now()
    alloc.active_allocation_key = None
    if successor:
        alloc.superseded_by = successor
        alloc.superseded_at = _now()
    _save(alloc, "REVERSE", reason=reason, evidence=evidence, operation_id=operation_id)


def _reverse_collection_allocations(coll, reason: str | None, evidence: str | None, operation_id: str | None = None):
    rows = frappe.db.sql(f"SELECT name FROM `tab{ALLOCATION}` WHERE collection=%s AND status='APPROVED' ORDER BY name FOR UPDATE", (coll.name,), as_dict=True)
    for row in rows:
        alloc = frappe.get_doc(ALLOCATION, row.name, for_update=True)
        _access(alloc)
        _reverse_payment_allocation(alloc, reason, evidence, operation_id=operation_id)
    coll.allocated_amount = "0.00"
    coll.container_parked_amount = "0.00"
    if coll.amount_state == "KNOWN" and coll.amount is not None:
        coll.unallocated_amount = coll.amount


def _reverse_adjustment_application(app, reason: str | None, evidence: str | None, successor: str | None = None, operation_id: str | None = None):
    app.status = "REVERSED"
    app.reversed_by = frappe.session.user
    app.reversed_at = _now()
    app.active_application_key = None
    if successor:
        app.superseded_by = successor
        app.superseded_at = _now()
    _save(app, "REVERSE", reason=reason, evidence=evidence, operation_id=operation_id)


def _reverse_adjustment_applications(adj, reason: str | None, evidence: str | None, operation_id: str | None = None):
    rows = frappe.db.sql(f"SELECT name FROM `tab{APPLICATION}` WHERE receivable_adjustment=%s AND status='APPROVED' ORDER BY name FOR UPDATE", (adj.name,), as_dict=True)
    for row in rows:
        app = frappe.get_doc(APPLICATION, row.name, for_update=True)
        _access(app)
        _reverse_adjustment_application(app, reason, evidence, operation_id=operation_id)
    adj.applied_amount = "0.00"
    adj.unapplied_amount = adj.amount


def _sync_collection_allocated_amounts(coll):
    rows = frappe.db.sql(f"SELECT allocation_type, amount FROM `tab{ALLOCATION}` WHERE collection=%s AND status='APPROVED' FOR UPDATE", (coll.name,), as_dict=True)
    total_allocated = Decimal(0)
    container_parked = Decimal(0)
    for row in rows:
        amt = Decimal(row.amount)
        total_allocated += amt
        if row.allocation_type == "CONTAINER_UNAPPLIED":
            container_parked += amt
    coll.allocated_amount = format(total_allocated, ".2f")
    coll.container_parked_amount = format(container_parked, ".2f")
    if coll.amount_state == "KNOWN" and coll.amount is not None:
        coll.unallocated_amount = format(Decimal(coll.amount) - total_allocated, ".2f")
    else:
        coll.unallocated_amount = None
    _save(coll, "SYNC_TOTALS")


def _sync_adjustment_applied_amounts(adj):
    rows = frappe.db.sql(f"SELECT amount FROM `tab{APPLICATION}` WHERE receivable_adjustment=%s AND status='APPROVED' FOR UPDATE", (adj.name,), as_dict=True)
    total_applied = sum((Decimal(row.amount) for row in rows), Decimal(0))
    adj.applied_amount = format(total_applied, ".2f")
    adj.unapplied_amount = format(Decimal(adj.amount) - total_applied, ".2f")
    _save(adj, "SYNC_TOTALS")


# --- Collection Mutators ---

def create_collection(
    *,
    company: str,
    source_namespace: str,
    source_event_id: str,
    direction: str = "INFLOW",
    amount: str | None = None,
    currency: str = "INR",
    amount_state: str | None = None,
    payment_channel: str = "BANK",
    bank_state: str = "NONE",
    source_classification: str = "NONE",
    bank_account: str | None = None,
    bank_reference: str | None = None,
    rail: str | None = None,
    cash_custodian: str | None = None,
    effective_at: str | None = None,
    payer_raw: str | None = None,
    customer: str | None = None,
    source_evidence: str | None = None,
    supersedes: str | None = None,
    reason: str | None = None
):
    _actor("maker")
    _locks(company)
    _linked("Company", company)
    _linked("Currency", currency)
    if customer:
        _linked("Customer", customer)
    if bank_account:
        ba = _linked("Bank Account", bank_account)
        if ba.company != company:
            _fail("Bank Account does not belong to Company")
    if cash_custodian:
        _linked("User", cash_custodian)

    if direction not in {"INFLOW", "OUTFLOW", "INTERNAL_TRANSFER", "UNKNOWN"}:
        _fail("Invalid direction")
    if payment_channel not in {"BANK", "CASH", "UNKNOWN"}:
        _fail("Invalid payment_channel")
    if bank_state not in {"NONE", "AUTHORIZATION_INPROCESS", "PENDING", "BANK_CLEARED", "UNKNOWN"}:
        _fail("Invalid bank_state")
    if source_classification not in {"NONE", "BANK_RECEIPT", "BANK_CREDIT_CONFIRMATION", "RTGS_NEFT", "CASH_DECLARATION", "OTHER"}:
        _fail("Invalid source_classification")

    if amount_state is None:
        amount_state = "UNKNOWN" if amount is None else "KNOWN"
    if amount_state not in {"KNOWN", "UNKNOWN"}:
        _fail("Invalid amount_state")
    if amount_state == "KNOWN":
        amount = _decimal(amount, "amount", 2, positive=True)
    elif amount is not None:
        _fail("Asserted amount requires KNOWN amount_state")

    file_name, file_sha256, evidence_snapshot, ev_co = _inspect_evidence(source_evidence)
    if ev_co and ev_co != company:
        _fail("Evidence company mismatch")

    source_namespace = _text(source_namespace, "source_namespace")
    source_event_id = _text(source_event_id, "source_event_id")
    event_key = _hash([PAYLOAD_VERSION, company, "collection", source_namespace, source_event_id])
    prior_source = frappe.db.sql(f"SELECT name FROM `tab{COLLECTION}` WHERE source_event_key=%s FOR UPDATE", (event_key,), as_dict=True)
    if effective_at:
        effective_at_val = _time(effective_at, "effective_at")
    elif prior_source:
        prior = frappe.get_doc(COLLECTION, prior_source[0].name, for_update=True)
        _access(prior)
        effective_at_val = json.loads(prior.source_payload)["effective_at"]
    else:
        effective_at_val = str(_now())
    receipt_state = "RECEIVED" if direction == "INFLOW" and (
        (payment_channel == "CASH" and source_classification == "CASH_DECLARATION") or
        (payment_channel == "BANK" and source_evidence and source_classification in {
            "BANK_RECEIPT", "BANK_CREDIT_CONFIRMATION", "RTGS_NEFT"})) else "UNKNOWN"

    payload = {
        "company": company,
        "source_namespace": source_namespace,
        "source_event_id": source_event_id,
        "direction": direction,
        "receipt_state": receipt_state,
        "amount": amount,
        "currency": currency,
        "amount_state": amount_state,
        "payment_channel": payment_channel,
        "bank_state": bank_state,
        "source_classification": source_classification,
        "bank_account": bank_account,
        "bank_reference": _text(bank_reference, "bank_reference", False),
        "rail": _text(rail, "rail", False),
        "cash_custodian": cash_custodian,
        "effective_at": effective_at_val,
        "payer_raw": _text(payer_raw, "payer_raw", False),
        "customer": customer,
        "source_evidence": source_evidence
    }
    if supersedes:
        payload.update(supersedes=supersedes, reason=_text(reason, "reason"))

    extras = {
        "naming_series": "COLL-.YYYY.-",
        "status": "DRAFT",
        "prepared_by": frappe.session.user,
        "prepared_at": _now(),
        "evidence_file": file_name,
        "evidence_sha256": file_sha256,
        "evidence_snapshot": evidence_snapshot,
        "allocated_amount": "0.00",
        "unallocated_amount": amount if amount_state == "KNOWN" else None,
        "container_parked_amount": "0.00"
    }
    return _insert(COLLECTION, payload, event_key, extras)


def submit_collection(collection_name: str, expected_version: Any = None):
    _actor("maker")
    doc = _load(COLLECTION, collection_name)
    _expected(doc, expected_version)
    if doc.prepared_by != frappe.session.user:
        _fail("Only the Collection maker may submit", True)
    if doc.status == "REVIEW_PENDING":
        return _response(doc, True)
    if doc.status != "DRAFT":
        _fail("Only DRAFT Collection can enter review")
    doc.status = "REVIEW_PENDING"
    _save(doc, "SUBMIT")
    return _response(doc)


def verify_collection(collection_name: str, expected_version: Any = None):
    doc = _load(COLLECTION, collection_name)
    _separate(doc, "verify")
    _expected(doc, expected_version)
    if doc.status == "VERIFIED" and doc.verified_by == frappe.session.user:
        return _response(doc, True)
    if doc.status != "REVIEW_PENDING":
        _fail("Collection must be REVIEW_PENDING")
    doc.status = "VERIFIED"
    doc.verified_by = frappe.session.user
    doc.verified_at = _now()
    _save(doc, "VERIFY", evidence=doc.source_evidence)
    return _response(doc)


def approve_collection(collection_name: str, expected_version: Any = None):
    doc = _load(COLLECTION, collection_name)
    _separate(doc, "approve")
    _expected(doc, expected_version)
    if doc.status == "APPROVED" and doc.approved_by == frappe.session.user:
        return _response(doc, True)
    if doc.status != "VERIFIED" or not doc.verified_by:
        _fail("Collection must have Accounts verification")

    if doc.bank_state == "BANK_CLEARED":
        if doc.payment_channel != "BANK":
            _fail("BANK_CLEARED requires BANK payment channel")
        if not doc.bank_account:
            _fail("BANK_CLEARED requires verified bank_account")
        ba = _linked("Bank Account", doc.bank_account)
        if ba.company != doc.company:
            _fail("Bank Account company mismatch")
        if not doc.bank_reference:
            _fail("BANK_CLEARED requires bank_reference")
        if doc.source_classification not in ("BANK_RECEIPT", "BANK_CREDIT_CONFIRMATION", "RTGS_NEFT"):
            _fail("BANK_CLEARED requires explicit bank credit confirmation/receipt classification")
        if not doc.source_evidence:
            _fail("BANK_CLEARED requires bound source_evidence")
        if doc.amount_state != "KNOWN" or not doc.amount or Decimal(doc.amount) <= 0:
            _fail("BANK_CLEARED requires known positive amount")

    active_key = _collection_active_key(doc)
    existing = frappe.db.sql(f"SELECT name FROM `tab{COLLECTION}` WHERE active_transaction_key=%s FOR UPDATE", (active_key,), as_dict=True)
    prior = None
    if doc.supersedes:
        prior = frappe.get_doc(COLLECTION, doc.supersedes, for_update=True)
        _access(prior)
        if prior.company != doc.company or prior.superseded_by or prior.status in {"SUPERSEDED", "REVERSED"}:
            _fail("CONCURRENT_STATE_CONFLICT")
    if any(row.name != (prior.name if prior else None) for row in existing):
        _fail("CONCURRENT_STATE_CONFLICT: active collection already exists for this transaction identity")

    if prior:
        _reverse_collection_allocations(prior, reason=f"Superseded by {doc.name}: {doc.reason}", evidence=doc.source_evidence)
        prior.status = "SUPERSEDED"
        prior.superseded_by = doc.name
        prior.superseded_at = _now()
        prior.active_transaction_key = None
        _save(prior, "SUPERSEDE", reason=doc.reason, evidence=doc.source_evidence)

    doc.status = "APPROVED"
    doc.approved_by = frappe.session.user
    doc.approved_at = _now()
    doc.active_transaction_key = active_key
    _save(doc, "APPROVE", evidence=doc.source_evidence)
    return _response(doc)


def reject_collection(collection_name: str, reason: str, expected_version: Any = None):
    doc = _load(COLLECTION, collection_name)
    _separate(doc, "reject")
    _expected(doc, expected_version)
    if doc.status not in {"REVIEW_PENDING", "VERIFIED"}:
        _fail("Only pending/verified Collection can be rejected")
    doc.status = "REJECTED"
    doc.reason = _text(reason, "reason")
    _save(doc, "REJECT", reason=doc.reason)
    return _response(doc)


def reverse_collection(collection_name: str, reason: str, evidence: str, expected_version: Any = None):
    doc = _load(COLLECTION, collection_name)
    _separate(doc, "reverse")
    _expected(doc, expected_version)
    if doc.status != "APPROVED":
        _fail("Only APPROVED Collection can be reversed")
    _evidence(evidence)
    _reverse_collection_allocations(doc, reason=reason, evidence=evidence)
    doc.status = "REVERSED"
    doc.reversed_by = frappe.session.user
    doc.reversed_at = _now()
    doc.active_transaction_key = None
    _save(doc, "REVERSE", reason=_text(reason, "reason"), evidence=evidence)
    return _response(doc)


def supersede_collection(collection_name: str, *, source_event_id: str, reason: str, source_evidence: str, changes: dict[str, Any] | str, expected_version: Any = None):
    _actor("maker")
    doc = _load(COLLECTION, collection_name)
    _expected(doc, expected_version)
    if doc.status != "APPROVED":
        _fail("Collection correction requires an APPROVED predecessor")
    reason = _text(reason, "reason")
    _evidence(source_evidence)
    if isinstance(changes, str):
        changes = frappe.parse_json(changes)
    if not isinstance(changes, dict):
        _fail("Invalid changes specification")
    payload = json.loads(doc.source_payload)
    allowed_changes = {"direction", "amount", "amount_state", "payment_channel", "bank_state", "source_classification", "bank_account", "bank_reference", "rail", "cash_custodian", "effective_at", "payer_raw", "customer", "currency"}
    if set(changes) - allowed_changes:
        _fail("Collection correction contains immutable or server fields")
    payload.pop("receipt_state", None)
    payload.update(changes)
    payload.update(source_event_id=_text(source_event_id, "source_event_id"), source_evidence=source_evidence)
    payload.pop("supersedes", None)
    payload.pop("reason", None)
    return create_collection(**payload, supersedes=doc.name, reason=reason)


# --- Payment Allocation Mutators ---

def propose_payment_allocation(
    *,
    collection: str,
    allocation_type: str,
    amount: str,
    currency: str,
    evidence: str,
    source_event_id: str,
    sale: str | None = None,
    container: str | None = None,
    customer: str | None = None,
    supersedes: str | None = None,
    reason: str | None = None
):
    _actor("maker")
    coll = _load(COLLECTION, collection)
    sale, container, customer, supersedes = (value or None for value in (sale, container, customer, supersedes))
    if allocation_type == "CONTAINER_UNAPPLIED" and (sale or customer):
        _fail("Container parking cannot identify a Sale or Customer")
    amount = _decimal(amount, "amount", 2, positive=True)
    replay = _replay_proposal(ALLOCATION, _key(coll.company, "allocation", source_event_id), {
        "collection": collection, "allocation_type": allocation_type, "amount": amount,
        "currency": currency, "evidence": evidence, "source_event_id": source_event_id,
        "sale": sale, "container": container, "customer": customer, "supersedes": supersedes,
        "reason": reason if supersedes else None}, derived={"container", "customer"})
    if replay:
        return replay
    _locks(coll.company, [container] if container else [])
    if allocation_type not in ("SALE", "CONTAINER_UNAPPLIED"):
        _fail("Invalid allocation_type")
    if coll.direction != "INFLOW" or coll.amount_state != "KNOWN":
        _fail("Collection is not eligible for payment allocation")
    if coll.status != "APPROVED":
        _fail("Payment allocation requires an APPROVED Collection")

    amount = _decimal(amount, "amount", 2, positive=True)
    _linked("Currency", currency)
    if currency != coll.currency:
        _fail("Allocation currency must match Collection currency")

    if allocation_type == "SALE":
        if not sale:
            _fail("SALE allocation requires a sale")
        sale_doc = _linked(SALE, sale)
        if sale_doc.company != coll.company:
            _fail("Sale company mismatch")
        if sale_doc.status != "APPROVED":
            _fail("Payment allocation requires APPROVED Sale")
        if container and container != sale_doc.container:
            _fail("Allocation Container must match Sale Container")
        container = sale_doc.container
        if not sale_doc.customer:
            _fail("Sale customer must be resolved before payment allocation")
        if customer and customer != sale_doc.customer:
            _fail("Allocation customer must match resolved Sale customer")
        customer = sale_doc.customer
    elif allocation_type == "CONTAINER_UNAPPLIED":
        if not container:
            _fail("CONTAINER_UNAPPLIED allocation requires a container")
        c_doc = _linked("Fresko Container", container)
        if c_doc.company != coll.company:
            _fail("Container company mismatch")
        customer = None
        sale = None

    file_name, file_sha256, evidence_snapshot, ev_co = _inspect_evidence(evidence, container)
    if ev_co and ev_co != coll.company:
        _fail("Evidence company mismatch")

    if supersedes:
        prior = _load(ALLOCATION, supersedes)
        if prior.collection != collection or prior.status not in ("APPROVED", "REVERSED"):
            _fail("Supersession requires active or reversed prior allocation of same collection")
        reason = _text(reason, "reason")

    payload = {
        "company": coll.company,
        "collection": collection,
        "allocation_type": allocation_type,
        "amount": amount,
        "currency": currency,
        "evidence": evidence,
        "source_event_id": _text(source_event_id, "source_event_id"),
        "sale": sale,
        "container": container,
        "customer": customer
    }
    if supersedes:
        payload.update(supersedes=supersedes, reason=reason)

    extras = {
        "naming_series": "PAL-.YYYY.-",
        "status": "DRAFT",
        "prepared_by": frappe.session.user,
        "prepared_at": _now(),
        "evidence_file": file_name,
        "evidence_sha256": file_sha256,
        "evidence_snapshot": evidence_snapshot
    }
    return _insert(ALLOCATION, payload, _key(coll.company, "allocation", source_event_id), extras)


def submit_payment_allocation(allocation_name: str, expected_version: Any = None):
    _actor("maker")
    doc = _load(ALLOCATION, allocation_name)
    _expected(doc, expected_version)
    if doc.prepared_by != frappe.session.user:
        _fail("Only the Payment Allocation maker may submit", True)
    if doc.status == "REVIEW_PENDING":
        return _response(doc, True)
    if doc.status != "DRAFT":
        _fail("Only DRAFT Payment Allocation can enter review")
    doc.status = "REVIEW_PENDING"
    _save(doc, "SUBMIT")
    return _response(doc)


def verify_payment_allocation(allocation_name: str, expected_version: Any = None):
    doc = _load(ALLOCATION, allocation_name)
    _separate(doc, "verify")
    _expected(doc, expected_version)
    if doc.status == "VERIFIED" and doc.verified_by == frappe.session.user:
        return _response(doc, True)
    if doc.status != "REVIEW_PENDING":
        _fail("Payment Allocation must be REVIEW_PENDING")
    doc.status = "VERIFIED"
    doc.verified_by = frappe.session.user
    doc.verified_at = _now()
    _save(doc, "VERIFY", evidence=doc.evidence)
    return _response(doc)


def approve_payment_allocation(allocation_name: str, expected_version: Any = None):
    doc = _load(ALLOCATION, allocation_name)
    _separate(doc, "approve")
    _expected(doc, expected_version)
    if doc.status == "APPROVED" and doc.approved_by == frappe.session.user:
        return _response(doc, True)
    if doc.status != "VERIFIED" or not doc.verified_by:
        _fail("Payment Allocation requires Accounts verification")

    coll = frappe.get_doc(COLLECTION, doc.collection, for_update=True)
    if coll.status != "APPROVED":
        _fail("Collection is not APPROVED")
    _access(coll)
    if not _collection_eligible(coll):
        _fail("BANK_PENDING_INELIGIBLE: Collection lacks eligible cleared bank receipt or declared cash receipt")

    prior = None
    if doc.supersedes:
        prior = frappe.get_doc(ALLOCATION, doc.supersedes, for_update=True)
        _access(prior)
        if prior.status not in ("APPROVED", "REVERSED") or prior.superseded_by:
            _fail("CONCURRENT_STATE_CONFLICT")

    # Cap 1: Collection cap
    alloc_rows = frappe.db.sql(f"SELECT name, amount FROM `tab{ALLOCATION}` WHERE collection=%s AND status='APPROVED' FOR UPDATE", (coll.name,), as_dict=True)
    allocated_sum = sum((Decimal(r.amount) for r in alloc_rows if not prior or r.name != prior.name), Decimal(0))
    if allocated_sum + Decimal(doc.amount) > Decimal(coll.amount):
        _fail("COLLECTION_CAP_EXCEEDED: Total allocations exceed collection amount")

    # Cap 2: Sale cap
    if doc.allocation_type == "SALE":
        sale_doc = frappe.get_doc(SALE, doc.sale, for_update=True)
        if sale_doc.status != "APPROVED":
            _fail("Sale is not APPROVED")
        gross_sale = _sale_gross(sale_doc, company=doc.company, currency=doc.currency, customer=doc.customer)

        sale_pay_rows = frappe.db.sql(f"SELECT name, amount FROM `tab{ALLOCATION}` WHERE sale=%s AND status='APPROVED' FOR UPDATE", (doc.sale,), as_dict=True)
        sale_pay_sum = sum((Decimal(r.amount) for r in sale_pay_rows if not prior or r.name != prior.name), Decimal(0))

        sale_adj_rows = frappe.db.sql(f"SELECT name, amount FROM `tab{APPLICATION}` WHERE sale=%s AND status='APPROVED' FOR UPDATE", (doc.sale,), as_dict=True)
        sale_adj_sum = sum((Decimal(r.amount) for r in sale_adj_rows), Decimal(0))

        if sale_pay_sum + sale_adj_sum + Decimal(doc.amount) > gross_sale:
            _fail("SALE_RECEIVABLE_CAP_EXCEEDED: Payments and adjustments exceed approved gross Sale")

    active_key = _hash([doc.collection, doc.source_event_id])
    if prior:
        if prior.status == "APPROVED":
            _reverse_payment_allocation(prior, reason=doc.reason, evidence=doc.evidence, successor=doc.name)
        else:
            prior.superseded_by = doc.name
            prior.superseded_at = _now()
            _save(prior, "SUPERSEDED", reason=doc.reason, evidence=doc.evidence)

    doc.status = "APPROVED"
    doc.approved_by = frappe.session.user
    doc.approved_at = _now()
    doc.active_allocation_key = active_key
    _save(doc, "APPROVE", evidence=doc.evidence)
    _sync_collection_allocated_amounts(coll)
    return _response(doc)


def reject_payment_allocation(allocation_name: str, reason: str, expected_version: Any = None):
    doc = _load(ALLOCATION, allocation_name)
    _separate(doc, "reject")
    _expected(doc, expected_version)
    if doc.status not in ("DRAFT", "REVIEW_PENDING", "VERIFIED"):
        _fail("Only pending payment allocation can be rejected")
    doc.status = "REJECTED"
    doc.reason = _text(reason, "reason")
    _save(doc, "REJECT", reason=doc.reason, evidence=doc.evidence)
    return _response(doc)


def reverse_payment_allocation(allocation_name: str, reason: str, evidence: str, expected_version: Any = None):
    doc = _load(ALLOCATION, allocation_name)
    _separate(doc, "reverse")
    _expected(doc, expected_version)
    if doc.status != "APPROVED":
        _fail("Only APPROVED payment allocation can be reversed")
    _evidence(evidence)
    _reverse_payment_allocation(doc, reason=reason, evidence=evidence)
    coll = frappe.get_doc(COLLECTION, doc.collection, for_update=True)
    _sync_collection_allocated_amounts(coll)
    return _response(doc)


# --- Receivable Adjustment Mutators ---

def propose_adjustment(
    *,
    company: str,
    customer: str,
    adjustment_type: str,
    amount: str,
    currency: str = "INR",
    evidence: str,
    source_event_id: str,
    agreement_reference: str | None = None,
    supersedes: str | None = None,
    reason: str | None = None
):
    _actor("maker")
    _locks(company)
    supersedes = supersedes or None
    amount = _decimal(amount, "amount", 2, positive=True)
    replay = _replay_proposal(ADJUSTMENT, _key(company, "adjustment", source_event_id), {
        "company": company, "customer": customer, "adjustment_type": adjustment_type,
        "amount": amount, "currency": currency, "evidence": evidence,
        "source_event_id": source_event_id, "agreement_reference": agreement_reference,
        "supersedes": supersedes, "reason": reason if supersedes else None})
    if replay:
        return replay
    _linked("Company", company)
    _linked("Customer", customer)
    _linked("Currency", currency)

    if adjustment_type not in ("DISCOUNT", "COMMISSION_SETOFF", "CUSTOMER_PAID_EXPENSE_SETOFF", "UNCLASSIFIED"):
        _fail("Invalid adjustment_type")
    amount = _decimal(amount, "amount", 2, positive=True)

    file_name, file_sha256, evidence_snapshot, ev_co = _inspect_evidence(evidence)
    if ev_co and ev_co != company:
        _fail("Evidence company mismatch")

    if supersedes:
        prior = _load(ADJUSTMENT, supersedes)
        if prior.company != company or prior.customer != customer or prior.status not in ("APPROVED", "REVERSED"):
            _fail("Invalid adjustment supersession")
        reason = _text(reason, "reason")

    payload = {
        "company": company,
        "customer": customer,
        "adjustment_type": adjustment_type,
        "amount": amount,
        "currency": currency,
        "evidence": evidence,
        "source_event_id": _text(source_event_id, "source_event_id"),
        "agreement_reference": _text(agreement_reference, "agreement_reference", False)
    }
    if supersedes:
        payload.update(supersedes=supersedes, reason=reason)

    extras = {
        "naming_series": "ADJ-.YYYY.-",
        "status": "DRAFT",
        "prepared_by": frappe.session.user,
        "prepared_at": _now(),
        "applied_amount": "0.00",
        "unapplied_amount": amount,
        "evidence_file": file_name,
        "evidence_sha256": file_sha256,
        "evidence_snapshot": evidence_snapshot
    }
    return _insert(ADJUSTMENT, payload, _key(company, "adjustment", source_event_id), extras)


def submit_adjustment(adjustment_name: str, expected_version: Any = None):
    _actor("maker")
    doc = _load(ADJUSTMENT, adjustment_name)
    _expected(doc, expected_version)
    if doc.prepared_by != frappe.session.user:
        _fail("Only the Adjustment maker may submit", True)
    if doc.status == "REVIEW_PENDING":
        return _response(doc, True)
    if doc.status != "DRAFT":
        _fail("Only DRAFT Adjustment can enter review")
    doc.status = "REVIEW_PENDING"
    _save(doc, "SUBMIT")
    return _response(doc)


def verify_adjustment(adjustment_name: str, expected_version: Any = None):
    doc = _load(ADJUSTMENT, adjustment_name)
    _separate(doc, "verify")
    _expected(doc, expected_version)
    if doc.status == "VERIFIED" and doc.verified_by == frappe.session.user:
        return _response(doc, True)
    if doc.status != "REVIEW_PENDING":
        _fail("Adjustment must be REVIEW_PENDING")
    doc.status = "VERIFIED"
    doc.verified_by = frappe.session.user
    doc.verified_at = _now()
    _save(doc, "VERIFY", evidence=doc.evidence)
    return _response(doc)


def approve_adjustment(adjustment_name: str, expected_version: Any = None):
    doc = _load(ADJUSTMENT, adjustment_name)
    _separate(doc, "approve")
    _expected(doc, expected_version)
    if doc.status == "APPROVED" and doc.approved_by == frappe.session.user:
        return _response(doc, True)
    if doc.status != "VERIFIED" or not doc.verified_by:
        _fail("Adjustment requires Accounts verification")

    if doc.adjustment_type == "UNCLASSIFIED":
        _fail("UNCLASSIFIED adjustment cannot be approved")
    if not doc.agreement_reference:
        _fail("Approved receivable adjustment requires explicit debt discharge agreement_reference")
    if not doc.evidence:
        _fail("Approved receivable adjustment requires supporting evidence")

    active_key = _hash([doc.company, doc.customer, doc.adjustment_type, doc.source_event_id])
    prior = None
    if doc.supersedes:
        prior = frappe.get_doc(ADJUSTMENT, doc.supersedes, for_update=True)
        _access(prior)
        if prior.status not in ("APPROVED", "REVERSED") or prior.superseded_by:
            _fail("CONCURRENT_STATE_CONFLICT")
        if prior.status == "APPROVED":
            _reverse_adjustment_applications(prior, reason=f"Superseded by {doc.name}: {doc.reason}", evidence=doc.evidence)
            prior.status = "SUPERSEDED"
            prior.superseded_by = doc.name
            prior.superseded_at = _now()
            prior.active_adjustment_key = None
            _save(prior, "SUPERSEDED", reason=doc.reason, evidence=doc.evidence)

    doc.status = "APPROVED"
    doc.approved_by = frappe.session.user
    doc.approved_at = _now()
    doc.active_adjustment_key = active_key
    _save(doc, "APPROVE", evidence=doc.evidence)
    return _response(doc)


def reject_adjustment(adjustment_name: str, reason: str, expected_version: Any = None):
    doc = _load(ADJUSTMENT, adjustment_name)
    _separate(doc, "reject")
    _expected(doc, expected_version)
    if doc.status not in ("DRAFT", "REVIEW_PENDING", "VERIFIED"):
        _fail("Only pending Adjustment can be rejected")
    doc.status = "REJECTED"
    doc.reason = _text(reason, "reason")
    _save(doc, "REJECT", reason=doc.reason, evidence=doc.evidence)
    return _response(doc)


def reverse_adjustment(adjustment_name: str, reason: str, evidence: str, expected_version: Any = None):
    doc = _load(ADJUSTMENT, adjustment_name)
    _separate(doc, "reverse")
    _expected(doc, expected_version)
    if doc.status != "APPROVED":
        _fail("Only APPROVED Adjustment can be reversed")
    _evidence(evidence)
    _reverse_adjustment_applications(doc, reason=reason, evidence=evidence)
    doc.status = "REVERSED"
    doc.reversed_by = frappe.session.user
    doc.reversed_at = _now()
    doc.active_adjustment_key = None
    _save(doc, "REVERSE", reason=_text(reason, "reason"), evidence=evidence)
    return _response(doc)


# --- Adjustment Application Mutators ---

def propose_adjustment_application(
    *,
    receivable_adjustment: str,
    sale: str,
    amount: str,
    currency: str,
    evidence: str,
    source_event_id: str,
    supersedes: str | None = None,
    reason: str | None = None
):
    _actor("maker")
    adj = _load(ADJUSTMENT, receivable_adjustment)
    supersedes = supersedes or None
    amount = _decimal(amount, "amount", 2, positive=True)
    replay = _replay_proposal(APPLICATION, _key(adj.company, "adjustment_application", source_event_id), {
        "receivable_adjustment": receivable_adjustment, "sale": sale, "amount": amount,
        "currency": currency, "evidence": evidence, "source_event_id": source_event_id,
        "supersedes": supersedes, "reason": reason if supersedes else None})
    if replay:
        return replay
    sale_doc = _linked(SALE, sale)
    if sale_doc.company != adj.company:
        _fail("Sale and Adjustment company mismatch")
    _locks(adj.company, [sale_doc.container] if sale_doc.container else [])
    sale_doc = frappe.get_doc(SALE, sale, for_update=True)

    if adj.status != "APPROVED":
        _fail("Receivable adjustment is not APPROVED")
    if adj.adjustment_type == "UNCLASSIFIED":
        _fail("UNCLASSIFIED adjustment cannot be applied")
    if sale_doc.company != adj.company:
        _fail("Sale and Adjustment company mismatch")
    if not sale_doc.customer or sale_doc.customer != adj.customer:
        _fail("Sale customer and Adjustment customer mismatch")
    if sale_doc.status != "APPROVED":
        _fail("Adjustment application requires APPROVED Sale")

    amount = _decimal(amount, "amount", 2, positive=True)
    _linked("Currency", currency)
    if currency != adj.currency or currency != sale_doc.currency:
        _fail("Application currency must match Adjustment and Sale currency")

    file_name, file_sha256, evidence_snapshot, ev_co = _inspect_evidence(evidence, sale_doc.container)
    if ev_co and ev_co != adj.company:
        _fail("Evidence company mismatch")

    if supersedes:
        prior = _load(APPLICATION, supersedes)
        if prior.receivable_adjustment != receivable_adjustment or prior.sale != sale:
            _fail("Invalid adjustment application supersession")
        reason = _text(reason, "reason")

    payload = {
        "company": adj.company,
        "receivable_adjustment": receivable_adjustment,
        "sale": sale,
        "customer": adj.customer,
        "amount": amount,
        "currency": currency,
        "evidence": evidence,
        "source_event_id": _text(source_event_id, "source_event_id")
    }
    if supersedes:
        payload.update(supersedes=supersedes, reason=reason)

    extras = {
        "naming_series": "ADJA-.YYYY.-",
        "status": "DRAFT",
        "prepared_by": frappe.session.user,
        "prepared_at": _now(),
        "evidence_file": file_name,
        "evidence_sha256": file_sha256,
        "evidence_snapshot": evidence_snapshot
    }
    return _insert(APPLICATION, payload, _key(adj.company, "adjustment_application", source_event_id), extras)


def submit_adjustment_application(application_name: str, expected_version: Any = None):
    _actor("maker")
    doc = _load(APPLICATION, application_name)
    _expected(doc, expected_version)
    if doc.prepared_by != frappe.session.user:
        _fail("Only the Adjustment Application maker may submit", True)
    if doc.status == "REVIEW_PENDING":
        return _response(doc, True)
    if doc.status != "DRAFT":
        _fail("Only DRAFT Adjustment Application can enter review")
    doc.status = "REVIEW_PENDING"
    _save(doc, "SUBMIT")
    return _response(doc)


def verify_adjustment_application(application_name: str, expected_version: Any = None):
    doc = _load(APPLICATION, application_name)
    _separate(doc, "verify")
    _expected(doc, expected_version)
    if doc.status == "VERIFIED" and doc.verified_by == frappe.session.user:
        return _response(doc, True)
    if doc.status != "REVIEW_PENDING":
        _fail("Adjustment Application must be REVIEW_PENDING")
    doc.status = "VERIFIED"
    doc.verified_by = frappe.session.user
    doc.verified_at = _now()
    _save(doc, "VERIFY", evidence=doc.evidence)
    return _response(doc)


def approve_adjustment_application(application_name: str, expected_version: Any = None):
    doc = _load(APPLICATION, application_name)
    _separate(doc, "approve")
    _expected(doc, expected_version)
    if doc.status == "APPROVED" and doc.approved_by == frappe.session.user:
        return _response(doc, True)
    if doc.status != "VERIFIED" or not doc.verified_by:
        _fail("Adjustment Application requires Accounts verification")

    adj = frappe.get_doc(ADJUSTMENT, doc.receivable_adjustment, for_update=True)
    if adj.status != "APPROVED":
        _fail("Receivable adjustment is not APPROVED")
    sale_doc = frappe.get_doc(SALE, doc.sale, for_update=True)
    if sale_doc.status != "APPROVED":
        _fail("Sale is not APPROVED")
    _access(adj)
    gross_sale = _sale_gross(sale_doc, company=doc.company, currency=doc.currency, customer=doc.customer)

    prior = None
    if doc.supersedes:
        prior = frappe.get_doc(APPLICATION, doc.supersedes, for_update=True)
        _access(prior)
        if prior.status not in ("APPROVED", "REVERSED") or prior.superseded_by:
            _fail("CONCURRENT_STATE_CONFLICT")

    # Cap 3: Adjustment capacity cap
    app_rows = frappe.db.sql(f"SELECT name, amount FROM `tab{APPLICATION}` WHERE receivable_adjustment=%s AND status='APPROVED' FOR UPDATE", (adj.name,), as_dict=True)
    adj_applied_sum = sum((Decimal(r.amount) for r in app_rows if not prior or r.name != prior.name), Decimal(0))
    if adj_applied_sum + Decimal(doc.amount) > Decimal(adj.amount):
        _fail("ADJUSTMENT_CAP_EXCEEDED: Applications exceed receivable adjustment amount")

    # Cap 2: Sale gross cap
    sale_pay_rows = frappe.db.sql(f"SELECT name, amount FROM `tab{ALLOCATION}` WHERE sale=%s AND status='APPROVED' FOR UPDATE", (doc.sale,), as_dict=True)
    sale_pay_sum = sum((Decimal(r.amount) for r in sale_pay_rows), Decimal(0))
    sale_adj_rows = frappe.db.sql(f"SELECT name, amount FROM `tab{APPLICATION}` WHERE sale=%s AND status='APPROVED' FOR UPDATE", (doc.sale,), as_dict=True)
    sale_adj_sum = sum((Decimal(r.amount) for r in sale_adj_rows if not prior or r.name != prior.name), Decimal(0))
    if sale_pay_sum + sale_adj_sum + Decimal(doc.amount) > gross_sale:
        _fail("SALE_RECEIVABLE_CAP_EXCEEDED: Payments and adjustments exceed approved gross Sale")

    active_key = _hash([doc.receivable_adjustment, doc.source_event_id])
    if prior:
        if prior.status == "APPROVED":
            _reverse_adjustment_application(prior, reason=doc.reason, evidence=doc.evidence, successor=doc.name)
        else:
            prior.superseded_by = doc.name
            prior.superseded_at = _now()
            _save(prior, "SUPERSEDED", reason=doc.reason, evidence=doc.evidence)

    doc.status = "APPROVED"
    doc.approved_by = frappe.session.user
    doc.approved_at = _now()
    doc.active_application_key = active_key
    _save(doc, "APPROVE", evidence=doc.evidence)
    _sync_adjustment_applied_amounts(adj)
    return _response(doc)


def reject_adjustment_application(application_name: str, reason: str, expected_version: Any = None):
    doc = _load(APPLICATION, application_name)
    _separate(doc, "reject")
    _expected(doc, expected_version)
    if doc.status not in ("DRAFT", "REVIEW_PENDING", "VERIFIED"):
        _fail("Only pending Adjustment Application can be rejected")
    doc.status = "REJECTED"
    doc.reason = _text(reason, "reason")
    _save(doc, "REJECT", reason=doc.reason, evidence=doc.evidence)
    return _response(doc)


def reverse_adjustment_application(application_name: str, reason: str, evidence: str, expected_version: Any = None):
    doc = _load(APPLICATION, application_name)
    _separate(doc, "reverse")
    _expected(doc, expected_version)
    if doc.status != "APPROVED":
        _fail("Only APPROVED Adjustment Application can be reversed")
    _evidence(evidence)
    _reverse_adjustment_application(doc, reason=reason, evidence=evidence)
    adj = frappe.get_doc(ADJUSTMENT, doc.receivable_adjustment, for_update=True)
    _sync_adjustment_applied_amounts(adj)
    return _response(doc)


# --- Commercial Event Compensation Hook ---

def compensate_for_sale_change(sale: str, reason: str, evidence: str, operation_id: str | None = None):
    sale_doc = _linked(SALE, sale)
    _locks(sale_doc.company, [sale_doc.container] if sale_doc.get("container") else [])
    reason = _text(reason, "reason")
    _evidence(evidence)

    reversed_allocs = []
    reversed_adjs = []

    alloc_rows = frappe.db.sql(f"SELECT name FROM `tab{ALLOCATION}` WHERE sale=%s AND status='APPROVED' ORDER BY name FOR UPDATE", (sale,), as_dict=True)
    for row in alloc_rows:
        alloc = frappe.get_doc(ALLOCATION, row.name, for_update=True)
        _access(alloc)
        _reverse_payment_allocation(alloc, reason=reason, evidence=evidence, operation_id=operation_id)
        coll = frappe.get_doc(COLLECTION, alloc.collection, for_update=True)
        _sync_collection_allocated_amounts(coll)
        reversed_allocs.append(alloc.name)

    adj_rows = frappe.db.sql(f"SELECT name FROM `tab{APPLICATION}` WHERE sale=%s AND status='APPROVED' ORDER BY name FOR UPDATE", (sale,), as_dict=True)
    for row in adj_rows:
        app = frappe.get_doc(APPLICATION, row.name, for_update=True)
        _access(app)
        _reverse_adjustment_application(app, reason=reason, evidence=evidence, operation_id=operation_id)
        adj = frappe.get_doc(ADJUSTMENT, app.receivable_adjustment, for_update=True)
        _sync_adjustment_applied_amounts(adj)
        reversed_adjs.append(app.name)

    return {
        "sale": sale,
        "reversed_payment_allocations": reversed_allocs,
        "reversed_adjustment_applications": reversed_adjs
    }


# --- File Protection Hooks ---

def _check_file_not_money_evidence(file_name: str, file_url: str | None = None):
    for dt in (COLLECTION, ALLOCATION, ADJUSTMENT, APPLICATION):
        if not frappe.db.table_exists(dt):
            continue
        if frappe.db.sql(f"SELECT name FROM `tab{dt}` WHERE evidence_file=%s LIMIT 1", (file_name,)):
            frappe.throw(f"File {file_name} is referenced by immutable money record and cannot be modified or deleted", frappe.ValidationError)
        if file_url:
            if frappe.db.sql(f"SELECT name FROM `tab{dt}` WHERE evidence_snapshot LIKE %s OR decision_history LIKE %s LIMIT 1", (f"%{file_url}%", f"%{file_url}%")):
                frappe.throw(f"File {file_name} is referenced by immutable money record and cannot be modified or deleted", frappe.ValidationError)


def protect_money_file_before_save(doc, method=None):
    if doc.doctype != "File":
        return
    old = doc.get_doc_before_save()
    if old:
        _check_file_not_money_evidence(doc.name, doc.file_url)


def protect_money_file_on_trash(doc, method=None):
    if doc.doctype != "File":
        return
    _check_file_not_money_evidence(doc.name, doc.file_url)


def forbid_money_delete(doc):
    _fail("Money documents are permanent audit records and cannot be deleted", True)


def forbid_money_rename(doc, *args, **kwargs):
    _fail("Money documents cannot be renamed", True)


def validate_money_document(doc):
    if not _SCOPE.get():
        _fail("Money records are service-only; direct writes/imports are forbidden", True)
    payload = json.loads(doc.source_payload or "null")
    if not isinstance(payload, dict) or _hash(payload) != doc.payload_sha256:
        _fail("Money source payload hash mismatch")
    old = doc.get_doc_before_save()
    if old:
        if old.source_payload != doc.source_payload or old.payload_sha256 != doc.payload_sha256 or old.source_event_key != doc.source_event_key:
            _fail("Money source identity is immutable", True)
        for field in doc.meta.fields:
            key = field.fieldname
            if key in OPERATIONAL[doc.doctype] or field.fieldtype in {"Section Break", "Column Break", "Tab Break"}:
                continue
            if str(old.get(key) or "") != str(doc.get(key) or ""):
                _fail(f"Money source field {key} is immutable", True)
        old_events = json.loads(old.decision_history or "[]")
        events = json.loads(doc.decision_history or "[]")
        if events[:-1] != old_events or int(doc.version) != int(old.version) + 1:
            _fail("Decision history must append exactly one event")
    else:
        if doc.status != "DRAFT" or doc.version != 1:
            _fail("Invalid initial money decision state")
    events = json.loads(doc.decision_history or "[]")
    if not events or events[-1]["actor"] != frappe.session.user or events[-1]["snapshot"] != _snapshot(doc):
        _fail("Forged money decision metadata")


# --- Permissions Queries & Handlers ---

def money_permission_query(doctype: str, user: str | None = None) -> str:
    try:
        roles = _roles(user)
    except frappe.PermissionError:
        return "1=0"
    if any("supplier" in r.casefold() for r in roles):
        return "1=0"
    if "Fresko Salesperson" in roles and not (roles & {"Fresko Accounts", "Fresko Approver"}):
        return "1=0"
    if roles & {"Fresko Accounts", "Fresko Approver"}:
        return ""
    return "1=0"


def collection_permission_query(user: str | None = None) -> str:
    return money_permission_query(COLLECTION, user)


def payment_allocation_permission_query(user: str | None = None) -> str:
    return money_permission_query(ALLOCATION, user)


def receivable_adjustment_permission_query(user: str | None = None) -> str:
    return money_permission_query(ADJUSTMENT, user)


def adjustment_application_permission_query(user: str | None = None) -> str:
    return money_permission_query(APPLICATION, user)


def money_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
    if (ptype or "read") not in READ_TYPES:
        return False
    user = user or frappe.session.user
    try:
        roles = _roles(user)
    except frappe.PermissionError:
        return False
    if any("supplier" in r.casefold() for r in roles):
        return False
    if "Fresko Salesperson" in roles and not (roles & {"Fresko Accounts", "Fresko Approver"}):
        return False
    if not roles & {"Fresko Accounts", "Fresko Approver"}:
        return False
    if doc is None or isinstance(doc, str):
        return False
    if user == frappe.session.user:
        try:
            _access(doc)
        except (frappe.PermissionError, frappe.ValidationError):
            return False
    return True


# --- Projections & Reconciliation Queries ---

def _state_at(doc, cutoff):
    result = None
    for event in json.loads(doc.decision_history or "[]"):
        if get_datetime(event["recorded_at"]) <= cutoff:
            result = event["snapshot"]
    return result


def get_collection_position(name: str, as_of: str | None = None) -> dict[str, Any]:
    roles = _roles()
    if not roles & {"Fresko Accounts", "Fresko Approver"}:
        _fail("Access denied to money position", True)
    coll = _load(COLLECTION, name)
    cutoff_text = _time(as_of or str(_now()), "as_of")
    cutoff = get_datetime(cutoff_text)

    state = _state_at(coll, cutoff)
    if state is None or state.get("status") in ("SUPERSEDED", "CANCELLED", "REJECTED", "REVERSED"):
        return {"name": coll.name, "as_of": cutoff_text, "exists": False, "allocations": []}

    effective_at = coll.get("effective_at")
    recorded_at = coll.get("recorded_at") or coll.get("creation")
    effective_and_recorded = True
    if effective_at and get_datetime(effective_at) > cutoff:
        effective_and_recorded = False
    if recorded_at and get_datetime(recorded_at) > cutoff:
        effective_and_recorded = False

    alloc_rows = frappe.db.sql(f"SELECT name FROM `tab{ALLOCATION}` WHERE collection=%s ORDER BY creation,name FOR UPDATE", (coll.name,), as_dict=True)
    allocations = []
    sale_allocated = Decimal(0)
    container_parked = Decimal(0)
    for row in alloc_rows:
        alloc_doc = frappe.get_doc(ALLOCATION, row.name, for_update=True)
        _access(alloc_doc)
        dec = _state_at(alloc_doc, cutoff)
        if not dec or dec.get("status") != "APPROVED":
            continue
        amt = Decimal(alloc_doc.amount)
        if alloc_doc.allocation_type == "SALE":
            sale_allocated += amt
        else:
            container_parked += amt
        allocations.append({
            "name": alloc_doc.name,
            "allocation_type": alloc_doc.allocation_type,
            "amount": alloc_doc.amount,
            "currency": alloc_doc.currency,
            "sale": alloc_doc.sale,
            "container": alloc_doc.container,
            "customer": alloc_doc.customer
        })

    total_allocated = sale_allocated + container_parked
    known_amount = Decimal(coll.amount) if coll.amount_state == "KNOWN" and coll.amount is not None else None
    unallocated = format(known_amount - total_allocated, ".2f") if known_amount is not None else None

    is_cash_declaration = coll.payment_channel == "CASH" and coll.direction == "INFLOW" and coll.source_classification == "CASH_DECLARATION"
    is_bank_cleared = coll.payment_channel == "BANK" and coll.bank_state == "BANK_CLEARED"
    is_bank_pending = coll.payment_channel == "BANK" and coll.bank_state in ("NONE", "UNKNOWN", "PENDING", "AUTHORIZATION_INPROCESS")
    receipt_received = effective_and_recorded and coll.receipt_state == "RECEIVED"
    historical = type("CollectionState", (), {**json.loads(coll.source_payload), "status": state.get("status")})()
    is_eligible = effective_and_recorded and _collection_eligible(historical)
    eligible_available_amount = unallocated if is_eligible else None
    site_tz = frappe.get_system_settings("time_zone")
    evidence_provenance = {
        "source_event": coll.source_event_id,
        "source_namespace": coll.source_namespace,
        "evidence_snapshot": json.loads(coll.evidence_snapshot) if coll.evidence_snapshot else None,
        "company": coll.company,
        "evidence": coll.get("evidence"),
        "source_evidence": coll.get("source_evidence"),
        "recorded_at": str(recorded_at) if recorded_at else None,
        "effective_at": str(effective_at) if effective_at else None
    }

    return {
        "name": coll.name,
        "as_of": cutoff_text,
        "exists": True,
        "company": coll.company,
        "status": state.get("status"),
        "payment_channel": coll.payment_channel,
        "direction": coll.direction,
        "bank_state": coll.bank_state,
        "is_bank_cleared": is_bank_cleared,
        "is_bank_pending": is_bank_pending,
        "is_cash_received": is_cash_declaration,
        "receipt_received": receipt_received,
        "eligible_available_amount": eligible_available_amount,
        "coverage": "CAPTURED_SUBSET",
        "site_timezone": site_tz,
        "source_event": coll.source_event_id,
        "source_namespace": coll.source_namespace,
        "evidence_snapshot": json.loads(coll.evidence_snapshot) if coll.evidence_snapshot else None,
        "evidence_provenance": evidence_provenance,
        "amount": coll.amount,
        "currency": coll.currency,
        "amount_state": coll.amount_state,
        "allocated_amount": format(total_allocated, ".2f"),
        "sale_allocated_amount": format(sale_allocated, ".2f"),
        "container_parked_amount": format(container_parked, ".2f"),
        "unallocated_amount": unallocated,
        "allocations": allocations
    }


def get_sale_receivable(sale: str, as_of: str | None = None) -> dict[str, Any]:
    roles = _roles()
    if not roles & {"Fresko Accounts", "Fresko Approver"}:
        _fail("Access denied to money position", True)
    from fresko_universe.fresko_core.services import commercial_service
    comm_view = commercial_service.get_sale_as_of(sale, as_of or str(_now()))
    if not comm_view.get("exists") or not comm_view.get("effective_at_cutoff") or comm_view.get("status") in ("SUPERSEDED", "CANCELLED", "REJECTED", "REVERSED"):
        return {"sale": sale, "exists": False, "as_of": as_of}

    cutoff_text = comm_view["as_of"]
    cutoff = get_datetime(cutoff_text)
    _locks(comm_view["company"], [comm_view["container"]] if comm_view.get("container") else [])

    lines = comm_view.get("lines") or []
    all_lines_final = bool(lines) and all(line.get("price_state") == "FINAL" for line in lines)
    is_qualifying_debt = (
        comm_view.get("status") == "APPROVED" and
        comm_view.get("effective_at_cutoff") is True and
        bool(comm_view.get("customer")) and
        all_lines_final
    )

    alloc_rows = frappe.db.sql(f"SELECT name FROM `tab{ALLOCATION}` WHERE sale=%s ORDER BY creation,name FOR UPDATE", (sale,), as_dict=True)
    cash_applied = Decimal(0)
    payment_allocations = []
    for row in alloc_rows:
        alloc_doc = frappe.get_doc(ALLOCATION, row.name, for_update=True)
        _access(alloc_doc)
        dec = _state_at(alloc_doc, cutoff)
        if dec and dec.get("status") == "APPROVED":
            cash_applied += Decimal(alloc_doc.amount)
            payment_allocations.append({
                "name": alloc_doc.name,
                "collection": alloc_doc.collection,
                "amount": alloc_doc.amount,
                "currency": alloc_doc.currency
            })

    adj_rows = frappe.db.sql(f"SELECT name FROM `tab{APPLICATION}` WHERE sale=%s ORDER BY creation,name FOR UPDATE", (sale,), as_dict=True)
    adj_applied = Decimal(0)
    adjustment_applications = []
    for row in adj_rows:
        app_doc = frappe.get_doc(APPLICATION, row.name, for_update=True)
        _access(app_doc)
        dec = _state_at(app_doc, cutoff)
        if dec and dec.get("status") == "APPROVED":
            adj_applied += Decimal(app_doc.amount)
            adjustment_applications.append({
                "name": app_doc.name,
                "receivable_adjustment": app_doc.receivable_adjustment,
                "amount": app_doc.amount,
                "currency": app_doc.currency
            })

    total_settled = cash_applied + adj_applied
    pending_count = comm_view.get("pending_amount_line_count", 0)
    gross_amount = Decimal(comm_view["known_commercial_amount"]) if comm_view.get("known_commercial_amount") is not None else None

    if not is_qualifying_debt:
        outstanding = None
    elif gross_amount is not None and pending_count == 0:
        outstanding = format(gross_amount - total_settled, ".2f")
    else:
        outstanding = None

    settlement_status = "UNSETTLED"
    if outstanding is not None and Decimal(outstanding) == Decimal(0) and comm_view.get("status") == "APPROVED":
        settlement_status = "SETTLED"
    elif total_settled > Decimal(0):
        settlement_status = "PARTIAL"

    return {
        "sale": sale,
        "as_of": cutoff_text,
        "exists": True,
        "is_qualifying_debt": is_qualifying_debt,
        "company": comm_view["company"],
        "container": comm_view.get("container"),
        "customer": comm_view.get("customer"),
        "currency": comm_view["currency"],
        "commercial_status": comm_view["status"],
        "gross_commercial_amount": comm_view.get("total_commercial_amount"),
        "known_commercial_amount": comm_view.get("known_commercial_amount"),
        "pending_amount_line_count": pending_count,
        "cash_applied_amount": format(cash_applied, ".2f"),
        "adjustment_applied_amount": format(adj_applied, ".2f"),
        "total_settled_amount": format(total_settled, ".2f"),
        "outstanding_receivable": outstanding,
        "settlement_status": settlement_status,
        "payment_allocations": payment_allocations,
        "adjustment_applications": adjustment_applications
    }


def get_container_receivable(container: str, as_of: str | None = None) -> dict[str, Any]:
    roles = _roles()
    if not roles & {"Fresko Accounts", "Fresko Approver"}:
        _fail("Access denied to money position", True)
    cont_doc = _linked("Fresko Container", container)
    _locks(cont_doc.company, [container])
    cutoff_text = _time(as_of or str(_now()), "as_of")
    cutoff = get_datetime(cutoff_text)

    sales_rows = frappe.db.sql(f"SELECT name FROM `tab{SALE}` WHERE container=%s ORDER BY sale_at,name FOR UPDATE", (container,), as_dict=True)
    sales_receivables = []
    gross_known_by_curr: dict[str, Decimal] = {}
    gross_unknown_counts: dict[str, int] = {}
    cash_by_curr: dict[str, Decimal] = {}
    adj_by_curr: dict[str, Decimal] = {}
    outstanding_known_by_curr: dict[str, Decimal] = {}
    outstanding_unknown_counts: dict[str, int] = {}
    unresolved_sales_count = 0

    for row in sales_rows:
        sr = get_sale_receivable(row.name, cutoff_text)
        if not sr.get("exists"):
            continue
        curr = sr["currency"]
        sales_receivables.append(sr)
        known_gross = sr.get("known_commercial_amount")
        if known_gross is not None:
            gross_known_by_curr[curr] = gross_known_by_curr.get(curr, Decimal(0)) + Decimal(known_gross)
        if sr.get("gross_commercial_amount") is None:
            gross_unknown_counts[curr] = gross_unknown_counts.get(curr, 0) + 1
            unresolved_sales_count += 1

        cash_by_curr[curr] = cash_by_curr.get(curr, Decimal(0)) + Decimal(sr["cash_applied_amount"])
        adj_by_curr[curr] = adj_by_curr.get(curr, Decimal(0)) + Decimal(sr["adjustment_applied_amount"])

        if sr.get("outstanding_receivable") is not None:
            outstanding_known_by_curr[curr] = outstanding_known_by_curr.get(curr, Decimal(0)) + Decimal(sr["outstanding_receivable"])
        else:
            outstanding_unknown_counts[curr] = outstanding_unknown_counts.get(curr, 0) + 1

    parked_rows = frappe.db.sql(f"SELECT name, amount, currency, collection FROM `tab{ALLOCATION}` WHERE container=%s AND allocation_type='CONTAINER_UNAPPLIED' ORDER BY creation,name FOR UPDATE", (container,), as_dict=True)
    parked_by_curr: dict[str, Decimal] = {}
    parked_allocations = []
    for row in parked_rows:
        alloc_doc = frappe.get_doc(ALLOCATION, row.name, for_update=True)
        _access(alloc_doc)
        dec = _state_at(alloc_doc, cutoff)
        if dec and dec.get("status") == "APPROVED":
            curr = alloc_doc.currency
            amt = Decimal(alloc_doc.amount)
            parked_by_curr[curr] = parked_by_curr.get(curr, Decimal(0)) + amt
            parked_allocations.append({"name": alloc_doc.name, "collection": alloc_doc.collection, "amount": alloc_doc.amount, "currency": curr})

    all_currencies = set(gross_known_by_curr) | set(gross_unknown_counts) | set(cash_by_curr) | set(adj_by_curr) | set(parked_by_curr)
    gross_sales_by_currency = {}
    outstanding_by_currency = {}
    for c in all_currencies:
        if gross_unknown_counts.get(c, 0) > 0:
            gross_sales_by_currency[c] = None
        else:
            gross_sales_by_currency[c] = format(gross_known_by_curr.get(c, Decimal(0)), ".2f")
        if outstanding_unknown_counts.get(c, 0) > 0:
            outstanding_by_currency[c] = None
        else:
            outstanding_by_currency[c] = format(outstanding_known_by_curr.get(c, Decimal(0)), ".2f")

    return {
        "container": container,
        "company": cont_doc.company,
        "as_of": cutoff_text,
        "sales_count": len(sales_receivables),
        "unresolved_pricing_sales_count": unresolved_sales_count,
        "gross_sales_by_currency": gross_sales_by_currency,
        "gross_sales_known_subtotal_by_currency": {c: format(v, ".2f") for c, v in gross_known_by_curr.items()},
        "gross_sales_unknown_count_by_currency": gross_unknown_counts,
        "cash_applied_by_currency": {c: format(cash_by_curr.get(c, Decimal(0)), ".2f") for c in all_currencies},
        "adjustments_by_currency": {c: format(adj_by_curr.get(c, Decimal(0)), ".2f") for c in all_currencies},
        "outstanding_receivable_by_currency": outstanding_by_currency,
        "outstanding_receivable_known_subtotal_by_currency": {c: format(v, ".2f") for c, v in outstanding_known_by_curr.items()},
        "outstanding_receivable_unknown_count_by_currency": outstanding_unknown_counts,
        "container_parked_by_currency": {c: format(parked_by_curr.get(c, Decimal(0)), ".2f") for c in all_currencies},
        "sales": sales_receivables,
        "container_parked_allocations": parked_allocations
    }


def get_customer_receivable(customer: str, company: str, as_of: str | None = None) -> dict[str, Any]:
    roles = _roles()
    if not roles & {"Fresko Accounts", "Fresko Approver"}:
        _fail("Access denied to money position", True)
    _locks(company)
    _linked("Customer", customer)
    cutoff_text = _time(as_of or str(_now()), "as_of")
    cutoff = get_datetime(cutoff_text)

    sales_rows = frappe.db.sql(f"SELECT name FROM `tab{SALE}` WHERE company=%s ORDER BY sale_at,name FOR UPDATE", (company,), as_dict=True)
    sales = []
    gross_known_by_curr: dict[str, Decimal] = {}
    gross_unknown_counts: dict[str, int] = {}
    cash_by_curr: dict[str, Decimal] = {}
    adj_by_curr: dict[str, Decimal] = {}
    outstanding_known_by_curr: dict[str, Decimal] = {}
    outstanding_unknown_counts: dict[str, int] = {}

    for row in sales_rows:
        sr = get_sale_receivable(row.name, cutoff_text)
        if not sr.get("exists") or sr.get("customer") != customer:
            continue
        curr = sr["currency"]
        sales.append(sr)
        known_gross = sr.get("known_commercial_amount")
        if known_gross is not None:
            gross_known_by_curr[curr] = gross_known_by_curr.get(curr, Decimal(0)) + Decimal(known_gross)
        if sr.get("gross_commercial_amount") is None:
            gross_unknown_counts[curr] = gross_unknown_counts.get(curr, 0) + 1

        cash_by_curr[curr] = cash_by_curr.get(curr, Decimal(0)) + Decimal(sr["cash_applied_amount"])
        adj_by_curr[curr] = adj_by_curr.get(curr, Decimal(0)) + Decimal(sr["adjustment_applied_amount"])

        if sr.get("outstanding_receivable") is not None:
            outstanding_known_by_curr[curr] = outstanding_known_by_curr.get(curr, Decimal(0)) + Decimal(sr["outstanding_receivable"])
        else:
            outstanding_unknown_counts[curr] = outstanding_unknown_counts.get(curr, 0) + 1

    adj_rows = frappe.db.sql(f"SELECT name FROM `tab{ADJUSTMENT}` WHERE company=%s AND customer=%s ORDER BY creation,name FOR UPDATE", (company, customer), as_dict=True)
    unapplied_adj_by_curr: dict[str, Decimal] = {}
    adjustments = []
    for row in adj_rows:
        adj_doc = frappe.get_doc(ADJUSTMENT, row.name, for_update=True)
        _access(adj_doc)
        state = _state_at(adj_doc, cutoff)
        if not state or state.get("status") != "APPROVED":
            continue

        app_rows = frappe.db.sql(f"SELECT name FROM `tab{APPLICATION}` WHERE receivable_adjustment=%s ORDER BY creation,name FOR UPDATE", (adj_doc.name,), as_dict=True)
        applied_amt = Decimal(0)
        for app_row in app_rows:
            app_doc = frappe.get_doc(APPLICATION, app_row.name, for_update=True)
            _access(app_doc)
            app_dec = _state_at(app_doc, cutoff)
            if app_dec and app_dec.get("status") == "APPROVED":
                applied_amt += Decimal(app_doc.amount)

        total_adj_amt = Decimal(adj_doc.amount)
        remaining_adj_amt = total_adj_amt - applied_amt

        rem_str = format(remaining_adj_amt, ".2f")
        unapplied_adj_by_curr[adj_doc.currency] = unapplied_adj_by_curr.get(adj_doc.currency, Decimal(0)) + remaining_adj_amt
        adjustments.append({
            "name": adj_doc.name,
            "adjustment_type": adj_doc.adjustment_type,
            "amount": adj_doc.amount,
            "unapplied_amount": rem_str,
            "currency": adj_doc.currency
        })

    all_currencies = set(gross_known_by_curr) | set(gross_unknown_counts) | set(cash_by_curr) | set(adj_by_curr) | set(unapplied_adj_by_curr)
    gross_sales_by_currency = {}
    outstanding_by_currency = {}
    for c in all_currencies:
        if gross_unknown_counts.get(c, 0) > 0:
            gross_sales_by_currency[c] = None
        else:
            gross_sales_by_currency[c] = format(gross_known_by_curr.get(c, Decimal(0)), ".2f")
        if outstanding_unknown_counts.get(c, 0) > 0:
            outstanding_by_currency[c] = None
        else:
            outstanding_by_currency[c] = format(outstanding_known_by_curr.get(c, Decimal(0)), ".2f")

    return {
        "customer": customer,
        "company": company,
        "as_of": cutoff_text,
        "gross_sales_by_currency": gross_sales_by_currency,
        "gross_sales_known_subtotal_by_currency": {c: format(v, ".2f") for c, v in gross_known_by_curr.items()},
        "gross_sales_unknown_count_by_currency": gross_unknown_counts,
        "cash_applied_by_currency": {c: format(cash_by_curr.get(c, Decimal(0)), ".2f") for c in all_currencies},
        "adjustments_by_currency": {c: format(adj_by_curr.get(c, Decimal(0)), ".2f") for c in all_currencies},
        "outstanding_receivable_by_currency": outstanding_by_currency,
        "outstanding_receivable_known_subtotal_by_currency": {c: format(v, ".2f") for c, v in outstanding_known_by_curr.items()},
        "outstanding_receivable_unknown_count_by_currency": outstanding_unknown_counts,
        "available_unapplied_adjustments_by_currency": {c: format(unapplied_adj_by_curr.get(c, Decimal(0)), ".2f") for c in all_currencies},
        "sales": sales,
        "adjustments": adjustments
    }


def get_unallocated_collections(company: str, as_of: str | None = None) -> dict[str, Any]:
    roles = _roles()
    if not roles & {"Fresko Accounts", "Fresko Approver"}:
        _fail("Access denied to money position", True)
    _locks(company)
    cutoff_text = _time(as_of or str(_now()), "as_of")
    cutoff = get_datetime(cutoff_text)

    rows = frappe.db.sql(f"SELECT name FROM `tab{COLLECTION}` WHERE company=%s AND direction='INFLOW' ORDER BY creation,name FOR UPDATE", (company,), as_dict=True)
    unallocated_by_curr: dict[str, Decimal] = {}
    cash_unallocated_by_curr: dict[str, Decimal] = {}
    bank_cleared_unallocated_by_curr: dict[str, Decimal] = {}
    collections = []

    for row in rows:
        pos = get_collection_position(row.name, cutoff_text)
        if not pos.get("exists") or pos.get("status") != "APPROVED":
            continue
        unalloc_str = pos.get("eligible_available_amount")
        if unalloc_str and Decimal(unalloc_str) > Decimal(0):
            curr = pos["currency"]
            amt = Decimal(unalloc_str)
            unallocated_by_curr[curr] = unallocated_by_curr.get(curr, Decimal(0)) + amt
            if pos["is_cash_received"]:
                cash_unallocated_by_curr[curr] = cash_unallocated_by_curr.get(curr, Decimal(0)) + amt
            elif pos["is_bank_cleared"]:
                bank_cleared_unallocated_by_curr[curr] = bank_cleared_unallocated_by_curr.get(curr, Decimal(0)) + amt
            collections.append(pos)

    all_currencies = set(unallocated_by_curr) | set(cash_unallocated_by_curr) | set(bank_cleared_unallocated_by_curr)
    return {
        "company": company,
        "as_of": cutoff_text,
        "total_unallocated_by_currency": {c: format(unallocated_by_curr.get(c, Decimal(0)), ".2f") for c in all_currencies},
        "cash_unallocated_by_currency": {c: format(cash_unallocated_by_curr.get(c, Decimal(0)), ".2f") for c in all_currencies},
        "bank_cleared_unallocated_by_currency": {c: format(bank_cleared_unallocated_by_curr.get(c, Decimal(0)), ".2f") for c in all_currencies},
        "unallocated_collections": collections
    }


def get_bank_pending_collections(company: str, as_of: str | None = None) -> dict[str, Any]:
    roles = _roles()
    if not roles & {"Fresko Accounts", "Fresko Approver"}:
        _fail("Access denied to money position", True)
    _locks(company)
    cutoff_text = _time(as_of or str(_now()), "as_of")
    cutoff = get_datetime(cutoff_text)

    rows = frappe.db.sql(f"SELECT name FROM `tab{COLLECTION}` WHERE company=%s AND payment_channel='BANK' ORDER BY creation,name FOR UPDATE", (company,), as_dict=True)
    known_pending_by_curr: dict[str, Decimal] = {}
    unknown_counts: dict[str, int] = {}
    pending_collections = []

    for row in rows:
        pos = get_collection_position(row.name, cutoff_text)
        if not pos.get("exists") or pos.get("status") in ("REJECTED", "SUPERSEDED", "REVERSED"):
            continue
        if not pos.get("is_bank_pending"):
            continue
        curr = pos["currency"]
        pending_collections.append(pos)
        if pos.get("amount") is not None and pos.get("amount_state") == "KNOWN":
            known_pending_by_curr[curr] = known_pending_by_curr.get(curr, Decimal(0)) + Decimal(pos["amount"])
        else:
            unknown_counts[curr] = unknown_counts.get(curr, 0) + 1

    all_currencies = set(known_pending_by_curr) | set(unknown_counts)
    pending_amount_by_currency = {}
    for c in all_currencies:
        if unknown_counts.get(c, 0) > 0:
            pending_amount_by_currency[c] = None
        else:
            pending_amount_by_currency[c] = format(known_pending_by_curr.get(c, Decimal(0)), ".2f")

    return {
        "company": company,
        "as_of": cutoff_text,
        "pending_count": len(pending_collections),
        "pending_amount_by_currency": pending_amount_by_currency,
        "pending_known_subtotal_by_currency": {c: format(v, ".2f") for c, v in known_pending_by_curr.items()},
        "pending_unknown_count_by_currency": unknown_counts,
        "collections": pending_collections
    }

MONEY_EXCEPTION_TYPES = {"MONEY_UNALLOCATED", "BANK_PENDING", "RECEIPT_AMOUNT_UNKNOWN", "RECEIPT_DIRECTION_UNKNOWN"}


def _refresh_collection_exceptions(coll):
    pending = set()
    if coll.status == "APPROVED":
        if coll.amount_state != "KNOWN":
            pending.add("RECEIPT_AMOUNT_UNKNOWN")
        if coll.direction == "UNKNOWN":
            pending.add("RECEIPT_DIRECTION_UNKNOWN")
        if coll.direction == "INFLOW" and coll.payment_channel == "BANK" and coll.bank_state != "BANK_CLEARED":
            pending.add("BANK_PENDING")
        if _collection_eligible(coll) and Decimal(coll.unallocated_amount or "0") > 0:
            pending.add("MONEY_UNALLOCATED")
    for kind in sorted(MONEY_EXCEPTION_TYPES):
        key = _hash(["money-exception-v1", coll.company, coll.name, kind])
        rows = frappe.db.sql("SELECT name FROM `tabFresko Exception` WHERE money_scope_key=%s FOR UPDATE", (key,), as_dict=True)
        if not rows and kind not in pending:
            continue
        if rows:
            exception = frappe.get_doc("Fresko Exception", rows[0].name, for_update=True)
            status = "Open" if kind in pending else "Resolved"
            if exception.status == status:
                continue
            exception.status = status
            if status == "Open":
                exception.resolved_by = exception.resolved_at = None
            exception.resolution_notes = "Controlled receipt reconciliation refreshed from accepted ledger state"
        else:
            exception = frappe.get_doc({"doctype": "Fresko Exception", "money_scope_key": key,
                "money_company": coll.company, "collection": coll.name, "exception_type": kind,
                "severity": "Material", "status": "Open", "as_of_recorded_at": _now(),
                "description": f"{kind} for Collection {coll.name}; source evidence and accepted receipt state govern reconciliation"})
        with _write():
            exception.save(ignore_permissions=True) if rows else exception.insert(ignore_permissions=True)


def validate_money_exception(doc):
    if not _SCOPE.get():
        _fail("Money Exceptions require the controlled service", True)
    if not doc.money_scope_key or not doc.money_company or not doc.collection:
        _fail("Money Exception requires server scope, Company and Collection")
    if doc.exception_type not in MONEY_EXCEPTION_TYPES or doc.get("commercial_scope_key") or doc.get("sale"):
        _fail("Invalid money Exception scope")
    parent = frappe.get_doc(COLLECTION, doc.collection)
    if parent.company != doc.money_company:
        _fail("Money Exception Company mismatch")
    if not doc.is_new():
        for field in ("money_scope_key", "money_company", "collection", "exception_type", "as_of_recorded_at"):
            if doc.has_value_changed(field):
                _fail(f"Money Exception {field} is immutable", True)


def exception_permission_query(user=None):
    from fresko_universe.fresko_core.services import commercial_service
    base = commercial_service.commercial_exception_permission_query(user)
    if money_permission_query(COLLECTION, user) == "1=0":
        return "(`tabFresko Exception`.money_scope_key IS NULL OR `tabFresko Exception`.money_scope_key='') AND (" + (base or "1=1") + ")"
    return base


def exception_has_permission(doc, ptype=None, user=None):
    if doc and doc.get("money_scope_key"):
        if (ptype or "read") not in READ_TYPES:
            return False
        return money_has_permission(frappe.get_doc(COLLECTION, doc.collection), ptype, user)
    from fresko_universe.fresko_core.services import commercial_service
    return commercial_service.commercial_exception_has_permission(doc, ptype, user)


def get_open_money_exceptions(company: str):
    if not _roles() & {"Fresko Accounts", "Fresko Approver"}:
        _fail("Money Exceptions require a financial role", True)
    _locks(company)
    rows = frappe.db.sql("SELECT name FROM `tabFresko Exception` WHERE money_company=%s AND status IN ('Open', 'In Progress') ORDER BY opened_at,name FOR UPDATE", (company,), as_dict=True)
    result = []
    for row in rows:
        doc = frappe.get_doc("Fresko Exception", row.name, for_update=True)
        _linked(COLLECTION, doc.collection)
        result.append({"name": doc.name, "exception_type": doc.exception_type, "status": doc.status,
            "collection": doc.collection, "severity": doc.severity, "description": doc.description,
            "opened_at": str(doc.opened_at), "money_scope_key": doc.money_scope_key})
    return {"company": company, "recorded_at": str(_now()), "coverage": "CAPTURED_SUBSET",
            "temporal_scope": "CURRENT_EXCEPTION_STATE", "exceptions": result}


def refresh_money_reconciliation(company: str) -> dict[str, Any]:
    roles = _roles()
    if not roles & {"Fresko Accounts", "Fresko Approver"}:
        _fail("Reconciliation refresh requires internal accounts or technical role", True)
    _locks(company)
    now_str = str(_now())
    unallocated = get_unallocated_collections(company, now_str)
    bank_pending = get_bank_pending_collections(company, now_str)
    rows = frappe.db.sql(f"SELECT name FROM `tab{COLLECTION}` WHERE company=%s AND status='APPROVED' FOR UPDATE", (company,), as_dict=True)
    for row in rows:
        c = frappe.get_doc(COLLECTION, row.name, for_update=True)
        _sync_collection_allocated_amounts(c)
    adj_rows = frappe.db.sql(f"SELECT name FROM `tab{ADJUSTMENT}` WHERE company=%s AND status='APPROVED' FOR UPDATE", (company,), as_dict=True)
    for row in adj_rows:
        a = frappe.get_doc(ADJUSTMENT, row.name, for_update=True)
        _sync_adjustment_applied_amounts(a)
    return {
        "company": company,
        "refreshed_at": now_str,
        "unallocated_collections": unallocated,
        "bank_pending_collections": bank_pending,
        "status": "REFRESHED"
    }


def _atomic(function):
    @wraps(function)
    def execute(*args, **kwargs):
        savepoint = "money_atomic_" + frappe.generate_hash(length=8)
        frappe.db.savepoint(savepoint)
        token = _OPERATION_TIME.set(_OPERATION_TIME.get())
        active_token = _OPERATION_ACTIVE.set(True)
        op_token = _OPERATION_ID.set(_OPERATION_ID.get())
        try:
            return function(*args, **kwargs)
        except Exception:
            frappe.db.rollback(save_point=savepoint)
            raise
        finally:
            _OPERATION_ID.reset(op_token)
            _OPERATION_ACTIVE.reset(active_token)
            _OPERATION_TIME.reset(token)
            frappe.db.release_savepoint(savepoint)
    return execute


for _method in (
    "create_collection", "submit_collection", "verify_collection", "approve_collection",
    "reject_collection", "reverse_collection", "supersede_collection",
    "propose_payment_allocation", "submit_payment_allocation", "verify_payment_allocation",
    "approve_payment_allocation", "reject_payment_allocation", "reverse_payment_allocation",
    "propose_adjustment", "submit_adjustment", "verify_adjustment", "approve_adjustment",
    "reject_adjustment", "reverse_adjustment",
    "propose_adjustment_application", "submit_adjustment_application", "verify_adjustment_application",
    "approve_adjustment_application", "reject_adjustment_application", "reverse_adjustment_application",
    "compensate_for_sale_change", "refresh_money_reconciliation"
):
    globals()[_method] = _atomic(globals()[_method])
