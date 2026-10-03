from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import run_schema_migration_harness as harness


class SchemaMigrationHarnessTest(unittest.TestCase):
    def _registry(self, root: Path, entries: list[dict[str, str]]) -> Path:
        path = root / "registry.json"
        path.write_text(
            json.dumps({"schema_version": 1, "proofs": entries}),
            encoding="utf-8",
        )
        return path

    def test_registry_preserves_declared_order_and_loads_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            scripts = root / "scripts"
            scripts.mkdir()
            for name in ("first", "second"):
                (scripts / f"{name}.py").write_text(
                    "def seed_phase1():\n    return 'seeded'\n",
                    encoding="utf-8",
                )
            registry = self._registry(
                root,
                [
                    {"id": "first", "path": "scripts/first.py"},
                    {"id": "second", "path": "scripts/second.py"},
                ],
            )

            specs = harness.load_registry(registry, repository_root=root)

            self.assertEqual([spec.proof_id for spec in specs], ["first", "second"])
            self.assertEqual(harness.load_proof_module(specs[0]).seed_phase1(), "seeded")

    def test_registry_rejects_duplicate_ids_and_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            proof = root / "proof.py"
            proof.write_text("def seed_phase1():\n    pass\n", encoding="utf-8")
            duplicate_registry = self._registry(
                root,
                [
                    {"id": "duplicate", "path": "proof.py"},
                    {"id": "duplicate", "path": "proof.py"},
                ],
            )
            with self.assertRaisesRegex(AssertionError, "Duplicate migration proof id"):
                harness.load_registry(duplicate_registry, repository_root=root)

            outside = root.parent / "outside_proof.py"
            outside.write_text("def seed_phase1():\n    pass\n", encoding="utf-8")
            escape_registry = self._registry(
                root,
                [{"id": "escape", "path": "../outside_proof.py"}],
            )
            with self.assertRaisesRegex(AssertionError, "escapes the repository root"):
                harness.load_registry(escape_registry, repository_root=root)

    def test_execute_stage_is_ordered_and_fails_on_missing_stage(self) -> None:
        calls: list[str] = []
        first = harness.ProofSpec("first", Path("first.py"))
        second = harness.ProofSpec("second", Path("second.py"))
        proofs = (
            (first, SimpleNamespace(seed_phase1=lambda: calls.append("first"))),
            (second, SimpleNamespace(seed_phase1=lambda: calls.append("second"))),
        )

        harness.execute_stage("seed_phase1", proofs)
        self.assertEqual(calls, ["first", "second"])

        with self.assertRaisesRegex(AssertionError, "does not expose callable"):
            harness.execute_stage(
                "verify_first_migrate",
                ((first, SimpleNamespace()),),
            )


if __name__ == "__main__":
    unittest.main()
