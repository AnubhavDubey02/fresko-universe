app_name = "fresko_universe"
app_title = "Fresko Universe"
app_publisher = "Fresko"
app_description = "Produce Trade OS — Container + Deal Phase 1"
app_email = "dev@fresko.local"
app_license = "mit"
app_version = "0.0.1"

required_apps = ["frappe", "erpnext"]

after_install = "fresko_universe.install.after_install"
after_migrate = "fresko_universe.install.after_migrate"

# DocType controllers own validate/before_insert; no duplicate string hooks needed.

fixtures = [
    {
        "dt": "Role",
        "filters": [
            [
                "name",
                "in",
                [
                    "Fresko Salesperson",
                    "Fresko Approver",
                    "Fresko Accounts",
                ],
            ]
        ],
    },
]

# FSEC-003 — row-level + document ACL (Salesperson owner/salesperson scoped)
permission_query_conditions = {
    "Fresko Deal": "fresko_universe.permissions.deal_permission_query",
    "Fresko Evidence": "fresko_universe.permissions.evidence_permission_query",
    "Fresko Evidence Attachment": "fresko_universe.permissions.evidence_attachment_permission_query",
    "Fresko Evidence Attempt": "fresko_universe.permissions.evidence_attempt_permission_query",
}

has_permission = {
    "Fresko Deal": "fresko_universe.permissions.deal_has_permission",
    "Fresko Evidence": "fresko_universe.permissions.evidence_has_permission",
    "Fresko Evidence Attachment": "fresko_universe.permissions.evidence_attachment_has_permission",
    "Fresko Evidence Attempt": "fresko_universe.permissions.evidence_attempt_has_permission",
}

# FSEC-004 / FSEC-005 — Protect captured original files and evidence records
doc_events = {
    "File": {
        "on_trash": "fresko_universe.fresko_core.services.evidence_service.prevent_captured_file_deletion",
        "before_save": "fresko_universe.fresko_core.services.evidence_service.prevent_captured_file_modification",
    },
    "Fresko Evidence": {
        "on_trash": "fresko_universe.fresko_core.services.evidence_service.prevent_captured_evidence_deletion",
    },
}


