"""Bench replay of the sanitized Plum aggregate through public services."""

from __future__ import annotations

import json
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from fresko_universe import outward, quantity_assertion
from fresko_universe.fresko_core.physical import physical_snapshot
from fresko_universe.tests.test_phase2a_outward import _ensure_user
from fresko_universe.tests.utils import ensure_masters


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "real_data_shadow"
    / "manifest.json"
)


class TestRealDataServiceReplay(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.masters = ensure_masters()
        cls.maker = _ensure_user(
            "shadow_replay_maker@example.com",
            ["Fresko Salesperson", "Fresko Approver"],
        )
        cls.checker = _ensure_user(
            "shadow_replay_checker@example.com", ["Fresko Approver"]
        )

    def setUp(self):
        frappe.set_user("Administrator")

    def test_plum_aggregate_replays_through_quantity_and_outward_services(self):
        manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        expected = next(row for row in manifest["replays"] if row["id"] == "21-sep-plum")
        lots = expected["lots"]
        container = frappe.get_doc(
            {
                "doctype": "Fresko Container",
                "naming_series": "CON-.YYYY.-.",
                "company": self.masters["company"],
                "container_no": f"SHADOW-PLUM-{frappe.generate_hash(length=6)}",
                "supplier": self.masters["supplier"],
                "item": self.masters["item"],
                "arrival_date": nowdate(),
                "inward_qty": expected["operating_inward"],
                "uom": self.masters["uom"],
                "currency": self.masters["currency"],
                "status": "Selling",
                "closing_status": "Open",
                "lots": [
                    {
                        "lot_no": lot_no,
                        "inward_qty": quantity,
                        "uom": self.masters["uom"],
                        "count_size": "SYNTHETIC",
                    }
                    for lot_no, quantity in lots.items()
                ],
            }
        ).insert(ignore_permissions=True)
        evidence = frappe.get_doc(
            {
                "doctype": "Fresko Evidence",
                "evidence_type": "Note",
                "container": container.name,
                "notes": "sanitized aggregate shadow replay; not source evidence",
            }
        ).insert(ignore_permissions=True)

        frappe.set_user(self.maker)
        operating = quantity_assertion.create(
            container=container.name,
            basis="OPERATING_INWARD",
            raw_value=str(expected["operating_inward"]),
            quantity=str(expected["operating_inward"]),
            uom=self.masters["uom"],
            raw_uom=self.masters["uom"],
            evidence=evidence.name,
            effective_at=f"{expected['as_of']} 23:59:59",
            provenance="SOURCE_EXTRACTED",
            reason="sanitized Plum aggregate replay",
            source_fact_id="plum-operating-inward-aggregate",
        )
        quantity_assertion.submit(operating["name"])
        frappe.set_user(self.checker)
        quantity_assertion.review(operating["name"], "ACTIVATE")

        frappe.set_user(self.maker)
        movement = outward.create(
            container=container.name,
            movement_at=f"{expected['as_of']} 23:59:59",
            source_evidence=evidence.name,
            source_event_id="plum-operating-outward-aggregate",
            lines=[
                {
                    "source_line_ref": f"line-{index}",
                    "raw_lot_text": lot_no,
                    "lot_no": lot_no,
                    "qty": quantity,
                    "uom": self.masters["uom"],
                    "raw_qty_text": str(quantity),
                    "raw_uom_text": self.masters["uom"],
                    "raw_rate_text": "PENDING",
                }
                for index, (lot_no, quantity) in enumerate(lots.items(), start=1)
            ],
        )
        outward.submit_for_review(movement["name"])
        frappe.set_user(self.checker)
        outward.post(movement["name"])

        frappe.set_user("Administrator")
        physical = physical_snapshot(container.name)
        self.assertEqual(physical["posted_physical_total"], expected["operating_outward"])
        self.assertEqual(physical["posted_by_lot"], {key: float(value) for key, value in lots.items()})
        self.assertEqual(expected["operating_inward"] - physical["posted_physical_total"], expected["stock"])
        projection = quantity_assertion.reconciliation_projection(container.name)
        self.assertEqual(projection["reconciliation_status"], "UNRESOLVED")
        self.assertEqual(
            frappe.db.count(
                "Fresko Container Quantity Assertion",
                {
                    "container": container.name,
                    "basis": "OPERATING_INWARD",
                    "status": "Active",
                },
            ),
            1,
        )
        self.assertEqual(
            frappe.db.count(
                "Fresko Exception",
                {"outward": movement["name"], "exception_type": "OUTWARD_UNPRICED"},
            ),
            1,
        )

