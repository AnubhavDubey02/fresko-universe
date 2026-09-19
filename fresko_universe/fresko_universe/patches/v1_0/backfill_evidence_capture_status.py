# Copyright (c) 2026, Anubhav Dubey and contributors
import hashlib
import frappe

from fresko_universe.constants import (
    HASH_ALGORITHM_LEGACY_PATH_V0,
    HASH_ALGORITHM_LEGACY_UNVERIFIED,
)


def execute():
    """Post-model-sync patch for Evidence Phase 2 fields.

    Reconciles legacy content_sha256 by demonstrating path-hash origin,
    backfills parent overall_verification_status and manifest_status,
    and preserves UNKNOWN/NULL identity for legacy rows.
    """
    # 1. Distinguish demonstrated path-hashes from other legacy hashes
    rows = frappe.db.sql(
        """
        SELECT name, file, external_ref, content_sha256, hash_algorithm
        FROM `tabFresko Evidence`
        WHERE content_sha256 IS NOT NULL AND content_sha256 != ''
        """,
        as_dict=True,
    )
    for row in rows:
        if row.get("hash_algorithm"):
            continue
        file_val = row.get("file") or row.get("external_ref") or ""
        expected_path_hash = hashlib.sha256(file_val.encode("utf-8")).hexdigest()
        if row.get("content_sha256") == expected_path_hash:
            algo = HASH_ALGORITHM_LEGACY_PATH_V0
        else:
            algo = HASH_ALGORITHM_LEGACY_UNVERIFIED
        name_val = row.get("name") if isinstance(row, dict) else getattr(row, "name", None)
        frappe.db.set_value("Fresko Evidence", name_val, "hash_algorithm", algo, update_modified=False)


    # 2. Backfill overall_verification_status where NULL or empty
    frappe.db.sql(
        """
        UPDATE `tabFresko Evidence`
        SET overall_verification_status = 'PENDING'
        WHERE overall_verification_status IS NULL OR overall_verification_status = ''
        """
    )

    # 3. Backfill manifest_status where NULL or empty
    frappe.db.sql(
        """
        UPDATE `tabFresko Evidence`
        SET manifest_status = 'UNKNOWN'
        WHERE manifest_status IS NULL OR manifest_status = ''
        """
    )

    # 4. Backfill expected_attachment_count where NULL
    frappe.db.sql(
        """
        UPDATE `tabFresko Evidence`
        SET expected_attachment_count = -1
        WHERE expected_attachment_count IS NULL
        """
    )

    # 5. Backfill verified_attachment_count where NULL
    frappe.db.sql(
        """
        UPDATE `tabFresko Evidence`
        SET verified_attachment_count = 0
        WHERE verified_attachment_count IS NULL
        """
    )
