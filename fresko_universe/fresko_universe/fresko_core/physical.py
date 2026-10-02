"""Read and validate the Phase 2A physical Outward ledger.

This module is intentionally separate from ``fresko_core.ats``. ATS models
commercial commitments; the functions here read only posted physical Outwards
and their compensating reversals.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe.utils import flt


def posted_physical_quantities(
    container: str, *, for_update: bool = False
) -> tuple[dict[str, float], float]:
    """Return net posted quantity by mapped lot and in the unmapped bucket."""
    lock_clause = " FOR UPDATE" if for_update else ""
    rows = frappe.db.sql(
        f"""
        SELECT o.name AS outward, o.movement_type, l.line_key, l.lot_no, l.qty, l.uom
        FROM `tabFresko Outward` o
        INNER JOIN `tabFresko Outward Line` l
          ON l.parent=o.name
         AND l.parenttype='Fresko Outward'
         AND l.parentfield='lines'
        WHERE o.container=%s AND o.status='Posted'
        ORDER BY o.creation, o.name, l.idx{lock_clause}
        """,
        (container,),
        as_dict=True,
    )

    by_lot: dict[str, float] = defaultdict(float)
    unmapped = 0.0
    for row in rows:
        sign = -1.0 if row.movement_type == "REVERSAL" else 1.0
        quantity = sign * flt(row.qty)
        if row.lot_no:
            by_lot[row.lot_no] += quantity
        else:
            unmapped += quantity
    return dict(by_lot), unmapped


def assert_mapped_lot_capacity(
    container: str, lot_no: str, additional_qty: float, uom: str
) -> float:
    """Fail closed when a new posted physical movement would overdraw a mapped lot.

    The caller must acquire the Container lock first. ``for_update=True`` then
    forces current reads, avoiding reuse of a pre-lock REPEATABLE READ snapshot.
    """
    lot_rows = frappe.db.sql(
        """
        SELECT inward_qty, uom
        FROM `tabFresko Container Lot`
        WHERE parent=%s
          AND parenttype='Fresko Container'
          AND parentfield='lots'
          AND lot_no=%s
        LIMIT 1 FOR UPDATE
        """,
        (container, lot_no),
        as_dict=True,
    )
    if not lot_rows:
        frappe.throw(
            f"Lot '{lot_no}' is not an authorized mapped lot on container {container}",
            title="Lot Not On Container",
        )
    lot_uom = str(lot_rows[0].uom or "")
    if str(uom or "") != lot_uom:
        frappe.throw(
            f"Physical Outward UOM {uom!r} does not match mapped lot "
            f"{lot_no} UOM {lot_uom!r}",
            title="Physical UOM Mismatch",
        )

    posted_by_lot, _unmapped = posted_physical_quantities(
        container, for_update=True
    )
    inward = flt(lot_rows[0].inward_qty)
    already_posted = flt(posted_by_lot.get(lot_no))
    remaining = inward - already_posted
    if flt(additional_qty) > remaining + 1e-9:
        frappe.throw(
            f"Physical Outward would overdraw lot {lot_no}: "
            f"need {additional_qty}, remaining physical quantity is {remaining}",
            title="Physical Lot Overdrawn",
        )
    return remaining


def assert_container_capacity(
    container: str, additional_qty: float, uoms: set[str]
) -> float:
    """Protect total inward stock, including source-backed unmapped movements."""
    rows = frappe.db.sql(
        """
        SELECT inward_qty, uom
        FROM `tabFresko Container`
        WHERE name=%s
        LIMIT 1 FOR UPDATE
        """,
        (container,),
        as_dict=True,
    )
    if not rows:
        frappe.throw(f"Fresko Container {container} does not exist")
    container_uom = str(rows[0].uom or "")
    mismatched = sorted(str(uom) for uom in uoms if str(uom) != container_uom)
    if mismatched:
        frappe.throw(
            f"Physical Outward UOM(s) {', '.join(mismatched)} do not match "
            f"container UOM {container_uom!r}",
            title="Physical UOM Mismatch",
        )

    posted_by_lot, unmapped = posted_physical_quantities(
        container, for_update=True
    )
    already_posted = sum(posted_by_lot.values()) + unmapped
    remaining = flt(rows[0].inward_qty) - flt(already_posted)
    if flt(additional_qty) > remaining + 1e-9:
        frappe.throw(
            f"Physical Outward would overdraw container {container}: "
            f"need {additional_qty}, remaining physical quantity is {remaining}",
            title="Physical Container Overdrawn",
        )
    return remaining


def physical_snapshot(container: str) -> dict:
    """Return additive physical truth without reading Deal.dispatched_qty."""
    by_lot, unmapped = posted_physical_quantities(container)
    movements = frappe.get_all(
        "Fresko Outward",
        filters={"container": container, "status": "Posted"},
        fields=[
            "name",
            "movement_type",
            "movement_at",
            "deal",
            "reverses_outward",
            "source_evidence",
            "source_event_id",
            "source_event_key",
            "payload_sha256",
            "prepared_by",
            "prepared_at",
            "posted_by",
            "posted_at",
            "creation",
            "modified",
        ],
        order_by="movement_at asc, creation asc",
    )
    movement_names = [row.name for row in movements]
    line_provenance = frappe.get_all(
        "Fresko Outward Line",
        filters={"parent": ("in", movement_names or [""])},
        fields=[
            "parent as outward",
            "idx",
            "line_key",
            "source_line_ref",
            "raw_lot_text",
            "lot_no",
            "batch",
            "qty",
            "uom",
            "raw_qty_text",
            "raw_uom_text",
            "raw_rate_text",
        ],
        order_by="parent asc, idx asc",
    )
    return {
        "posted_by_lot": by_lot,
        "unmapped_physical_qty": unmapped,
        "posted_physical_total": sum(by_lot.values()) + unmapped,
        "movements": movements,
        "line_provenance": line_provenance,
    }
