"""FSEC-001/002/003 permission regression tests (require Frappe/ERPNext site).

Run via: bench --site <site> run-tests --app fresko_universe --module fresko_universe.tests.test_fsec_permissions
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from fresko_universe.approvals import create_revision_approval, decide
from fresko_universe.deals import (
    apply_rate_rules,
    apply_revision,
    cancel_deal,
    record_dispatch,
    request_revision,
)
from fresko_universe.permissions import (
    deal_has_permission,
    deal_permission_query,
    evidence_attachment_has_permission,
    evidence_attachment_permission_query,
    evidence_attempt_has_permission,
    evidence_attempt_permission_query,
    deny_supplier_http_access,
)
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

    def test_evidence_children_supplier_first_and_orphan_attempt(self):
        evidence = frappe.get_doc({
            "doctype": "Fresko Evidence",
            "evidence_type": "Note",
            "container": self.container.name,
            "notes": "evidence child permission regression",
        }).insert(ignore_permissions=True)
        roles = {
            "supplier": {"Fresko Supplier Viewer"},
            "mixed_accounts": {"Fresko Supplier Viewer", "Fresko Accounts"},
            "mixed_manager": {"Fresko Supplier Viewer", "System Manager"},
            "accounts": {"Fresko Accounts"},
            "approver": {"Fresko Approver"},
        }
        with patch("fresko_universe.permissions.current_roles", side_effect=lambda user: roles[user]):
            for user in ("supplier", "mixed_accounts", "mixed_manager"):
                self.assertEqual(evidence_attachment_permission_query(user), "1=0")
                self.assertEqual(evidence_attempt_permission_query(user), "1=0")
                attachment = SimpleNamespace(evidence="missing-evidence", flags=SimpleNamespace(in_service=True))
                attempt = SimpleNamespace(evidence="missing-evidence")
                self.assertFalse(evidence_attachment_has_permission(attachment, "read", user))
                self.assertFalse(evidence_attachment_has_permission(attachment, "create", user))
                self.assertFalse(evidence_attachment_has_permission(attachment, "write", user))
                self.assertFalse(evidence_attempt_has_permission(attempt, "read", user))

            self.assertEqual(evidence_attachment_permission_query("accounts"), "")
            self.assertEqual(evidence_attachment_permission_query("approver"), "")
            self.assertNotEqual(evidence_attempt_permission_query("accounts"), "1=0")
            self.assertNotEqual(evidence_attempt_permission_query("approver"), "1=0")
            attachment = SimpleNamespace(evidence=evidence.name)
            attempt = SimpleNamespace(evidence=evidence.name)
            for user in ("accounts", "approver"):
                self.assertTrue(evidence_attachment_has_permission(attachment, "read", user))
                self.assertTrue(evidence_attempt_has_permission(attempt, "read", user))

    def test_pinned_validate_auth_resolves_api_identity_before_supplier_hook(self):
        from frappe.auth import validate_auth

        order = []
        def resolve_api_identity(_header):
            order.append("api_key")
            frappe.set_user("fsec_accounts@example.com")

        def run_guard():
            order.append("auth_hook")
            deny_supplier_http_access()

        request = SimpleNamespace(method="GET", path="/api/resource/Fresko Evidence Attachment")
        with patch.object(frappe, "request", request), patch.object(
            frappe, "get_request_header", return_value="token fake:key"
        ), patch("frappe.auth.validate_oauth"), patch(
            "frappe.auth.validate_auth_via_api_keys", side_effect=resolve_api_identity
        ), patch.object(
            frappe, "get_hooks", return_value=["fresko_universe.permissions.deny_supplier_http_access"]
        ), patch.object(
            frappe, "get_attr", return_value=run_guard
        ), patch("fresko_universe.permissions.current_roles", return_value={"Fresko Supplier Viewer"}):
            old_form_dict = frappe.local.form_dict
            try:
                frappe.local.form_dict = {}
                with self.assertRaises(frappe.PermissionError):
                    validate_auth()
            finally:
                frappe.local.form_dict = old_form_dict
                frappe.set_user("Administrator")
        self.assertEqual(order, ["api_key", "auth_hook"])
    def test_authenticated_supplier_http_guard(self):
        def reject(message, error_type):
            raise error_type(message)

        cases = (
            ("POST", "/api/method/login", None, True),
            ("POST", "/api/method/login", "login", True),
            ("POST", "/api/method/logout", "logout", True),
            ("GET", "/api/method/frappe.auth.get_logged_user", None, True),
            ("GET", "/api/method/frappe.auth.get_logged_user", "frappe.auth.get_logged_user", True),
            ("POST", "/api/method/login", "frappe.client.get_list", False),
            ("POST", "/api/method/logout", "frappe.client.get_list", False),
            ("GET", "/api/method/frappe.auth.get_logged_user", "logout", False),
            ("GET", "/api/method/logout", None, False),
            ("GET", "/api/resource/File", None, False),
            ("GET", "/private/files/evidence.pdf", None, False),
            ("GET", "/api/resource/Fresko Evidence Attachment", None, False),
            ("GET", "/api/resource/Fresko Evidence Attempt", None, False),
        )
        for roles in (
            {"Fresko Supplier Viewer"},
            {"Fresko Supplier Viewer", "Fresko Accounts"},
            {"Fresko Supplier Viewer", "System Manager"},
        ):
            for method, path, cmd, allowed in cases:
                fake_frappe = SimpleNamespace(
                    session=SimpleNamespace(user="supplier-user"),
                    request=SimpleNamespace(method=method, path=path),
                    local=SimpleNamespace(form_dict={} if cmd is None else {"cmd": cmd}),
                    PermissionError=frappe.PermissionError,
                    throw=reject,
                )
                with patch("fresko_universe.permissions.frappe", fake_frappe), patch(
                    "fresko_universe.permissions.current_roles", return_value=roles
                ):
                    if allowed:
                        self.assertIsNone(deny_supplier_http_access())
                    else:
                        with self.assertRaises(frappe.PermissionError):
                            deny_supplier_http_access()

        fake_admin = SimpleNamespace(
            session=SimpleNamespace(user="Administrator"),
            request=SimpleNamespace(method="GET", path="/api/resource/File"),
            local=SimpleNamespace(form_dict={}),
            PermissionError=frappe.PermissionError,
            throw=reject,
        )
        with patch("fresko_universe.permissions.frappe", fake_admin), patch(
            "fresko_universe.permissions.current_roles", return_value={"System Manager", "Fresko Supplier Viewer"}
        ):
            with self.assertRaises(frappe.PermissionError):
                deny_supplier_http_access()

        for user in ("Guest", "accounts-user"):
            fake_frappe = SimpleNamespace(
                session=SimpleNamespace(user=user),
                request=SimpleNamespace(method="GET", path="/private/files/evidence.pdf"),
                local=SimpleNamespace(form_dict={}),
            )
            with patch("fresko_universe.permissions.frappe", fake_frappe), patch(
                "fresko_universe.permissions.current_roles", return_value={"Fresko Accounts"}
            ):
                self.assertIsNone(deny_supplier_http_access())

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
        )
        apr.flags.allow_controlled_insert = True  # simulate a pre-existing/corrupt bound row
        apr.insert(ignore_permissions=True)

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
        apr_res = create_revision_approval(
            rev["revision"], "APPROVE", decision_rate=55, reason="ok approval"
        )
        frappe.set_user("fsec_sales_a@example.com")
        with self.assertRaises(frappe.PermissionError):
            apply_revision(rev["revision"], approval_name=apr_res["approval"])

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
        )
        apr.flags.allow_controlled_insert = True  # simulate legacy evidence for downstream guard
        apr.insert(ignore_permissions=True)
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

    def test_apply_revision_rejects_unbound_deal_only_approval(self):
        deal = make_deal(self.container, proposed_rate=50, qty=5)
        apply_rate_rules(deal.name)
        deal.reload()
        ev = frappe.get_doc(
            {
                "doctype": "Fresko Evidence",
                "evidence_type": "Note",
                "deal": deal.name,
                "container": self.container.name,
                "notes": "fsec unbound",
            }
        ).insert(ignore_permissions=True)
        rev = request_revision(
            deal.name,
            "approved_rate",
            55,
            reason="needs revision bind",
            supporting_evidence=ev.name,
        )
        apr = frappe.get_doc(
            {
                "doctype": "Fresko Approval",
                "deal": deal.name,
                "decision": "APPROVE",
                "decision_rate": 55,
                "proposed_rate": deal.proposed_rate,
                "rate_floor": deal.rate_floor,
                "rate_ceiling": deal.rate_ceiling,
                "approver": frappe.session.user,
                "reason": "deal-only unbound",
            }
        )
        apr.flags.allow_controlled_insert = True  # simulate legacy unbound Approval
        apr.insert(ignore_permissions=True)
        frappe.set_user("fsec_approver@example.com")
        with self.assertRaises(frappe.PermissionError):
            apply_revision(rev["revision"], approval_name=apr.name)

    def test_apply_revision_bound_ok_and_consume(self):
        deal = make_deal(self.container, proposed_rate=50, qty=5)
        apply_rate_rules(deal.name)
        deal.reload()
        ev = frappe.get_doc(
            {
                "doctype": "Fresko Evidence",
                "evidence_type": "Note",
                "deal": deal.name,
                "container": self.container.name,
                "notes": "fsec bound ok",
            }
        ).insert(ignore_permissions=True)
        rev = request_revision(
            deal.name,
            "approved_rate",
            55,
            reason="bound apply",
            supporting_evidence=ev.name,
        )
        frappe.set_user("fsec_approver@example.com")
        apr_res = create_revision_approval(
            rev["revision"], "APPROVE", decision_rate=55, reason="bound approve"
        )
        applied = apply_revision(rev["revision"], approval_name=apr_res["approval"])
        self.assertEqual(applied["status"], "Applied")
        apr = frappe.get_doc("Fresko Approval", apr_res["approval"])
        self.assertEqual(int(apr.consumed or 0), 1)
        deal.reload()
        self.assertEqual(float(deal.approved_rate), 55.0)

    def test_direct_approval_and_revision_creation_denied(self):
        deal = make_deal(self.container, proposed_rate=50, qty=5)
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc(
                {
                    "doctype": "Fresko Revision",
                    "parent_doctype": "Fresko Deal",
                    "parent_name": deal.name,
                    "fieldname": "qty",
                    "old_value": "5",
                    "new_value": "4",
                    "changed_by": "Guest",
                    "changed_at": "2000-01-01 00:00:00",
                    "reason": "direct forged revision",
                    "status": "Pending",
                }
            ).insert(ignore_permissions=True)
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc(
                {
                    "doctype": "Fresko Approval",
                    "deal": deal.name,
                    "decision": "APPROVE",
                    "approver": "Guest",
                    "decided_at": "2000-01-01 00:00:00",
                    "reason": "direct forged approval",
                }
            ).insert(ignore_permissions=True)

    def test_controlled_insert_forces_server_provenance(self):
        deal = make_deal(self.container, proposed_rate=50, qty=5)
        rev = frappe.get_doc(
            {
                "doctype": "Fresko Revision",
                "parent_doctype": "Fresko Deal",
                "parent_name": deal.name,
                "fieldname": "qty",
                "old_value": "5",
                "new_value": "4",
                "changed_by": "Guest",
                "changed_at": "2000-01-01 00:00:00",
                "reason": "server provenance revision",
                "status": "Pending",
            }
        )
        rev.flags.allow_controlled_insert = True
        rev.insert(ignore_permissions=True)
        self.assertEqual(rev.changed_by, frappe.session.user)
        self.assertNotEqual(str(rev.changed_at), "2000-01-01 00:00:00")

        apr = frappe.get_doc(
            {
                "doctype": "Fresko Approval",
                "deal": deal.name,
                "revision": rev.name,
                "decision": "APPROVE",
                "approver": "Guest",
                "decided_at": "2000-01-01 00:00:00",
                "reason": "server provenance approval",
            }
        )
        apr.flags.allow_controlled_insert = True
        apr.insert(ignore_permissions=True)
        self.assertEqual(apr.approver, frappe.session.user)
        self.assertNotEqual(str(apr.decided_at), "2000-01-01 00:00:00")

    def test_revision_allowlist_is_enforced_at_every_boundary(self):
        deal = make_deal(self.container, proposed_rate=50, qty=5)
        apply_rate_rules(deal.name)
        deal.reload()

        with self.assertRaises(frappe.ValidationError):
            request_revision(deal.name, "container", "OTHER", reason="container move")

        malicious = frappe.get_doc(
            {
                "doctype": "Fresko Revision",
                "parent_doctype": "Fresko Deal",
                "parent_name": deal.name,
                "fieldname": "status",
                "old_value": deal.status,
                "new_value": "Reconciled",
                "reason": "attempt arbitrary field",
                "status": "Pending",
            }
        )
        malicious.flags.allow_controlled_insert = True
        with self.assertRaises(frappe.ValidationError):
            malicious.insert(ignore_permissions=True)

        legitimate = request_revision(
            deal.name,
            "item",
            deal.item,
            reason="create row for apply boundary",
        )
        frappe.db.set_value(
            "Fresko Revision", legitimate["revision"], "fieldname", "status",
            update_modified=False,
        )
        with self.assertRaises(frappe.ValidationError):
            apply_revision(legitimate["revision"])

    def test_approver_cannot_mint_revision_oversell_evidence(self):
        deal = make_deal(self.container, proposed_rate=50, qty=5)
        apply_rate_rules(deal.name)
        ev = frappe.get_doc(
            {
                "doctype": "Fresko Evidence",
                "evidence_type": "Note",
                "deal": deal.name,
                "container": self.container.name,
                "notes": "revision oversell attack",
            }
        ).insert(ignore_permissions=True)
        rev = request_revision(
            deal.name,
            "qty",
            4,
            reason="oversell-label attack",
            supporting_evidence=ev.name,
        )
        frappe.set_user("fsec_approver@example.com")
        with self.assertRaises(frappe.ValidationError):
            create_revision_approval(
                rev["revision"],
                "OVERSELL_OVERRIDE",
                reason="ordinary approver cannot mint D10 evidence",
            )
