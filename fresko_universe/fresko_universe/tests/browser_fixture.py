"""Explicitly enabled synthetic browser fixtures; never a whitelisted API."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

import frappe
from frappe.utils import now_datetime, nowdate
from frappe.installer import update_site_config
from frappe.utils.password import update_password, set_encrypted_password, get_decrypted_password
from frappe.utils.file_manager import save_file
import hashlib

from fresko_universe import outward
from fresko_universe.tests.utils import make_container


def _insert_browser_user(values):
    """Reserve one synthetic-user slot only in this local provisioning call."""
    if (not all(frappe.conf.get(flag) for flag in
                ("allow_tests", "fresko_browser_fixture_only", "fresko_disposable_browser_site"))
            or frappe.session.user != "Administrator"
            or values.get("doctype") != "User"
            or not values.get("email", "").endswith("@example.invalid")):
        frappe.throw("Synthetic user provisioning denied", frappe.PermissionError)
    present = "throttle_user_limit" in frappe.conf
    previous = frappe.conf.get("throttle_user_limit")
    try:
        # Native matrices can exhaust the 60-user limit before browser setup.
        # This capacity never persists or changes an HTTP worker's threshold.
        frappe.conf.throttle_user_limit = max(
            int(previous if previous is not None else 60),
            frappe.db.get_creation_count("User", 60) + 1)
        return frappe.get_doc(values).insert(ignore_permissions=True)
    finally:
        if present:
            frappe.conf.throttle_user_limit = previous
        else:
            frappe.conf.pop("throttle_user_limit", None)


def seed(manifest_path: str, browser_origin: str = "http://127.0.0.1:8000"):
    if not frappe.conf.get("fresko_browser_fixture_only") or not frappe.conf.get("allow_tests") or not frappe.conf.get("fresko_disposable_browser_site"):
        frappe.throw("Browser fixture requires both explicit synthetic-site flags")
    if frappe.session.user != "Administrator":
        frappe.throw("Browser fixture requires local bench Administrator", frappe.PermissionError)
    if frappe.conf.get("fresko_browser_seed_id"):
        frappe.throw("This disposable site already contains a browser fixture")
    origin = urlsplit(browser_origin)
    if (not origin.hostname or origin.username or origin.password or origin.path not in ("", "/")
            or origin.query or origin.fragment or origin.scheme not in ("http", "https")
            or (origin.scheme == "http" and origin.hostname not in ("127.0.0.1", "localhost"))):
        frappe.throw("Fixture browser origin must be HTTPS or explicit local loopback")
    target = Path(manifest_path).resolve()
    bench = Path(frappe.get_app_path("frappe")).resolve().parents[2]
    if target.is_relative_to(bench) or target.exists():
        frappe.throw("Credential manifest must be new and outside the bench")
    token = secrets.token_hex(5)
    company = frappe.get_doc({"doctype": "Company", "company_name": f"Browser Synthetic {token}",
        "abbr": f"B{token}", "default_currency": "INR", "country": "India"}).insert(ignore_permissions=True).name
    supplier = frappe.get_doc({"doctype": "Supplier", "supplier_name": f"Browser Supplier {token}",
        "supplier_group": "All Supplier Groups", "supplier_type": "Company"}).insert(ignore_permissions=True).name
    item = frappe.get_doc({"doctype": "Item", "item_code": f"BROWSER-{token}", "item_name": "Synthetic Produce",
        "item_group": "All Item Groups", "stock_uom": "Nos", "is_stock_item": 0}).insert(ignore_permissions=True).name
    customer_group = frappe.get_doc({"doctype": "Customer Group", "customer_group_name": f"Browser Customers {token}", "parent_customer_group": "All Customer Groups", "is_group": 0}).insert(ignore_permissions=True).name
    territory = frappe.get_doc({"doctype": "Territory", "territory_name": f"Browser Territory {token}", "parent_territory": "All Territories", "is_group": 0}).insert(ignore_permissions=True).name
    customer = frappe.get_doc({"doctype": "Customer", "customer_name": f"Browser Buyer {token}",
        "customer_type": "Company", "customer_group": customer_group, "territory": territory}).insert(ignore_permissions=True).name
    roles = {"sales": ["Fresko Salesperson"], "maker": ["Fresko Accounts"],
        "verifier": ["Fresko Accounts"], "approver": ["Fresko Approver"],
        "supplier": ["Fresko Supplier Viewer"], "mixed": ["Fresko Supplier Viewer", "Fresko Accounts"]}
    users = {}
    for label, assigned in roles.items():
        for role in assigned:
            if not frappe.db.exists("Role", role):
                frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)
        email = f"browser-{label}-{token}@example.invalid"
        password = secrets.token_urlsafe(24)
        _insert_browser_user({"doctype": "User", "email": email, "first_name": f"Browser {label}",
            "enabled": 1, "user_type": "System User", "send_welcome_email": 0,
            "roles": [{"role": role} for role in assigned]})
        update_password(email, password)
        frappe.defaults.set_user_default("Company", company, user=email)
        users[label] = {"email": email, "password": password, "roles": assigned}
    masters = {"company": company, "supplier": supplier, "item": item, "uom": "Nos", "currency": "INR"}
    set_encrypted_password("User", users["maker"]["email"], "SYNTHETIC ENCRYPTION SENTINEL", "api_secret")
    scenarios = []
    for width in [1280, 390, 360]:
        frappe.set_user("Administrator")
        container = make_container(masters, container_no=f"BROWSER-{token}-{width}", inward_qty=100,
            lots=[{"lot_no": "BROWSER-A", "inward_qty": 60, "uom": "Nos"},
                  {"lot_no": "BROWSER-B", "inward_qty": 40, "uom": "Nos"}])
        alternate = make_container(masters, container_no=f"BROWSER-ALT-{token}-{width}", inward_qty=20)
        evidence = frappe.get_doc({"doctype": "Fresko Evidence", "container": container.name,
            "evidence_type": "Note", "notes": "SYNTHETIC browser acceptance; no financial source truth"}).insert(ignore_permissions=True)
        frappe.set_user(users["sales"]["email"])
        result = outward.create(container=container.name, movement_at=now_datetime(),
            source_evidence=evidence.name, source_event_id=f"browser:{token}:{width}:outward", lines=[{
                "source_line_ref": "1", "raw_lot_text": "BROWSER-A", "lot_no": "BROWSER-A",
                "qty": "30", "uom": "Nos", "raw_qty_text": "30", "raw_uom_text": "Nos"}])
        outward.submit_for_review(result["name"])
        frappe.set_user(users["approver"]["email"])
        outward.post(result["name"])
        doc = frappe.get_doc("Fresko Outward", result["name"])
        scenarios.append({"width": width, "container": container.name, "alternate": alternate.name,
            "evidence": evidence.name, "lots": [r.name for r in container.lots],
            "outward": doc.name, "outward_line_key": doc.lines[0].line_key,
            "raw_alias": f"  Browser Buyer {token} {width}  ", "event_prefix": f"browser:{token}:{width}"})
    frappe.set_user("Administrator")
    private = save_file(f"browser-private-{token}.txt", b"SYNTHETIC PRIVATE RESTORE SENTINEL", "Fresko Evidence", scenarios[0]["evidence"], is_private=1)
    public = save_file(f"browser-public-{token}.txt", b"SYNTHETIC PUBLIC RESTORE SENTINEL", "Fresko Evidence", scenarios[0]["evidence"], is_private=0)
    frappe.db.commit()
    update_site_config("fresko_browser_seed_id", token)
    manifest = {"format_version": 1, "synthetic_only": True, "browser_origin": browser_origin.rstrip("/"), "company": company, "item": item,
        "uom": "Nos", "customer": customer, "users": users, "scenarios": scenarios,
        "fixture_date": nowdate(), "sentinels": [{"name": private.name, "sha256": hashlib.sha256(Path(private.get_full_path()).read_bytes()).hexdigest()}, {"name": public.name, "sha256": hashlib.sha256(Path(public.get_full_path()).read_bytes()).hexdigest()}]}
    target.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(manifest, stream)
    return {"synthetic_only": True, "scenario_count": len(scenarios)}


def recovery_snapshot(manifest_path: str, snapshot_path: str):
    """Snapshot protected record payloads and actual public/private file bytes."""
    if not frappe.conf.get("fresko_browser_fixture_only") or not frappe.conf.get("allow_tests") or not frappe.conf.get("fresko_disposable_browser_site"):
        frappe.throw("Synthetic recovery flags required")
    manifest = json.loads(Path(manifest_path).read_text())
    if manifest.get("synthetic_only") is not True:
        frappe.throw("Synthetic recovery manifest required")
    company = manifest["company"]
    data = {}
    for doctype in ["Fresko Container", "Fresko Outward", "Fresko Commercial Sale", "Fresko Collection", "Fresko Payment Allocation", "Fresko Party Alias Mapping", "Fresko Sale Outward Allocation"]:
        data[doctype] = [frappe.get_doc(doctype, row.name).as_dict() for row in frappe.get_all(doctype, filters={"company": company}, order_by="name")]
    secret = get_decrypted_password("User", manifest["users"]["maker"]["email"], "api_secret")
    if secret != "SYNTHETIC ENCRYPTION SENTINEL":
        frappe.throw("Restored encryption key cannot decrypt the synthetic sentinel")
    data["encrypted_secret_hash"] = hashlib.sha256(secret.encode()).hexdigest()
    data["files"] = []
    for expected in manifest["sentinels"]:
        doc = frappe.get_doc("File", expected["name"])
        digest = hashlib.sha256(Path(doc.get_full_path()).read_bytes()).hexdigest()
        if digest != expected["sha256"]:
            frappe.throw("Recovered file sentinel hash mismatch")
        data["files"].append({"name": doc.name, "sha256": digest, "private": doc.is_private})
    target = Path(snapshot_path)
    with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(data, stream, default=str, sort_keys=True)
    return {"synthetic_only": True, "record_counts": {key: len(value) for key, value in data.items()}}
