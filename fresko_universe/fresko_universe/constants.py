"""Locked Phase 1 constants — do not drift from PHASE1_BLUEPRINT_FINAL.md."""

from __future__ import annotations

DEAL_STATUSES = [
    "Proposed",
    "Auto Approved",
    "Approval Required",
    "Approved",
    "Countered",
    "Rejected",
    "Outward Pending",
    "Dispatched",
    "Partially Dispatched",
    "Payment Pending",
    "Paid",
    "Partially Paid",
    "Reconciled",
    "Cancelled",
    "Disputed",
]

# D4: Countered → Approved only via accept_counter
DEAL_TRANSITIONS = {
    "Proposed": {"Auto Approved", "Approval Required", "Cancelled"},
    "Approval Required": {"Approved", "Countered", "Rejected", "Cancelled"},
    "Auto Approved": {"Outward Pending", "Cancelled", "Disputed"},
    "Approved": {"Outward Pending", "Cancelled", "Disputed"},
    "Countered": {"Approved", "Cancelled"},
    "Rejected": {"Cancelled"},
    "Outward Pending": {"Dispatched", "Partially Dispatched", "Cancelled", "Disputed"},
    "Dispatched": {"Payment Pending", "Disputed"},
    "Partially Dispatched": {"Dispatched", "Payment Pending", "Cancelled", "Disputed"},
    "Payment Pending": {"Paid", "Partially Paid", "Disputed", "Cancelled"},
    "Paid": {"Reconciled", "Disputed"},
    "Partially Paid": {"Paid", "Reconciled", "Disputed"},
    "Reconciled": set(),
    "Cancelled": set(),
    "Disputed": {"Outward Pending", "Payment Pending", "Cancelled"},
}

# D3: PROPOSED / Approval Required / Countered do NOT reduce ATS
ATS_ACTIVE_STATUSES = frozenset(
    {
        "Auto Approved",
        "Approved",
        "Outward Pending",
        "Dispatched",
        "Partially Dispatched",
        "Payment Pending",
        "Paid",
        "Partially Paid",
        "Reconciled",
        "Disputed",
        "Cancelled",  # reserves dispatched_qty only via commercial_qty_for_ats
    }
)
ATS_REDUCING_STATUSES = ATS_ACTIVE_STATUSES

COMMERCIAL_LOCK_STATUSES = frozenset(
    {
        "Approval Required",  # F-H4: freeze qty/lot/container after apply_rate_rules
        "Auto Approved",
        "Approved",
        "Countered",
        "Outward Pending",
        "Dispatched",
        "Partially Dispatched",
        "Payment Pending",
        "Paid",
        "Partially Paid",
        "Reconciled",
    }
)

LOCKED_COMMERCIAL_FIELDS = frozenset(
    {
        "container",
        "buyer_alias",
        "item",
        "lot_no",
        "container_lot",
        "qty",
        "proposed_rate",
        "uom",
        "company",
        "approved_rate",
        "customer",
        "count_size",
    }
)

CONTAINER_STATUS_TRANSITIONS = {
    "Draft": {"Expected", "Arrived", "Cancelled"},
    "Expected": {"Arrived", "Cancelled"},
    "Arrived": {"In Cold Storage", "Selling", "Cancelled"},
    "In Cold Storage": {"Selling", "Closing", "Cancelled"},
    "Selling": {"Closing", "Cancelled"},
    "Closing": {"Closed", "Selling"},
    "Closed": set(),
    "Cancelled": set(),
}

EXCEPTION_TYPES = frozenset(
    {
        "BUYER_UNRESOLVED",
        "DUPLICATE_MESSAGE",
        "OVERSELL_OVERRIDE",
        "STOCK_SHORTFALL",
        "RATE_FLOOR_BREACH",
        "RATE_POLICY_MISSING",
        "DATA_INTEGRITY",
        "OTHER",
    }
)

MATERIAL_EXCEPTION_TYPES = frozenset(
    {
        "BUYER_UNRESOLVED",
        "DUPLICATE_MESSAGE",
        "OVERSELL_OVERRIDE",
        "STOCK_SHORTFALL",
        "RATE_FLOOR_BREACH",
        "RATE_POLICY_MISSING",
        "DATA_INTEGRITY",
        "OTHER",
    }
)

EXCEPTION_OPEN_STATUSES = frozenset({"Open", "In Progress"})
OVERSELL_OVERRIDE_ROLES = frozenset({"System Manager"})  # D10 / DV4: Approver cannot oversell

# Post-approval commercial revisions require Approval + evidence (Controls B2)
MATERIAL_REVISION_FIELDS = frozenset(
    {
        "approved_rate",
        "qty",
        "lot_no",
        "container_lot",
        "customer",
    }
)

# Cancelled still reduces ATS by already-dispatched qty (QA: cancel-after-partial)
ATS_CANCEL_KEEPS_DISPATCHED = True
