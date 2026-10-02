"""Controlled immutable Container quantity assertions and reconciliation projection."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from fresko_universe import permissions
from fresko_universe.fresko_core.ats import lock_container_for_update
from fresko_universe.fresko_core.doctype.fresko_container_quantity_assertion.fresko_container_quantity_assertion import canonical_quantity


PAYLOAD_VERSION = "fresko-container-quantity-assertion:v1"


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _assert_evidence(container: str, evidence: str) -> None:
    if not frappe.db.exists("Fresko Evidence", evidence):
        frappe.throw(_("Fresko Evidence {0} does not exist").format(evidence))
    if not permissions.evidence_has_permission(evidence, "read", user=frappe.session.user):
        frappe.throw(_("Access denied to supporting Evidence"), frappe.PermissionError)
    if str(frappe.db.get_value("Fresko Evidence", evidence, "container") or "") != str(container):
        frappe.throw(_("Supporting Evidence must be scoped to the same Container"))


def _response(doc, *, replayed=False) -> dict[str, Any]:
    return {"name": doc.name, "container": doc.container, "basis": doc.basis, "quantity": doc.quantity, "uom": doc.uom, "status": doc.status, "replayed": replayed}


def create_quantity_assertion(*, container: str, basis: str, raw_value: str, quantity: Any, uom: str | None, raw_uom: str | None, evidence: str, effective_at: str | None, provenance: str, reason: str, source_fact_id: str, supersedes: str | None = None) -> dict[str, Any]:
    permissions.assert_can_prepare_quantity_assertion()
    if not frappe.db.exists("Fresko Container", container):
        frappe.throw(_("Fresko Container {0} does not exist").format(container))
    lock_container_for_update(container)
    basis, provenance, source_fact_id = _clean(basis), _clean(provenance), _clean(source_fact_id)
    if basis not in {"DECLARED_SHIPPING", "CUSTOMS_DECLARED", "OPERATING_INWARD"}:
        frappe.throw(_("basis is invalid"))
    if provenance not in {"SOURCE_EXTRACTED", "USER_CONFIRMED", "AUTHORIZED_DECISION"}:
        frappe.throw(_("provenance is invalid"))
    if raw_value is None or not str(raw_value).strip() or not source_fact_id:
        frappe.throw(_("raw_value and source_fact_id are required"))
    quantity, uom, raw_uom, reason, supersedes = canonical_quantity(quantity), _clean(uom), _clean(raw_uom), _clean(reason), _clean(supersedes)
    if quantity is not None and not uom:
        frappe.throw(_("A known quantity requires uom"))
    if not reason:
        frappe.throw(_("reason is required"))
    _assert_evidence(container, evidence)
    # Source fact identifiers are only meaningful inside their evidence envelope.
    identity = {"version": PAYLOAD_VERSION, "container": container, "basis": basis, "evidence": evidence, "source_fact_id": source_fact_id}
    payload = {**identity, "raw_value": str(raw_value), "quantity": quantity, "uom": uom, "raw_uom": raw_uom, "evidence": evidence, "effective_at": str(effective_at) if effective_at else None, "provenance": provenance, "reason": reason, "supersedes": supersedes}
    assertion_key, payload_sha256 = _sha(identity), _sha(payload)
    existing = frappe.db.get_value("Fresko Container Quantity Assertion", {"assertion_key": assertion_key}, "name")
    if existing:
        return _replay(existing, payload_sha256)
    doc = frappe.get_doc({"doctype": "Fresko Container Quantity Assertion", **{key: value for key, value in payload.items() if key != "version"}, "assertion_key": assertion_key, "payload_sha256": payload_sha256, "status": "Draft", "prepared_by": frappe.session.user, "prepared_at": now_datetime()})
    doc.flags.in_service = True
    try:
        doc.insert(ignore_permissions=True)
    except frappe.UniqueValidationError:
        existing = frappe.db.get_value("Fresko Container Quantity Assertion", {"assertion_key": assertion_key}, "name")
        if not existing:
            raise
        return _replay(existing, payload_sha256)
    return _response(doc)


def _replay(name: str, payload_sha256: str) -> dict[str, Any]:
    if not permissions.quantity_assertion_has_permission(name, "read", frappe.session.user):
        frappe.throw(_("Access denied"), frappe.PermissionError)
    doc = frappe.get_doc("Fresko Container Quantity Assertion", name)
    if doc.payload_sha256 != payload_sha256:
        # The existing schema has no dedicated conflict ledger; do not claim durable conflict capture.
        frappe.throw(_("Quantity assertion source identity already exists with a different payload"), frappe.UniqueValidationError)
    return _response(doc, replayed=True)


def _locked(name: str):
    probe = frappe.get_doc("Fresko Container Quantity Assertion", name)
    lock_container_for_update(probe.container)
    return frappe.get_doc("Fresko Container Quantity Assertion", name, for_update=True)


def submit_quantity_assertion(name: str) -> dict[str, Any]:
    permissions.assert_can_prepare_quantity_assertion()
    doc = _locked(name)
    if doc.prepared_by != frappe.session.user:
        frappe.throw(_("Only the assertion maker may submit it"), frappe.PermissionError)
    if doc.status == "Review Pending":
        return _response(doc, replayed=True)
    if doc.status != "Draft":
        frappe.throw(_("Only a Draft quantity assertion may be submitted"))
    doc.flags.in_service = True
    doc.status = "Review Pending"
    doc.save(ignore_permissions=True)
    return _response(doc)


def review_quantity_assertion(name: str, decision: str) -> dict[str, Any]:
    permissions.assert_can_activate_quantity_assertion()
    doc = _locked(name)
    decision = _clean(decision)
    if decision not in {"ACTIVATE", "REJECT"}:
        frappe.throw(_("decision must be ACTIVATE or REJECT"))
    if doc.status in {"Active", "Rejected"}:
        if (doc.status == "Active") == (decision == "ACTIVATE"):
            return _response(doc, replayed=True)
        frappe.throw(_("Assertion already has a different terminal review decision"))
    if doc.status != "Review Pending":
        frappe.throw(_("Only a Review Pending quantity assertion may be reviewed"))
    if doc.prepared_by == frappe.session.user:
        frappe.throw(_("Assertion maker cannot review their own assertion"), frappe.PermissionError)
    doc.flags.in_service = True
    if decision == "REJECT":
        doc.status = "Rejected"
        doc.save(ignore_permissions=True)
        return _response(doc)
    _activate(doc)
    doc.status = "Active"
    doc.save(ignore_permissions=True)
    return _response(doc)


def _activate(doc) -> None:
    active = frappe.db.sql("""SELECT name FROM `tabFresko Container Quantity Assertion` WHERE container=%s AND basis=%s AND IFNULL(uom, '')=%s AND status='Active' FOR UPDATE""", (doc.container, doc.basis, doc.uom or ""), as_dict=True)
    if doc.supersedes:
        prior = frappe.get_doc("Fresko Container Quantity Assertion", doc.supersedes, for_update=True)
        if prior.status != "Active" or any(row.name != prior.name for row in active):
            frappe.throw(_("supersedes must be the sole active assertion in this scope"))
        successor = frappe.db.get_value("Fresko Container Quantity Assertion", {"supersedes": prior.name, "status": ("in", ["Active", "Superseded"])}, "name")
        if successor:
            frappe.throw(_("The prior assertion already has an activated successor"))
        prior.flags.in_service = True
        prior.superseded_by, prior.status = doc.name, "Superseded"
        prior.save(ignore_permissions=True)
    elif active:
        frappe.throw(_("An active quantity assertion already exists; correction must supersede it"))


def quantity_reconciliation_projection(container: str) -> dict[str, Any]:
    """Read-only comparison; no stock, ATS, Container mutation, or exception side effects."""
    if not frappe.db.exists("Fresko Container", container):
        frappe.throw(_("Fresko Container {0} does not exist").format(container))
    if not frappe.has_permission("Fresko Container", ptype="read", doc=frappe.get_doc("Fresko Container", container)):
        frappe.throw(_("Access denied"), frappe.PermissionError)
    declared = _latest(container, "DECLARED_SHIPPING")
    if not declared or declared.quantity is None:
        return {"container": container, "reconciliation_status": "UNRESOLVED", "reason": "declared shipping quantity is unknown or absent", "todo": "PHYSICAL_VARIANCE exception creation requires an Outward-linked service and is intentionally not invoked"}
    operating = _latest(container, "OPERATING_INWARD", uom=declared.uom)
    # An active operating assertion in another UOM is explicit source data,
    # so it must block the legacy Container.inward_qty compatibility fallback.
    any_operating = _latest(container, "OPERATING_INWARD")
    compatibility = False
    if not operating and not any_operating:
        legacy = frappe.get_doc("Fresko Container", container)
        legacy_uom = _clean(getattr(legacy, "uom", None))
        if legacy.inward_qty is not None and legacy_uom == declared.uom:
            operating = type("Legacy", (), {"name": None, "quantity": canonical_quantity(legacy.inward_qty), "uom": legacy_uom})()
            compatibility = True
    if not operating or operating.quantity is None:
        return {"container": container, "declared_assertion": declared.name, "reconciliation_status": "UNRESOLVED", "reason": "no same-UOM active operating inward assertion", "todo": "PHYSICAL_VARIANCE exception creation requires an Outward-linked service and is intentionally not invoked"}
    variance = format(Decimal(declared.quantity) - Decimal(operating.quantity), "f")
    return {"container": container, "declared_assertion": declared.name, "operating_assertion": operating.name, "uom": declared.uom, "declared_quantity": declared.quantity, "operating_quantity": operating.quantity, "operating_basis": "COMPATIBILITY_OPERATIONAL_INWARD" if compatibility else "OPERATING_INWARD", "variance": variance, "reconciliation_status": "OPEN_VARIANCE" if Decimal(variance) else "MATCH", "todo": "PHYSICAL_VARIANCE exception creation requires an Outward-linked service and is intentionally not invoked"}


def _latest(container: str, basis: str, uom: str | None = None):
    filters = {"container": container, "basis": basis, "status": "Active"}
    if uom is not None:
        filters["uom"] = uom
    names = frappe.get_all("Fresko Container Quantity Assertion", filters=filters, order_by="activated_at desc, creation desc, name desc", limit=1, pluck="name")
    return frappe.get_doc("Fresko Container Quantity Assertion", names[0]) if names else None
