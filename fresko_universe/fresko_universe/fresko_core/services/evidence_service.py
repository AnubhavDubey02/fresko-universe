# Copyright (c) 2026, Anubhav Dubey and contributors
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

import frappe
from frappe.utils import now_datetime

from fresko_universe.constants import (
    EVIDENCE_ATTEMPT_OPERATIONS,
    EVIDENCE_ATTEMPT_OUTCOMES,
    HASH_ALGORITHM_SHA256_V1,
    SCOPED_ATTACHMENT_LOGICAL_VERSION,
    SCOPED_ATTACHMENT_VERSION,
    SCOPED_MESSAGE_KEY_VERSION,
    TRUSTED_PROVENANCE_TYPES,
)
from fresko_universe import permissions
from fresko_universe.permissions import (
    ROLE_APPROVER,
    current_roles,
    evidence_has_permission,
    is_system_manager,
)


class IntegrityConflictError(frappe.ValidationError):
    pass


@dataclass
class CaptureResult:
    success: bool
    status: str
    content_sha256: str | None = None
    content_byte_count: int = 0
    reason: str | None = None


def canonicalize_payload(payload: Any) -> tuple[str, str]:
    """Return (canonical_json_string, sha256_hex) for a payload object or string."""
    if payload is None:
        payload_str = ""
    elif isinstance(payload, (dict, list)):
        payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    elif isinstance(payload, bytes):
        payload_str = payload.decode("utf-8", errors="replace")
    else:
        payload_str = str(payload)

    digest = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
    return payload_str, digest


def compute_scoped_message_key(
    provider: str | None,
    provider_account_id: str | None,
    conversation_id: str | None,
    provider_message_id: str | None,
) -> str | None:
    """Compute deterministic scoped-message key per WHATSAPP_FIXTURE_CONTRACT.md.

    Preserves opaque provider identifiers exactly without trimming.
    """
    scope = [provider, provider_account_id, conversation_id, provider_message_id]
    if not all(isinstance(v, str) and v for v in scope):
        return None

    payload = json.dumps(
        [
            SCOPED_MESSAGE_KEY_VERSION,
            provider,
            provider_account_id,
            conversation_id,
            provider_message_id,
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_logical_attachment_key(
    provider: str | None,
    provider_account_id: str | None,
    conversation_id: str | None,
    provider_message_id: str | None,
    identity_type: str,
    identity_value: str | int,
) -> str | None:
    """Compute logical attachment key with typed identity namespace.

    Explicitly separates ["provider_id", val] from ["ordinal", val]
    so provider IDs like "ord:0" cannot collide with ordinal 0.
    Preserves opaque provider identifiers exactly without trimming.
    """
    scope = [provider, provider_account_id, conversation_id, provider_message_id]
    if not all(isinstance(v, str) and v for v in scope):
        return None

    if identity_type == "provider_id":
        if not isinstance(identity_value, str) or not identity_value:
            return None
        id_spec = ["provider_id", identity_value]
    elif identity_type == "ordinal":
        if not isinstance(identity_value, int) or identity_value < 0:
            return None
        id_spec = ["ordinal", identity_value]
    else:
        return None

    payload = json.dumps(
        [
            SCOPED_ATTACHMENT_LOGICAL_VERSION,
            provider,
            provider_account_id,
            conversation_id,
            provider_message_id,
            id_spec,
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_scoped_attachment_version_key(
    logical_attachment_key: str | None,
    version: int,
) -> str | None:
    """Compute version-scoped key for an immutable attachment capture version."""
    if not logical_attachment_key or not isinstance(version, int) or version < 1:
        return None

    payload = json.dumps(
        [SCOPED_ATTACHMENT_VERSION, logical_attachment_key, version],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _lock_parent_evidence(evidence_name: str) -> dict:
    """Lock the parent Fresko Evidence row first to enforce deterministic lock hierarchy."""
    rows = frappe.db.sql(
        """
        SELECT name, deal, manifest_status, expected_attachment_count,
               verified_attachment_count, overall_verification_status,
               provider, provider_account_id, conversation_id, provider_message_id,
               scoped_message_key, message_payload_sha256
        FROM `tabFresko Evidence`
        WHERE name = %s
        FOR UPDATE
        """,
        (evidence_name,),
        as_dict=True,
    )
    if not rows:
        frappe.throw(f"Evidence '{evidence_name}' not found", frappe.DoesNotExistError)
    return rows[0]


def _persist_attempt_independently(fields: dict[str, Any]) -> bool:
    """Persist structured conflict attempt record via an independent connection/transaction,
    ensuring the caller's active database transaction is NEVER committed."""
    try:
        conf = getattr(frappe, "conf", None)
        if conf and getattr(conf, "db_name", None):
            import pymysql

            db_host = getattr(conf, "db_host", "127.0.0.1") or "127.0.0.1"
            db_port = int(getattr(conf, "db_port", 3306) or 3306)
            db_user = getattr(conf, "db_name", None)
            db_password = getattr(conf, "db_password", None)
            db_name = getattr(conf, "db_name", None)
            db_socket = getattr(conf, "db_socket", None)

            connect_kwargs: dict[str, Any] = {
                "user": db_user,
                "password": db_password,
                "database": db_name,
                "charset": "utf8mb4",
                "autocommit": True,
            }
            if db_socket and os.path.exists(db_socket):
                connect_kwargs["unix_socket"] = db_socket
            else:
                connect_kwargs["host"] = db_host
                connect_kwargs["port"] = db_port

            conn = pymysql.connect(**connect_kwargs)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SET foreign_key_checks = 0")
                    cols = list(fields.keys())
                    placeholders = ", ".join(["%s"] * len(cols))
                    col_names = ", ".join([f"`{c}`" for c in cols])
                    sql = f"INSERT INTO `tabFresko Evidence Attempt` ({col_names}) VALUES ({placeholders})"
                    cursor.execute(sql, list(fields.values()))
                conn.commit()
                return True
            except Exception as ce:
                print(f"[_persist_attempt_independently cursor ERROR: {ce}]")
            finally:
                conn.close()
    except Exception as e:
        print(f"[_persist_attempt_independently conn ERROR: {e}]")
    return False


def _record_attempt(
    evidence: str,
    operation: str,
    outcome: str,
    evidence_attachment: str | None = None,
    scoped_message_key: str | None = None,
    logical_attachment_key: str | None = None,
    scoped_attachment_version_key: str | None = None,
    payload_sha256: str | None = None,
    existing_payload_sha256: str | None = None,
    source_payload: str | None = None,
    existing_payload: str | None = None,
    old_doc_ref: str | None = None,
    new_doc_ref: str | None = None,
    observed_byte_count: int | None = None,
    observed_sha256: str | None = None,
    reason: str | None = None,
    isolated: bool = False,
) -> None:
    """Insert an authoritative, structured, append-only attempt record.

    Internal blanket commits are NEVER performed.
    When isolated=True, the record is persisted via a dedicated database transaction
    so it survives caller rollback without committing the caller's active database transaction.
    """
    now = now_datetime()
    actor = frappe.session.user or "Administrator"
    name = frappe.generate_hash(length=10)

    fields = {
        "name": name,
        "creation": now,
        "modified": now,
        "modified_by": actor,
        "owner": actor,
        "docstatus": 0,
        "idx": 0,
        "evidence": evidence,
        "evidence_attachment": evidence_attachment,
        "scoped_message_key": scoped_message_key,
        "logical_attachment_key": logical_attachment_key,
        "scoped_attachment_version_key": scoped_attachment_version_key,
        "attempt_time": now,
        "actor": actor,
        "operation": operation,
        "outcome": outcome,
        "payload_sha256": payload_sha256,
        "existing_payload_sha256": existing_payload_sha256,
        "source_payload": source_payload,
        "existing_payload": existing_payload,
        "old_doc_ref": old_doc_ref,
        "new_doc_ref": new_doc_ref,
        "observed_byte_count": observed_byte_count,
        "observed_sha256": observed_sha256,
        "reason": reason,
    }

    if isolated:
        persisted = _persist_attempt_independently(fields)
        if persisted:
            return

    # Within-transaction insert (NEVER calls frappe.db.commit)
    attempt = frappe.new_doc("Fresko Evidence Attempt")
    attempt.flags.in_service = True
    for k, v in fields.items():
        setattr(attempt, k, v)
    attempt.insert(ignore_permissions=True)


def _load_manifest_data(prov_ref: str | None) -> Any:
    """Load JSON manifest data from path or existing attempt records."""
    if not prov_ref or not str(prov_ref).strip():
        return None

    ref_str = str(prov_ref)
    candidates = [
        ref_str,
        frappe.get_site_path(ref_str) if hasattr(frappe, "get_site_path") else None,
        os.path.join(os.path.dirname(__file__), "..", "..", "..", ref_str),
    ]
    for c in candidates:
        if c and os.path.exists(c) and os.path.isfile(c):
            try:
                with open(c, "r", encoding="utf-8") as mf:
                    return json.load(mf)
            except Exception:
                pass

    existing_attempts = frappe.db.sql(
        """
        SELECT name, source_payload, observed_byte_count, observed_sha256
        FROM `tabFresko Evidence Attempt`
        WHERE (name = %s OR old_doc_ref = %s OR new_doc_ref = %s)
        LIMIT 1
        """,
        (ref_str, ref_str, ref_str),
        as_dict=True,
    )
    if existing_attempts:
        att_entry = existing_attempts[0]
        sp = getattr(att_entry, "source_payload", None) or (att_entry.get("source_payload") if hasattr(att_entry, "get") else None)
        if sp:
            try:
                return json.loads(sp)
            except Exception:
                pass
        obc = getattr(att_entry, "observed_byte_count", None) or (att_entry.get("observed_byte_count") if hasattr(att_entry, "get") else None)
        osh = getattr(att_entry, "observed_sha256", None) or (att_entry.get("observed_sha256") if hasattr(att_entry, "get") else None)
        if obc or osh:
            return {
                "attachments": [{
                    "expected_byte_count": obc,
                    "expected_sha256": osh,
                }]
            }
    return None


def _extract_manifest_items(manifest_data: Any) -> list[dict]:
    """Extract list of attachment items from parsed manifest data."""
    items: list[dict] = []
    if isinstance(manifest_data, dict):
        if "attachments" in manifest_data and isinstance(manifest_data["attachments"], list):
            items = manifest_data["attachments"]
        elif "files" in manifest_data and isinstance(manifest_data["files"], list):
            items = manifest_data["files"]
        elif "cases" in manifest_data and isinstance(manifest_data["cases"], list):
            for case in manifest_data["cases"]:
                src = case.get("source", {})
                for m in src.get("attachment_members", []):
                    items.append(m if isinstance(m, dict) else {"file_name": str(m)})
        else:
            for k, v in manifest_data.items():
                if isinstance(v, dict):
                    entry_copy = dict(v)
                    entry_copy.setdefault("key", k)
                    items.append(entry_copy)
    elif isinstance(manifest_data, list):
        items = manifest_data
    return items


def _load_parent_payload(parent_name: str | None) -> Any:
    """Retrieve transport payload from attempt records for parent evidence."""
    if not parent_name:
        return None
    attempt_rows = frappe.db.sql(
        """
        SELECT name, source_payload, observed_byte_count, observed_sha256
        FROM `tabFresko Evidence Attempt`
        WHERE evidence = %s AND operation IN ('MESSAGE_INGEST', 'ATTACHMENT_INGEST')
        ORDER BY creation DESC
        """,
        (parent_name,),
        as_dict=True,
    )
    for att_rec in attempt_rows:
        sp = getattr(att_rec, "source_payload", None) or (att_rec.get("source_payload") if hasattr(att_rec, "get") else None)
        if sp:
            try:
                return json.loads(sp)
            except Exception:
                pass
    return None



def get_validated_local_file_path(file_url: str) -> str:
    """Validate file path against local site root using strict path-component containment."""
    from pathlib import Path

    if not file_url:
        frappe.throw("Empty file URL", frappe.ValidationError)

    # Reject remote storage protocols explicitly
    if file_url.startswith(("http://", "https://", "s3://", "gs://", "ftp://")):
        frappe.throw(
            f"Remote storage '{file_url}' is unsupported; local storage required",
            title="Unsupported Storage",
        )

    if file_url.startswith("/private/files/"):
        subpath = file_url[len("/private/files/") :]
        file_path = frappe.get_site_path("private", "files", subpath)
    elif file_url.startswith("/files/"):
        subpath = file_url[len("/files/") :]
        file_path = frappe.get_site_path("public", "files", subpath)
    else:
        # Check if absolute path or bare filename
        if os.path.isabs(file_url):
            file_path = file_url
        else:
            file_path = frappe.get_site_path("private", "files", file_url)

    realpath = os.path.realpath(file_path)
    file_p = Path(realpath)
    private_root = Path(os.path.realpath(frappe.get_site_path("private", "files")))
    public_root = Path(os.path.realpath(frappe.get_site_path("public", "files")))

    def _is_component_contained(child: Path, root: Path) -> bool:
        try:
            return child.is_relative_to(root) and child != root
        except AttributeError:
            try:
                rel = child.relative_to(root)
                return str(rel) != "." and not str(rel).startswith("..")
            except ValueError:
                return False

    if not (_is_component_contained(file_p, private_root) or _is_component_contained(file_p, public_root)):
        frappe.throw("File path traversal outside site files is forbidden", frappe.PermissionError)

    if not os.path.exists(realpath):
        frappe.throw(f"File does not exist on disk: {file_url}", frappe.DoesNotExistError)

    return realpath


def assert_file_read_permission(file_name_or_url: str, user: str | None = None) -> None:
    """Verify that user has read permission on the underlying File document."""
    user = user or frappe.session.user
    if user == "Administrator" or is_system_manager(current_roles(user)):
        return

    if frappe.db.exists("File", file_name_or_url):
        file_doc = frappe.get_doc("File", file_name_or_url)
    else:
        matching = frappe.get_all("File", filters={"file_url": file_name_or_url}, pluck="name")
        if not matching:
            frappe.throw(f"File document '{file_name_or_url}' not found", frappe.DoesNotExistError)
        file_doc = frappe.get_doc("File", matching[0])

    if not frappe.has_permission("File", doc=file_doc, ptype="read", user=user):
        frappe.throw(f"Access denied to file '{file_name_or_url}'", frappe.PermissionError)


def assert_can_capture_evidence(evidence_doc: Any, user: str | None = None) -> None:
    """Ensure user has Approver or System Manager role and read access to Evidence."""
    user = user or frappe.session.user
    roles = permissions.current_roles(user)
    if user != "Administrator" and not permissions.is_system_manager(roles) and permissions.ROLE_APPROVER not in roles:
        frappe.throw(
            "Evidence capture requires Fresko Approver or System Manager role",
            frappe.PermissionError,
        )
    if not permissions.evidence_has_permission(evidence_doc, "read", user=user):
        frappe.throw("Access denied to Evidence", frappe.PermissionError)


def prove_ordinal_ordering(
    parent_row: dict | Any,
    ordinal_value: int,
    provenance_type: str,
    provenance_ref: str | None = None,
) -> tuple[bool, str | None]:
    """Prove that an ordinal attachment has verified stable ordering from the source.

    Missing identity never becomes ordinal zero; ordinal fallback requires
    verified stable ordering from manifest or provider transport payload.
    """
    if not isinstance(ordinal_value, int) or ordinal_value < 0:
        return False, f"Invalid ordinal value: {ordinal_value}"

    if provenance_type == "OFFLINE_IMPORT_MANIFEST":
        if not provenance_ref:
            return False, "Ordinal identity requires immutable manifest reference in provenance_ref"
        manifest_data = _load_manifest_data(provenance_ref)
        if manifest_data is None:
            return False, f"Cannot load offline manifest '{provenance_ref}' to verify ordinal ordering"
        items = _extract_manifest_items(manifest_data)
        ord_matches = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            item_ord = item.get("attachment_ordinal") if "attachment_ordinal" in item else item.get("ordinal")
            if item_ord is not None:
                if item_ord == ordinal_value:
                    ord_matches.append(item)
            elif idx == ordinal_value:
                ord_matches.append(item)

        if len(ord_matches) == 1:
            return True, None
        elif len(ord_matches) > 1:
            return False, f"Manifest contains ambiguous multiple entries ({len(ord_matches)}) for ordinal {ordinal_value}"
        else:
            return False, f"Manifest contains no verified entry establishing stable ordering for ordinal {ordinal_value}"

    elif provenance_type in ("PROVIDER_PAYLOAD_DIGEST", "PROVIDER_HEADER_CONTENT_LENGTH"):
        parent_name = getattr(parent_row, "name", None) or (
            parent_row.get("name") if hasattr(parent_row, "get") else None
        )
        parent_exp_count = (
            getattr(parent_row, "expected_attachment_count", None)
            if getattr(parent_row, "expected_attachment_count", None) is not None
            else (parent_row.get("expected_attachment_count") if hasattr(parent_row, "get") else None)
        )
        payload_data = _load_parent_payload(parent_name)

        candidates = []
        if isinstance(payload_data, dict):
            if "attachments" in payload_data and isinstance(payload_data["attachments"], list):
                candidates.extend(payload_data["attachments"])
            for media_key in ("document", "image", "video", "audio", "media"):
                if media_key in payload_data and isinstance(payload_data[media_key], dict):
                    candidates.append(payload_data[media_key])

            ord_matches = []
            for idx, c in enumerate(candidates):
                if not isinstance(c, dict):
                    continue
                c_ord = c.get("ordinal", idx)
                if c_ord == ordinal_value:
                    ord_matches.append(c)

            if len(ord_matches) == 1:
                return True, None
            elif len(ord_matches) > 1:
                return False, f"Provider transport payload contains ambiguous declarations ({len(ord_matches)}) for ordinal {ordinal_value}"
            elif len(candidates) == 1 and ordinal_value == 0:
                # Exactly one media candidate in provider payload proves ordinal 0
                return True, None

        if provenance_type == "PROVIDER_HEADER_CONTENT_LENGTH" and ordinal_value == 0:
            if parent_exp_count == 1 or len(candidates) == 1:
                return True, None

        return False, f"Provider transport does not establish verified stable ordering for ordinal {ordinal_value}"

    return False, f"Provenance type '{provenance_type}' cannot prove stable ordering for ordinal identity"


def validate_completeness_provenance(
    att_row: dict | Any, parent_row: dict | Any
) -> tuple[bool, str | None, int | None, str | None]:
    """Validate completeness provenance contract.

    Binds expected size and hash strictly to their immutable source and provenance record.
    Arbitrary API inputs cannot establish trusted completeness; caller fallback is disallowed.
    Ambiguous or conflicting matches are rejected.
    Unsupported or missing provenance remains UNKNOWN/PENDING.
    """
    prov_type = getattr(att_row, "provenance_type", None) or (
        att_row.get("provenance_type") if hasattr(att_row, "get") else None
    )
    prov_ref = getattr(att_row, "provenance_ref", None) or (
        att_row.get("provenance_ref") if hasattr(att_row, "get") else None
    )
    caller_bytes = getattr(att_row, "expected_byte_count", None) if getattr(att_row, "expected_byte_count", None) is not None else (
        att_row.get("expected_byte_count") if hasattr(att_row, "get") else None
    )
    caller_hash = getattr(att_row, "expected_sha256", None) or (
        att_row.get("expected_sha256") if hasattr(att_row, "get") else None
    )
    att_file_url = getattr(att_row, "file_url", None) or (
        att_row.get("file_url") if hasattr(att_row, "get") else None
    )
    att_id_type = getattr(att_row, "identity_type", None) or (
        att_row.get("identity_type") if hasattr(att_row, "get") else None
    )
    att_prov_id = getattr(att_row, "provider_attachment_id", None) or (
        att_row.get("provider_attachment_id") if hasattr(att_row, "get") else None
    )
    att_ordinal = getattr(att_row, "attachment_ordinal", None) if getattr(att_row, "attachment_ordinal", None) is not None else (
        att_row.get("attachment_ordinal") if hasattr(att_row, "get") else None
    )
    att_logical_key = getattr(att_row, "logical_attachment_key", None) or (
        att_row.get("logical_attachment_key") if hasattr(att_row, "get") else None
    )

    if not prov_type or prov_type not in TRUSTED_PROVENANCE_TYPES:
        return (
            False,
            f"Provenance '{prov_type}' is unverified or untrusted; cannot establish completeness",
            None,
            None,
        )

    # Prove ordinal ordering if identity is ordinal
    if att_id_type == "ordinal":
        if att_ordinal is None:
            return False, "Ordinal identity requires non-null attachment_ordinal", None, None
        proved, ord_err = prove_ordinal_ordering(parent_row, int(att_ordinal), prov_type, prov_ref)
        if not proved:
            return False, ord_err, None, None

    file_basename = os.path.basename(att_file_url) if att_file_url else ""

    if prov_type == "OFFLINE_IMPORT_MANIFEST":
        if not prov_ref or not str(prov_ref).strip():
            return (
                False,
                "Offline import provenance requires an immutable manifest reference in provenance_ref",
                None,
                None,
            )

        manifest_data = _load_manifest_data(prov_ref)
        if manifest_data is None:
            return (
                False,
                f"Offline import manifest '{prov_ref}' could not be verified or located",
                None,
                None,
            )

        items = _extract_manifest_items(manifest_data)
        matching_entries: list[dict] = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            entry_name = entry.get("file_name") or entry.get("file") or entry.get("archive_member") or entry.get("name")
            entry_key = entry.get("logical_attachment_key") or entry.get("key")
            entry_prov_id = entry.get("provider_attachment_id") or entry.get("id")
            entry_ord = entry.get("attachment_ordinal") if "attachment_ordinal" in entry else entry.get("ordinal")

            matches = False
            if att_logical_key and entry_key and entry_key == att_logical_key:
                matches = True
            elif att_prov_id and entry_prov_id and str(entry_prov_id) == str(att_prov_id):
                matches = True
            elif att_id_type == "ordinal" and entry_ord is not None and entry_ord == att_ordinal:
                matches = True
            elif entry_name and file_basename and (
                entry_name == file_basename or os.path.basename(str(entry_name)) == file_basename
            ):
                matches = True
            elif entry_name and att_file_url and str(entry_name) == str(att_file_url):
                matches = True

            if matches:
                matching_entries.append(entry)

        if not matching_entries:
            return (
                False,
                f"Offline manifest '{prov_ref}' contains no verified entry for this attachment",
                None,
                None,
            )

        if len(matching_entries) > 1:
            return (
                False,
                f"Offline manifest '{prov_ref}' contains ambiguous conflicting matches ({len(matching_entries)}) for this attachment",
                None,
                None,
            )

        found_entry = matching_entries[0]
        bound_bytes = (
            found_entry.get("expected_byte_count")
            or found_entry.get("size_bytes")
            or found_entry.get("size")
            or found_entry.get("byte_count")
            or found_entry.get("content_byte_count")
        )
        bound_hash = (
            found_entry.get("expected_sha256")
            or found_entry.get("sha256")
            or found_entry.get("content_sha256")
            or found_entry.get("hash")
        )

        if bound_bytes is None and bound_hash is None:
            return (
                False,
                f"Manifest entry for attachment '{file_basename}' provides neither expected size nor hash",
                None,
                None,
            )

        # Enforce source-bound expectations: reject conflicting or unsupported caller assertions
        if caller_bytes is not None and caller_bytes > -1:
            if bound_bytes is None:
                return (
                    False,
                    "Manifest entry does not declare expected byte count; caller fallback is disallowed",
                    None,
                    None,
                )
            if caller_bytes != bound_bytes:
                return (
                    False,
                    f"Caller expected byte count ({caller_bytes}) conflicts with manifest declared count ({bound_bytes})",
                    None,
                    None,
                )

        if caller_hash:
            if bound_hash is None:
                return (
                    False,
                    "Manifest entry does not declare expected sha256; caller fallback is disallowed",
                    None,
                    None,
                )
            if caller_hash != bound_hash:
                return (
                    False,
                    f"Caller expected hash ({caller_hash}) conflicts with manifest declared hash ({bound_hash})",
                    None,
                    None,
                )

        return True, None, bound_bytes, bound_hash

    elif prov_type in ("PROVIDER_PAYLOAD_DIGEST", "PROVIDER_HEADER_CONTENT_LENGTH"):
        parent_hash = getattr(parent_row, "message_payload_sha256", None) or (
            parent_row.get("message_payload_sha256") if hasattr(parent_row, "get") else None
        )
        parent_ev_name = getattr(parent_row, "name", None) or (
            parent_row.get("name") if hasattr(parent_row, "get") else None
        )

        if not parent_hash and not prov_ref:
            return (
                False,
                "Provider delivery provenance lacks bound parent payload or ingest attempt reference",
                None,
                None,
            )

        payload_data = _load_parent_payload(parent_ev_name)
        candidates: list[dict] = []
        if isinstance(payload_data, dict):
            if "attachments" in payload_data and isinstance(payload_data["attachments"], list):
                candidates.extend(payload_data["attachments"])
            for media_key in ("document", "image", "video", "audio", "media"):
                if media_key in payload_data and isinstance(payload_data[media_key], dict):
                    candidates.append(payload_data[media_key])

        matching_decls: list[dict] = []
        for idx, c in enumerate(candidates):
            if not isinstance(c, dict):
                continue
            c_id = c.get("id") or c.get("provider_attachment_id")
            c_ord = c.get("ordinal", idx)
            c_fn = c.get("filename") or c.get("file_name")
            if att_prov_id and c_id and str(c_id) == str(att_prov_id):
                matching_decls.append(c)
            elif att_id_type == "ordinal" and att_ordinal is not None and c_ord == att_ordinal:
                matching_decls.append(c)
            elif file_basename and c_fn and (c_fn == file_basename or os.path.basename(str(c_fn)) == file_basename):
                matching_decls.append(c)

        if len(matching_decls) > 1:
            return (
                False,
                f"Provider transport payload contains ambiguous conflicting declarations ({len(matching_decls)}) for this attachment",
                None,
                None,
            )

        found_decl = None
        if len(matching_decls) == 1:
            found_decl = matching_decls[0]
        elif len(candidates) == 1 and not att_prov_id and (att_ordinal is None or att_ordinal == 0):
            found_decl = candidates[0]

        if not found_decl:
            # Check ref attempts
            attempt_rows = frappe.db.sql(
                """
                SELECT name, evidence_attachment, observed_byte_count, observed_sha256
                FROM `tabFresko Evidence Attempt`
                WHERE evidence = %s AND operation IN ('MESSAGE_INGEST', 'ATTACHMENT_INGEST')
                ORDER BY creation DESC
                """,
                (parent_ev_name,),
                as_dict=True,
            )
            att_name = getattr(att_row, "name", None) or (att_row.get("name") if hasattr(att_row, "get") else None)
            ref_attempts = [
                a for a in attempt_rows
                if (prov_ref and (getattr(a, "name", None) or (a.get("name") if hasattr(a, "get") else None)) == prov_ref)
                or (att_name and (getattr(a, "evidence_attachment", None) or (a.get("evidence_attachment") if hasattr(a, "get") else None)) == att_name)
            ]
            if ref_attempts:
                ref_a = ref_attempts[0]
                obc = getattr(ref_a, "observed_byte_count", None) or (ref_a.get("observed_byte_count") if hasattr(ref_a, "get") else None)
                osh = getattr(ref_a, "observed_sha256", None) or (ref_a.get("observed_sha256") if hasattr(ref_a, "get") else None)
                if obc or osh:
                    found_decl = {
                        "byte_count": obc,
                        "sha256": osh,
                    }

        if not found_decl:
            return (
                False,
                "Provider transport payload/attempt does not contain expected length/hash declarations for this attachment",
                None,
                None,
            )

        bound_bytes = (
            found_decl.get("file_size")
            or found_decl.get("byte_count")
            or found_decl.get("size")
            or found_decl.get("expected_byte_count")
        )
        bound_hash = (
            found_decl.get("sha256")
            or found_decl.get("digest")
            or found_decl.get("expected_sha256")
        )

        if prov_type == "PROVIDER_PAYLOAD_DIGEST" and not bound_hash:
            return (
                False,
                "Provider payload digest provenance requires source sha256; caller fallback is disallowed",
                None,
                None,
            )

        if bound_bytes is None and bound_hash is None:
            return (
                False,
                "Provider declaration provides neither expected size nor hash",
                None,
                None,
            )

        # Enforce source-bound expectations: reject conflicting caller assertions
        if caller_bytes is not None and caller_bytes > -1:
            if bound_bytes is None:
                return (
                    False,
                    "Provider payload does not declare expected byte count; caller fallback is disallowed",
                    None,
                    None,
                )
            if caller_bytes != bound_bytes:
                return (
                    False,
                    f"Caller expected byte count ({caller_bytes}) conflicts with provider declared count ({bound_bytes})",
                    None,
                    None,
                )

        if caller_hash:
            if bound_hash is None:
                return (
                    False,
                    "Provider payload does not declare expected sha256; caller fallback is disallowed",
                    None,
                    None,
                )
            if caller_hash != bound_hash:
                return (
                    False,
                    f"Caller expected hash ({caller_hash}) conflicts with provider declared hash ({bound_hash})",
                    None,
                    None,
                )

        return True, None, bound_bytes, bound_hash

    return False, f"Unsupported provenance type: {prov_type}", None, None



def ingest_message_evidence(
    provider: str | None = None,
    provider_account_id: str | None = None,
    conversation_id: str | None = None,
    provider_message_id: str | None = None,
    raw_payload: Any = None,
    deal: str | None = None,
    container: str | None = None,
    notes: str | None = None,
    manifest_status: str = "UNKNOWN",
    expected_attachment_count: int = -1,
) -> tuple[Any, str]:
    """Service method for idempotent message evidence creation.

    Uses savepoint-isolated insert to catch UniqueValidationError on scoped_message_key.
    Performs locking read, collision checks, payload conflict preservation,
    and inherited permission checks.
    """
    canonical_payload_str, payload_sha = canonicalize_payload(raw_payload)
    scoped_key = compute_scoped_message_key(
        provider, provider_account_id, conversation_id, provider_message_id
    )

    doc = frappe.new_doc("Fresko Evidence")
    doc.flags.in_service = True
    doc.evidence_type = "WhatsApp Message" if provider == "whatsapp-cloud" else "Note"
    doc.deal = deal
    doc.container = container
    doc.notes = notes
    doc.provider = provider
    doc.provider_account_id = provider_account_id
    doc.conversation_id = conversation_id
    doc.provider_message_id = provider_message_id
    doc.scoped_message_key = scoped_key
    doc.message_payload_sha256 = payload_sha
    doc.manifest_status = manifest_status
    doc.expected_attachment_count = expected_attachment_count
    doc.verified_attachment_count = 0
    doc.overall_verification_status = "PENDING"

    if not scoped_key:
        # Legacy or unresolved identity: normal insert
        doc.insert()
        _record_attempt(
            evidence=doc.name,
            operation="MESSAGE_INGEST",
            outcome="SUCCESS_NEW",
            payload_sha256=payload_sha,
            source_payload=canonical_payload_str,
            reason="New evidence inserted without scoped message key",
        )
        return doc, "SUCCESS_NEW"

    # Savepoint-isolated insert for scoped key
    sp = "sp_ev_" + frappe.generate_hash(length=8)
    frappe.db.savepoint(sp)
    try:
        doc.insert()
        frappe.db.release_savepoint(sp)
        _record_attempt(
            evidence=doc.name,
            operation="MESSAGE_INGEST",
            outcome="SUCCESS_NEW",
            scoped_message_key=scoped_key,
            payload_sha256=payload_sha,
            source_payload=canonical_payload_str,
            reason="New scoped message evidence ingested successfully",
        )
        return doc, "SUCCESS_NEW"
    except frappe.UniqueValidationError:
        frappe.db.rollback(save_point=sp)

        # Locking read on existing record
        existing_rows = frappe.db.sql(
            """
            SELECT name, deal, provider, provider_account_id, conversation_id,
                   provider_message_id, scoped_message_key, message_payload_sha256,
                   overall_verification_status
            FROM `tabFresko Evidence`
            WHERE scoped_message_key = %s
            FOR UPDATE
            """,
            (scoped_key,),
            as_dict=True,
        )
        if not existing_rows:
            raise

        existing = existing_rows[0]

        # 1. Permission check FIRST: never expose existing record merely because key matches
        if not permissions.evidence_has_permission(existing.name, "read", user=frappe.session.user):
            _record_attempt(
                evidence=existing.name,
                operation="MESSAGE_INGEST",
                outcome="ACCESS_DENIED",
                scoped_message_key=scoped_key,
                payload_sha256=payload_sha,
                reason="Caller lacks permission to access existing evidence on redelivery",
                isolated=True,
            )
            frappe.throw("Access denied", frappe.PermissionError)

        # 2. Collision check: all 4 original scope fields must match exactly
        scope_matches = (
            existing.provider == provider
            and existing.provider_account_id == provider_account_id
            and existing.conversation_id == conversation_id
            and existing.provider_message_id == provider_message_id
        )
        if not scope_matches:
            _record_attempt(
                evidence=existing.name,
                operation="MESSAGE_INGEST",
                outcome="CONFLICT_KEY_COLLISION",
                scoped_message_key=scoped_key,
                payload_sha256=payload_sha,
                source_payload=canonical_payload_str,
                reason=f"Key collision: scope fields do not match existing row {existing.name}",
                isolated=True,
            )
            raise IntegrityConflictError(
                f"Scoped message key collision detected on evidence {existing.name}",
            )

        # 3. Payload conflict check
        if existing.message_payload_sha256 and existing.message_payload_sha256 != payload_sha:
            frappe.db.set_value(
                "Fresko Evidence",
                existing.name,
                "overall_verification_status",
                "CONFLICT",
                update_modified=False,
            )
            _record_attempt(
                evidence=existing.name,
                operation="MESSAGE_INGEST",
                outcome="CONFLICT_PAYLOAD_MISMATCH",
                scoped_message_key=scoped_key,
                payload_sha256=payload_sha,
                existing_payload_sha256=existing.message_payload_sha256,
                source_payload=canonical_payload_str,
                reason="Conflicting payload received for existing scoped message key",
                isolated=True,
            )
            return frappe.get_doc("Fresko Evidence", existing.name), "CONFLICT_PAYLOAD_MISMATCH"

        # 4. Idempotent redelivery
        _record_attempt(
            evidence=existing.name,
            operation="MESSAGE_INGEST",
            outcome="SUCCESS_IDEMPOTENT_REDELIVERY",
            scoped_message_key=scoped_key,
            payload_sha256=payload_sha,
            reason="Idempotent duplicate message delivery accepted",
        )
        return frappe.get_doc("Fresko Evidence", existing.name), "SUCCESS_IDEMPOTENT_REDELIVERY"


def ingest_attachment(
    evidence_name: str,
    file_url: str,
    identity_type: str,
    identity_value: str | int,
    provenance_type: str = "MISSING_PROVENANCE",
    provenance_ref: str | None = None,
    expected_byte_count: int = -1,
    expected_sha256: str | None = None,
) -> tuple[Any, str]:
    """Ingest a logical attachment linked to a parent Fresko Evidence row.

    Parent-first lock is acquired before checking or writing child records.
    """
    parent = _lock_parent_evidence(evidence_name)

    # Permission check on parent and file
    if not permissions.evidence_has_permission(evidence_name, "write", user=frappe.session.user):
        frappe.throw("Access denied to create attachment for Evidence", frappe.PermissionError)
    assert_file_read_permission(file_url)

    logical_key = compute_logical_attachment_key(
        parent.provider,
        parent.provider_account_id,
        parent.conversation_id,
        parent.provider_message_id,
        identity_type,
        identity_value,
    )

    # Check if a current version of this logical attachment already exists
    existing_att = frappe.db.sql(
        """
        SELECT name, file_url, content_sha256, capture_status, version, logical_attachment_key,
               provenance_type, provenance_ref, expected_byte_count, expected_sha256
        FROM `tabFresko Evidence Attachment`
        WHERE evidence = %s AND logical_attachment_key = %s AND is_current_version = 1
        FOR UPDATE
        """,
        (evidence_name, logical_key),
        as_dict=True,
    )

    if existing_att:
        curr = existing_att[0]
        # Permission check: caller must have read permission on parent to access existing attachment
        if not permissions.evidence_has_permission(evidence_name, "read", user=frappe.session.user):
            _record_attempt(
                evidence=evidence_name,
                evidence_attachment=curr.name,
                operation="ATTACHMENT_INGEST",
                outcome="ACCESS_DENIED",
                logical_attachment_key=logical_key,
                reason="Caller lacks read permission for existing attachment on redelivery",
                isolated=True,
            )
            frappe.throw("Access denied", frappe.PermissionError)

        curr_prov_type = getattr(curr, "provenance_type", None) or (curr.get("provenance_type") if hasattr(curr, "get") else None)
        curr_prov_ref = getattr(curr, "provenance_ref", None) or (curr.get("provenance_ref") if hasattr(curr, "get") else None)
        curr_exp_bytes = getattr(curr, "expected_byte_count", None) if getattr(curr, "expected_byte_count", None) is not None else (curr.get("expected_byte_count") if hasattr(curr, "get") else None)
        curr_exp_sha = getattr(curr, "expected_sha256", None) or (curr.get("expected_sha256") if hasattr(curr, "get") else None)
        curr_file_url = getattr(curr, "file_url", None) or (curr.get("file_url") if hasattr(curr, "get") else None)
        curr_sha = getattr(curr, "content_sha256", None) or (curr.get("content_sha256") if hasattr(curr, "get") else None)

        prov_match = (
            curr_prov_type == provenance_type
            and (curr_prov_ref == provenance_ref or not provenance_ref)
            and (expected_byte_count == -1 or curr_exp_bytes == expected_byte_count)
            and (expected_sha256 is None or curr_exp_sha == expected_sha256)
        )

        # Replay content check: ALWAYS read disk bytes and verify SHA-256 against existing attachment
        # even if curr_file_url == file_url
        content_match = False
        try:
            new_path = get_validated_local_file_path(file_url)
            with open(new_path, "rb") as nf:
                replay_bytes = nf.read()
            replay_hash = hashlib.sha256(replay_bytes).hexdigest()
            replay_len = len(replay_bytes)

            if curr_sha:
                content_match = (replay_hash == curr_sha)
            elif curr_exp_sha:
                content_match = (replay_hash == curr_exp_sha)
            elif curr_exp_bytes is not None and curr_exp_bytes > -1:
                content_match = (replay_len == curr_exp_bytes and curr_file_url == file_url)
            else:
                content_match = (curr_file_url == file_url)
        except Exception:
            content_match = False

        if prov_match and content_match:
            _record_attempt(
                evidence=evidence_name,
                evidence_attachment=curr.name,
                operation="ATTACHMENT_INGEST",
                outcome="SUCCESS_IDEMPOTENT_REDELIVERY",
                logical_attachment_key=logical_key,
                reason="Idempotent attachment replay with verified content and provenance match",
            )
            return frappe.get_doc("Fresko Evidence Attachment", curr.name), "SUCCESS_IDEMPOTENT_REDELIVERY"
        else:
            reason = "New file or conflicting provenance submitted for existing logical attachment without correction flow"
            _record_attempt(
                evidence=evidence_name,
                evidence_attachment=curr.name,
                operation="ATTACHMENT_INGEST",
                outcome="CONFLICT_PAYLOAD_MISMATCH",
                logical_attachment_key=logical_key,
                reason=reason,
                isolated=True,
            )
            frappe.throw(
                f"Logical attachment '{curr.name}' already exists with different content/provenance; use supersede_attachment",
                frappe.ValidationError,
            )

    # Ordinal identity check: ordinal identity requires verified stable-ordering provenance
    if identity_type == "ordinal":
        proved, ord_err = prove_ordinal_ordering(parent, int(identity_value), provenance_type, provenance_ref)
        if not proved:
            _record_attempt(
                evidence=evidence_name,
                operation="ATTACHMENT_INGEST",
                outcome="VALIDATION_FAILED",
                logical_attachment_key=logical_key,
                reason=ord_err,
                isolated=True,
            )
            frappe.throw(
                ord_err or "Ordinal identity requires verified stable-ordering provenance",
                frappe.ValidationError,
            )

    # Create version 1
    version = 1
    version_key = compute_scoped_attachment_version_key(logical_key, version)

    att = frappe.new_doc("Fresko Evidence Attachment")
    att.flags.in_service = True
    att.evidence = evidence_name
    att.provider = parent.provider
    att.provider_account_id = parent.provider_account_id
    att.conversation_id = parent.conversation_id
    att.provider_message_id = parent.provider_message_id
    att.identity_type = identity_type
    if identity_type == "provider_id":
        att.provider_attachment_id = str(identity_value)
    else:
        att.attachment_ordinal = int(identity_value)
    att.logical_attachment_key = logical_key
    att.version = version
    att.scoped_attachment_version_key = version_key
    att.file = file_url
    att.file_url = file_url
    att.provenance_type = provenance_type
    att.provenance_ref = provenance_ref
    att.expected_byte_count = expected_byte_count
    att.expected_sha256 = expected_sha256
    att.capture_status = "PENDING"
    att.is_current_version = 1
    att.is_superseded = 0
    att.insert()

    # Mark parent as having attachments
    frappe.db.set_value("Fresko Evidence", evidence_name, "has_attachments", 1, update_modified=False)

    _record_attempt(
        evidence=evidence_name,
        evidence_attachment=att.name,
        operation="ATTACHMENT_INGEST",
        outcome="SUCCESS_NEW",
        logical_attachment_key=logical_key,
        scoped_attachment_version_key=version_key,
        reason="Logical attachment version 1 ingested successfully",
    )

    aggregate_parent_evidence_status(evidence_name)
    return att, "SUCCESS_NEW"


def verify_and_capture_attachment(attachment_name: str) -> CaptureResult:
    """Verify attachment bytes, validate completeness provenance, and capture atomically.

    Adheres strictly to:
    - Parent-first lock order.
    - Double raw binary disk read (bypassing File.get_content() string decoding).
    - Trusted completeness provenance validation.
    - Compare-and-set idempotency on repeated verification.
    """
    # 1. Look up parent Evidence first and acquire parent-first lock FOR UPDATE
    parent_evidence_rows = frappe.db.sql(
        "SELECT evidence FROM `tabFresko Evidence Attachment` WHERE name = %s",
        (attachment_name,),
        as_dict=True,
    )
    if not parent_evidence_rows:
        frappe.throw(f"Attachment '{attachment_name}' not found", frappe.DoesNotExistError)

    parent_name = (
        parent_evidence_rows[0].evidence
        if hasattr(parent_evidence_rows[0], "evidence")
        else parent_evidence_rows[0].get("evidence")
    )
    parent = _lock_parent_evidence(parent_name)

    # 2. Lock child attachment row second
    att_rows = frappe.db.sql(
        """
        SELECT name, evidence, file_url, storage_ref, provenance_type, provenance_ref,
               expected_byte_count, expected_sha256, capture_status, readback_verified,
               content_sha256, content_byte_count, logical_attachment_key,
               scoped_attachment_version_key, is_current_version, is_superseded
        FROM `tabFresko Evidence Attachment`
        WHERE name = %s
        FOR UPDATE
        """,
        (attachment_name,),
        as_dict=True,
    )
    if not att_rows:
        frappe.throw(f"Attachment '{attachment_name}' not found", frappe.DoesNotExistError)

    att = att_rows[0]

    # Guard against verifying superseded versions (Finding 2)
    if (
        getattr(att, "is_superseded", 0) == 1
        or getattr(att, "capture_status", None) == "SUPERSEDED"
        or getattr(att, "is_current_version", 1) == 0
    ):
        return CaptureResult(
            success=False,
            status="SUPERSEDED",
            reason="Attachment has been superseded by a newer version and cannot be verified or captured",
        )

    # 2. Authority and access check
    parent_doc = frappe.get_doc("Fresko Evidence", parent.name)
    assert_can_capture_evidence(parent_doc)
    assert_file_read_permission(att.file_url)

    # 3. Compare-and-set serialization: if already CAPTURED and verified, return existing
    if att.capture_status == "CAPTURED" and att.readback_verified:
        return CaptureResult(
            success=True,
            status="CAPTURED",
            content_sha256=att.content_sha256,
            content_byte_count=att.content_byte_count,
            reason="Already verified and captured",
        )

    # 4. Check completeness provenance contract
    is_trusted, prov_reason, bound_bytes, bound_hash = validate_completeness_provenance(att, parent)
    if not is_trusted:
        _record_attempt(
            evidence=parent.name,
            evidence_attachment=att.name,
            operation="ATTACHMENT_VERIFY",
            outcome="VERIFICATION_FAILURE_PERMANENT",
            logical_attachment_key=att.logical_attachment_key,
            reason=prov_reason,
        )
        return CaptureResult(success=False, status="PENDING", reason=prov_reason)

    # 5. Transition to VERIFYING
    frappe.db.set_value(
        "Fresko Evidence Attachment", att.name, "capture_status", "VERIFYING", update_modified=False
    )

    # 6. Read actual persisted binary bytes directly from disk
    try:
        disk_path = get_validated_local_file_path(att.file_url)
        with open(disk_path, "rb") as f:
            read1 = f.read()
        with open(disk_path, "rb") as f:
            read2 = f.read()
    except Exception as e:
        frappe.db.set_value(
            "Fresko Evidence Attachment",
            att.name,
            {"capture_status": "FAILED_RETRYABLE", "failure_reason": str(e)},
            update_modified=False,
        )
        _record_attempt(
            evidence=parent.name,
            evidence_attachment=att.name,
            operation="ATTACHMENT_VERIFY",
            outcome="FAILED_STORAGE",
            reason=f"Storage read error: {e}",
        )
        aggregate_parent_evidence_status(parent.name)
        return CaptureResult(success=False, status="FAILED_RETRYABLE", reason=str(e))

    # Double read consistency check
    if read1 != read2:
        frappe.db.set_value(
            "Fresko Evidence Attachment",
            att.name,
            {
                "capture_status": "FAILED_RETRYABLE",
                "failure_reason": "Torn or inconsistent disk read detected",
            },
            update_modified=False,
        )
        _record_attempt(
            evidence=parent.name,
            evidence_attachment=att.name,
            operation="ATTACHMENT_VERIFY",
            outcome="VERIFICATION_FAILURE_RETRYABLE",
            observed_byte_count=len(read1),
            reason="Disk read consistency check failed",
        )
        aggregate_parent_evidence_status(parent.name)
        return CaptureResult(
            success=False,
            status="FAILED_RETRYABLE",
            reason="Disk read consistency check failed",
        )

    byte_count = len(read1)
    computed_sha256 = hashlib.sha256(read1).hexdigest()

    # 7. Check transport completeness against validated source-bound expected size/hash
    expected_bytes = bound_bytes if bound_bytes is not None else att.expected_byte_count
    expected_hash = bound_hash if bound_hash else att.expected_sha256
    if expected_bytes is not None and expected_bytes > -1:
        if byte_count < expected_bytes:
            reason = f"Partial file: read {byte_count} bytes, expected {expected_bytes}"
            frappe.db.set_value(
                "Fresko Evidence Attachment",
                att.name,
                {"capture_status": "PARTIAL", "failure_reason": reason},
                update_modified=False,
            )
            _record_attempt(
                evidence=parent.name,
                evidence_attachment=att.name,
                operation="ATTACHMENT_VERIFY",
                outcome="VERIFICATION_PARTIAL_BYTES",
                observed_byte_count=byte_count,
                observed_sha256=computed_sha256,
                reason=reason,
            )
            aggregate_parent_evidence_status(parent.name)
            return CaptureResult(
                success=False,
                status="PARTIAL",
                content_byte_count=byte_count,
                content_sha256=computed_sha256,
                reason=reason,
            )
        elif byte_count > expected_bytes:
            reason = f"Byte length overflow: read {byte_count} bytes, expected {expected_bytes}"
            frappe.db.set_value(
                "Fresko Evidence Attachment",
                att.name,
                {"capture_status": "HASH_MISMATCH", "failure_reason": reason},
                update_modified=False,
            )
            _record_attempt(
                evidence=parent.name,
                evidence_attachment=att.name,
                operation="ATTACHMENT_VERIFY",
                outcome="VERIFICATION_HASH_MISMATCH",
                observed_byte_count=byte_count,
                observed_sha256=computed_sha256,
                reason=reason,
            )
            aggregate_parent_evidence_status(parent.name)
            return CaptureResult(success=False, status="HASH_MISMATCH", reason=reason)

    if expected_hash:
        if computed_sha256 != expected_hash:
            reason = f"Hash mismatch: computed {computed_sha256}, expected {expected_hash}"
            frappe.db.set_value(
                "Fresko Evidence Attachment",
                att.name,
                {"capture_status": "HASH_MISMATCH", "failure_reason": reason},
                update_modified=False,
            )
            _record_attempt(
                evidence=parent.name,
                evidence_attachment=att.name,
                operation="ATTACHMENT_VERIFY",
                outcome="VERIFICATION_HASH_MISMATCH",
                observed_byte_count=byte_count,
                observed_sha256=computed_sha256,
                reason=reason,
            )
            aggregate_parent_evidence_status(parent.name)
            return CaptureResult(success=False, status="HASH_MISMATCH", reason=reason)

    # Empty file check: zero-byte file without expected count 0 is retryable failure
    if byte_count == 0 and (expected_bytes is None or expected_bytes != 0):
        reason = "Zero-byte file without explicit zero-length expectation"
        frappe.db.set_value(
            "Fresko Evidence Attachment",
            att.name,
            {"capture_status": "FAILED_RETRYABLE", "failure_reason": reason},
            update_modified=False,
        )
        _record_attempt(
            evidence=parent.name,
            evidence_attachment=att.name,
            operation="ATTACHMENT_VERIFY",
            outcome="VERIFICATION_FAILURE_RETRYABLE",
            observed_byte_count=0,
            reason=reason,
        )
        aggregate_parent_evidence_status(parent.name)
        return CaptureResult(success=False, status="FAILED_RETRYABLE", reason=reason)

    # 8. All verification invariants passed -> mark CAPTURED atomically with savepoint isolation
    sp = "sp_att_cap_" + frappe.generate_hash(length=8)
    frappe.db.savepoint(sp)
    try:
        frappe.db.set_value(
            "Fresko Evidence Attachment",
            att.name,
            {
                "content_byte_count": byte_count,
                "content_sha256": computed_sha256,
                "hash_algorithm": HASH_ALGORITHM_SHA256_V1,
                "capture_status": "CAPTURED",
                "readback_verified": 1,
                "failure_reason": None,
            },
            update_modified=False,
        )
        frappe.db.release_savepoint(sp)
    except Exception as e:
        frappe.db.rollback(save_point=sp)
        write_err = None
        try:
            frappe.db.set_value(
                "Fresko Evidence Attachment",
                att.name,
                {
                    "capture_status": "FAILED_RETRYABLE",
                    "failure_reason": f"Database write failed during capture finalization: {e}",
                },
                update_modified=False,
            )
        except Exception as we:
            write_err = we

        _record_attempt(
            evidence=parent.name,
            evidence_attachment=att.name,
            operation="ATTACHMENT_VERIFY",
            outcome="FAILED_DB_WRITE",
            logical_attachment_key=att.logical_attachment_key,
            scoped_attachment_version_key=att.scoped_attachment_version_key,
            observed_byte_count=byte_count,
            observed_sha256=computed_sha256,
            reason=f"Database write failed during capture finalization: {e}"
            + (f"; persisting failure status failed: {write_err}" if write_err else ""),
            isolated=True,
        )

        if write_err is not None:
            # Never claim a persisted failure status after swallowing its write failure
            raise write_err

        aggregate_parent_evidence_status(parent.name)
        return CaptureResult(
            success=False,
            status="FAILED_RETRYABLE",
            reason=f"Database write failed: {e}",
        )

    _record_attempt(
        evidence=parent.name,
        evidence_attachment=att.name,
        operation="ATTACHMENT_VERIFY",
        outcome="VERIFICATION_SUCCESS",
        logical_attachment_key=att.logical_attachment_key,
        scoped_attachment_version_key=att.scoped_attachment_version_key,
        observed_byte_count=byte_count,
        observed_sha256=computed_sha256,
        reason="Attachment verified and captured with byte-hash readback",
    )

    aggregate_parent_evidence_status(parent.name)
    return CaptureResult(
        success=True,
        status="CAPTURED",
        content_sha256=computed_sha256,
        content_byte_count=byte_count,
    )


def supersede_attachment(
    attachment_name: str,
    new_file_url: str,
    reason: str,
    provenance_type: str = "MISSING_PROVENANCE",
    provenance_ref: str | None = None,
    expected_byte_count: int = -1,
    expected_sha256: str | None = None,
) -> Any:
    """Correct an attachment by superseding it with a new immutable version.

    Preserves logical attachment identity without synthesizing new ordinals.
    """
    if not reason or not str(reason).strip():
        frappe.throw("A justification reason is mandatory for corrections", frappe.ValidationError)

    # Parent-first lock: look up parent Evidence first and acquire parent-first lock FOR UPDATE
    parent_evidence_rows = frappe.db.sql(
        "SELECT evidence FROM `tabFresko Evidence Attachment` WHERE name = %s",
        (attachment_name,),
        as_dict=True,
    )
    if not parent_evidence_rows:
        frappe.throw(f"Attachment '{attachment_name}' not found", frappe.DoesNotExistError)

    parent_name = (
        parent_evidence_rows[0].evidence
        if hasattr(parent_evidence_rows[0], "evidence")
        else parent_evidence_rows[0].get("evidence")
    )
    parent = _lock_parent_evidence(parent_name)

    # Lock child attachment row second
    att_rows = frappe.db.sql(
        """
        SELECT name, evidence, provider, provider_account_id, conversation_id,
               provider_message_id, identity_type, provider_attachment_id,
               attachment_ordinal, logical_attachment_key, version,
               is_current_version, is_superseded
        FROM `tabFresko Evidence Attachment`
        WHERE name = %s
        FOR UPDATE
        """,
        (attachment_name,),
        as_dict=True,
    )
    if not att_rows:
        frappe.throw(f"Attachment '{attachment_name}' not found", frappe.DoesNotExistError)

    old_att = att_rows[0]

    # Permission check: Approver or System Manager only
    parent_doc = frappe.get_doc("Fresko Evidence", parent.name)
    assert_can_capture_evidence(parent_doc)
    assert_file_read_permission(new_file_url)

    if old_att.is_superseded:
        frappe.throw("Attachment has already been superseded", frappe.ValidationError)

    new_version = old_att.version + 1
    new_version_key = compute_scoped_attachment_version_key(
        old_att.logical_attachment_key, new_version
    )

    # Insert replacement version
    new_doc = frappe.new_doc("Fresko Evidence Attachment")
    new_doc.flags.in_service = True
    new_doc.evidence = old_att.evidence
    new_doc.provider = old_att.provider
    new_doc.provider_account_id = old_att.provider_account_id
    new_doc.conversation_id = old_att.conversation_id
    new_doc.provider_message_id = old_att.provider_message_id
    new_doc.identity_type = old_att.identity_type
    new_doc.provider_attachment_id = old_att.provider_attachment_id
    new_doc.attachment_ordinal = old_att.attachment_ordinal
    new_doc.logical_attachment_key = old_att.logical_attachment_key
    new_doc.version = new_version
    new_doc.scoped_attachment_version_key = new_version_key
    new_doc.file = new_file_url
    new_doc.file_url = new_file_url
    new_doc.provenance_type = provenance_type
    new_doc.provenance_ref = provenance_ref
    new_doc.expected_byte_count = expected_byte_count
    new_doc.expected_sha256 = expected_sha256
    new_doc.capture_status = "PENDING"
    new_doc.is_current_version = 1
    new_doc.is_superseded = 0
    new_doc.insert()

    # Mark old version superseded
    frappe.db.set_value(
        "Fresko Evidence Attachment",
        old_att.name,
        {
            "is_current_version": 0,
            "is_superseded": 1,
            "superseded_by": new_doc.name,
            "capture_status": "SUPERSEDED",
        },
        update_modified=False,
    )

    _record_attempt(
        evidence=parent.name,
        evidence_attachment=new_doc.name,
        operation="CORRECTION_SUPERSEDE",
        outcome="SUCCESS_NEW",
        logical_attachment_key=old_att.logical_attachment_key,
        scoped_attachment_version_key=new_version_key,
        old_doc_ref=old_att.name,
        new_doc_ref=new_doc.name,
        reason=reason,
    )

    aggregate_parent_evidence_status(parent.name)
    return new_doc


def aggregate_parent_evidence_status(evidence_name: str) -> str:
    """Parent-first locked aggregation of parent Evidence status.

    Evaluates only current accepted versions (is_current_version = 1).
    COMPLETE strictly requires manifest_status == 'FINALIZED' and every
    expected logical attachment verified.
    """
    parent = _lock_parent_evidence(evidence_name)

    if parent.overall_verification_status == "CONFLICT":
        return "CONFLICT"

    # Query only current versions
    attachments = frappe.db.sql(
        """
        SELECT name, logical_attachment_key, capture_status, readback_verified
        FROM `tabFresko Evidence Attachment`
        WHERE evidence = %s AND is_current_version = 1
        ORDER BY name ASC
        LOCK IN SHARE MODE
        """,
        (evidence_name,),
        as_dict=True,
    )

    has_conflict = any(a.capture_status == "CONFLICT" for a in attachments)
    if has_conflict:
        frappe.db.set_value(
            "Fresko Evidence",
            evidence_name,
            "overall_verification_status",
            "CONFLICT",
            update_modified=False,
        )
        return "CONFLICT"

    has_failing = any(
        getattr(a, "capture_status", None) in ("PARTIAL", "HASH_MISMATCH", "FAILED_PERMANENT")
        for a in attachments
    )

    manifest_status = getattr(parent, "manifest_status", None) or "UNKNOWN"
    expected_count = getattr(parent, "expected_attachment_count", None)
    if expected_count is None:
        expected_count = -1

    captured_count = sum(
        1
        for a in attachments
        if getattr(a, "capture_status", None) == "CAPTURED"
        and getattr(a, "readback_verified", 0) == 1
    )

    frappe.db.set_value(
        "Fresko Evidence",
        evidence_name,
        "verified_attachment_count",
        captured_count,
        update_modified=False,
    )

    # If manifest is not finalized, count is UNKNOWN -> cannot be COMPLETE
    if manifest_status != "FINALIZED" or expected_count < 0:
        new_status = "PARTIAL" if has_failing else "PENDING"
        frappe.db.set_value(
            "Fresko Evidence",
            evidence_name,
            "overall_verification_status",
            new_status,
            update_modified=False,
        )
        return new_status

    # Manifest is FINALIZED
    if len(attachments) != expected_count:
        new_status = "PARTIAL" if (has_failing or len(attachments) > expected_count) else "PENDING"
        frappe.db.set_value(
            "Fresko Evidence",
            evidence_name,
            "overall_verification_status",
            new_status,
            update_modified=False,
        )
        return new_status

    if captured_count == expected_count and not has_failing:
        new_status = "COMPLETE"
    elif has_failing:
        new_status = "PARTIAL"
    else:
        new_status = "PENDING"

    frappe.db.set_value(
        "Fresko Evidence",
        evidence_name,
        "overall_verification_status",
        new_status,
        update_modified=False,
    )
    return new_status


def prevent_captured_file_deletion(doc, method=None):
    """FSEC-004/005: Protect captured and superseded original bytes against application-level deletion."""
    file_url = getattr(doc, "file_url", None)
    doc_name = getattr(doc, "name", None)
    file_name = getattr(doc, "file_name", None)

    # Use exact match or suffix match on filename or file_url
    search_terms = tuple(set(t for t in (file_url, doc_name, file_name, f"/private/files/{file_name}" if file_name else None) if t))
    if not search_terms:
        return

    placeholders = ", ".join(["%s"] * len(search_terms))
    refs = frappe.db.sql(
        f"""
        SELECT name, evidence, capture_status, version
        FROM `tabFresko Evidence Attachment`
        WHERE (
            file IN ({placeholders})
            OR file_url IN ({placeholders})
            OR file LIKE %s
            OR file_url LIKE %s
        )
        AND (capture_status IN ('CAPTURED', 'SUPERSEDED') OR is_superseded = 1)
        LIMIT 1
        """,
        search_terms + search_terms + (f"%{file_name}" if file_name else "%", f"%{file_name}" if file_name else "%"),
        as_dict=True,
    )
    if refs:
        ref_name = getattr(refs[0], "name", None) or (refs[0].get("name") if hasattr(refs[0], "get") else str(refs[0]))
        frappe.throw(
            f"Cannot delete File '{doc_name or file_name}': referenced by captured Evidence Attachment '{ref_name}' (or superseded). "
            "Captured original bytes are immutable.",
            frappe.PermissionError,
        )


def prevent_captured_file_modification(doc, method=None):
    """FSEC-004/005: Protect captured and superseded original bytes against application-level modification/replacement."""
    if getattr(doc, "is_new", None) and doc.is_new():
        return
    file_url = getattr(doc, "file_url", None)
    doc_name = getattr(doc, "name", None)
    file_name = getattr(doc, "file_name", None)

    db_file_url = doc.get_db_value("file_url") if hasattr(doc, "get_db_value") else None
    db_file_name = doc.get_db_value("file_name") if hasattr(doc, "get_db_value") else None

    search_terms = tuple(set(t for t in (
        file_url, doc_name, file_name, db_file_url, db_file_name,
        f"/private/files/{file_name}" if file_name else None,
        f"/private/files/{db_file_name}" if db_file_name else None,
    ) if t))
    if not search_terms:
        return

    placeholders = ", ".join(["%s"] * len(search_terms))
    refs = frappe.db.sql(
        f"""
        SELECT name, evidence, capture_status, version
        FROM `tabFresko Evidence Attachment`
        WHERE (
            file IN ({placeholders})
            OR file_url IN ({placeholders})
            OR file LIKE %s
            OR file_url LIKE %s
        )
        AND (capture_status IN ('CAPTURED', 'SUPERSEDED') OR is_superseded = 1)
        LIMIT 1
        """,
        search_terms + search_terms + (
            f"%{db_file_name or file_name}" if (db_file_name or file_name) else "%",
            f"%{db_file_name or file_name}" if (db_file_name or file_name) else "%",
        ),
        as_dict=True,
    )
    if refs:
        ref_name = getattr(refs[0], "name", None) or (refs[0].get("name") if hasattr(refs[0], "get") else str(refs[0]))
        for field in ("file_url", "content_hash", "file_name", "file_size"):
            if getattr(doc, "has_value_changed", None) and doc.has_value_changed(field):
                frappe.throw(
                    f"Cannot modify File '{doc_name or file_name}' field '{field}': referenced by captured Evidence Attachment '{ref_name}' (or superseded). "
                    "Captured original bytes are immutable.",
                    frappe.PermissionError,
                )


def prevent_captured_evidence_deletion(doc, method=None):
    """Protect captured or scoped Fresko Evidence from deletion."""
    status = getattr(doc, "overall_verification_status", None)
    scoped_key = getattr(doc, "scoped_message_key", None)
    if status in ("COMPLETE", "PARTIAL") or scoped_key:
        frappe.throw(
            "Captured or scoped Fresko Evidence records cannot be deleted",
            frappe.PermissionError,
        )
    att_count = (
        frappe.db.count("Fresko Evidence Attachment", {"evidence": doc.name})
        if hasattr(frappe.db, "count")
        else len(frappe.db.sql("SELECT name FROM `tabFresko Evidence Attachment` WHERE evidence=%s", (doc.name,)))
    )
    if att_count > 0:
        frappe.throw(
            "Fresko Evidence with existing attachments cannot be deleted",
            frappe.PermissionError,
        )
