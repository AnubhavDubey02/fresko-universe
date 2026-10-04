"""Available-To-Sell (soft commercial reservation) — Phase 1.

D3: PROPOSED / APPROVAL_REQUIRED / COUNTERED do not reduce ATS.
APPROVED / AUTO_APPROVED (and successor commercial statuses) do.
Cancelled reserves already-dispatched qty only (QA cancel-after-partial).
Never posts Stock Ledger Entry.
"""

from __future__ import annotations

from typing import Optional

import frappe
from frappe.utils import flt

from fresko_universe.constants import ATS_REDUCING_STATUSES


def lock_container_for_update(container: str) -> None:
    """Serialize stock-sensitive mutations on one stable container row."""
    frappe.db.sql(
        "SELECT name FROM `tabFresko Container` WHERE name=%s FOR UPDATE",
        (container,),
    )


def available_to_sell(
    container: str,
    lot_no: str,
    *,
    exclude_deal: Optional[str] = None,
    for_update: bool = False,
) -> float:
    if for_update:
        lock_container_for_update(container)

    # Under InnoDB REPEATABLE READ, the caller may already have established a
    # snapshot while probing the Deal before it waited for the container lock.
    # Propagate current-read semantics so a waiter sees reservations committed
    # by the transaction that held the container lock before it.
    lot_inward, lot_uom = _lot_inward(container, lot_no, for_update=for_update)
    reserved = _reserved_qty(
        container,
        lot_no,
        exclude_deal=exclude_deal,
        for_update=for_update,
    )
    lot_available = flt(lot_inward) - flt(reserved)

    # A Container Quantity Assertion is container-wide, not lot-specific.  Do
    # not invent a pro-rata shortage allocation between lots.  Instead, cap
    # every lot's ATS by the remaining container-wide capacity after all
    # commercial reservations.  This makes the aggregate sellable quantity the
    # lower of legacy inward and the active same-UOM OPERATING_INWARD fact.
    container_capacity = _container_operating_capacity(
        container, lot_uom, for_update=for_update
    )
    container_reserved = _reserved_qty(
        container,
        None,
        exclude_deal=exclude_deal,
        for_update=for_update,
    )
    container_available = flt(container_capacity) - flt(container_reserved)
    return min(lot_available, container_available)


def _lot_inward_qty(container: str, lot_no: str, *, for_update: bool = False) -> float:
    return _lot_inward(container, lot_no, for_update=for_update)[0]


def _lot_inward(
    container: str, lot_no: str, *, for_update: bool = False
) -> tuple[float, str]:
    lock_clause = " FOR UPDATE" if for_update else ""
    row = frappe.db.sql(
        f"""
        SELECT inward_qty, uom
        FROM `tabFresko Container Lot`
        WHERE parent=%s AND parenttype='Fresko Container' AND lot_no=%s
        LIMIT 1{lock_clause}
        """,
        (container, lot_no),
        as_dict=True,
    )
    if not row:
        frappe.throw(
            f"Lot '{lot_no}' not found on container {container}",
            title="Lot Not On Container",
        )
    return flt(row[0].inward_qty), row[0].uom


def _container_operating_capacity(
    container: str, uom: str, *, for_update: bool = False
) -> float:
    """Return the lower of legacy inward and active same-UOM operating truth.

    An active operating assertion in another UOM is explicit evidence that
    cannot be converted implicitly.  Fail closed instead of falling back to a
    legacy scalar in that situation.
    """
    lock_clause = " FOR UPDATE" if for_update else ""
    container_rows = frappe.db.sql(
        f"""
        SELECT inward_qty, uom
        FROM `tabFresko Container`
        WHERE name=%s
        LIMIT 1{lock_clause}
        """,
        (container,),
        as_dict=True,
    )
    if not container_rows:
        frappe.throw(f"Container {container} does not exist")
    legacy = container_rows[0]
    if legacy.uom != uom:
        frappe.throw(
            f"Container {container} lot UOM {uom} does not match legacy inward UOM {legacy.uom}",
            title="ATS UOM Mismatch",
        )

    assertions = frappe.db.sql(
        f"""
        SELECT name, quantity, uom
        FROM `tabFresko Container Quantity Assertion`
        WHERE container=%s AND basis='OPERATING_INWARD' AND status='Active'
        ORDER BY activated_at DESC, creation DESC, name DESC{lock_clause}
        """,
        (container,),
        as_dict=True,
    )
    same_uom = next((row for row in assertions if row.uom == uom), None)
    if same_uom is None:
        if assertions:
            frappe.throw(
                f"ATS is unresolved for container {container}: active operating inward uses another or unknown UOM",
                title="ATS Operating Quantity Unresolved",
            )
        return flt(legacy.inward_qty)
    if same_uom.quantity in (None, ""):
        frappe.throw(
            f"ATS is unresolved for container {container}: active operating inward quantity is unknown",
            title="ATS Operating Quantity Unresolved",
        )
    return min(flt(legacy.inward_qty), flt(same_uom.quantity))


def _reserved_qty(
    container: str,
    lot_no: str | None,
    *,
    exclude_deal: Optional[str] = None,
    for_update: bool = False,
) -> float:
    statuses = tuple(ATS_REDUCING_STATUSES)
    params: list = [container, statuses]
    lot_clause = ""
    if lot_no is not None:
        lot_clause = " AND lot_no=%s"
        params.insert(1, lot_no)
    exclude_clause = ""
    if exclude_deal:
        exclude_clause = " AND name != %s"
        params.append(exclude_deal)
    lock_clause = " FOR UPDATE" if for_update else ""

    rows = frappe.db.sql(
        f"""
        SELECT name, status, qty, COALESCE(dispatched_qty, 0) AS dispatched_qty
        FROM `tabFresko Deal`
        WHERE container=%s
          {lot_clause}
          AND status IN %s
          {exclude_clause}
        {lock_clause}
        """,
        tuple(params),
        as_dict=True,
    )
    total = 0.0
    for r in rows:
        total += commercial_qty_for_ats(r)
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
        # QA: cancel after partial must not free already-dispatched qty
        return max(dispatched, 0.0)
    return qty


def approved_sold(container: str, lot_no: str | None = None) -> float:
    filters = {"container": container, "status": ("in", list(ATS_REDUCING_STATUSES))}
    if lot_no:
        filters["lot_no"] = lot_no
    deals = frappe.get_all(
        "Fresko Deal", filters=filters, fields=["qty", "status", "dispatched_qty"]
    )
    return sum(commercial_qty_for_ats(d) for d in deals)
