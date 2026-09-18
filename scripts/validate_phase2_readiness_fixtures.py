#!/usr/bin/env python3
"""Validate the test-only WhatsApp readiness corpus without app dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = (
    REPO_ROOT
    / "fresko_universe"
    / "fresko_universe"
    / "fixtures"
    / "whatsapp_readiness"
)


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        fail(f"{path.name}: root must be an object")
    return value


def assert_no_numeric_confidence(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if "confidence" in key and isinstance(child, (int, float)):
                fail(f"{child_path}: numeric confidence is forbidden")
            if "percentage" in key.lower():
                fail(f"{child_path}: confidence percentages are forbidden")
            assert_no_numeric_confidence(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_numeric_confidence(child, f"{path}[{index}]")


def validate_case(case: dict[str, Any], vocab: dict[str, list[str]]) -> None:
    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id:
        fail("case id must be a non-empty string")

    for key in (
        "category",
        "source",
        "interpretation",
        "confirmed_facts",
        "expected",
        "expected_result_review",
    ):
        if key not in case:
            fail(f"{case_id}: missing {key}")

    source = case["source"]
    if not isinstance(source, dict) or not source.get("kind") or not source.get("raw_text"):
        fail(f"{case_id}: source kind and raw_text are required")
    if not isinstance(source.get("attachment_members"), list):
        fail(f"{case_id}: attachment_members must be a list")

    if not isinstance(case["interpretation"], str) or not case["interpretation"]:
        fail(f"{case_id}: interpretation must be explicit")
    if not isinstance(case["confirmed_facts"], list) or not case["confirmed_facts"]:
        fail(f"{case_id}: confirmed_facts must be a non-empty list")

    expected = case["expected"]
    if not isinstance(expected, dict):
        fail(f"{case_id}: expected must be an object")
    for field, allowed in vocab.items():
        if expected.get(field) not in allowed:
            fail(f"{case_id}: invalid {field}={expected.get(field)!r}")
    if not isinstance(expected.get("exceptions"), list):
        fail(f"{case_id}: expected.exceptions must be a list")

    review = case["expected_result_review"]
    if review.get("status") != "REVIEWED" or not review.get("basis"):
        fail(f"{case_id}: expected result must be explicitly reviewed")


def validate_semantics(by_id: dict[str, dict[str, Any]]) -> None:
    add_10 = by_id["ambiguous-amendment-add-10"]["expected"]
    add_50 = by_id["ambiguous-amendment-add-50"]["expected"]
    if add_10.get("parent_order") != "UNKNOWN" or add_50.get("parent_order") != "UNKNOWN":
        fail("ambiguous amendments must leave parent_order UNKNOWN")

    redelivery = by_id["provider-redelivery-same-message"]["expected"]
    identical = by_id["identical-text-distinct-message-records"]["expected"]
    if redelivery.get("deduplication_action") == identical.get("deduplication_action"):
        fail("provider redelivery and identical text must have different handling")

    multi = by_id["one-message-many-attachments"]
    if len(multi["source"]["attachment_members"]) < 2:
        fail("multi-attachment case must contain at least two attachments")

    bank = by_id["bank-authorization-not-cleared-receipt"]["expected"]
    if bank.get("financial_verification") != "PENDING" or bank.get("ledger_received") is not False:
        fail("Authorization InProcess must remain pending and not received")

    cold = by_id["cold-storage-bill-missing"]["expected"]
    if cold.get("verified_amount") != "UNKNOWN":
        fail("missing cold-storage bill must keep verified amount UNKNOWN")

    cha = by_id["cha-excess-payment-claim"]["expected"]
    if cha.get("financial_verification") != "PENDING":
        fail("CHA verification must remain PENDING")
    if cha.get("exemption_status") != "PENDING" or cha.get("recoverable_amount") != "PENDING":
        fail("CHA exemption and recoverable amount must remain PENDING")

    partial = by_id["partial-attachment-download-retry"]["expected"]
    if partial.get("captured_successfully") is not False:
        fail("partial attachment must not be marked captured")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_archive(
    archive_path: Path,
    manifest: dict[str, Any],
    cases: list[dict[str, Any]],
) -> None:
    archive = manifest["archive"]
    if archive_path.stat().st_size != archive["size_bytes"]:
        fail("archive size does not match manifest")
    if sha256_file(archive_path) != archive["sha256"]:
        fail("archive SHA-256 does not match manifest")

    with zipfile.ZipFile(archive_path) as bundle:
        bad = bundle.testzip()
        if bad is not None:
            fail(f"archive integrity failure at {bad}")
        members = set(bundle.namelist())
        if len(members) != archive["entry_count"]:
            fail("archive entry count does not match manifest")
        if archive["transcript_member"] not in members:
            fail("transcript member is missing")
        transcript_lines = bundle.read(archive["transcript_member"]).decode("utf-8-sig").splitlines()

        for case in cases:
            source = case["source"]
            if source["kind"] == "closeout_requirement":
                continue
            member = source.get("archive_member")
            if member not in members:
                fail(f"{case['id']}: source archive member missing")
            for attachment in source["attachment_members"]:
                if attachment not in members:
                    fail(f"{case['id']}: attachment member {attachment} missing")
            for start, end in source.get("transcript_line_ranges", []):
                if start < 1 or end < start or end > len(transcript_lines):
                    fail(f"{case['id']}: invalid transcript line range {start}-{end}")
                if not any(line.strip() for line in transcript_lines[start - 1 : end]):
                    fail(f"{case['id']}: transcript line range is empty")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, help="Optional external source ZIP")
    args = parser.parse_args()

    manifest = load_json(FIXTURE_DIR / "manifest.json")
    corpus = load_json(FIXTURE_DIR / "cases.json")
    if manifest.get("schema_version") != 1 or corpus.get("schema_version") != 1:
        fail("unsupported fixture schema version")

    archive = manifest.get("archive", {})
    if archive.get("drive_id") != "1JYTZvKROdcy2tRMbbgfiRaVb7qZ4drxS":
        fail("unexpected Drive source id")
    if len(archive.get("sha256", "")) != 64:
        fail("manifest SHA-256 must be 64 hexadecimal characters")
    int(archive["sha256"], 16)
    if manifest.get("extraction", {}).get("full_archive_committed") is not False:
        fail("full archive must remain outside Git")

    vocab = corpus.get("confidence_vocabulary")
    cases = corpus.get("cases")
    if not isinstance(vocab, dict) or not isinstance(cases, list) or not cases:
        fail("confidence vocabulary and non-empty cases are required")

    assert_no_numeric_confidence(corpus)
    ids: list[str] = []
    for case in cases:
        if not isinstance(case, dict):
            fail("each case must be an object")
        validate_case(case, vocab)
        ids.append(case["id"])
    if len(ids) != len(set(ids)):
        fail("fixture ids must be unique")

    by_id = {case["id"]: case for case in cases}
    validate_semantics(by_id)

    if list(FIXTURE_DIR.glob("*.zip")):
        fail("source ZIP must not be committed in fixture directory")
    if args.archive:
        validate_archive(args.archive.resolve(), manifest, cases)

    archive_note = " with external archive" if args.archive else ""
    print(f"Validated {len(cases)} WhatsApp readiness fixtures{archive_note}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, TypeError, ValueError, OSError, zipfile.BadZipFile) as error:
        print(f"Fixture validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
