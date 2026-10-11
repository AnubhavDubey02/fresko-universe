"""Native allocation approval authorization; synthetic Bench fixtures only.

No mocked permissions or writes. Snapshot BEFORE transaction rollback so a
denied operation cannot hide partial persistence behind test cleanup.
"""
import json

import frappe
from frappe.tests.utils import FrappeTestCase

from fresko_universe import commercial
from fresko_universe.tests.test_commercial_sale import (
    ALLOCATION, SALE, CommercialSaleFixtures, _ensure_user,
)


class TestP0Authorization(CommercialSaleFixtures, FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.checker_with_approval = _ensure_user(
            "p0_checker@example.invalid", ["Fresko Accounts", "Fresko Approver"])
        cls.supplier_with_approval = _ensure_user(
            "p0_supplier@example.invalid", ["Fresko Supplier Viewer", "Fresko Approver"])
        frappe.db.commit()

    def _candidate(self, *, verified):
        # Both maker and checker also hold Approver: denials must test identity
        # separation, rather than succeeding merely because a role is absent.
        self.maker = self.all_roles
        self.accounts = self.checker_with_approval
        self.sale = self._approve_sale(self._create())
        self.physical = self._outward()
        allocation = self._allocation(self.sale, self.physical, 30)
        if verified:
            self._verify_allocation(allocation)
        return allocation

    def _snapshot(self):
        # Test-only unrestricted inspection includes related rows hidden from
        # the acting user. No permission bypass is used by the action itself.
        truth = {}
        for doctype, name in (
            ("Fresko Container", self.container.name),
            ("Fresko Outward", self.physical.name),
            ("Fresko Evidence", self.evidence.name),
        ):
            truth[doctype] = frappe.get_doc(doctype, name).as_dict()
        state = {"truth": truth, "sale": frappe.get_doc(SALE, self.sale.name).as_dict()}
        for doctype in (ALLOCATION, "Fresko Exception"):
            state[doctype] = [frappe.get_doc(doctype, name).as_dict() for name in
                frappe.get_all(doctype, filters={"container": self.container.name},
                               order_by="name", pluck="name")]
        references = [self.container.name, self.physical.name, self.sale.name, self.evidence.name]
        references += [row["name"] for row in state[ALLOCATION] + state["Fresko Exception"]]
        for doctype, field in (("Version", "docname"), ("Comment", "reference_name")):
            state[doctype] = frappe.get_all(doctype, filters={field: ("in", references)},
                                           fields=["*"], order_by="name")
        return state

    def _deny_unchanged(self, allocation, actor, error, message=None, version=None):
        before = self._snapshot()
        frappe.set_user(actor)
        try:
            context = (self.assertRaisesRegex(error, message) if message
                       else self.assertRaises(error))
            with context:
                commercial.approve_sale_outward_allocation(
                    allocation.name, expected_version=allocation.version if version is None else version)
        finally:
            frappe.set_user("Administrator")
        self.assertEqual(before, self._snapshot(), "Denied approval persisted related changes")

    def test_missing_verifier_denies_without_any_persisted_effect(self):
        allocation = self._candidate(verified=False)
        self.assertEqual(allocation.state, "PROPOSED")
        self.assertFalse(allocation.verified_by)
        self._deny_unchanged(allocation, self.approver, frappe.ValidationError,
                             "requires Accounts verification")

    def test_wrong_role_supplier_maker_and_checker_denials_have_no_effect(self):
        allocation = self._candidate(verified=True)
        for actor in (self.other_maker, self.manager, self.supplier,
                      self.supplier_with_approval, self.maker, self.accounts):
            with self.subTest(actor=actor):
                self._deny_unchanged(allocation, actor, frappe.PermissionError)

    def test_stale_token_denies_without_any_persisted_effect(self):
        allocation = self._candidate(verified=True)
        self._deny_unchanged(allocation, self.approver, frappe.ValidationError,
                             "STALE_VERSION", version=allocation.version - 1)

    def test_authorized_approval_and_current_token_replay_have_one_effect(self):
        allocation = self._candidate(verified=True)
        before = self._snapshot()
        original_version = allocation.version
        frappe.set_user(self.approver)
        try:
            result = commercial.approve_sale_outward_allocation(
                allocation.name, expected_version=original_version)
        finally:
            frappe.set_user("Administrator")
        allocation.reload()
        self.assertFalse(result["replayed"])
        self.assertEqual(allocation.state, "APPROVED")
        self.assertEqual(allocation.prepared_by, self.maker)
        self.assertEqual(allocation.verified_by, self.accounts)
        self.assertEqual(allocation.approved_by, self.approver)
        self.assertEqual(len({allocation.prepared_by, allocation.verified_by,
                              allocation.approved_by}), 3)
        self.assertEqual(allocation.version, original_version + 1)
        approvals = [event for event in json.loads(allocation.decision_history)
                     if event["action"] == "APPROVE"]
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0]["actor"], self.approver)
        self.assertEqual(self._active_qty(sale=self.sale), 30)
        self.assertEqual(self._active_qty(physical=self.physical), 30)
        once = self._snapshot()
        self.assertEqual(before["truth"], once["truth"], "Approval edited physical/source truth")
        frappe.set_user(self.approver)
        try:
            replay = commercial.approve_sale_outward_allocation(
                allocation.name, expected_version=allocation.version)
        finally:
            frappe.set_user("Administrator")
        self.assertTrue(replay["replayed"])
        self.assertEqual(once, self._snapshot(), "Replay duplicated quantity or audit effects")
