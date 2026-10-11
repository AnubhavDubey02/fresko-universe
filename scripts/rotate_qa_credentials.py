import json
import os
import pathlib
import secrets

def rotate():
    bench_sites = pathlib.Path("/home/dshri/.local/state/fresko-control/group-1b/runtime/frappe-bench/sites")
    os.chdir(bench_sites)

    import frappe
    from frappe.utils.password import update_password

    frappe.init(site="group1b-qa.localhost")
    frappe.connect()
    if not all(frappe.conf.get(key) for key in ("allow_tests", "fresko_disposable_browser_site", "fresko_browser_fixture_only")):
        raise RuntimeError("Credential rotation requires an explicitly disposable fixture site")
    frappe.set_user("Administrator")

    credentials_dir = pathlib.Path("/home/dshri/.local/state/fresko-control/group-1b/runtime/secrets")
    credentials_dir.mkdir(parents=True, exist_ok=True)
    creds_file = credentials_dir / "qa_reporting_credentials.json"
    manifest_file = credentials_dir / "browser-manifest.json"

    http_users = [
        ("accounts", "group1b-http-accounts@example.invalid"),
        ("maker", "group1b-http-maker@example.invalid"),
        ("reviewer", "group1b-http-reviewer@example.invalid"),
        ("other", "group1b-http-other@example.invalid"),
        ("supplier", "group1b-http-supplier@example.invalid"),
        ("mixed", "group1b-http-mixed@example.invalid"),
        ("revoked", "group1b-http-revoked@example.invalid"),
        ("ambiguous", "group1b-http-ambiguous@example.invalid"),
    ]

    creds = {"users": {}}
    for role_label, email in http_users:
        if frappe.db.exists("User", email):
            new_pass = secrets.token_urlsafe(24)
            update_password(email, new_pass, logout_all_sessions=True)
            creds["users"][role_label] = {"email": email, "password": new_pass}

    # Rotate manifest users if manifest exists
    if manifest_file.exists():
        manifest = json.loads(manifest_file.read_text())
        if "users" in manifest:
            for label, uinfo in manifest["users"].items():
                m_email = uinfo.get("email")
                if m_email and frappe.db.exists("User", m_email):
                    m_pass = next((info["password"] for info in creds["users"].values() if info["email"] == m_email), None) or secrets.token_urlsafe(24)
                    update_password(m_email, m_pass, logout_all_sessions=True)
                    manifest["users"][label]["password"] = m_pass
            # Write back manifest mode 0600
            manifest_file.write_text(json.dumps(manifest, indent=2))
            os.chmod(manifest_file, 0o600)

    frappe.db.commit()
    frappe.destroy()

    # Write private credentials file mode 0600
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    with os.fdopen(os.open(creds_file, flags, 0o600), "w") as f:
        json.dump(creds, f, indent=2)
    os.chmod(creds_file, 0o600)

    print(f"Rotated {len(creds['users'])} QA credentials. Private file saved at mode 0600.")

if __name__ == "__main__":
    rotate()
