#!/usr/bin/env python3
"""Fail CI when a persisted schema changes without a new migration proof.

``scripts/schema_snapshot.json`` records the persisted shape of every Fresko
DocType, the hash of every schema-changing source (install hooks that run DDL,
``patches.txt`` and patch modules), and the registered migration proof ids.

``--check`` fails when the current repository no longer matches the committed
snapshot.  With ``--base-ref`` it also fails when the schema differs from the
base branch's snapshot but no new proof id was registered, so a hand-edited
snapshot cannot hide a schema change.  ``--update`` rewrites the snapshot and
refuses a schema change unless a new proof is registered.

Labels, descriptions, permissions, and layout are not persisted schema and are
ignored.  Offline only: this never imports Frappe or touches a database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import run_schema_migration_harness as harness


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "fresko_universe" / "fresko_universe"
SNAPSHOT_PATH = Path(__file__).with_name("schema_snapshot.json")
SNAPSHOT_RELATIVE = "scripts/schema_snapshot.json"
SNAPSHOT_VERSION = 1

# is_virtual decides whether a table exists at all.
DOCTYPE_KEYS = ("module", "istable", "issingle", "is_virtual", "is_submittable", "is_tree", "autoname", "engine")
# Absent and 0/False are equivalent in Frappe exports, so both are omitted; a
# change to or from a non-zero value is still detected.
FIELD_KEYS = ("fieldtype", "options", "reqd", "unique", "length", "precision", "default", "search_index")
# Display-only field types create no column.
NON_COLUMN_FIELDTYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading", "Fold"}
# Python sources that run DDL or data migration during install/migrate.
SCHEMA_SOURCE_GLOBS = ("install.py", "patches.txt", "patches/**/*.py")


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _doctype_schema(definition: dict[str, Any]) -> dict[str, Any]:
    fields = {}
    for field in definition.get("fields") or []:
        if field.get("fieldtype") in NON_COLUMN_FIELDTYPES:
            continue
        name = field.get("fieldname")
        _require(name, f"{definition.get('name')} has a field without fieldname")
        _require(name not in fields, f"{definition.get('name')} declares {name} twice")
        fields[name] = {key: field.get(key) for key in FIELD_KEYS if field.get(key) not in (None, "", 0)}
    return {
        **{key: definition.get(key) for key in DOCTYPE_KEYS if definition.get(key) not in (None, "", 0)},
        "fields": dict(sorted(fields.items())),
    }


def _sha256_text(path: Path) -> str:
    # Normalize line endings so the hash is platform independent.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def build_snapshot(app_root: Path = APP_ROOT, registry: Path = harness.DEFAULT_REGISTRY, *, repository_root: Path = ROOT) -> dict[str, Any]:
    doctypes: dict[str, Any] = {}
    for path in sorted(app_root.glob("*/doctype/*/*.json")):
        definition = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(definition, dict) or definition.get("doctype") != "DocType":
            continue
        name = definition.get("name")
        _require(name and name not in doctypes, f"Duplicate or unnamed DocType in {path}")
        doctypes[name] = _doctype_schema(definition)

    sources = {}
    for pattern in SCHEMA_SOURCE_GLOBS:
        for path in sorted(app_root.glob(pattern)):
            if path.is_file() and path.name != "__init__.py":
                sources[path.relative_to(app_root).as_posix()] = _sha256_text(path)

    specs = harness.load_registry(registry, repository_root=repository_root)
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "doctypes": dict(sorted(doctypes.items())),
        "schema_sources": dict(sorted(sources.items())),
        "migration_proofs": [spec.proof_id for spec in specs],
    }


def schema_part(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {"doctypes": snapshot.get("doctypes"), "schema_sources": snapshot.get("schema_sources")}


def describe_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    changes = []
    old_types, new_types = old.get("doctypes") or {}, new.get("doctypes") or {}
    for name in sorted(set(old_types) | set(new_types)):
        if name not in old_types:
            changes.append(f"DocType added: {name}")
        elif name not in new_types:
            changes.append(f"DocType removed: {name}")
        elif old_types[name] != new_types[name]:
            old_fields, new_fields = old_types[name].get("fields", {}), new_types[name].get("fields", {})
            for field in sorted(set(old_fields) | set(new_fields)):
                if old_fields.get(field) != new_fields.get(field):
                    changes.append(f"{name}.{field}: {old_fields.get(field)!r} -> {new_fields.get(field)!r}")
            old_props = {k: v for k, v in old_types[name].items() if k != "fields"}
            new_props = {k: v for k, v in new_types[name].items() if k != "fields"}
            if old_props != new_props:
                changes.append(f"{name} properties: {old_props!r} -> {new_props!r}")
    old_sources, new_sources = old.get("schema_sources") or {}, new.get("schema_sources") or {}
    for source in sorted(set(old_sources) | set(new_sources)):
        if old_sources.get(source) != new_sources.get(source):
            changes.append(f"schema source changed: {source}")
    return changes


def require_new_proof_for_change(old: dict[str, Any], new: dict[str, Any], label: str) -> None:
    changes = describe_changes(old, new)
    if not changes:
        return
    added = set(new.get("migration_proofs") or []) - set(old.get("migration_proofs") or [])
    _require(
        added,
        f"Persisted schema changed relative to {label} without a new registered migration proof:\n  "
        + "\n  ".join(changes)
        + "\nAdd a scripts/prove_*.py proof, register it in scripts/schema_migration_proofs.json "
        "(see docs/SCHEMA_MIGRATION_PROOFS.md), then run: python3 scripts/check_schema_snapshot.py --update",
    )


def _render(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def load_base_snapshot(base_ref: str, *, repository_root: Path = ROOT) -> dict[str, Any] | None:
    """Return the base ref's committed snapshot, or None when it predates the snapshot."""
    result = subprocess.run(
        ["git", "-C", str(repository_root), "show", f"{base_ref}:{SNAPSHOT_RELATIVE}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        verify = subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}"],
            capture_output=True,
            text=True,
        )
        _require(verify.returncode == 0, f"Base ref {base_ref!r} is not available; fetch it before checking")
        return None
    return json.loads(result.stdout)


def check(snapshot_path: Path, current: dict[str, Any], base: dict[str, Any] | None, base_ref: str | None) -> None:
    _require(snapshot_path.is_file(), f"Schema snapshot is missing: {snapshot_path}")
    committed = json.loads(snapshot_path.read_text(encoding="utf-8"))
    _require(committed.get("snapshot_version") == SNAPSHOT_VERSION, "Unsupported schema snapshot version")
    if committed != current:
        changes = describe_changes(committed, current)
        if committed.get("migration_proofs") != current.get("migration_proofs"):
            changes.append(
                f"migration proofs: {committed.get('migration_proofs')!r} -> {current.get('migration_proofs')!r}"
            )
        raise AssertionError(
            "scripts/schema_snapshot.json is out of date:\n  "
            + "\n  ".join(changes or ["formatting or ordering differs"])
            + "\nIf this is a schema change, register a migration proof first; then run: "
            "python3 scripts/check_schema_snapshot.py --update"
        )
    if base is not None:
        require_new_proof_for_change(base, current, base_ref or "base")


def update(snapshot_path: Path, current: dict[str, Any]) -> bool:
    if snapshot_path.is_file():
        previous = json.loads(snapshot_path.read_text(encoding="utf-8"))
        require_new_proof_for_change(previous, current, "the committed snapshot")
    rendered = _render(current)
    if snapshot_path.is_file() and snapshot_path.read_text(encoding="utf-8") == rendered:
        return False
    snapshot_path.write_bytes(rendered.encode("utf-8"))
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Fail if the committed snapshot is stale or unproven")
    mode.add_argument("--update", action="store_true", help="Rewrite the snapshot (requires a new proof for schema changes)")
    parser.add_argument("--base-ref", help="Also require a new proof for schema changes relative to this git ref")
    args = parser.parse_args(argv)

    current = build_snapshot()
    try:
        if args.update:
            changed = update(SNAPSHOT_PATH, current)
            print("Schema snapshot updated." if changed else "Schema snapshot already current.")
        else:
            base = load_base_snapshot(args.base_ref) if args.base_ref else None
            check(SNAPSHOT_PATH, current, base, args.base_ref)
            suffix = f"; base {args.base_ref} {'has no snapshot yet' if base is None else 'checked'}" if args.base_ref else ""
            print(f"Schema snapshot current: {len(current['doctypes'])} DocTypes, {len(current['migration_proofs'])} proofs{suffix}.")
    except AssertionError as error:
        print(f"Schema snapshot check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
