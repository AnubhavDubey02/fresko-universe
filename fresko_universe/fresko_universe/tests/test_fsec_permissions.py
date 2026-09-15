"""FSEC-001/002/003 permission regression tests (require Frappe/ERPNext site).

Run via: bench --site <site> run-tests --app fresko_universe --module fresko_universe.tests.test_fsec_permissions
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from fresko_universe.approvals import decide
from fresko_universe.deals import (
    apply_rate_rules,
    apply_revision,
    cancel_deal,
    record_dispatch,
    request_revision,
)
from fresko_universe.permissions import deal_has_permission, deal_permission_query
from fresko_universe.tests.utils import ensure_masters, make_container, make_deal


def _ensure_user(email: str, roles: list[str]) -> str:
    if not frappe.db.exists("User", email):
        u = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": email.split("@")[0],
                "send_welcome_email": 0,
                "user_type": "System User",
            }
        )
        u.insert(ignore_permissions=True)
    user = frappe.get_doc("User", email)
    existing = {r.role for r in user.roles}
    for role in roles:
        if role not in existing and frappe.db.exists("Role", role):
            user.append("roles", {"role": role})
    user.save(ignore_permissions=True)
    frappe.db.commit()
    return email


class TestFSECPermissions(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.masters = ensure_masters()
        _ensure_user("fsec_sales_a@example.com", ["Fresko Salesperson"])
        _ensure_user("fsec_sales_b@example.com", ["Fresko Salesperson"])
        _ensure_user("fsec_approver@example.com", ["Fresko Approver"])
        _ensure_user("fsec_accounts@example.com", ["Fresko Accounts"])

    def setUp(self):
        frappe.set_user("Administrator")
        self.container = make_container(
            self.masters,
            container_no=f"FSEC-{frappe.generate_hash(length=6)}",
            rate_floor=10,
            rate_ceiling=200,
        )

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_accounts_denied_cancel_and_apply_rate(self):
        deal = make_deal(self.container, proposed_rate=50, qty=5)
        frappe.db.set_value("Fresko Deal", deal.name, "owner", "fsec_sales_a@example.com")
        frappe.set_user("fsec_accounts@example.com")
        with self.assertRaises(frappe.PermissionError):
            cancel_deal(deal.name, "accounts should not cancel")
        with self.assertRaises(frappe.PermissionError):
            apply_rate_rules(deal.name)

    def test_salesperson_cancel_own_allowed_other_denied(self):
        deal = make_deal(self.container, proposed_rate=50, qty=5)
        frappe.db.set_value(
            "Fresko Deal",
            deal.name,
            {"owner": "fsec_sales_a@example.com", "salesperson_user": "fsec_sales_a@example.com"},
        )
        frappe.set_user("fsec_sales_a@example.com")
        cancel_deal(deal.name, "owner cancel ok")
        deal.reload()
        self.assertEqual(deal.status, "Cancelled")

        deal2 = make_deal(self.container, proposed_rate=50, qty=5)
        frappe.db.set_value(
            "Fresko Deal",
            deal2.name,
            {"owner": "fsec_sales_a@example.com", "salesperson_user": "fsec_sales_a@example.com"},
        )
        frappe.set_user("fsec_sales_b@example.com")
        with self.assertRaises(frappe.PermissionError):
            cancel_deal(deal2.name, "other salesperson")

    def test_salesperson_denied_record_dispatch(self):
        deal = make_deal(self.container, proposed_rate=50, qty=5)
        apply_rate_rules(deal.name)
        deal.reload()
        frappe.db.set_value("Fresko Deal", deal.name, "owner", "fsec_sales_a@example.com")
        frappe.set_user("fsec_sales_a@example.com")
        with self.assertRaises(frappe.PermissionError):
            record_dispatch(deal.name, 1)

    def test_apply_revision_rejects_mismatched_approval_deal(self):
        d1 = make_deal(self.container, proposed_rate=50, qty=5)
        apply_rate_rules(d1.name)
        d1.reload()
        d2 = make_deal(self.container, proposed_rate=40, qty=5)
        apply_rate_rules(d2.name)
        d2.reload()

        ev = frappe.get_doc(
            {
                "doctype": "Fresko Evidence",
                "evidence_type": "Note",
                "deal": d1.name,
                "container": self.container.name,
                "notes": "fsec mismatch",
            }
        ).insert(ignore_permissions=True)
        rev = request_revision(
            d1.name,
            "approved_rate",
            55,
            reason="fsec mismatch test",
            supporting_evidence=ev.name,
        )
        # Approval bound to d2, not d1
        apr = frappe.get_doc(
            {
                "doctype": "Fresko Approval",
                "deal": d2.name,
                "decision": "APPROVE",
                "decision_rate": 55,
                "proposed_rate": d2.proposed_rate,
                "rate_floor": d2.rate_floor,
                "rate_ceiling": d2.rate_ceiling,
                "approver": frappe.session.user,
                "reason": "wrong deal approval",
            }
        ).insert(ignore_permissions=True)

        frappe.set_user("fsec_approver@example.com")
        with self.assertRaises(frappe.PermissionError):
            apply_revision(rev["revision"], approval_name=apr.name)

    def test_apply_revision_rejects_non_approver(self):
        deal = make_deal(self.container, proposed_rate=50, qty=5)
        apply_rate_rules(deal.name)
        deal.reload()
        frappe.db.set_value("Fresko Deal", deal.name, "owner", "fsec_sales_a@example.com")
        ev = frappe.get_doc(
            {
                "doctype": "Fresko Evidence",
                "evidence_type": "Note",
                "deal": deal.name,
                "container": self.container.name,
                "notes": "fsec non-approver",
            }
        ).insert(ignore_permissions=True)
        frappe.set_user("fsec_sales_a@example.com")
        rev = request_revision(
            deal.name,
            "approved_rate",
            55,
            reason="salesperson request",
            supporting_evidence=ev.name,
        )
        frappe.set_user("Administrator")
        apr = frappe.get_doc(
            {
                "doctype": "Fresko Approval",
                "deal": deal.name,
                "decision": "APPROVE",
                "decision_rate": 55,
                "proposed_rate": deal.proposed_rate,
                "rate_floor": deal.rate_floor,
                "rate_ceiling": deal.rate_ceiling,
                "approver": "Administrator",
                "reason": "ok approval",
            }
        ).insert(ignore_permissions=True)
        frappe.set_user("fsec_sales_a@example.com")
        with self.assertRaises(frappe.PermissionError):
            apply_revision(rev["revision"], approval_name=apr.name)

    def test_apply_revision_rejects_reject_decision(self):
        deal = make_deal(self.container, proposed_rate=50, qty=5)
        apply_rate_rules(deal.name)
        deal.reload()
        ev = frappe.get_doc(
            {
                "doctype": "Fresko Evidence",
                "evidence_type": "Note",
                "deal": deal.name,
                "container": self.container.name,
                "notes": "fsec reject decision",
            }
        ).insert(ignore_permissions=True)
        rev = request_revision(
            deal.name,
            "approved_rate",
            55,
            reason="should fail on REJECT approval",
            supporting_evidence=ev.name,
        )
        apr = frappe.get_doc(
            {
                "doctype": "Fresko Approval",
                "deal": deal.name,
                "decision": "REJECT",
                "decision_rate": 55,
                "proposed_rate": deal.proposed_rate,
                "rate_floor": deal.rate_floor,
                "rate_ceiling": deal.rate_ceiling,
                "approver": frappe.session.user,
                "reason": "reject cannot authorize",
            }
        ).insert(ignore_permissions=True)
        frappe.set_user("fsec_approver@example.com")
        with self.assertRaises(frappe.PermissionError):
            apply_revision(rev["revision"], approval_name=apr.name)

    def test_permission_query_two_sales_users(self):
        frappe.set_user("Administrator")
        q_a = deal_permission_query("fsec_sales_a@example.com")
        q_b = deal_permission_query("fsec_sales_b@example.com")
        self.assertIn("fsec_sales_a@example.com", q_a)
        self.assertIn("fsec_sales_b@example.com", q_b)
        self.assertNotEqual(q_a, q_b)

        d_a = make_deal(self.container, proposed_rate=50, qty=2)
        frappe.db.set_value(
            "Fresko Deal",
            d_a.name,
            {"owner": "fsec_sales_a@example.com", "salesperson_user": "fsec_sales_a@example.com"},
        )
        d_b = make_deal(self.container, proposed_rate=50, qty=2)
        frappe.db.set_value(
            "Fresko Deal",
            d_b.name,
            {"owner": "fsec_sales_b@example.com", "salesperson_user": "fsec_sales_b@example.com"},
        )
        d_a.reload()
        d_b.reload()
        self.assertTrue(deal_has_permission(d_a, "read", user="fsec_sales_a@example.com"))
        self.assertFalse(deal_has_permission(d_b, "read", user="fsec_sales_a@example.com"))
        self.assertTrue(deal_has_permission(d_b, "read", user="fsec_sales_b@example.com"))
        self.assertFalse(deal_has_permission(d_a, "write", user="fsec_sales_b@example.com"))
