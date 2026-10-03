"""Bench integration gates for the immutable Container Quantity Assertion ledger.

Run with: bench --site <site> run-tests --app fresko_universe --module
fresko_universe.tests.test_container_quantity_assertion
"""
from __future__ import annotations

import frappe
import threading
from queue import Queue
from frappe.tests.utils import FrappeTestCase

from fresko_universe import outward, quantity_assertion
from fresko_universe.deals import apply_rate_rules
from fresko_universe.fresko_core.ats import available_to_sell
from fresko_universe.tests.test_phase2a_outward import _ensure_user
from fresko_universe.tests.utils import ensure_masters, make_container, make_deal


class TestContainerQuantityAssertion(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.masters = ensure_masters()
        cls.maker = _ensure_user("quantity_assertion_maker@example.com", ["Fresko Salesperson", "Fresko Approver"])
        cls.checker = _ensure_user("quantity_assertion_checker@example.com", ["Fresko Approver"])

    def setUp(self):
        frappe.set_user("Administrator")

    def _evidence(self, container, label):
        return frappe.get_doc({"doctype": "Fresko Evidence", "evidence_type": "Note", "container": container.name, "notes": f"quantity assertion: {label}"}).insert(ignore_permissions=True)

    def _create(self, container, evidence, source_id, *, basis="DECLARED_SHIPPING", quantity="3060", uom=None, supersedes=None):
        frappe.set_user(self.maker)
        return quantity_assertion.create(
            container=container.name, basis=basis, raw_value=str(quantity) if quantity is not None else "unknown from source",
            quantity=quantity, uom=uom if uom is not None else self.masters["uom"], raw_uom=self.masters["uom"],
            evidence=evidence.name, effective_at="2026-10-03 10:00:00", provenance="SOURCE_EXTRACTED",
            reason="integration assertion", source_fact_id=source_id, supersedes=supersedes,
        )

    def _submit(self, name):
        frappe.set_user(self.maker)
        return quantity_assertion.submit(name)

    def _activate(self, name):
        frappe.set_user(self.checker)
        return quantity_assertion.review(name, "ACTIVATE")

    def _two_connection_workers(self, worker):
        site, barrier, outcomes = frappe.local.site, threading.Barrier(2), Queue()
        def run(name):
            frappe.init(site=site)
            frappe.connect()
            try:
                frappe.set_user(self.checker)
                barrier.wait(timeout=20)
                worker(name)
                frappe.db.commit()
                outcomes.put((name, "OK"))
            except Exception:
                frappe.db.rollback()
                outcomes.put((name, "DENIED"))
            finally:
                frappe.destroy()
        return outcomes, run

    def test_lifecycle_replay_unknown_and_uom_gate(self):
        container = make_container(self.masters, container_no=f"QTY-{frappe.generate_hash(length=6)}", inward_qty=3056)
        evidence = self._evidence(container, "lifecycle")
        created = self._create(container, evidence, "shipping-1")
        self.assertEqual(frappe.db.get_value("Fresko Container Quantity Assertion", created["name"], "status"), "Draft")
        self.assertTrue(self._submit(created["name"]))
        frappe.set_user(self.maker)
        with self.assertRaises(frappe.PermissionError):
            quantity_assertion.review(created["name"], "ACTIVATE")
        self._activate(created["name"])
        self.assertEqual(frappe.db.get_value("Fresko Container Quantity Assertion", created["name"], "status"), "Active")
        frappe.set_user(self.maker)
        self.assertTrue(self._create(container, evidence, "shipping-1")["replayed"])
        with self.assertRaises(frappe.UniqueValidationError):
            self._create(container, evidence, "shipping-1", quantity="3061")
        unknown = self._create(container, evidence, "customs-unknown", basis="CUSTOMS_DECLARED", quantity=None, uom=None)
        self.assertIsNone(frappe.db.get_value("Fresko Container Quantity Assertion", unknown["name"], "quantity"))
        with self.assertRaises(frappe.ValidationError):
            self._create(container, evidence, "customs-no-uom", basis="CUSTOMS_DECLARED", quantity="1", uom="")

    def test_projection_supersession_and_cross_uom(self):
        container = make_container(self.masters, container_no=f"QTY-{frappe.generate_hash(length=6)}", inward_qty=3056)
        original_inward = frappe.db.get_value("Fresko Container", container.name, "inward_qty")
        evidence = self._evidence(container, "projection")
        declared = self._create(container, evidence, "shipping-3060", quantity="3060")
        operating = self._create(container, evidence, "operating-3056", basis="OPERATING_INWARD", quantity="3056")
        self._submit(declared["name"]); self._activate(declared["name"])
        self._submit(operating["name"]); self._activate(operating["name"])
        frappe.set_user("Administrator")
        projection = quantity_assertion.reconciliation_projection(container.name)
        self.assertEqual(projection["variance"], "4")
        self.assertEqual(projection["reconciliation_status"], "OPEN_VARIANCE")
        self.assertEqual(frappe.db.get_value("Fresko Container", container.name, "inward_qty"), original_inward)
        successor = self._create(container, evidence, "shipping-3060-corrected", quantity="3060", supersedes=declared["name"])
        self._submit(successor["name"]); self._activate(successor["name"])
        self.assertEqual(frappe.db.get_value("Fresko Container Quantity Assertion", declared["name"], "status"), "Superseded")
        self.assertEqual(frappe.db.count("Fresko Container Quantity Assertion", {"container": container.name, "basis": "DECLARED_SHIPPING", "uom": self.masters["uom"], "status": "Active"}), 1)
        other_uom = frappe.get_doc({"doctype": "UOM", "uom_name": f"QTY-UOM-{frappe.generate_hash(length=6)}", "must_be_whole_number": 0}).insert(ignore_permissions=True)
        cross_container = make_container(self.masters, container_no=f"QTY-{frappe.generate_hash(length=6)}", inward_qty=1)
        cross_evidence = self._evidence(cross_container, "cross-uom")
        cross_declared = self._create(cross_container, cross_evidence, "shipping-cross", quantity="2")
        cross_operating = self._create(cross_container, cross_evidence, "operating-cross", basis="OPERATING_INWARD", quantity="2", uom=other_uom.name)
        self._submit(cross_declared["name"]); self._activate(cross_declared["name"])
        self._submit(cross_operating["name"]); self._activate(cross_operating["name"])
        frappe.set_user("Administrator")
        self.assertEqual(quantity_assertion.reconciliation_projection(cross_container.name)["reconciliation_status"], "UNRESOLVED")

    def test_legacy_fallback_is_explicitly_unverified(self):
        container = make_container(
            self.masters,
            container_no=f"QTY-{frappe.generate_hash(length=6)}",
            inward_qty=3056,
        )
        evidence = self._evidence(container, "legacy compatibility")
        declared = self._create(container, evidence, "shipping-legacy", quantity="3060")
        self._submit(declared["name"])
        self._activate(declared["name"])
        frappe.set_user("Administrator")
        projection = quantity_assertion.reconciliation_projection(container.name)
        self.assertEqual(projection["operating_basis"], "LEGACY_UNVERIFIED")
        self.assertIsNone(projection["operating_assertion"])

    def test_active_operating_inward_caps_container_wide_ats(self):
        container = make_container(
            self.masters,
            container_no=f"QTY-{frappe.generate_hash(length=6)}",
            inward_qty=3060,
        )
        evidence = self._evidence(container, "operating ATS cap")
        operating = self._create(
            container,
            evidence,
            "operating-ats-3056",
            basis="OPERATING_INWARD",
            quantity="3056",
        )
        self._submit(operating["name"])
        self._activate(operating["name"])
        frappe.set_user("Administrator")
        self.assertEqual(available_to_sell(container.name, "LOT-A"), 3056)

        excessive = make_deal(container, qty=3057, proposed_rate=120)
        excessive_result = apply_rate_rules(excessive.name)
        excessive.reload()
        self.assertEqual(excessive_result["status"], "Approval Required")
        self.assertEqual(excessive.status, "Approval Required")
        self.assertEqual(
            frappe.db.count(
                "Fresko Exception",
                {"deal": excessive.name, "exception_type": "STOCK_SHORTFALL"},
            ),
            1,
        )

        allowed = make_deal(container, qty=3056, proposed_rate=120)
        result = apply_rate_rules(allowed.name)
        self.assertEqual(result["status"], "Auto Approved")

    def test_system_manager_cannot_review_own_quantity_assertion(self):
        container = make_container(
            self.masters,
            container_no=f"QTY-{frappe.generate_hash(length=6)}",
            inward_qty=1,
        )
        evidence = self._evidence(container, "system manager separation")
        frappe.set_user("Administrator")
        created = quantity_assertion.create(
            container=container.name,
            basis="DECLARED_SHIPPING",
            raw_value="1",
            quantity="1",
            uom=self.masters["uom"],
            raw_uom=self.masters["uom"],
            evidence=evidence.name,
            effective_at="2026-10-03 10:00:00",
            provenance="SOURCE_EXTRACTED",
            reason="system manager maker/checker regression",
            source_fact_id="system-manager-self-review",
        )
        quantity_assertion.submit(created["name"])
        with self.assertRaises(frappe.PermissionError):
            quantity_assertion.review(created["name"], "ACTIVATE")
        self.assertEqual(
            frappe.db.get_value(
                "Fresko Container Quantity Assertion", created["name"], "status"
            ),
            "Review Pending",
        )

    def test_quantity_activation_and_outward_post_share_container_first_lock(self):
        container = make_container(
            self.masters,
            container_no=f"QTY-LOCK-{frappe.generate_hash(length=6)}",
            inward_qty=20,
        )
        evidence = self._evidence(container, "cross-service lock")
        assertion = self._create(container, evidence, "cross-service-quantity", quantity="20")
        self._submit(assertion["name"])
        frappe.set_user(self.maker)
        outward_result = outward.create(
            container=container.name,
            movement_at="2026-10-03 10:00:00",
            source_evidence=evidence.name,
            source_event_id="cross-service-outward",
            lines=[{
                "source_line_ref": "1",
                "raw_lot_text": "LOT-A",
                "lot_no": "LOT-A",
                "qty": 10,
                "uom": self.masters["uom"],
                "raw_qty_text": "10",
                "raw_uom_text": self.masters["uom"],
                "raw_rate_text": None,
            }],
        )
        outward.submit_for_review(outward_result["name"])
        frappe.db.commit()

        site = frappe.local.site
        barrier = threading.Barrier(2)
        outcomes = Queue()

        def run(action):
            frappe.init(site=site)
            frappe.connect()
            try:
                frappe.set_user(self.checker)
                barrier.wait(timeout=20)
                if action == "assertion":
                    quantity_assertion.review(assertion["name"], "ACTIVATE")
                else:
                    outward.post(outward_result["name"])
                frappe.db.commit()
                outcomes.put((action, "OK"))
            except Exception as exc:
                frappe.db.rollback()
                outcomes.put((action, f"ERROR:{exc}"))
            finally:
                frappe.destroy()

        threads = [threading.Thread(target=run, args=(action,)) for action in ("assertion", "outward")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=40)
        results = dict(outcomes.get(timeout=5) for _ in threads)
        self.assertEqual(results, {"assertion": "OK", "outward": "OK"})

        frappe.set_user("Administrator")
        frappe.db.rollback()
        frappe.db.delete("Fresko Exception", {"outward": outward_result["name"]})
        frappe.db.delete("Fresko Outward Line", {"parent": outward_result["name"]})
        frappe.db.delete("Fresko Outward", {"name": outward_result["name"]})
        frappe.db.delete("Fresko Container Quantity Assertion", {"name": assertion["name"]})
        frappe.db.delete("Fresko Evidence", {"name": evidence.name})
        frappe.db.delete("Fresko Container Lot", {"parent": container.name})
        frappe.db.delete("Fresko Container", {"name": container.name})
        frappe.db.commit()

    def test_two_connection_competing_activation_leaves_one_active(self):
        container = make_container(self.masters, container_no=f"QTY-{frappe.generate_hash(length=6)}", inward_qty=1)
        evidence = self._evidence(container, "concurrent activation")
        first = self._create(container, evidence, "race-1", quantity="1")
        second = self._create(container, evidence, "race-2", quantity="2")
        self._submit(first["name"]); self._submit(second["name"])
        # Worker connections need committed candidates; cleanup below removes these explicit rows.
        frappe.db.commit()
        outcomes, worker = self._two_connection_workers(lambda name: quantity_assertion.review(name, "ACTIVATE"))
        threads = [threading.Thread(target=worker, args=(name,)) for name in (first["name"], second["name"])]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=30)
        result = [outcomes.get(timeout=5)[1] for _ in threads]
        frappe.set_user("Administrator")
        self.assertEqual(result.count("OK"), 1)
        self.assertEqual(frappe.db.count("Fresko Container Quantity Assertion", {"container": container.name, "basis": "DECLARED_SHIPPING", "uom": self.masters["uom"], "status": "Active"}), 1)
        frappe.db.delete("Fresko Container Quantity Assertion", {"container": container.name})
        frappe.db.delete("Fresko Evidence", evidence.name)
        frappe.db.delete("Fresko Container Lot", {"parent": container.name})
        frappe.db.delete("Fresko Container", {"name": container.name})
        frappe.db.commit()


class TestPhysicalVarianceException(FrappeTestCase):
    """Bench integration gates for persistent PHYSICAL_VARIANCE exceptions."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.masters = ensure_masters()
        cls.maker = _ensure_user("phyvar_maker@example.com", ["Fresko Salesperson", "Fresko Approver"])
        cls.checker = _ensure_user("phyvar_checker@example.com", ["Fresko Approver"])
        cls.maker_only = _ensure_user("phyvar_maker_only@example.com", ["Fresko Salesperson"])

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")

    def _evidence(self, container, label):
        return frappe.get_doc({"doctype": "Fresko Evidence", "evidence_type": "Note", "container": container.name, "notes": f"phyvar: {label}"}).insert(ignore_permissions=True)

    def _create(self, container, evidence, source_id, *, basis="DECLARED_SHIPPING", quantity="3060", uom=None, supersedes=None):
        frappe.set_user(self.maker)
        return quantity_assertion.create(
            container=container.name, basis=basis, raw_value=str(quantity) if quantity is not None else "unknown",
            quantity=quantity, uom=uom if uom is not None else self.masters["uom"], raw_uom=self.masters["uom"],
            evidence=evidence.name, effective_at="2026-10-03 10:00:00", provenance="SOURCE_EXTRACTED",
            reason="phyvar integration assertion", source_fact_id=source_id, supersedes=supersedes,
        )

    def _submit(self, name):
        frappe.set_user(self.maker)
        return quantity_assertion.submit(name)

    def _activate(self, name):
        frappe.set_user(self.checker)
        return quantity_assertion.review(name, "ACTIVATE")

    def _activate_pair(self, container, evidence, declared_qty="3060", operating_qty="3056", declared_id="d-1", operating_id="o-1"):
        declared = self._create(container, evidence, declared_id, quantity=declared_qty)
        operating = self._create(container, evidence, operating_id, basis="OPERATING_INWARD", quantity=operating_qty)
        self._submit(declared["name"]); self._activate(declared["name"])
        self._submit(operating["name"]); self._activate(operating["name"])
        return declared, operating

    def _cleanup(self, container, evidence):
        frappe.set_user("Administrator")
        frappe.db.delete("Fresko Exception", {"container": container.name})
        frappe.db.delete("Fresko Container Quantity Assertion", {"container": container.name})
        frappe.db.delete("Fresko Evidence", {"name": evidence.name})
        frappe.db.delete("Fresko Container Lot", {"parent": container.name})
        frappe.db.delete("Fresko Container", {"name": container.name})
        frappe.db.commit()

    def test_3060_vs_3056_creates_open_physical_variance(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=3056)
        original_inward = frappe.db.get_value("Fresko Container", container.name, "inward_qty")
        evidence = self._evidence(container, "3060v3056")
        try:
            declared, operating = self._activate_pair(container, evidence)
            frappe.set_user("Administrator")
            exceptions = frappe.get_all(
                "Fresko Exception",
                filters={"container": container.name, "exception_type": "PHYSICAL_VARIANCE", "status": "Open"},
                fields=["name", "declared_quantity_assertion", "operating_quantity_assertion", "variance_quantity", "variance_uom", "variance_key"],
            )
            self.assertEqual(len(exceptions), 1)
            exc = exceptions[0]
            self.assertEqual(exc.variance_quantity, "4")
            self.assertEqual(exc.declared_quantity_assertion, declared["name"])
            self.assertEqual(exc.operating_quantity_assertion, operating["name"])
            self.assertEqual(exc.variance_uom, self.masters["uom"])
            self.assertTrue(exc.variance_key)
            # Container.inward_qty unchanged
            self.assertEqual(frappe.db.get_value("Fresko Container", container.name, "inward_qty"), original_inward)
            # Projection key matches
            projection = quantity_assertion.reconciliation_projection(container.name)
            self.assertEqual(projection["physical_variance_exception"], exc.name)
        finally:
            self._cleanup(container, evidence)

    def test_reverse_activation_order_also_creates_one(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=3060)
        evidence = self._evidence(container, "reverse-order")
        try:
            operating = self._create(container, evidence, "rev-o-1", basis="OPERATING_INWARD", quantity="3056")
            declared = self._create(container, evidence, "rev-d-1", quantity="3060")
            self._submit(operating["name"]); self._activate(operating["name"])
            self._submit(declared["name"]); self._activate(declared["name"])
            frappe.set_user("Administrator")
            count = frappe.db.count("Fresko Exception", {"container": container.name, "exception_type": "PHYSICAL_VARIANCE", "status": "Open"})
            self.assertEqual(count, 1)
        finally:
            self._cleanup(container, evidence)

    def test_ensure_physical_variance_idempotent(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=3056)
        evidence = self._evidence(container, "idempotent")
        try:
            self._activate_pair(container, evidence, declared_qty="3060", operating_qty="3056", declared_id="idem-d", operating_id="idem-o")
            frappe.set_user(self.checker)
            result1 = quantity_assertion.ensure_physical_variance(container.name)
            result2 = quantity_assertion.ensure_physical_variance(container.name)
            self.assertIsNotNone(result1["physical_variance_exception"])
            self.assertEqual(result1["physical_variance_exception"], result2["physical_variance_exception"])
        finally:
            self._cleanup(container, evidence)

    def test_equal_quantities_no_exception(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=3060)
        evidence = self._evidence(container, "equal")
        try:
            self._activate_pair(container, evidence, declared_qty="3060", operating_qty="3060", declared_id="eq-d", operating_id="eq-o")
            frappe.set_user("Administrator")
            count = frappe.db.count("Fresko Exception", {"container": container.name, "exception_type": "PHYSICAL_VARIANCE"})
            self.assertEqual(count, 0)
        finally:
            self._cleanup(container, evidence)

    def test_declared_only_no_exception(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=100)
        evidence = self._evidence(container, "declared-only")
        try:
            declared = self._create(container, evidence, "donly-d", quantity="100")
            self._submit(declared["name"]); self._activate(declared["name"])
            frappe.set_user("Administrator")
            count = frappe.db.count("Fresko Exception", {"container": container.name, "exception_type": "PHYSICAL_VARIANCE"})
            self.assertEqual(count, 0)
        finally:
            self._cleanup(container, evidence)

    def test_legacy_fallback_no_exception(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=3056)
        evidence = self._evidence(container, "legacy-fallback")
        try:
            declared = self._create(container, evidence, "leg-d", quantity="3060")
            self._submit(declared["name"]); self._activate(declared["name"])
            frappe.set_user("Administrator")
            count = frappe.db.count("Fresko Exception", {"container": container.name, "exception_type": "PHYSICAL_VARIANCE"})
            self.assertEqual(count, 0)
            projection = quantity_assertion.reconciliation_projection(container.name)
            self.assertIsNone(projection["physical_variance_exception"])
        finally:
            self._cleanup(container, evidence)

    def test_cross_uom_no_exception(self):
        # Only if a second UOM is easily available
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=100)
        evidence = self._evidence(container, "cross-uom")
        other_uom = frappe.get_doc({"doctype": "UOM", "uom_name": f"PV-UOM-{frappe.generate_hash(length=6)}", "must_be_whole_number": 0}).insert(ignore_permissions=True)
        try:
            declared = self._create(container, evidence, "cross-d", quantity="100")
            operating = self._create(container, evidence, "cross-o", basis="OPERATING_INWARD", quantity="90", uom=other_uom.name)
            self._submit(declared["name"]); self._activate(declared["name"])
            self._submit(operating["name"]); self._activate(operating["name"])
            frappe.set_user("Administrator")
            count = frappe.db.count("Fresko Exception", {"container": container.name, "exception_type": "PHYSICAL_VARIANCE"})
            self.assertEqual(count, 0, "cross-UOM pair must not create a PHYSICAL_VARIANCE exception")
        finally:
            frappe.set_user("Administrator")
            frappe.db.delete("Fresko Exception", {"container": container.name})
            frappe.db.delete("Fresko Container Quantity Assertion", {"container": container.name})
            frappe.db.delete("Fresko Evidence", {"name": evidence.name})
            frappe.db.delete("Fresko Container Lot", {"parent": container.name})
            frappe.db.delete("Fresko Container", {"name": container.name})
            frappe.db.delete("UOM", {"name": other_uom.name})
            frappe.db.commit()

    def test_declared_supersession_new_exception_old_stays(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=3056)
        evidence = self._evidence(container, "supersession")
        try:
            declared, operating = self._activate_pair(container, evidence, declared_qty="3060", operating_qty="3056", declared_id="sup-d1", operating_id="sup-o1")
            frappe.set_user("Administrator")
            old_exc = frappe.get_all(
                "Fresko Exception",
                filters={"container": container.name, "exception_type": "PHYSICAL_VARIANCE", "status": "Open"},
                pluck="name",
            )
            self.assertEqual(len(old_exc), 1)
            old_exc_name = old_exc[0]
            # Supersede declared with a new value
            new_declared = self._create(container, evidence, "sup-d2", quantity="3058", supersedes=declared["name"])
            self._submit(new_declared["name"]); self._activate(new_declared["name"])
            frappe.set_user("Administrator")
            all_exc = frappe.get_all(
                "Fresko Exception",
                filters={"container": container.name, "exception_type": "PHYSICAL_VARIANCE"},
                fields=["name", "status", "variance_quantity"],
                order_by="creation asc",
            )
            # Old exception stays Open unchanged; new exception created for new pair
            self.assertEqual(len(all_exc), 2)
            old = next(e for e in all_exc if e.name == old_exc_name)
            new = next(e for e in all_exc if e.name != old_exc_name)
            self.assertEqual(old.status, "Open")
            self.assertEqual(old.variance_quantity, "4")
            self.assertEqual(new.status, "Open")
            self.assertEqual(new.variance_quantity, "2")
        finally:
            self._cleanup(container, evidence)

    def test_close_gate_blocked_while_open(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=3056)
        evidence = self._evidence(container, "close-gate")
        try:
            self._activate_pair(container, evidence, declared_qty="3060", operating_qty="3056", declared_id="gate-d", operating_id="gate-o")
            frappe.set_user("Administrator")
            doc = frappe.get_doc("Fresko Container", container.name)
            doc.status = "Closing"
            doc.save()
            doc.reload()
            doc.status = "Closed"
            doc.closing_status = "Fully Reconciled"
            # Match the gate message so an unrelated ValidationError cannot pass vacuously.
            with self.assertRaisesRegex(frappe.ValidationError, "open material Exceptions"):
                doc.save()
        finally:
            self._cleanup(container, evidence)

    def test_waive_with_notes(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=3056)
        evidence = self._evidence(container, "waive")
        try:
            self._activate_pair(container, evidence, declared_qty="3060", operating_qty="3056", declared_id="waive-d", operating_id="waive-o")
            frappe.set_user("Administrator")
            exc_name = frappe.get_all(
                "Fresko Exception",
                filters={"container": container.name, "exception_type": "PHYSICAL_VARIANCE", "status": "Open"},
                pluck="name",
            )[0]
            frappe.set_user(self.checker)
            result = quantity_assertion.resolve_physical_variance(exc_name, "WAIVE", "Accepted by operations team")
            self.assertEqual(result["status"], "Waived")
            self.assertFalse(result["replayed"])
            # Replay same decision
            replay = quantity_assertion.resolve_physical_variance(exc_name, "WAIVE", "duplicate call")
            self.assertEqual(replay["status"], "Waived")
            self.assertTrue(replay["replayed"])
            # Different terminal decision throws
            with self.assertRaises(frappe.ValidationError):
                quantity_assertion.resolve_physical_variance(exc_name, "RESOLVE", "try resolve")
        finally:
            self._cleanup(container, evidence)

    def test_blank_notes_throws(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=3056)
        evidence = self._evidence(container, "blank-notes")
        try:
            self._activate_pair(container, evidence, declared_qty="3060", operating_qty="3056", declared_id="bn-d", operating_id="bn-o")
            frappe.set_user("Administrator")
            exc_name = frappe.get_all(
                "Fresko Exception",
                filters={"container": container.name, "exception_type": "PHYSICAL_VARIANCE", "status": "Open"},
                pluck="name",
            )[0]
            frappe.set_user(self.checker)
            with self.assertRaises(frappe.ValidationError):
                quantity_assertion.resolve_physical_variance(exc_name, "WAIVE", "")
        finally:
            self._cleanup(container, evidence)

    def test_direct_insert_without_flag_throws(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=100)
        evidence = self._evidence(container, "no-flag")
        try:
            self._activate_pair(container, evidence, declared_qty="3060", operating_qty="3056", declared_id="nf-d", operating_id="nf-o")
            frappe.set_user("Administrator")
            exc_name = frappe.get_all(
                "Fresko Exception",
                filters={"container": container.name, "exception_type": "PHYSICAL_VARIANCE", "status": "Open"},
                pluck="name",
            )[0]
            exc = frappe.get_doc("Fresko Exception", exc_name)
            # Direct insert of a new quantity-scoped PHYSICAL_VARIANCE without flag
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc({
                    "doctype": "Fresko Exception",
                    "exception_type": "PHYSICAL_VARIANCE",
                    "severity": "Material",
                    "status": "Open",
                    "container": container.name,
                    "declared_quantity_assertion": exc.declared_quantity_assertion,
                    "operating_quantity_assertion": exc.operating_quantity_assertion,
                    "variance_quantity": "4",
                    "variance_uom": self.masters["uom"],
                    "variance_key": "fake-key-test",
                    "description": "should fail",
                }).insert()
        finally:
            self._cleanup(container, evidence)

    def test_other_exception_cannot_squat_variance_key(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=3056)
        evidence = self._evidence(container, "squat")
        try:
            declared = self._create(container, evidence, "sq-d", quantity="3060")
            operating = self._create(container, evidence, "sq-o", basis="OPERATING_INWARD", quantity="3056")
            from fresko_universe.fresko_core.services.quantity_assertion_service import _variance_key
            frappe.set_user("Administrator")
            # A non-variance Desk row must not pre-claim the pair's deterministic key.
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc({
                    "doctype": "Fresko Exception",
                    "exception_type": "OTHER",
                    "severity": "Low",
                    "status": "Open",
                    "container": container.name,
                    "variance_key": _variance_key(container.name, declared["name"], operating["name"]),
                    "description": "squat attempt",
                }).insert(ignore_permissions=True)
            self._submit(declared["name"]); self._activate(declared["name"])
            self._submit(operating["name"]); self._activate(operating["name"])
            frappe.set_user("Administrator")
            self.assertEqual(
                frappe.db.count("Fresko Exception", {"container": container.name, "exception_type": "PHYSICAL_VARIANCE", "status": "Open"}),
                1,
            )
        finally:
            self._cleanup(container, evidence)

    def test_editing_variance_quantity_blocked(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=3056)
        evidence = self._evidence(container, "immutable-vq")
        try:
            self._activate_pair(container, evidence, declared_qty="3060", operating_qty="3056", declared_id="imm-d", operating_id="imm-o")
            frappe.set_user("Administrator")
            exc_name = frappe.get_all(
                "Fresko Exception",
                filters={"container": container.name, "exception_type": "PHYSICAL_VARIANCE", "status": "Open"},
                pluck="name",
            )[0]
            exc = frappe.get_doc("Fresko Exception", exc_name)
            exc.variance_quantity = "999"
            exc.flags.in_quantity_service = True
            with self.assertRaises(frappe.PermissionError):
                exc.save(ignore_permissions=True)
            with self.assertRaises(frappe.PermissionError):
                frappe.delete_doc("Fresko Exception", exc_name, ignore_permissions=True)
            self.assertTrue(frappe.db.exists("Fresko Exception", exc_name))
        finally:
            self._cleanup(container, evidence)

    def test_maker_without_checker_cannot_ensure(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=100)
        evidence = self._evidence(container, "maker-only")
        try:
            frappe.set_user(self.maker_only)
            with self.assertRaises(frappe.PermissionError):
                quantity_assertion.ensure_physical_variance(container.name)
        finally:
            self._cleanup(container, evidence)

    def test_maker_without_checker_cannot_resolve(self):
        container = make_container(self.masters, container_no=f"PV-{frappe.generate_hash(length=6)}", inward_qty=3056)
        evidence = self._evidence(container, "maker-resolve")
        try:
            self._activate_pair(container, evidence, declared_qty="3060", operating_qty="3056", declared_id="mr-d", operating_id="mr-o")
            frappe.set_user("Administrator")
            exc_name = frappe.get_all(
                "Fresko Exception",
                filters={"container": container.name, "exception_type": "PHYSICAL_VARIANCE", "status": "Open"},
                pluck="name",
            )[0]
            frappe.set_user(self.maker_only)
            with self.assertRaises(frappe.PermissionError):
                quantity_assertion.resolve_physical_variance(exc_name, "WAIVE", "should fail")
        finally:
            self._cleanup(container, evidence)
