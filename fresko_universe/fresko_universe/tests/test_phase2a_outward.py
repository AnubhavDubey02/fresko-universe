"""Phase 2A physical Outward integration gates.

Run with a migrated site:

    bench --site <site> run-tests --app fresko_universe \
      --module fresko_universe.tests.test_phase2a_outward

These tests intentionally use the public ``fresko_universe.outward`` facade.
They are not offline smoke tests: transaction boundaries, permissions, unique
source identity, and physical totals require a real Frappe/MariaDB site.
"""

from __future__ import annotations

import threading
from queue import Queue

import frappe
from frappe.tests.utils import FrappeTestCase

from fresko_universe import outward
from fresko_universe.fresko_core.physical import physical_snapshot
from fresko_universe.tests.utils import ensure_masters, make_container, make_deal


def _ensure_user(email: str, roles: list[str]) -> str:
    if not frappe.db.exists("User", email):
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": email.split("@", 1)[0],
                "send_welcome_email": 0,
                "user_type": "System User",
            }
        )
        user.insert(ignore_permissions=True)
    user = frappe.get_doc("User", email)
    existing = {row.role for row in user.roles}
    for role in roles:
        if role not in existing and frappe.db.exists("Role", role):
            user.append("roles", {"role": role})
    user.save(ignore_permissions=True)
    frappe.db.commit()
    return email


class TestPhase2AOutward(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.masters = ensure_masters()
        cls.maker = _ensure_user(
            "phase2a_outward_maker@example.com",
            ["Fresko Salesperson", "Fresko Approver"],
        )
        cls.checker = _ensure_user(
            "phase2a_outward_checker@example.com", ["Fresko Approver"]
        )
        cls.accounts = _ensure_user(
            "phase2a_outward_accounts@example.com", ["Fresko Accounts"]
        )

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")

    def _evidence(self, container, label: str):
        return frappe.get_doc(
            {
                "doctype": "Fresko Evidence",
                "evidence_type": "Note",
                "container": container.name,
                "notes": f"phase2a outward evidence: {label}",
            }
        ).insert(ignore_permissions=True)

    def _line(
        self,
        qty: int,
        *,
        lot_no: str | None,
        source_line_ref: str = "1",
        uom: str | None = None,
    ):
        line_uom = uom or self.masters["uom"]
        return {
            "source_line_ref": source_line_ref,
            "raw_lot_text": lot_no or "LOT / UNMAPPED",
            "lot_no": lot_no,
            "qty": qty,
            "uom": line_uom,
            "raw_qty_text": str(qty),
            "raw_uom_text": line_uom,
            "raw_rate_text": None,
        }

    def _create(
        self,
        container,
        evidence,
        event_id: str,
        qty: int,
        *,
        lot_no: str | None,
        uom: str | None = None,
    ):
        frappe.set_user(self.maker)
        result = outward.create(
            container=container.name,
            movement_at="2026-10-01 10:00:00",
            source_evidence=evidence.name,
            source_event_id=event_id,
            lines=[self._line(qty, lot_no=lot_no, uom=uom)],
        )
        self.assertTrue(result["name"])
        return frappe.get_doc("Fresko Outward", result["name"])

    def _submit(self, outward_doc):
        frappe.set_user(self.maker)
        outward.submit_for_review(outward_doc.name)
        outward_doc.reload()
        self.assertEqual(outward_doc.status, "Review Pending")

    def _post(self, outward_doc):
        self._submit(outward_doc)
        frappe.set_user(self.checker)
        result = outward.post(outward_doc.name)
        outward_doc.reload()
        self.assertEqual(outward_doc.status, "Posted")
        return result

    def _open_unpriced(self, outward_name):
        return frappe.get_all(
            "Fresko Exception",
            filters={
                "outward": outward_name,
                "exception_type": "OUTWARD_UNPRICED",
                "status": ("in", ["Open", "In Progress"]),
            },
            pluck="name",
        )

    def _open_exception(self, outward_name, exception_type):
        return frappe.get_all(
            "Fresko Exception",
            filters={
                "outward": outward_name,
                "exception_type": exception_type,
                "status": ("in", ["Open", "In Progress"]),
            },
            fields=["name", "exception_type", "description", "status"],
            order_by="creation asc",
        )

    def _cleanup_committed_rows(
        self,
        *,
        container_name: str,
        outward_names: list[str],
        assertion_names: list[str] | None = None,
        evidence_names: list[str] | None = None,
    ):
        """Remove only rows committed by a worker-backed concurrency test."""
        frappe.set_user("Administrator")
        frappe.db.rollback()
        outward_names = list(outward_names)
        assertion_names = list(assertion_names or [])
        evidence_names = list(evidence_names or [])
        for outward_name in outward_names:
            frappe.db.delete("Fresko Exception", {"outward": outward_name})
        for assertion_name in assertion_names:
            frappe.db.delete("Fresko Field Assertion", {"name": assertion_name})
        if outward_names:
            frappe.db.delete(
                "Fresko Outward Line", {"parent": ("in", outward_names)}
            )
            frappe.db.delete("Fresko Outward", {"name": ("in", outward_names)})
        for evidence_name in evidence_names:
            frappe.db.delete("Fresko Evidence", {"name": evidence_name})
        frappe.db.delete("Fresko Container Lot", {"parent": container_name})
        frappe.db.delete("Fresko Container", {"name": container_name})
        frappe.db.commit()

    def _run_two_connection_workers(self, worker, *, user=None):
        site = frappe.local.site
        barrier = threading.Barrier(2)
        outcomes = Queue()

        def run_one(argument):
            frappe.init(site=site)
            frappe.connect()
            try:
                frappe.set_user(user or self.checker)
                barrier.wait(timeout=20)
                worker(argument)
                frappe.db.commit()
                outcomes.put((argument, "OK", ""))
            except Exception as exc:
                frappe.db.rollback()
                outcomes.put((argument, "DENIED", str(exc)))
            finally:
                frappe.destroy()

        return outcomes, run_one

    def test_447_unpriced_outward_posts_without_deal_buyer_rate_and_expected_exceptions(self):
        container = make_container(
            self.masters,
            container_no=f"P2A-PLUM-{frappe.generate_hash(length=6)}",
            lot_no="PLUM-447",
            inward_qty=500,
            rate_floor=None,
            rate_ceiling=None,
        )
        evidence = self._evidence(container, "447 plum")
        doc = self._create(container, evidence, "plum-outward-447", 447, lot_no="PLUM-447")
        self._post(doc)

        self.assertFalse(getattr(doc, "deal", None))
        self.assertFalse(getattr(doc, "buyer", None))
        self.assertFalse(getattr(doc, "customer", None))
        self.assertFalse(getattr(doc, "rate", None))
        self.assertEqual(len(self._open_unpriced(doc.name)), 1)
        self.assertEqual(
            len(self._open_exception(doc.name, "OUTWARD_WITHOUT_DEAL")), 1
        )
        snapshot = physical_snapshot(container.name)
        self.assertEqual(snapshot["posted_by_lot"]["PLUM-447"], 447)
        self.assertEqual(snapshot["posted_physical_total"], 447)

    def test_no_deal_post_opens_one_deterministic_outward_without_deal_exception(self):
        container = make_container(
            self.masters,
            container_no=f"P2A-NO-DEAL-{frappe.generate_hash(length=6)}",
            lot_no="NO-DEAL-LOT",
            inward_qty=20,
        )
        evidence = self._evidence(container, "no deal exception")
        doc = self._create(container, evidence, "no-deal-exception", 5, lot_no="NO-DEAL-LOT")
        self._post(doc)

        exceptions = self._open_exception(doc.name, "OUTWARD_WITHOUT_DEAL")
        self.assertEqual(len(exceptions), 1)
        self.assertEqual(exceptions[0].exception_type, "OUTWARD_WITHOUT_DEAL")
        self.assertEqual(
            exceptions[0].description,
            "Physical Outward posted without an associated commercial Deal",
        )

    def test_raw_source_strings_are_preserved_verbatim(self):
        container = make_container(
            self.masters,
            container_no=f"P2A-RAW-{frappe.generate_hash(length=6)}",
            lot_no="RAW-LOT",
            inward_qty=100,
        )
        evidence = self._evidence(container, "verbatim raw source")
        frappe.set_user(self.maker)
        created = outward.create(
            container=container.name,
            movement_at="2026-10-01 10:30:00",
            source_evidence=evidence.name,
            source_event_id="  raw-event-id  ",
            gatepass_no="  GP / 007  ",
            vehicle_no="  KA-01-AB-1234  ",
            raw_party_name="  Shri M/s A & B  ",
            lines=[
                {
                    "source_line_ref": "  raw-line-ref  ",
                    "raw_lot_text": "  BALANCE / UNMAPPED  ",
                    "lot_no": None,
                    "qty": 92,
                    "uom": self.masters["uom"],
                    "raw_qty_text": "  92 crates  ",
                    "raw_uom_text": "  Crate  ",
                    "raw_rate_text": "  NOT AVAILABLE  ",
                }
            ],
        )
        doc = frappe.get_doc("Fresko Outward", created["name"])
        self.assertEqual(doc.source_event_id, "  raw-event-id  ")
        self.assertEqual(doc.gatepass_no, "  GP / 007  ")
        self.assertEqual(doc.vehicle_no, "  KA-01-AB-1234  ")
        self.assertEqual(doc.raw_party_name, "  Shri M/s A & B  ")
        self.assertEqual(doc.lines[0].source_line_ref, "  raw-line-ref  ")
        self.assertEqual(doc.lines[0].raw_lot_text, "  BALANCE / UNMAPPED  ")
        self.assertEqual(doc.lines[0].raw_qty_text, "  92 crates  ")
        self.assertEqual(doc.lines[0].raw_uom_text, "  Crate  ")
        self.assertEqual(doc.lines[0].raw_rate_text, "  NOT AVAILABLE  ")

    def test_duplicate_gatepass_opens_pairwise_exception_without_rejection(self):
        container = make_container(
            self.masters,
            container_no=f"P2A-GP-{frappe.generate_hash(length=6)}",
            lot_no="GP-LOT",
            inward_qty=50,
        )
        evidence = self._evidence(container, "duplicate gatepass")
        frappe.set_user(self.maker)
        first_result = outward.create(
            container=container.name,
            movement_at="2026-10-01 10:00:00",
            source_evidence=evidence.name,
            source_event_id="gatepass-first",
            gatepass_no="  GP / 007  ",
            lines=[
                self._line(10, lot_no="GP-LOT", source_line_ref="first-a"),
                self._line(5, lot_no="GP-LOT", source_line_ref="first-b"),
            ],
        )
        first = frappe.get_doc("Fresko Outward", first_result["name"])
        self._post(first)
        self.assertFalse(self._open_exception(first.name, "DUPLICATE_GATEPASS"))

        frappe.set_user(self.maker)
        second_result = outward.create(
            container=container.name,
            movement_at="2026-10-01 11:00:00",
            source_evidence=evidence.name,
            source_event_id="gatepass-second",
            gatepass_no="gp-007",
            lines=[self._line(5, lot_no="GP-LOT", source_line_ref="second-a")],
        )
        second = frappe.get_doc("Fresko Outward", second_result["name"])
        self._post(second)
        second.reload()
        first.reload()
        self.assertEqual(first.gatepass_no, "  GP / 007  ")
        self.assertEqual(second.gatepass_no, "gp-007")
        self.assertEqual(first.gatepass_comparison_key, second.gatepass_comparison_key)
        duplicates = frappe.get_all(
            "Fresko Exception",
            filters={
                "exception_type": "DUPLICATE_GATEPASS",
                "outward": second.name,
                "related_outward": first.name,
                "status": "Open",
            },
            fields=["name", "outward", "related_outward"],
        )
        self.assertEqual(len(duplicates), 1)

        frappe.set_user(self.maker)
        reversal_result = outward.reverse(
            outward_name=first.name,
            movement_at="2026-10-01 12:00:00",
            source_evidence=evidence.name,
            source_event_id="gatepass-first-reversal",
            reason="test full reversal",
        )
        reversal = frappe.get_doc("Fresko Outward", reversal_result["name"])
        self._post(reversal)
        self.assertEqual(reversal.gatepass_no, first.gatepass_no)
        self.assertFalse(self._open_exception(reversal.name, "DUPLICATE_GATEPASS"))

    def test_180_unpriced_then_authorized_rate_assertion_resolves_without_mutating_outward(self):
        container = make_container(
            self.masters,
            container_no=f"P2A-GRAPE-{frappe.generate_hash(length=6)}",
            lot_no="GRAPE-180",
            inward_qty=200,
            rate_floor=None,
            rate_ceiling=None,
        )
        movement_evidence = self._evidence(container, "180 grapes movement")
        doc = self._create(container, movement_evidence, "grape-outward-180", 180, lot_no="GRAPE-180")
        self._post(doc)
        doc.reload()
        original_payload = doc.payload_sha256
        original_qty = doc.lines[0].qty
        line_key = doc.lines[0].line_key
        self.assertEqual(len(self._open_unpriced(doc.name)), 1)

        rate_evidence = self._evidence(container, "later authorized grape rate")
        frappe.set_user(self.maker)
        assertion = outward.create_rate_assertion(
            outward_name=doc.name,
            outward_line_key=line_key,
            assertion_basis="USER_CONFIRMED",
            raw_value="700",
            rate=700,
            currency=self.masters["currency"],
            rate_uom=self.masters["uom"],
            evidence=rate_evidence.name,
            effective_at="2026-10-01 12:00:00",
            reason="authorized later rate",
        )
        outward.submit_assertion(assertion["name"])
        frappe.set_user(self.checker)
        outward.review_assertion(assertion["name"], "ACTIVATE")

        assertion_doc = frappe.get_doc("Fresko Field Assertion", assertion["name"])
        doc.reload()
        self.assertEqual(assertion_doc.status, "Active")
        self.assertEqual(doc.status, "Posted")
        self.assertEqual(doc.payload_sha256, original_payload)
        self.assertEqual(doc.lines[0].qty, original_qty)
        self.assertEqual(len(self._open_unpriced(doc.name)), 0)

        other_uom = frappe.db.get_value(
            "UOM", {"name": ("!=", self.masters["uom"])}, "name"
        )
        if other_uom:
            mismatch_evidence = self._evidence(container, "mismatched rate UOM")
            frappe.set_user(self.maker)
            with self.assertRaises(frappe.ValidationError):
                outward.create_rate_assertion(
                    outward_name=doc.name,
                    outward_line_key=line_key,
                    assertion_basis="USER_CONFIRMED",
                    raw_value="701",
                    rate=701,
                    currency=self.masters["currency"],
                    rate_uom=other_uom,
                    evidence=mismatch_evidence.name,
                    effective_at="2026-10-01 12:30:00",
                    reason="known rate UOM mismatch",
                )

    def test_maker_cannot_self_post(self):
        container = make_container(
            self.masters,
            container_no=f"P2A-SELF-{frappe.generate_hash(length=6)}",
            lot_no="SELF-LOT",
            inward_qty=20,
        )
        evidence = self._evidence(container, "maker separation")
        doc = self._create(container, evidence, "maker-self-post", 5, lot_no="SELF-LOT")
        self._submit(doc)
        frappe.set_user(self.maker)
        with self.assertRaises(frappe.PermissionError):
            outward.post(doc.name)
        doc.reload()
        self.assertEqual(doc.status, "Review Pending")

    def test_accounts_cannot_mutate_outward(self):
        container = make_container(
            self.masters,
            container_no=f"P2A-ACCT-{frappe.generate_hash(length=6)}",
            lot_no="ACCT-LOT",
            inward_qty=20,
        )
        evidence = self._evidence(container, "accounts ACL")
        doc = self._create(container, evidence, "accounts-cannot-mutate", 5, lot_no="ACCT-LOT")
        self._submit(doc)
        frappe.set_user(self.accounts)
        with self.assertRaises(frappe.PermissionError):
            outward.post(doc.name)
        doc.reload()
        doc.status = "Posted"
        with self.assertRaises(frappe.PermissionError):
            doc.save(ignore_permissions=True)

    def test_mapped_lot_overdraw_fails_without_posting(self):
        container = make_container(
            self.masters,
            container_no=f"P2A-OVERDRAW-{frappe.generate_hash(length=6)}",
            lot_no="OVERDRAW-LOT",
            inward_qty=100,
        )
        evidence = self._evidence(container, "mapped lot overdraw")
        doc = self._create(container, evidence, "mapped-lot-overdraw", 101, lot_no="OVERDRAW-LOT")
        self._submit(doc)
        frappe.set_user(self.checker)
        with self.assertRaises(frappe.ValidationError):
            outward.post(doc.name)
        doc.reload()
        self.assertEqual(doc.status, "Review Pending")
        self.assertEqual(physical_snapshot(container.name)["posted_physical_total"], 0)

    def test_mapped_line_uom_mismatch_is_rejected_before_posting(self):
        other_uom = frappe.db.get_value(
            "UOM", {"name": ("!=", self.masters["uom"])}, "name"
        )
        if not other_uom:
            self.skipTest("site requires at least two UOMs for mismatch coverage")
        container = make_container(
            self.masters,
            container_no=f"P2A-UOM-MISMATCH-{frappe.generate_hash(length=6)}",
            lot_no="UOM-MISMATCH-LOT",
            inward_qty=20,
        )
        evidence = self._evidence(container, "mapped line UOM mismatch")
        doc = self._create(
            container,
            evidence,
            "mapped-line-uom-mismatch",
            5,
            lot_no="UOM-MISMATCH-LOT",
            uom=other_uom,
        )
        self._submit(doc)
        frappe.set_user(self.checker)
        with self.assertRaises(frappe.ValidationError):
            outward.post(doc.name)
        doc.reload()
        self.assertEqual(doc.status, "Review Pending")
        self.assertEqual(physical_snapshot(container.name)["posted_physical_total"], 0)

    def test_unmapped_outward_cannot_exceed_container_total_inward(self):
        container = make_container(
            self.masters,
            container_no=f"P2A-UNMAPPED-OVERDRAW-{frappe.generate_hash(length=6)}",
            lot_no="UNMAPPED-OVERDRAW-LOT",
            inward_qty=100,
        )
        evidence = self._evidence(container, "unmapped container overdraw")
        doc = self._create(
            container,
            evidence,
            "unmapped-container-overdraw",
            101,
            lot_no=None,
        )
        self._submit(doc)
        frappe.set_user(self.checker)
        with self.assertRaises(frappe.ValidationError):
            outward.post(doc.name)
        doc.reload()
        self.assertEqual(doc.status, "Review Pending")
        snapshot = physical_snapshot(container.name)
        self.assertEqual(snapshot["posted_physical_total"], 0)
        self.assertEqual(snapshot["unmapped_physical_qty"], 0)

    def test_source_replay_same_payload_is_idempotent_and_changed_payload_fails(self):
        container = make_container(
            self.masters,
            container_no=f"P2A-REPLAY-{frappe.generate_hash(length=6)}",
            lot_no="REPLAY-LOT",
            inward_qty=100,
        )
        evidence = self._evidence(container, "source replay")
        first = self._create(container, evidence, "same-source-event", 10, lot_no="REPLAY-LOT")
        self.addCleanup(
            lambda: self._cleanup_committed_rows(
                container_name=container.name,
                outward_names=[first.name],
                evidence_names=[evidence.name],
            )
        )
        # Make the original visible to the independent durability transaction.
        frappe.db.commit()
        frappe.set_user(self.maker)
        replay = outward.create(
            container=container.name,
            movement_at="2026-10-01 10:00:00",
            source_evidence=evidence.name,
            source_event_id="same-source-event",
            lines=[self._line(10, lot_no="REPLAY-LOT")],
        )
        self.assertEqual(replay["name"], first.name)
        self.assertTrue(replay["replayed"])
        self.assertEqual(frappe.db.count("Fresko Outward", {"source_event_key": first.source_event_key}), 1)

        with self.assertRaises(frappe.UniqueValidationError):
            outward.create(
                container=container.name,
                movement_at="2026-10-01 10:00:00",
                source_evidence=evidence.name,
                source_event_id="same-source-event",
                lines=[self._line(11, lot_no="REPLAY-LOT")],
            )
        with self.assertRaises(frappe.UniqueValidationError):
            outward.create(
                container=container.name,
                movement_at="2026-10-01 10:00:00",
                source_evidence=evidence.name,
                source_event_id="same-source-event",
                gatepass_no="CHANGED",
                lines=[self._line(10, lot_no="REPLAY-LOT")],
            )
        self.assertEqual(frappe.db.count("Fresko Outward", {"source_event_key": first.source_event_key}), 1)
        # Reset the main connection's snapshot before checking the independently
        # committed append-only audit attempt.
        frappe.db.rollback()
        attempts = frappe.get_all(
            "Fresko Evidence Attempt",
            filters={
                "evidence": evidence.name,
                "operation": "OUTWARD_CREATE",
                "outcome": "CONFLICT_PAYLOAD_MISMATCH",
            },
            fields=["name", "durability_state"],
            order_by="creation desc",
        )
        self.assertTrue(attempts)
        self.assertEqual(attempts[0].durability_state, "COMMITTED_INDEPENDENT")

    def test_full_reversal_preserves_original_and_nets_physical_quantity(self):
        container = make_container(
            self.masters,
            container_no=f"P2A-REV-{frappe.generate_hash(length=6)}",
            lot_no="REV-LOT",
            inward_qty=100,
        )
        movement_evidence = self._evidence(container, "original movement")
        original = self._create(container, movement_evidence, "original-outward", 60, lot_no="REV-LOT")
        self._post(original)
        original.reload()
        original_payload = original.payload_sha256

        reversal_evidence = self._evidence(container, "reversal movement")
        frappe.set_user(self.maker)
        reversal = outward.reverse(
            outward_name=original.name,
            movement_at="2026-10-01 13:00:00",
            source_evidence=reversal_evidence.name,
            source_event_id="reversal-outward",
            reason="test compensating reversal",
        )
        reversal_doc = frappe.get_doc("Fresko Outward", reversal["name"])
        self._post(reversal_doc)

        original.reload()
        reversal_doc.reload()
        self.assertEqual(original.status, "Posted")
        self.assertEqual(original.payload_sha256, original_payload)
        self.assertEqual(reversal_doc.status, "Posted")
        self.assertEqual(reversal_doc.movement_type, "REVERSAL")
        self.assertEqual(reversal_doc.reverses_outward, original.name)
        snapshot = physical_snapshot(container.name)
        self.assertEqual(snapshot["posted_by_lot"]["REV-LOT"], 0)
        self.assertEqual(snapshot["posted_physical_total"], 0)

    def test_same_reversal_source_event_replays_existing_draft_reversal(self):
        container = make_container(
            self.masters,
            container_no=f"P2A-REV-REPLAY-{frappe.generate_hash(length=6)}",
            lot_no="REV-REPLAY-LOT",
            inward_qty=100,
        )
        movement_evidence = self._evidence(container, "reversal replay original")
        original = self._create(
            container,
            movement_evidence,
            "reversal-replay-original",
            30,
            lot_no="REV-REPLAY-LOT",
        )
        self._post(original)
        reversal_evidence = self._evidence(container, "reversal replay source")
        frappe.set_user(self.maker)
        first = outward.reverse(
            outward_name=original.name,
            movement_at="2026-10-01 13:00:00",
            source_evidence=reversal_evidence.name,
            source_event_id="same-reversal-source-event",
            reason="replayable draft reversal",
        )
        replay = outward.reverse(
            outward_name=original.name,
            movement_at="2026-10-01 13:00:00",
            source_evidence=reversal_evidence.name,
            source_event_id="same-reversal-source-event",
            reason="replayable draft reversal",
        )

        self.assertEqual(replay["name"], first["name"])
        self.assertTrue(replay["replayed"])
        reversal_doc = frappe.get_doc("Fresko Outward", first["name"])
        self.assertEqual(reversal_doc.status, "Draft")
        self.assertEqual(reversal_doc.movement_type, "REVERSAL")
        self.assertEqual(reversal_doc.reverses_outward, original.name)

    def test_concurrent_distinct_reversal_sources_create_one_draft_only(self):
        """Distinct reversal identities still serialize on one posted Outward."""
        container = make_container(
            self.masters,
            container_no=f"P2A-REVERSAL-RACE-{frappe.generate_hash(length=6)}",
            lot_no="REVERSAL-RACE-LOT",
            inward_qty=100,
        )
        movement_evidence = self._evidence(container, "reversal race original")
        reversal_evidence_a = self._evidence(container, "reversal race A")
        reversal_evidence_b = self._evidence(container, "reversal race B")
        original = self._create(
            container,
            movement_evidence,
            "reversal-race-original",
            40,
            lot_no="REVERSAL-RACE-LOT",
        )
        self._post(original)

        evidence_and_events = [
            (reversal_evidence_a.name, "distinct-reversal-event-a"),
            (reversal_evidence_b.name, "distinct-reversal-event-b"),
        ]

        def cleanup_reversal_race_rows():
            frappe.db.rollback()
            reversal_names = frappe.get_all(
                "Fresko Outward",
                filters={"reverses_outward": original.name},
                pluck="name",
            )
            self._cleanup_committed_rows(
                container_name=container.name,
                outward_names=[original.name, *reversal_names],
                evidence_names=[
                    movement_evidence.name,
                    reversal_evidence_a.name,
                    reversal_evidence_b.name,
                ],
            )

        self.addCleanup(cleanup_reversal_race_rows)
        frappe.db.commit()

        def create_reversal(evidence_and_event):
            evidence_name, event_id = evidence_and_event
            return outward.reverse(
                outward_name=original.name,
                movement_at="2026-10-01 15:00:00",
                source_evidence=evidence_name,
                source_event_id=event_id,
                reason="concurrent distinct reversal source",
            )

        outcomes, run_one = self._run_two_connection_workers(
            create_reversal, user=self.maker
        )
        workers = [
            threading.Thread(target=run_one, args=(evidence_and_event,))
            for evidence_and_event in evidence_and_events
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        self.assertFalse(
            any(worker.is_alive() for worker in workers), "reversal worker hung"
        )

        results = [outcomes.get_nowait(), outcomes.get_nowait()]
        self.assertEqual([row[1] for row in results].count("OK"), 1, results)
        self.assertEqual([row[1] for row in results].count("DENIED"), 1, results)
        denied = next(row for row in results if row[1] == "DENIED")
        self.assertIn("reversal", denied[2].lower())

        frappe.db.rollback()
        reversal_names = frappe.get_all(
            "Fresko Outward",
            filters={"reverses_outward": original.name},
            fields=["name", "status", "source_event_id"],
        )
        self.assertEqual(len(reversal_names), 1, reversal_names)
        self.assertEqual(reversal_names[0].status, "Draft")
        self.assertIn(
            reversal_names[0].source_event_id,
            {event_id for _evidence, event_id in evidence_and_events},
        )
        original.reload()
        self.assertEqual(original.status, "Posted")
        self.assertEqual(physical_snapshot(container.name)["posted_physical_total"], 40)

    def test_posted_physical_truth_blocks_lowering_lot_inward_qty(self):
        container = make_container(
            self.masters,
            container_no=f"P2A-INWARD-REDUCTION-{frappe.generate_hash(length=6)}",
            lot_no="INWARD-REDUCTION-LOT",
            inward_qty=100,
        )
        evidence = self._evidence(container, "inward reduction guard")
        doc = self._create(
            container,
            evidence,
            "inward-reduction-guard",
            60,
            lot_no="INWARD-REDUCTION-LOT",
        )
        self._post(doc)

        container.reload()
        container.inward_qty = 50
        container.lots[0].inward_qty = 50
        container.flags.inward_qty_change_reason = "test physical truth guard"
        with self.assertRaises(frappe.ValidationError):
            container.save(ignore_permissions=True)
        container.reload()
        self.assertEqual(container.inward_qty, 100)
        self.assertEqual(container.lots[0].inward_qty, 100)

    def test_outward_does_not_change_legacy_deal_dispatched_qty(self):
        container = make_container(
            self.masters,
            container_no=f"P2A-DEAL-BOUNDARY-{frappe.generate_hash(length=6)}",
            lot_no="DEAL-BOUNDARY-LOT",
            inward_qty=50,
        )
        deal = make_deal(
            container,
            lot_no="DEAL-BOUNDARY-LOT",
            qty=10,
            proposed_rate=700,
        )
        deal.reload()
        original_dispatched_qty = deal.dispatched_qty
        evidence = self._evidence(container, "deal boundary")
        frappe.set_user(self.maker)
        created = outward.create(
            container=container.name,
            movement_at="2026-10-01 10:00:00",
            source_evidence=evidence.name,
            source_event_id="deal-boundary-outward",
            deal=deal.name,
            lines=[self._line(20, lot_no="DEAL-BOUNDARY-LOT")],
        )
        doc = frappe.get_doc("Fresko Outward", created["name"])
        self._post(doc)

        deal.reload()
        self.assertEqual(doc.deal, deal.name)
        self.assertEqual(
            len(self._open_exception(doc.name, "OUTWARD_WITHOUT_DEAL")), 0
        )
        self.assertEqual(deal.dispatched_qty, original_dispatched_qty)
        self.assertEqual(physical_snapshot(container.name)["posted_physical_total"], 20)

    def test_concurrent_post_candidates_serialize_physical_overdraw(self):
        """Two 60-unit posts against inward 100 yield one commit and one denial."""
        container = make_container(
            self.masters,
            container_no=f"P2A-POST-RACE-{frappe.generate_hash(length=6)}",
            lot_no="POST-RACE-LOT",
            inward_qty=100,
        )
        evidence_a = self._evidence(container, "post race A")
        evidence_b = self._evidence(container, "post race B")
        first = self._create(
            container, evidence_a, "post-race-a", 60, lot_no="POST-RACE-LOT"
        )
        second = self._create(
            container, evidence_b, "post-race-b", 60, lot_no="POST-RACE-LOT"
        )
        self._submit(first)
        self._submit(second)
        outward_names = [first.name, second.name]
        self.addCleanup(
            lambda: self._cleanup_committed_rows(
                container_name=container.name,
                outward_names=outward_names,
                evidence_names=[evidence_a.name, evidence_b.name],
            )
        )
        frappe.db.commit()

        outcomes, run_one = self._run_two_connection_workers(
            lambda outward_name: outward.post(outward_name)
        )
        workers = [
            threading.Thread(target=run_one, args=(outward_name,))
            for outward_name in outward_names
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        self.assertFalse(any(worker.is_alive() for worker in workers), "post worker hung")

        results = [outcomes.get_nowait(), outcomes.get_nowait()]
        self.assertEqual([row[1] for row in results].count("OK"), 1, results)
        self.assertEqual([row[1] for row in results].count("DENIED"), 1, results)
        denied = next(row for row in results if row[1] == "DENIED")
        self.assertIn("physical", denied[2].lower())

        # End the main connection's old snapshot before reading worker commits.
        frappe.db.rollback()
        statuses = frappe.get_all(
            "Fresko Outward",
            filters={"name": ("in", outward_names)},
            pluck="status",
        )
        self.assertEqual(sorted(statuses), ["Posted", "Review Pending"])
        self.assertEqual(
            physical_snapshot(container.name)["posted_physical_total"], 60
        )

    def test_concurrent_rate_supersessions_leave_one_active_successor(self):
        """Two corrections of one Active predecessor cannot both activate."""
        container = make_container(
            self.masters,
            container_no=f"P2A-RATE-RACE-{frappe.generate_hash(length=6)}",
            lot_no="RATE-RACE-LOT",
            inward_qty=100,
        )
        movement_evidence = self._evidence(container, "rate race movement")
        predecessor_evidence = self._evidence(container, "rate race predecessor")
        successor_evidence_a = self._evidence(container, "rate race successor A")
        successor_evidence_b = self._evidence(container, "rate race successor B")
        doc = self._create(
            container,
            movement_evidence,
            "rate-race-outward",
            10,
            lot_no="RATE-RACE-LOT",
        )
        self._post(doc)
        line_key = doc.lines[0].line_key

        frappe.set_user(self.maker)
        predecessor = outward.create_rate_assertion(
            outward_name=doc.name,
            outward_line_key=line_key,
            assertion_basis="USER_CONFIRMED",
            raw_value="100",
            rate=100,
            currency=self.masters["currency"],
            rate_uom=self.masters["uom"],
            evidence=predecessor_evidence.name,
            effective_at="2026-10-01 11:00:00",
            reason="initial active rate",
        )
        outward.submit_assertion(predecessor["name"])
        frappe.set_user(self.checker)
        outward.review_assertion(predecessor["name"], "ACTIVATE")

        frappe.set_user(self.maker)
        successor_a = outward.create_rate_assertion(
            outward_name=doc.name,
            outward_line_key=line_key,
            assertion_basis="USER_CONFIRMED",
            raw_value="101",
            rate=101,
            currency=self.masters["currency"],
            rate_uom=self.masters["uom"],
            evidence=successor_evidence_a.name,
            effective_at="2026-10-01 12:00:00",
            reason="correction A",
            supersedes=predecessor["name"],
        )
        outward.submit_assertion(successor_a["name"])
        successor_b = outward.create_rate_assertion(
            outward_name=doc.name,
            outward_line_key=line_key,
            assertion_basis="USER_CONFIRMED",
            raw_value="102",
            rate=102,
            currency=self.masters["currency"],
            rate_uom=self.masters["uom"],
            evidence=successor_evidence_b.name,
            effective_at="2026-10-01 12:01:00",
            reason="correction B",
            supersedes=predecessor["name"],
        )
        outward.submit_assertion(successor_b["name"])
        outward_names = [doc.name]
        assertion_names = [
            predecessor["name"],
            successor_a["name"],
            successor_b["name"],
        ]
        evidence_names = [
            movement_evidence.name,
            predecessor_evidence.name,
            successor_evidence_a.name,
            successor_evidence_b.name,
        ]
        self.addCleanup(
            lambda: self._cleanup_committed_rows(
                container_name=container.name,
                outward_names=outward_names,
                assertion_names=assertion_names,
                evidence_names=evidence_names,
            )
        )
        frappe.db.commit()

        successor_names = [successor_a["name"], successor_b["name"]]
        outcomes, run_one = self._run_two_connection_workers(
            lambda assertion_name: outward.review_assertion(assertion_name, "ACTIVATE")
        )
        workers = [
            threading.Thread(target=run_one, args=(assertion_name,))
            for assertion_name in successor_names
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        self.assertFalse(any(worker.is_alive() for worker in workers), "rate worker hung")

        results = [outcomes.get_nowait(), outcomes.get_nowait()]
        self.assertEqual([row[1] for row in results].count("OK"), 1, results)
        self.assertEqual([row[1] for row in results].count("DENIED"), 1, results)

        frappe.db.rollback()
        predecessor_doc = frappe.get_doc("Fresko Field Assertion", predecessor["name"])
        self.assertEqual(predecessor_doc.status, "Superseded")
        active = frappe.get_all(
            "Fresko Field Assertion",
            filters={
                "outward": doc.name,
                "outward_line_key": line_key,
                "asserted_field": "rate",
                "status": "Active",
            },
            pluck="name",
        )
        self.assertEqual(len(active), 1, active)
        self.assertIn(active[0], successor_names)

    def test_concurrent_initial_rate_assertions_leave_one_active(self):
        """Two initial rates for one scope cannot both activate."""
        container = make_container(
            self.masters,
            container_no=f"P2A-INITIAL-RATE-RACE-{frappe.generate_hash(length=6)}",
            lot_no="INITIAL-RATE-RACE-LOT",
            inward_qty=100,
        )
        movement_evidence = self._evidence(container, "initial rate race movement")
        rate_evidence_a = self._evidence(container, "initial rate race A")
        rate_evidence_b = self._evidence(container, "initial rate race B")
        doc = self._create(
            container,
            movement_evidence,
            "initial-rate-race-outward",
            10,
            lot_no="INITIAL-RATE-RACE-LOT",
        )
        self._post(doc)
        line_key = doc.lines[0].line_key

        frappe.set_user(self.maker)
        first = outward.create_rate_assertion(
            outward_name=doc.name,
            outward_line_key=line_key,
            assertion_basis="SOURCE_EXTRACTED",
            raw_value="201",
            rate=201,
            currency=self.masters["currency"],
            rate_uom=self.masters["uom"],
            evidence=rate_evidence_a.name,
            effective_at="2026-10-01 14:00:00",
            reason="initial source rate A",
        )
        outward.submit_assertion(first["name"])
        second = outward.create_rate_assertion(
            outward_name=doc.name,
            outward_line_key=line_key,
            assertion_basis="SOURCE_EXTRACTED",
            raw_value="202",
            rate=202,
            currency=self.masters["currency"],
            rate_uom=self.masters["uom"],
            evidence=rate_evidence_b.name,
            effective_at="2026-10-01 14:01:00",
            reason="initial source rate B",
        )
        outward.submit_assertion(second["name"])

        outward_names = [doc.name]
        assertion_names = [first["name"], second["name"]]
        evidence_names = [
            movement_evidence.name,
            rate_evidence_a.name,
            rate_evidence_b.name,
        ]
        self.addCleanup(
            lambda: self._cleanup_committed_rows(
                container_name=container.name,
                outward_names=outward_names,
                assertion_names=assertion_names,
                evidence_names=evidence_names,
            )
        )
        frappe.db.commit()

        assertion_names = [first["name"], second["name"]]
        outcomes, run_one = self._run_two_connection_workers(
            lambda assertion_name: outward.review_assertion(assertion_name, "ACTIVATE")
        )
        workers = [
            threading.Thread(target=run_one, args=(assertion_name,))
            for assertion_name in assertion_names
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        self.assertFalse(any(worker.is_alive() for worker in workers), "initial rate worker hung")

        results = [outcomes.get_nowait(), outcomes.get_nowait()]
        self.assertEqual([row[1] for row in results].count("OK"), 1, results)
        self.assertEqual([row[1] for row in results].count("DENIED"), 1, results)

        frappe.db.rollback()
        active = frappe.get_all(
            "Fresko Field Assertion",
            filters={
                "outward": doc.name,
                "outward_line_key": line_key,
                "asserted_field": "rate",
                "status": "Active",
            },
            pluck="name",
        )
        self.assertEqual(len(active), 1, active)
        self.assertIn(active[0], assertion_names)

    def test_concurrent_line_rates_resolve_multi_line_unpriced_exception(self):
        """Every line scope must be priced before OUTWARD_UNPRICED resolves."""
        container = make_container(
            self.masters,
            container_no=f"P2A-MULTI-LINE-RATE-RACE-{frappe.generate_hash(length=6)}",
            lot_no="MULTI-LINE-RATE-LOT",
            inward_qty=100,
        )
        movement_evidence = self._evidence(container, "multi-line rate movement")
        rate_evidence_a = self._evidence(container, "multi-line rate A")
        rate_evidence_b = self._evidence(container, "multi-line rate B")
        frappe.set_user(self.maker)
        created = outward.create(
            container=container.name,
            movement_at="2026-10-01 16:00:00",
            source_evidence=movement_evidence.name,
            source_event_id="multi-line-rate-race-outward",
            lines=[
                self._line(
                    10,
                    lot_no="MULTI-LINE-RATE-LOT",
                    source_line_ref="1",
                ),
                self._line(
                    20,
                    lot_no="MULTI-LINE-RATE-LOT",
                    source_line_ref="2",
                ),
            ],
        )
        doc = frappe.get_doc("Fresko Outward", created["name"])
        self._post(doc)
        line_keys = [line.line_key for line in doc.lines]

        frappe.set_user(self.maker)
        first = outward.create_rate_assertion(
            outward_name=doc.name,
            outward_line_key=line_keys[0],
            assertion_basis="SOURCE_EXTRACTED",
            raw_value="301",
            rate=301,
            currency=self.masters["currency"],
            rate_uom=self.masters["uom"],
            evidence=rate_evidence_a.name,
            effective_at="2026-10-01 16:01:00",
            reason="line 1 source rate",
        )
        outward.submit_assertion(first["name"])
        second = outward.create_rate_assertion(
            outward_name=doc.name,
            outward_line_key=line_keys[1],
            assertion_basis="SOURCE_EXTRACTED",
            raw_value="302",
            rate=302,
            currency=self.masters["currency"],
            rate_uom=self.masters["uom"],
            evidence=rate_evidence_b.name,
            effective_at="2026-10-01 16:02:00",
            reason="line 2 source rate",
        )
        outward.submit_assertion(second["name"])
        assertion_names = [first["name"], second["name"]]
        self.addCleanup(
            lambda: self._cleanup_committed_rows(
                container_name=container.name,
                outward_names=[doc.name],
                assertion_names=assertion_names,
                evidence_names=[
                    movement_evidence.name,
                    rate_evidence_a.name,
                    rate_evidence_b.name,
                ],
            )
        )
        frappe.db.commit()

        outcomes, run_one = self._run_two_connection_workers(
            lambda assertion_name: outward.review_assertion(assertion_name, "ACTIVATE")
        )
        workers = [
            threading.Thread(target=run_one, args=(assertion_name,))
            for assertion_name in assertion_names
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        self.assertFalse(
            any(worker.is_alive() for worker in workers), "multi-line rate worker hung"
        )

        results = [outcomes.get_nowait(), outcomes.get_nowait()]
        self.assertEqual([row[1] for row in results].count("OK"), 2, results)
        frappe.db.rollback()
        statuses = frappe.get_all(
            "Fresko Field Assertion",
            filters={"name": ("in", assertion_names)},
            pluck="status",
        )
        self.assertEqual(statuses, ["Active", "Active"])
        self.assertEqual(len(self._open_unpriced(doc.name)), 0)
