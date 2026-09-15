"""Available-To-Sell (soft commercial reservation) — Phase 1.

D3: PROPOSED / APPROVAL_REQUIRED / COUNTERED do not reduce ATS.
APPROVED / AUTO_APPROVED (and successor commercial statuses) do.
Never posts Stock Ledger Entry.
"""

from __future__ import annotations

from typing import Optional

import frappe
from frappe.utils import flt

from fresko_universe.constants import ATS_REDUCING_STATUSES


def available_to_sell(
    container: str,
    lot_no: str,
    *,
    exclude_deal: Optional[str] = None,
    for_update: bool = False,
) -> float:
    if for_update:
        frappe.db.sql(
            "SELECT name FROM `tabFresko Container` WHERE name=%s FOR UPDATE",
            (container,),
        )

    lot_inward = _lot_inward_qty(container, lot_no)
    reserved = _reserved_qty(container, lot_no, exclude_deal=exclude_deal)
    return flt(lot_inward) - flt(reserved)


def _lot_inward_qty(container: str, lot_no: str) -> float:
    row = frappe.db.sql(
        """
        SELECT inward_qty
        FROM `tabFresko Container Lot`
        WHERE parent=%s AND parenttype='Fresko Container' AND lot_no=%s
        LIMIT 1
        """,
        (container, lot_no),
        as_dict=True,
    )
    if not row:
        frappe.throw(
            f"Lot '{lot_no}' not found on container {container}",
            title="Lot Not On Container",
        )
    return flt(row[0].inward_qty)


def _reserved_qty(container: str, lot_no: str, *, exclude_deal: Optional[str] = None) -> float:
    statuses = tuple(ATS_REDUCING_STATUSES)
    params: list = [container, lot_no, statuses]
    exclude_clause = ""
    if exclude_deal:
        exclude_clause = " AND name != %s"
        params.append(exclude_deal)

    rows = frappe.db.sql(
        f"""
        SELECT name, status, qty, COALESCE(dispatched_qty, 0) AS dispatched_qty
        FROM `tabFresko Deal`
        WHERE container=%s
          AND lot_no=%s
          AND status IN %s
          {exclude_clause}
        """,
        tuple(params),
        as_dict=True,
    )
    total = 0.0
    for r in rows:
        qty = flt(r.qty)
        if r.status == "Partially Dispatched":
            total += max(qty - flt(r.dispatched_qty), 0.0)
        else:
            total += qty
    return total


def assert_ats_allows(
    container: str,
    lot_no: str,
    qty: float,
    *,
    exclude_deal: Optional[str] = None,
    allow_oversell: bool = False,
) -> float:
    ats = available_to_sell(
        container, lot_no, exclude_deal=exclude_deal, for_update=True
    )
    if flt(qty) > flt(ats) and not allow_oversell:
        frappe.throw(
            f"Insufficient available-to-sell for lot {lot_no}: need {qty}, ATS={ats}",
            title="ATS Shortfall",
        )
    return ats


def commercial_qty_for_ats(deal) -> float:
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


def approved_sold(container: str, lot_no: str | None = None) -> float:
    filters = {"container": container, "status": ("in", list(ATS_REDUCING_STATUSES))}
    if lot_no:
        filters["lot_no"] = lot_no
    deals = frappe.get_all(
        "Fresko Deal", filters=filters, fields=["qty", "status", "dispatched_qty"]
    )
    return sum(commercial_qty_for_ats(d) for d in deals)
