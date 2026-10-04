"""Pure policy definitions for close exception materiality and pilot safety gates.

This module contains no Frappe or database dependencies and provides deterministic,
policy-level classification of exception types and severities.
"""

from typing import Mapping

# Canonical classification mapping for every FreskoException exception_type enum
CLOSE_EXCEPTION_POLICY: Mapping[str, str] = {
    # Classification: "always" material (blocking close regardless of severity)
    "BUYER_UNRESOLVED": "always",
    "DUPLICATE_MESSAGE": "always",
    "OVERSELL_OVERRIDE": "always",
    "STOCK_SHORTFALL": "always",
    "RATE_FLOOR_BREACH": "always",
    "RATE_POLICY_MISSING": "always",
    "OUTWARD_UNPRICED": "always",
    "OUTWARD_WITHOUT_DEAL": "always",
    "LOT_UNRESOLVED": "always",
    "DUPLICATE_GATEPASS": "always",
    "PHYSICAL_VARIANCE": "always",
    "DATA_INTEGRITY": "always",
    "ALIAS_UNRESOLVED": "always",
    "ALIAS_CONFLICT": "always",
    "RATE_UNKNOWN": "always",
    "RATE_EVIDENCE_MISSING": "always",
    "PRICE_BUCKET_UNALLOCATED": "always",
    "LOT_UNKNOWN": "always",
    "PARTY_UNKNOWN": "always",
    "MOVEMENT_TIME_UNKNOWN": "always",
    "SALE_WITHOUT_OUTWARD": "always",
    "OUTWARD_WITHOUT_SALE": "always",
    "ALLOCATION_OVERDRAW": "always",
    # Classification: "severity" dependent (material if severity is Material or Critical)
    "OTHER": "severity",
    "IDEMPOTENCY_PAYLOAD_CONFLICT": "severity",
    "CONCURRENT_STATE_CONFLICT": "severity",
    # Classification: "attributed_money" (treated as material for monetary close gate)
    "MONEY_UNALLOCATED": "attributed_money",
    "BANK_PENDING": "attributed_money",
    "RECEIPT_AMOUNT_UNKNOWN": "attributed_money",
    "RECEIPT_DIRECTION_UNKNOWN": "attributed_money",
}

ALWAYS_MATERIAL_EXCEPTION_TYPES: frozenset[str] = frozenset(
    k for k, v in CLOSE_EXCEPTION_POLICY.items() if v == "always"
)

MONEY_EXCEPTION_TYPES: frozenset[str] = frozenset(
    k for k, v in CLOSE_EXCEPTION_POLICY.items() if v == "attributed_money"
)

MATERIAL_EXCEPTION_TYPES: frozenset[str] = (
    ALWAYS_MATERIAL_EXCEPTION_TYPES | MONEY_EXCEPTION_TYPES
)

MATERIAL_EXCEPTION_SEVERITIES: frozenset[str] = frozenset({"Material", "Critical"})

EXCEPTION_OPEN_STATUSES: frozenset[str] = frozenset({"Open", "In Progress"})


def exception_is_material(kind: str, severity: str) -> bool:
    """Determine whether an exception is material based on type and severity.

    Returns True if the exception kind is intrinsically material (always or attributed_money),
    or if its severity is Material or Critical (including for unknown or future kinds).
    Non-material kinds with Info, Low, Medium, or High severity do not block.
    """
    if kind in MATERIAL_EXCEPTION_TYPES:
        return True
    return severity in MATERIAL_EXCEPTION_SEVERITIES
