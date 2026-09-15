"""Test helpers for fresko_universe (require ERPNext/Frappe site)."""

from __future__ import annotations

import frappe
from frappe.utils import nowdate


def ensure_masters():
    """Create minimal Company/Item/UOM/Currency/Supplier if missing (test site)."""
    if not frappe.db.exists("Currency", "INR"):
        # ERPNext fixtures usually provide INR; skip create if DocType locked
        pass
    company = frappe.db.get_single_value("Global Defaults", "default_company") if frappe.db.exists("DocType", "Global Defaults") else None
    if not company:
        companies = frappe.get_all("Company", limit=1)
        company = companies[0].name if companies else None
    if not company:
        frappe.throw("No Company found — configure ERPNext site before running integration tests")

    uom = frappe.db.get_value("UOM", {"uom_name": "Kg"}, "name") or frappe.db.get_value("UOM", {}, "name")
    item = frappe.db.get_value("Item", {"disabled": 0}, "name")
    supplier = frappe.db.get_value("Supplier", {}, "name")
    currency = frappe.db.get_value("Company", company, "default_currency") or "INR"
    return {
        "company": company,
        "uom": uom,
        "item": item,
        "supplier": supplier,
        "currency": currency,
    }


def make_container(masters=None, lot_no="LOT-A", inward_qty=100, rate_floor=100, **kwargs):
    masters = masters or ensure_masters()
    doc = frappe.get_doc(
        {
            "doctype": "Fresko Container",
            "naming_series": "CON-.YYYY.-.",
            "company": masters["company"],
            "container_no": kwargs.pop("container_no", f"TEST-{frappe.generate_hash(length=8)}"),
            "supplier": masters["supplier"],
            "item": masters["item"],
            "arrival_date": nowdate(),
            "inward_qty": inward_qty,
            "uom": masters["uom"],
            "currency": masters["currency"],
            "status": "Selling",
            "closing_status": "Open",
            "default_rate_floor": rate_floor,
            "default_rate_ceiling": kwargs.pop("rate_ceiling", 200),
            "lots": [
                {
                    "lot_no": lot_no,
                    "inward_qty": inward_qty,
                    "uom": masters["uom"],
                    "count_size": kwargs.pop("count_size", "16/20"),
                }
            ],
            **kwargs,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc


def make_deal(container, lot_no="LOT-A", qty=10, proposed_rate=120, **kwargs):
    masters = ensure_masters()
    doc = frappe.get_doc(
        {
            "doctype": "Fresko Deal",
            "naming_series": "DEAL-.YYYY.-.",
            "company": container.company,
            "container": container.name,
            "buyer_alias": kwargs.pop("buyer_alias", "TestBuyer"),
            "item": container.item,
            "lot_no": lot_no,
            "qty": qty,
            "uom": container.uom,
            "proposed_rate": proposed_rate,
            "currency": container.currency,
            "status": "Proposed",
            **kwargs,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc
