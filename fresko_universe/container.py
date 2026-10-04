"""Container snapshot API — fresko_universe.container.snapshot."""

from __future__ import annotations

import frappe

from fresko_universe.fresko_core.doctype.fresko_container.fresko_container import (
    container_snapshot,
)
from fresko_universe.permissions import assert_can_read_ats_snapshot


@frappe.whitelist()
def snapshot(container: str, lot_no: str | None = None):
    """Separated physical/commercial/assertion/exception snapshot for Fresko readers."""
    assert_can_read_ats_snapshot()
    return container_snapshot(container, lot_no)
