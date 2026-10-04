# Copyright (c) 2026, Fresko and contributors
# License: MIT

import frappe
from frappe.model.document import Document
from frappe.utils import flt, get_system_timezone, now_datetime

from fresko_universe.constants import CONTAINER_STATUS_TRANSITIONS


class FreskoContainer(Document):
    def validate(self):
        if self.closing_status == "Fully Reconciled":
            from fresko_universe.fresko_core.services.close_gate_service import lock_close_gate_company

            lock_close_gate_company(self.company)
        if not self.is_new():
            from fresko_universe.fresko_core.ats import lock_container_for_update

            lock_container_for_update(self.name)
        self._validate_unique_container_no()
        self._validate_lots()
        self._validate_inward_qty()
        self._validate_inward_vs_posted_physical()
        self._validate_inward_vs_approved_sold()
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
            if not row.uom:
                frappe.throw(f"Lot {row.lot_no}: UOM is required")
            if self.uom and row.uom != self.uom:
                frappe.throw(
                    f"Lot {row.lot_no}: UOM {row.uom!r} must match "
                    f"Container UOM {self.uom!r} until conversions are modeled"
                )

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

    def _validate_inward_vs_posted_physical(self):
        """Never let mutable inward setup undercut immutable posted movement truth."""
        if self.is_new():
            return
        from fresko_universe.fresko_core.physical import posted_physical_quantities

        posted_by_lot, unmapped = posted_physical_quantities(
            self.name, for_update=True
        )
        incoming_lots = {
            row.lot_no: row for row in (self.get("lots") or []) if row.lot_no
        }
        db_lots = {
            row.lot_no: row.uom
            for row in frappe.db.sql(
                """
                SELECT lot_no, uom
                FROM `tabFresko Container Lot`
                WHERE parent=%s AND parenttype='Fresko Container'
                FOR UPDATE
                """,
                (self.name,),
                as_dict=True,
            )
        }
        for lot_no, posted in posted_by_lot.items():
            if flt(posted) <= 1e-9:
                continue
            row = incoming_lots.get(lot_no)
            if not row:
                frappe.throw(
                    f"Cannot remove lot {lot_no}: posted physical quantity {posted} remains"
                )
            if flt(row.inward_qty) + 1e-9 < flt(posted):
                frappe.throw(
                    f"Lot {lot_no}: inward_qty {row.inward_qty} cannot be below "
                    f"posted physical quantity {posted}"
                )
            if db_lots.get(lot_no) and row.uom != db_lots[lot_no]:
                frappe.throw(
                    f"Lot {lot_no}: UOM cannot change while posted physical quantity remains"
                )

        posted_total = sum(flt(value) for value in posted_by_lot.values()) + flt(
            unmapped
        )
        if flt(self.inward_qty) + 1e-9 < posted_total:
            frappe.throw(
                f"Container inward_qty {self.inward_qty} cannot be below posted "
                f"physical quantity {posted_total}"
            )
        if posted_total > 1e-9 and self.has_value_changed("uom"):
            frappe.throw(
                "Container UOM cannot change while posted physical quantity remains"
            )

    def _validate_inward_vs_approved_sold(self):
        """F-H1: cannot lower lot/container inward below approved_sold.

        Also blocks deleting a lot row that still has approved_sold > 0
        (otherwise removing the lot would bypass the inward floor check).
        """
        if self.is_new():
            return
        from fresko_universe.fresko_core.ats import approved_sold

        current_lots = {row.lot_no for row in self.get("lots") or [] if row.lot_no}
        db_lots = frappe.get_all(
            "Fresko Container Lot",
            filters={"parent": self.name, "parenttype": "Fresko Container"},
            fields=["lot_no"],
        )
        for db_row in db_lots:
            lot_no = db_row.lot_no
            if lot_no and lot_no not in current_lots:
                sold = approved_sold(self.name, lot_no)
                if flt(sold) > 1e-9:
                    frappe.throw(
                        f"Cannot remove lot {lot_no}: approved_sold {sold} > 0 (F-H1)"
                    )

        for row in self.get("lots") or []:
            sold = approved_sold(self.name, row.lot_no)
            if flt(row.inward_qty) + 1e-9 < flt(sold):
                frappe.throw(
                    f"Lot {row.lot_no}: inward_qty {row.inward_qty} cannot be below "
                    f"approved_sold {sold} (F-H1 / DATA_INTEGRITY)"
                )
        # Container total vs sum of approved across lots
        if self.get("lots"):
            total_sold = approved_sold(self.name, None)
            if flt(self.inward_qty) + 1e-9 < flt(total_sold):
                frappe.throw(
                    f"Container inward_qty {self.inward_qty} cannot be below "
                    f"total approved_sold {total_sold} (F-H1)"
                )
        elif flt(approved_sold(self.name, None)) > 1e-9:
            # All lots removed but commercial sold remains
            frappe.throw(
                f"Cannot clear all lots while approved_sold remains "
                f"(F-H1 / DATA_INTEGRITY)"
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
        from fresko_universe.fresko_core.services.close_gate_service import assert_container_can_fully_reconcile

        assert_container_can_fully_reconcile(self.name, self.company)


@frappe.whitelist()
def container_snapshot(container: str, lot_no: str | None = None):
    from fresko_universe.fresko_core.ats import available_to_sell
    from fresko_universe.fresko_core.physical import physical_snapshot
    from fresko_universe.permissions import (
        assert_can_read_ats_snapshot,
        deal_has_permission,
        outward_has_permission,
    )
    from frappe.utils import flt

    assert_can_read_ats_snapshot()
    snapshot_as_of = now_datetime()
    doc = frappe.get_doc("Fresko Container", container)
    physical = physical_snapshot(container)
    visible_movements = [
        row
        for row in physical["movements"]
        if outward_has_permission(row.name, "read", user=frappe.session.user)
    ]
    visible_outward_names = [row.name for row in visible_movements]
    physical_view = dict(physical)
    physical_view["movements"] = visible_movements
    physical_view["line_provenance"] = [
        row
        for row in physical["line_provenance"]
        if row.outward in visible_outward_names
    ]
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
            "posted_physical_outward": flt(
                physical["posted_by_lot"].get(row.lot_no)
            ),
            "physical_remaining": inward
            - flt(physical["posted_by_lot"].get(row.lot_no)),
            "count_size": row.count_size,
            "uom": row.uom,
        })
    legacy_rows = frappe.get_all(
        "Fresko Deal",
        filters={"container": container},
        fields=["dispatched_qty"],
    )
    legacy_dispatched = sum(flt(row.dispatched_qty) for row in legacy_rows)
    assertions = frappe.get_all(
        "Fresko Field Assertion",
        filters={"outward": ("in", visible_outward_names or [""])},
        fields=[
            "name",
            "outward",
            "outward_line_key",
            "asserted_field",
            "assertion_basis",
            "raw_value",
            "rate",
            "currency",
            "rate_uom",
            "evidence",
            "effective_at",
            "status",
            "supersedes",
            "superseded_by",
            "assertion_key",
            "payload_sha256",
            "prepared_by",
            "prepared_at",
            "asserted_by",
            "asserted_at",
            "reviewed_by",
            "reviewed_at",
            "activated_by",
            "activated_at",
            "creation",
            "modified",
        ],
        order_by="effective_at asc, creation asc",
    )
    exceptions = frappe.get_all(
        "Fresko Exception",
        filters={"container": container},
        fields=[
            "name",
            "exception_type",
            "severity",
            "status",
            "deal",
            "outward",
            "description",
            "resolution_notes",
            "opened_by",
            "opened_at",
            "resolved_by",
            "resolved_at",
            "creation",
            "modified",
        ],
        order_by="creation asc",
    )
    exceptions = [
        row
        for row in exceptions
        if (
            (row.outward and row.outward in visible_outward_names)
            or (
                not row.outward
                and (
                    not row.deal
                    or deal_has_permission(
                        row.deal, "read", user=frappe.session.user
                    )
                )
            )
        )
    ]
    response = {
        "snapshot_context": {
            "snapshot_version": "fresko-container-live:v1",
            "mode": "LIVE_OPERATIONAL",
            "as_of": snapshot_as_of,
            "reporting_timezone": get_system_timezone(),
            "reporting_period": {
                "basis": "LEDGER_STATE_VISIBLE_TO_TRANSACTION",
                "start": None,
                "end": snapshot_as_of,
            },
            "is_frozen": False,
            "is_reconciliation_snapshot": False,
            "is_ca_ready": False,
            "included_record_ids": {
                "outwards": visible_outward_names,
                "assertions": [row.name for row in assertions],
                "exceptions": [row.name for row in exceptions],
            },
        },
        "container": doc.name,
        "container_no": doc.container_no,
        "status": doc.status,
        "inward_qty": flt(doc.inward_qty),
        "uom": doc.uom,
        "lots": lots_out,
        "approved_sold_total": sum(l["approved_sold"] for l in lots_out),
        "available_to_sell_total": sum(l["available_to_sell"] for l in lots_out),
        "physical": physical_view,
        "commercial": {
            "approved_sold_total": sum(l["approved_sold"] for l in lots_out),
            "available_to_sell_total": sum(l["available_to_sell"] for l in lots_out),
            "legacy_deal_dispatched_qty": legacy_dispatched,
            "legacy_dispatch_is_physical_ledger": False,
        },
        "assertions": assertions,
        "exceptions": exceptions,
        "provenance": {
            "outward_evidence": sorted(
                {
                    row.source_evidence
                    for row in visible_movements
                    if row.source_evidence
                }
            ),
            "assertion_evidence": sorted(
                {row.evidence for row in assertions if row.evidence}
            ),
        },
    }
    return response
