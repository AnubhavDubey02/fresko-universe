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
            # Nest the root so the escape target stays inside the temporary directory.
            root = Path(temporary_directory) / "repo"
            root.mkdir()
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

            duplicate_path_registry = self._registry(
                root,
                [
                    {"id": "first", "path": "proof.py"},
                    {"id": "second", "path": "./proof.py"},
                ],
            )
            with self.assertRaisesRegex(AssertionError, "duplicate path"):
                harness.load_registry(duplicate_path_registry, repository_root=root)

    def test_validation_rejects_missing_stage_and_unregistered_proof(self) -> None:
        complete = "".join(f"def {stage}():\n    pass\n" for stage in harness.STAGES)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "prove_alpha.py").write_text(complete, encoding="utf-8")
            registry = self._registry(root, [{"id": "alpha", "path": "scripts/prove_alpha.py"}])

            specs = harness.validate_registry(registry, repository_root=root)
            self.assertEqual([spec.proof_id for spec in specs], ["alpha"])

            (scripts / "prove_beta.py").write_text(complete, encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "Unregistered schema migration proof\\(s\\): prove_beta.py"):
                harness.validate_registry(registry, repository_root=root)
            (scripts / "prove_beta.py").unlink()

            # A stage nested in a class or guarded block is not a module-level stage.
            (scripts / "prove_alpha.py").write_text(
                "def seed_phase1():\n    pass\n"
                "class Hidden:\n    def verify_first_migrate(self):\n        pass\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                AssertionError, "does not define stage\\(s\\): verify_first_migrate, verify_second_migrate"
            ):
                harness.validate_registry(registry, repository_root=root)

    def test_repository_registry_is_valid_and_complete(self) -> None:
        specs = harness.validate_registry()
        self.assertEqual(
            [spec.proof_id for spec in specs],
            ["evidence_attempt_link_to_data", "phase2a_physical_ledger", "physical_variance_exception", "integrity_seal_ledger", "commercial_sale_ledger", "money_reconciliation_ledger"],
        )

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

        with self.assertRaisesRegex(AssertionError, "Unsupported migration proof stage"):
            harness.execute_stage("migrate", proofs)

    def test_execute_stage_stops_at_first_failure(self) -> None:
        calls: list[str] = []

        def fail() -> None:
            calls.append("first")
            raise AssertionError("seeded proof failed")

        proofs = (
            (harness.ProofSpec("first", Path("first.py")), SimpleNamespace(seed_phase1=fail)),
            (
                harness.ProofSpec("second", Path("second.py")),
                SimpleNamespace(seed_phase1=lambda: calls.append("second")),
            ),
        )
        with self.assertRaisesRegex(AssertionError, "seeded proof failed"):
            harness.execute_stage("seed_phase1", proofs)
        self.assertEqual(calls, ["first"])


if __name__ == "__main__":
    unittest.main()
