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
    "Fresko Adjustment Application": "fresko_universe.fresko_core.services.money_service.adjustment_application_permission_query",
    "Fresko Receivable Adjustment": "fresko_universe.fresko_core.services.money_service.receivable_adjustment_permission_query",
    "Fresko Payment Allocation": "fresko_universe.fresko_core.services.money_service.payment_allocation_permission_query",
    "Fresko Collection": "fresko_universe.fresko_core.services.money_service.collection_permission_query",
    "Customer": "fresko_universe.permissions.customer_internal_permission_query",
    "Fresko Exception": "fresko_universe.fresko_core.services.money_service.exception_permission_query",
    "Fresko Sale Outward Allocation": "fresko_universe.fresko_core.services.commercial_service.allocation_permission_query",
    "Fresko Party Alias Mapping": "fresko_universe.fresko_core.services.commercial_service.alias_permission_query",
    "Fresko Commercial Sale": "fresko_universe.fresko_core.services.commercial_service.sale_permission_query",
    "Fresko Deal": "fresko_universe.permissions.deal_permission_query",
    "Fresko Evidence": "fresko_universe.permissions.evidence_permission_query",
    "Fresko Evidence Attachment": "fresko_universe.permissions.evidence_attachment_permission_query",
    "Fresko Evidence Attempt": "fresko_universe.permissions.evidence_attempt_permission_query",
    "Fresko Outward": "fresko_universe.permissions.outward_permission_query",
    "Fresko Field Assertion": "fresko_universe.permissions.field_assertion_permission_query",
    "Fresko Container Quantity Assertion": "fresko_universe.permissions.quantity_assertion_permission_query",
}

has_permission = {
    "Fresko Adjustment Application": "fresko_universe.fresko_core.services.money_service.money_has_permission",
    "Fresko Receivable Adjustment": "fresko_universe.fresko_core.services.money_service.money_has_permission",
    "Fresko Payment Allocation": "fresko_universe.fresko_core.services.money_service.money_has_permission",
    "Fresko Collection": "fresko_universe.fresko_core.services.money_service.money_has_permission",
    "Customer": "fresko_universe.permissions.customer_internal_has_permission",
    "Fresko Exception": "fresko_universe.fresko_core.services.money_service.exception_has_permission",
    "Fresko Sale Outward Allocation": "fresko_universe.fresko_core.services.commercial_service.commercial_has_permission",
    "Fresko Party Alias Mapping": "fresko_universe.fresko_core.services.commercial_service.commercial_has_permission",
    "Fresko Commercial Sale": "fresko_universe.fresko_core.services.commercial_service.commercial_has_permission",
    "Fresko Deal": "fresko_universe.permissions.deal_has_permission",
    "Fresko Evidence": "fresko_universe.permissions.evidence_has_permission",
    "Fresko Evidence Attachment": "fresko_universe.permissions.evidence_attachment_has_permission",
    "Fresko Evidence Attempt": "fresko_universe.permissions.evidence_attempt_has_permission",
    "Fresko Outward": "fresko_universe.permissions.outward_has_permission",
    "Fresko Field Assertion": "fresko_universe.permissions.field_assertion_has_permission",
    "Fresko Container Quantity Assertion": "fresko_universe.permissions.quantity_assertion_has_permission",
}

# FSEC-004 / FSEC-005 — Protect captured original files and evidence records
doc_events = {
    "File": {
        "on_trash": ["fresko_universe.fresko_core.services.evidence_service.prevent_captured_file_deletion", "fresko_universe.fresko_core.services.money_service.protect_money_file_on_trash"],
        "before_save": ["fresko_universe.fresko_core.services.evidence_service.prevent_captured_file_modification", "fresko_universe.fresko_core.services.money_service.protect_money_file_before_save"],
    },
    "Fresko Evidence": {
        "on_trash": "fresko_universe.fresko_core.services.evidence_service.prevent_captured_evidence_deletion",
    },
}

scheduler_events = {
    "daily": [
        "fresko_universe.integrity.scheduled_integrity_check",
    ],
}


