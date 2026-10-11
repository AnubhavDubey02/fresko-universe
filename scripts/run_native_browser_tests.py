import csv
import io
import json
import os
import pathlib
import sys
import time
from decimal import Decimal
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:18080"
EVIDENCE_DIR = pathlib.Path(__file__).resolve().parents[1] / "evidence" / "native_browser"
SCREENSHOTS_DIR = EVIDENCE_DIR / "screenshots"
VIDEO_DIR = EVIDENCE_DIR / "video"
TRACES_DIR = EVIDENCE_DIR / "traces"
CSV_DIR = EVIDENCE_DIR / "csv"
LOGS_DIR = EVIDENCE_DIR / "logs"

for d in (SCREENSHOTS_DIR, VIDEO_DIR, TRACES_DIR, CSV_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

PASSWORD = "SyntheticQA_Pass123!"
CONTAINER_A = "CON-2026-00479"

VIEWPORTS = {
    "DESKTOP": {"width": 1440, "height": 900},
    "MOBILE": {"width": 390, "height": 844, "is_mobile": True, "has_touch": True}
}

cases = [
    {
        "id": "NATIVE-CONTAINER_STOCK-DESKTOP",
        "user": "group1b-http-accounts@example.invalid",
        "container": CONTAINER_A,
        "report": "container_stock",
        "viewport": "DESKTOP",
        "expect_error": False,
        "export_csv": True
    },
    {
        "id": "NATIVE-CONTAINER_STOCK-MOBILE",
        "user": "group1b-http-accounts@example.invalid",
        "container": CONTAINER_A,
        "report": "container_stock",
        "viewport": "MOBILE",
        "expect_error": False,
        "export_csv": True
    },
    {
        "id": "NATIVE-SALES-DESKTOP",
        "user": "group1b-http-accounts@example.invalid",
        "container": CONTAINER_A,
        "report": "sales",
        "viewport": "DESKTOP",
        "expect_error": False,
        "export_csv": False
    },
    {
        "id": "NATIVE-RECEIVABLES-DESKTOP",
        "user": "group1b-http-accounts@example.invalid",
        "container": CONTAINER_A,
        "report": "receivables",
        "viewport": "DESKTOP",
        "expect_error": False,
        "export_csv": False
    },
    {
        "id": "NATIVE-TENANT_DENIAL-DESKTOP",
        "user": "group1b-http-other@example.invalid",
        "container": CONTAINER_A,
        "report": "container_stock",
        "viewport": "DESKTOP",
        "expect_error": True,
        "export_csv": False
    }
]

def run_suite():
    results = []
    start_total = time.time()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        for case in cases:
            case_id = case["id"]
            vp_name = case["viewport"]
            vp = VIEWPORTS[vp_name]
            print(f"--- Running {case_id} ---")
            t0 = time.time()

            # Record video into case-specific dir
            case_video_dir = VIDEO_DIR / case_id
            case_video_dir.mkdir(parents=True, exist_ok=True)

            context = browser.new_context(
                viewport={"width": vp["width"], "height": vp["height"]},
                is_mobile=vp.get("is_mobile", False),
                has_touch=vp.get("has_touch", False),
                record_video_dir=str(case_video_dir),
                record_video_size={"width": vp["width"], "height": vp["height"]}
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)

            page = context.new_page()
            page_errors = []
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))

            record = {
                "id": case_id,
                "scope": "REAL NATIVE FRAPPE v15 + MARIADB 10.6 OVER LOOPBACK HTTP",
                "report": case["report"],
                "viewport": vp_name.lower(),
                "user": case["user"],
                "status": "PENDING",
                "error": None,
                "csv_path": None,
                "screenshots": {}
            }

            try:
                # 1. Login
                page.goto(f"{BASE_URL}/login", wait_until="networkidle")
                page.locator("#login_email").fill(case["user"])
                page.locator("#login_password").fill(PASSWORD)
                page.locator("button.btn-login").first.click()
                page.wait_for_url("**/app/**", timeout=20000)

                # 2. Go to Reports Desk Page via client-side routing
                page.evaluate("frappe.set_route('fresko-reports')")
                page.locator("#frp-run").wait_for(timeout=15000)

                # Capture before screenshot
                shot_before = SCREENSHOTS_DIR / f"{case_id}_before.png"
                page.screenshot(path=str(shot_before))
                record["screenshots"]["before"] = str(shot_before.name)

                # Fill container and select type
                page.locator("#frp-container").fill(case["container"])
                page.locator("#frp-type").select_option(case["report"])

                # Click Run
                page.locator("#frp-run").click()

                if case["expect_error"]:
                    # Wait for denial status message
                    page.get_by_text("Report could not be loaded", exact=False).wait_for(timeout=15000)
                    time.sleep(1)
                    shot_after = SCREENSHOTS_DIR / f"{case_id}_denial.png"
                    page.screenshot(path=str(shot_after))
                    record["screenshots"]["after"] = str(shot_after.name)
                    record["status"] = "PASS_NATIVE_DENIAL"
                else:
                    # Wait for success status
                    page.get_by_text("Read-only report ready", exact=False).wait_for(timeout=20000)
                    time.sleep(1)
                    shot_after = SCREENSHOTS_DIR / f"{case_id}_after.png"
                    page.screenshot(path=str(shot_after))
                    record["screenshots"]["after"] = str(shot_after.name)

                    if case["export_csv"]:
                        assert page.locator("#frp-export").is_enabled()
                        with page.expect_download() as download_info:
                            page.locator("#frp-export").click()
                        download = download_info.value
                        csv_dest = CSV_DIR / f"{case_id}.csv"
                        download.save_as(str(csv_dest))
                        record["csv_path"] = str(csv_dest.name)

                    record["status"] = "PASS_NATIVE"

            except Exception as e:
                print(f"FAILED {case_id}: {e}")
                record["status"] = "FAIL"
                record["error"] = str(e)
                shot_err = SCREENSHOTS_DIR / f"{case_id}_error.png"
                try:
                    page.screenshot(path=str(shot_err))
                    record["screenshots"]["error"] = str(shot_err.name)
                except Exception:
                    pass

            finally:
                trace_path = TRACES_DIR / f"{case_id}.zip"
                context.tracing.stop(path=str(trace_path))
                record["trace"] = str(trace_path.name)

                page.close()
                video_obj = page.video
                context.close()

                if video_obj:
                    time.sleep(0.5)
                    raw_video = video_obj.path()
                    target_video = VIDEO_DIR / f"{case_id}.webm"
                    if pathlib.Path(raw_video).exists():
                        pathlib.Path(raw_video).replace(target_video)
                        record["video"] = str(target_video.name)
                # Cleanup per-case dir if empty
                if case_video_dir.exists():
                    try:
                        case_video_dir.rmdir()
                    except Exception:
                        pass

                record["elapsed_s"] = round(time.time() - t0, 3)
                record["page_errors"] = page_errors
                results.append(record)
                print(f"Finished {case_id}: {record['status']} in {record['elapsed_s']}s")

        browser.close()

    total_elapsed = round(time.time() - start_total, 3)
    out = {
        "format": "FRESKO_NATIVE_BROWSER_E2E_EVIDENCE_V1",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": BASE_URL,
        "total_cases": len(results),
        "passed_cases": sum(1 for r in results if r["status"].startswith("PASS")),
        "total_elapsed_s": total_elapsed,
        "cases": results
    }

    results_file = LOGS_DIR / "native_browser_results.json"
    results_file.write_text(json.dumps(out, indent=2))
    print(f"\nSuite complete: {out['passed_cases']}/{out['total_cases']} passed in {total_elapsed}s")
    print(f"Results written to: {results_file}")
    return out

if __name__ == "__main__":
    out = run_suite()
    if out["passed_cases"] != out["total_cases"]:
        sys.exit(1)
