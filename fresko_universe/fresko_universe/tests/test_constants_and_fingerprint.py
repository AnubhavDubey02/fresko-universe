"""Unit tests runnable without a full Frappe/ERPNext bench.

Run: python -m pytest fresko_universe/fresko_universe/tests/test_constants_and_fingerprint.py -q
"""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

# Allow importing app package from repo layout without install
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fresko_universe.constants import (  # noqa: E402
    ATS_ACTIVE_STATUSES,
    COMMERCIAL_LOCK_STATUSES,
    DEAL_TRANSITIONS,
    OVERSELL_OVERRIDE_ROLES,
    EXCEPTION_TYPES,
    MATERIAL_EXCEPTION_TYPES,
)


def make_fingerprint(buyer_alias, container, lot_no, qty, proposed_rate, uom, day):
    raw = "|".join(
        [
            (buyer_alias or "").strip().lower(),
            container or "",
            lot_no or "",
            _fmt(qty),
            _fmt(proposed_rate),
            uom or "",
            day,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fmt(val):
    f = float(val or 0)
    return f"{f:.6f}".rstrip("0").rstrip(".") if f else "0"


class TestFingerprint(unittest.TestCase):
    def test_fingerprint_stable(self):
        a = make_fingerprint("Rehan", "CON-1", "L1", 50, 12.5, "Crate", "2026-09-15")
        b = make_fingerprint("  REHAN ", "CON-1", "L1", 50.0, 12.500, "Crate", "2026-09-15")
        self.assertEqual(a, b)

    def test_fingerprint_differs_on_qty(self):
        a = make_fingerprint("Rehan", "CON-1", "L1", 50, 12.5, "Crate", "2026-09-15")
        b = make_fingerprint("Rehan", "CON-1", "L1", 51, 12.5, "Crate", "2026-09-15")
        self.assertNotEqual(a, b)


class TestStateMachine(unittest.TestCase):
    def test_proposed_cannot_jump_to_reconciled(self):
        self.assertNotIn("Reconciled", DEAL_TRANSITIONS["Proposed"])

    def test_countered_goes_to_approved_not_outward(self):
        # D4 locked
        self.assertIn("Approved", DEAL_TRANSITIONS["Countered"])
        self.assertNotIn("Outward Pending", DEAL_TRANSITIONS["Countered"])

    def test_proposed_does_not_reduce_ats(self):
        self.assertNotIn("Proposed", ATS_ACTIVE_STATUSES)
        self.assertNotIn("Approval Required", ATS_ACTIVE_STATUSES)
        self.assertNotIn("Countered", ATS_ACTIVE_STATUSES)

    def test_approved_reduces_ats(self):
        self.assertIn("Approved", ATS_ACTIVE_STATUSES)
        self.assertIn("Auto Approved", ATS_ACTIVE_STATUSES)

    def test_commercial_lock_includes_approved(self):
        self.assertIn("Approved", COMMERCIAL_LOCK_STATUSES)
        self.assertIn("Auto Approved", COMMERCIAL_LOCK_STATUSES)

    def test_commercial_lock_includes_approval_required(self):
        # F-H4
        self.assertIn("Approval Required", COMMERCIAL_LOCK_STATUSES)

    def test_d10_oversell_system_manager_only(self):
        self.assertEqual(OVERSELL_OVERRIDE_ROLES, frozenset({"System Manager"}))
        self.assertNotIn("Fresko Approver", OVERSELL_OVERRIDE_ROLES)


class TestRateBandHierarchy(unittest.TestCase):
    """D5 resolution logic mirrored without frappe Document."""

    def resolve(self, lot_floor, bands, default_floor, item, count_size, container_item):
        if lot_floor is not None:
            return lot_floor
        cs = (count_size or "").strip()
        if cs:
            for band in bands:
                band_item = band.get("item") or container_item
                if (band.get("count_size") or "").strip() == cs and band_item == item:
                    return band["rate_floor"]
        return default_floor

    def test_lot_override_wins(self):
        v = self.resolve(10, [{"count_size": "16/20", "rate_floor": 20, "item": None}], 30, "ITEM", "16/20", "ITEM")
        self.assertEqual(v, 10)

    def test_count_band_before_default(self):
        v = self.resolve(None, [{"count_size": "16/20", "rate_floor": 20, "item": None}], 30, "ITEM", "16/20", "ITEM")
        self.assertEqual(v, 20)

    def test_default_fallback(self):
        v = self.resolve(None, [], 30, "ITEM", "16/20", "ITEM")
        self.assertEqual(v, 30)


class TestExceptionTypes(unittest.TestCase):
    def test_rate_policy_missing_in_exception_types(self):
        from fresko_universe.constants import EXCEPTION_TYPES, MATERIAL_EXCEPTION_TYPES
        self.assertIn("RATE_POLICY_MISSING", EXCEPTION_TYPES)
        self.assertIn("RATE_POLICY_MISSING", MATERIAL_EXCEPTION_TYPES)
        self.assertIn("RATE_FLOOR_BREACH", EXCEPTION_TYPES)


if __name__ == "__main__":
    unittest.main()
