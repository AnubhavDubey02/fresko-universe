"""Real Frappe UI acceptance. Requires explicitly seeded, isolated synthetic site."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from decimal import Decimal
from urllib.parse import parse_qs
import unittest

from playwright.sync_api import sync_playwright, expect
from browser_support import BrowserSession


class BrowserAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(Path(os.environ["FRESKO_BROWSER_MANIFEST"]).read_text())
        if cls.fixture.get("synthetic_only") is not True:
            raise ValueError("Only explicit synthetic fixtures are accepted")
        cls.base = os.environ["FRESKO_BROWSER_URL"].rstrip("/")
        fixture_origin = (cls.fixture.get("browser_origin") or "").rstrip("/")
        if not fixture_origin or cls.base != fixture_origin:
            raise ValueError("Browser URL must exactly match the synthetic fixture browser_origin")
        cls.output = Path(os.environ["FRESKO_BROWSER_ARTIFACTS"])
        cls.output.mkdir(parents=True, exist_ok=True)
        cls.progress_path = Path(os.environ["FRESKO_BROWSER_MANIFEST"]).parent / "browser-progress.json"
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def session(self, role, width=1280):
        user = self.fixture["users"][role]
        session = BrowserSession(self.browser, self.base, user["email"], user["password"],
            {"width": width, "height": 900})
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

    def response_action(self, session, method, action, success=True):
        with session.page.expect_response(lambda r: method in r.url and r.request.method == "POST") as wait:
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
        session.goto("app/fresko-workspace")
        expect(session.page.locator(".fresko-workspace-container")).to_be_visible()
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
        session.page.locator('[data-tab-id="sales"]').click()
        session.page.locator("tr").filter(has=session.page.get_by_text(sale, exact=True)).get_by_role("button", name="Inspect", exact=True).click()
        expect(session.page.locator(".fresko-card-title").filter(has_text="Selected Sale:")).to_contain_text(sale)

    def sale_step(self, session, scenario, sale, label, method):
        self.workspace(session, scenario)
        self.inspect(session, sale)
        self.response_action(session, method, lambda: session.page.get_by_role("button", name=label, exact=True).click())
        self.record_progress(scenario["width"], sale=sale, stage=method.replace(".", "_"))

    def money_page(self, session):
        session.goto("app/fresko-money")
        expect(session.page.locator("#tbl-collections")).to_be_visible()
        session.datetime_field("cutoff", "2099-01-01 00:00:00")
        expect(session.page.locator("#fm-projections")).to_contain_text("Total Eligible")

    def money_step(self, session, name, target, label, method):
        self.money_page(session)
        row = session.page.locator(target + " tr").filter(has_text=name)
        self.response_action(session, method, lambda: row.get_by_role("button", name=label, exact=True).click())

    def scenario(self, width):
        scenario = next(s for s in self.fixture["scenarios"] if s["width"] == width)
        sales, maker, verifier, approver = [self.session(role, width) for role in ["sales", "maker", "verifier", "approver"]]
        self.workspace(sales, scenario)
        sales.page.get_by_role("button", name="New Sale", exact=True).click()
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
        self.record_progress(width, sale=sale, stage="sale_created")
        self.inspect(sales, sale)
        self.assertEqual(sales.page.locator(".fresko-card-title").filter(has_text="Selected Sale:").count(), 1)
        source = sales.rpc("frappe.client.get", {"doctype": "Fresko Commercial Sale", "name": sale})["message"]
        self.assertEqual(source["raw_party_alias"], scenario["raw_alias"])
        self.assertEqual(len(source["lines"]), 2)
        original_version = source["version"]
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
        self.sale_step(verifier, scenario, sale, "Verify Sale", "commercial.verify_sale")
        self.sale_step(approver, scenario, sale, "Approve Sale", "commercial.approve_sale")
        # Alias is proposed and reviewed through three real users and native dialogs.
        self.workspace(sales, scenario)
        sales.page.get_by_role("button", name="Propose Alias", exact=True).click()
        sales.dialog("Propose Party Alias Mapping")
        for field, value in {"company": self.fixture["company"], "raw_alias": scenario["raw_alias"],
                             "proposed_customer": self.fixture["customer"], "evidence": scenario["evidence"]}.items():
            sales.field(field, value, True)
        alias = self.response_action(sales, "commercial.propose_alias_mapping", lambda: sales.click_dialog("Propose Mapping"))["name"]
        self.record_progress(width, alias=alias, stage="alias_proposed")
        for user, label, method in [(verifier, "Verify", "verify_alias_mapping"), (approver, "Approve", "approve_alias_mapping")]:
            self.workspace(user, scenario)
            user.page.locator('[data-tab-id="alias"]').click()
            row = user.page.locator("#fresko-alias-queue-wrap tr").filter(has_text=alias)
            self.response_action(user, "commercial." + method, lambda: row.get_by_role("button", name=label, exact=True).click())
        # Late rate proposal creates an auditable successor. Never rewrite approved source.
        for index in range(2):
            self.workspace(sales, scenario)
            self.inspect(sales, sale)
            sales.page.get_by_role("button", name="Propose Rate", exact=True).first.click()
            for field, value in {"rate": "100", "evidence": scenario["evidence"], "reason": "Synthetic browser late price"}.items():
                sales.field(field, value, True)
            successor = self.response_action(sales, "commercial.propose_rate", lambda: sales.click_dialog("Propose Rate"))["name"]
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
        allocations = []
        for qty in ["20", "11", "21"]:
            self.workspace(sales, scenario)
            self.inspect(sales, sale)
            sales.page.get_by_role("button", name="+ Allocate to Outward", exact=True).click()
            sales.dialog("Propose Sale")
            sales.field("outward", scenario["outward"], True, require_autocomplete=True)
            expect(sales.dialog().locator('[data-fieldname="outward_line_key"] select')).to_have_value(scenario["outward_line_key"])
            sales.field("qty", qty, True)
            sales.field("evidence", scenario["evidence"], True)
            allocation = self.response_action(sales, "commercial.propose_sale_outward_allocation", lambda: sales.click_dialog("Propose Allocation"))["name"]
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
        maker.page.get_by_role("button", name="New Collection", exact=True).click()
        maker.dialog("Receive / Capture Collection")
        for field, value in {"payment_channel": "CASH", "source_classification": "CASH_DECLARATION", "amount": "6000",
            "payer_raw": scenario["raw_alias"], "customer": self.fixture["customer"], "source_evidence": scenario["evidence"]}.items():
            maker.field(field, value, True)
        collection = self.response_action(maker, "money.create_collection", lambda: maker.click_dialog("Create Collection"))["name"]
        self.record_progress(width, collection=collection, stage="collection_created")
        self.money_step(maker, collection, "#tbl-collections", "Submit", "money.submit_collection")
        denied = maker.rpc("fresko_universe.money.verify_collection", {"collection_name": collection})
        self.assertFalse(denied["ok"], "Maker must not verify own collection")
        maker.dismiss_messages()
        self.money_step(verifier, collection, "#tbl-collections", "Verify", "money.verify_collection")
        self.money_step(approver, collection, "#tbl-collections", "Approve", "money.approve_collection")
        self.money_page(maker)
        maker.page.get_by_role("button", name="Propose Allocation", exact=True).click()
        maker.dialog("Propose Payment Allocation")
        for field, value in {"collection": collection, "amount": "1000", "sale": sale,
            "container": scenario["container"], "evidence": scenario["evidence"]}.items():
            maker.field(field, value, True)
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

    def test_supplier_and_mixed_denials(self):
        for role in ["supplier", "mixed"]:
            with self.subTest(role=role):
                session = self.session(role)
                for route in ["app/fresko-workspace", "app/fresko-money"]:
                    session.goto(route)
                    expect(session.page.locator(".fresko-workspace-container, .fm-page")).to_have_count(0)
                    for method, args in [
                        ("fresko_universe.money.get_unallocated_collections", {"company": self.fixture["company"]}),
                        ("fresko_universe.commercial.get_container_reconciliation", {"container": self.fixture["scenarios"][0]["container"]})]:
                        response = session.context.request.get(self.base + "/api/method/" + method, params=args)
                        self.assertEqual(response.status, 403)
                        self.assertEqual(response.json().get("exc_type"), "PermissionError")


class SafeResult(unittest.TextTestResult):
    def _exc_info_to_string(self, err, test):
        # Public CI artifacts must never include credentials or raw HTTP/session traces.
        detail = super()._exc_info_to_string(err, test)
        fixture = getattr(BrowserAcceptance, "fixture", {})
        for user in fixture.get("users", {}).values():
            detail = detail.replace(user["password"], "[REDACTED]")
        private = Path(os.environ["FRESKO_BROWSER_MANIFEST"]).parent / "private-errors.txt"
        with os.fdopen(os.open(private, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as stream:
            stream.write(detail + "\n")
        return f"{err[0].__name__}: scenario failed; inspect private runner diagnostics"


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
    Path(args.artifacts).mkdir(parents=True, exist_ok=True)
    (Path(args.artifacts) / "summary.json").write_text(json.dumps({"tests": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors), "skips": len(result.skipped),
        "synthetic_only": True, "viewports": [1280, 390, 360], "physical_touch_device": "PENDING"}, indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
