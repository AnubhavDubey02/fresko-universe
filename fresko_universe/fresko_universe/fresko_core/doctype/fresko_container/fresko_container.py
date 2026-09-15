# Copyright (c) 2026, Fresko and contributors
# License: MIT

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from fresko_universe.constants import CONTAINER_STATUS_TRANSITIONS


class FreskoContainer(Document):
    def validate(self):
        self._validate_unique_container_no()
        self._validate_lots()
        self._validate_inward_qty()
        self._validate_status_transition()
        self._validate_close_gate()

    def _validate_unique_container_no(self):
        if not self.container_no or not self.company:
            return
        existing = frappe.db.exists(
            "Fresko Container",
            {
                "company": self.company,
                "container_no": self.container_no,
                "name": ("!=", self.name),
            },
        )
        if existing:
            frappe.throw(
                f"Container No {self.container_no!r} already exists for company {self.company} ({existing})"
            )

    def _validate_lots(self):
        seen = set()
        for row in self.get("lots") or []:
            if not row.lot_no:
                frappe.throw("Lot No is required on every lot row")
            if row.lot_no in seen:
                frappe.throw(f"Duplicate lot_no {row.lot_no!r} on container")
            seen.add(row.lot_no)
            if flt(row.inward_qty) < 0:
                frappe.throw(f"Lot {row.lot_no}: inward_qty cannot be negative")

        if self.status in ("Arrived", "In Cold Storage", "Selling", "Closing", "Closed"):
            if not self.get("lots"):
                frappe.throw("Lots are required once container status is Arrived or later")

        if self.get("lots"):
            lot_sum = sum(flt(r.inward_qty) for r in self.lots)
            if abs(lot_sum - flt(self.inward_qty)) > 0.0001:
                frappe.throw(
                    f"Container inward_qty ({self.inward_qty}) must equal sum of lot inward_qty ({lot_sum})"
                )

    def _validate_inward_qty(self):
        if self.inward_qty is not None and flt(self.inward_qty) <= 0 and self.status not in (
            "Draft",
            "Expected",
            "Cancelled",
        ):
            frappe.throw("Inward Qty must be > 0 once container has arrived")
        if not self.is_new() and self.has_value_changed("inward_qty"):
            if self.status in ("Selling", "Closing", "Closed") and not self.flags.get(
                "inward_qty_change_reason"
            ):
                frappe.throw(
                    "Cannot change Inward Qty after selling started without an explicit reason"
                )

    def _validate_status_transition(self):
        if self.is_new():
            return
        old = self.get_db_value("status")
        if old == self.status:
            return
        allowed = CONTAINER_STATUS_TRANSITIONS.get(old, set())
        if self.status not in allowed:
            frappe.throw(f"Invalid container status transition {old} → {self.status}")

    def _validate_close_gate(self):
        if self.closing_status != "Fully Reconciled":
            return
        if self.status != "Closed":
            frappe.throw("Set Status to Closed before Fully Reconciled")
        open_material = frappe.get_all(
            "Fresko Exception",
            filters={
                "container": self.name,
                "status": ("in", ["Open", "In Progress"]),
                "exception_type": (
                    "in",
                    [
                        "BUYER_UNRESOLVED",
                        "OVERSELL_OVERRIDE",
                        "STOCK_SHORTFALL",
                        "DATA_INTEGRITY",
                        "DUPLICATE_MESSAGE",
                        "RATE_FLOOR_BREACH",
                    ],
                ),
            },
            limit=1,
        )
        if open_material:
            frappe.throw(
                "Cannot set Fully Reconciled while open material Exceptions exist on this container"
            )



@frappe.whitelist()
def container_snapshot(container: str, lot_no: str | None = None):
    from fresko_universe.fresko_core.ats import available_to_sell
    from frappe.utils import flt

    doc = frappe.get_doc("Fresko Container", container)
    lots_out = []
    for row in doc.get("lots") or []:
        if lot_no and row.lot_no != lot_no:
            continue
        ats = available_to_sell(container, row.lot_no)
        inward = flt(row.inward_qty)
        lots_out.append({
            "lot_no": row.lot_no,
            "inward_qty": inward,
            "approved_sold": inward - ats,
            "available_to_sell": ats,
            "count_size": row.count_size,
            "uom": row.uom,
        })
    return {
        "container": doc.name,
        "container_no": doc.container_no,
        "status": doc.status,
        "inward_qty": flt(doc.inward_qty),
        "uom": doc.uom,
        "lots": lots_out,
        "approved_sold_total": sum(l["approved_sold"] for l in lots_out),
        "available_to_sell_total": sum(l["available_to_sell"] for l in lots_out),
    }
