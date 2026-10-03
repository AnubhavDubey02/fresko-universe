"""Commercial Sale integration gates for a migrated, pinned Frappe/MariaDB site.

Run with ``bench --site <site> run-tests --app fresko_universe --module
fresko_universe.tests.test_commercial_sale``. These tests exercise public server
methods and real transactions; they do not substitute mocked offline truth for
physical movement, permission, or concurrent allocation checks.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from decimal import Decimal
from queue import Queue

import frappe
from frappe import client
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_datetime
from frappe.utils.file_manager import save_file

from fresko_universe import commercial, outward
from fresko_universe.fresko_core.physical import physical_snapshot
from fresko_universe.tests.utils import ensure_masters, make_container, make_deal


SALE = "Fresko Commercial Sale"
ALIAS = "Fresko Party Alias Mapping"
ALLOCATION = "Fresko Sale Outward Allocation"


def _ensure_user(email, roles):
    if not frappe.db.exists("User", email):
        frappe.get_doc({
            "doctype": "User", "email": email, "first_name": email.split("@")[0],
            "send_welcome_email": 0, "user_type": "System User",
        }).insert(ignore_permissions=True)
    user = frappe.get_doc("User", email)
    existing = {row.role for row in user.roles}
    for role in roles:
        if not frappe.db.exists("Role", role):
            frappe.throw(f"Required commercial test role is missing: {role}")
        if role not in existing:
            user.append("roles", {"role": role})
    user.save(ignore_permissions=True)
    return email


class TestCommercialSale(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.masters = ensure_masters()
        cls.maker = _ensure_user("commercial_maker@example.com", ["Fresko Salesperson"])
        cls.accounts = _ensure_user("commercial_accounts@example.com", ["Fresko Accounts"])
        cls.approver = _ensure_user("commercial_approver@example.com", ["Fresko Approver"])
        cls.manager = _ensure_user("commercial_manager@example.com", ["System Manager"])
        if not frappe.db.exists("Role", "Fresko Supplier Viewer"):
            frappe.get_doc({"doctype": "Role", "role_name": "Fresko Supplier Viewer", "desk_access": 0}).insert(ignore_permissions=True)
        cls.supplier = _ensure_user("commercial_supplier@example.com", ["Fresko Supplier Viewer", "Fresko Accounts"])
        cls.other_maker = _ensure_user("commercial_other_maker@example.com", ["Fresko Salesperson"])
        cls.all_roles = _ensure_user("commercial_all_roles@example.com", [
            "Fresko Salesperson", "Fresko Accounts", "Fresko Approver",
        ])
        frappe.db.commit()

    def setUp(self):
        frappe.set_user("Administrator")
        self.token = frappe.generate_hash(length=10)
        self.container = make_container(
            self.masters, container_no=f"COMMERCIAL-{self.token}", inward_qty=2000,
            lots=[
                {"lot_no": "42076", "inward_qty": 1000, "uom": self.masters["uom"]},
                {"lot_no": "42074", "inward_qty": 1000, "uom": self.masters["uom"]},
            ],
        )
        self.evidence = self._evidence("commercial source")
        self.customer = self._customer("Approved Buyer")
        self.second_customer = self._customer("Different Buyer")

    def tearDown(self):
        frappe.set_user("Administrator")

    def _customer(self, label):
        return frappe.get_doc({
            "doctype": "Customer", "customer_name": f"{label} {self.token}",
            "customer_type": "Company",
            "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
            "territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
        }).insert(ignore_permissions=True).name

    def _evidence(self, label, *, container=None, photo=False):
        frappe.set_user("Administrator")
        evidence = frappe.get_doc({
            "doctype": "Fresko Evidence", "container": (container or self.container).name,
            "evidence_type": "Photo" if photo else "Note",
            "notes": f"commercial test {self.token}: {label}",
        }).insert(ignore_permissions=True)
        if photo:
            # A compact synthetic source fixture, not the confidential business photo.
            png = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
                "/x8AAwMCAO+aWQAAAABJRU5ErkJggg=="
            )
            file_doc = save_file(f"commercial-{self.token}.png", png, "Fresko Evidence", evidence.name, is_private=1)
            self.addCleanup(self._remove_test_file, file_doc.name)
            evidence.file = file_doc.file_url
            evidence.save(ignore_permissions=True)
        return evidence

    @staticmethod
    def _remove_test_file(name):
        frappe.set_user("Administrator")
        if frappe.db.exists("File", name):
            frappe.delete_doc("File", name, ignore_permissions=True)

    def _line(self, qty="100", rate="825", *, lot="42076", ref="1", **changes):
        row = {
            "line_key": f"source-{ref}", "item": self.masters["item"], "source_line_ref": ref,
            "container_lot": next((row.name for row in self.container.lots if row.lot_no == lot), None),
            "raw_lot_text": lot, "lot_state": "KNOWN" if lot else "UNKNOWN",
            "qty": qty, "qty_state": "KNOWN" if qty is not None else "UNKNOWN",
            "uom": self.masters["uom"], "price_state": "PROPOSED" if rate is not None else "UNKNOWN",
            "rate": rate, "rate_basis": "RATE_ASSERTION" if rate is not None else "NONE",
            "evidence": self.evidence.name,
        }
        row.update(changes)
        return row

    def _create(self, *, lines=None, event="sale", user=None, **changes):
        args = {
            "company": self.container.company, "container": self.container.name,
            "sale_at": "2026-10-01 10:00:00", "source_evidence": self.evidence.name,
            "source_event_id": f"{self.token}:{event}", "lines": lines or [self._line()],
            "raw_party_alias": f"Raw Buyer {self.token}", "party_state": "KNOWN",
            "currency": self.masters["currency"],
        }
        args.update(changes)
        frappe.set_user(user or self.maker)
        result = commercial.create_sale(**args)
        return frappe.get_doc(SALE, result["name"])

    def _approve_sale(self, sale):
        frappe.set_user(sale.prepared_by)
        commercial.submit_sale(sale.name)
        frappe.set_user(self.accounts)
        commercial.verify_sale(sale.name)
        frappe.set_user(self.approver)
        commercial.approve_sale(sale.name)
        sale.reload()
        self.assertEqual(sale.status, "APPROVED")
        return sale

    def _mapping(self, raw=None, customer=None, *, event="alias", user=None, **changes):
        args = {
            "company": self.container.company, "raw_alias": raw or f"Raw Buyer {self.token}",
            "proposed_customer": customer or self.customer, "evidence": self.evidence.name,
            "source_event_id": f"{self.token}:{event}", "normalization_scope": "EXACT_COMPANY_V1",
        }
        args.update(changes)
        frappe.set_user(user or self.maker)
        return frappe.get_doc(ALIAS, commercial.propose_alias_mapping(**args)["name"])

    def _approve_mapping(self, mapping):
        frappe.set_user(self.accounts)
        commercial.verify_alias_mapping(mapping.name)
        frappe.set_user(self.approver)
        commercial.approve_alias_mapping(mapping.name)
        mapping.reload()
        self.assertEqual(mapping.status, "APPROVED")
        return mapping

    def _outward(self, qty=100, *, event="outward", lot="42076", movement_at="2026-10-02 11:00:00"):
        frappe.set_user(self.maker)
        result = outward.create(
            container=self.container.name, movement_at=movement_at,
            source_evidence=self.evidence.name, source_event_id=f"{self.token}:{event}",
            lines=[{
                "source_line_ref": "1", "raw_lot_text": lot, "lot_no": lot,
                "qty": qty, "uom": self.masters["uom"],
                "raw_qty_text": str(qty), "raw_uom_text": self.masters["uom"],
            }],
        )
        doc = frappe.get_doc("Fresko Outward", result["name"])
        outward.submit_for_review(doc.name)
        frappe.set_user(self.approver)
        outward.post(doc.name)
        doc.reload()
        return doc

    def _allocation(self, sale, physical, qty, *, event="allocation", line=0, **changes):
        args = {
            "sale_name": sale.name, "sale_line_key": sale.lines[line].line_key,
            "outward": physical.name, "outward_line_key": physical.lines[0].line_key,
            "qty": str(qty), "uom": self.masters["uom"], "evidence": self.evidence.name,
            "source_event_id": f"{self.token}:{event}",
        }
        args.update(changes)
        frappe.set_user(self.maker)
        return frappe.get_doc(ALLOCATION, commercial.propose_sale_outward_allocation(**args)["name"])

    def _verify_allocation(self, allocation):
        frappe.set_user(self.accounts)
        commercial.verify_sale_outward_allocation(allocation.name)
        allocation.reload()
        return allocation

    def _approve_allocation(self, allocation):
        self._verify_allocation(allocation)
        frappe.set_user(self.approver)
        commercial.approve_sale_outward_allocation(allocation.name)
        allocation.reload()
        self.assertEqual(allocation.state, "APPROVED")
        return allocation

    @staticmethod
    def _active_qty(*, sale=None, physical=None):
        filters = {"state": "APPROVED"}
        if sale:
            filters["sale"] = sale.name
        if physical:
            filters["outward"] = physical.name
        return sum((Decimal(row.qty) for row in frappe.get_all(ALLOCATION, filters=filters, fields=["qty"])), Decimal(0))

    def _exceptions(self, sale, kind):
        return frappe.get_all("Fresko Exception", filters={
            "sale": sale.name, "exception_type": kind, "status": ("in", ["Open", "In Progress"]),
        }, pluck="name")

    def test_reconciliation_totals_keep_unknown_money_and_partial_physical_allocation(self):
        physical = self._outward(100)
        sale = self._approve_sale(self._create(lines=[self._line("80", None)]))
        self._approve_allocation(self._allocation(sale, physical, 60))
        frappe.set_user(self.accounts)
        view = commercial.get_container_reconciliation(self.container.name, as_of="2099-12-31 23:59:59")
        totals = view["totals_by_uom"][self.masters["uom"]]
        expected = {"commercially_sold_qty": 80, "priced_qty": 0, "unpriced_qty": 80,
                    "physically_allocated_qty": 60, "physically_unallocated_qty": 40,
                    "sold_not_physically_allocated_qty": 20, "physical_qty": 100}
        for field, amount in expected.items():
            self.assertEqual(Decimal(totals[field]), Decimal(amount), field)
        self.assertEqual(view["unresolved_buyer_count"], 1)
        self.assertEqual(view["unknown_quantity_count"], 0)
        self.assertEqual(view["confirmed_value_by_currency"], {})
        projected = commercial.get_sale_as_of(sale.name, "2099-12-31 23:59:59")
        self.assertIsNone(projected["total_commercial_amount"])
        self.assertEqual(projected["pending_amount_line_count"], 1)
        self.assertEqual(Decimal(projected["lines"][0]["remaining_qty"]), Decimal(20))
        self.assertEqual(projected["reconciliation_state"], "PENDING")
        outward_view = commercial.get_outward_reconciliation(physical.name, as_of="2099-12-31 23:59:59")
        self.assertEqual(Decimal(outward_view["totals_by_uom"][self.masters["uom"]]["remaining_qty"]), Decimal(40))
        self.assertIn("ALIAS_UNRESOLVED", outward_view["unresolved_flags"])

    def test_corrected_sale_compensation_has_one_atomic_recording_time(self):
        sale = self._approve_sale(self._create())
        allocation = self._approve_allocation(self._allocation(sale, self._outward(), 100))
        frappe.set_user(self.maker)
        result = commercial.supersede_sale(sale.name, source_event_id=f"{self.token}:atomic-correction",
            reason="Evidence-backed quantity correction", source_evidence=self.evidence.name,
            changes={"lines": [self._line("90", "825")]})
        successor = self._approve_sale(frappe.get_doc(SALE, result["name"]))
        sale.reload()
        allocation.reload()
        times = {json.loads(record.decision_history)[-1]["recorded_at"]
                 for record in (sale, allocation, successor)}
        self.assertEqual(len(times), 1, "A cutoff cannot expose half of an atomic correction")
        self.assertEqual(allocation.state, "REVERSED")
        self.assertEqual(sale.status, "SUPERSEDED")

    def test_multilot_sale_preserves_source_and_decimal_total(self):
        sale = self._create(lines=[self._line("80", "825"), self._line("20", "825", lot="42074", ref="2")])
        self.assertEqual(len(sale.lines), 2)
        self.assertEqual(sum(Decimal(row.qty) for row in sale.lines), Decimal("100"))
        self.assertEqual(sum(Decimal(row.amount) for row in sale.lines), Decimal("82500"))
        self.assertNotEqual(sale.lines[0].line_key, sale.lines[1].line_key)
        self.assertEqual(sale.raw_party_alias, f"Raw Buyer {self.token}")
        self.assertFalse(sale.customer)
        self.assertEqual(sale.status, "DRAFT")
        self.assertTrue(all(row.price_state == "PROPOSED" for row in sale.lines))
        self.assertEqual(self._active_qty(sale=sale), 0)
        self.assertEqual(physical_snapshot(self.container.name)["posted_physical_total"], 0)

    def test_price_buckets_have_amount_but_no_invented_gp_allocation(self):
        sale = self._create(lines=[
            self._line("47", "1350", lot=None, rate_basis="PRICE_BUCKET", bucket_key="bucket-1350"),
            self._line("133", "1300", lot=None, ref="2", rate_basis="PRICE_BUCKET", bucket_key="bucket-1300"),
        ])
        self._approve_sale(sale)
        self.assertEqual(sum(Decimal(row.amount) for row in sale.lines), Decimal("236350"))
        self.assertTrue(all(not row.container_lot for row in sale.lines))
        self.assertEqual(self._active_qty(sale=sale), 0)
        self.assertTrue(self._exceptions(sale, "PRICE_BUCKET_UNALLOCATED"))
        self.assertFalse(frappe.db.exists("Fresko Outward", {"container": self.container.name}))

    def test_unknown_party_lot_quantity_and_rate_survive_approval(self):
        sale = self._create(raw_party_alias=None, party_state="UNKNOWN", lines=[self._line(None, None, lot=None)])
        self._approve_sale(sale)
        self.assertFalse(sale.raw_party_alias)
        self.assertFalse(sale.customer)
        self.assertEqual(sale.party_state, "UNKNOWN")
        self.assertEqual(sale.lines[0].qty_state, "UNKNOWN")
        self.assertFalse(sale.lines[0].qty)
        self.assertEqual(sale.lines[0].price_state, "UNKNOWN")
        self.assertFalse(sale.lines[0].amount)
        for kind in ("PARTY_UNKNOWN", "LOT_UNKNOWN", "RATE_UNKNOWN"):
            self.assertTrue(self._exceptions(sale, kind), kind)

    def test_known_party_and_lot_require_their_raw_source(self):
        for changes in ({"raw_party_alias": None, "party_state": "KNOWN"},
                        {"lines": [self._line(lot=None, lot_state="KNOWN")]}):
            with self.subTest(changes=changes), self.assertRaises(frappe.ValidationError):
                self._create(**changes)

    def test_decimal_replay_normalizes_text_but_changed_amount_conflicts(self):
        sale = self._create(lines=[self._line("80.000", "825.00")])
        replay = self._create(lines=[self._line("80", "825")])
        self.assertEqual(replay.name, sale.name)
        self.assertEqual(replay.payload_sha256, sale.payload_sha256)
        with self.assertRaisesRegex(frappe.ValidationError, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self._create(lines=[self._line("81", "825")])
        sale.reload()
        self.assertEqual(Decimal(sale.lines[0].qty), Decimal("80"))
        self.assertEqual(frappe.db.count(SALE, {"container": self.container.name}), 1)

    def test_invalid_decimal_forms_cannot_leave_partial_sale(self):
        for value in ("1e2", "NaN", "Infinity", "-1", "0", 100.1):
            with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
                self._create(event=f"bad-{value}", lines=[self._line(value)])
        self.assertEqual(frappe.db.count(SALE, {"container": self.container.name}), 0)

    def test_duplicate_source_lines_and_buckets_are_rejected_atomically(self):
        cases = [
            [self._line(), self._line()],
            [self._line(rate_basis="PRICE_BUCKET", bucket_key="same"),
             self._line(ref="2", rate_basis="PRICE_BUCKET", bucket_key="same")],
        ]
        for index, lines in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(frappe.ValidationError):
                self._create(event=f"duplicate-{index}", lines=lines)
        self.assertEqual(frappe.db.count(SALE, {"container": self.container.name}), 0)

    def test_caller_cannot_forge_final_price_or_server_identity(self):
        for changes in ({"price_state": "FINAL"}, {"amount": "1"}):
            with self.subTest(changes=changes), self.assertRaises(frappe.ValidationError):
                self._create(lines=[self._line(**changes)])

    def test_sale_maker_accounts_approver_are_three_distinct_actors(self):
        sale = self._create(user=self.all_roles)
        frappe.set_user(self.all_roles)
        commercial.submit_sale(sale.name)
        with self.assertRaises(frappe.PermissionError):
            commercial.verify_sale(sale.name)
        frappe.set_user(self.accounts)
        commercial.verify_sale(sale.name)
        frappe.set_user(self.all_roles)
        with self.assertRaises(frappe.PermissionError):
            commercial.approve_sale(sale.name)
        frappe.set_user(self.approver)
        commercial.approve_sale(sale.name)
        sale.reload()
        self.assertEqual({sale.prepared_by, sale.verified_by, sale.approved_by}, {self.all_roles, self.accounts, self.approver})

    def test_wrong_role_and_system_manager_cannot_routine_approve(self):
        sale = self._create()
        commercial.submit_sale(sale.name)
        for user in (self.maker, self.approver, self.manager):
            frappe.set_user(user)
            with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
                commercial.verify_sale(sale.name)
        frappe.set_user(self.accounts)
        commercial.verify_sale(sale.name)
        for user in (self.maker, self.accounts, self.manager):
            frappe.set_user(user)
            with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
                commercial.approve_sale(sale.name)

    def test_sale_cannot_skip_review_or_overwrite_a_stale_version(self):
        sale = self._create()
        frappe.set_user(self.approver)
        with self.assertRaises(frappe.ValidationError):
            commercial.approve_sale(sale.name)
        old_version = sale.version
        frappe.set_user(self.maker)
        commercial.submit_sale(sale.name)
        frappe.set_user(self.accounts)
        with self.assertRaisesRegex(frappe.ValidationError, "STALE_VERSION"):
            commercial.verify_sale(sale.name, expected_version=old_version)
        sale.reload()
        self.assertEqual(sale.status, "REVIEW_PENDING")

    def test_insufficient_sale_evidence_rejection_retains_source(self):
        sale = self._create()
        commercial.submit_sale(sale.name)
        frappe.set_user(self.approver)
        commercial.reject_sale(sale.name, reason="Exact source needs checking")
        sale.reload()
        self.assertEqual(sale.status, "REJECTED")
        self.assertEqual(sale.source_evidence, self.evidence.name)
        self.assertEqual(Decimal(sale.lines[0].rate), Decimal("825"))
        self.assertEqual(self._active_qty(sale=sale), 0)

    def test_alias_is_pending_until_accounts_and_approver_decide(self):
        mapping = self._mapping(raw=f"  Exact Raw Buyer {self.token}  ")
        self.assertEqual(mapping.raw_alias, f"  Exact Raw Buyer {self.token}  ")
        self.assertEqual(mapping.status, "PROPOSED")
        frappe.set_user(self.approver)
        with self.assertRaises(frappe.ValidationError):
            commercial.approve_alias_mapping(mapping.name)
        self._approve_mapping(mapping)
        self.assertEqual(mapping.proposed_customer, self.customer)
        self.assertEqual(mapping.proposed_by, self.maker)
        self.assertEqual(mapping.verified_by, self.accounts)
        self.assertEqual(mapping.approved_by, self.approver)
        self.assertEqual(mapping.raw_alias, f"  Exact Raw Buyer {self.token}  ")

    def test_approved_exact_alias_is_reused_without_editing_raw_party(self):
        raw = f"  Exact Buyer {self.token}  "
        mapping = self._approve_mapping(self._mapping(raw=raw))
        first = self._create(raw_party_alias=raw)
        second = self._create(raw_party_alias=raw, event="sale-2")
        for sale in (first, second):
            self.assertEqual(sale.raw_party_alias, raw)
            self.assertEqual(sale.customer, self.customer)
            self.assertEqual(sale.alias_mapping, mapping.name)
            self.assertEqual(sale.alias_resolution, "VERIFIED")

    def test_spelling_whitespace_and_case_do_not_guess_alias_truth(self):
        raw = f"Exact Buyer {self.token}"
        self._approve_mapping(self._mapping(raw=raw))
        for index, candidate in enumerate((raw.lower(), f" {raw}", raw.replace("Buyer", "Byer"))):
            sale = self._create(raw_party_alias=candidate, event=f"spelling-{index}")
            self.assertFalse(sale.customer)
            self.assertFalse(sale.alias_mapping)
            self.assertTrue(self._exceptions(sale, "ALIAS_UNRESOLVED"))

    def test_alias_approved_later_resolves_sale_without_changing_source(self):
        sale = self._create()
        original_digest = sale.payload_sha256
        self._approve_sale(sale)
        mapping = self._approve_mapping(self._mapping())
        sale.reload()
        self.assertEqual(sale.customer, self.customer)
        self.assertEqual(sale.alias_mapping, mapping.name)
        self.assertEqual(sale.alias_resolution, "VERIFIED")
        self.assertEqual(sale.payload_sha256, original_digest)
        self.assertEqual(sale.raw_party_alias, f"Raw Buyer {self.token}")

    def test_wrong_customer_rejection_does_not_resolve_alias(self):
        sale = self._create()
        mapping = self._mapping(customer=self.second_customer)
        frappe.set_user(self.accounts)
        commercial.verify_alias_mapping(mapping.name)
        frappe.set_user(self.approver)
        commercial.reject_alias_mapping(mapping.name, reason="Source belongs to a different Customer")
        mapping.reload()
        sale.reload()
        self.assertEqual(mapping.status, "REJECTED")
        self.assertEqual(mapping.proposed_customer, self.second_customer)
        self.assertFalse(sale.customer)
        self.assertEqual(mapping.evidence, self.evidence.name)

    def test_alias_replay_checks_digest_and_unauthorized_redelivery(self):
        mapping = self._mapping()
        self.assertEqual(self._mapping().name, mapping.name)
        with self.assertRaisesRegex(frappe.ValidationError, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self._mapping(customer=self.second_customer)
        frappe.set_user(self.supplier)
        with self.assertRaises(frappe.PermissionError):
            commercial.propose_alias_mapping(
                company=self.container.company, raw_alias=mapping.raw_alias,
                proposed_customer=self.customer, evidence=self.evidence.name,
                source_event_id=f"{self.token}:alias", normalization_scope="EXACT_COMPANY_V1",
            )
        self.assertEqual(frappe.db.count(ALIAS, {"raw_alias": mapping.raw_alias}), 1)

    def test_alias_three_actor_rule_cannot_be_bypassed_with_all_roles(self):
        mapping = self._mapping(user=self.all_roles)
        frappe.set_user(self.all_roles)
        with self.assertRaises(frappe.PermissionError):
            commercial.verify_alias_mapping(mapping.name)
        frappe.set_user(self.accounts)
        commercial.verify_alias_mapping(mapping.name)
        frappe.set_user(self.all_roles)
        with self.assertRaises(frappe.PermissionError):
            commercial.approve_alias_mapping(mapping.name)

    def test_sale_direct_client_write_insert_and_delete_are_denied(self):
        sale = self._create()
        frappe.set_user(self.manager)
        for field, value in (("customer", self.customer), ("status", "APPROVED"), ("raw_party_alias", "forged")):
            with self.subTest(field=field), self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                client.set_value(SALE, sale.name, field, value)
        forged = sale.as_dict()
        forged.pop("name")
        forged["source_event_id"] = f"{self.token}:forged-insert"
        forged["flags"] = {"in_service": True, "in_commercial_service": True}
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            client.insert(forged)
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            client.delete(SALE, sale.name)
        sale.reload()
        self.assertEqual(sale.status, "DRAFT")
        self.assertEqual(sale.raw_party_alias, f"Raw Buyer {self.token}")

    def test_controller_rejects_ignore_permissions_save_and_delete(self):
        sale = self._create()
        frappe.set_user("Administrator")
        sale.flags.in_service = True
        sale.flags.in_commercial_service = True
        sale.lines[0].rate = "1"
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            sale.save(ignore_permissions=True)
        sale.reload()
        self.assertEqual(Decimal(sale.lines[0].rate), Decimal("825"))
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            frappe.delete_doc(SALE, sale.name, ignore_permissions=True)

    def test_supplier_internal_read_list_replay_and_projection_denied(self):
        mapping = self._approve_mapping(self._mapping())
        sale = self._approve_sale(self._create())
        physical = self._outward()
        allocation = self._approve_allocation(self._allocation(sale, physical, 100))
        frappe.set_user(self.maker)
        deal = make_deal(self.container, lot_no="42076", qty=1)
        frappe.set_user(self.supplier)
        for doctype, name in ((SALE, sale.name), (ALIAS, mapping.name), (ALLOCATION, allocation.name),
                              ("Customer", self.customer), ("Fresko Deal", deal.name)):
            with self.subTest(doctype=doctype), self.assertRaises(frappe.PermissionError):
                client.get(doctype, name)
        for doctype in (SALE, ALIAS, ALLOCATION, "Customer", "Fresko Deal"):
            with self.subTest(doctype=doctype):
                try:
                    rows = client.get_list(doctype, fields=["name"])
                except frappe.PermissionError:
                    rows = []
                self.assertEqual(rows, [])
        for call in (
            lambda: commercial.get_sale_as_of(sale.name, "2099-01-01 00:00:00"),
            lambda: commercial.get_container_reconciliation(self.container.name),
            lambda: commercial.get_outward_reconciliation(physical.name),
            lambda: self._create(user=self.supplier),
        ):
            with self.assertRaises(frappe.PermissionError):
                call()

    def test_unassigned_salesperson_cannot_read_or_redeliver_another_sale(self):
        sale = self._create()
        frappe.set_user(self.other_maker)
        with self.assertRaises(frappe.PermissionError):
            client.get(SALE, sale.name)
        with self.assertRaises(frappe.PermissionError):
            self._create(user=self.other_maker)

    def test_many_to_many_allocation_keeps_distinct_movement_times(self):
        first = self._approve_sale(self._create(lines=[self._line("100")]))
        second = self._approve_sale(self._create(lines=[self._line("20")], event="second-sale"))
        movement_a = self._outward(60, event="gp-a")
        movement_b = self._outward(60, event="gp-b", movement_at="2026-10-03 12:00:00")
        original = physical_snapshot(self.container.name)
        self._approve_allocation(self._allocation(first, movement_a, 60, event="first-a"))
        self._approve_allocation(self._allocation(first, movement_b, 40, event="first-b"))
        self._approve_allocation(self._allocation(second, movement_b, 20, event="second-b"))
        self.assertEqual(self._active_qty(sale=first), Decimal("100"))
        self.assertEqual(self._active_qty(sale=second), Decimal("20"))
        self.assertEqual(self._active_qty(physical=movement_b), Decimal("60"))
        first.reload()
        movement_a.reload()
        movement_b.reload()
        self.assertEqual(get_datetime(first.sale_at), get_datetime("2026-10-01 10:00:00"))
        self.assertEqual(get_datetime(movement_a.movement_at), get_datetime("2026-10-02 11:00:00"))
        self.assertEqual(get_datetime(movement_b.movement_at), get_datetime("2026-10-03 12:00:00"))
        self.assertEqual(physical_snapshot(self.container.name), original)

    def test_allocation_sale_and_outward_caps_rechecked_at_approval(self):
        sale = self._approve_sale(self._create(lines=[self._line("100")]))
        physical = self._outward(80)
        first = self._allocation(sale, physical, 60, event="cap-a")
        second = self._allocation(sale, physical, 40, event="cap-b")
        self._approve_allocation(first)
        self._verify_allocation(second)
        frappe.set_user(self.approver)
        with self.assertRaisesRegex(frappe.ValidationError, "ALLOCATION_OVERDRAW"):
            commercial.approve_sale_outward_allocation(second.name)
        second.reload()
        self.assertEqual(second.state, "PROPOSED")
        self.assertEqual(self._active_qty(physical=physical), Decimal("60"))
        other = self._outward(80, event="other-gp")
        excess = self._allocation(sale, other, 50, event="sale-cap")
        self._verify_allocation(excess)
        frappe.set_user(self.approver)
        with self.assertRaisesRegex(frappe.ValidationError, "ALLOCATION_OVERDRAW"):
            commercial.approve_sale_outward_allocation(excess.name)
        self.assertEqual(self._active_qty(sale=sale), Decimal("60"))

    def test_allocation_reversal_is_audited_and_restores_capacity(self):
        sale = self._approve_sale(self._create())
        physical = self._outward()
        original = self._approve_allocation(self._allocation(sale, physical, 100))
        allocation = self._allocation(sale, physical, 100, event="active-correction",
                                      supersedes=original.name, reason="Exact pairing correction")
        self._approve_allocation(allocation)
        replay = self._allocation(sale, physical, 100, event="active-correction",
                                  supersedes=original.name, reason="Exact pairing correction")
        self.assertEqual(replay.name, allocation.name)
        original.reload()
        self.assertEqual(original.state, "REVERSED")
        self.assertEqual(original.superseded_by, allocation.name)
        self.assertEqual(self._active_qty(sale=sale), Decimal("100"))
        before = physical_snapshot(self.container.name)
        frappe.set_user(self.approver)
        commercial.reverse_sale_outward_allocation(allocation.name, reason="Wrong source pairing", evidence=self.evidence.name)
        allocation.reload()
        self.assertEqual(allocation.state, "REVERSED")
        self.assertEqual(self._active_qty(sale=sale), Decimal("0"))
        replacement = self._allocation(sale, physical, 100, event="replacement", supersedes=allocation.name, reason="Corrected pairing after explicit reversal")
        self._approve_allocation(replacement)
        self.assertEqual(self._active_qty(sale=sale), Decimal("100"))
        self.assertEqual(physical_snapshot(self.container.name), before)

    def test_allocations_reject_bucket_unknown_qty_wrong_lot_and_uom(self):
        physical = self._outward()
        cases = [
            self._line("100", "825", lot=None, rate_basis="PRICE_BUCKET", bucket_key="unknown-gp"),
            self._line(None, None),
            self._line("100", "825", lot="42074"),
        ]
        for index, line in enumerate(cases):
            sale = self._approve_sale(self._create(lines=[line], event=f"incompatible-{index}"))
            with self.subTest(index=index), self.assertRaises(frappe.ValidationError):
                self._allocation(sale, physical, 10, event=f"bad-allocation-{index}")
        sale = self._approve_sale(self._create(event="uom-sale"))
        wrong_uom = frappe.db.get_value("UOM", {"name": ("!=", self.masters["uom"])}, "name")
        self.assertTrue(wrong_uom, "ERPNext baseline must contain more than one UOM")
        with self.assertRaises(frappe.ValidationError):
            self._allocation(sale, physical, 10, event="bad-uom", uom=wrong_uom)

    def test_allocation_needs_approved_sale_and_three_actor_review(self):
        sale = self._create()
        physical = self._outward()
        with self.assertRaises(frappe.ValidationError):
            self._allocation(sale, physical, 10)
        self._approve_sale(sale)
        allocation = self._allocation(sale, physical, 10)
        frappe.set_user(self.approver)
        with self.assertRaises(frappe.ValidationError):
            commercial.approve_sale_outward_allocation(allocation.name)
        frappe.set_user(self.maker)
        with self.assertRaises(frappe.PermissionError):
            commercial.verify_sale_outward_allocation(allocation.name)
        self._approve_allocation(allocation)
        rejected = self._allocation(sale, physical, 10, event="rejected-pairing")
        self._verify_allocation(rejected)
        frappe.set_user(self.approver)
        commercial.reject_sale_outward_allocation(rejected.name, reason="Insufficient source pairing evidence")
        rejected.reload()
        self.assertEqual(rejected.state, "REJECTED")
        self.assertEqual(rejected.evidence, self.evidence.name)
        self.assertEqual(self._active_qty(sale=sale), Decimal("10"))

    def test_allocation_replay_and_digest_conflict_do_not_duplicate_quantity(self):
        sale = self._approve_sale(self._create())
        physical = self._outward()
        allocation = self._allocation(sale, physical, 30)
        replay = self._allocation(sale, physical, "30.000")
        self.assertEqual(replay.name, allocation.name)
        self._approve_allocation(allocation)
        with self.assertRaisesRegex(frappe.ValidationError, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self._allocation(sale, physical, 31)
        self.assertEqual(self._active_qty(sale=sale), Decimal("30"))

    def test_missing_exact_photo_blocks_92_at_700_finalization(self):
        sale = self._create(lines=[self._line("92", "700")])
        commercial.submit_sale(sale.name)
        frappe.set_user(self.accounts)
        commercial.verify_sale(sale.name)
        frappe.set_user(self.approver)
        with self.assertRaises(frappe.ValidationError):
            commercial.approve_sale(sale.name)
        sale.reload()
        self.assertNotEqual(sale.status, "APPROVED")
        self.assertEqual(sale.lines[0].price_state, "PROPOSED")
        self.assertEqual(self._active_qty(sale=sale), Decimal("0"))

    def test_photo_linked_92_at_700_requires_approval_and_preserves_physical(self):
        photo = self._evidence("synthetic exact handwritten source", photo=True)
        physical = self._outward(92)
        before = physical_snapshot(self.container.name)
        sale = self._create(source_evidence=photo.name, lines=[self._line("92", "700", evidence=photo.name)])
        self.assertEqual(sale.lines[0].price_state, "PROPOSED")
        self._approve_sale(sale)
        self.assertEqual(Decimal(sale.lines[0].amount), Decimal("64400"))
        self.assertEqual(physical_snapshot(self.container.name), before)
        self.assertEqual(self._active_qty(physical=physical), Decimal("0"))

    def test_rate_correction_is_new_sale_and_history_retains_original_price(self):
        original = self._approve_sale(self._create(lines=[self._line("100", "825")]))
        original_digest = original.payload_sha256
        evidence = self._evidence("exact corrected commercial rate")
        frappe.set_user(self.maker)
        proposed = commercial.propose_rate(
            original.name, line_key=original.lines[0].line_key, rate="826",
            evidence=evidence.name, source_event_id=f"{self.token}:rate-correction",
            reason="Exact source rate correction", expected_version=original.version,
        )
        successor = frappe.get_doc(SALE, proposed["name"])
        self.assertNotEqual(successor.name, original.name)
        self.assertEqual(successor.supersedes, original.name)
        self.assertEqual(Decimal(successor.lines[0].amount), Decimal("82600"))
        original.reload()
        self.assertEqual(original.status, "APPROVED")
        self.assertEqual(original.payload_sha256, original_digest)
        frappe.set_user(self.maker)
        commercial.submit_sale(successor.name)
        frappe.set_user(self.accounts)
        commercial.verify_rate(successor.name)
        frappe.set_user(self.approver)
        commercial.approve_rate(successor.name)
        original.reload()
        successor.reload()
        self.assertEqual(original.status, "SUPERSEDED")
        self.assertEqual(original.superseded_by, successor.name)
        self.assertEqual(Decimal(original.lines[0].rate), Decimal("825"))
        self.assertEqual(Decimal(successor.lines[0].rate), Decimal("826"))

    def test_sale_correction_compensates_allocations_only_on_successor_approval(self):
        sale = self._approve_sale(self._create())
        physical = self._outward()
        allocation = self._approve_allocation(self._allocation(sale, physical, 100))
        before = physical_snapshot(self.container.name)
        evidence = self._evidence("corrected original quantity")
        frappe.set_user(self.maker)
        result = commercial.supersede_sale(
            sale.name, source_event_id=f"{self.token}:corrected-sale", reason="Exact quantity correction",
            source_evidence=evidence.name, changes={"lines": [self._line("90", evidence=evidence.name)]},
            expected_version=sale.reload().version,
        )
        successor = frappe.get_doc(SALE, result["name"])
        self.assertEqual(self._active_qty(sale=sale), Decimal("100"))
        self.assertEqual(sale.status, "APPROVED")
        self._approve_sale(successor)
        sale.reload()
        allocation.reload()
        self.assertEqual(sale.status, "SUPERSEDED")
        self.assertEqual(allocation.state, "REVERSED")
        self.assertEqual(self._active_qty(sale=sale), 0)
        self.assertTrue(any(event["reason"] == "Exact quantity correction" and event["evidence"] == evidence.name
                            for event in json.loads(allocation.decision_history)))
        self.assertEqual(physical_snapshot(self.container.name), before)

    def test_alias_remap_and_remap_back_retain_history_and_compensate_allocations(self):
        first = self._approve_mapping(self._mapping())
        sale = self._approve_sale(self._create())
        physical = self._outward()
        allocation = self._approve_allocation(self._allocation(sale, physical, 100))
        before = physical_snapshot(self.container.name)
        second = self._mapping(customer=self.second_customer, event="remap", supersedes=first.name,
                               reason="Exact buyer identity correction")
        self._approve_mapping(second)
        replay = self._mapping(customer=self.second_customer, event="remap", supersedes=first.name,
                               reason="Exact buyer identity correction")
        self.assertEqual(replay.name, second.name)
        first.reload()
        sale.reload()
        allocation.reload()
        self.assertEqual(first.status, "SUPERSEDED")
        self.assertEqual(first.superseded_by, second.name)
        self.assertEqual(first.proposed_customer, self.customer)
        self.assertEqual(sale.status, "REVIEW_PENDING")
        self.assertEqual(allocation.state, "REVERSED")
        self.assertEqual(self._active_qty(sale=sale), 0)
        third = self._mapping(event="remap-back", supersedes=second.name,
                              reason="Further exact buyer evidence restores original identity")
        self._approve_mapping(third)
        self.assertNotEqual(third.name, first.name)
        second.reload()
        self.assertEqual(second.status, "SUPERSEDED")
        self.assertEqual(frappe.db.count(ALIAS, {"raw_alias": first.raw_alias, "status": "APPROVED"}), 1)
        self.assertEqual(physical_snapshot(self.container.name), before)

    def _cleanup_committed_container(self):
        """Delete only this test's committed fixtures after worker connections close."""
        frappe.set_user("Administrator")
        frappe.db.rollback()
        sales = frappe.get_all(SALE, filters={"container": self.container.name}, pluck="name")
        outwards = frappe.get_all("Fresko Outward", filters={"container": self.container.name}, pluck="name")
        aliases = frappe.get_all(ALIAS, filters={"evidence": self.evidence.name}, pluck="name")
        for name in sales:
            frappe.db.delete("Fresko Exception", {"sale": name})
        for name in outwards:
            frappe.db.delete("Fresko Exception", {"outward": name})
        frappe.db.delete(ALLOCATION, {"container": self.container.name})
        if sales:
            frappe.db.delete("Fresko Commercial Sale Line", {"parent": ("in", sales)})
            frappe.db.delete(SALE, {"name": ("in", sales)})
        if aliases:
            frappe.db.delete(ALIAS, {"name": ("in", aliases)})
        if outwards:
            frappe.db.delete("Fresko Outward Line", {"parent": ("in", outwards)})
            frappe.db.delete("Fresko Outward", {"name": ("in", outwards)})
        frappe.db.delete("Fresko Evidence", {"container": self.container.name})
        frappe.db.delete("Fresko Container Lot", {"parent": self.container.name})
        frappe.db.delete("Fresko Container", {"name": self.container.name})
        for customer in (self.customer, self.second_customer):
            frappe.db.delete("Customer", {"name": customer})
        frappe.db.commit()

    def _race(self, names, worker):
        site = frappe.local.site
        barrier = threading.Barrier(len(names))
        outcomes = Queue()

        def run_one(name):
            frappe.init(site=site)
            frappe.connect()
            try:
                frappe.set_user(self.approver)
                barrier.wait(timeout=20)
                worker(name)
                frappe.db.commit()
                outcomes.put((name, "OK", ""))
            except Exception as exc:
                frappe.db.rollback()
                outcomes.put((name, "DENIED", str(exc)))
            finally:
                frappe.destroy()

        threads = [threading.Thread(target=run_one, args=(name,)) for name in names]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertFalse(any(thread.is_alive() for thread in threads), "Commercial transaction worker hung")
        self.assertEqual(outcomes.qsize(), len(names))
        frappe.db.rollback()
        return [outcomes.get_nowait() for _ in names]

    def test_two_connections_cannot_overdraw_sale_quantity(self):
        sale = self._approve_sale(self._create())
        movement_a = self._outward(60, event="race-gp-a")
        movement_b = self._outward(60, event="race-gp-b")
        allocations = [self._allocation(sale, movement_a, 60, event="race-a"),
                       self._allocation(sale, movement_b, 60, event="race-b")]
        for allocation in allocations:
            self._verify_allocation(allocation)
        self.addCleanup(self._cleanup_committed_container)
        frappe.db.commit()
        outcomes = self._race([row.name for row in allocations], commercial.approve_sale_outward_allocation)
        self.assertEqual([row[1] for row in outcomes].count("OK"), 1, outcomes)
        self.assertEqual([row[1] for row in outcomes].count("DENIED"), 1, outcomes)
        self.assertIn("ALLOCATION_OVERDRAW", next(row[2] for row in outcomes if row[1] == "DENIED"))
        self.assertEqual(self._active_qty(sale=sale), Decimal("60"))
        self.assertEqual(physical_snapshot(self.container.name)["posted_physical_total"], 120)

    def test_two_connections_cannot_overdraw_outward_quantity(self):
        physical = self._outward(100)
        first_sale = self._approve_sale(self._create(lines=[self._line("60")]))
        second_sale = self._approve_sale(self._create(lines=[self._line("60")], event="race-second-sale"))
        allocations = [self._allocation(first_sale, physical, 60, event="race-a"),
                       self._allocation(second_sale, physical, 60, event="race-b")]
        for allocation in allocations:
            self._verify_allocation(allocation)
        self.addCleanup(self._cleanup_committed_container)
        frappe.db.commit()
        outcomes = self._race([row.name for row in allocations], commercial.approve_sale_outward_allocation)
        self.assertEqual([row[1] for row in outcomes].count("OK"), 1, outcomes)
        self.assertEqual([row[1] for row in outcomes].count("DENIED"), 1, outcomes)
        self.assertIn("ALLOCATION_OVERDRAW", next(row[2] for row in outcomes if row[1] == "DENIED"))
        self.assertEqual(self._active_qty(physical=physical), Decimal("60"))
        self.assertEqual(physical_snapshot(self.container.name)["posted_physical_total"], 100)

    def test_two_connections_alias_remap_leave_one_approved_successor(self):
        first = self._approve_mapping(self._mapping())
        second = self._mapping(customer=self.second_customer, event="alias-race-a", supersedes=first.name, reason="Candidate A")
        third = self._mapping(event="alias-race-b", supersedes=first.name, reason="Candidate B")
        for mapping in (second, third):
            frappe.set_user(self.accounts)
            commercial.verify_alias_mapping(mapping.name)
        self.addCleanup(self._cleanup_committed_container)
        frappe.db.commit()
        outcomes = self._race([second.name, third.name], commercial.approve_alias_mapping)
        self.assertEqual([row[1] for row in outcomes].count("OK"), 1, outcomes)
        self.assertEqual([row[1] for row in outcomes].count("DENIED"), 1, outcomes)
        approved = frappe.get_all(ALIAS, filters={"raw_alias": first.raw_alias, "status": "APPROVED"}, pluck="name")
        self.assertEqual(len(approved), 1)
        self.assertIn(approved[0], [second.name, third.name])

    def test_alias_scope_and_evidence_do_not_cross_company_or_container(self):
        raw = f"Raw Buyer {self.token}"
        self._approve_mapping(self._mapping(raw=raw))
        frappe.set_user("Administrator")
        other_company = frappe.get_doc({
            "doctype": "Company", "company_name": f"Commercial Scope {self.token}",
            "abbr": f"C{self.token[:4]}", "default_currency": self.masters["currency"],
            "country": frappe.db.get_value("Company", self.container.company, "country") or "India",
        }).insert(ignore_permissions=True)
        other_masters = {**self.masters, "company": other_company.name}
        other_container = make_container(other_masters, inward_qty=100, lot_no="OTHER-LOT")
        other_evidence = self._evidence("other Company source", container=other_container)
        row = self._line("10", lot=None)
        row["evidence"] = other_evidence.name
        sale = self._create(
            company=other_company.name, container=other_container.name,
            source_evidence=other_evidence.name, raw_party_alias=raw, lines=[row],
        )
        self.assertFalse(sale.customer)
        self.assertFalse(sale.alias_mapping)
        with self.assertRaises(frappe.ValidationError):
            self._create(event="cross-company", company=other_company.name)
        with self.assertRaises(frappe.ValidationError):
            self._create(event="cross-evidence", source_evidence=other_evidence.name)
        with self.assertRaises(frappe.ValidationError):
            self._mapping(event="cross-alias", company=other_company.name)

    def test_recorded_time_projection_keeps_pre_alias_and_pre_approval_truth(self):
        sale = self._create(sale_at="2099-01-01 00:00:00")
        created_at = json.loads(sale.decision_history)[-1]["recorded_at"]
        before_create = str(add_to_date(get_datetime(created_at), seconds=-1))
        self._approve_sale(sale)
        approved_at = json.loads(sale.decision_history)[-1]["recorded_at"]
        self._approve_mapping(self._mapping())
        frappe.set_user(self.accounts)
        absent = commercial.get_sale_as_of(sale.name, before_create)
        captured = commercial.get_sale_as_of(sale.name, created_at)
        approved = commercial.get_sale_as_of(sale.name, approved_at)
        current = commercial.get_sale_as_of(sale.name, "2099-12-31 23:59:59")
        self.assertFalse(absent["exists"])
        self.assertTrue(captured["exists"])
        self.assertEqual(captured["status"], "DRAFT")
        self.assertEqual(captured["lines"][0]["price_state"], "PROPOSED")
        self.assertFalse(captured["customer"])
        self.assertEqual(approved["status"], "APPROVED")
        self.assertEqual(approved["lines"][0]["price_state"], "FINAL")
        self.assertFalse(approved["customer"])
        self.assertEqual(approved["reconciliation_state"], "PENDING")
        self.assertEqual(current["customer"], self.customer)
        self.assertEqual(current["reconciliation_state"], "PENDING")
        self.assertEqual(captured["sale_at"], "2099-01-01 00:00:00")
        sale.reload()
        self.assertEqual(sale.lines[0].price_state, "PROPOSED")

    def test_physical_reversal_invalidates_effective_allocation_but_not_history(self):
        self._approve_mapping(self._mapping())
        sale = self._approve_sale(self._create())
        physical = self._outward()
        allocation = self._approve_allocation(self._allocation(sale, physical, 100))
        before_reversal = json.loads(allocation.decision_history)[-1]["recorded_at"]
        # Separate persisted Datetime precision from the audit JSON precision.
        time.sleep(1.1)
        frappe.set_user(self.maker)
        result = outward.reverse(
            physical.name, movement_at="2026-10-03 15:00:00",
            source_evidence=self.evidence.name, source_event_id=f"{self.token}:physical-reversal",
            reason="Physical source movement cancelled",
        )
        outward.submit_for_review(result["name"])
        frappe.set_user(self.approver)
        outward.post(result["name"])
        physical.reload()
        self.assertEqual(physical.status, "Posted")
        self.assertEqual(physical_snapshot(self.container.name)["posted_physical_total"], 0)
        historical = commercial.get_sale_as_of(sale.name, before_reversal)
        current = commercial.get_sale_as_of(sale.name, "2099-12-31 23:59:59")
        self.assertEqual(historical["movement_status"], "EVIDENCED")
        self.assertEqual(historical["reconciliation_state"], "CONFIRMED")
        self.assertEqual(Decimal(historical["lines"][0]["allocated_qty"]), Decimal("100"))
        self.assertEqual(current["allocations"], [])
        self.assertEqual(current["movement_status"], "NOT_EVIDENCED")
        self.assertEqual(current["reconciliation_state"], "PENDING")
        outward_view = commercial.get_outward_reconciliation(physical.name)
        self.assertFalse(outward_view["physical_active"])
        self.assertEqual(outward_view["allocations"], [])

    def test_3060_operating_3056_physical_and_financial_unknowns_are_unchanged(self):
        frappe.set_user("Administrator")
        self.container = make_container(self.masters, inward_qty=3060, lot_no="GRAPES-BOUNDARY")
        self.evidence = self._evidence("operating/physical quantity boundary; labour outflow INR101; owner-stated INR350000 pending bank evidence")
        frappe.set_user(self.maker)
        deal = make_deal(self.container, lot_no="GRAPES-BOUNDARY", qty=10)
        original_dispatch = deal.dispatched_qty
        physical = self._outward(3056, lot="GRAPES-BOUNDARY")
        before = physical_snapshot(self.container.name)
        sale = self._approve_sale(self._create(
            lines=[self._line("180", None, lot="GRAPES-BOUNDARY")], deal=deal.name,
        ))
        view = commercial.get_container_reconciliation(self.container.name)
        self.assertEqual(view["reconciliation_state"], "PENDING")
        projected = next(row for row in view["sales"] if row["name"] == sale.name)
        self.assertFalse(projected["customer"])
        self.assertEqual(projected["lines"][0]["price_state"], "UNKNOWN")
        self.assertIsNone(projected["lines"][0]["amount"])
        self.assertEqual(projected["lines"][0]["allocation_state"], "UNALLOCATED")
        # Source wording is not a Collection, a cleared payment, or bank truth.
        for record in (view, projected):
            for field in ("received", "cleared", "collections", "customer_collections", "receivable", "receipt_amount"):
                self.assertNotIn(field, record)
        self.container.reload()
        deal.reload()
        self.assertEqual(self.container.inward_qty, 3060)
        self.assertEqual(physical_snapshot(self.container.name)["posted_physical_total"], 3056)
        self.assertEqual(physical_snapshot(self.container.name), before)
        self.assertEqual(deal.dispatched_qty, original_dispatch)
        self.assertEqual(physical.name, before["movements"][0].name)

    def test_company_alias_remap_compensates_allocations_across_containers(self):
        mapping = self._approve_mapping(self._mapping())
        container_a, evidence_a = self.container, self.evidence
        sale_a = self._approve_sale(self._create())
        outward_a = self._outward()
        allocation_a = self._approve_allocation(self._allocation(sale_a, outward_a, 100))
        before_a = physical_snapshot(container_a.name)
        frappe.set_user("Administrator")
        self.container = make_container(self.masters, inward_qty=100, lot_no="42076")
        self.evidence = self._evidence("same Company second Container source")
        sale_b = self._approve_sale(self._create(event="sale-b"))
        self.assertEqual(sale_b.alias_mapping, mapping.name)
        outward_b = self._outward(event="outward-b")
        with self.assertRaises(frappe.ValidationError):
            self._allocation(sale_b, outward_b, 100, event="wrong-allocation-evidence", evidence=evidence_a.name)
        allocation_b = self._approve_allocation(self._allocation(sale_b, outward_b, 100, event="allocation-b"))
        before_b = physical_snapshot(self.container.name)
        correction = self._mapping(
            customer=self.second_customer, event="cross-container-remap", evidence=evidence_a.name,
            supersedes=mapping.name, reason="Company-scoped exact alias identity correction",
        )
        self._approve_mapping(correction)
        for sale, allocation in ((sale_a, allocation_a), (sale_b, allocation_b)):
            sale.reload()
            allocation.reload()
            self.assertEqual(sale.status, "REVIEW_PENDING")
            self.assertFalse(sale.customer)
            self.assertEqual(allocation.state, "REVERSED")
            self.assertEqual(self._active_qty(sale=sale), 0)
            self.assertTrue(any(event["evidence"] == evidence_a.name and event["reason"] == correction.reason
                                for event in json.loads(allocation.decision_history)))
        self.assertEqual(physical_snapshot(container_a.name), before_a)
        self.assertEqual(physical_snapshot(self.container.name), before_b)
