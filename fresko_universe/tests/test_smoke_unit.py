"""
Smoke / unit tests runnable without a Frappe bench.

  python -m pytest tests/test_smoke_unit.py -v
  python -m unittest tests.test_smoke_unit -v

These cover pure logic: fingerprint algorithm, rate-band hierarchy, ATS math,
transition maps, D4 counter path state rules — via lightweight mocks.
"""

from __future__ import annotations

import hashlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Ensure app package importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _install_frappe_stub():
    if "frappe" in sys.modules and hasattr(sys.modules["frappe"], "utils"):
        return
    frappe = types.ModuleType("frappe")
    frappe.throw = lambda *a, **k: (_ for _ in ()).throw(Exception(a[0] if a else "throw"))
    frappe.whitelist = lambda *a, **k: (lambda fn: fn)
    frappe.log_error = lambda *a, **k: None
    frappe.session = types.SimpleNamespace(user="Administrator")
    frappe.db = MagicMock()
    frappe.get_doc = MagicMock()
    frappe.get_all = MagicMock(return_value=[])
    frappe.get_roles = MagicMock(return_value=["System Manager"])
    utils = types.ModuleType("frappe.utils")
    utils.flt = lambda v, p=None: float(v or 0)
    utils.nowdate = lambda: "2026-09-15"
    utils.now_datetime = lambda: "2026-09-15 12:00:00"
    utils.sha256_hash = lambda s: hashlib.sha256(s.encode()).hexdigest()
    frappe.utils = utils
    model = types.ModuleType("frappe.model")
    document = types.ModuleType("frappe.model.document")
    class Document:
        pass
    document.Document = Document
    sys.modules["frappe"] = frappe
    sys.modules["frappe.utils"] = utils
    sys.modules["frappe.model"] = model
    sys.modules["frappe.model.document"] = document
    tests_utils = types.ModuleType("frappe.tests")
    tests_utils2 = types.ModuleType("frappe.tests.utils")
    class FrappeTestCase(unittest.TestCase):
        pass
    tests_utils2.FrappeTestCase = FrappeTestCase
    sys.modules["frappe.tests"] = tests_utils
    sys.modules["frappe.tests.utils"] = tests_utils2


_install_frappe_stub()

from fresko_universe.constants import (  # noqa: E402
    ATS_ACTIVE_STATUSES,
    DEAL_TRANSITIONS,
    OVERSELL_OVERRIDE_ROLES,
)
from fresko_universe.rate_rules import rate_in_band, resolve_rate_band  # noqa: E402
from fresko_universe.ats import commercial_qty_for_ats  # noqa: E402


class TestFingerprintAlgorithm(unittest.TestCase):
    def test_locked_fingerprint_shape(self):
        buyer_alias = "  Rehan "
        container = "CON-2026-0001"
        lot_no = "41869"
        qty = 50
        proposed_rate = 120.5
        uom = "Kg"
        day = "2026-09-15"
        raw = "|".join(
            [
                buyer_alias.strip().lower(),
                container,
                lot_no,
                f"{float(qty):.6f}".rstrip("0").rstrip("."),
                f"{float(proposed_rate):.6f}".rstrip("0").rstrip("."),
                uom,
                day,
            ]
        )
        fp = hashlib.sha256(raw.encode()).hexdigest()
        self.assertEqual(len(fp), 64)
        # stable
        self.assertEqual(fp, hashlib.sha256(raw.encode()).hexdigest())
        self.assertIn("rehan|", raw)


class TestRateFloorHierarchyD5(unittest.TestCase):
    def _container(self, **kw):
        c = MagicMock()
        c.get = lambda k, d=None: kw.get(k, d)
        for k, v in kw.items():
            setattr(c, k, v)
        return c

    def test_lot_override_wins(self):
        lot = MagicMock()
        lot.lot_no = "L1"
        lot.rate_floor_override = 80
        lot.rate_ceiling_override = 150
        lot.get = lambda k, d=None: getattr(lot, k, d)
        lot.count_size = "16/20"
        c = self._container(
            default_rate_floor=100,
            default_rate_ceiling=200,
            lots=[lot],
            rate_rules=[],
        )
        floor, ceiling = resolve_rate_band(c, "L1", "16/20")
        self.assertEqual(floor, 80)
        self.assertEqual(ceiling, 150)

    def test_count_size_rule_middle_tier(self):
        lot = MagicMock()
        lot.lot_no = "L1"
        lot.rate_floor_override = None
        lot.rate_ceiling_override = None
        lot.count_size = "16/20"
        lot.get = lambda k, d=None: getattr(lot, k, d)
        rule = MagicMock()
        rule.count_size = "16/20"
        rule.rate_floor = 90
        rule.rate_ceiling = 140
        rule.get = lambda k, d=None: getattr(rule, k, d)
        c = self._container(
            default_rate_floor=100,
            default_rate_ceiling=200,
            lots=[lot],
            rate_rules=[rule],
        )
        floor, ceiling = resolve_rate_band(c, "L1", "16/20")
        self.assertEqual(floor, 90)
        self.assertEqual(ceiling, 140)

    def test_container_default_fallback(self):
        lot = MagicMock()
        lot.lot_no = "L1"
        lot.rate_floor_override = None
        lot.rate_ceiling_override = None
        lot.count_size = None
        lot.get = lambda k, d=None: getattr(lot, k, d)
        c = self._container(
            default_rate_floor=100,
            default_rate_ceiling=200,
            lots=[lot],
            rate_rules=[],
        )
        floor, ceiling = resolve_rate_band(c, "L1", None)
        self.assertEqual(floor, 100)
        self.assertEqual(ceiling, 200)

    def test_rate_in_band(self):
        self.assertTrue(rate_in_band(100, 100, 200))
        self.assertFalse(rate_in_band(99, 100, 200))
        self.assertFalse(rate_in_band(201, 100, 200))
        self.assertTrue(rate_in_band(150, None, None))


class TestATSMath(unittest.TestCase):
    def test_proposed_not_in_active(self):
        self.assertNotIn("Proposed", ATS_ACTIVE_STATUSES)
        self.assertNotIn("Approval Required", ATS_ACTIVE_STATUSES)
        self.assertIn("Approved", ATS_ACTIVE_STATUSES)
        self.assertIn("Auto Approved", ATS_ACTIVE_STATUSES)
        self.assertNotIn("Countered", ATS_ACTIVE_STATUSES)

    def test_partial_dispatch_remaining(self):
        deal = MagicMock(status="Partially Dispatched", qty=100, dispatched_qty=40)
        self.assertEqual(commercial_qty_for_ats(deal), 60)

    def test_cancelled_zero(self):
        deal = MagicMock(status="Cancelled", qty=100, dispatched_qty=0)
        self.assertEqual(commercial_qty_for_ats(deal), 0)


class TestStateMachineD4(unittest.TestCase):
    def test_countered_only_to_approved_or_cancelled(self):
        self.assertEqual(DEAL_TRANSITIONS["Countered"], {"Approved", "Cancelled"})
        self.assertNotIn("Outward Pending", DEAL_TRANSITIONS["Countered"])

    def test_proposed_transitions(self):
        self.assertEqual(
            DEAL_TRANSITIONS["Proposed"],
            {"Auto Approved", "Approval Required", "Cancelled"},
        )

    def test_reconciled_terminal(self):
        self.assertEqual(DEAL_TRANSITIONS["Reconciled"], set())


class TestD10Roles(unittest.TestCase):
    def test_oversell_roles(self):
        self.assertIn("System Manager", OVERSELL_OVERRIDE_ROLES)
        # D10: Approver alone is insufficient for oversell
        self.assertNotIn("Fresko Approver", OVERSELL_OVERRIDE_ROLES)


class TestAppLayout(unittest.TestCase):
    def test_required_files_exist(self):
        app = ROOT / "fresko_universe"
        required = [
            "hooks.py",
            "modules.txt",
            "patches.txt",
            "install.py",
            "constants.py",
            "ats.py",
            "rate_rules.py",
            "deals.py",
            "approvals.py",
            "container.py",
            "fresko_core/doctype/fresko_container/fresko_container.json",
            "fresko_core/doctype/fresko_container_lot/fresko_container_lot.json",
            "fresko_core/doctype/fresko_container_source_document/fresko_container_source_document.json",
            "fresko_core/doctype/fresko_container_rate_rule/fresko_container_rate_rule.json",
            "fresko_deals/doctype/fresko_approval/fresko_approval.json",
            "fresko_deals/doctype/fresko_revision/fresko_revision.json",
            "fresko_core/doctype/fresko_evidence/fresko_evidence.json",
            "fresko_core/doctype/fresko_exception/fresko_exception.json",
            "fresko_deals/doctype/fresko_deal/fresko_deal.json",
        ]
        for rel in required:
            self.assertTrue((app / rel).exists(), f"missing {rel}")

    def test_doctype_json_names(self):
        import json
        expected = {
            "fresko_container": "Fresko Container",
            "fresko_deal": "Fresko Deal",
            "fresko_approval": "Fresko Approval",
            "fresko_revision": "Fresko Revision",
            "fresko_evidence": "Fresko Evidence",
            "fresko_exception": "Fresko Exception",
        }
        for key, name in expected.items():
            # find json
            matches = list((ROOT / "fresko_universe").rglob(f"{key}.json"))
            self.assertTrue(matches, key)
            data = json.loads(matches[0].read_text())
            self.assertEqual(data["name"], name)

    def test_sample_drive_fixtures_exist(self):
        fixtures = ROOT / "fresko_universe" / "fixtures" / "drive"
        self.assertTrue((fixtures / "SAMPLE_lots_buyers_rates.xlsx").exists())
        self.assertTrue((fixtures / "SAMPLE_container_header.xlsx").exists())


if __name__ == "__main__":
    unittest.main()
