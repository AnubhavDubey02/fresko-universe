"""D5 rate-floor hierarchy: Lot override → Container+Count/Size → Container default.

Gate 1 (Anubhav merge gate): empty / unresolved band must NOT auto-approve.
When no applicable floor or ceiling is resolved, callers must route to
Approval Required + RATE_POLICY_MISSING (see deals.apply_rate_rules).
"""

from __future__ import annotations

from frappe.utils import flt


def resolve_rate_band(container_doc, lot_no: str | None, count_size: str | None = None) -> tuple[float | None, float | None]:
    """
    Returns (floor, ceiling).
    Hierarchy (D5):
      1. Lot override (rate_floor_override / rate_ceiling_override on matching lot)
      2. Container rate rule matching count_size (product = container.item implicit)
      3. Container default_rate_floor / default_rate_ceiling
    No buyer-specific floor in V1.

    Both None means no applicable policy resolved (Gate 1 → not auto-approve).
    """
    floor = None
    ceiling = None

    lot_row = None
    if lot_no:
        for row in container_doc.get("lots") or []:
            if row.lot_no == lot_no:
                lot_row = row
                break

    if lot_row:
        if lot_row.get("rate_floor_override") is not None:
            floor = flt(lot_row.rate_floor_override)
        if lot_row.get("rate_ceiling_override") is not None:
            ceiling = flt(lot_row.rate_ceiling_override)
        if floor is not None or ceiling is not None:
            return floor, ceiling
        if not count_size:
            count_size = lot_row.get("count_size")

    cs = (count_size or "").strip()
    if cs:
        for rule in container_doc.get("rate_rules") or []:
            if (rule.get("count_size") or "").strip() == cs:
                if rule.get("rate_floor") is not None:
                    floor = flt(rule.rate_floor)
                if rule.get("rate_ceiling") is not None:
                    ceiling = flt(rule.rate_ceiling)
                return floor, ceiling

    if container_doc.get("default_rate_floor") is not None:
        floor = flt(container_doc.default_rate_floor)
    if container_doc.get("default_rate_ceiling") is not None:
        ceiling = flt(container_doc.default_rate_ceiling)
    return floor, ceiling


def policy_resolved(floor, ceiling) -> bool:
    """Gate 1: at least one bound must exist for a resolvable policy band."""
    return floor is not None or ceiling is not None


# Alias used in docs / older drafts
is_rate_band_resolved = policy_resolved


def rate_in_band(proposed_rate, floor, ceiling) -> bool:
    """True when proposed_rate is within resolved bounds.

    Empty band (both None) is NOT in-band (Gate 1 / F-M7). Callers should
    prefer policy_resolved + RATE_POLICY_MISSING before auto-approve.
    """
    if not policy_resolved(floor, ceiling):
        return False
    rate = flt(proposed_rate)
    if floor is not None and rate < flt(floor):
        return False
    if ceiling is not None and rate > flt(ceiling):
        return False
    return True
