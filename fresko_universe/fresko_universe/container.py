"""Container snapshot API — fresko_universe.container.snapshot."""

from __future__ import annotations

import frappe
from frappe.utils import flt

from fresko_universe.ats import approved_sold, available_to_sell


@frappe.whitelist()
def snapshot(container: str, lot_no: str | None = None):
    """Return inward / approved_sold / ATS for container (optionally one lot)."""
    doc = frappe.get_doc("Fresko Container", container)
    lots_out = []
    for row in doc.get("lots") or []:
        if lot_no and row.lot_no != lot_no:
            continue
        sold = approved_sold(container, row.lot_no)
        ats = available_to_sell(container, row.lot_no)
        lots_out.append(
            {
                "lot_no": row.lot_no,
                "inward_qty": flt(row.inward_qty),
                "approved_sold": flt(sold),
                "available_to_sell": flt(ats),
                "count_size": row.count_size,
                "uom": row.uom,
            }
        )
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
