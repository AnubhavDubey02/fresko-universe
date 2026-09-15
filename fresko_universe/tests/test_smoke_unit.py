"""Smoke tests without Frappe bench: python3 -m unittest tests.test_smoke_unit -v"""

from __future__ import annotations

import hashlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _install_frappe_stub():
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
    tu = types.ModuleType("frappe.tests")
    tu2 = types.ModuleType("frappe.tests.utils")
    class FrappeTestCase(unittest.TestCase):
        pass
    tu2.FrappeTestCase = FrappeTestCase
    sys.modules["frappe.tests"] = tu
    sys.modules["frappe.tests.utils"] = tu2


_install_frappe_stub()

from fresko_universe.constants import (  # noqa: E402
    ATS_ACTIVE_STATUSES,
    COMMERCIAL_LOCK_STATUSES,
    DEAL_TRANSITIONS,
    MATERIAL_REVISION_FIELDS,
    OVERSELL_OVERRIDE_ROLES,
)
from fresko_universe.rate_rules import rate_in_band, resolve_rate_band  # noqa: E402
from fresko_universe.ats import commercial_qty_for_ats  # noqa: E402


class TestFingerprint(unittest.TestCase):
    def test_locked_shape(self):
        raw = "|".join(["rehan", "CON-1", "41869", "50", "120.5", "Kg", "2026-09-15"])
        fp = hashlib.sha256(raw.encode()).hexdigest()
        self.assertEqual(len(fp), 64)


class TestRateFloorD5(unittest.TestCase):
    def _c(self, **kw):
        c = MagicMock()
        c.get = lambda k, d=None: kw.get(k, d)
        for k, v in kw.items():
            setattr(c, k, v)
        return c

    def test_lot_override(self):
        lot = MagicMock(lot_no="L1", rate_floor_override=80, rate_ceiling_override=150, count_size="16/20")
        lot.get = lambda k, d=None: getattr(lot, k, d)
        c = self._c(default_rate_floor=100, default_rate_ceiling=200, lots=[lot], rate_rules=[])
        floor, ceiling = resolve_rate_band(c, "L1", "16/20")
        self.assertEqual(floor, 80)
        self.assertEqual(ceiling, 150)

    def test_count_size_rule(self):
        lot = MagicMock(lot_no="L1", rate_floor_override=None, rate_ceiling_override=None, count_size="16/20")
        lot.get = lambda k, d=None: getattr(lot, k, d)
        rule = MagicMock(count_size="16/20", rate_floor=90, rate_ceiling=140)
        rule.get = lambda k, d=None: getattr(rule, k, d)
        c = self._c(default_rate_floor=100, default_rate_ceiling=200, lots=[lot], rate_rules=[rule])
        floor, ceiling = resolve_rate_band(c, "L1", "16/20")
        self.assertEqual(floor, 90)

    def test_default(self):
        lot = MagicMock(lot_no="L1", rate_floor_override=None, rate_ceiling_override=None, count_size=None)
        lot.get = lambda k, d=None: getattr(lot, k, d)
        c = self._c(default_rate_floor=100, default_rate_ceiling=200, lots=[lot], rate_rules=[])
        floor, ceiling = resolve_rate_band(c, "L1", None)
        self.assertEqual(floor, 100)

    def test_in_band(self):
        self.assertTrue(rate_in_band(100, 100, 200))
        self.assertFalse(rate_in_band(99, 100, 200))


class TestATS(unittest.TestCase):
    def test_proposed_excluded(self):
        self.assertNotIn("Proposed", ATS_ACTIVE_STATUSES)
        self.assertNotIn("Approval Required", ATS_ACTIVE_STATUSES)
        self.assertNotIn("Countered", ATS_ACTIVE_STATUSES)
        self.assertIn("Approved", ATS_ACTIVE_STATUSES)
        self.assertIn("Auto Approved", ATS_ACTIVE_STATUSES)

    def test_partial(self):
        d = MagicMock(status="Partially Dispatched", qty=100, dispatched_qty=40)
        self.assertEqual(commercial_qty_for_ats(d), 60)

    def test_cancelled_zero_dispatch(self):
        d = MagicMock(status="Cancelled", qty=100, dispatched_qty=0)
        self.assertEqual(commercial_qty_for_ats(d), 0)

    def test_cancelled_keeps_dispatched(self):
        # QA: cancel after partial must not free already-dispatched qty
        d = MagicMock(status="Cancelled", qty=100, dispatched_qty=40)
        self.assertEqual(commercial_qty_for_ats(d), 40)
        self.assertIn("Cancelled", ATS_ACTIVE_STATUSES)


class TestD4(unittest.TestCase):
    def test_countered(self):
        self.assertEqual(DEAL_TRANSITIONS["Countered"], {"Approved", "Cancelled"})


class TestD10(unittest.TestCase):
    def test_roles(self):
        self.assertIn("System Manager", OVERSELL_OVERRIDE_ROLES)
        self.assertNotIn("Fresko Approver", OVERSELL_OVERRIDE_ROLES)
        self.assertNotIn("Fresko Owner", OVERSELL_OVERRIDE_ROLES)
        self.assertEqual(OVERSELL_OVERRIDE_ROLES, frozenset({"System Manager"}))


class TestCommercialLock(unittest.TestCase):
    def test_approval_required_locked(self):
        # F-H4
        self.assertIn("Approval Required", COMMERCIAL_LOCK_STATUSES)
        self.assertIn("approved_rate", MATERIAL_REVISION_FIELDS)
        self.assertIn("qty", MATERIAL_REVISION_FIELDS)


class TestLayout(unittest.TestCase):
    def test_files(self):
        app = ROOT / "fresko_universe"
        for rel in [
            "hooks.py", "modules.txt", "patches.txt", "install.py", "constants.py",
            "ats.py", "rate_rules.py", "deals.py", "approvals.py", "container.py",
            "fresko_core/ats.py",
            "fresko_core/doctype/fresko_container/fresko_container.json",
            "fresko_core/doctype/fresko_container_lot/fresko_container_lot.json",
            "fresko_core/doctype/fresko_approval/fresko_approval.json",
            "fresko_core/doctype/fresko_revision/fresko_revision.json",
            "fresko_core/doctype/fresko_evidence/fresko_evidence.json",
            "fresko_core/doctype/fresko_exception/fresko_exception.json",
            "fresko_deals/doctype/fresko_deal/fresko_deal.json",
        ]:
            self.assertTrue((app / rel).exists(), rel)

    def test_doctype_names(self):
        expected = {
            "fresko_container": "Fresko Container",
            "fresko_deal": "Fresko Deal",
            "fresko_approval": "Fresko Approval",
            "fresko_revision": "Fresko Revision",
            "fresko_evidence": "Fresko Evidence",
            "fresko_exception": "Fresko Exception",
        }
        for key, name in expected.items():
            matches = list((ROOT / "fresko_universe").rglob(f"{key}.json"))
            self.assertTrue(matches, key)
            self.assertEqual(json.loads(matches[0].read_text())["name"], name)

    def test_evidence_hash_field_canonical(self):
        # content_sha256 in JSON; controller must match (no content_hash dual name)
        ev_json = next((ROOT / "fresko_universe").rglob("fresko_evidence.json"))
        data = json.loads(ev_json.read_text())
        fields = {f["fieldname"] for f in data["fields"]}
        self.assertIn("content_sha256", fields)
        self.assertNotIn("content_hash", fields)
        ev_py = (
            ROOT / "fresko_universe" / "fresko_core" / "doctype" /
            "fresko_evidence" / "fresko_evidence.py"
        ).read_text()
        self.assertIn("content_sha256", ev_py)
        self.assertNotIn("content_hash", ev_py)

    def test_approval_revision_under_core(self):
        core = ROOT / "fresko_universe" / "fresko_core" / "doctype"
        self.assertTrue((core / "fresko_approval" / "fresko_approval.json").exists())
        self.assertTrue((core / "fresko_revision" / "fresko_revision.json").exists())
        self.assertTrue((core / "fresko_approval" / "fresko_approval.py").exists())
        self.assertTrue((core / "fresko_revision" / "fresko_revision.py").exists())
        deals = ROOT / "fresko_universe" / "fresko_deals" / "doctype"
        self.assertFalse((deals / "fresko_approval").exists())
        self.assertFalse((deals / "fresko_revision").exists())


if __name__ == "__main__":
    unittest.main()
