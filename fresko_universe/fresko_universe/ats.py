"""Available-to-sell computation (blueprint §F + D3)."""

from __future__ import annotations

import frappe
from frappe.utils import flt

from fresko_universe.constants import ATS_ACTIVE_STATUSES


def commercial_qty_for_ats(deal) -> float:
    """Qty still counting against ATS for a deal row."""
    status = deal.status if hasattr(deal, "status") else deal.get("status")
    qty = flt(deal.qty if hasattr(deal, "qty") else deal.get("qty"))
    dispatched = flt(
        deal.dispatched_qty if hasattr(deal, "dispatched_qty") else deal.get("dispatched_qty")
    )
    if status == "Partially Dispatched":
        return max(qty - dispatched, 0.0)
    if status == "Cancelled":
        return 0.0
    return qty


def available_to_sell(container: str, lot_no: str, exclude_deal: str | None = None, for_update: bool = False) -> float:
    """
    ATS(lot) = lot.inward_qty - SUM(commercial qty of active deals on lot).
    PROPOSED / Approval Required do not reduce ATS (D3).
    When for_update=True, lock the parent Container row (transactional guard).
    """
    if for_update:
        # Row-lock container document for concurrency (D3 / blueprint §F.6)
        frappe.db.sql(
            "SELECT name FROM `tabFresko Container` WHERE name=%s FOR UPDATE",
            (container,),
        )

    lot_inward = _lot_inward_qty(container, lot_no)
    reserved = 0.0
    filters = {
        "container": container,
        "lot_no": lot_no,
        "status": ("in", list(ATS_ACTIVE_STATUSES)),
        "docstatus": ("<", 2),
    }
    deals = frappe.get_all(
        "Fresko Deal",
        filters=filters,
        fields=["name", "qty", "status", "dispatched_qty"],
    )
    for d in deals:
        if exclude_deal and d.name == exclude_deal:
            continue
        reserved += commercial_qty_for_ats(d)
    return flt(lot_inward) - flt(reserved)


def _lot_inward_qty(container: str, lot_no: str) -> float:
    lots = frappe.get_all(
        "Fresko Container Lot",
        filters={"parent": container, "parenttype": "Fresko Container", "lot_no": lot_no},
        fields=["inward_qty", "name"],
        limit=1,
    )
    if not lots:
        frappe.throw(f"Lot {lot_no!r} not found on container {container}")
    return flt(lots[0].inward_qty)


def approved_sold(container: str, lot_no: str | None = None) -> float:
    filters = {
        "container": container,
        "status": ("in", list(ATS_ACTIVE_STATUSES)),
    }
    if lot_no:
        filters["lot_no"] = lot_no
    deals = frappe.get_all(
        "Fresko Deal",
        filters=filters,
        fields=["qty", "status", "dispatched_qty"],
    )
    return sum(commercial_qty_for_ats(d) for d in deals)
