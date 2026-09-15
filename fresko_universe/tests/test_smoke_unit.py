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
    frappe._ = lambda msg, *a, **k: msg
    frappe.whitelist = lambda *a, **k: (lambda fn: fn)
    frappe.log_error = lambda *a, **k: None
    frappe.session = types.SimpleNamespace(user="Administrator")
    frappe.PermissionError = type("PermissionError", (Exception,), {})
    frappe.db = MagicMock()
    frappe.db.escape = lambda v: "'%s'" % str(v).replace("'", "''")
    frappe.get_doc = MagicMock()
    frappe.get_all = MagicMock(return_value=[])
    frappe.get_roles = MagicMock(return_value=["System Manager"])
    frappe.db.commit = MagicMock()
    frappe.db.escape = lambda v, percent=True: "'%s'" % str(v).replace("'", "''")
    frappe.PermissionError = type("PermissionError", (Exception,), {})
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
    EXCEPTION_TYPES,
    MATERIAL_REVISION_FIELDS,
    OVERSELL_OVERRIDE_ROLES,
)
from fresko_universe.rate_rules import (  # noqa: E402
    policy_resolved,
    rate_in_band,
    resolve_rate_band,
)
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

    def test_policy_resolved(self):
        self.assertFalse(policy_resolved(None, None))
        self.assertTrue(policy_resolved(100, None))
        self.assertTrue(policy_resolved(None, 200))
        self.assertTrue(policy_resolved(100, 200))

    def test_currency_zero_overrides_fall_through_to_default(self):
        """Bench Currency empty → 0.0 must not win over container defaults."""
        lot = MagicMock(
            lot_no="L1",
            rate_floor_override=0.0,
            rate_ceiling_override=0.0,
            count_size="16/20",
        )
        lot.get = lambda k, d=None: getattr(lot, k, d)
        c = self._c(default_rate_floor=100, default_rate_ceiling=200, lots=[lot], rate_rules=[])
        floor, ceiling = resolve_rate_band(c, "L1", "16/20")
        self.assertEqual(floor, 100)
        self.assertEqual(ceiling, 200)

    def test_currency_zero_defaults_are_unresolved(self):
        lot = MagicMock(
            lot_no="L1",
            rate_floor_override=0.0,
            rate_ceiling_override=0.0,
            count_size=None,
        )
        lot.get = lambda k, d=None: getattr(lot, k, d)
        c = self._c(default_rate_floor=0.0, default_rate_ceiling=0.0, lots=[lot], rate_rules=[])
        floor, ceiling = resolve_rate_band(c, "L1", None)
        self.assertIsNone(floor)
        self.assertIsNone(ceiling)
        self.assertFalse(policy_resolved(floor, ceiling))

    def test_empty_band_must_not_imply_resolved(self):
        # F-M7 closed: empty band is not resolved and not in-band
        self.assertFalse(policy_resolved(None, None))
        self.assertFalse(rate_in_band(50, None, None))
        # Currency empty → 0.0 must also be unresolved (bench)
        self.assertFalse(policy_resolved(0, 0))
        self.assertFalse(policy_resolved(0.0, None))
        self.assertFalse(rate_in_band(50, 0, 0))



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



class TestD10Runtime(unittest.TestCase):
    """Runtime gate: Approver cannot commercial-oversell (D10) without bench."""

    def test_approver_cannot_oversell_override(self):
        import frappe
        from fresko_universe.approvals import decide

        frappe.get_roles = MagicMock(return_value=["Fresko Approver"])
        deal = MagicMock()
        deal.name = "DEAL-OV"
        deal.status = "Approval Required"
        deal.container = "C1"
        deal.lot_no = "L1"
        deal.qty = 100
        deal.proposed_rate = 10
        deal.rate_floor = 5
        deal.rate_ceiling = 20
        frappe.get_doc = MagicMock(return_value=deal)

        with self.assertRaises(Exception) as ctx:
            decide("DEAL-OV", "OVERSELL_OVERRIDE", reason="try oversell")
        self.assertIn("System Manager", str(ctx.exception))

    def test_approver_cannot_approve_with_oversell_flag(self):
        import frappe
        from fresko_universe.approvals import decide

        frappe.get_roles = MagicMock(return_value=["Fresko Approver"])
        deal = MagicMock()
        deal.name = "DEAL-OV2"
        deal.status = "Approval Required"
        deal.container = "C1"
        deal.lot_no = "L1"
        deal.qty = 100
        deal.proposed_rate = 10
        deal.rate_floor = 5
        deal.rate_ceiling = 20
        frappe.get_doc = MagicMock(return_value=deal)

        with self.assertRaises(Exception) as ctx:
            decide("DEAL-OV2", "APPROVE", reason="try flag", oversell_override=1)
        self.assertIn("System Manager", str(ctx.exception))


class TestFlagContracts(unittest.TestCase):
    """Source-level contracts for F-H5 / F-H6 (no bench required)."""

    def test_apply_revision_uses_allow_revision_apply(self):
        deals_py = (ROOT / "fresko_universe" / "deals.py").read_text()
        rev_py = (
            ROOT / "fresko_universe" / "fresko_core" / "doctype"
            / "fresko_revision" / "fresko_revision.py"
        ).read_text()
        self.assertIn("allow_revision_apply", rev_py)
        self.assertIn("rev.flags.allow_revision_apply", deals_py)
        self.assertNotIn("allow_applied_write", deals_py)
        self.assertNotIn("allow_applied_write", rev_py)
        # Return dict must include supporting_evidence (acceptance KeyError fix)
        self.assertIn('"supporting_evidence": rev.supporting_evidence', deals_py)

    def test_dispatch_flag_unified_to_allow_dispatch_write(self):
        deals_py = (ROOT / "fresko_universe" / "deals.py").read_text()
        deal_py = (
            ROOT / "fresko_universe" / "fresko_deals" / "doctype"
            / "fresko_deal" / "fresko_deal.py"
        ).read_text()
        self.assertIn("allow_dispatch_write", deals_py)
        self.assertIn("allow_dispatch_write", deal_py)
        self.assertNotIn("allow_dispatched_qty_write", deals_py)
        self.assertNotIn("allow_dispatched_qty_write", deal_py)
        # Single cancel_deal definition (F-M1 duplicate removed)
        self.assertEqual(deals_py.count("def cancel_deal"), 1)
        # set_dispatched_qty delegates to record_dispatch
        self.assertIn("def set_dispatched_qty", deals_py)
        self.assertIn("return record_dispatch(", deals_py)

    def test_lot_delete_cannot_bypass_approved_sold(self):
        container_py = (
            ROOT / "fresko_universe" / "fresko_core" / "doctype"
            / "fresko_container" / "fresko_container.py"
        ).read_text()
        self.assertIn("Cannot remove lot", container_py)
        self.assertIn("not in current_lots", container_py)

    def test_applied_revision_trail_frozen(self):
        rev_py = (
            ROOT / "fresko_universe" / "fresko_core" / "doctype"
            / "fresko_revision" / "fresko_revision.py"
        ).read_text()
        for field in (
            "old_value",
            "new_value",
            "reason",
            "supporting_evidence",
            "approval_reference",
            "changed_by",
            "changed_at",
        ):
            self.assertIn('"' + field + '"', rev_py)
        self.assertIn("Cannot alter historical revision field", rev_py)

    def test_accept_counter_acl_owner_salesperson_only(self):
        deals_py = (ROOT / "fresko_universe" / "deals.py").read_text()
        self.assertNotIn(
            'is_privileged = "System Manager" in roles or "Fresko Approver"',
            deals_py,
        )
        self.assertNotIn("System Manager) may accept a counter", deals_py)
        self.assertNotIn('"System Manager" not in roles', deals_py)
        self.assertIn(
            "Only the deal owner or assigned salesperson_user may accept a counter (D4)",
            deals_py,
        )




class TestGate1RatePolicyMissing(unittest.TestCase):
    """Gate 1: empty rate policy fail-closed → AR + RATE_POLICY_MISSING."""

    def _deal(self, **kw):
        d = MagicMock()
        d.name = kw.get("name", "DEAL-RP")
        d.status = "Proposed"
        d.container = "C1"
        d.lot_no = kw.get("lot_no", "L1")
        d.count_size = kw.get("count_size", "16/20")
        d.proposed_rate = kw.get("proposed_rate", 100)
        d.qty = kw.get("qty", 10)
        d.approved_rate = None
        d.approval_required = 0
        d.rate_floor = None
        d.rate_ceiling = None
        d.customer = kw.get("customer", "Cust")
        d.buyer_alias = None
        d.flags = MagicMock()
        d.set_status = MagicMock(side_effect=lambda s: setattr(d, "status", s))
        d.save = MagicMock()
        d.get = lambda k, default=None: getattr(d, k, default)
        return d

    def _container(self, **kw):
        c = MagicMock()
        defaults = {
            "lots": kw.get("lots", []),
            "rate_rules": kw.get("rate_rules", []),
            "default_rate_floor": kw.get("default_rate_floor", None),
            "default_rate_ceiling": kw.get("default_rate_ceiling", None),
        }
        c.get = lambda k, d=None: defaults.get(k, d) if k in defaults else getattr(c, k, d)
        for k, v in defaults.items():
            setattr(c, k, v)
        return c

    def _lot(self, lot_no="L1", floor=None, ceiling=None, count_size="16/20"):
        lot = MagicMock(
            lot_no=lot_no,
            rate_floor_override=floor,
            rate_ceiling_override=ceiling,
            count_size=count_size,
        )
        lot.get = lambda k, d=None: getattr(lot, k, d)
        return lot

    def _run_apply(self, deal, container, ats=1000):
        import frappe
        from fresko_universe import deals as deals_mod
        from fresko_universe import ats as ats_mod

        inserted = []

        def fake_get_doc(dt, name=None):
            if dt == "Fresko Deal":
                return deal
            if dt == "Fresko Container":
                return container
            if dt == "Fresko Exception":
                ex = MagicMock()
                ex.insert = MagicMock()
                inserted.append(ex)
                return ex
            return MagicMock()

        frappe.get_doc = MagicMock(side_effect=fake_get_doc)
        # _open_exception uses frappe.get_doc({dict}) — handle dict form
        _real_side = frappe.get_doc.side_effect

        def get_doc_flex(*a, **k):
            if a and isinstance(a[0], dict):
                ex = MagicMock()
                ex.insert = MagicMock()
                ex.name = "EX-1"
                inserted.append(a[0])
                return ex
            return _real_side(*a, **k)

        frappe.get_doc = MagicMock(side_effect=get_doc_flex)
        frappe.get_all = MagicMock(return_value=[])
        frappe.db.commit = MagicMock()
        # Gate 1 paths run as privileged site user (bench Administrator / SM)
        frappe.session = types.SimpleNamespace(user="Administrator")
        frappe.get_roles = MagicMock(return_value=["System Manager"])

        # Patch ATS on deals module (imported name binding)
        orig_ats = deals_mod.available_to_sell
        deals_mod.available_to_sell = MagicMock(return_value=ats)
        try:
            result = deals_mod.apply_rate_rules(deal.name)
        finally:
            deals_mod.available_to_sell = orig_ats
        return result, inserted

    def test_1_no_rules_no_defaults_rate_policy_missing(self):
        deal = self._deal()
        container = self._container(lots=[self._lot()], rate_rules=[], default_rate_floor=None)
        result, inserted = self._run_apply(deal, container)
        self.assertEqual(deal.status, "Approval Required")
        self.assertEqual(deal.approval_required, 1)
        self.assertIsNone(deal.approved_rate)
        self.assertEqual(deal.proposed_rate, 100)
        self.assertIsNone(deal.rate_floor)
        self.assertIsNone(deal.rate_ceiling)
        self.assertTrue(any(i.get("exception_type") == "RATE_POLICY_MISSING" for i in inserted))
        self.assertIn("RATE_POLICY_MISSING", EXCEPTION_TYPES)

    def test_2_rules_exist_no_matching_count_size_no_defaults(self):
        rule = MagicMock(count_size="21/25", rate_floor=90, rate_ceiling=140)
        rule.get = lambda k, d=None: getattr(rule, k, d)
        deal = self._deal(count_size="16/20")
        container = self._container(
            lots=[self._lot(count_size="16/20")],
            rate_rules=[rule],
            default_rate_floor=None,
            default_rate_ceiling=None,
        )
        result, inserted = self._run_apply(deal, container)
        self.assertEqual(deal.status, "Approval Required")
        self.assertTrue(any(i.get("exception_type") == "RATE_POLICY_MISSING" for i in inserted))
        self.assertIsNone(deal.approved_rate)

    def test_3_lot_without_override_no_other_rule(self):
        deal = self._deal(count_size=None)
        # lot exists, no override, no count_size → falls through to empty defaults
        container = self._container(
            lots=[self._lot(floor=None, ceiling=None, count_size=None)],
            rate_rules=[],
            default_rate_floor=None,
        )
        result, inserted = self._run_apply(deal, container)
        self.assertEqual(deal.status, "Approval Required")
        self.assertTrue(any(i.get("exception_type") == "RATE_POLICY_MISSING" for i in inserted))

    def test_4_inherited_floor_in_band_auto_approved(self):
        deal = self._deal(proposed_rate=110, count_size="16/20")
        rule = MagicMock(count_size="16/20", rate_floor=100, rate_ceiling=200)
        rule.get = lambda k, d=None: getattr(rule, k, d)
        container = self._container(
            lots=[self._lot(floor=None, ceiling=None, count_size="16/20")],
            rate_rules=[rule],
            default_rate_floor=None,
        )
        result, inserted = self._run_apply(deal, container, ats=1000)
        self.assertEqual(deal.status, "Auto Approved")
        self.assertEqual(deal.approved_rate, 110)
        self.assertEqual(deal.approval_required, 0)
        self.assertFalse(any(i.get("exception_type") == "RATE_POLICY_MISSING" for i in inserted))

    def test_5_lot_override_in_band_auto_approved(self):
        deal = self._deal(proposed_rate=85, count_size="16/20")
        container = self._container(
            lots=[self._lot(floor=80, ceiling=150, count_size="16/20")],
            rate_rules=[],
            default_rate_floor=100,
        )
        result, inserted = self._run_apply(deal, container, ats=1000)
        self.assertEqual(deal.status, "Auto Approved")
        self.assertEqual(deal.approved_rate, 85)
        self.assertEqual(deal.rate_floor, 80)


class TestD4AcceptCounterACL(unittest.TestCase):
    """D4 tighter: only owner or salesperson_user; SM/Approver cannot accept."""

    def _run(self, user, roles, owner="owner@x.com", salesperson=None):
        import frappe
        from fresko_universe import deals as deals_mod
        from fresko_universe import ats as ats_mod

        deal = MagicMock()
        deal.name = "DEAL-D4"
        deal.status = "Countered"
        deal.owner = owner
        deal.salesperson_user = salesperson
        deal.approved_rate = 12
        deal.container = "C1"
        deal.lot_no = "L1"
        deal.qty = 5
        deal.flags = MagicMock()
        deal.set_status = MagicMock(side_effect=lambda s: setattr(deal, "status", s))
        deal.save = MagicMock()

        frappe.session = types.SimpleNamespace(user=user)
        frappe.get_roles = MagicMock(return_value=roles)
        frappe.get_doc = MagicMock(return_value=deal)
        frappe.db.commit = MagicMock()
        deals_mod.available_to_sell = MagicMock(return_value=100)
        return deals_mod.accept_counter(deal.name), deal

    def test_owner_can_accept(self):
        result, deal = self._run("owner@x.com", ["Fresko Salesperson"], owner="owner@x.com")
        self.assertEqual(result["status"], "Approved")

    def test_salesperson_can_accept(self):
        result, deal = self._run(
            "sp@x.com", ["Fresko Salesperson"], owner="owner@x.com", salesperson="sp@x.com"
        )
        self.assertEqual(result["status"], "Approved")

    def test_system_manager_cannot_accept(self):
        with self.assertRaises(Exception) as ctx:
            self._run("admin@x.com", ["System Manager"], owner="owner@x.com", salesperson=None)
        self.assertIn("owner or assigned salesperson_user", str(ctx.exception))

    def test_approver_cannot_accept(self):
        with self.assertRaises(Exception) as ctx:
            self._run("appr@x.com", ["Fresko Approver"], owner="owner@x.com", salesperson="sp@x.com")
        self.assertIn("owner or assigned salesperson_user", str(ctx.exception))

    def test_empty_salesperson_only_owner(self):
        with self.assertRaises(Exception):
            self._run("other@x.com", ["Fresko Salesperson"], owner="owner@x.com", salesperson=None)


class TestD4SalespersonFieldLock(unittest.TestCase):
    """G-M1: salesperson_user must be commercially locked (blocks Desk reassignment on Countered)."""

    def test_salesperson_in_locked_commercial_fields(self):
        from fresko_universe.constants import LOCKED_COMMERCIAL_FIELDS, COMMERCIAL_LOCK_STATUSES

        self.assertIn("salesperson_user", LOCKED_COMMERCIAL_FIELDS)
        self.assertIn("Countered", COMMERCIAL_LOCK_STATUSES)



class TestFSEC001WhitelistACL(unittest.TestCase):
    """FSEC-001: Accounts / stranger cannot cancel, dispatch, or apply_rate_rules."""

    def _deal(self, owner="owner@x.com", salesperson=None, status="Approved"):
        deal = MagicMock()
        deal.name = "DEAL-ACL"
        deal.status = status
        deal.owner = owner
        deal.salesperson_user = salesperson
        deal.container = "C1"
        deal.lot_no = "L1"
        deal.qty = 10
        deal.dispatched_qty = 0
        deal.cancel_reason = None
        deal.proposed_rate = 100
        deal.count_size = "16/20"
        deal.flags = MagicMock()
        deal.set_status = MagicMock(side_effect=lambda s: setattr(deal, "status", s))
        deal.save = MagicMock()
        deal.get = lambda k, default=None: getattr(deal, k, default)
        return deal

    def _as(self, user, roles):
        import frappe

        frappe.session = types.SimpleNamespace(user=user)
        frappe.get_roles = MagicMock(return_value=roles)

    def test_accounts_cannot_cancel_deal(self):
        import frappe
        from fresko_universe import deals as deals_mod

        deal = self._deal()
        self._as("acc@x.com", ["Fresko Accounts"])
        frappe.get_doc = MagicMock(return_value=deal)
        with self.assertRaises(Exception) as ctx:
            deals_mod.cancel_deal(deal.name, "nope")
        self.assertIn("Not permitted", str(ctx.exception))

    def test_stranger_salesperson_cannot_cancel_others_deal(self):
        import frappe
        from fresko_universe import deals as deals_mod

        deal = self._deal(owner="owner@x.com", salesperson="sp@x.com")
        self._as("other@x.com", ["Fresko Salesperson"])
        frappe.get_doc = MagicMock(return_value=deal)
        with self.assertRaises(Exception) as ctx:
            deals_mod.cancel_deal(deal.name, "nope")
        self.assertIn("Not permitted", str(ctx.exception))

    def test_owner_salesperson_can_cancel(self):
        import frappe
        from fresko_universe import deals as deals_mod

        deal = self._deal(owner="sp@x.com", status="Proposed")
        self._as("sp@x.com", ["Fresko Salesperson"])
        frappe.get_doc = MagicMock(return_value=deal)
        frappe.db.commit = MagicMock()
        result = deals_mod.cancel_deal(deal.name, "buyer backed out")
        self.assertEqual(result["status"], "Cancelled")

    def test_salesperson_cannot_record_dispatch(self):
        import frappe
        from fresko_universe import deals as deals_mod

        deal = self._deal(owner="sp@x.com")
        self._as("sp@x.com", ["Fresko Salesperson"])
        frappe.get_doc = MagicMock(return_value=deal)
        with self.assertRaises(Exception) as ctx:
            deals_mod.record_dispatch(deal.name, 1)
        self.assertIn("Not permitted", str(ctx.exception))

    def test_accounts_cannot_record_dispatch(self):
        import frappe
        from fresko_universe import deals as deals_mod

        deal = self._deal()
        self._as("acc@x.com", ["Fresko Accounts"])
        frappe.get_doc = MagicMock(return_value=deal)
        with self.assertRaises(Exception) as ctx:
            deals_mod.record_dispatch(deal.name, 1)
        self.assertIn("Not permitted", str(ctx.exception))

    def test_approver_can_record_dispatch(self):
        import frappe
        from fresko_universe import deals as deals_mod

        deal = self._deal(status="Approved")
        self._as("appr@x.com", ["Fresko Approver"])
        frappe.get_doc = MagicMock(return_value=deal)
        frappe.db.sql = MagicMock(return_value=[])
        frappe.db.commit = MagicMock()
        result = deals_mod.record_dispatch(deal.name, 5)
        self.assertEqual(result["dispatched_qty"], 5)

    def test_accounts_cannot_apply_rate_rules(self):
        import frappe
        from fresko_universe import deals as deals_mod

        deal = self._deal(status="Proposed")
        self._as("acc@x.com", ["Fresko Accounts"])
        frappe.get_doc = MagicMock(return_value=deal)
        with self.assertRaises(Exception) as ctx:
            deals_mod.apply_rate_rules(deal.name)
        self.assertIn("Not permitted", str(ctx.exception))

    def test_accounts_cannot_request_revision(self):
        import frappe
        from fresko_universe import deals as deals_mod

        deal = self._deal(status="Approved")
        self._as("acc@x.com", ["Fresko Accounts"])
        frappe.get_doc = MagicMock(return_value=deal)
        with self.assertRaises(Exception) as ctx:
            deals_mod.request_revision(deal.name, "qty", "8", reason="cut")
        self.assertIn("Not permitted", str(ctx.exception))

    def test_snapshot_requires_fresko_role(self):
        from fresko_universe.permissions import assert_can_read_ats_snapshot

        self._as("acc@x.com", ["Fresko Accounts"])
        assert_can_read_ats_snapshot()
        self._as("stranger@x.com", ["Guest"])
        with self.assertRaises(Exception) as ctx:
            assert_can_read_ats_snapshot()
        self.assertIn("Not permitted", str(ctx.exception))


class TestFSEC002ApplyRevisionBind(unittest.TestCase):
    """FSEC-002: Approval must bind to deal + APPROVE/OVERSELL; Approver/SM only."""

    def _as(self, user, roles):
        import frappe

        frappe.session = types.SimpleNamespace(user=user)
        frappe.get_roles = MagicMock(return_value=roles)

    def _fixtures(self, approval_deal="DEAL-A", decision="APPROVE"):
        rev = MagicMock()
        rev.name = "REV-1"
        rev.status = "Pending"
        rev.parent_doctype = "Fresko Deal"
        rev.parent_name = "DEAL-A"
        rev.fieldname = "approved_rate"
        rev.new_value = "18"
        rev.approval_reference = None
        rev.supporting_evidence = "EV-1"
        rev.flags = MagicMock()
        rev.save = MagicMock()

        deal = MagicMock()
        deal.name = "DEAL-A"
        deal.status = "Approved"
        deal.container = "C1"
        deal.lot_no = "L1"
        deal.qty = 10
        deal.flags = MagicMock()
        deal.set = MagicMock()
        deal.save = MagicMock()

        approval = MagicMock()
        approval.name = "APR-1"
        approval.deal = approval_deal
        approval.decision = decision
        return rev, deal, approval

    def _run(self, rev, deal, approval, roles, user="appr@x.com"):
        import frappe
        from fresko_universe import deals as deals_mod

        self._as(user, roles)
        docs = {
            ("Fresko Revision", rev.name): rev,
            ("Fresko Deal", deal.name): deal,
            ("Fresko Approval", approval.name): approval,
        }

        def get_doc(dt, name=None):
            if isinstance(dt, dict):
                return MagicMock()
            return docs[(dt, name)]

        frappe.get_doc = MagicMock(side_effect=get_doc)
        frappe.db.exists = MagicMock(return_value=True)
        frappe.db.commit = MagicMock()
        frappe.get_all = MagicMock(return_value=[])
        deals_mod.available_to_sell = MagicMock(return_value=1000)
        return deals_mod.apply_revision(rev.name, approval_name=approval.name)

    def test_apply_revision_rejects_non_approver(self):
        rev, deal, approval = self._fixtures()
        with self.assertRaises(Exception) as ctx:
            self._run(rev, deal, approval, ["Fresko Salesperson"], user="sp@x.com")
        self.assertIn("Not permitted", str(ctx.exception))

    def test_apply_revision_rejects_mismatched_approval_deal(self):
        rev, deal, approval = self._fixtures(approval_deal="DEAL-OTHER")
        with self.assertRaises(Exception) as ctx:
            self._run(rev, deal, approval, ["Fresko Approver"])
        msg = str(ctx.exception)
        self.assertTrue("DEAL-OTHER" in msg or "not DEAL-A" in msg or "bound" in msg)

    def test_apply_revision_rejects_reject_decision(self):
        rev, deal, approval = self._fixtures(decision="REJECT")
        with self.assertRaises(Exception) as ctx:
            self._run(rev, deal, approval, ["Fresko Approver"])
        self.assertIn("REJECT", str(ctx.exception))

    def test_apply_revision_approver_bound_ok(self):
        rev, deal, approval = self._fixtures()
        result = self._run(rev, deal, approval, ["Fresko Approver"])
        self.assertEqual(result["status"], "Applied")
        self.assertEqual(result["approval_reference"], approval.name)


class TestFSEC003DealPermissionHooks(unittest.TestCase):
    """FSEC-003: has_permission / permission_query scoping."""

    def test_salesperson_cannot_write_foreign_or_locked_deal(self):
        import frappe
        from fresko_universe.permissions import deal_has_permission

        frappe.session = types.SimpleNamespace(user="sp@x.com")
        frappe.get_roles = MagicMock(return_value=["Fresko Salesperson"])

        foreign = MagicMock(owner="other@x.com", salesperson_user=None, status="Proposed")
        self.assertFalse(deal_has_permission(foreign, "write", "sp@x.com"))

        own_locked = MagicMock(owner="sp@x.com", salesperson_user=None, status="Approved")
        self.assertFalse(deal_has_permission(own_locked, "write", "sp@x.com"))

        own_proposed = MagicMock(owner="sp@x.com", salesperson_user=None, status="Proposed")
        self.assertTrue(deal_has_permission(own_proposed, "write", "sp@x.com"))

    def test_accounts_read_only_on_deal(self):
        import frappe
        from fresko_universe.permissions import deal_has_permission

        frappe.get_roles = MagicMock(return_value=["Fresko Accounts"])
        deal = MagicMock(owner="x", salesperson_user=None, status="Proposed")
        self.assertTrue(deal_has_permission(deal, "read", "acc@x.com"))
        self.assertFalse(deal_has_permission(deal, "write", "acc@x.com"))

    def test_permission_query_scopes_two_sales_users(self):
        import frappe
        from fresko_universe.permissions import deal_permission_query

        frappe.get_roles = MagicMock(return_value=["Fresko Salesperson"])
        frappe.db.escape = lambda v, percent=True: "'%s'" % v
        q_a = deal_permission_query("sales_a@x.com")
        q_b = deal_permission_query("sales_b@x.com")
        self.assertIn("sales_a@x.com", q_a)
        self.assertIn("sales_b@x.com", q_b)
        self.assertNotEqual(q_a, q_b)
        self.assertIn("salesperson_user", q_a)

    def test_approver_query_unrestricted(self):
        import frappe
        from fresko_universe.permissions import deal_permission_query

        frappe.get_roles = MagicMock(return_value=["Fresko Approver"])
        self.assertEqual(deal_permission_query("appr@x.com"), "")

    def test_hooks_register_permission_maps(self):
        hooks_py = (ROOT / "fresko_universe" / "hooks.py").read_text()
        self.assertIn("permission_query_conditions", hooks_py)
        self.assertIn("deal_has_permission", hooks_py)
        self.assertIn("evidence_has_permission", hooks_py)
        self.assertIn("deal_permission_query", hooks_py)


if __name__ == "__main__":
    unittest.main()
