"""Locked Phase 1 constants — do not drift from PHASE1_BLUEPRINT_FINAL.md."""

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

# D4: Countered → Approved only via accept_counter (not Outward Pending).
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

# Statuses that reduce ATS (D3). PROPOSED / APPROVAL_REQUIRED do NOT.
ATS_ACTIVE_STATUSES = {
    "Auto Approved",
    "Approved",
    # Countered intentionally excluded (D3 literal); accept_counter re-reads ATS under lock
    "Outward Pending",
    "Dispatched",
    "Partially Dispatched",
    "Payment Pending",
    "Paid",
    "Partially Paid",
    "Reconciled",
    "Disputed",
}

COMMERCIAL_LOCK_STATUSES = {
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

LOCKED_COMMERCIAL_FIELDS = {
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
}

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

MATERIAL_EXCEPTION_TYPES = {
    "BUYER_UNRESOLVED",
    "DUPLICATE_MESSAGE",
    "OVERSELL_OVERRIDE",
    "STOCK_SHORTFALL",
    "RATE_FLOOR_BREACH",
    "DATA_INTEGRITY",
}

OVERSELL_OVERRIDE_ROLES = {"System Manager"}  # D10 Owner/Admin only; Approver insufficient alone
