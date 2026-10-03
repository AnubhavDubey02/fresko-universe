"""Run every registered seeded schema-migration proof through one site session.

Schema-changing pull requests add a focused ``scripts/prove_*.py`` module and
register it in ``schema_migration_proofs.json``.  Each module exposes the three
stage functions used by the exact Phase 1-to-current upgrade gate.  Non-schema
changes do not need to add a proof.  ``--validate-only`` is the offline gate:
it checks the registry, the stage contract of every proof, and that no
``prove_*.py`` module is left unregistered.

A stage is fail-fast, not atomic across proofs: proofs own their commits, so a
failure stops later proofs but does not undo an earlier proof's committed seed
or snapshot.  The upgrade site is disposable and must be recreated after any
failure.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = Path(__file__).with_name("schema_migration_proofs.json")
STAGES = ("seed_phase1", "verify_first_migrate", "verify_second_migrate")
PROOF_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
PROOF_GLOB = "prove_*.py"


@dataclass(frozen=True)
class ProofSpec:
    proof_id: str
    path: Path


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_registry(
    registry_path: Path = DEFAULT_REGISTRY,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> tuple[ProofSpec, ...]:
    """Validate and return proof specifications in their declared order."""
    registry_path = registry_path.resolve()
    repository_root = repository_root.resolve()
    _require(registry_path.is_file(), f"Migration proof registry is missing: {registry_path}")

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    _require(isinstance(payload, dict), "Migration proof registry must be a JSON object")
    _require(payload.get("schema_version") == 1, "Unsupported migration proof registry version")
    entries = payload.get("proofs")
    _require(isinstance(entries, list) and entries, "Migration proof registry must list at least one proof")

    specs: list[ProofSpec] = []
    seen_ids: set[str] = set()
    seen_paths: set[Path] = set()
    for index, entry in enumerate(entries):
        _require(isinstance(entry, dict), f"Proof entry {index} must be a JSON object")
        proof_id = entry.get("id")
        relative_path = entry.get("path")
        _require(
            isinstance(proof_id, str) and bool(PROOF_ID_PATTERN.fullmatch(proof_id)),
            f"Proof entry {index} has an invalid id: {proof_id!r}",
        )
        _require(proof_id not in seen_ids, f"Duplicate migration proof id: {proof_id}")
        _require(
            isinstance(relative_path, str) and relative_path.endswith(".py"),
            f"Proof {proof_id} must name a Python file",
        )
        candidate = (repository_root / relative_path).resolve()
        _require(
            candidate.is_relative_to(repository_root),
            f"Proof {proof_id} escapes the repository root: {relative_path}",
        )
        _require(candidate.is_file(), f"Proof {proof_id} is missing: {candidate}")
        _require(candidate not in seen_paths, f"Proof {proof_id} registers a duplicate path: {relative_path}")
        specs.append(ProofSpec(proof_id=proof_id, path=candidate))
        seen_ids.add(proof_id)
        seen_paths.add(candidate)

    return tuple(specs)


def validate_proof_source(spec: ProofSpec) -> None:
    """Statically require every stage as a top-level function, without importing Frappe."""
    tree = ast.parse(spec.path.read_text(encoding="utf-8"), filename=str(spec.path))
    defined = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    missing = [stage for stage in STAGES if stage not in defined]
    _require(not missing, f"Proof {spec.proof_id} does not define stage(s): {', '.join(missing)}")


def check_registry_coverage(specs: Sequence[ProofSpec], scripts_dir: Path) -> None:
    """Fail when a seeded proof module exists but would be silently skipped."""
    registered = {spec.path for spec in specs}
    unregistered = sorted(
        path.name for path in scripts_dir.resolve().glob(PROOF_GLOB) if path.resolve() not in registered
    )
    _require(not unregistered, "Unregistered schema migration proof(s): " + ", ".join(unregistered))


def validate_registry(
    registry_path: Path = DEFAULT_REGISTRY,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> tuple[ProofSpec, ...]:
    """Run every offline check that the Bench stage would otherwise discover late."""
    specs = load_registry(registry_path, repository_root=repository_root)
    for spec in specs:
        validate_proof_source(spec)
    check_registry_coverage(specs, repository_root / "scripts")
    return specs


def load_proof_module(spec: ProofSpec) -> ModuleType:
    """Load one proof from its registered file without making scripts a package."""
    module_name = f"_fresko_schema_migration_proof_{spec.proof_id}"
    module_spec = importlib.util.spec_from_file_location(module_name, spec.path)
    _require(module_spec is not None and module_spec.loader is not None, f"Cannot load proof {spec.proof_id}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def execute_stage(stage: str, proofs: Sequence[tuple[ProofSpec, ModuleType]]) -> None:
    """Execute one lifecycle stage in deterministic registry order."""
    _require(stage in STAGES, f"Unsupported migration proof stage: {stage}")
    for spec, module in proofs:
        function = getattr(module, stage, None)
        _require(callable(function), f"Proof {spec.proof_id} does not expose callable {stage}()")
        print(f"==> migration proof {spec.proof_id}: {stage}")
        function()


def run_site_stage(site: str, stage: str, registry_path: Path) -> None:
    """Connect once and run all registered proofs in order, stopping at the first failure."""
    specs = validate_registry(registry_path)

    cwd = Path.cwd()
    sites_path = cwd / "sites" if (cwd / "sites").is_dir() else cwd
    site_config = sites_path / site / "site_config.json"
    _require(site_config.is_file(), f"Site configuration is missing: {site_config}")

    import frappe  # Imported lazily so registry validation remains an offline gate.

    os.chdir(sites_path)
    frappe.init(site=site, sites_path=".")
    frappe.connect()
    try:
        proofs = tuple((spec, load_proof_module(spec)) for spec in specs)
        execute_stage(stage, proofs)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise
    finally:
        frappe.destroy()
        os.chdir(cwd)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", help="Bench site name")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the registry, proof stage contracts, and coverage without importing Frappe",
    )
    parser.add_argument("stage", nargs="?", choices=STAGES)
    args = parser.parse_args()

    if args.validate_only:
        specs = validate_registry(args.registry)
        print("Registered schema migration proofs: " + ", ".join(spec.proof_id for spec in specs))
        return
    if not args.site or not args.stage:
        parser.error("--site and stage are required unless --validate-only is used")
    run_site_stage(args.site, args.stage, args.registry)


if __name__ == "__main__":
    main()
