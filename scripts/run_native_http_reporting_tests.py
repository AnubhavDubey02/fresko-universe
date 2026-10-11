import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from http.cookiejar import CookieJar

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPO_ROOT / "evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = os.environ.get("FRESKO_BROWSER_URL", "http://127.0.0.1:18080")
CREDS_FILE = pathlib.Path(os.environ.get("FRESKO_QA_CREDENTIALS_FILE", "/home/dshri/.local/state/fresko-control/group-1b/runtime/secrets/qa_reporting_credentials.json"))
CONTAINER_A = "CON-2026-00479"

def load_credentials():
    if not CREDS_FILE.exists():
        raise FileNotFoundError(f"Missing private credentials file: {CREDS_FILE}")
    data = json.loads(CREDS_FILE.read_text())
    # Return user_email -> password mapping
    creds = {}
    for role_label, info in data.get("users", {}).items():
        creds[info["email"]] = info["password"]
    return creds

def get_git_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), text=True).strip()
    except Exception:
        return "UNKNOWN"

class HTTPClient:
    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url
        self.cookie_jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))
        self.csrf_token = None

    def post(self, path, data=None):
        url = f"{self.base_url}{path}"
        headers = {}
        encoded = None
        if data is not None:
            encoded = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if self.csrf_token:
            headers["X-Frappe-CSRF-Token"] = self.csrf_token

        req = urllib.request.Request(url, data=encoded, headers=headers, method="POST")
        try:
            with self.opener.open(req, timeout=30) as resp:
                status = resp.status
                body = resp.read().decode("utf-8")
                # update csrf token if present in cookies
                for cookie in self.cookie_jar:
                    if cookie.name == "csrf_token":
                        self.csrf_token = cookie.value
                return status, body
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8") if e.fp else ""
            return e.code, body

    def get(self, path):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method="GET")
        try:
            with self.opener.open(req, timeout=30) as resp:
                status = resp.status
                body = resp.read().decode("utf-8")
                for cookie in self.cookie_jar:
                    if cookie.name == "csrf_token":
                        self.csrf_token = cookie.value
                return status, body
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8") if e.fp else ""
            return e.code, body

    def login(self, email, password):
        status, body = self.post("/api/method/login", {"usr": email, "pwd": password})
        if status != 200:
            raise RuntimeError(f"Login failed for {email}: HTTP {status} {body}")
        # Get CSRF token
        for cookie in self.cookie_jar:
            if cookie.name == "csrf_token":
                self.csrf_token = cookie.value
        return status

def run_tests():
    creds = load_credentials()
    sha = os.environ.get("FRESKO_DEPLOYED_SHA", get_git_sha())
    required = {"group1b-http-accounts@example.invalid", "group1b-http-supplier@example.invalid", "group1b-http-mixed@example.invalid", "group1b-http-other@example.invalid"}
    if required - set(creds):
        raise ValueError("Missing mandatory role-separated QA credentials")
    results = []

    print(f"Running native HTTP reporting API tests against {BASE_URL} (SHA: {sha})...")

    # 1. Unauthenticated / Guest denial on get_report_context
    guest_client = HTTPClient()
    status, body = guest_client.post("/api/method/fresko_universe.reporting_engine.get_report_context")
    results.append({
        "id": "HTTP-GUEST-CONTEXT-DENIAL",
        "description": "Unauthenticated Guest rejected on get_report_context",
        "status_code": status,
        "expected_code": 403,
        "passed": status == 403 and "PermissionError" in body
    })
    print(f"HTTP-GUEST-CONTEXT-DENIAL: {'PASS' if results[-1]['passed'] else 'FAIL'} (HTTP {status})")

    # 2. Supplier denial
    supp_email = "group1b-http-supplier@example.invalid"
    if supp_email in creds:
        supp_client = HTTPClient()
        supp_client.login(supp_email, creds[supp_email])
        status, body = supp_client.post("/api/method/fresko_universe.reporting_engine.get_report_context")
        results.append({
            "id": "HTTP-SUPPLIER-DENIAL",
            "description": "Supplier role rejected with HTTP 403",
            "status_code": status,
            "expected_code": 403,
            "passed": status == 403
        })
        print(f"HTTP-SUPPLIER-DENIAL: {'PASS' if results[-1]['passed'] else 'FAIL'} (HTTP {status})")

    # 3. Mixed role denial
    mixed_email = "group1b-http-mixed@example.invalid"
    if mixed_email in creds:
        mixed_client = HTTPClient()
        mixed_client.login(mixed_email, creds[mixed_email])
        status, body = mixed_client.post("/api/method/fresko_universe.reporting_engine.get_report_context")
        results.append({
            "id": "HTTP-MIXED-ROLE-DENIAL",
            "description": "Mixed Supplier/Accounts role rejected with HTTP 403",
            "status_code": status,
            "expected_code": 403,
            "passed": status == 403
        })
        print(f"HTTP-MIXED-ROLE-DENIAL: {'PASS' if results[-1]['passed'] else 'FAIL'} (HTTP {status})")

    # 4. Multi-tenant denial: Company B user accessing Company A container
    other_email = "group1b-http-other@example.invalid"
    if other_email in creds:
        other_client = HTTPClient()
        other_client.login(other_email, creds[other_email])
        status, body = other_client.post(
            "/api/method/fresko_universe.reporting_engine.execute_report",
            {"report": "container_stock", "container": CONTAINER_A}
        )
        results.append({
            "id": "HTTP-TENANT-DENIAL",
            "description": "Company B user denied access to Company A container",
            "status_code": status,
            "expected_code": 403,
            "passed": status == 403 and "Report access unavailable" in body
        })
        print(f"HTTP-TENANT-DENIAL: {'PASS' if results[-1]['passed'] else 'FAIL'} (HTTP {status})")

    # 5. Authenticated Company A user (Accounts) - get_report_context
    acc_email = "group1b-http-accounts@example.invalid"
    acc_client = HTTPClient()
    acc_client.login(acc_email, creds[acc_email])

    status, body = acc_client.post("/api/method/fresko_universe.reporting_engine.get_report_context")
    body_json = json.loads(body) if status == 200 else {}
    msg = body_json.get("message", {})
    context_passed = (
        status == 200 and
        msg.get("company") == "Wind Power LLC" and
        isinstance(msg.get("containers"), list) and
        msg.get("supported_reports") == ["container_stock", "receivables", "sales"]
    )
    results.append({
        "id": "HTTP-ACCOUNTS-CONTEXT",
        "description": "Company A accounts user receives valid context and permitted containers",
        "status_code": status,
        "expected_code": 200,
        "passed": context_passed,
        "company": msg.get("company"),
        "container_count": len(msg.get("containers", []))
    })
    print(f"HTTP-ACCOUNTS-CONTEXT: {'PASS' if context_passed else 'FAIL'} (HTTP {status})")

    # 6. execute_report endpoints
    for report_name in ["container_stock", "sales", "receivables"]:
        status, body = acc_client.post(
            "/api/method/fresko_universe.reporting_engine.execute_report",
            {"report": report_name, "container": CONTAINER_A}
        )
        body_json = json.loads(body) if status == 200 else {}
        msg = body_json.get("message", {})
        rows = msg.get("rows", [])
        rep_passed = (
            status == 200 and
            msg.get("report") == report_name and
            msg.get("company") == "Wind Power LLC" and
            msg.get("container") == CONTAINER_A and
            len(rows) > 0 and
            msg.get("read_only") is True
        )
        results.append({
            "id": f"HTTP-EXECUTE-{report_name.upper()}",
            "description": f"Execute report '{report_name}' returns HTTP 200 with non-empty rows",
            "status_code": status,
            "expected_code": 200,
            "passed": rep_passed,
            "row_count": len(rows),
            "status": msg.get("status")
        })
        print(f"HTTP-EXECUTE-{report_name.upper()}: {'PASS' if rep_passed else 'FAIL'} (HTTP {status}, {len(rows)} rows)")

    # 7. export_report_csv endpoints
    for report_name in ["container_stock", "sales", "receivables"]:
        status, body = acc_client.post(
            "/api/method/fresko_universe.reporting_engine.export_report_csv",
            {"report": report_name, "container": CONTAINER_A}
        )
        body_json = json.loads(body) if status == 200 else {}
        msg = body_json.get("message", {})
        content = msg.get("content", "")
        csv_passed = (
            status == 200 and
            msg.get("filename", "").endswith(".csv") and
            msg.get("mime_type") == "text/csv;charset=utf-8" and
            content.startswith("\ufeff") and
            msg.get("rows", 0) > 0 and
            msg.get("read_only") is True
        )
        results.append({
            "id": f"HTTP-EXPORT-CSV-{report_name.upper()}",
            "description": f"Export CSV for '{report_name}' returns HTTP 200 with UTF-8 BOM content",
            "status_code": status,
            "expected_code": 200,
            "passed": csv_passed,
            "filename": msg.get("filename"),
            "rows": msg.get("rows")
        })
        print(f"HTTP-EXPORT-CSV-{report_name.upper()}: {'PASS' if csv_passed else 'FAIL'} (HTTP {status}, {msg.get('rows')} rows)")

    out = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_sha": sha,
        "base_url": BASE_URL,
        "total_tests": len(results),
        "passed_tests": sum(1 for r in results if r["passed"]),
        "results": results
    }

    out_file = EVIDENCE_DIR / "native_http_reporting_results.json"
    out_file.write_text(json.dumps(out, indent=2))
    print(f"\nNative HTTP tests complete: {out['passed_tests']}/{out['total_tests']} passed.")
    print(f"Report saved to: {out_file}")
    return out

if __name__ == "__main__":
    out = run_tests()
    if out["passed_tests"] != out["total_tests"]:
        sys.exit(1)
