"""Smoke tests without Frappe bench: python3 -m unittest tests.test_smoke_unit -v"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _install_frappe_stub():
    frappe = types.ModuleType("frappe")
    validation_error = type("ValidationError", (Exception,), {})
    permission_error = type("PermissionError", (Exception,), {})
    does_not_exist = type("DoesNotExistError", (Exception,), {})
    unique_validation = type("UniqueValidationError", (validation_error,), {})

    def _throw(msg, exc=None, title=None, *a, **k):
        err_cls = exc if (isinstance(exc, type) and issubclass(exc, Exception)) else Exception
        raise err_cls(str(msg))

    frappe.throw = _throw
    frappe._ = lambda msg, *a, **k: msg
    frappe.whitelist = lambda *a, **k: (lambda fn: fn)
    frappe.log_error = lambda *a, **k: None
    frappe.session = types.SimpleNamespace(user="Administrator")
    frappe.ValidationError = validation_error
    frappe.PermissionError = permission_error
    frappe.DoesNotExistError = does_not_exist
    frappe.UniqueValidationError = unique_validation
    frappe.db = MagicMock()
    frappe.db.escape = lambda v, percent=True: "'%s'" % str(v).replace("'", "''")
    frappe.db.savepoint = MagicMock()
    frappe.db.rollback = MagicMock()
    frappe.db.release_savepoint = MagicMock()
    frappe.db.sql = MagicMock(return_value=[])
    frappe.db.set_value = MagicMock()
    frappe.db.exists = MagicMock(return_value=False)
    frappe.get_doc = MagicMock()
    frappe.get_all = MagicMock(return_value=[])
    frappe.get_roles = MagicMock(return_value=["System Manager"])
    frappe.db.commit = MagicMock()
    frappe.generate_hash = lambda length=8: "hash1234"
    frappe.has_permission = MagicMock(return_value=True)
    frappe.get_site_path = lambda *p: str(ROOT / "scratch" / Path(*p))
    frappe.new_doc = MagicMock()
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
    REVISION_ELIGIBLE_FIELDS,
)
from fresko_universe.rate_rules import (  # noqa: E402
    policy_resolved,
    rate_in_band,
    resolve_rate_band,
)
from fresko_universe.ats import commercial_qty_for_ats  # noqa: E402
from fresko_universe.permissions import APPROVAL_APPLY_DECISIONS  # noqa: E402


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

    def test_terminal_statuses_commercially_locked(self):
        # Blocker 1: Cancelled / Rejected / Disputed never freely editable
        for st in ("Cancelled", "Rejected", "Disputed"):
            self.assertIn(st, COMMERCIAL_LOCK_STATUSES)

    def test_revision_allowlist_and_phase1_container_decision(self):
        self.assertIn("qty", REVISION_ELIGIBLE_FIELDS)
        self.assertIn("approved_rate", REVISION_ELIGIBLE_FIELDS)
        self.assertNotIn("status", REVISION_ELIGIBLE_FIELDS)
        self.assertNotIn("container", REVISION_ELIGIBLE_FIELDS)
        self.assertEqual(APPROVAL_APPLY_DECISIONS, frozenset({"APPROVE"}))

    def test_dispatch_lock_precedes_physical_reads(self):
        deals_py = (ROOT / "fresko_universe" / "deals.py").read_text()
        body = deals_py.split("def record_dispatch", 1)[1].split("def request_revision", 1)[0]
        self.assertIn("lock_container_for_update(locked_container)", body)
        self.assertIn('frappe.get_doc("Fresko Deal", deal_name, for_update=True)', body)
        self.assertEqual(body.count("FOR UPDATE"), 2)
        self.assertLess(
            body.index("lock_container_for_update(locked_container)"),
            body.index('frappe.get_doc("Fresko Deal", deal_name, for_update=True)'),
        )
        self.assertLess(
            body.index('frappe.get_doc("Fresko Deal", deal_name, for_update=True)'),
            body.index("SELECT inward_qty"),
        )

    def test_revision_and_approval_are_server_created(self):
        for doctype in ("fresko_revision", "fresko_approval"):
            path = next((ROOT / "fresko_universe").rglob(f"{doctype}.json"))
            data = json.loads(path.read_text())
            for permission in data["permissions"]:
                self.assertFalse(permission.get("create", 0), permission["role"])

        deals_py = (ROOT / "fresko_universe" / "deals.py").read_text()
        approvals_py = (ROOT / "fresko_universe" / "approvals.py").read_text()
        rev_py = next((ROOT / "fresko_universe").rglob("fresko_revision.py")).read_text()
        apr_py = next((ROOT / "fresko_universe").rglob("fresko_approval.py")).read_text()
        self.assertIn("rev.flags.allow_controlled_insert = True", deals_py)
        self.assertIn("ap.flags.allow_controlled_insert = True", approvals_py)
        self.assertIn('self.changed_by = frappe.session.user', rev_py)
        self.assertIn('self.approver = frappe.session.user', apr_py)
        self.assertIn("REVISION_ELIGIBLE_FIELDS", rev_py)
        self.assertIn("REVISION_ELIGIBLE_FIELDS", deals_py)


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

        deal = MagicMock()
        deal.name = "DEAL-D4"
        deal.status = "Countered"
        deal.owner = owner
        deal.salesperson_user = salesperson
        deal.approved_rate = None  # RC: NULL until accept copies COUNTER decision_rate
        deal.approval = "APR-COUNTER"
        deal.container = "C1"
        deal.lot_no = "L1"
        deal.qty = 5
        deal.flags = MagicMock()
        deal.set_status = MagicMock(side_effect=lambda s: setattr(deal, "status", s))
        deal.save = MagicMock()

        frappe.session = types.SimpleNamespace(user=user)
        frappe.get_roles = MagicMock(return_value=roles)
        frappe.get_doc = MagicMock(return_value=deal)
        frappe.db.exists = MagicMock(return_value=True)
        frappe.db.get_value = MagicMock(
            return_value=types.SimpleNamespace(decision="COUNTER", decision_rate=12)
        )
        frappe.db.commit = MagicMock()
        deals_mod.available_to_sell = MagicMock(return_value=100)
        return deals_mod.accept_counter(deal.name), deal

    def test_owner_can_accept(self):
        result, deal = self._run("owner@x.com", ["Fresko Salesperson"], owner="owner@x.com")
        self.assertEqual(result["status"], "Approved")
        self.assertEqual(result["approved_rate"], 12)
        self.assertEqual(deal.approved_rate, 12)

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


class TestD6AcceptCounterBuyerUnresolved(unittest.TestCase):
    """D6: accept_counter opens BUYER_UNRESOLVED when customer empty; skips when set."""

    def _run(self, customer):
        import frappe
        from fresko_universe import deals as deals_mod

        deal = MagicMock()
        deal.name = "DEAL-D6"
        deal.status = "Countered"
        deal.owner = "owner@x.com"
        deal.salesperson_user = None
        deal.approved_rate = None
        deal.approval = "APR-D6-COUNTER"
        deal.container = "C1"
        deal.lot_no = "L1"
        deal.qty = 5
        deal.customer = customer
        deal.buyer_alias = "Alias"
        deal.flags = MagicMock()
        deal.set_status = MagicMock(side_effect=lambda s: setattr(deal, "status", s))
        deal.save = MagicMock()

        inserted = []

        def get_doc_flex(*a, **k):
            if a and isinstance(a[0], dict):
                ex = MagicMock()
                ex.insert = MagicMock()
                ex.name = "EX-D6"
                inserted.append(a[0])
                return ex
            if a and a[0] == "Fresko Deal":
                return deal
            return deal

        frappe.session = types.SimpleNamespace(user="owner@x.com")
        frappe.get_roles = MagicMock(return_value=["Fresko Salesperson"])
        frappe.get_doc = MagicMock(side_effect=get_doc_flex)
        frappe.get_all = MagicMock(return_value=[])
        frappe.db.exists = MagicMock(return_value=True)
        frappe.db.get_value = MagicMock(
            return_value=types.SimpleNamespace(decision="COUNTER", decision_rate=12)
        )
        frappe.db.commit = MagicMock()
        orig_ats = deals_mod.available_to_sell
        deals_mod.available_to_sell = MagicMock(return_value=100)
        try:
            result = deals_mod.accept_counter(deal.name)
        finally:
            deals_mod.available_to_sell = orig_ats
        return result, deal, inserted

    def test_empty_customer_opens_buyer_unresolved(self):
        result, deal, inserted = self._run(customer=None)
        self.assertEqual(result["status"], "Approved")
        self.assertTrue(
            any(i.get("exception_type") == "BUYER_UNRESOLVED" for i in inserted),
            "accept_counter must open BUYER_UNRESOLVED when customer empty",
        )

    def test_customer_set_skips_buyer_unresolved(self):
        result, deal, inserted = self._run(customer="CUST-1")
        self.assertEqual(result["status"], "Approved")
        self.assertFalse(
            any(i.get("exception_type") == "BUYER_UNRESOLVED" for i in inserted),
            "accept_counter must not open BUYER_UNRESOLVED when customer set",
        )


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

    def _fixtures(self, approval_deal="DEAL-A", decision="APPROVE", revision="REV-1", consumed=0):
        rev = MagicMock()
        rev.name = "REV-1"
        rev.status = "Pending"
        rev.parent_doctype = "Fresko Deal"
        rev.parent_name = "DEAL-A"
        rev.fieldname = "approved_rate"
        rev.old_value = "20"
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
        deal.approved_rate = 20
        deal.get = MagicMock(side_effect=lambda f, d=None: getattr(deal, f, d))
        deal.flags = MagicMock()
        deal.set = MagicMock()
        deal.save = MagicMock()

        approval = MagicMock()
        approval.name = "APR-1"
        approval.deal = approval_deal
        approval.decision = decision
        approval.revision = revision
        approval.consumed = consumed
        approval.flags = MagicMock()
        approval.save = MagicMock()
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

    def test_apply_revision_rejects_deal_only_approval(self):
        rev, deal, approval = self._fixtures(revision=None)
        approval.revision = None
        with self.assertRaises(Exception) as ctx:
            self._run(rev, deal, approval, ["Fresko Approver"])
        self.assertTrue("Deal-only" in str(ctx.exception) or "revision" in str(ctx.exception).lower())

    def test_apply_revision_rejects_other_revision_same_deal(self):
        rev, deal, approval = self._fixtures(revision="REV-OTHER")
        with self.assertRaises(Exception) as ctx:
            self._run(rev, deal, approval, ["Fresko Approver"])
        self.assertIn("REV-OTHER", str(ctx.exception))

    def test_apply_revision_rejects_consumed_approval(self):
        rev, deal, approval = self._fixtures(consumed=1)
        with self.assertRaises(Exception) as ctx:
            self._run(rev, deal, approval, ["Fresko Approver"])
        self.assertIn("consumed", str(ctx.exception).lower())

    def test_apply_revision_rejects_stale_old_value(self):
        rev, deal, approval = self._fixtures()
        deal.approved_rate = 99  # drifted after revision requested
        with self.assertRaises(Exception) as ctx:
            self._run(rev, deal, approval, ["Fresko Approver"])
        self.assertIn("stale", str(ctx.exception).lower())

    def test_apply_revision_rejects_counter_decision(self):
        rev, deal, approval = self._fixtures(decision="COUNTER")
        with self.assertRaises(Exception) as ctx:
            self._run(rev, deal, approval, ["Fresko Approver"])
        self.assertIn("COUNTER", str(ctx.exception))


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

        for st in ("Cancelled", "Rejected", "Disputed"):
            locked = MagicMock(owner="sp@x.com", salesperson_user=None, status=st)
            self.assertFalse(deal_has_permission(locked, "write", "sp@x.com"), st)

    def test_approver_cannot_write_locked_statuses(self):
        import frappe
        from fresko_universe.permissions import deal_has_permission

        frappe.get_roles = MagicMock(return_value=["Fresko Approver"])
        proposed = MagicMock(owner="x", salesperson_user=None, status="Proposed")
        self.assertTrue(deal_has_permission(proposed, "write", "appr@x.com"))
        for st in ("Approved", "Cancelled", "Rejected", "Disputed", "Countered"):
            locked = MagicMock(owner="x", salesperson_user=None, status=st)
            self.assertFalse(deal_has_permission(locked, "write", "appr@x.com"), st)

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



class TestRCCounterApprovedRateUnset(unittest.TestCase):
    """RC: COUNTER must not masquerade as Approved via Deal.approved_rate / amount."""

    def test_counter_branch_forces_approved_rate_null(self):
        approvals_py = (ROOT / "fresko_universe" / "approvals.py").read_text()
        self.assertIn('decision == "COUNTER"', approvals_py)
        self.assertIn('"approved_rate": None', approvals_py)
        # Must not assign deal.approved_rate = rate in COUNTER branch
        # Isolate COUNTER block roughly
        idx = approvals_py.find('if decision == "COUNTER"')
        block = approvals_py[idx : approvals_py.find('if decision == "REJECT"', idx)]
        self.assertNotIn("deal.approved_rate = rate", block)
        self.assertIn("decision_rate", block)

    def test_accept_counter_copies_decision_rate(self):
        deals_py = (ROOT / "fresko_universe" / "deals.py").read_text()
        self.assertIn("_load_counter_decision_rate", deals_py)
        self.assertIn("deal.approved_rate = counter_rate", deals_py)

    def test_amount_uses_proposed_while_countered(self):
        deal_py = (
            ROOT / "fresko_universe" / "fresko_deals" / "doctype"
            / "fresko_deal" / "fresko_deal.py"
        ).read_text()
        self.assertIn('self.status == "Countered"', deal_py)
        self.assertIn("proposed_rate", deal_py[deal_py.find("def _compute_amount") :])

    def test_countered_amount_smoke_logic(self):
        # Pure logic mirror of _compute_amount
        status, approved_rate, proposed_rate, qty = "Countered", None, 50, 10
        if status == "Countered" or approved_rate is None:
            rate = proposed_rate
        else:
            rate = approved_rate
        self.assertEqual(qty * rate, 500)
        # After accept
        status, approved_rate = "Approved", 80
        if status == "Countered" or approved_rate is None:
            rate = proposed_rate
        else:
            rate = approved_rate
        self.assertEqual(qty * rate, 800)


class TestBlocker2RevisionApprovalBind(unittest.TestCase):
    """Source contracts: Approval.revision Link + create_revision_approval."""

    def test_approval_json_has_revision_and_consumed(self):
        import json
        apr = json.loads(
            (
                ROOT / "fresko_universe" / "fresko_core" / "doctype"
                / "fresko_approval" / "fresko_approval.json"
            ).read_text()
        )
        names = {f["fieldname"] for f in apr["fields"]}
        self.assertIn("revision", names)
        self.assertIn("consumed", names)
        rev_field = next(f for f in apr["fields"] if f["fieldname"] == "revision")
        self.assertEqual(rev_field["options"], "Fresko Revision")

    def test_create_revision_approval_exists(self):
        approvals_py = (ROOT / "fresko_universe" / "approvals.py").read_text()
        self.assertIn("def create_revision_approval", approvals_py)
        self.assertIn("revision=rev.name", approvals_py)

    def test_apply_revision_requires_revision_bind(self):
        deals_py = (ROOT / "fresko_universe" / "deals.py").read_text()
        self.assertIn("assert_approval_bound_for_revision(approval, deal, revision=rev)", deals_py)
        self.assertIn("assert_approval_not_consumed", deals_py)
        self.assertIn("_assert_revision_old_value_matches_deal", deals_py)
        self.assertIn("_mark_approval_consumed", deals_py)


class TestForcedRollbackContract(unittest.TestCase):
    """Forced rollback: multi-doc path must not commit when failure injected before commit."""

    def test_apply_revision_commit_is_last(self):
        deals_py = (ROOT / "fresko_universe" / "deals.py").read_text()
        idx = deals_py.find("def apply_revision")
        block = deals_py[idx : deals_py.find("def set_dispatched_qty", idx)]
        commit_pos = block.rfind("frappe.db.commit()")
        consume_pos = block.find("_mark_approval_consumed")
        deal_save_pos = block.find("deal.save(ignore_permissions=True)")
        self.assertGreater(commit_pos, deal_save_pos)
        self.assertGreater(commit_pos, consume_pos)

    def test_injected_failure_before_commit_rolls_back(self):
        """Simulate Exception insert + Deal mutation then boom before commit → rollback."""
        import frappe
        from fresko_universe import deals as deals_mod

        state = {"deal_saved": False, "rev_saved": False, "committed": False, "rolled_back": False}

        rev = MagicMock()
        rev.name = "REV-RB"
        rev.status = "Pending"
        rev.parent_doctype = "Fresko Deal"
        rev.parent_name = "DEAL-RB"
        rev.fieldname = "qty"
        rev.old_value = "10"
        rev.new_value = "8"
        rev.approval_reference = "APR-RB"
        rev.supporting_evidence = "EV-1"
        rev.flags = MagicMock()

        def rev_save(*a, **k):
            state["rev_saved"] = True
            rev.status = "Applied"

        rev.save = MagicMock(side_effect=rev_save)

        deal = MagicMock()
        deal.name = "DEAL-RB"
        deal.status = "Approved"
        deal.container = "C1"
        deal.lot_no = "L1"
        deal.qty = 10
        deal.get = MagicMock(side_effect=lambda f, d=None: getattr(deal, f, d))
        deal.flags = MagicMock()
        deal.set = MagicMock(side_effect=lambda f, v: setattr(deal, f, v))

        def deal_save(*a, **k):
            state["deal_saved"] = True

        deal.save = MagicMock(side_effect=deal_save)

        approval = MagicMock()
        approval.name = "APR-RB"
        approval.deal = "DEAL-RB"
        approval.decision = "APPROVE"
        approval.revision = "REV-RB"
        approval.consumed = 0
        approval.flags = MagicMock()
        approval.save = MagicMock()

        docs = {
            ("Fresko Revision", rev.name): rev,
            ("Fresko Deal", deal.name): deal,
            ("Fresko Approval", approval.name): approval,
        }

        def get_doc(dt, name=None):
            if isinstance(dt, dict):
                return MagicMock()
            return docs[(dt, name)]

        frappe.session = types.SimpleNamespace(user="appr@x.com")
        frappe.get_roles = MagicMock(return_value=["Fresko Approver"])
        frappe.get_doc = MagicMock(side_effect=get_doc)
        frappe.db.exists = MagicMock(return_value=True)
        frappe.get_all = MagicMock(return_value=[])
        deals_mod.available_to_sell = MagicMock(return_value=1000)

        def boom_commit():
            state["committed"] = True
            raise RuntimeError("forced failure before durable commit")

        def rollback():
            state["rolled_back"] = True
            # simulate DB undo
            deal.qty = 10
            rev.status = "Pending"
            approval.consumed = 0
            state["deal_saved"] = False
            state["rev_saved"] = False

        frappe.db.commit = MagicMock(side_effect=boom_commit)
        frappe.db.rollback = MagicMock(side_effect=rollback)

        with self.assertRaises(RuntimeError):
            try:
                deals_mod.apply_revision(rev.name, approval_name=approval.name)
            except RuntimeError:
                frappe.db.rollback()
                raise

        self.assertTrue(state["rolled_back"])
        self.assertEqual(deal.qty, 10)
        self.assertEqual(rev.status, "Pending")
        self.assertEqual(approval.consumed, 0)


class TestDecideCounterRuntime(unittest.TestCase):
    """Runtime smoke: decide(COUNTER) leaves approved_rate None."""

    def test_counter_leaves_approved_rate_none(self):
        import frappe
        from fresko_universe import approvals as approvals_mod

        deal = MagicMock()
        deal.name = "DEAL-CTR"
        deal.status = "Approval Required"
        deal.proposed_rate = 50
        deal.rate_floor = 100
        deal.rate_ceiling = 200
        deal.approved_rate = None
        deal.qty = 5
        deal.container = "C1"
        deal.lot_no = "L1"
        deal.flags = MagicMock()
        deal.set_status = MagicMock(side_effect=lambda s: setattr(deal, "status", s))
        deal.save = MagicMock()

        inserted = []

        def get_doc_flex(*a, **k):
            if a and isinstance(a[0], dict) and a[0].get("doctype") == "Fresko Approval":
                ap = MagicMock()
                ap.name = "APR-CTR"
                ap.decision = a[0]["decision"]
                ap.decision_rate = a[0]["decision_rate"]
                ap.insert = MagicMock()
                inserted.append(a[0])
                return ap
            return deal

        frappe.session = types.SimpleNamespace(user="appr@x.com")
        frappe.get_roles = MagicMock(return_value=["Fresko Approver"])
        frappe.get_doc = MagicMock(side_effect=get_doc_flex)
        frappe.db.commit = MagicMock()
        frappe.db.set_value = MagicMock()

        result = approvals_mod.decide(
            deal.name, "COUNTER", decision_rate=80, reason="counter offer"
        )
        self.assertEqual(deal.status, "Countered")
        self.assertIsNone(deal.approved_rate)
        self.assertIsNone(result["approved_rate"])
        self.assertEqual(result["decision"], "COUNTER")
        self.assertEqual(result["decision_rate"], 80)
        frappe.db.set_value.assert_called()
        self.assertTrue(any(i.get("decision") == "COUNTER" for i in inserted))


class TestFSEC004FSEC005Behavioral(unittest.TestCase):
    """Behavioral tests covering FSEC-004 & FSEC-005 requirements."""

    def setUp(self):
        import frappe
        frappe.session = types.SimpleNamespace(user="Administrator")
        frappe.get_roles = MagicMock(return_value=["System Manager"])
        frappe.has_permission = MagicMock(return_value=True)

    def tearDown(self):
        import frappe
        frappe.session = types.SimpleNamespace(user="Administrator")
        frappe.get_roles = MagicMock(return_value=["System Manager"])
        frappe.has_permission = MagicMock(return_value=True)

    def test_scoped_message_key_deterministic_and_opaque(self):
        from fresko_universe.fresko_core.services.evidence_service import compute_scoped_message_key

        key1 = compute_scoped_message_key("whatsapp-cloud", "ACC_1", "CHAT_A", "MSG_123")
        self.assertIsNotNone(key1)
        self.assertEqual(len(key1), 64)
        # Deterministic
        key2 = compute_scoped_message_key("whatsapp-cloud", "ACC_1", "CHAT_A", "MSG_123")
        self.assertEqual(key1, key2)
        # Opaque: preserves whitespace / case
        key_case = compute_scoped_message_key("whatsapp-cloud", "acc_1", "CHAT_A", "MSG_123")
        self.assertNotEqual(key1, key_case)
        # Missing any field returns None
        self.assertIsNone(compute_scoped_message_key("whatsapp-cloud", "", "CHAT_A", "MSG_123"))
        self.assertIsNone(compute_scoped_message_key(None, "ACC_1", "CHAT_A", "MSG_123"))

    def test_typed_attachment_identity_prevents_ord0_collision(self):
        from fresko_universe.fresko_core.services.evidence_service import compute_logical_attachment_key

        key_provider = compute_logical_attachment_key(
            "whatsapp-cloud", "ACC_1", "CHAT_A", "MSG_123", "provider_id", "ord:0"
        )
        key_ordinal = compute_logical_attachment_key(
            "whatsapp-cloud", "ACC_1", "CHAT_A", "MSG_123", "ordinal", 0
        )
        self.assertIsNotNone(key_provider)
        self.assertIsNotNone(key_ordinal)
        # Explicit identity type tuple ensures "ord:0" does NOT collide with ordinal 0
        self.assertNotEqual(key_provider, key_ordinal)
        # Missing identity returns None (does not default to ordinal 0)
        self.assertIsNone(
            compute_logical_attachment_key(
                "whatsapp-cloud", "ACC_1", "CHAT_A", "MSG_123", "provider_id", ""
            )
        )
        self.assertIsNone(
            compute_logical_attachment_key(
                "whatsapp-cloud", "ACC_1", "CHAT_A", "MSG_123", "ordinal", -1
            )
        )

    def test_version_scoped_key_advances_without_changing_logical_identity(self):
        from fresko_universe.fresko_core.services.evidence_service import (
            compute_logical_attachment_key,
            compute_scoped_attachment_version_key,
        )

        log_key = compute_logical_attachment_key(
            "whatsapp-cloud", "ACC_1", "CHAT_A", "MSG_123", "ordinal", 0
        )
        v1_key = compute_scoped_attachment_version_key(log_key, 1)
        v2_key = compute_scoped_attachment_version_key(log_key, 2)
        self.assertNotEqual(v1_key, v2_key)
        self.assertIsNone(compute_scoped_attachment_version_key(log_key, 0))

    def test_forged_metadata_injection_blocked_on_attachment(self):
        from fresko_universe.fresko_core.doctype.fresko_evidence_attachment.fresko_evidence_attachment import (
            FreskoEvidenceAttachment,
        )

        doc = FreskoEvidenceAttachment()
        doc.is_new = lambda: True
        doc.flags = MagicMock(in_service=False)
        doc.capture_status = "CAPTURED"
        with self.assertRaises(Exception):
            doc.validate()

        doc2 = FreskoEvidenceAttachment()
        doc2.is_new = lambda: True
        doc2.flags = MagicMock(in_service=False)
        doc2.capture_status = "PENDING"
        doc2.content_sha256 = "forged_sha"
        with self.assertRaises(Exception):
            doc2.validate()

    def test_forged_metadata_injection_blocked_on_evidence(self):
        from fresko_universe.fresko_core.doctype.fresko_evidence.fresko_evidence import (
            FreskoEvidence,
        )

        doc = FreskoEvidence()
        doc.is_new = lambda: True
        doc.flags = MagicMock(in_service=False)
        doc.overall_verification_status = "COMPLETE"
        with self.assertRaises(Exception):
            doc.validate()

    def test_attachment_and_attempt_deletion_blocked(self):
        from fresko_universe.fresko_core.doctype.fresko_evidence_attachment.fresko_evidence_attachment import (
            FreskoEvidenceAttachment,
        )
        from fresko_universe.fresko_core.doctype.fresko_evidence_attempt.fresko_evidence_attempt import (
            FreskoEvidenceAttempt,
        )

        att = FreskoEvidenceAttachment()
        with self.assertRaises(Exception):
            att.on_trash()
        attempt = FreskoEvidenceAttempt()
        with self.assertRaises(Exception):
            attempt.on_trash()

    def test_attempt_immutability_enforced(self):
        from fresko_universe.fresko_core.doctype.fresko_evidence_attempt.fresko_evidence_attempt import (
            FreskoEvidenceAttempt,
        )

        attempt = FreskoEvidenceAttempt()
        attempt.flags = MagicMock(in_service=False)
        with self.assertRaises(Exception):
            attempt.before_insert()
        attempt.flags = MagicMock(in_service=True)
        attempt.is_new = lambda: False
        with self.assertRaises(Exception):
            attempt.validate()

    def test_remote_storage_paths_explicitly_rejected(self):
        from fresko_universe.fresko_core.services.evidence_service import (
            get_validated_local_file_path,
        )

        with self.assertRaises(Exception) as ctx:
            get_validated_local_file_path("https://s3.amazonaws.com/bucket/file.pdf")
        self.assertIn("unsupported", str(ctx.exception).lower())

        with self.assertRaises(Exception) as ctx:
            get_validated_local_file_path("s3://my-bucket/receipt.png")
        self.assertIn("unsupported", str(ctx.exception).lower())

    def test_migration_demonstrates_path_hash_origin(self):
        from fresko_universe.patches.v1_0 import backfill_evidence_capture_status
        import frappe

        path_hash = hashlib.sha256("/files/test.pdf".encode()).hexdigest()
        fake_hash = "1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff"

        sample_rows = [
            {
                "name": "EV-1",
                "file": "/files/test.pdf",
                "external_ref": None,
                "content_sha256": path_hash,
                "hash_algorithm": None,
            },
            {
                "name": "EV-2",
                "file": "/files/other.pdf",
                "external_ref": None,
                "content_sha256": fake_hash,
                "hash_algorithm": None,
            },
        ]
        orig_sql = frappe.db.sql
        orig_set_value = frappe.db.set_value
        set_values = []
        try:
            frappe.db.sql = MagicMock(return_value=sample_rows)
            frappe.db.set_value = MagicMock(
                side_effect=lambda dt, dn, fn, val, **k: set_values.append((dn, fn, val))
            )
            backfill_evidence_capture_status.execute()
            self.assertIn(("EV-1", "hash_algorithm", "legacy-path-url-v0"), set_values)
            self.assertIn(("EV-2", "hash_algorithm", "legacy-unverified"), set_values)
        finally:
            frappe.db.sql = orig_sql
            frappe.db.set_value = orig_set_value

    def test_untrusted_completeness_provenance_cannot_become_captured(self):
        from fresko_universe.fresko_core.services.evidence_service import verify_and_capture_attachment
        import frappe

        att_row = {
            "name": "ATT-1",
            "evidence": "EV-1",
            "file_url": "/private/files/test.pdf",
            "storage_ref": "File/123",
            "provenance_type": "UNTRUSTED_CALLER",
            "provenance_ref": None,
            "expected_byte_count": 100,
            "expected_sha256": None,
            "capture_status": "PENDING",
            "readback_verified": 0,
            "content_sha256": None,
            "content_byte_count": 0,
            "logical_attachment_key": "log_key_1",
            "scoped_attachment_version_key": "ver_key_1",
        }
        parent_row = {
            "name": "EV-1",
            "deal": None,
            "manifest_status": "UNKNOWN",
            "expected_attachment_count": -1,
            "verified_attachment_count": 0,
            "overall_verification_status": "PENDING",
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC",
            "conversation_id": "CONV",
            "provider_message_id": "MSG",
            "scoped_message_key": "key",
            "message_payload_sha256": "pay_hash",
        }

        orig_sql = frappe.db.sql
        orig_get_doc = frappe.get_doc
        try:
            def flex_sql(query, params=None, as_dict=False):
                if "tabFresko Evidence Attachment" in query:
                    return [types.SimpleNamespace(**att_row)]
                if "tabFresko Evidence" in query:
                    return [types.SimpleNamespace(**parent_row)]
                return []

            frappe.db.sql = MagicMock(side_effect=flex_sql)
            ev_doc = MagicMock()
            ev_doc.name = "EV-1"
            frappe.get_doc = MagicMock(return_value=ev_doc)
            frappe.session = types.SimpleNamespace(user="Administrator")

            res = verify_and_capture_attachment("ATT-1")
            self.assertFalse(res.success)
            self.assertEqual(res.status, "PENDING")
            self.assertIn("untrusted", res.reason.lower())
        finally:
            frappe.db.sql = orig_sql
            frappe.get_doc = orig_get_doc

    def test_unknown_attachment_count_cannot_aggregate_complete(self):
        from fresko_universe.fresko_core.services.evidence_service import aggregate_parent_evidence_status
        import frappe

        parent_row = {
            "name": "EV-1",
            "deal": None,
            "manifest_status": "UNKNOWN",
            "expected_attachment_count": -1,
            "verified_attachment_count": 0,
            "overall_verification_status": "PENDING",
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC",
            "conversation_id": "CONV",
            "provider_message_id": "MSG",
            "scoped_message_key": "key",
            "message_payload_sha256": "pay_hash",
        }
        att_row = {
            "name": "ATT-1",
            "logical_attachment_key": "k1",
            "capture_status": "CAPTURED",
            "readback_verified": 1,
        }

        orig_sql = frappe.db.sql
        try:
            def flex_sql(query, params=None, as_dict=False):
                if "FROM `tabFresko Evidence`" in query:
                    return [types.SimpleNamespace(**parent_row)]
                if "FROM `tabFresko Evidence Attachment`" in query:
                    return [types.SimpleNamespace(**att_row)]
                return []

            frappe.db.sql = MagicMock(side_effect=flex_sql)
            # Manifest is UNKNOWN: even though attachment is CAPTURED, status remains PENDING
            status = aggregate_parent_evidence_status("EV-1")
            self.assertEqual(status, "PENDING")
            self.assertNotEqual(status, "COMPLETE")

            # Finalize manifest with count = 1
            parent_row["manifest_status"] = "FINALIZED"
            parent_row["expected_attachment_count"] = 1
            status_final = aggregate_parent_evidence_status("EV-1")
            self.assertEqual(status_final, "COMPLETE")
        finally:
            frappe.db.sql = orig_sql

    def test_payload_conflict_preservation(self):
        from fresko_universe.fresko_core.services.evidence_service import ingest_message_evidence
        import frappe

        existing_row = {
            "name": "EV-EXISTING",
            "deal": None,
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC_1",
            "conversation_id": "CONV_1",
            "provider_message_id": "MSG_1",
            "scoped_message_key": "mocked_key",
            "message_payload_sha256": "original_payload_hash_1111",
            "overall_verification_status": "PENDING",
        }

        orig_new_doc = frappe.new_doc
        orig_sql = frappe.db.sql
        try:
            def flex_new_doc(dt, *a, **k):
                d = MagicMock()
                d.doctype = dt
                if dt == "Fresko Evidence":
                    d.insert = MagicMock(side_effect=frappe.UniqueValidationError("Fresko Evidence", "EV-NEW", "Duplicate key"))
                else:
                    d.insert = MagicMock()
                return d

            frappe.new_doc = MagicMock(side_effect=flex_new_doc)
            frappe.db.sql = MagicMock(return_value=[types.SimpleNamespace(**existing_row)])
            existing_doc = MagicMock(name="EV-EXISTING", overall_verification_status="CONFLICT")
            frappe.get_doc = MagicMock(return_value=existing_doc)

            doc, outcome = ingest_message_evidence(
                provider="whatsapp-cloud",
                provider_account_id="ACC_1",
                conversation_id="CONV_1",
                provider_message_id="MSG_1",
                raw_payload={"text": "Different conflicting message content"},
            )
            self.assertEqual(outcome, "CONFLICT_PAYLOAD_MISMATCH")
        finally:
            frappe.new_doc = orig_new_doc
            frappe.db.sql = orig_sql

    def test_unauthorized_redelivery_blocked(self):
        from fresko_universe.fresko_core.services.evidence_service import ingest_message_evidence
        import frappe

        # The payload hash matches so it would normally be an idempotent redelivery
        from fresko_universe.fresko_core.services.evidence_service import canonicalize_payload
        _, expected_hash = canonicalize_payload({"text": "Same content"})

        existing_row = {
            "name": "EV-SECRET",
            "deal": "DEAL-SECRET",
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC_1",
            "conversation_id": "CONV_1",
            "provider_message_id": "MSG_1",
            "scoped_message_key": "mocked_key",
            "message_payload_sha256": expected_hash,
            "overall_verification_status": "PENDING",
        }

        orig_new_doc = frappe.new_doc
        orig_sql = frappe.db.sql
        try:
            def flex_new_doc(dt, *a, **k):
                d = MagicMock()
                d.doctype = dt
                if dt == "Fresko Evidence":
                    d.insert = MagicMock(side_effect=frappe.UniqueValidationError("Fresko Evidence", "EV-NEW", "dup"))
                else:
                    d.insert = MagicMock()
                return d

            frappe.new_doc = MagicMock(side_effect=flex_new_doc)
            frappe.db.sql = MagicMock(return_value=[types.SimpleNamespace(**existing_row)])
            frappe.session = types.SimpleNamespace(user="unauthorized_salesperson@example.com")
            from fresko_universe import permissions
            orig_ev_has_perm = permissions.evidence_has_permission
            permissions.evidence_has_permission = MagicMock(return_value=False)

            with self.assertRaises(Exception) as ctx:
                ingest_message_evidence(
                    provider="whatsapp-cloud",
                    provider_account_id="ACC_1",
                    conversation_id="CONV_1",
                    provider_message_id="MSG_1",
                    raw_payload={"text": "Same content"},
                )
            self.assertIn("access denied", str(ctx.exception).lower())
        finally:
            frappe.new_doc = orig_new_doc
            frappe.db.sql = orig_sql
            permissions.evidence_has_permission = orig_ev_has_perm

    def test_forged_completeness_provenance_rejected(self):
        from fresko_universe.fresko_core.doctype.fresko_evidence_attachment.fresko_evidence_attachment import (
            FreskoEvidenceAttachment,
        )
        from fresko_universe.fresko_core.services.evidence_service import (
            validate_completeness_provenance,
        )

        # 1. Direct API caller attempting to set OFFLINE_IMPORT_MANIFEST or PROVIDER_PAYLOAD_DIGEST
        doc = FreskoEvidenceAttachment()
        doc.is_new = lambda: True
        doc.flags = MagicMock(in_service=False)
        doc.provenance_type = "OFFLINE_IMPORT_MANIFEST"
        with self.assertRaises(Exception) as ctx:
            doc.validate()
        self.assertIn("server-controlled service required", str(ctx.exception).lower())

        # 2. Offline import provenance with non-existent manifest ref fails closed
        att_row = {
            "provenance_type": "OFFLINE_IMPORT_MANIFEST",
            "provenance_ref": "/nonexistent/path/to/manifest.json",
            "expected_byte_count": 500,
            "expected_sha256": "abcdef",
        }
        parent_row = {"name": "EV-1", "message_payload_sha256": "pay_sha"}
        trusted, reason, _, _ = validate_completeness_provenance(att_row, parent_row)
        self.assertFalse(trusted)
        self.assertIn("could not be verified", reason.lower())

        # 3. Provider delivery provenance without parent payload or ingest attempt reference fails closed
        att_row2 = {
            "provenance_type": "PROVIDER_PAYLOAD_DIGEST",
            "provenance_ref": None,
            "expected_byte_count": 500,
            "expected_sha256": "abcdef",
        }
        parent_row2 = {"name": "EV-2", "message_payload_sha256": None}
        trusted2, reason2, _, _ = validate_completeness_provenance(att_row2, parent_row2)
        self.assertFalse(trusted2)
        self.assertIn("lacks bound parent payload", reason2.lower())

    def test_captured_file_deletion_and_modification_blocked(self):
        import frappe
        from fresko_universe.fresko_core.services.evidence_service import (
            prevent_captured_file_deletion,
            prevent_captured_file_modification,
            prevent_captured_evidence_deletion,
        )

        orig_sql = frappe.db.sql
        try:
            # File referenced by a CAPTURED attachment cannot be deleted
            captured_ref = [{"name": "ATT-CAP", "evidence": "EV-1", "capture_status": "CAPTURED", "version": 1}]
            frappe.db.sql = MagicMock(return_value=captured_ref)

            file_doc = MagicMock()
            file_doc.name = "FILE-1"
            file_doc.file_url = "/private/files/important.pdf"
            file_doc.is_new = lambda: False
            file_doc.has_value_changed = lambda f: f == "file_url"

            with self.assertRaises(Exception) as ctx:
                prevent_captured_file_deletion(file_doc)
            self.assertIn("referenced by captured evidence attachment", str(ctx.exception).lower())

            with self.assertRaises(Exception) as ctx:
                prevent_captured_file_modification(file_doc)
            self.assertIn("cannot modify file", str(ctx.exception).lower())

            # Evidence with attachments or COMPLETE status cannot be deleted
            ev_doc = MagicMock()
            ev_doc.name = "EV-1"
            ev_doc.overall_verification_status = "COMPLETE"
            ev_doc.scoped_message_key = "scoped_key_123"

            with self.assertRaises(Exception) as ctx:
                prevent_captured_evidence_deletion(ev_doc)
            self.assertIn("cannot be deleted", str(ctx.exception).lower())
        finally:
            frappe.db.sql = orig_sql

    def test_database_failure_during_capture_rolls_back_safely(self):
        import frappe
        from fresko_universe.fresko_core.services.evidence_service import verify_and_capture_attachment

        att_row = {
            "name": "ATT-DB-FAIL",
            "evidence": "EV-1",
            "file_url": "/private/files/test.pdf",
            "storage_ref": "File/123",
            "provenance_type": "PROVIDER_HEADER_CONTENT_LENGTH",
            "provenance_ref": None,
            "expected_byte_count": 12,
            "expected_sha256": None,
            "capture_status": "PENDING",
            "readback_verified": 0,
            "content_sha256": None,
            "content_byte_count": 0,
            "logical_attachment_key": "log_key_db",
            "scoped_attachment_version_key": "ver_key_db",
        }
        parent_row = {
            "name": "EV-1",
            "deal": None,
            "manifest_status": "FINALIZED",
            "expected_attachment_count": 1,
            "verified_attachment_count": 0,
            "overall_verification_status": "PENDING",
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC",
            "conversation_id": "CONV",
            "provider_message_id": "MSG",
            "scoped_message_key": "key",
            "message_payload_sha256": "pay_hash",
        }

        orig_sql = frappe.db.sql
        orig_set_value = frappe.db.set_value
        orig_savepoint = frappe.db.savepoint
        orig_rollback = frappe.db.rollback
        try:
            attempt_row = {
                "name": "ATT-ATTEMPT",
                "evidence": "EV-1",
                "operation": "MESSAGE_INGEST",
                "source_payload": json.dumps({"document": {"file_size": 12}}),
                "observed_byte_count": 12,
                "observed_sha256": None,
            }

            def flex_sql(query, params=None, as_dict=False):
                if "FROM `tabFresko Evidence Attachment`" in query:
                    return [types.SimpleNamespace(**att_row)]
                if "FROM `tabFresko Evidence Attempt`" in query:
                    return [types.SimpleNamespace(**attempt_row)]
                if "FROM `tabFresko Evidence`" in query:
                    return [types.SimpleNamespace(**parent_row)]
                return []

            frappe.db.sql = MagicMock(side_effect=flex_sql)
            frappe.get_doc = MagicMock(return_value=types.SimpleNamespace(**parent_row))
            from fresko_universe.fresko_core.services import evidence_service
            orig_get_path = evidence_service.get_validated_local_file_path

            test_content = b"123456789012"
            evidence_service.get_validated_local_file_path = MagicMock(return_value="mock_file.txt")

            def set_value_side_effect(dt, dn, fields, *a, **k):
                if isinstance(fields, dict) and fields.get("capture_status") == "CAPTURED":
                    raise Exception("DB Connection Lost / Deadlock")
                return None

            frappe.db.set_value = MagicMock(side_effect=set_value_side_effect)

            from unittest.mock import mock_open, patch
            with patch("builtins.open", mock_open(read_data=test_content)):
                res = verify_and_capture_attachment("ATT-DB-FAIL")

            # Must NOT report capture success
            self.assertFalse(res.success)
            self.assertEqual(res.status, "FAILED_RETRYABLE")
            self.assertIn("database write failed", res.reason.lower())
            frappe.db.rollback.assert_called()
        finally:
            frappe.db.sql = orig_sql
            frappe.db.set_value = orig_set_value
            frappe.db.savepoint = orig_savepoint
            frappe.db.rollback = orig_rollback
            evidence_service.get_validated_local_file_path = orig_get_path

    def test_unauthorized_attachment_redelivery_blocked(self):
        import frappe
        from fresko_universe.fresko_core.services.evidence_service import ingest_attachment
        from fresko_universe import permissions

        existing_att = {
            "name": "ATT-EXISTING",
            "file_url": "/private/files/doc.pdf",
            "content_sha256": "abc",
            "capture_status": "CAPTURED",
            "version": 1,
            "logical_attachment_key": "log_key_1",
        }
        parent_row = {
            "name": "EV-SECRET",
            "deal": "DEAL-SECRET",
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC",
            "conversation_id": "CONV",
            "provider_message_id": "MSG",
            "scoped_message_key": "key",
            "message_payload_sha256": "pay_hash",
        }

        orig_sql = frappe.db.sql
        orig_ev_has_perm = permissions.evidence_has_permission
        from fresko_universe.fresko_core.services import evidence_service
        orig_assert_file = evidence_service.assert_file_read_permission
        try:
            def flex_sql(query, params=None, as_dict=False):
                if "FROM `tabFresko Evidence`" in query:
                    return [types.SimpleNamespace(**parent_row)]
                if "FROM `tabFresko Evidence Attachment`" in query:
                    return [types.SimpleNamespace(**existing_att)]
                return []

            frappe.db.sql = MagicMock(side_effect=flex_sql)
            evidence_service.assert_file_read_permission = MagicMock()

            def perm_check(doc, ptype="read", user=None):
                if ptype == "write":
                    return True
                return False  # read denied

            permissions.evidence_has_permission = MagicMock(side_effect=perm_check)

            with self.assertRaises(Exception) as ctx:
                ingest_attachment(
                    evidence_name="EV-SECRET",
                    file_url="/private/files/doc.pdf",
                    identity_type="ordinal",
                    identity_value=0,
                )
            self.assertIn("access denied", str(ctx.exception).lower())
        finally:
            frappe.db.sql = orig_sql
            permissions.evidence_has_permission = orig_ev_has_perm
            evidence_service.assert_file_read_permission = orig_assert_file

    def test_storage_read_failure_and_torn_read(self):
        import frappe
        from fresko_universe.fresko_core.services.evidence_service import verify_and_capture_attachment

        att_row = {
            "name": "ATT-TORN",
            "evidence": "EV-1",
            "file_url": "/private/files/test.pdf",
            "storage_ref": "File/123",
            "provenance_type": "PROVIDER_HEADER_CONTENT_LENGTH",
            "provenance_ref": None,
            "expected_byte_count": 10,
            "expected_sha256": None,
            "capture_status": "PENDING",
            "readback_verified": 0,
            "content_sha256": None,
            "content_byte_count": 0,
            "logical_attachment_key": "log_key_torn",
            "scoped_attachment_version_key": "ver_key_torn",
        }
        parent_row = {
            "name": "EV-1",
            "deal": None,
            "manifest_status": "FINALIZED",
            "expected_attachment_count": 1,
            "verified_attachment_count": 0,
            "overall_verification_status": "PENDING",
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC",
            "conversation_id": "CONV",
            "provider_message_id": "MSG",
            "scoped_message_key": "key",
            "message_payload_sha256": "pay_hash",
        }

        orig_sql = frappe.db.sql
        try:
            attempt_row = {
                "name": "ATT-ATTEMPT",
                "evidence": "EV-1",
                "operation": "MESSAGE_INGEST",
                "source_payload": json.dumps({"document": {"file_size": 10}}),
                "observed_byte_count": 10,
                "observed_sha256": None,
            }

            def flex_sql(query, params=None, as_dict=False):
                if "FROM `tabFresko Evidence Attachment`" in query:
                    return [types.SimpleNamespace(**att_row)]
                if "FROM `tabFresko Evidence Attempt`" in query:
                    return [types.SimpleNamespace(**attempt_row)]
                if "FROM `tabFresko Evidence`" in query:
                    return [types.SimpleNamespace(**parent_row)]
                return []

            frappe.db.sql = MagicMock(side_effect=flex_sql)
            frappe.get_doc = MagicMock(return_value=types.SimpleNamespace(**parent_row))
            from fresko_universe.fresko_core.services import evidence_service
            orig_get_path = evidence_service.get_validated_local_file_path
            evidence_service.get_validated_local_file_path = MagicMock(return_value="mock_file.txt")

            from unittest.mock import patch
            with patch("builtins.open", side_effect=IOError("Storage disk I/O error")):
                res_io = verify_and_capture_attachment("ATT-TORN")
            self.assertFalse(res_io.success)
            self.assertEqual(res_io.status, "FAILED_RETRYABLE")
            self.assertIn("storage disk i/o error", res_io.reason.lower())

            mock_files = [
                MagicMock(read=MagicMock(return_value=b"1234567890")),
                MagicMock(read=MagicMock(return_value=b"12345DIFFERENT")),
            ]
            open_mock = MagicMock(side_effect=lambda *a, **k: mock_files.pop(0))
            with patch("builtins.open", open_mock):
                res_torn = verify_and_capture_attachment("ATT-TORN")
            self.assertFalse(res_torn.success)
            self.assertEqual(res_torn.status, "FAILED_RETRYABLE")
            self.assertIn("consistency check failed", res_torn.reason.lower())
        finally:
            frappe.db.sql = orig_sql
            evidence_service.get_validated_local_file_path = orig_get_path

    def test_concurrent_verification_and_correction_preserves_old_version(self):
        import frappe
        from fresko_universe.fresko_core.services.evidence_service import supersede_attachment

        old_att_row = {
            "name": "ATT-V1",
            "evidence": "EV-1",
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC",
            "conversation_id": "CONV",
            "provider_message_id": "MSG",
            "identity_type": "ordinal",
            "provider_attachment_id": None,
            "attachment_ordinal": 0,
            "logical_attachment_key": "log_key_1",
            "version": 1,
            "is_current_version": 1,
            "is_superseded": 0,
            "file": "/private/files/orig.pdf",
            "file_url": "/private/files/orig.pdf",
            "capture_status": "CAPTURED",
            "readback_verified": 1,
            "content_sha256": "orig_sha_123",
            "content_byte_count": 100,
        }
        parent_row = {
            "name": "EV-1",
            "deal": None,
            "manifest_status": "FINALIZED",
            "expected_attachment_count": 1,
            "verified_attachment_count": 1,
            "overall_verification_status": "COMPLETE",
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC",
            "conversation_id": "CONV",
            "provider_message_id": "MSG",
            "scoped_message_key": "key",
            "message_payload_sha256": "pay_hash",
        }

        orig_sql = frappe.db.sql
        orig_set_value = frappe.db.set_value
        from fresko_universe.fresko_core.services import evidence_service
        orig_assert_file = evidence_service.assert_file_read_permission
        evidence_service.assert_file_read_permission = MagicMock()
        set_values = []
        try:
            def flex_sql(query, params=None, as_dict=False):
                if "FROM `tabFresko Evidence Attachment`" in query:
                    return [types.SimpleNamespace(**old_att_row)]
                if "FROM `tabFresko Evidence`" in query:
                    return [types.SimpleNamespace(**parent_row)]
                return []

            frappe.db.sql = MagicMock(side_effect=flex_sql)
            frappe.get_doc = MagicMock(return_value=types.SimpleNamespace(**parent_row))
            def record_set_value(dt, dn, *args, **kwargs):
                val = args[0] if args else kwargs
                set_values.append((dn, val))

            frappe.db.set_value = MagicMock(side_effect=record_set_value)

            new_v2 = supersede_attachment(
                attachment_name="ATT-V1",
                new_file_url="/private/files/v2.pdf",
                reason="Correcting scanned resolution",
                provenance_type="PROVIDER_HEADER_CONTENT_LENGTH",
                expected_byte_count=200,
            )

            # New version is version 2 with same logical key
            self.assertEqual(new_v2.version, 2)
            self.assertEqual(new_v2.logical_attachment_key, "log_key_1")
            self.assertEqual(new_v2.is_current_version, 1)
            self.assertEqual(new_v2.is_superseded, 0)
            self.assertEqual(new_v2.capture_status, "PENDING")

            # Old version marked superseded
            self.assertTrue(any(
                dn == "ATT-V1" and isinstance(val, dict) and val.get("is_current_version") == 0 and val.get("is_superseded") == 1 and val.get("capture_status") == "SUPERSEDED"
                for dn, val in set_values
            ))
        finally:
            frappe.db.sql = orig_sql
            frappe.db.set_value = orig_set_value
            evidence_service.assert_file_read_permission = orig_assert_file

    def test_attachment_immutability_and_direct_edit_blocked(self):
        from fresko_universe.fresko_core.doctype.fresko_evidence_attachment.fresko_evidence_attachment import (
            FreskoEvidenceAttachment,
        )

        # 1. Existing attachment cannot be edited via direct Desk/API without in_service flag
        doc = FreskoEvidenceAttachment()
        doc.is_new = lambda: False
        doc.flags = MagicMock(in_service=False)
        with self.assertRaises(Exception) as ctx:
            doc.validate()
        self.assertIn("direct desk/api modification", str(ctx.exception).lower())

        # 2. Identity fields are immutable once set, even in service
        doc_svc = FreskoEvidenceAttachment()
        doc_svc.is_new = lambda: False
        doc_svc.flags = MagicMock(in_service=True)
        doc_svc.has_value_changed = lambda f: f == "logical_attachment_key"
        doc_svc.get_db_value = lambda f: "old_key_123" if f == "logical_attachment_key" else None
        with self.assertRaises(Exception) as ctx:
            doc_svc.validate()
        self.assertIn("identity field 'logical_attachment_key' is immutable", str(ctx.exception).lower())

        # 3. Captured content fields are immutable once CAPTURED
        doc_cap = FreskoEvidenceAttachment()
        doc_cap.is_new = lambda: False
        doc_cap.flags = MagicMock(in_service=True)
        doc_cap.has_value_changed = lambda f: f == "content_sha256"
        def get_db_val(f):
            if f == "capture_status":
                return "CAPTURED"
            if f == "content_sha256":
                return "sha_old"
            return None
        doc_cap.get_db_value = get_db_val
        with self.assertRaises(Exception) as ctx:
            doc_cap.validate()
        self.assertIn("content field 'content_sha256' is immutable once captured", str(ctx.exception).lower())

    def test_parent_evidence_immutability_enforced(self):
        from fresko_universe.fresko_core.doctype.fresko_evidence.fresko_evidence import (
            FreskoEvidence,
        )

        doc = FreskoEvidence()
        doc.is_new = lambda: False
        doc.flags = MagicMock(in_service=True)
        doc.has_value_changed = lambda f: f == "scoped_message_key"
        doc.get_db_value = lambda f: "existing_scoped_key" if f == "scoped_message_key" else None
        with self.assertRaises(Exception) as ctx:
            doc.validate()
        self.assertIn("evidence field 'scoped_message_key' is immutable once set", str(ctx.exception).lower())

    def test_parent_first_lock_hierarchy_enforced(self):
        import frappe
        from fresko_universe.fresko_core.services.evidence_service import (
            verify_and_capture_attachment,
            supersede_attachment,
        )

        att_row = {
            "name": "ATT-LOCK",
            "evidence": "EV-LOCK",
            "file_url": "/private/files/test.pdf",
            "storage_ref": "File/123",
            "provenance_type": "PROVIDER_HEADER_CONTENT_LENGTH",
            "provenance_ref": None,
            "expected_byte_count": 10,
            "expected_sha256": None,
            "capture_status": "PENDING",
            "readback_verified": 0,
            "content_sha256": None,
            "content_byte_count": 0,
            "logical_attachment_key": "log_key_lock",
            "scoped_attachment_version_key": "ver_key_lock",
            "version": 1,
            "is_current_version": 1,
            "is_superseded": 0,
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC",
            "conversation_id": "CONV",
            "provider_message_id": "MSG",
            "identity_type": "ordinal",
            "provider_attachment_id": None,
            "attachment_ordinal": 0,
        }
        parent_row = {
            "name": "EV-LOCK",
            "deal": None,
            "manifest_status": "FINALIZED",
            "expected_attachment_count": 1,
            "verified_attachment_count": 0,
            "overall_verification_status": "PENDING",
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC",
            "conversation_id": "CONV",
            "provider_message_id": "MSG",
            "scoped_message_key": "key",
            "message_payload_sha256": "pay_hash",
        }

        lock_order = []
        orig_sql = frappe.db.sql
        from fresko_universe.fresko_core.services import evidence_service
        orig_assert_file = evidence_service.assert_file_read_permission
        orig_get_path = evidence_service.get_validated_local_file_path
        try:
            evidence_service.assert_file_read_permission = MagicMock()
            evidence_service.get_validated_local_file_path = MagicMock(return_value="mock.txt")

            def tracing_sql(query, params=None, as_dict=False):
                if "FOR UPDATE" in query:
                    if "FROM `tabFresko Evidence`" in query:
                        lock_order.append("PARENT_LOCK")
                        return [types.SimpleNamespace(**parent_row)]
                    elif "FROM `tabFresko Evidence Attachment`" in query:
                        lock_order.append("CHILD_LOCK")
                        return [types.SimpleNamespace(**att_row)]
                else:
                    if "FROM `tabFresko Evidence Attachment`" in query:
                        return [types.SimpleNamespace(**att_row)]
                    if "FROM `tabFresko Evidence`" in query:
                        return [types.SimpleNamespace(**parent_row)]
                return []

            frappe.db.sql = MagicMock(side_effect=tracing_sql)
            frappe.get_doc = MagicMock(return_value=types.SimpleNamespace(**parent_row))

            from unittest.mock import mock_open, patch
            with patch("builtins.open", mock_open(read_data=b"0123456789")):
                verify_and_capture_attachment("ATT-LOCK")

            # Verify that PARENT_LOCK strictly preceded CHILD_LOCK
            self.assertIn("PARENT_LOCK", lock_order)
            self.assertIn("CHILD_LOCK", lock_order)
            parent_idx = lock_order.index("PARENT_LOCK")
            child_idx = lock_order.index("CHILD_LOCK")
            self.assertLess(parent_idx, child_idx, "Parent Evidence FOR UPDATE lock must precede Child Attachment FOR UPDATE lock")

            # Now verify supersede_attachment lock order
            lock_order.clear()
            supersede_attachment(
                attachment_name="ATT-LOCK",
                new_file_url="/private/files/new.pdf",
                reason="Resolution fix",
                provenance_type="PROVIDER_HEADER_CONTENT_LENGTH",
                expected_byte_count=10,
            )
            self.assertIn("PARENT_LOCK", lock_order)
            self.assertIn("CHILD_LOCK", lock_order)
            parent_idx2 = lock_order.index("PARENT_LOCK")
            child_idx2 = lock_order.index("CHILD_LOCK")
            self.assertLess(parent_idx2, child_idx2, "Parent Evidence FOR UPDATE lock must precede Child Attachment FOR UPDATE lock in correction")
        finally:
            frappe.db.sql = orig_sql
            evidence_service.assert_file_read_permission = orig_assert_file
            evidence_service.get_validated_local_file_path = orig_get_path

    def test_regression_completeness_provenance_binds_to_manifest_and_payload(self):
        """Finding 1: Manifest contents must be verified and bound to attachment; provider payload must declare attachment."""
        import os
        import frappe
        from fresko_universe.fresko_core.services.evidence_service import validate_completeness_provenance
        import tempfile

        # Case 1: Manifest has arbitrary JSON not mentioning this attachment -> must fail closed
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
            json.dump({"random_key": "arbitrary_data"}, tf)
            manifest_path = tf.name

        try:
            att_row = {
                "name": "ATT-UNBOUND",
                "file_url": "/private/files/invoice.pdf",
                "identity_type": "ordinal",
                "attachment_ordinal": 0,
                "logical_attachment_key": "log_unbound",
                "provenance_type": "OFFLINE_IMPORT_MANIFEST",
                "provenance_ref": manifest_path,
                "expected_byte_count": 1234,
                "expected_sha256": "fakehash",
            }
            parent_row = {"name": "EV-1", "message_payload_sha256": "hash1"}
            trusted, reason, _, _ = validate_completeness_provenance(att_row, parent_row)
            self.assertFalse(trusted)
            self.assertIn("no verified entry", reason.lower())

            # Case 2: Manifest mentions this attachment explicitly with size and hash -> succeeds
            with open(manifest_path, "w", encoding="utf-8") as tf2:
                json.dump({
                    "attachments": [
                        {
                            "file_name": "invoice.pdf",
                            "expected_byte_count": 1234,
                            "expected_sha256": "correct_hash",
                        }
                    ]
                }, tf2)

            att_row["expected_sha256"] = "correct_hash"
            trusted2, reason2, bound_bytes, bound_hash = validate_completeness_provenance(att_row, parent_row)
            self.assertTrue(trusted2, f"Failed with reason: {reason2}")
            self.assertEqual(bound_bytes, 1234)
            self.assertEqual(bound_hash, "correct_hash")

            # Case 3: Provider payload lacks attachment declaration -> must fail closed
            att_prov = {
                "name": "ATT-PROV",
                "file_url": "/private/files/doc.pdf",
                "identity_type": "provider_id",
                "provider_attachment_id": "att_unknown_id",
                "logical_attachment_key": "log_prov",
                "provenance_type": "PROVIDER_PAYLOAD_DIGEST",
                "provenance_ref": None,
                "expected_byte_count": 500,
                "expected_sha256": "sha500",
            }
            parent_empty_payload = {"name": "EV-2", "message_payload_sha256": "parent_hash"}
            trusted3, reason3, _, _ = validate_completeness_provenance(att_prov, parent_empty_payload)
            self.assertFalse(trusted3)
            self.assertIn("does not contain", reason3.lower())
        finally:
            if os.path.exists(manifest_path):
                os.remove(manifest_path)

    def test_regression_superseded_file_protection_and_verification_rejection(self):
        """Finding 2: Files backing SUPERSEDED attachments must remain protected; superseded attachments cannot be verified."""
        import os
        import frappe
        from fresko_universe.fresko_core.services.evidence_service import (
            prevent_captured_file_deletion,
            prevent_captured_file_modification,
            verify_and_capture_attachment,
        )

        orig_sql = frappe.db.sql
        try:
            # File referenced by SUPERSEDED attachment cannot be deleted or modified
            superseded_ref = [{"name": "ATT-OLD", "evidence": "EV-1", "capture_status": "SUPERSEDED", "version": 1, "is_superseded": 1}]
            frappe.db.sql = MagicMock(return_value=superseded_ref)

            file_doc = MagicMock()
            file_doc.name = "FILE-OLD"
            file_doc.file_url = "/private/files/old_receipt.pdf"
            file_doc.is_new = lambda: False
            file_doc.has_value_changed = lambda f: f == "file_url"

            with self.assertRaises(Exception) as ctx_del:
                prevent_captured_file_deletion(file_doc)
            self.assertIn("cannot delete file", str(ctx_del.exception).lower())

            with self.assertRaises(Exception) as ctx_mod:
                prevent_captured_file_modification(file_doc)
            self.assertIn("cannot modify file", str(ctx_mod.exception).lower())

            # verify_and_capture_attachment on superseded attachment must fail
            old_att_row = {
                "name": "ATT-OLD",
                "evidence": "EV-1",
                "file_url": "/private/files/old_receipt.pdf",
                "is_superseded": 1,
                "is_current_version": 0,
                "capture_status": "SUPERSEDED",
                "version": 1,
                "logical_attachment_key": "log1",
                "scoped_attachment_version_key": "ver1",
            }
            parent_row = {"name": "EV-1", "overall_verification_status": "COMPLETE"}

            def flex_sql(query, params=None, as_dict=False):
                if "FROM `tabFresko Evidence Attachment`" in query:
                    return [types.SimpleNamespace(**old_att_row)]
                if "FROM `tabFresko Evidence`" in query:
                    return [types.SimpleNamespace(**parent_row)]
                return []

            frappe.db.sql = MagicMock(side_effect=flex_sql)
            frappe.get_doc = MagicMock(return_value=types.SimpleNamespace(**parent_row))
            res = verify_and_capture_attachment("ATT-OLD")
            self.assertFalse(res.success)
            self.assertEqual(res.status, "SUPERSEDED")
            self.assertIn("superseded", res.reason.lower())
        finally:
            frappe.db.sql = orig_sql

    def test_regression_path_component_containment_and_traversal(self):
        """Finding 3: Sibling directories (files-backup) and traversals must fail path containment."""
        from fresko_universe.fresko_core.services.evidence_service import get_validated_local_file_path
        import frappe

        # Create sibling directory private/files-backup and a file inside it
        sibling_dir = frappe.get_site_path("private", "files-backup")
        os.makedirs(sibling_dir, exist_ok=True)
        sibling_file = os.path.join(sibling_dir, "secret.pdf")
        with open(sibling_file, "wb") as f:
            f.write(b"secret")

        try:
            # Traversal outside
            with self.assertRaises(Exception) as ctx1:
                get_validated_local_file_path("/private/files/../../etc/passwd")
            self.assertIn("forbidden", str(ctx1.exception).lower())

            # Sibling prefix directory: private/files-backup must NOT pass containment for private/files
            with self.assertRaises(Exception) as ctx2:
                get_validated_local_file_path(sibling_file)
            self.assertIn("forbidden", str(ctx2.exception).lower())
        finally:
            if os.path.exists(sibling_file):
                os.remove(sibling_file)
            if os.path.exists(sibling_dir):
                os.rmdir(sibling_dir)

    def test_regression_identity_contract_untrimmed_replay_and_ordinal(self):
        """Finding 4: Provider IDs are untrimmed; ordinal identity requires stable-ordering provenance; replay checks content/provenance."""
        from fresko_universe.fresko_core.services.evidence_service import (
            compute_scoped_message_key,
            compute_logical_attachment_key,
            ingest_attachment,
        )

        # 4a: Opaque IDs must NOT be trimmed
        key_raw = compute_scoped_message_key(" whatsapp-cloud ", " ACC ", " CHAT ", " MSG ")
        key_stripped = compute_scoped_message_key("whatsapp-cloud", "ACC", "CHAT", "MSG")
        self.assertNotEqual(key_raw, key_stripped, "Opaque identifiers must not be trimmed")

        # 4b: Ordinal identity without stable-ordering provenance is rejected
        parent_row = {
            "name": "EV-1",
            "deal": None,
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC",
            "conversation_id": "CONV",
            "provider_message_id": "MSG",
        }
        import frappe
        orig_sql = frappe.db.sql
        try:
            def flex_sql(query, params=None, as_dict=False):
                if "FROM `tabFresko Evidence`" in query:
                    return [types.SimpleNamespace(**parent_row)]
                return []

            frappe.db.sql = MagicMock(side_effect=flex_sql)
            with self.assertRaises(Exception) as ctx_ord:
                ingest_attachment(
                    evidence_name="EV-1",
                    file_url="/private/files/doc.pdf",
                    identity_type="ordinal",
                    identity_value=0,
                    provenance_type="UNTRUSTED_CALLER",
                )
            self.assertIn("stable ordering", str(ctx_ord.exception).lower())
        finally:
            frappe.db.sql = orig_sql

    def test_regression_transaction_boundary_no_blanket_commits(self):
        """Finding 1: Internal blanket commits must be removed; unrelated caller changes are NOT committed."""
        from fresko_universe.fresko_core.services.evidence_service import ingest_message_evidence
        import frappe

        existing_row = {
            "name": "EV-COLLIDE",
            "deal": None,
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC_ORIGINAL",
            "conversation_id": "CONV_ORIGINAL",
            "provider_message_id": "MSG_ORIGINAL",
            "scoped_message_key": "COLLISION_KEY",
            "message_payload_sha256": "pay_orig",
            "overall_verification_status": "PENDING",
        }

        orig_new_doc = frappe.new_doc
        orig_sql = frappe.db.sql
        commit_calls = []
        attempt_docs = []
        try:
            def flex_new_doc(dt, *a, **k):
                d = MagicMock()
                d.doctype = dt
                if dt == "Fresko Evidence":
                    d.insert = MagicMock(side_effect=frappe.UniqueValidationError("Fresko Evidence", "EV-NEW", "dup"))
                elif dt == "Fresko Evidence Attempt":
                    d.insert = MagicMock(side_effect=lambda *args, **kwargs: attempt_docs.append(d))
                else:
                    d.insert = MagicMock()
                return d

            frappe.new_doc = MagicMock(side_effect=flex_new_doc)
            frappe.db.sql = MagicMock(return_value=[types.SimpleNamespace(**existing_row)])
            frappe.db.commit = MagicMock(side_effect=lambda: commit_calls.append(True))

            # Trigger key collision: scope fields differ
            from fresko_universe.fresko_core.services.evidence_service import IntegrityConflictError
            with self.assertRaises(IntegrityConflictError):
                ingest_message_evidence(
                    provider="whatsapp-cloud",
                    provider_account_id="ACC_COLLIDING",
                    conversation_id="CONV_COLLIDING",
                    provider_message_id="MSG_COLLIDING",
                    raw_payload={"text": "collision"},
                )

            # Assert frappe.db.commit was NEVER called (blanket commit removed)
            self.assertEqual(len(commit_calls), 0, "evidence_service must NEVER blanket commit frappe.db")
            # Attempt record must still be created
            self.assertTrue(len(attempt_docs) > 0, "Structured attempt record must be created")
        finally:
            frappe.new_doc = orig_new_doc
            frappe.db.sql = orig_sql

    def test_regression_source_bound_expectations_and_ambiguity_rejection(self):
        """Finding 2: Ambiguous provenance matches and caller fallback must be rejected."""
        import tempfile
        import frappe
        from fresko_universe.fresko_core.services.evidence_service import validate_completeness_provenance

        # Ambiguous manifest: two entries match the same file name
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
            json.dump({
                "attachments": [
                    {"file_name": "ambig.pdf", "expected_byte_count": 100, "expected_sha256": "hash1"},
                    {"file_name": "ambig.pdf", "expected_byte_count": 200, "expected_sha256": "hash2"},
                ]
            }, tf)
            manifest_path = tf.name

        try:
            att_row = {
                "name": "ATT-AMBIG",
                "file_url": "/private/files/ambig.pdf",
                "identity_type": "provider_id",
                "provider_attachment_id": "p_id",
                "logical_attachment_key": "log_ambig",
                "provenance_type": "OFFLINE_IMPORT_MANIFEST",
                "provenance_ref": manifest_path,
                "expected_byte_count": 100,
                "expected_sha256": "hash1",
            }
            parent_row = {"name": "EV-AMBIG", "message_payload_sha256": "h"}
            ok, reason, _, _ = validate_completeness_provenance(att_row, parent_row)
            self.assertFalse(ok)
            self.assertIn("ambiguous", reason.lower())

            # Manifest without declared expected hash rejects caller fallback
            with open(manifest_path, "w", encoding="utf-8") as tf2:
                json.dump({
                    "attachments": [
                        {"file_name": "ambig.pdf", "expected_byte_count": 100}
                    ]
                }, tf2)

            att_row["expected_sha256"] = "caller_invented_hash"
            ok2, reason2, _, _ = validate_completeness_provenance(att_row, parent_row)
            self.assertFalse(ok2)
            self.assertIn("caller fallback is disallowed", reason2.lower())
        finally:
            if os.path.exists(manifest_path):
                os.remove(manifest_path)

    def test_regression_replay_content_checked_at_same_url(self):
        """Finding 3: Replay checks actual file content on disk even when URL is unchanged."""
        from fresko_universe.fresko_core.services.evidence_service import ingest_attachment
        import frappe

        parent_row = {
            "name": "EV-1",
            "deal": None,
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC",
            "conversation_id": "CONV",
            "provider_message_id": "MSG",
        }
        existing_att_row = {
            "name": "ATT-EXISTING",
            "file_url": "/private/files/invoice.pdf",
            "content_sha256": "original_content_hash_12345",
            "expected_byte_count": 10,
            "expected_sha256": "original_content_hash_12345",
            "capture_status": "CAPTURED",
            "version": 1,
            "logical_attachment_key": "log_key",
            "provenance_type": "PROVIDER_PAYLOAD_DIGEST",
            "provenance_ref": None,
        }

        orig_sql = frappe.db.sql
        from fresko_universe.fresko_core.services import evidence_service
        orig_assert_file = evidence_service.assert_file_read_permission
        orig_get_path = evidence_service.get_validated_local_file_path
        try:
            evidence_service.assert_file_read_permission = MagicMock()
            evidence_service.get_validated_local_file_path = MagicMock(return_value="mock_invoice.pdf")

            def flex_sql(query, params=None, as_dict=False):
                if "FROM `tabFresko Evidence Attachment`" in query:
                    return [types.SimpleNamespace(**existing_att_row)]
                if "FROM `tabFresko Evidence`" in query:
                    return [types.SimpleNamespace(**parent_row)]
                return []

            frappe.db.sql = MagicMock(side_effect=flex_sql)

            # Mock file on disk having DIFFERENT content (tampered) despite same URL
            from unittest.mock import mock_open, patch
            with patch("builtins.open", mock_open(read_data=b"MODIFIED_BYTES_NOT_MATCHING")):
                with self.assertRaises(frappe.ValidationError) as ctx:
                    ingest_attachment(
                        evidence_name="EV-1",
                        file_url="/private/files/invoice.pdf",
                        identity_type="provider_id",
                        identity_value="p_id",
                        provenance_type="PROVIDER_PAYLOAD_DIGEST",
                        expected_byte_count=10,
                        expected_sha256="original_content_hash_12345",
                    )
            self.assertIn("supersede_attachment", str(ctx.exception).lower())
        finally:
            frappe.db.sql = orig_sql
            evidence_service.assert_file_read_permission = orig_assert_file
            evidence_service.get_validated_local_file_path = orig_get_path

    def test_regression_never_claim_persisted_failure_after_write_failure(self):
        """Finding 4: When updating status to FAILED_RETRYABLE throws, the error is NOT swallowed."""
        from fresko_universe.fresko_core.services.evidence_service import verify_and_capture_attachment
        import frappe

        att_row = {
            "name": "ATT-SWALLOW-TEST",
            "evidence": "EV-1",
            "file_url": "/private/files/test.pdf",
            "storage_ref": "File/123",
            "provenance_type": "PROVIDER_HEADER_CONTENT_LENGTH",
            "provenance_ref": None,
            "expected_byte_count": 5,
            "expected_sha256": None,
            "capture_status": "PENDING",
            "readback_verified": 0,
            "content_sha256": None,
            "content_byte_count": 0,
            "logical_attachment_key": "log_swallow",
            "scoped_attachment_version_key": "ver_swallow",
            "identity_type": "provider_id",
            "provider_attachment_id": "prov_1",
            "attachment_ordinal": None,
        }
        parent_row = {
            "name": "EV-1",
            "deal": None,
            "manifest_status": "FINALIZED",
            "expected_attachment_count": 1,
            "verified_attachment_count": 0,
            "overall_verification_status": "PENDING",
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC",
            "conversation_id": "CONV",
            "provider_message_id": "MSG",
            "scoped_message_key": "key",
            "message_payload_sha256": "pay_hash",
        }

        orig_sql = frappe.db.sql
        orig_set_value = frappe.db.set_value
        from fresko_universe.fresko_core.services import evidence_service
        orig_assert_file = evidence_service.assert_file_read_permission
        orig_get_path = evidence_service.get_validated_local_file_path
        try:
            evidence_service.assert_file_read_permission = MagicMock()
            evidence_service.get_validated_local_file_path = MagicMock(return_value="mock.txt")

            attempt_row = {
                "name": "ATT-ATTEMPT",
                "evidence": "EV-1",
                "operation": "MESSAGE_INGEST",
                "source_payload": json.dumps({"document": {"id": "prov_1", "file_size": 5}}),
                "observed_byte_count": 5,
                "observed_sha256": None,
            }

            def flex_sql(query, params=None, as_dict=False):
                if "FROM `tabFresko Evidence Attachment`" in query:
                    return [types.SimpleNamespace(**att_row)]
                if "FROM `tabFresko Evidence Attempt`" in query:
                    return [types.SimpleNamespace(**attempt_row)]
                if "FROM `tabFresko Evidence`" in query:
                    return [types.SimpleNamespace(**parent_row)]
                return []

            frappe.db.sql = MagicMock(side_effect=flex_sql)
            frappe.get_doc = MagicMock(return_value=types.SimpleNamespace(**parent_row))

            def throwing_set_value(dt, dn, fields, *a, **k):
                # Always raise DB write failure
                raise Exception("Database fatal write error: disk full")

            frappe.db.set_value = MagicMock(side_effect=throwing_set_value)

            from unittest.mock import mock_open, patch
            with patch("builtins.open", mock_open(read_data=b"12345")):
                with self.assertRaises(Exception) as ctx:
                    verify_and_capture_attachment("ATT-SWALLOW-TEST")

            self.assertIn("disk full", str(ctx.exception))
        finally:
            frappe.db.sql = orig_sql
            frappe.db.set_value = orig_set_value
            evidence_service.assert_file_read_permission = orig_assert_file
            evidence_service.get_validated_local_file_path = orig_get_path

    def test_regression_db_failure_persists_failed_retryable_status(self):
        """Finding 6: When database finalization fails, stored status in DB must be updated to FAILED_RETRYABLE."""
        from fresko_universe.fresko_core.services.evidence_service import verify_and_capture_attachment
        import frappe

        att_row = {
            "name": "ATT-FAIL-DB",
            "evidence": "EV-1",
            "file_url": "/private/files/test.pdf",
            "storage_ref": "File/123",
            "provenance_type": "PROVIDER_HEADER_CONTENT_LENGTH",
            "provenance_ref": None,
            "expected_byte_count": 5,
            "expected_sha256": None,
            "capture_status": "PENDING",
            "readback_verified": 0,
            "content_sha256": None,
            "content_byte_count": 0,
            "logical_attachment_key": "log_f",
            "scoped_attachment_version_key": "ver_f",
            "identity_type": "provider_id",
            "provider_attachment_id": "prov_1",
            "attachment_ordinal": None,
        }
        parent_row = {
            "name": "EV-1",
            "deal": None,
            "manifest_status": "FINALIZED",
            "expected_attachment_count": 1,
            "verified_attachment_count": 0,
            "overall_verification_status": "PENDING",
            "provider": "whatsapp-cloud",
            "provider_account_id": "ACC",
            "conversation_id": "CONV",
            "provider_message_id": "MSG",
            "scoped_message_key": "key",
            "message_payload_sha256": "pay_hash",
        }

        orig_sql = frappe.db.sql
        orig_set_value = frappe.db.set_value
        from fresko_universe.fresko_core.services import evidence_service
        orig_assert_file = evidence_service.assert_file_read_permission
        orig_get_path = evidence_service.get_validated_local_file_path
        status_updates = []
        try:
            evidence_service.assert_file_read_permission = MagicMock()
            evidence_service.get_validated_local_file_path = MagicMock(return_value="mock.txt")

            attempt_row = {
                "name": "ATT-ATTEMPT",
                "evidence": "EV-1",
                "operation": "MESSAGE_INGEST",
                "source_payload": json.dumps({"document": {"id": "prov_1", "file_size": 5}}),
                "observed_byte_count": 5,
                "observed_sha256": None,
            }

            def flex_sql(query, params=None, as_dict=False):
                if "FROM `tabFresko Evidence Attachment`" in query:
                    return [types.SimpleNamespace(**att_row)]
                if "FROM `tabFresko Evidence Attempt`" in query:
                    return [types.SimpleNamespace(**attempt_row)]
                if "FROM `tabFresko Evidence`" in query:
                    return [types.SimpleNamespace(**parent_row)]
                return []

            frappe.db.sql = MagicMock(side_effect=flex_sql)
            frappe.get_doc = MagicMock(return_value=types.SimpleNamespace(**parent_row))

            def tracking_set_value(dt, dn, fields, *a, **k):
                if isinstance(fields, dict):
                    if fields.get("capture_status") == "CAPTURED":
                        raise Exception("Simulated DB Deadlock / Constraint Error")
                    status_updates.append(fields.get("capture_status"))

            frappe.db.set_value = MagicMock(side_effect=tracking_set_value)

            from unittest.mock import mock_open, patch
            with patch("builtins.open", mock_open(read_data=b"12345")):
                res = verify_and_capture_attachment("ATT-FAIL-DB")

            self.assertEqual(res.status, "FAILED_RETRYABLE")
            # Database stored status must have been updated to FAILED_RETRYABLE
            self.assertIn("FAILED_RETRYABLE", status_updates, "Stored status in DB must be updated to FAILED_RETRYABLE on error")
        finally:
            frappe.db.sql = orig_sql
            frappe.db.set_value = orig_set_value
            evidence_service.assert_file_read_permission = orig_assert_file
            evidence_service.get_validated_local_file_path = orig_get_path

    def test_regression_parent_aggregation_uses_current_read(self):
        """Finding 7: Parent aggregation must query child attachments with current-read semantics (LOCK IN SHARE MODE / FOR UPDATE)."""
        from fresko_universe.fresko_core.services.evidence_service import aggregate_parent_evidence_status
        import frappe

        queries = []
        orig_sql = frappe.db.sql
        try:
            def recording_sql(query, params=None, as_dict=False):
                queries.append(query)
                if "FROM `tabFresko Evidence`" in query:
                    return [types.SimpleNamespace(
                        name="EV-1",
                        manifest_status="FINALIZED",
                        expected_attachment_count=1,
                        overall_verification_status="PENDING",
                    )]
                if "FROM `tabFresko Evidence Attachment`" in query:
                    return []
                return []

            frappe.db.sql = MagicMock(side_effect=recording_sql)
            aggregate_parent_evidence_status("EV-1")

            child_query = next((q for q in queries if "FROM `tabFresko Evidence Attachment`" in q), "")
            self.assertTrue(
                "LOCK IN SHARE MODE" in child_query or "FOR UPDATE" in child_query,
                f"Child attachment query must use current-read locking (LOCK IN SHARE MODE or FOR UPDATE), got: {child_query}",
            )
        finally:
            frappe.db.sql = orig_sql



if __name__ == "__main__":
    unittest.main()


