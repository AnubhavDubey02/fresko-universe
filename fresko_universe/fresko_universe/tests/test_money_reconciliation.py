"""Money acceptance tests requiring a real migrated Frappe/MariaDB site.

Run: bench --site <site> run-tests --app fresko_universe --module
fresko_universe.tests.test_money_reconciliation. Source examples are synthetic;
these gates do not certify bank clearance or import private transaction data.
"""
from __future__ import annotations

import hashlib
import json
import threading
from decimal import Decimal
from queue import Queue

import frappe
from frappe import client
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_datetime
from frappe.utils.file_manager import save_file

from fresko_universe import commercial, money
from fresko_universe.fresko_core.physical import physical_snapshot
from fresko_universe.tests.test_commercial_sale import _ensure_user
from fresko_universe.tests.utils import ensure_masters, make_container

COLLECTION = "Fresko Collection"
ALLOCATION = "Fresko Payment Allocation"
ADJUSTMENT = "Fresko Receivable Adjustment"
APPLICATION = "Fresko Adjustment Application"
SALE = "Fresko Commercial Sale"


class TestMoneyReconciliation(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.masters = ensure_masters()
        cls.maker = _ensure_user("money_maker@example.com", ["Fresko Accounts"])
        cls.checker = _ensure_user("money_checker@example.com", ["Fresko Accounts"])
        cls.approver = _ensure_user("money_approver@example.com", ["Fresko Approver"])
        cls.salesperson = _ensure_user("money_salesperson@example.com", ["Fresko Salesperson"])
        cls.manager = _ensure_user("money_manager@example.com", ["System Manager"])
        cls.all_roles = _ensure_user("money_all_roles@example.com", ["Fresko Accounts", "Fresko Approver"])
        if not frappe.db.exists("Role", "Fresko Supplier Viewer"):
            frappe.get_doc({"doctype": "Role", "role_name": "Fresko Supplier Viewer", "desk_access": 0}).insert(ignore_permissions=True)
        cls.supplier = _ensure_user("money_supplier@example.com", ["Fresko Supplier Viewer", "Fresko Accounts"])
        frappe.db.commit()

    def setUp(self):
        frappe.set_user("Administrator")
        self.token = frappe.generate_hash(length=10)
        self.container = make_container(self.masters, lot_no="MONEY-LOT", inward_qty=100)
        self.evidence = frappe.get_doc({
            "doctype": "Fresko Evidence", "container": self.container.name,
            "evidence_type": "Note", "notes": f"Synthetic money source {self.token}",
        }).insert(ignore_permissions=True)
        self.customer = frappe.get_doc({
            "doctype": "Customer", "customer_name": f"Money Buyer {self.token}", "customer_type": "Company",
            "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
            "territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
        }).insert(ignore_permissions=True).name
        self.documents = {dt: [] for dt in (COLLECTION, ALLOCATION, ADJUSTMENT, APPLICATION, SALE, "Fresko Party Alias Mapping")}

    def tearDown(self):
        frappe.set_user("Administrator")

    def _doc(self, doctype, result):
        self.documents[doctype].append(result["name"])
        return frappe.get_doc(doctype, result["name"])

    def _collection(self, amount="1000", *, event="receipt", user=None, **changes):
        args = {
            "company": self.container.company, "source_namespace": "synthetic-money-v1",
            "source_event_id": f"{self.token}:{event}", "direction": "INFLOW",
            "amount": amount, "currency": self.masters["currency"],
            "payment_channel": "CASH", "bank_state": "NONE", "source_classification": "CASH_DECLARATION",
            "effective_at": "2026-09-21 15:25:48", "payer_raw": f"  Raw Payer {self.token}  ",
            "source_evidence": self.evidence.name,
        }
        args.update(changes)
        frappe.set_user(user or self.maker)
        return self._doc(COLLECTION, money.create_collection(**args))

    def _review(self, doc, kind):
        frappe.set_user(doc.prepared_by)
        getattr(money, f"submit_{kind}")(doc.name)
        frappe.set_user(self.checker)
        getattr(money, f"verify_{kind}")(doc.name)
        doc.reload()
        self.assertEqual(doc.status, "VERIFIED")
        return doc

    def _approve(self, doc, kind):
        self._review(doc, kind)
        frappe.set_user(self.approver)
        getattr(money, f"approve_{kind}")(doc.name)
        doc.reload()
        self.assertEqual(doc.status, "APPROVED")
        return doc

    def _sale(self, amount="1000", *, event="sale", resolved=True, rate_known=True):
        raw = f"Money Alias {self.token}:{event}"
        if resolved:
            frappe.set_user(self.salesperson)
            mapping = self._doc("Fresko Party Alias Mapping", commercial.propose_alias_mapping(
                company=self.container.company, raw_alias=raw, proposed_customer=self.customer,
                evidence=self.evidence.name, source_event_id=f"{self.token}:alias:{event}",
            ))
            frappe.set_user(self.maker)
            commercial.verify_alias_mapping(mapping.name)
            frappe.set_user(self.approver)
            commercial.approve_alias_mapping(mapping.name)
        frappe.set_user(self.salesperson)
        sale = self._doc(SALE, commercial.create_sale(
            company=self.container.company, container=self.container.name,
            sale_at="2026-09-21 10:00:00", source_evidence=self.evidence.name,
            source_event_id=f"{self.token}:{event}", raw_party_alias=raw, party_state="KNOWN",
            currency=self.masters["currency"], lines=[{
                "line_key": "source-line-1", "source_line_ref": "1", "item": self.masters["item"],
                "container_lot": self.container.lots[0].name, "raw_lot_text": "MONEY-LOT", "lot_state": "KNOWN",
                "qty": "1", "qty_state": "KNOWN", "uom": self.masters["uom"],
                "rate": amount if rate_known else None, "price_state": "PROPOSED" if rate_known else "UNKNOWN",
                "rate_basis": "RATE_ASSERTION" if rate_known else "NONE", "evidence": self.evidence.name,
            }],
        ))
        commercial.submit_sale(sale.name)
        frappe.set_user(self.maker)
        commercial.verify_sale(sale.name)
        frappe.set_user(self.approver)
        commercial.approve_sale(sale.name)
        return sale.reload()

    def _allocation(self, receipt, amount, *, sale=None, event="allocation", **changes):
        args = {
            "collection": receipt.name, "allocation_type": "SALE" if sale else "CONTAINER_UNAPPLIED",
            "amount": str(amount), "currency": self.masters["currency"], "evidence": self.evidence.name,
            "source_event_id": f"{self.token}:{event}", "sale": sale.name if sale else None,
            "container": self.container.name,
        }
        args.update(changes)
        frappe.set_user(self.maker)
        return self._doc(ALLOCATION, money.propose_payment_allocation(**args))

    def _adjustment(self, amount="100", *, event="adjustment", **changes):
        args = {
            "company": self.container.company, "customer": self.customer, "adjustment_type": "DISCOUNT",
            "amount": amount, "currency": self.masters["currency"], "evidence": self.evidence.name,
            "source_event_id": f"{self.token}:{event}", "agreement_reference": f"Synthetic discharge agreement {self.token}",
        }
        args.update(changes)
        frappe.set_user(self.maker)
        return self._doc(ADJUSTMENT, money.propose_adjustment(**args))

    def _application(self, adjustment, sale, amount, *, event="application", **changes):
        args = {
            "receivable_adjustment": adjustment.name, "sale": sale.name, "amount": str(amount),
            "currency": self.masters["currency"], "evidence": self.evidence.name,
            "source_event_id": f"{self.token}:{event}",
        }
        args.update(changes)
        frappe.set_user(self.maker)
        return self._doc(APPLICATION, money.propose_adjustment_application(**args))

    def _bank_account(self):
        frappe.set_user("Administrator")
        bank = "Synthetic Money Bank"
        if not frappe.db.exists("Bank", bank):
            frappe.get_doc({"doctype": "Bank", "bank_name": bank}).insert(ignore_permissions=True)
        ledger_account = frappe.db.get_value("Account", {
            "company": self.container.company, "account_type": "Bank", "is_group": 0,
        }, "name")
        if not ledger_account:
            parent_account = frappe.db.get_value("Account", {
                "company": self.container.company, "root_type": "Asset", "is_group": 1,
            }, "name")
            self.assertTrue(parent_account, "The integration site must have an Asset account group")
            ledger_account = frappe.get_doc({
                "doctype": "Account", "account_name": f"Money Bank Ledger {self.token}",
                "company": self.container.company, "parent_account": parent_account,
                "account_type": "Bank", "is_group": 0,
            }).insert(ignore_permissions=True).name
        return frappe.get_doc({
            "doctype": "Bank Account", "account_name": f"Money Test {self.token}", "bank": bank,
            "is_company_account": 1, "company": self.container.company,
            "account": ledger_account,
            "bank_account_no": f"SYNTHETIC-{self.token}",
        }).insert(ignore_permissions=True).name

    def _position(self, receipt, as_of=None):
        frappe.set_user(self.checker)
        return money.get_collection_position(receipt.name, as_of=as_of)

    def _receivable(self, sale, as_of=None):
        frappe.set_user(self.checker)
        return money.get_sale_receivable(sale.name, as_of=as_of)

    def test_cash_declaration_is_received_without_bank_account_or_slip(self):
        receipt = self._approve(self._collection("630000"), "collection")
        view = self._position(receipt)
        self.assertTrue(view["is_cash_received"])
        self.assertFalse(view["is_bank_cleared"])
        self.assertEqual(Decimal(view["unallocated_amount"]), Decimal("630000"))
        self.assertFalse(receipt.bank_account)
        self.assertFalse(receipt.bank_reference)
        self.assertFalse(receipt.evidence_file)
        self.assertFalse(receipt.customer)
        self.assertEqual(receipt.payer_raw, f"  Raw Payer {self.token}  ")

    def test_authorization_inprocess_received_does_not_approve_allocation(self):
        receipt = self._approve(self._collection(
            "350000", payment_channel="BANK", bank_state="AUTHORIZATION_INPROCESS",
            source_classification="RTGS_NEFT", rail="RTGS", bank_reference=f"PENDING-{self.token}",
        ), "collection")
        allocation = self._review(self._allocation(receipt, "100"), "payment_allocation")
        frappe.set_user(self.approver)
        with self.assertRaisesRegex(frappe.ValidationError, "BANK_PENDING_INELIGIBLE"):
            money.approve_payment_allocation(allocation.name)
        self.assertEqual(self._position(receipt)["allocated_amount"], "0.00")
        self.assertTrue(self._position(receipt)["is_bank_pending"])

    def test_direction_unknown_and_labour_outflow_do_not_create_customer_funds(self):
        for index, direction in enumerate(("UNKNOWN", "OUTFLOW", "INTERNAL_TRANSFER")):
            receipt = self._approve(self._collection("101", event=f"direction-{index}", direction=direction), "collection")
            with self.subTest(direction=direction), self.assertRaises(frappe.ValidationError):
                self._allocation(receipt, "1", event=f"invalid-{index}")
            self.assertFalse(self._position(receipt)["is_cash_received"])
        unallocated = money.get_unallocated_collections(self.container.company)
        self.assertFalse(set(self.documents[COLLECTION]) & {row["name"] for row in unallocated["unallocated_collections"]})

    def test_unknown_amount_stays_null_and_invalid_decimal_forms_leave_no_rows(self):
        receipt = self._collection(None, direction="UNKNOWN", payment_channel="UNKNOWN", source_classification="NONE")
        self.assertIsNone(self._position(receipt)["amount"])
        self.assertIsNone(self._position(receipt)["unallocated_amount"])
        before = frappe.db.count(COLLECTION)
        for value in ("NaN", "1e3", "-1", "0", "1.001", 1.0, "9" * 30):
            with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
                self._collection(value, event=f"invalid-{value}")
        self.assertEqual(frappe.db.count(COLLECTION), before)

    def test_money_maker_verifier_approver_are_distinct_even_with_all_roles(self):
        receipt = self._collection(user=self.all_roles)
        money.submit_collection(receipt.name)
        with self.assertRaises(frappe.PermissionError):
            money.verify_collection(receipt.name)
        frappe.set_user(self.checker)
        money.verify_collection(receipt.name)
        frappe.set_user(self.all_roles)
        with self.assertRaises(frappe.PermissionError):
            money.approve_collection(receipt.name)
        frappe.set_user(self.approver)
        money.approve_collection(receipt.name)
        receipt.reload()
        self.assertEqual(len({receipt.prepared_by, receipt.verified_by, receipt.approved_by}), 3)

    def test_wrong_roles_cannot_prepare_and_system_manager_cannot_approve(self):
        for user in (self.salesperson, self.manager, self.approver):
            with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
                self._collection(user=user)
        receipt = self._review(self._collection(), "collection")
        frappe.set_user(self.manager)
        with self.assertRaises(frappe.PermissionError):
            money.approve_collection(receipt.name)

    def test_stale_version_and_rejection_preserve_source(self):
        receipt = self._collection()
        old_version = receipt.version
        money.submit_collection(receipt.name)
        frappe.set_user(self.checker)
        with self.assertRaisesRegex(frappe.ValidationError, "STALE_VERSION"):
            money.verify_collection(receipt.name, expected_version=old_version)
        frappe.set_user(self.approver)
        money.reject_collection(receipt.name, reason="No receipt established by this source")
        receipt.reload()
        self.assertEqual(receipt.status, "REJECTED")
        self.assertEqual(Decimal(receipt.amount), Decimal("1000"))
        self.assertEqual(receipt.source_evidence, self.evidence.name)

    def test_decimal_idempotence_and_payload_conflict_do_not_change_source(self):
        receipt = self._collection("1000.00")
        self.assertEqual(self._collection("1000").name, receipt.name)
        with self.assertRaisesRegex(frappe.ValidationError, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self._collection("1001")
        receipt.reload()
        self.assertEqual(receipt.amount, "1000.00")

    def test_source_namespace_and_event_are_distinct_opaque_identity_parts(self):
        first = self._collection(source_namespace=f"{self.token}:bank", source_event_id="message")
        second = self._collection(source_namespace=self.token, source_event_id="bank:message")
        self.assertNotEqual(first.name, second.name)
        self.assertEqual(first.source_namespace, f"{self.token}:bank")
        self.assertEqual(second.source_event_id, "bank:message")
        self.assertEqual(self._collection(source_namespace=self.token, source_event_id="bank:message").name, second.name)

    def test_replay_without_effective_time_preserves_original_server_time(self):
        receipt = self._collection(effective_at=None)
        original_time = str(receipt.effective_at)
        digest = receipt.payload_sha256
        replay = self._collection(effective_at=None)
        self.assertEqual(replay.name, receipt.name)
        self.assertEqual(str(replay.effective_at), original_time)
        self.assertEqual(replay.payload_sha256, digest)
        with self.assertRaisesRegex(frappe.ValidationError, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self._collection(effective_at="2099-01-01 00:00:00")

    def test_container_park_consumes_receipt_without_reducing_sale_receivable(self):
        sale = self._sale()
        receipt = self._approve(self._collection(), "collection")
        park = self._approve(self._allocation(receipt, "600"), "payment_allocation")
        view = self._position(receipt)
        self.assertEqual(view["container_parked_amount"], "600.00")
        self.assertEqual(view["sale_allocated_amount"], "0.00")
        self.assertEqual(view["unallocated_amount"], "400.00")
        self.assertFalse(park.customer)
        self.assertFalse(park.sale)
        self.assertEqual(self._receivable(sale)["outstanding_receivable"], "1000.00")

    def test_cash_applications_are_many_to_many_without_physical_mutation(self):
        first, second = self._sale("1000"), self._sale("800", event="second-sale")
        a = self._approve(self._collection("900", event="cash-a"), "collection")
        b = self._approve(self._collection("1000", event="cash-b"), "collection")
        physical_before = physical_snapshot(self.container.name)
        for receipt, sale, amount, event in ((a, first, "700", "a-first"), (a, second, "200", "a-second"),
                                            (b, first, "300", "b-first"), (b, second, "600", "b-second")):
            self._approve(self._allocation(receipt, amount, sale=sale, event=event), "payment_allocation")
        self.assertEqual(self._receivable(first)["outstanding_receivable"], "0.00")
        self.assertEqual(self._receivable(second)["outstanding_receivable"], "0.00")
        self.assertEqual(self._position(b)["unallocated_amount"], "100.00")
        self.assertEqual(physical_snapshot(self.container.name), physical_before)

    def test_receipt_cap_counts_container_park_and_sale_applications(self):
        receipt = self._approve(self._collection(), "collection")
        self._approve(self._allocation(receipt, "700", event="park"), "payment_allocation")
        sale = self._sale()
        allocation = self._review(self._allocation(receipt, "400", sale=sale, event="excess"), "payment_allocation")
        frappe.set_user(self.approver)
        with self.assertRaisesRegex(frappe.ValidationError, "COLLECTION_CAP_EXCEEDED"):
            money.approve_payment_allocation(allocation.name)
        self.assertEqual(self._position(receipt)["allocated_amount"], "700.00")
        self.assertEqual(self._receivable(sale)["outstanding_receivable"], "1000.00")

    def test_unresolved_customer_and_unknown_sale_amount_cannot_receive_final_cash(self):
        receipt = self._approve(self._collection(), "collection")
        unresolved = self._sale(resolved=False)
        with self.assertRaises(frappe.ValidationError):
            self._allocation(receipt, "1", sale=unresolved)
        unknown = self._sale(event="unknown-price", rate_known=False)
        candidate = self._review(self._allocation(receipt, "1", sale=unknown), "payment_allocation")
        frappe.set_user(self.approver)
        with self.assertRaisesRegex(frappe.ValidationError, "SALE_GROSS_INCOMPLETE"):
            money.approve_payment_allocation(candidate.name)
        self.assertIsNone(self._receivable(unknown)["outstanding_receivable"])

    def test_park_to_sale_correction_is_atomic_and_replayable(self):
        receipt = self._approve(self._collection(), "collection")
        park = self._approve(self._allocation(receipt, "1000", event="park"), "payment_allocation")
        sale = self._sale()
        correction = self._allocation(receipt, "1000", sale=sale, event="apply-park", supersedes=park.name,
                                      reason="Exact receipt attribution now establishes buyer and Sale")
        self._approve(correction, "payment_allocation")
        park.reload()
        self.assertEqual(park.status, "REVERSED")
        self.assertEqual(park.superseded_by, correction.name)
        self.assertEqual(self._position(receipt)["container_parked_amount"], "0.00")
        self.assertEqual(self._receivable(sale)["outstanding_receivable"], "0.00")
        replay = self._allocation(receipt, "1000", sale=sale, event="apply-park", supersedes=park.name,
                                  reason="Exact receipt attribution now establishes buyer and Sale")
        self.assertEqual(replay.name, correction.name)
        self.assertEqual(json.loads(park.decision_history)[-1]["recorded_at"], json.loads(correction.decision_history)[-1]["recorded_at"])

    def test_payment_proposal_replay_after_collection_reversal_preserves_reversed_record(self):
        receipt = self._approve(self._collection(), "collection")
        sale = self._sale()
        original = self._approve(self._allocation(receipt, "400", sale=sale), "payment_allocation")
        frappe.set_user(self.approver)
        money.reverse_collection(receipt.name, reason="Receipt source establishes reversal", evidence=self.evidence.name)
        original.reload()
        digest, history, version = original.payload_sha256, original.decision_history, original.version
        replay = self._allocation(receipt, "400", sale=sale)
        self.assertEqual(replay.name, original.name)
        self.assertEqual(replay.status, "REVERSED")
        self.assertEqual((replay.payload_sha256, replay.decision_history, replay.version), (digest, history, version))
        self.assertEqual(self._receivable(sale)["cash_applied_amount"], "0.00")
        with self.assertRaisesRegex(frappe.ValidationError, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self._allocation(receipt, "401", sale=sale)
        self.assertEqual(frappe.db.count(ALLOCATION, {"collection": receipt.name}), 1)

    def test_ui_blank_optional_fields_replay_reversed_sale_and_park_allocations(self):
        sale = self._sale()
        for index, target in enumerate((sale, None)):
            with self.subTest(allocation_type="SALE" if target else "CONTAINER_UNAPPLIED"):
                receipt = self._approve(self._collection(event=f"blank-receipt-{index}"), "collection")
                event = f"blank-allocation-{index}"
                original = self._approve(self._allocation(receipt, "100", sale=target, event=event), "payment_allocation")
                frappe.set_user(self.approver)
                money.reverse_collection(receipt.name, reason="Receipt reversal before UI redelivery", evidence=self.evidence.name)
                original.reload()
                history, version = original.decision_history, original.version
                frappe.set_user(self.maker)
                result = money.propose_payment_allocation(
                    collection=receipt.name, allocation_type="SALE" if target else "CONTAINER_UNAPPLIED",
                    amount="100.00", currency=self.masters["currency"], evidence=self.evidence.name,
                    source_event_id=f"{self.token}:{event}", sale=target.name if target else "",
                    container="" if target else self.container.name, customer="", supersedes="", reason="",
                )
                self.assertEqual(result["name"], original.name)
                self.assertEqual(result["status"], "REVERSED")
                original.reload()
                self.assertEqual((original.decision_history, original.version), (history, version))
                self.assertEqual(frappe.db.count(ALLOCATION, {"collection": receipt.name}), 1)
                if target is None:
                    with self.assertRaisesRegex(frappe.ValidationError, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
                        money.propose_payment_allocation(
                            collection=receipt.name, allocation_type="CONTAINER_UNAPPLIED", amount="100.00",
                            currency=self.masters["currency"], evidence=self.evidence.name,
                            source_event_id=f"{self.token}:{event}", container="",
                        )
        self.assertEqual(self._receivable(sale)["cash_applied_amount"], "0.00")

    def test_allocation_cannot_silently_replace_caller_container_with_sale_container(self):
        receipt = self._approve(self._collection(), "collection")
        sale = self._sale()
        frappe.set_user("Administrator")
        other_container = make_container(self.masters, lot_no="OTHER-MONEY-LOT")
        with self.assertRaises(frappe.ValidationError):
            self._allocation(receipt, "100", sale=sale, container=other_container.name)
        self.assertEqual(frappe.db.count(ALLOCATION, {"collection": receipt.name}), 0)
        self.assertEqual(self._receivable(sale)["outstanding_receivable"], "1000.00")

    def test_allocations_reject_unknown_channel_or_undeclared_cash(self):
        for index, changes in enumerate((
            {"payment_channel": "UNKNOWN", "source_classification": "NONE"},
            {"payment_channel": "CASH", "source_classification": "NONE"},
        )):
            receipt = self._approve(self._collection(event=f"unestablished-{index}", **changes), "collection")
            allocation = self._review(self._allocation(receipt, "1", event=f"ineligible-{index}"), "payment_allocation")
            frappe.set_user(self.approver)
            with self.subTest(index=index), self.assertRaises(frappe.ValidationError):
                money.approve_payment_allocation(allocation.name)
            self.assertEqual(self._position(receipt)["allocated_amount"], "0.00")

    def test_cleared_bank_requires_identity_and_same_transaction_cannot_count_twice(self):
        account = self._bank_account()
        args = {"payment_channel": "BANK", "bank_state": "BANK_CLEARED", "source_classification": "BANK_CREDIT_CONFIRMATION",
                "bank_account": account, "bank_reference": f"BANK-{self.token}", "rail": "RTGS"}
        invalid = self._review(self._collection(event="missing-ref", **{**args, "bank_reference": None}), "collection")
        frappe.set_user(self.approver)
        with self.assertRaises(frappe.ValidationError):
            money.approve_collection(invalid.name)
        first = self._approve(self._collection(event="bank-original", **args), "collection")
        second = self._review(self._collection(event="bank-second-message", **args), "collection")
        frappe.set_user(self.approver)
        with self.assertRaisesRegex(frappe.ValidationError, "CONCURRENT_STATE_CONFLICT"):
            money.approve_collection(second.name)
        self.assertTrue(self._position(first)["is_bank_cleared"])
        second.reload()
        self.assertEqual(second.status, "VERIFIED")
        self.assertEqual(self._position(first)["unallocated_amount"], "1000.00")

    def test_expense_estimate_or_unclassified_bridge_cannot_be_approved_setoff(self):
        for index, changes in enumerate(({"agreement_reference": None}, {"adjustment_type": "UNCLASSIFIED"})):
            adjustment = self._review(self._adjustment("77600", event=f"unsupported-{index}", **changes), "adjustment")
            frappe.set_user(self.approver)
            with self.subTest(index=index), self.assertRaises(frappe.ValidationError):
                money.approve_adjustment(adjustment.name)
            adjustment.reload()
            self.assertEqual(adjustment.status, "VERIFIED")
        self.assertEqual(frappe.db.count(COLLECTION, {"source_evidence": self.evidence.name}), 0)

    def test_approved_noncash_adjustments_reduce_debt_without_creating_cash(self):
        sale = self._sale()
        for index, kind in enumerate(("DISCOUNT", "COMMISSION_SETOFF", "CUSTOMER_PAID_EXPENSE_SETOFF")):
            adjustment = self._approve(self._adjustment("100", event=f"kind-{index}", adjustment_type=kind), "adjustment")
            self._approve(self._application(adjustment, sale, "100", event=f"apply-{index}"), "adjustment_application")
        view = self._receivable(sale)
        self.assertEqual(view["cash_applied_amount"], "0.00")
        self.assertEqual(view["adjustment_applied_amount"], "300.00")
        self.assertEqual(view["outstanding_receivable"], "700.00")
        self.assertEqual(frappe.db.count(COLLECTION, {"source_evidence": self.evidence.name}), 0)

    def test_combined_sale_cash_and_adjustment_cap_is_not_two_independent_caps(self):
        sale = self._sale()
        receipt = self._approve(self._collection(), "collection")
        self._approve(self._allocation(receipt, "800", sale=sale), "payment_allocation")
        adjustment = self._approve(self._adjustment("300"), "adjustment")
        application = self._review(self._application(adjustment, sale, "300"), "adjustment_application")
        frappe.set_user(self.approver)
        with self.assertRaisesRegex(frappe.ValidationError, "SALE_RECEIVABLE_CAP_EXCEEDED"):
            money.approve_adjustment_application(application.name)
        self.assertEqual(self._receivable(sale)["outstanding_receivable"], "200.00")
        application.reload()
        self.assertEqual(application.status, "VERIFIED")

    def test_adjustment_capacity_spans_multiple_sales_and_reversal_restores_it(self):
        first, second = self._sale(), self._sale(event="second-sale")
        adjustment = self._approve(self._adjustment("100"), "adjustment")
        application = self._approve(self._application(adjustment, first, "60", event="first"), "adjustment_application")
        excess = self._review(self._application(adjustment, second, "50", event="second"), "adjustment_application")
        frappe.set_user(self.approver)
        with self.assertRaisesRegex(frappe.ValidationError, "ADJUSTMENT_CAP_EXCEEDED"):
            money.approve_adjustment_application(excess.name)
        money.reverse_adjustment_application(application.name, reason="Wrong attribution", evidence=self.evidence.name)
        money.approve_adjustment_application(excess.name)
        application.reload()
        adjustment.reload()
        self.assertEqual(application.status, "REVERSED")
        self.assertEqual(adjustment.unapplied_amount, "50.00")
        self.assertEqual(self._receivable(first)["adjustment_applied_amount"], "0.00")
        self.assertEqual(self._receivable(second)["adjustment_applied_amount"], "50.00")

    def test_adjustment_successor_replay_after_prior_supersession_preserves_decision(self):
        original = self._approve(self._adjustment("100"), "adjustment")
        reason = "Exact discharge agreement corrects the setoff amount"
        successor = self._approve(self._adjustment(
            "200", event="adjustment-correction", supersedes=original.name, reason=reason,
        ), "adjustment")
        original.reload()
        self.assertEqual(original.status, "SUPERSEDED")
        history, version = successor.decision_history, successor.version
        replay = self._adjustment("200", event="adjustment-correction", supersedes=original.name, reason=reason)
        self.assertEqual(replay.name, successor.name)
        self.assertEqual(replay.status, "APPROVED")
        self.assertEqual((replay.decision_history, replay.version), (history, version))
        with self.assertRaisesRegex(frappe.ValidationError, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self._adjustment("201", event="adjustment-correction", supersedes=original.name, reason=reason)
        self.assertEqual(frappe.db.count(ADJUSTMENT, {"supersedes": original.name}), 1)
        self.assertEqual(frappe.db.count(COLLECTION, {"source_evidence": self.evidence.name}), 0)

    def test_adjustment_parent_supersession_reverses_application_without_child_successor(self):
        sale = self._sale()
        original = self._approve(self._adjustment("100"), "adjustment")
        application = self._approve(self._application(original, sale, "60"), "adjustment_application")
        cutoff = json.loads(application.decision_history)[-1]["recorded_at"]
        reason = "Exact discharge agreement corrects the parent adjustment"
        successor = self._adjustment("200", event="parent-adjustment-correction", supersedes=original.name, reason=reason)
        self.assertEqual(self._receivable(sale)["adjustment_applied_amount"], "60.00")
        self._approve(successor, "adjustment")
        original.reload()
        application.reload()
        self.assertEqual(original.status, "SUPERSEDED")
        self.assertEqual(original.superseded_by, successor.name)
        self.assertEqual(successor.supersedes, original.name)
        self.assertEqual(application.status, "REVERSED")
        self.assertFalse(application.superseded_by)
        self.assertEqual(application.receivable_adjustment, original.name)
        self.assertIn(successor.name, json.loads(application.decision_history)[-1]["reason"])
        self.assertEqual(frappe.db.count(APPLICATION, {"sale": sale.name}), 1)
        self.assertEqual(self._receivable(sale)["adjustment_applied_amount"], "0.00")
        self.assertEqual(self._receivable(sale)["outstanding_receivable"], "1000.00")
        self.assertEqual(self._receivable(sale, cutoff)["adjustment_applied_amount"], "60.00")
        events = [json.loads(doc.decision_history)[-1] for doc in (original, application, successor)]
        self.assertEqual(len({event["recorded_at"] for event in events}), 1)
        self.assertEqual(len({event["operation_id"] for event in events}), 1)

    def test_application_replay_after_parent_adjustment_reversal_does_not_restore_setoff(self):
        sale = self._sale()
        adjustment = self._approve(self._adjustment(), "adjustment")
        original = self._approve(self._application(adjustment, sale, "100"), "adjustment_application")
        frappe.set_user(self.approver)
        money.reverse_adjustment(adjustment.name, reason="Discharge agreement revoked", evidence=self.evidence.name)
        original.reload()
        history, version = original.decision_history, original.version
        replay = self._application(adjustment, sale, "100")
        self.assertEqual(replay.name, original.name)
        self.assertEqual(replay.status, "REVERSED")
        self.assertEqual((replay.decision_history, replay.version), (history, version))
        self.assertEqual(self._receivable(sale)["adjustment_applied_amount"], "0.00")
        self.assertEqual(self._receivable(sale)["outstanding_receivable"], "1000.00")
        with self.assertRaisesRegex(frappe.ValidationError, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self._application(adjustment, sale, "101")
        self.assertEqual(frappe.db.count(APPLICATION, {"receivable_adjustment": adjustment.name}), 1)

    def test_reversing_collection_reverses_all_applications_with_one_timestamp(self):
        sale = self._sale()
        receipt = self._approve(self._collection(), "collection")
        allocation = self._approve(self._allocation(receipt, "600", sale=sale), "payment_allocation")
        park = self._approve(self._allocation(receipt, "400", event="park"), "payment_allocation")
        before = physical_snapshot(self.container.name)
        frappe.set_user(self.approver)
        money.reverse_collection(receipt.name, reason="Exact source says receipt reversed", evidence=self.evidence.name)
        events = []
        for doc in (receipt, allocation, park):
            doc.reload()
            self.assertEqual(doc.status, "REVERSED")
            events.append(json.loads(doc.decision_history)[-1])
        self.assertEqual(len({event["recorded_at"] for event in events}), 1)
        self.assertEqual(len({event["operation_id"] for event in events}), 1)
        self.assertEqual(self._receivable(sale)["outstanding_receivable"], "1000.00")
        self.assertEqual(physical_snapshot(self.container.name), before)

    def test_collection_successor_preserves_old_source_and_compensates_on_approval(self):
        sale = self._sale()
        original = self._approve(self._collection(), "collection")
        allocation = self._approve(self._allocation(original, "600", sale=sale), "payment_allocation")
        digest, payload = original.payload_sha256, original.source_payload
        frappe.set_user(self.maker)
        successor = self._doc(COLLECTION, money.supersede_collection(
            original.name, source_event_id=f"{self.token}:receipt-correction", reason="Exact source corrects amount",
            source_evidence=self.evidence.name, changes={"amount": "900"}, expected_version=original.reload().version,
        ))
        self.assertEqual(self._receivable(sale)["cash_applied_amount"], "600.00")
        self._approve(successor, "collection")
        original.reload()
        allocation.reload()
        self.assertEqual(original.status, "SUPERSEDED")
        self.assertEqual(original.superseded_by, successor.name)
        self.assertEqual(original.source_payload, payload)
        self.assertEqual(original.payload_sha256, digest)
        self.assertEqual(allocation.status, "REVERSED")
        self.assertFalse(allocation.superseded_by)
        self.assertEqual(allocation.collection, original.name)
        self.assertEqual(successor.supersedes, original.name)
        self.assertEqual(self._receivable(sale)["cash_applied_amount"], "0.00")
        self.assertEqual(self._position(successor)["unallocated_amount"], "900.00")
        self.assertEqual(json.loads(original.decision_history)[-1]["recorded_at"], json.loads(successor.decision_history)[-1]["recorded_at"])

    def test_historical_positions_keep_pre_reversal_allocations(self):
        sale = self._sale()
        receipt = self._approve(self._collection(), "collection")
        allocation = self._approve(self._allocation(receipt, "400", sale=sale), "payment_allocation")
        cutoff = json.loads(allocation.decision_history)[-1]["recorded_at"]
        frappe.set_user(self.approver)
        money.reverse_payment_allocation(allocation.name, reason="Later attribution correction", evidence=self.evidence.name)
        historical = self._receivable(sale, cutoff)
        self.assertEqual(historical["cash_applied_amount"], "400.00")
        self.assertEqual(historical["outstanding_receivable"], "600.00")
        self.assertEqual(self._position(receipt, cutoff)["unallocated_amount"], "600.00")
        self.assertEqual(self._receivable(sale)["cash_applied_amount"], "0.00")
        self.assertEqual(self._position(receipt)["unallocated_amount"], "1000.00")
        container_history = money.get_container_receivable(self.container.name, as_of=cutoff)
        self.assertEqual(container_history["cash_applied_by_currency"][self.masters["currency"]], "400.00")

    def test_future_effective_receipt_is_recorded_but_not_current_available_cash(self):
        receipt = self._approve(self._collection(effective_at="2099-01-01 00:00:00"), "collection")
        cutoff = json.loads(receipt.decision_history)[-1]["recorded_at"]
        view = self._position(receipt, cutoff)
        self.assertTrue(view["exists"])
        current = money.get_unallocated_collections(self.container.company, as_of=cutoff)
        self.assertNotIn(receipt.name, {row["name"] for row in current["unallocated_collections"]})
        allocation = self._review(self._allocation(receipt, "1"), "payment_allocation")
        frappe.set_user(self.approver)
        with self.assertRaises(frappe.ValidationError):
            money.approve_payment_allocation(allocation.name)
        self.assertEqual(self._position(receipt)["allocated_amount"], "0.00")

    def test_collection_reversal_requires_evidence_from_its_company(self):
        receipt = self._approve(self._collection(), "collection")
        frappe.set_user("Administrator")
        other_company = frappe.get_doc({
            "doctype": "Company", "company_name": f"Money Scope {self.token}",
            "abbr": f"M{self.token[:4]}", "default_currency": self.masters["currency"],
            "country": frappe.db.get_value("Company", self.container.company, "country") or "India",
        }).insert(ignore_permissions=True)
        other_container = make_container({**self.masters, "company": other_company.name})
        foreign_evidence = frappe.get_doc({
            "doctype": "Fresko Evidence", "container": other_container.name,
            "evidence_type": "Note", "notes": "Synthetic unrelated Company reversal source",
        }).insert(ignore_permissions=True)
        frappe.set_user(self.approver)
        with self.assertRaises(frappe.ValidationError):
            money.reverse_collection(receipt.name, reason="Unrelated Company source", evidence=foreign_evidence.name)
        receipt.reload()
        self.assertEqual(receipt.status, "APPROVED")
        self.assertEqual(self._position(receipt)["unallocated_amount"], "1000.00")

    def test_sale_supersession_compensates_cash_and_noncash_without_retargeting(self):
        sale = self._sale()
        receipt = self._approve(self._collection(), "collection")
        cash = self._approve(self._allocation(receipt, "400", sale=sale), "payment_allocation")
        adjustment = self._approve(self._adjustment("100"), "adjustment")
        noncash = self._approve(self._application(adjustment, sale, "100"), "adjustment_application")
        before = physical_snapshot(self.container.name)
        frappe.set_user(self.salesperson)
        proposal = commercial.propose_rate(sale.name, line_key=sale.lines[0].line_key, rate="900",
                                           evidence=self.evidence.name, source_event_id=f"{self.token}:sale-correction",
                                           reason="Exact corrected Sale price")
        successor = self._doc(SALE, proposal)
        commercial.submit_sale(successor.name)
        frappe.set_user(self.maker)
        commercial.verify_sale(successor.name)
        frappe.set_user(self.approver)
        commercial.approve_sale(successor.name)
        for doc in (cash, noncash):
            doc.reload()
            self.assertEqual(doc.status, "REVERSED")
            self.assertEqual(doc.sale, sale.name)
        self.assertEqual(self._position(receipt)["unallocated_amount"], "1000.00")
        self.assertEqual(self._receivable(successor)["cash_applied_amount"], "0.00")
        self.assertEqual(self._receivable(successor)["adjustment_applied_amount"], "0.00")
        self.assertEqual(physical_snapshot(self.container.name), before)

    def test_supplier_with_accounts_and_salesperson_cannot_read_pooled_money(self):
        receipt = self._approve(self._collection(), "collection")
        sale = self._sale()
        allocation = self._approve(self._allocation(receipt, "100", sale=sale), "payment_allocation")
        adjustment = self._approve(self._adjustment(), "adjustment")
        application = self._approve(self._application(adjustment, sale, "100"), "adjustment_application")
        for user in (self.supplier, self.salesperson):
            frappe.set_user(user)
            for doctype, doc in ((COLLECTION, receipt), (ALLOCATION, allocation), (ADJUSTMENT, adjustment), (APPLICATION, application)):
                with self.subTest(user=user, doctype=doctype), self.assertRaises(frappe.PermissionError):
                    client.get(doctype, doc.name)
            for call in (lambda: money.get_collection_position(receipt.name), lambda: money.get_sale_receivable(sale.name),
                         lambda: money.get_customer_receivable(self.customer, self.container.company),
                         lambda: money.get_unallocated_collections(self.container.company)):
                with self.assertRaises(frappe.PermissionError):
                    call()
            with self.assertRaises(frappe.PermissionError):
                self._collection(user=user)

    def test_direct_api_save_delete_and_forged_capability_flags_cannot_write_money(self):
        receipt = self._collection()
        frappe.set_user(self.manager)
        for field, value in (("amount", "1"), ("status", "APPROVED"), ("prepared_by", self.approver)):
            with self.subTest(field=field), self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                client.set_value(COLLECTION, receipt.name, field, value)
        forged = receipt.as_dict()
        forged.pop("name")
        forged["flags"] = {"in_service": True, "in_money_service": True}
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            client.insert(forged)
        receipt.flags.in_service = True
        receipt.flags.in_money_service = True
        receipt.amount = "1"
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            receipt.save(ignore_permissions=True)
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            frappe.delete_doc(COLLECTION, receipt.name, ignore_permissions=True)
        receipt.reload()
        self.assertEqual(receipt.amount, "1000.00")
        self.assertEqual(receipt.status, "DRAFT")

    def test_source_binding_hashes_persisted_bytes_and_protects_original_file(self):
        frappe.set_user("Administrator")
        source_bytes = b"Synthetic source: bank credit, INR 1000; no real transaction data.\n"
        file_doc = save_file(f"money-{self.token}.txt", source_bytes, "Fresko Evidence", self.evidence.name, is_private=1)
        self.addCleanup(self._cleanup_test_file, file_doc.name)
        self.evidence.file = file_doc.file_url
        self.evidence.save(ignore_permissions=True)
        receipt = self._collection()
        self.assertEqual(receipt.evidence_file, file_doc.name)
        self.assertEqual(receipt.evidence_sha256, hashlib.sha256(source_bytes).hexdigest())
        self.assertEqual(json.loads(receipt.evidence_snapshot)["file_sha256"], receipt.evidence_sha256)
        frappe.set_user("Administrator")
        file_doc.file_name = "forged-replacement.txt"
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            file_doc.save(ignore_permissions=True)
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            frappe.delete_doc("File", file_doc.name, ignore_permissions=True)
        file_doc.reload()
        self.assertEqual(file_doc.get_content(), source_bytes)

    @staticmethod
    def _cleanup_test_file(file_name):
        # Only synthetic fixtures; remove the test's own immutable reference first.
        frappe.set_user("Administrator")
        frappe.db.delete(COLLECTION, {"evidence_file": file_name})
        if frappe.db.exists("File", file_name):
            frappe.delete_doc("File", file_name, ignore_permissions=True)

    def _cleanup_committed_rows(self):
        """Surgical cleanup of fixture rows committed for real worker connections."""
        frappe.set_user("Administrator")
        frappe.db.rollback()
        frappe.db.delete("Fresko Exception", {"container": self.container.name})
        collections = list(set(self.documents[COLLECTION]))
        if collections:
            frappe.db.delete("Fresko Exception", {"collection": ("in", collections)})
        for dt in (APPLICATION, ALLOCATION, ADJUSTMENT, COLLECTION):
            names = list(set(self.documents[dt]))
            if names:
                frappe.db.delete(dt, {"name": ("in", names)})
        sales = list(set(self.documents[SALE]))
        if sales:
            frappe.db.delete("Fresko Commercial Sale Line", {"parent": ("in", sales)})
            frappe.db.delete(SALE, {"name": ("in", sales)})
        aliases = list(set(self.documents["Fresko Party Alias Mapping"]))
        if aliases:
            frappe.db.delete("Fresko Party Alias Mapping", {"name": ("in", aliases)})
        frappe.db.delete("Fresko Evidence", {"name": self.evidence.name})
        frappe.db.delete("Fresko Container Lot", {"parent": self.container.name})
        frappe.db.delete("Fresko Container", {"name": self.container.name})
        frappe.db.delete("Customer", {"name": self.customer})
        frappe.db.commit()

    def _race_approve(self, allocations):
        site = frappe.local.site
        barrier = threading.Barrier(2)
        outcomes = Queue()

        def worker(name):
            frappe.init(site=site)
            frappe.connect()
            try:
                frappe.set_user(self.approver)
                barrier.wait(timeout=20)
                money.approve_payment_allocation(name)
                frappe.db.commit()
                outcomes.put((name, "OK", ""))
            except Exception as exc:
                frappe.db.rollback()
                outcomes.put((name, "DENIED", str(exc)))
            finally:
                frappe.destroy()

        threads = [threading.Thread(target=worker, args=(row.name,)) for row in allocations]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertFalse(any(thread.is_alive() for thread in threads), "Money allocation worker hung")
        self.assertEqual(outcomes.qsize(), 2)
        frappe.db.rollback()
        result = [outcomes.get_nowait(), outcomes.get_nowait()]
        self.assertEqual([row[1] for row in result].count("OK"), 1, result)
        self.assertEqual([row[1] for row in result].count("DENIED"), 1, result)
        return next(row[2] for row in result if row[1] == "DENIED")

    def test_two_connections_cannot_spend_one_receipt_twice(self):
        receipt = self._approve(self._collection(), "collection")
        first, second = self._sale(), self._sale(event="second-sale")
        allocations = [self._review(self._allocation(receipt, "600", sale=first, event="race-a"), "payment_allocation"),
                       self._review(self._allocation(receipt, "600", sale=second, event="race-b"), "payment_allocation")]
        self.addCleanup(self._cleanup_committed_rows)
        frappe.db.commit()
        denial = self._race_approve(allocations)
        self.assertIn("COLLECTION_CAP_EXCEEDED", denial)
        self.assertEqual(self._position(receipt)["allocated_amount"], "600.00")
        self.assertEqual(self._position(receipt)["unallocated_amount"], "400.00")
        self.assertEqual(physical_snapshot(self.container.name)["posted_physical_total"], 0)

    def test_two_connections_cannot_overpay_one_sale(self):
        sale = self._sale()
        first = self._approve(self._collection("600", event="receipt-a"), "collection")
        second = self._approve(self._collection("600", event="receipt-b"), "collection")
        allocations = [self._review(self._allocation(first, "600", sale=sale, event="race-a"), "payment_allocation"),
                       self._review(self._allocation(second, "600", sale=sale, event="race-b"), "payment_allocation")]
        self.addCleanup(self._cleanup_committed_rows)
        frappe.db.commit()
        denial = self._race_approve(allocations)
        self.assertIn("SALE_RECEIVABLE_CAP_EXCEEDED", denial)
        self.assertEqual(self._receivable(sale)["cash_applied_amount"], "600.00")
        self.assertEqual(self._receivable(sale)["outstanding_receivable"], "400.00")

    def test_frappe_rpc_preserves_transport_cmd_and_rejects_forged_actor(self):
        frappe.set_user(self.maker)
        args = {"company": self.container.company, "source_namespace": "synthetic-rpc",
                "source_event_id": self.token, "direction": "UNKNOWN", "amount": None,
                "payment_channel": "UNKNOWN"}
        result = frappe.call(money.create_collection, cmd="fresko_universe.money.create_collection", **args)
        doc = self._doc(COLLECTION, result)
        self.assertEqual(doc.prepared_by, self.maker)
        before = frappe.db.count(COLLECTION)
        with self.assertRaises(frappe.ValidationError):
            frappe.call(money.create_collection, cmd="fresko_universe.money.create_collection",
                        approved_by=self.approver, **{**args, "source_event_id": self.token + "-forged"})
        self.assertEqual(frappe.db.count(COLLECTION), before)
