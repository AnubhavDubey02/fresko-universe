"""D5 rate-floor hierarchy: Lot override → Container+Count/Size → Container default.

Gate 1 (Anubhav merge gate): empty / unresolved band must NOT auto-approve.
When no applicable floor or ceiling is resolved, callers must route to
Approval Required + RATE_POLICY_MISSING (see deals.apply_rate_rules).
"""

from __future__ import annotations

from frappe.utils import flt


def _optional_rate(val):
    """Normalize optional Currency/Float rate-policy values.

    Frappe Currency fields on DocTypes/child tables commonly materialize empty
    values as 0.0 after insert/reload (MariaDB DECIMAL / Document casting).
    Phase 1 rate floors/ceilings are never meaningfully zero for produce, so
    treat None / '' / 0 as unset so hierarchy can fall through and Gate 1
    fail-closed (both unset → unresolved) works under real bench.
    """
    if val is None or val == "":
        return None
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    if num == 0:
        return None
    return flt(num)


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
        floor = _optional_rate(lot_row.get("rate_floor_override"))
        ceiling = _optional_rate(lot_row.get("rate_ceiling_override"))
        if floor is not None or ceiling is not None:
            return floor, ceiling
        if not count_size:
            count_size = lot_row.get("count_size")

    cs = (count_size or "").strip()
    if cs:
        for rule in container_doc.get("rate_rules") or []:
            if (rule.get("count_size") or "").strip() == cs:
                floor = _optional_rate(rule.get("rate_floor"))
                ceiling = _optional_rate(rule.get("rate_ceiling"))
                return floor, ceiling

    floor = _optional_rate(container_doc.get("default_rate_floor"))
    ceiling = _optional_rate(container_doc.get("default_rate_ceiling"))
    return floor, ceiling


def policy_resolved(floor, ceiling) -> bool:
    """Gate 1: at least one bound must exist for a resolvable policy band.

    Currency-coerced 0 / 0.0 counts as unset (same as None).
    """
    return _optional_rate(floor) is not None or _optional_rate(ceiling) is not None


# Alias used in docs / older drafts
is_rate_band_resolved = policy_resolved


def rate_in_band(proposed_rate, floor, ceiling) -> bool:
    """True when proposed_rate is within resolved bounds.

    Empty band (both None/0) is NOT in-band (Gate 1 / F-M7). Callers should
    prefer policy_resolved + RATE_POLICY_MISSING before auto-approve.
    """
    floor = _optional_rate(floor)
    ceiling = _optional_rate(ceiling)
    if not policy_resolved(floor, ceiling):
        return False
    rate = flt(proposed_rate)
    if floor is not None and rate < flt(floor):
        return False
    if ceiling is not None and rate > flt(ceiling):
        return False
    return True
