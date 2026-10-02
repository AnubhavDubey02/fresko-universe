# Copyright (c) 2026, Anubhav Dubey and contributors
import frappe


def execute():
    """Set durability_state = 'UNKNOWN' on attempt rows written before the field existed.

    Legacy attempt rows carry no record of how they were persisted, so UNKNOWN is
    the only truthful value: it asserts neither an independent commit nor
    caller-transaction binding. This deliberately does NOT infer durability from
    any other column — migration is not evidence.

    Idempotent: only NULL/empty values are touched, so reruns are no-ops.
    """
    if not frappe.db.has_column("Fresko Evidence Attempt", "durability_state"):
        return

    frappe.db.sql(
        """
        UPDATE `tabFresko Evidence Attempt`
        SET durability_state = 'UNKNOWN'
        WHERE durability_state IS NULL OR durability_state = ''
        """
    )
