"""Real Frappe UI acceptance. Requires explicitly seeded, isolated synthetic site."""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from decimal import Decimal
from urllib.parse import parse_qs
import traceback
import time
import unittest

from playwright.sync_api import sync_playwright, expect
from playwright.async_api import async_playwright
from browser_support import BrowserSession


class BrowserAcceptance(unittest.TestCase):
    def setUp(self):
        self.current_stage = "setup"
        self._browser_sessions = []

    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(Path(os.environ["FRESKO_BROWSER_MANIFEST"]).read_text())
        if cls.fixture.get("synthetic_only") is not True:
            raise ValueError("Only explicit synthetic fixtures are accepted")
        cls.base = os.environ["FRESKO_BROWSER_URL"].rstrip("/")
        fixture_origin = (cls.fixture.get("browser_origin") or "").rstrip("/")
        if not fixture_origin or cls.base != fixture_origin:
            raise ValueError("Browser URL must exactly match the synthetic fixture browser_origin")
        output = Path(os.environ["FRESKO_BROWSER_ARTIFACTS"])
        if output.is_symlink() or output.exists():
            raise ValueError("Browser artifact output must be a new, nonsymlink directory")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir(mode=0o700)
        cls.output = output
        cls.progress_path = Path(os.environ["FRESKO_BROWSER_MANIFEST"]).parent / "browser-progress.json"
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()
        # Frappe's first Page render and subsequent projection refreshes are
        # asynchronous. Bound positive UI readiness consistently without
        # waiting for network idle or suppressing application errors.
        expect.set_options(timeout=30000)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def session(self, role, width=1280, expect_desk=None):
        if expect_desk is None:
            expect_desk = role not in ("supplier", "mixed")
        user = self.fixture["users"][role]
        session = BrowserSession(
            self.browser,
            self.base,
            user["email"],
            user["password"],
            {"width": width, "height": 900},
            expect_desk=expect_desk,
        )
        self._browser_sessions.append(session)
        self.addCleanup(session.close)
        return session

    def record_progress(self, width, **values):
        try:
            progress = json.loads(self.progress_path.read_text())
        except FileNotFoundError:
            progress = {}
        key = str(width)
        progress.setdefault(key, {}).update(values)
        fd = os.open(self.progress_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(progress, stream, sort_keys=True)

    def response_action(self, session, method, action, success=True, timeout=30000):
        self.current_stage = method
        with session.page.expect_response(lambda r: method in r.url and r.request.method == "POST", timeout=timeout) as wait:
            action()
        response = wait.value
        payload = response.json()
        self.assertEqual(response.ok, success, f"Unexpected HTTP outcome for {method}: {payload.get('_server_messages')}")
        if success:
            self.assertFalse(payload.get("exc"), f"Server exception for {method}")
            self.assertIsNotNone(payload.get("message"), f"Missing result for {method}")
        else:
            self.assertEqual(response.status, 417)
            self.assertEqual(payload.get("exc_type"), "ValidationError")
        session.page.wait_for_function("!frappe.request.ajax_count")
        session.dismiss_messages()
        return payload.get("message")

    def click_page_action(self, session, label):
        """Click a native Page action, using Frappe's mobile Menu when collapsed."""
        button = session.page.get_by_role("button", name=label, exact=True)
        for index in range(button.count()):
            candidate = button.nth(index)
            if candidate.is_visible():
                candidate.click()
                return
        primary = session.page.locator(".page-head button.primary-action:visible")
        if primary.count() and primary.first.get_attribute("data-label") == label:
            primary.first.click()
            return
        menu_button = session.page.locator(".page-head button[aria-label='Menu']:visible").first
        menu_button.wait_for(state="visible", timeout=30000)
        menu_button.click()
        dropdown = session.page.locator(".page-head .dropdown-menu:visible").last
        dropdown.wait_for(state="visible", timeout=10000)
        links = dropdown.locator("a:visible, button:visible, [role='menuitem']:visible")
        for index in range(links.count()):
            candidate = links.nth(index)
            if candidate.inner_text().strip() == label:
                candidate.click()
                return
        raise AssertionError(f"Native Page Menu did not expose action {label!r}")

    @staticmethod
    def request_args(raw):
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                return payload.get("args", payload)
        except (TypeError, json.JSONDecodeError):
            pass
        fields = {key: values[-1] for key, values in parse_qs(raw, keep_blank_values=True).items()}
        if "data" in fields:
            try:
                nested = json.loads(fields["data"])
                if isinstance(nested, dict):
                    fields.update(nested)
            except json.JSONDecodeError:
                pass
        return {key: value for key, value in fields.items() if key not in ("cmd", "data")}

    def assert_version_error(self, session, method, args, code):
        result = session.page.evaluate(
            """async ([url, args]) => {
                const response = await fetch(url, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Frappe-CSRF-Token': frappe.csrf_token
                    },
                    body: JSON.stringify(args)
                });
                return {status: response.status, body: await response.json()};
            }""",
            [self.base + "/api/method/" + method, args],
        )
        body = result["body"]
        self.assertEqual(result["status"], 417,
                         f"{method} should reject this version token: {body.get('exc_type')} {body.get('_server_messages')}")
        self.assertEqual(body.get("exc_type"), "ValidationError")
        self.assertIn(code, str(body.get("_server_messages", "")))
        return body

    def assert_blank_version_wire(self, session, method, sale):
        observed = {}
        endpoint = "/api/method/" + method

        def capture(request):
            if request.method == "POST" and endpoint in request.url:
                observed["body"] = request.post_data or ""

        session.page.on("request", capture)
        result = session.page.evaluate(
            """([method, sale]) => new Promise(resolve => {
                frappe.call({
                    method,
                    args: {sale_name: sale, expected_version: null},
                    callback: response => resolve({
                        ok: !response || !response.exc,
                        exc_type: response && response.exc_type,
                        server_messages: response && response._server_messages
                    }),
                    error: error => resolve({
                        ok: false,
                        // Frappe passes the parsed response JSON directly to this callback.
                        exc_type: error && error.exc_type,
                        server_messages: error && error._server_messages
                    })
                });
            })""",
            [method, sale],
        )
        session.page.remove_listener("request", capture)
        self.assertFalse(result["ok"], "Blank expected_version must be rejected by the real endpoint")
        self.assertIn("EXPECTED_VERSION_REQUIRED", str(result["server_messages"]))
        wire = observed.get("body", "")
        if wire.lstrip().startswith("{"):
            payload = json.loads(wire)
            self.assertIn("expected_version", payload)
            self.assertIn(payload["expected_version"], (None, ""))
        else:
            fields = parse_qs(wire, keep_blank_values=True)
            self.assertIn("expected_version", fields)
            self.assertEqual(fields["expected_version"], [""])

    def sale_truth(self, session, sale):
        doc = session.rpc("frappe.client.get", {"doctype": "Fresko Commercial Sale", "name": sale})
        self.assertTrue(doc.get("ok"), "Could not read synthetic Sale truth")
        source = doc["message"]
        return {key: source.get(key) for key in ("status", "version", "decision_history", "source_payload", "payload_sha256")}

    def workspace(self, session, scenario):
        self.current_stage = "workspace:container-live"
        session.goto("app/fresko-workspace")
        expect(session.page.locator(".fresko-workspace-container")).to_be_visible(timeout=30000)
        # Blank means the live projection, which supplies the current version token.
        session.clear_datetime_field("as_of")
        session.field("container", scenario["container"], require_autocomplete=True)
        session.page.wait_for_function(
            """expected => {
                const ws = frappe.container.page.fresko_workspace;
                return ws && ws.as_of_value === '' && ws.container_field.get_value() === expected &&
                    ws.container_data && ws.container_data.container === expected &&
                    ws.container_data.projection_mode === 'LIVE';
            }""",
            arg=scenario["container"],
            timeout=30000,
        )
        expect(session.page.locator(".fresko-workspace-container")).to_contain_text(scenario["container"])

    def inspect(self, session, sale):
        self.current_stage = "workspace:inspect-sale"
        session.dismiss_messages()
        session.page.locator('[data-tab-id="sales"]').click()
        session.page.locator("tr").filter(has=session.page.get_by_text(sale, exact=True)).get_by_role("button", name="Inspect", exact=True).click()
        expect(session.page.locator(".fresko-card-title").filter(has_text="Selected Sale:")).to_contain_text(sale)

    def sale_step(self, session, scenario, sale, label, method):
        self.workspace(session, scenario)
        self.inspect(session, sale)
        self.response_action(session, method, lambda: session.page.get_by_role("button", name=label, exact=True).click())
        self.record_progress(scenario["width"], sale=sale, stage=method.replace(".", "_"))

    def money_page(self, session):
        self.current_stage = "money:load"
        session.goto("app/fresko-money")
        expect(session.page.locator("#tbl-collections")).to_be_visible(timeout=30000)
        session.datetime_field("cutoff", "2099-01-01 00:00:00")
        expect(session.page.locator("#fm-projections")).to_contain_text("Total Eligible", timeout=30000)

    def money_step(self, session, name, target, label, method):
        self.money_page(session)
        row = session.page.locator(target + " tr").filter(has_text=name)
        self.response_action(session, method, lambda: row.get_by_role("button", name=label, exact=True).click())

    def scenario(self, width):
        scenario = next(s for s in self.fixture["scenarios"] if s["width"] == width)
        sales, maker, verifier, approver = [self.session(role, width) for role in ["sales", "maker", "verifier", "approver"]]
        progress = json.loads(self.progress_path.read_text()) if self.progress_path.exists() else {}
        saved = progress.get(str(width), {})
        if saved.get("sale"):
            sale = saved["sale"]
            self.workspace(sales, scenario)
        else:
            self.workspace(sales, scenario)
            self.click_page_action(sales, "New Sale")
            dialog = sales.dialog("Prepare Commercial Sale")
            sales.field("raw_party_alias", scenario["raw_alias"], True)
            sales.field("party_state", "KNOWN", True)
            sales.field("source_evidence", scenario["evidence"], True)
            dialog.get_by_role("button", name="+ Add Lot Line", exact=True).click()
            for index in range(2):
                row = dialog.locator(".fresko-line-row").nth(index)
                row.locator(".line-lot").select_option(scenario["lots"][index])
                row.locator(".line-raw-lot").fill("BROWSER-A" if index == 0 else "BROWSER-B")
                row.locator(".line-qty").fill("40" if index == 0 else "10")
                row.locator(".line-evidence").fill(scenario["evidence"])
            sale = self.response_action(sales, "commercial.create_sale", lambda: sales.click_dialog("Create Sale"))["name"]
            try:
                dialog.wait_for(state="hidden", timeout=15000)
            except Exception:
                pass
            sales.dismiss_messages()
            self.record_progress(width, sale=sale, stage="sale_created")
        self.inspect(sales, sale)
        self.assertEqual(sales.page.locator(".fresko-card-title").filter(has_text="Selected Sale:").count(), 1)
        source = sales.rpc("frappe.client.get", {"doctype": "Fresko Commercial Sale", "name": sale})["message"]
        self.assertEqual(source["raw_party_alias"], scenario["raw_alias"])
        self.assertEqual(len(source["lines"]), 2)
        original_version = source["version"]
        sale_status = source["status"]
        if sale_status == "DRAFT":
            original_truth = self.sale_truth(sales, sale)
            self.assert_version_error(sales, "fresko_universe.commercial.submit_sale",
                                      {"sale_name": sale}, "EXPECTED_VERSION_REQUIRED")
            self.assertEqual(self.sale_truth(sales, sale), original_truth)
            self.assert_blank_version_wire(sales, "fresko_universe.commercial.submit_sale", sale)
            self.assertEqual(self.sale_truth(sales, sale), original_truth)
            self.assert_version_error(sales, "fresko_universe.commercial.submit_sale",
                                      {"sale_name": sale, "expected_version": "01"}, "INVALID_EXPECTED_VERSION")
            self.assertEqual(self.sale_truth(sales, sale), original_truth)
            self.assert_version_error(sales, "fresko_universe.commercial.submit_sale",
                                      {"sale_name": sale, "expected_version": str(int(original_version) + 17)}, "STALE_VERSION")
            self.assertEqual(self.sale_truth(sales, sale), original_truth)
            self.sale_step(sales, scenario, sale, "Submit Sale", "commercial.submit_sale")
            self.assert_version_error(sales, "fresko_universe.commercial.submit_sale",
                                      {"sale_name": sale, "expected_version": original_version}, "STALE_VERSION")
        elif sale_status in ("REVIEW_PENDING", "VERIFIED"):
            self.assert_version_error(sales, "fresko_universe.commercial.submit_sale",
                                      {"sale_name": sale, "expected_version": str(max(1, int(original_version) - 1))},
                                      "STALE_VERSION")
        if sale_status in ("DRAFT", "REVIEW_PENDING"):
            self.sale_step(verifier, scenario, sale, "Verify Sale", "commercial.verify_sale")
            sale_status = "VERIFIED"
        if sale_status == "VERIFIED":
            self.sale_step(approver, scenario, sale, "Approve Sale", "commercial.approve_sale")
        elif sale_status != "APPROVED":
            self.fail(f"Cannot resume browser workflow from Sale status {sale_status!r}")
        # Alias is proposed and reviewed through three real users and native dialogs.
        alias = saved.get("alias")
        alias_status = None
        if alias:
            alias_doc = sales.rpc("frappe.client.get", {"doctype": "Fresko Party Alias Mapping", "name": alias})
            self.assertTrue(alias_doc.get("ok"), "Could not read saved alias workflow progress")
            alias_status = alias_doc["message"].get("status")
        if not alias:
            self.workspace(sales, scenario)
            self.click_page_action(sales, "Propose Alias")
            sales.dialog("Propose Party Alias Mapping")
            for field, value in {"company": self.fixture["company"], "raw_alias": scenario["raw_alias"],
                                 "proposed_customer": self.fixture["customer"], "evidence": scenario["evidence"]}.items():
                sales.field(field, value, True)
            alias = self.response_action(sales, "commercial.propose_alias_mapping", lambda: sales.click_dialog("Propose Mapping"))["name"]
            sales.dismiss_messages()
            self.record_progress(width, alias=alias, stage="alias_proposed")
            alias_status = "PROPOSED"
        if alias_status == "PROPOSED":
            for user, label, method in [(verifier, "Verify", "verify_alias_mapping"), (approver, "Approve", "approve_alias_mapping")]:
                self.workspace(user, scenario)
                user.page.locator('[data-tab-id="alias"]').click()
                row = user.page.locator("#fresko-alias-queue-wrap tr").filter(has_text=alias)
                self.response_action(user, "commercial." + method, lambda: row.get_by_role("button", name=label, exact=True).click())
                self.record_progress(width, alias=alias, stage="alias_" + method)
        else:
            self.assertEqual(alias_status, "APPROVED", "Saved alias workflow is not approved")
        # Late rate proposal creates an auditable successor. Never rewrite approved source.
        current = sales.rpc("fresko_universe.commercial.get_sale_current", {"sale_name": sale})
        self.assertTrue(current.get("ok"), "Could not read current Sale before late-rate workflow")
        unpriced_count = sum(line["price_state"] != "FINAL" for line in current["message"]["lines"])
        if unpriced_count:
            self.assertIsNone(current["message"]["total_commercial_amount"])
            unpriced_truth = self.sale_truth(sales, sale)
            self.money_page(verifier)
            verifier.page.locator('[data-tab="receivables"]').click()
            verifier.page.locator("#rec-sale").fill(sale)
            position = self.response_action(verifier, "money.get_sale_receivable",
                lambda: verifier.page.locator("#btn-query-rec").click())
            self.assertTrue(position["exists"])
            self.assertGreater(position["pending_amount_line_count"], 0)
            self.assertIsNone(position["gross_commercial_amount"])
            self.assertIsNone(position["outstanding_receivable"])
            expect(verifier.page.locator("#fm-receivable-result")).to_contain_text("PENDING")
            self.assertEqual(self.sale_truth(sales, sale), unpriced_truth,
                             "Reading an unpriced Sale must preserve its commercial truth")
        for index in range(unpriced_count):
            self.workspace(sales, scenario)
            self.inspect(sales, sale)
            sales.page.get_by_role("button", name="Propose Rate", exact=True).first.click()
            for field, value in {"rate": "100", "evidence": scenario["evidence"], "reason": "Synthetic browser late price"}.items():
                sales.field(field, value, True)
            successor = self.response_action(sales, "commercial.propose_rate", lambda: sales.click_dialog("Propose Rate"))["name"]
            sales.dismiss_messages()
            sale = successor
            self.record_progress(width, sale=sale, stage=f"rate_successor_{index + 1}")
            self.sale_step(sales, scenario, sale, "Submit Sale", "commercial.submit_sale")
            self.sale_step(verifier, scenario, sale, "Verify Sale", "commercial.verify_sale")
            self.sale_step(approver, scenario, sale, "Approve Sale", "commercial.approve_sale")
        effective = sales.rpc("fresko_universe.commercial.get_sale_current", {"sale_name": sale})
        self.assertTrue(effective.get("ok"), "Could not read the current Sale projection")
        effective_sale = effective["message"]
        self.assertEqual(effective_sale.get("projection_mode"), "LIVE")
        self.assertEqual(len(effective_sale["lines"]), 2)
        self.assertEqual(len({line["line_key"] for line in effective_sale["lines"]}), 2)
        for line in effective_sale["lines"]:
            self.assertEqual(line["price_state"], "FINAL")
            self.assertEqual(line["rate"], "100")
            self.assertEqual(Decimal(line["amount"]), Decimal(line["qty"]) * Decimal("100"))
        self.assertEqual(Decimal(effective_sale["total_commercial_amount"]), Decimal("5000"))
        # Real Sale to Outward allocation, followed by an overdraw approval denial.
        allocations = list(saved.get("allocations", []))
        if allocations:
            self.assertEqual(len(allocations), 3, "Saved allocation progress is incomplete; refusing to replay proposals")
            states = []
            for name in allocations:
                doc = sales.rpc("frappe.client.get", {"doctype": "Fresko Sale Outward Allocation", "name": name})
                self.assertTrue(doc.get("ok"), "Saved Sale-Outward allocation is missing")
                states.append((doc["message"].get("state"), bool(doc["message"].get("verified_by"))))
            self.assertEqual(states, [("APPROVED", True), ("PROPOSED", True), ("PROPOSED", True)],
                             "Saved allocation stage is not the expected completed approval/overdraw result")
        else:
            for qty in ["20", "11", "21"]:
                self.workspace(sales, scenario)
                self.inspect(sales, sale)
                sales.page.get_by_role("button", name="+ Allocate to Outward", exact=True).click()
                sales.dialog("Propose Sale-Outward Allocation")
                sales.field("outward", scenario["outward"], True, require_autocomplete=True)
                expect(sales.dialog().locator('[data-fieldname="outward_line_key"] select')).to_have_value(scenario["outward_line_key"])
                sales.field("qty", qty, True)
                sales.field("evidence", scenario["evidence"], True)
                allocation = self.response_action(sales, "commercial.propose_sale_outward_allocation", lambda: sales.click_dialog("Propose Allocation"))["name"]
                sales.dismiss_messages()
                allocations.append(allocation)
                self.record_progress(width, sale=sale, allocations=allocations, stage=f"allocation_{qty}_proposed")
                for user, label, method, success in [(verifier, "Verify", "verify_sale_outward_allocation", True),
                                                    (approver, "Approve", "approve_sale_outward_allocation", qty == "20")]:
                    self.workspace(user, scenario)
                    self.inspect(user, sale)
                    row = user.page.locator(".fresko-alloc-queue-wrap tr").filter(has_text=allocation)
                    self.response_action(user, "commercial." + method, lambda: row.get_by_role("button", name=label, exact=True).click(), success)
        # Cash declaration, maker/checker segregation and payment allocation.
        self.money_page(maker)
        self.click_page_action(maker, "New Collection")
        maker.dialog("Receive / Capture Collection")
        for field, value in {"payment_channel": "CASH", "source_classification": "CASH_DECLARATION", "amount": "6000",
            "payer_raw": scenario["raw_alias"], "customer": self.fixture["customer"], "source_evidence": scenario["evidence"]}.items():
            maker.field(field, value, True, require_autocomplete=field in {"customer", "source_evidence"})
        create_request = {}
        def capture_collection_request(request):
            if request.method == "POST" and "money.create_collection" in request.url:
                create_request["args"] = self.request_args(request.post_data or "")
        maker.page.on("request", capture_collection_request)
        collection = self.response_action(
            maker, "money.create_collection",
            lambda: maker.dialog().get_by_role("button", name="Create Collection", exact=True).dblclick()
        )["name"]
        maker.page.remove_listener("request", capture_collection_request)
        original_args = create_request.get("args", {})
        self.assertEqual(original_args.get("source_namespace"), "manual_workspace")
        source_event_id = original_args.get("source_event_id")
        self.assertTrue(source_event_id, "Native collection create did not send its source event ID")
        csrf = maker.page.evaluate("() => frappe.csrf_token")
        replay_response = maker.context.request.post(
            self.base + "/api/method/fresko_universe.money.create_collection",
            data=original_args, headers={"X-Frappe-CSRF-Token": csrf})
        self.assertEqual(replay_response.status, 200, "Exact source-event replay should return the original collection")
        self.assertEqual(replay_response.json().get("message", {}).get("name"), collection,
                         "Exact replay must resolve to the one original Collection")
        saved_rows = maker.rpc("frappe.client.get_list", {
            "doctype": "Fresko Collection", "filters": {"source_event_id": source_event_id},
            "fields": ["name", "source_event_id", "source_event_key"], "limit_page_length": 10})
        self.assertTrue(saved_rows.get("ok"), "Could not read back source-event Collection records")
        self.assertEqual([row["name"] for row in saved_rows["message"]], [collection],
                         "Exact replay must leave exactly one persisted Collection for the source event")
        self.record_progress(width, collection=collection, stage="collection_created")
        self.money_step(maker, collection, "#tbl-collections", "Submit", "money.submit_collection")
        before_denial = maker.rpc("frappe.client.get", {"doctype": "Fresko Collection", "name": collection})
        self.assertTrue(before_denial.get("ok"))
        denied = maker.context.request.post(
            self.base + "/api/method/fresko_universe.money.verify_collection",
            data={"collection_name": collection, "expected_version": before_denial["message"]["version"]},
            headers={"X-Frappe-CSRF-Token": maker.page.evaluate("() => frappe.csrf_token")},
        )
        self.assertEqual(denied.status, 403, "Maker must not verify own collection")
        self.assertEqual(denied.json().get("exc_type"), "PermissionError")
        after_denial = maker.rpc("frappe.client.get", {"doctype": "Fresko Collection", "name": collection})
        self.assertTrue(after_denial.get("ok"))
        self.assertEqual(after_denial["message"], before_denial["message"],
                         "Denied maker self-verification must preserve Collection truth")
        maker.dismiss_messages()
        self.money_step(verifier, collection, "#tbl-collections", "Verify", "money.verify_collection")
        self.money_step(approver, collection, "#tbl-collections", "Approve", "money.approve_collection")
        self.money_page(maker)
        self.click_page_action(maker, "Propose Allocation")
        maker.dialog("Propose Payment Allocation")
        for field, value in {"collection": collection, "amount": "1000", "sale": sale,
            "container": scenario["container"], "evidence": scenario["evidence"]}.items():
            maker.field(field, value, True, require_autocomplete=field in {"collection", "sale", "container", "evidence"})
        payment = self.response_action(maker, "money.propose_payment_allocation", lambda: maker.click_dialog("Propose Allocation"))["name"]
        self.record_progress(width, payment=payment, stage="payment_proposed")
        for user, label, method in [(maker, "Submit", "submit_payment_allocation"),
            (verifier, "Verify", "verify_payment_allocation"), (approver, "Approve", "approve_payment_allocation")]:
            self.money_step(user, payment, "#tbl-allocations", label, "money." + method)
        self.money_page(verifier)
        verifier.page.locator('[data-tab="receivables"]').click()
        verifier.page.locator("#rec-sale").fill(sale)
        self.response_action(verifier, "money.get_sale_receivable", lambda: verifier.page.locator("#btn-query-rec").click())
        expect(verifier.page.locator("#fm-receivable-result")).to_contain_text("INR 4000")
        expect(verifier.page.locator("#fm-receivable-result")).to_contain_text(sale)
        verifier.page.screenshot(path=str(self.output / f"money-{width}.png"), full_page=True)
        self.workspace(sales, scenario)
        self.inspect(sales, sale)
        sales.page.screenshot(path=str(self.output / f"workspace-{width}.png"), full_page=True)
        physical = sales.rpc("frappe.client.get", {"doctype": "Fresko Outward", "name": scenario["outward"]})["message"]
        self.assertEqual(physical["lines"][0]["qty"], 30)
        self.assertEqual(physical["status"], "Posted")

    def test_desktop(self):
        self.scenario(1280)

    def test_mobile_390(self):
        self.scenario(390)

    def test_mobile_360(self):
        self.scenario(360)

    def test_native_links_preserve_collection_dialog(self):
        """Selecting Customer and tabbing into Datetime must keep its dialog open."""
        scenario = next(s for s in self.fixture["scenarios"] if s["width"] == 360)
        sales = self.session("sales", 360)
        self.workspace(sales, scenario)  # Exercise the Page-level Link getter too.
        maker = self.session("maker", 360)
        self.money_page(maker)
        self.click_page_action(maker, "New Collection")
        maker.dialog("Receive / Capture Collection")
        self.current_stage = "money:customer-link-keeps-dialog-open"
        maker.field("customer", self.fixture["customer"], True, require_autocomplete=True)
        expect(maker.dialog().locator(".modal-title")).to_have_text("Receive / Capture Collection")
        self.assertEqual(maker._get_frappe_field_value("customer", True), self.fixture["customer"])
        self.assertEqual(maker.page.locator("#datepickers-container .datepicker.active:visible").count(), 0)
        maker.field("source_evidence", scenario["evidence"], True)
        self.assertEqual(maker._get_frappe_field_value("source_evidence", True), scenario["evidence"])

    def test_supplier_and_mixed_denials(self):
        progress = json.loads(self.progress_path.read_text()) if self.progress_path.exists() else {}
        known_sale = progress.get("1280", {}).get("sale")
        for role in ["supplier", "mixed"]:
            with self.subTest(role=role):
                session = self.session(role, expect_desk=False)
                session.goto("app/fresko-workspace")
                denied_heading = session.page.get_by_role("heading", name="Access Denied", exact=True)
                native_denied = session.page.get_by_role("heading", name="Not Permitted", exact=True)
                login_form = session.page.locator("form.form-signin, input#login_email")
                expect(denied_heading.or_(native_denied).or_(login_form)).to_be_visible(timeout=30000)
                self.assertEqual(session.page.locator(".fresko-workspace-container button:visible").count(), 0,
                                 "Denied Workspace must expose no operational controls")
                session.goto("app/fresko-money")
                money_denial = session.page.locator(".fm-denied")
                native_denial = session.page.get_by_role("heading", name="Not Permitted", exact=True)
                expect(money_denial.or_(native_denial).or_(login_form)).to_be_visible(timeout=30000)
                if money_denial.count() and money_denial.is_visible():
                    expect(money_denial).to_contain_text("Access denied", timeout=30000)
                self.assertEqual(session.page.locator("#tbl-collections tr, #tbl-allocations tr").count(), 0,
                                 "Denied Money page must expose no finance rows")
                for method, args in [
                    ("fresko_universe.money.get_unallocated_collections", {"company": self.fixture["company"]}),
                    ("fresko_universe.fresko_core.services.operator_service.get_money_action_target", {"doctype": "Fresko Collection", "document_name": "SYNTHETIC-DENIED-TARGET", "action": "verify_collection"}),
                    ("fresko_universe.commercial.get_container_reconciliation", {"container": self.fixture["scenarios"][0]["container"]})]:
                    response = session.context.request.get(self.base + "/api/method/" + method, params=args)
                    self.assertEqual(response.status, 403)
                    self.assertEqual(response.json().get("exc_type"), "PermissionError")
                for child_doctype in ["Fresko Evidence Attachment", "Fresko Evidence Attempt"]:
                    response = session.context.request.get(f"{self.base}/api/resource/{child_doctype}")
                    self.assertEqual(response.status, 403)
                    self.assertEqual(response.json().get("exc_type"), "PermissionError")
                if known_sale:
                    sales = self.session("sales")
                    before = self.sale_truth(sales, known_sale)
                    current = sales.rpc("fresko_universe.commercial.get_sale_current", {"sale_name": known_sale})
                    self.assertTrue(current.get("ok"))
                    token = current["message"]["current_version"]
                    csrf = session.page.evaluate("() => (window.frappe && window.frappe.csrf_token) || ''")
                    response = session.context.request.post(
                        self.base + "/api/method/fresko_universe.commercial.verify_sale",
                        data={"sale_name": known_sale, "expected_version": token},
                        headers={"X-Frappe-CSRF-Token": csrf},
                    )
                    self.assertEqual(response.status, 403)
                    self.assertEqual(response.json().get("exc_type"), "PermissionError")
                    self.assertEqual(self.sale_truth(sales, known_sale), before,
                                     "Unauthorized verifier attempt must leave Sale truth unchanged")
                    sales.close()

    def test_saved_state_exact_money_targets(self):
        """FR-QA-016: cached native Page focuses the exact authorized record.

        Saved records are already approved: changed actions must be blocked and
        navigation must not add a decision or perform a financial mutation.
        """
        progress = json.loads(self.progress_path.read_text()) if self.progress_path.exists() else {}
        saved = progress.get("1280", {})
        self.assertTrue(saved.get("collection") and saved.get("payment"), "Required desktop truth must exist")
        money = self.session("verifier")
        try:
            self.money_page(money)
            target_network = []
            target_started = [None]
            def record_target_request(request):
                body = request.post_data or ""
                command = parse_qs(body).get("cmd", [""])[0]
                if "operator_service.get_money_action_target" in request.url or command.endswith("operator_service.get_money_action_target"):
                    target_network.append({"event": "request", "elapsed": time.monotonic() - target_started[0] if target_started[0] else None, "method": request.method, "url": request.url, "cmd": command})
            def record_target_response(response):
                request = response.request
                body = request.post_data or ""
                command = parse_qs(body).get("cmd", [""])[0]
                if "operator_service.get_money_action_target" in request.url or command.endswith("operator_service.get_money_action_target"):
                    target_network.append({"event": "response", "elapsed": time.monotonic() - target_started[0] if target_started[0] else None, "status": response.status, "url": response.url, "cmd": command})
            money.page.on("request", record_target_request)
            money.page.on("response", record_target_response)
            money.page.evaluate("""() => {
                const diagnostic = window.__freskoMoneyTargetDiagnostic = {
                    consume_calls: 0, page_show_calls: 0, router_change_calls: 0,
                    rpc_calls: [], company_updates: []
                };
                const companyField = fresko_money.company_field;
                const setCompany = companyField.set_value;
                companyField.set_value = function(value) {
                    const update = { before: this.get_value(), requested: value, state: 'started' };
                    diagnostic.company_updates.push(update);
                    const promise = setCompany.apply(this, arguments);
                    update.after = this.get_value();
                    return Promise.resolve(promise).then(function(result) {
                        update.state = 'resolved';
                        update.final = companyField.get_value();
                        return result;
                    }, function(error) {
                        update.state = 'rejected';
                        update.error = String(error && error.message || error).slice(0, 120);
                        throw error;
                    });
                };
                const frappeCall = frappe.call;
                frappe.call = function(options) {
                    if (options && options.method === 'fresko_universe.fresko_core.services.operator_service.get_money_action_target') {
                        const call = { state: 'started', method: options.method, target: options.args };
                        diagnostic.rpc_calls.push(call);
                        return frappeCall.apply(this, arguments).then(function(result) {
                            call.state = 'resolved';
                            call.exc = Boolean(result && result.exc);
                            call.result = result && result.message;
                            return result;
                        }, function(error) {
                            call.state = 'rejected';
                            call.error = String(error && error.message || error).slice(0, 120);
                            throw error;
                        });
                    }
                    return frappeCall.apply(this, arguments);
                };
                const consume = fresko_money.consume_action_target;
                fresko_money.consume_action_target = function() {
                    diagnostic.consume_calls += 1;
                    return consume.apply(this, arguments);
                };
                const page = frappe.pages['fresko-money'];
                const page_show = page && page.on_page_show;
                if (page_show) page.on_page_show = function() {
                    diagnostic.page_show_calls += 1;
                    return page_show.apply(this, arguments);
                };
                const trigger = frappe.router.trigger;
                if (trigger) frappe.router.trigger = function(name) {
                    if (name === 'change') diagnostic.router_change_calls += 1;
                    return trigger.apply(this, arguments);
                };
            }""")
            for doctype, name, action in (
                ("Fresko Collection", saved["collection"], "verify_collection"),
                ("Fresko Payment Allocation", saved["payment"], "approve_payment_allocation"),
            ):
                before = money.rpc("frappe.client.get", {"doctype": doctype, "name": name})
                self.assertTrue(before.get("ok"))
                money.page.evaluate("() => frappe.set_route('fresko-workspace')")
                expect(money.page.locator(".fresko-workspace-container")).to_be_visible(timeout=30000)
                money.page.wait_for_function(
                    "() => frappe.get_route()[0] === 'fresko-workspace'", timeout=30000
                )
                target = {"doctype": doctype, "document_name": name, "action": action}
                money.page.evaluate("target => sessionStorage.setItem('fresko_money_target', JSON.stringify(target))", target)
                target_started[0] = time.monotonic()
                try:
                    money.page.evaluate("() => { frappe.set_route('fresko-money'); }")
                    money.page.wait_for_function(
                        "target => window.__freskoMoneyTargetDiagnostic.rpc_calls.some(call => call.state === 'resolved' && call.target && call.target.doctype === target.doctype && call.target.document_name === target.document_name && call.target.action === target.action)",
                        arg=target,
                        timeout=60000,
                    )
                    result = money.page.evaluate(
                        "target => window.__freskoMoneyTargetDiagnostic.rpc_calls.find(call => call.state === 'resolved' && call.target && call.target.doctype === target.doctype && call.target.document_name === target.document_name && call.target.action === target.action).result",
                        target,
                    )
                    self.assertTrue(any(item.get("event") == "response" and item.get("status") == 200 for item in target_network),
                                    "Target RPC must complete successfully over HTTP")
                except Exception:
                    diagnostic = money.page.evaluate("""() => ({
                        ...window.__freskoMoneyTargetDiagnostic,
                        route: frappe.get_route(),
                        page_id: frappe.container && frappe.container.page && frappe.container.page.id,
                        target_present: Boolean(sessionStorage.getItem('fresko_money_target')),
                        target_pending: Boolean(fresko_money.target_pending),
                        rpc_calls: window.__freskoMoneyTargetDiagnostic.rpc_calls,
                        company: fresko_money.get_company(),
                        company_updates: window.__freskoMoneyTargetDiagnostic.company_updates
                    })""")
                    print("[MONEY_TARGET_DIAGNOSTIC] " + json.dumps({**diagnostic, "network": target_network}, sort_keys=True))
                    raise
                self.assertEqual(result["record"]["name"], name)
                self.assertFalse(result["allowed"], "Approved record cannot be reverified/reapproved")
                panel = money.page.locator("#fm-target-record")
                expect(panel).to_be_visible(timeout=30000)
                expect(panel).to_have_attribute("data-document-name", name)
                expect(panel).to_have_attribute("data-doctype", doctype)
                expect(panel).to_be_focused()
                self.assertEqual(panel.locator("button").count(), 0)
                self.assertIsNone(money.page.evaluate("() => sessionStorage.getItem('fresko_money_target')"))
                after = money.rpc("frappe.client.get", {"doctype": doctype, "name": name})
                for field in ("version", "status", "decision_history", "source_payload"):
                    self.assertEqual(after["message"].get(field), before["message"].get(field), field)
        finally:
            money.close()

    def test_saved_state_historical_receivables_and_exceptions(self):
        """Read existing approved synthetic truth without creating financial rows."""
        progress = json.loads(self.progress_path.read_text()) if self.progress_path.exists() else {}
        saved = progress.get("1280", {})
        required = ("sale", "collection", "payment")
        if not all(saved.get(key) for key in required):
            self.fail("Required saved approved desktop workflow IDs are missing; acceptance must not skip")
        scenario = next(s for s in self.fixture["scenarios"] if s["width"] == 1280)
        sale = saved["sale"]
        sales = self.session("sales")
        before = self.sale_truth(sales, sale)

        self.current_stage = "workspace:live-exceptions"
        self.workspace(sales, scenario)
        expect(sales.page.locator(".fresko-badge-exception")).to_contain_text("OUTWARD_WITHOUT_SALE", timeout=30000)
        sales.datetime_field("as_of", "2099-01-01 00:00:00")
        sales.page.wait_for_function(
            """() => { const ws = frappe.container.page.fresko_workspace;
                return ws && ws.as_of_value && ws.container_data && ws.container_data.projection_mode === 'HISTORICAL'; }""",
            timeout=30000,
        )
        sales.page.locator('[data-tab-id="sales"]').click()
        expect(sales.page.locator(".fresko-workspace-container")).to_contain_text(sale, timeout=30000)
        for label in ("Submit Sale", "Verify Sale", "Approve Sale", "Propose Rate", "+ Allocate to Outward"):
            self.assertEqual(sales.page.get_by_role("button", name=label, exact=True).count(), 0,
                             f"Historical view must not expose {label}")
        self.assertEqual(self.sale_truth(sales, sale), before, "Historical browsing must not alter Sale truth")

        money = self.session("verifier")
        self.money_page(money)
        money.page.locator('[data-tab="receivables"]').click()
        money.field("container", scenario["container"], require_autocomplete=True)
        position = self.response_action(money, "money.get_container_receivable",
            lambda: money.page.locator("#btn-query-rec").click())
        self.assertEqual(position["container"], scenario["container"])
        self.assertEqual(position["sales_count"], 1)
        self.assertEqual(position["unresolved_pricing_sales_count"], 0)
        self.assertEqual(position["outstanding_receivable_by_currency"], {"INR": "4000.00"})
        expect(money.page.locator("#fm-receivable-result")).to_contain_text(scenario["container"], timeout=30000)
        expect(money.page.locator("#fm-receivable-result")).to_contain_text("INR: 4000.00", timeout=30000)
        money.field("container", "")
        money.page.locator("#rec-customer").fill(self.fixture["customer"])
        position = self.response_action(money, "money.get_customer_receivable",
            lambda: money.page.locator("#btn-query-rec").click())
        self.assertEqual(position["customer"], self.fixture["customer"])
        self.assertEqual(position["outstanding_receivable_by_currency"], {"INR": "12000.00"})
        self.assertEqual(position["outstanding_receivable_unknown_count_by_currency"], {})
        expect(money.page.locator("#fm-receivable-result")).to_contain_text(self.fixture["customer"], timeout=30000)
        expect(money.page.locator("#fm-receivable-result")).to_contain_text("INR: 12000.00", timeout=30000)
        money.page.locator("#rec-sale").fill(sale)
        money.page.locator("#btn-query-rec").click()
        expect(money.page.locator("#fm-receivable-result")).to_contain_text("INR 4000", timeout=30000)
        expect(money.page.locator("#fm-receivable-result")).to_contain_text(sale, timeout=30000)

        for doctype, name, expected_status in (
            ("Fresko Commercial Sale", sale, "APPROVED"),
            ("Fresko Collection", saved["collection"], "APPROVED"),
            ("Fresko Payment Allocation", saved["payment"], "APPROVED"),
        ):
            doc = money.rpc("frappe.client.get", {"doctype": doctype, "name": name})
            self.assertTrue(doc.get("ok"), f"Could not read saved {doctype} truth")
            self.assertEqual(doc["message"].get("status"), expected_status)
            if doctype != "Fresko Commercial Sale":
                truth = doc["message"]
                self.assertEqual(truth.get("prepared_by"), self.fixture["users"]["maker"]["email"])
                self.assertEqual(truth.get("verified_by"), self.fixture["users"]["verifier"]["email"])
                self.assertEqual(truth.get("approved_by"), self.fixture["users"]["approver"]["email"])

        collection_before = money.rpc("frappe.client.get", {
            "doctype": "Fresko Collection", "name": saved["collection"]})["message"]
        original_payload = json.loads(collection_before["source_payload"])
        replay_fields = ("company", "source_namespace", "source_event_id", "direction", "amount", "currency",
            "amount_state", "payment_channel", "bank_state", "source_classification", "bank_account",
            "bank_reference", "rail", "cash_custodian", "effective_at", "payer_raw", "customer",
            "source_evidence", "supersedes", "reason")
        replay_args = {key: original_payload.get(key) for key in replay_fields if key in original_payload}
        maker = self.session("maker")
        replay = maker.context.request.post(
            self.base + "/api/method/fresko_universe.money.create_collection", data=replay_args,
            headers={"X-Frappe-CSRF-Token": maker.page.evaluate("() => frappe.csrf_token")})
        self.assertEqual(replay.status, 200, "Exact source-event replay must succeed")
        self.assertEqual(replay.json().get("message", {}).get("name"), saved["collection"],
                         "Exact source-event replay must return the original persisted Collection")
        event_rows = maker.rpc("frappe.client.get_list", {
            "doctype": "Fresko Collection", "filters": {"source_event_id": original_payload["source_event_id"]},
            "fields": ["name", "source_event_id", "source_event_key"], "limit_page_length": 10})
        self.assertTrue(event_rows.get("ok"), "Could not read back persisted source-event identities")
        self.assertEqual([row["name"] for row in event_rows["message"]], [saved["collection"]],
                         "Exact source-event replay must leave exactly one persisted Collection")
        self.assert_version_error(money, "fresko_universe.money.verify_collection", {
            "collection_name": saved["collection"],
            "expected_version": str(max(1, int(collection_before["version"]) - 1)),
        }, "STALE_VERSION")
        collection_after = money.rpc("frappe.client.get", {
            "doctype": "Fresko Collection", "name": saved["collection"]})["message"]
        self.assertEqual(collection_after, collection_before,
                         "Stale replay against approved Collection must leave posted truth unchanged")
        payment_before = money.rpc("frappe.client.get", {
            "doctype": "Fresko Payment Allocation", "name": saved["payment"]})["message"]
        approver = self.session("approver")
        self.assert_version_error(approver, "fresko_universe.money.approve_payment_allocation", {
            "allocation_name": saved["payment"],
            "expected_version": str(max(1, int(payment_before["version"]) - 1)),
        }, "STALE_VERSION")
        payment_after = money.rpc("frappe.client.get", {
            "doctype": "Fresko Payment Allocation", "name": saved["payment"]})["message"]
        self.assertEqual(payment_after, payment_before,
                         "Stale replay against approved Payment must leave posted truth unchanged")

    def test_saved_state_delayed_real_responses(self):
        """Use established financial truth so old/new Money renders differ."""
        async def exercise():
            scenarios = {s["width"]: s for s in self.fixture["scenarios"]}
            first = scenarios[1280]
            held = asyncio.Event()
            release = asyncio.Event()
            fulfilled = asyncio.Event()
            fetched = {}
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch()
                context = await browser.new_context(viewport={"width": 1280, "height": 900})
                page = await context.new_page()
                user = self.fixture["users"]["sales"]
                await page.goto(self.base + "/login")
                form = page.locator("form.form-signin:visible, form:has(input#login_email):visible").first
                await form.locator("input#login_email").fill(user["email"])
                await form.locator("input#login_password").fill(user["password"])
                await form.locator("button[type=submit]").click()
                await page.wait_for_url(lambda url: "/login" not in url)
                login = await context.request.get(self.base + "/api/method/frappe.auth.get_logged_user")
                login_body = await login.json()
                assert login.ok and login_body.get("message") == user["email"], "Synthetic Sales login failed"
                await page.goto(self.base + "/app/fresko-workspace")
                root = page.locator(".fresko-workspace-container")
                await root.wait_for(state="visible", timeout=30000)

                async def set_link(value):
                    holder = page.locator("body div[data-fieldname='container']:visible").first
                    control = holder.locator("input:not([type=hidden])").first
                    if await control.input_value() != value:
                        await control.fill(value)
                        options = holder.locator(".awesomplete ul:visible [role='option']:visible")
                        await options.filter(has_text=value).first.wait_for(state="visible", timeout=10000)
                        match = None
                        for i in range(await options.count()):
                            option = options.nth(i)
                            text = (await option.inner_text()).strip().splitlines()[0].strip()
                            if text == value or text.startswith(value + " "):
                                match = option
                                break
                        assert match is not None, "Native Container Link did not offer the requested fixture"
                        await match.click()
                        await control.press("Tab")
                    await page.wait_for_function(
                        "expected => frappe.container.page.fresko_workspace.container_field.get_value() === expected",
                        arg=value, timeout=10000)

                async def wait_data(container, cutoff, mode):
                    try:
                        await page.wait_for_function(
                            """([container, cutoff, mode]) => { const ws = frappe.container.page.fresko_workspace;
                                return ws && ws.as_of_value === cutoff && ws.container_data &&
                                    ws.container_data.container === container && ws.container_data.projection_mode === mode &&
                                    (mode !== 'HISTORICAL' || ws.container_data.as_of === cutoff); }""",
                            arg=[container, cutoff, mode], timeout=30000)
                    except Exception:
                        state = await page.evaluate("""() => { const ws = frappe.container.page.fresko_workspace;
                            return {route: frappe.get_route_str(), container_value: ws && ws.container_field.get_value(),
                                container_name: ws && ws.container_name, as_of_value: ws && ws.as_of_value,
                                data_container: ws && ws.container_data && ws.container_data.container,
                                data_as_of: ws && ws.container_data && ws.container_data.as_of,
                                projection_mode: ws && ws.container_data && ws.container_data.projection_mode}; }""")
                        (Path(os.environ["FRESKO_BROWSER_MANIFEST"]).parent / "delayed-debug.json").write_text(json.dumps(state))
                        raise

                async def delayed_route(route):
                    request = route.request
                    raw = request.post_data or ""
                    if ("commercial.get_container_reconciliation" in request.url and
                            first["container"] in raw and not held.is_set()):
                        response = await route.fetch()
                        body = await response.json()
                        result = body.get("message") or {}
                        assert response.ok and result.get("container") == first["container"] and result.get("projection_mode") == "LIVE", \
                            "Delayed route must hold a successful actual LIVE server response for Container A"
                        fetched.update(status=response.status, container=result.get("container"), mode=result.get("projection_mode"))
                        held.set()
                        await release.wait()
                        await route.fulfill(response=response)
                        fulfilled.set()
                    else:
                        await route.continue_()

                await page.route("**/api/method/fresko_universe.commercial.get_container_reconciliation", delayed_route)
                await set_link(first["container"])
                await asyncio.wait_for(held.wait(), timeout=30)
                native_cutoff = await page.evaluate("iso => frappe.datetime.str_to_user(iso)", "2099-01-01 00:00:00")
                date_control = page.locator("body div[data-fieldname='as_of']:visible input:not([type=hidden])").first
                await date_control.fill(native_cutoff)
                await date_control.press("Tab")
                await page.wait_for_function(
                    "() => frappe.container.page.fresko_workspace.as_of_field.get_value() === '2099-01-01 00:00:00'",
                    timeout=10000)
                await wait_data(first["container"], "2099-01-01 00:00:00", "HISTORICAL")
                release.set()
                await asyncio.wait_for(fulfilled.wait(), timeout=10)
                await page.wait_for_function("!frappe.request.ajax_count", timeout=30000)
                await wait_data(first["container"], "2099-01-01 00:00:00", "HISTORICAL")
                assert fetched == {"status": 200, "container": first["container"], "mode": "LIVE"}, \
                    "Held response was not an actual successful server response"
                await page.unroute("**/api/method/fresko_universe.commercial.get_container_reconciliation", delayed_route)

                # Hold a second actual response while the operator changes Container.
                container_held, container_release, container_fulfilled = (asyncio.Event() for _ in range(3))
                async def delayed_container_route(route):
                    args = self.request_args(route.request.post_data or "")
                    if args.get("container") == first["container"] and not container_held.is_set():
                        response = await route.fetch()
                        body = await response.json()
                        result = body.get("message") or {}
                        assert response.ok and result.get("container") == first["container"]
                        container_held.set()
                        await container_release.wait()
                        await route.fulfill(response=response)
                        container_fulfilled.set()
                    else:
                        await route.continue_()
                await page.route("**/api/method/fresko_universe.commercial.get_container_reconciliation", delayed_container_route)
                await page.get_by_role("button", name="Refresh", exact=True).click()
                await asyncio.wait_for(container_held.wait(), timeout=30)
                await page.keyboard.press("Escape")  # Page picker only; no dialog is open.
                await set_link(first["alternate"])
                await wait_data(first["alternate"], "2099-01-01 00:00:00", "HISTORICAL")
                container_release.set()
                await asyncio.wait_for(container_fulfilled.wait(), timeout=10)
                await page.wait_for_function("!frappe.request.ajax_count", timeout=30000)
                await wait_data(first["alternate"], "2099-01-01 00:00:00", "HISTORICAL")
                await page.unroute("**/api/method/fresko_universe.commercial.get_container_reconciliation", delayed_container_route)

                # Prove the Money reader also discards a stale, genuinely fetched
                # Container receivable after a native cutoff refresh.
                money_user = self.fixture["users"]["verifier"]
                money_context = await browser.new_context(viewport={"width": 1280, "height": 900})
                money_page = await money_context.new_page()
                await money_page.goto(self.base + "/login")
                money_form = money_page.locator("form.form-signin:visible, form:has(input#login_email):visible").first
                await money_form.locator("input#login_email").fill(money_user["email"])
                await money_form.locator("input#login_password").fill(money_user["password"])
                await money_form.locator("button[type=submit]").click()
                await money_page.wait_for_url(lambda url: "/login" not in url)
                await money_page.goto(self.base + "/app/fresko-money")
                await money_page.locator("#tbl-collections").wait_for(state="visible", timeout=30000)

                async def money_link(fieldname, value):
                    holder = money_page.locator(f"body div[data-fieldname='{fieldname}']:visible").first
                    control = holder.locator("input:not([type=hidden])").first
                    if await control.input_value() != value:
                        await control.fill(value)
                        options = holder.locator(".awesomplete ul:visible [role='option']:visible")
                        await options.filter(has_text=value).first.wait_for(state="visible", timeout=10000)
                        match = None
                        for i in range(await options.count()):
                            option = options.nth(i)
                            text = (await option.inner_text()).strip().splitlines()[0].strip()
                            if text == value or text.startswith(value + " "):
                                match = option
                                break
                        assert match is not None, f"Native Money Link {fieldname} did not offer the requested fixture"
                        await match.click()
                        await control.press("Tab")
                    await money_page.wait_for_function(
                        f"expected => window.fresko_money.{fieldname}_field.get_value() === expected",
                        arg=value, timeout=10000)

                await money_link("company", self.fixture["company"])
                await money_link("container", first["container"])
                async def set_money_cutoff(value):
                    shown = await money_page.evaluate("iso => frappe.datetime.str_to_user(iso)", value)
                    control = money_page.locator("body div[data-fieldname='cutoff']:visible input:not([type=hidden])").first
                    await control.fill(shown)
                    await control.press("Tab")
                    await money_page.wait_for_function(
                        "expected => window.fresko_money.cutoff_field.get_value() === expected",
                        arg=value, timeout=10000)

                await money_page.locator('[data-tab="receivables"]').click()
                await set_money_cutoff("2099-01-01 00:00:00")
                money_held = asyncio.Event()
                money_release = asyncio.Event()
                money_fulfilled = asyncio.Event()
                money_latest_received = asyncio.Event()
                money_fetched = {}
                money_latest = {}
                async def delayed_money_route(route):
                    request = route.request
                    if "money.get_container_receivable" not in request.url:
                        await route.continue_()
                        return
                    args = self.request_args(request.post_data or "")
                    if args.get("container") == first["container"] and "2099" in str(args.get("as_of")) and not money_held.is_set():
                        response = await route.fetch()
                        body = await response.json()
                        result = body.get("message") or {}
                        assert response.ok and result.get("container") == first["container"], \
                            "Money delay must hold an actual successful Container receivable response"
                        money_fetched.update(status=response.status, container=result.get("container"), as_of=result.get("as_of"), sales_count=result.get("sales_count"))
                        money_held.set()
                        await money_release.wait()
                        await route.fulfill(response=response)
                        money_fulfilled.set()
                    else:
                        await route.continue_()

                async def capture_latest_money_response(response):
                    if "money.get_container_receivable" not in response.url:
                        return
                    args = self.request_args(response.request.post_data or "")
                    if args.get("container") == first["container"] and "2000" in str(args.get("as_of")):
                        body = await response.json()
                        result = body.get("message") or {}
                        money_latest.update(status=response.status, container=result.get("container"), as_of=result.get("as_of"), sales_count=result.get("sales_count"))
                        money_latest_received.set()

                money_page.on("response", capture_latest_money_response)
                await money_page.route("**/api/method/fresko_universe.money.get_container_receivable", delayed_money_route)
                await money_page.locator("#btn-query-rec").click()
                await asyncio.wait_for(money_held.wait(), timeout=30)
                await set_money_cutoff("2000-01-01 00:00:00")
                await money_page.locator("#btn-query-rec").click()
                await asyncio.wait_for(money_latest_received.wait(), timeout=30)
                await money_page.wait_for_function(
                    """([container, count]) => { const result = document.querySelector('#fm-receivable-result');
                        return result && result.innerText.includes(container) && Array.from(result.querySelectorAll('p'))
                            .some(p => p.innerText.trim() === 'Sales Count: ' + count); }""",
                    arg=[first["container"], money_latest.get("sales_count")], timeout=30000)
                latest_text = await money_page.locator("#fm-receivable-result").inner_text()
                assert money_fetched.get("status") == 200 and money_fetched.get("container") == first["container"], \
                    "Held Money response was not returned by the real endpoint"
                assert money_latest.get("status") == 200 and money_latest.get("container") == first["container"] and "2000" in str(money_latest.get("as_of")), \
                    "Newer Money cutoff result was not a real response for the requested cutoff"
                assert money_fetched.get("sales_count", 0) > money_latest.get("sales_count", 0), \
                    "Race acceptance requires distinguishable financial states; missing workflow truth must fail"
                money_release.set()
                await asyncio.wait_for(money_fulfilled.wait(), timeout=10)
                await money_page.wait_for_function("!frappe.request.ajax_count", timeout=30000)
                assert await money_page.locator("#fm-receivable-result").inner_text() == latest_text, \
                    "Obsolete Money response replaced the newer cutoff result"
                await money_page.unroute("**/api/method/fresko_universe.money.get_container_receivable", delayed_money_route)
                await money_context.close()
                await context.close()
                await browser.close()
                return {"workspace_held_response": fetched, "workspace_final_projection": "HISTORICAL",
                        "workspace_container_switch": "held_response_discarded",
                        "money_held_response": money_fetched, "money_new_response": money_latest}

        self.current_stage = "workspace:delayed-live-response-after-asof-switch"
        # The suite also owns Playwright's synchronous event loop. Run the
        # independent async browser on its own thread/event loop.
        with ThreadPoolExecutor(max_workers=1) as pool:
            evidence = pool.submit(asyncio.run, exercise()).result()
        # The browser artifact records only fixture names and response mode, never cookies or credentials.
        (self.output / "delayed-workspace-response.json").write_text(json.dumps(evidence, sort_keys=True))


class SafeResult(unittest.TextTestResult):
    def _exc_info_to_string(self, err, test):
        # Keep full details private; public output contains sanitized locations and workflow labels.
        detail = super()._exc_info_to_string(err, test)
        fixture = getattr(BrowserAcceptance, "fixture", {})
        for user in fixture.get("users", {}).values():
            detail = detail.replace(user["password"], "[REDACTED]")
        private = Path(os.environ["FRESKO_BROWSER_MANIFEST"]).parent / "private-errors.txt"
        with os.fdopen(os.open(private, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as stream:
            stream.write(detail + "\n")
        locations = [f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}"
                     for frame in traceback.extract_tb(err[2])]
        sessions = getattr(test, "_browser_sessions", [])
        control = next((session.last_field for session in reversed(sessions) if session.last_field), "unknown")
        safe = {
            "test": test.id(),
            "stage": getattr(test, "current_stage", "unknown"),
            "control_field": control,
            "exception": err[0].__name__,
            "locations": locations,
        }
        return "Sanitized browser failure: " + json.dumps(safe, sort_keys=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--artifacts", required=True)
    args = parser.parse_args()
    os.environ.update(FRESKO_BROWSER_MANIFEST=args.manifest, FRESKO_BROWSER_URL=args.url,
        FRESKO_BROWSER_ARTIFACTS=args.artifacts)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BrowserAcceptance)
    result = unittest.TextTestRunner(verbosity=2, resultclass=SafeResult).run(suite)
    output = Path(args.artifacts)
    accepted_output = getattr(BrowserAcceptance, "output", None)
    if (accepted_output is not None and accepted_output == output and
            output.is_dir() and not output.is_symlink()):
        (output / "summary.json").write_text(json.dumps({"tests": result.testsRun,
            "failures": len(result.failures), "errors": len(result.errors), "skips": len(result.skipped),
            "synthetic_only": True, "viewports": [1280, 390, 360], "physical_touch_device": "PENDING"}, indent=2))
    elif result.wasSuccessful():
        raise SystemExit("Refusing to report success because artifact directory was not accepted")
    passed = result.wasSuccessful() and not result.skipped
    raise SystemExit(0 if passed else 1)
