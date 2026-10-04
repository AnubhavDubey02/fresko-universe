from __future__ import annotations

from decimal import Decimal, InvalidOperation

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


_PAYLOAD_FIELDS = ("container", "basis", "raw_value", "quantity", "uom", "raw_uom", "evidence", "effective_at", "provenance", "reason", "supersedes", "source_fact_id", "assertion_key", "payload_sha256")


class FreskoContainerQuantityAssertion(Document):
    """Append-only quantity fact; all writes enter through quantity_assertion_service."""

    def before_insert(self):
        if not self.flags.get("in_service"):
            frappe.throw("Container Quantity Assertions can only be created through the controlled service", frappe.PermissionError)
        if self.status != "Draft":
            frappe.throw("New Container Quantity Assertions must start in Draft")
        self.prepared_by, self.prepared_at = frappe.session.user, now_datetime()
        self.reviewed_by = self.reviewed_at = self.activated_by = self.activated_at = self.superseded_by = None
        self.quantity = canonical_quantity(self.quantity)

    def validate(self):
        self._validate_payload()
        if self.is_new():
            self._validate_supersession()
            return
        if not self.flags.get("in_service"):
            frappe.throw("Direct modification of Container Quantity Assertions is forbidden", frappe.PermissionError)
        for field in _PAYLOAD_FIELDS:
            if self.has_value_changed(field):
                frappe.throw(f"Container Quantity Assertion payload field '{field}' is immutable", frappe.PermissionError)
        old = self.get_db_value("status")
        if self.status == old:
            frappe.throw("Container Quantity Assertion can be saved only for a controlled status transition")
        if old == "Draft" and self.status == "Review Pending" and frappe.session.user == self.prepared_by:
            return
        if old == "Review Pending" and self.status in ("Active", "Rejected"):
            if frappe.session.user == self.prepared_by:
                frappe.throw("Assertion maker cannot review their own assertion", frappe.PermissionError)
            self.reviewed_by, self.reviewed_at = frappe.session.user, now_datetime()
            if self.status == "Active":
                self.activated_by, self.activated_at = self.reviewed_by, self.reviewed_at
            return
        if old == "Active" and self.status == "Superseded" and self.superseded_by:
            return
        frappe.throw(f"Invalid Container Quantity Assertion transition {old} → {self.status}")

    def on_trash(self):
        frappe.throw("Container Quantity Assertions cannot be deleted; append a superseding assertion", frappe.PermissionError)

    def _validate_payload(self):
        if not str(self.raw_value or "").strip() or not str(self.reason or "").strip():
            frappe.throw("Raw Source Value and Reason are required")
        if not str(self.source_fact_id or "").strip() or not self.assertion_key or not self.payload_sha256:
            frappe.throw("Source Fact Identity, Assertion Key, and Payload SHA256 are service-assigned required fields")
        self.quantity = canonical_quantity(self.quantity)
        if self.quantity is not None and not self.uom:
            frappe.throw("A known quantity requires a UOM")

    def _validate_supersession(self):
        if not self.supersedes:
            return
        prior = frappe.db.get_value("Fresko Container Quantity Assertion", self.supersedes, ["container", "basis", "uom", "status"], as_dict=True)
        if not prior or prior.status != "Active":
            frappe.throw("supersedes must reference an Active Container Quantity Assertion")
        if (prior.container, prior.basis, prior.uom or "") != (self.container, self.basis, self.uom or ""):
            frappe.throw("A superseding quantity assertion must use the same container, basis, and UOM scope")


def canonical_quantity(value) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    text = str(value).strip()
    if "e" in text.lower():
        frappe.throw("Quantity exponent notation is not permitted")
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        frappe.throw("Quantity must be a decimal value or blank")
    if not number.is_finite() or number < 0:
        frappe.throw("Quantity must be finite and non-negative")
    normalized = format(number.normalize(), "f")
    return "0" if normalized in ("-0", "") else normalized
