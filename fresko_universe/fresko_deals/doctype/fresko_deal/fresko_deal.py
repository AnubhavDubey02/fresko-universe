# Copyright (c) 2026, Fresko and contributors
# License: MIT

from __future__ import annotations

import hashlib

import frappe
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from fresko_universe.constants import (
    COMMERCIAL_LOCK_STATUSES,
    DEAL_TRANSITIONS,
    LOCKED_COMMERCIAL_FIELDS,
)


class FreskoDeal(Document):
    def before_insert(self):
        if self.status and self.status != "Proposed":
            frappe.throw("New deals must start as Proposed")
        self.status = "Proposed"
        if not self.created_on:
            self.created_on = frappe.utils.now_datetime()
        if not self.duplicate_fingerprint:
            self.duplicate_fingerprint = self.make_fingerprint()

    def validate(self):
        self._set_title()
        self._fetch_defaults_from_container()
        self._validate_qty()
        self._validate_lot_belongs_to_container()
        self._validate_buyer_alias_immutable()
        self._validate_idempotency_keys()
        self._validate_status_transition()
        self._enforce_commercial_lock()
        self._enforce_dispatched_qty_lock()
        self._validate_reconciled_gate()
        self._compute_amount()
        if self.status == "Cancelled" and not self.cancel_reason:
            frappe.throw("cancel_reason is required when status is Cancelled")

    def _set_title(self):
        alias = self.buyer_alias or ""
        self.title = f"{alias} · {flt(self.qty)} · {self.lot_no or ''}".strip(" ·")

    def _fetch_defaults_from_container(self):
        if not self.container:
            return
        container = frappe.db.get_value(
            "Fresko Container",
            self.container,
            ["company", "item", "uom", "currency"],
            as_dict=True,
        )
        if not container:
            frappe.throw(f"Container {self.container} not found")
        if not self.company:
            self.company = container.company
        if not self.item:
            self.item = container.item
        if not self.uom:
            self.uom = container.uom
        if not self.currency:
            self.currency = container.currency

    def _validate_qty(self):
        if flt(self.qty) <= 0:
            frappe.throw("Deal qty must be > 0")

    def _validate_lot_belongs_to_container(self):
        if not self.container or not self.lot_no:
            return
        lots = frappe.get_all(
            "Fresko Container Lot",
            filters={
                "parent": self.container,
                "parenttype": "Fresko Container",
                "lot_no": self.lot_no,
            },
            fields=["name", "batch", "count_size", "uom"],
            limit=1,
        )
        if not lots:
            frappe.throw(
                f"Lot {self.lot_no!r} does not belong to container {self.container}"
            )
        row = lots[0]
        if not self.container_lot:
            self.container_lot = row.name
        elif self.container_lot != row.name:
            # allow if lot_no matches; sync row name
            self.container_lot = row.name
        if not self.batch and row.batch:
            self.batch = row.batch
        if not self.count_size and row.count_size:
            self.count_size = row.count_size

    def _validate_buyer_alias_immutable(self):
        if self.is_new():
            return
        if self.has_value_changed("buyer_alias"):
            frappe.throw("buyer_alias is immutable after insert (D6)")
        # Never allow clearing
        if not (self.buyer_alias or "").strip():
            frappe.throw("buyer_alias cannot be empty")

    def _validate_idempotency_keys(self):
        if self.source_message_id:
            if not self.is_new() and self.has_value_changed("source_message_id"):
                old = self.get_db_value("source_message_id")
                if old:
                    frappe.throw("source_message_id is immutable once set")
            existing = frappe.db.exists(
                "Fresko Deal",
                {"source_message_id": self.source_message_id, "name": ("!=", self.name)},
            )
            if existing:
                frappe.throw(
                    f"Duplicate source_message_id {self.source_message_id!r} — "
                    f"already on deal {existing}",
                    title="Duplicate Message",
                )

        if self.duplicate_fingerprint:
            if not self.is_new() and self.has_value_changed("duplicate_fingerprint"):
                old = self.get_db_value("duplicate_fingerprint")
                if old:
                    frappe.throw("duplicate_fingerprint is immutable once set")
            existing = frappe.db.exists(
                "Fresko Deal",
                {
                    "duplicate_fingerprint": self.duplicate_fingerprint,
                    "name": ("!=", self.name),
                },
            )
            if existing:
                # Attach evidence + exception path (blueprint)
                self._raise_duplicate_fingerprint(existing)

    def _raise_duplicate_fingerprint(self, existing_deal: str):
        # Create Evidence + Exception on the existing deal; never create second deal
        try:
            ev = frappe.get_doc(
                {
                    "doctype": "Fresko Evidence",
                    "evidence_type": "Note",
                    "deal": existing_deal,
                    "container": self.container,
                    "message_id": self.source_message_id,
                    "notes": (
                        f"Duplicate fingerprint attempt blocked. "
                        f"fingerprint={self.duplicate_fingerprint}"
                    ),
                }
            )
            ev.insert(ignore_permissions=True)
            ex = frappe.get_doc(
                {
                    "doctype": "Fresko Exception",
                    "exception_type": "DUPLICATE_MESSAGE",
                    "severity": "Material",
                    "status": "Open",
                    "deal": existing_deal,
                    "container": self.container,
                    "description": (
                        f"Duplicate deal fingerprint {self.duplicate_fingerprint} "
                        f"blocked; evidence {ev.name}"
                    ),
                }
            )
            ex.insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(title="duplicate fingerprint side-effects")
        frappe.throw(
            f"Duplicate fingerprint — attach to existing deal {existing_deal}; "
            "second Deal not created",
            title="Duplicate Fingerprint",
        )

    def _validate_status_transition(self):
        if self.is_new():
            return
        old = self.get_db_value("status")
        if old == self.status:
            return
        # Only whitelist methods may change status (flags.allow_status_transition)
        if not self.flags.get("allow_status_transition"):
            frappe.throw(
                f"Illegal Desk/API status transition {old} → {self.status}. "
                "Use whitelist methods only."
            )
        allowed = DEAL_TRANSITIONS.get(old, set())
        if self.status not in allowed:
            frappe.throw(f"Invalid deal status transition {old} → {self.status}")

    def _enforce_commercial_lock(self):
        if self.is_new():
            return
        old_status = self.get_db_value("status")
        locked = old_status in COMMERCIAL_LOCK_STATUSES or self.status in COMMERCIAL_LOCK_STATUSES

        if self.has_value_changed("approved_rate") and not self.flags.get("allow_approval_write"):
            frappe.throw("approved_rate can only be set by the approval / revision decision path")

        if not locked:
            # Still freeze proposed_rate after leaving Proposed
            if old_status != "Proposed" and self.has_value_changed("proposed_rate"):
                if not self.flags.get("allow_commercial_revision"):
                    frappe.throw("proposed_rate is frozen after leaving Proposed")
            return

        for f in LOCKED_COMMERCIAL_FIELDS:
            if f == "approved_rate":
                continue  # handled above
            if self.has_value_changed(f) and not self.flags.get("allow_commercial_revision"):
                frappe.throw(
                    f"Cannot change {f} after commercial approval without revision flow"
                )

    def _enforce_dispatched_qty_lock(self):
        """Server-only writes + physical ceiling (never forge ATS via Desk edit)."""
        if flt(self.dispatched_qty or 0) < 0:
            frappe.throw("dispatched_qty cannot be negative")
        if flt(self.dispatched_qty or 0) > flt(self.qty):
            frappe.throw(
                f"dispatched_qty {self.dispatched_qty} cannot exceed deal qty {self.qty} "
                "(physical ceiling; even under commercial oversell)"
            )
        if self.is_new():
            if flt(self.dispatched_qty or 0) != 0 and not self.flags.get("allow_dispatch_write"):
                frappe.throw("dispatched_qty is server-only; use deals.record_dispatch")
            return
        if self.has_value_changed("dispatched_qty") and not self.flags.get("allow_dispatch_write"):
            frappe.throw(
                "dispatched_qty is server-only (read_only + validate). "
                "Desk/API direct edits rejected — use deals.record_dispatch. "
                "frappe.db.set_value bypass is unsupported and must not be used."
            )

    def _validate_reconciled_gate(self):
        if self.status != "Reconciled":
            return
        if not self.customer:
            frappe.throw(
                "Cannot set Reconciled while Customer is unresolved (D6 / BUYER_UNRESOLVED)"
            )
        open_buyer = frappe.get_all(
            "Fresko Exception",
            filters={
                "deal": self.name,
                "exception_type": "BUYER_UNRESOLVED",
                "status": ("in", ["Open", "In Progress"]),
            },
            limit=1,
        )
        if open_buyer:
            frappe.throw("Cannot set Reconciled while BUYER_UNRESOLVED Exception is open")

    def _compute_amount(self):
        # RC: Countered must not present unaccepted counter as approved commercial amount.
        # Counter rate lives on Approval.decision_rate; approved_rate stays NULL until accept.
        if self.status == "Countered" or self.approved_rate is None:
            rate = self.proposed_rate
        else:
            rate = self.approved_rate
        self.amount = flt(self.qty) * flt(rate)

    def make_fingerprint(self) -> str:
        """Locked algorithm from blueprint §B."""
        day = nowdate()
        if self.created_on:
            day = str(self.created_on)[:10]
        raw = "|".join(
            [
                (self.buyer_alias or "").strip().lower(),
                self.container or "",
                self.lot_no or "",
                _format_num(self.qty),
                _format_num(self.proposed_rate),
                self.uom or "",
                day,
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def set_status(self, new_status: str):
        """Internal helper for whitelist methods."""
        self.flags.allow_status_transition = True
        self.status = new_status


def _format_num(val) -> str:
    return f"{flt(val):.6f}".rstrip("0").rstrip(".") if val is not None else "0"
