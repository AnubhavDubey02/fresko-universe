from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import check_schema_snapshot as snapshot


STAGES = "".join(f"def {stage}():\n    pass\n" for stage in ("seed_phase1", "verify_first_migrate", "verify_second_migrate"))


class SchemaSnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.app = self.root / "fresko_universe" / "fresko_universe"
        self.doctype_dir = self.app / "core" / "doctype" / "thing"
        self.doctype_dir.mkdir(parents=True)
        (self.app / "patches").mkdir()
        (self.app / "patches.txt").write_text("[post_model_sync]\n", encoding="utf-8")
        (self.app / "install.py").write_text("def after_migrate():\n    pass\n", encoding="utf-8")
        self.scripts = self.root / "scripts"
        self.scripts.mkdir()
        self.registry = self.scripts / "registry.json"
        self._write_doctype(label="Amount")
        self._write_registry(["alpha"])

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _write_doctype(self, *, label: str, fieldtype: str = "Data", extra: list[dict] | None = None) -> None:
        definition = {
            "doctype": "DocType",
            "name": "Thing",
            "module": "Core",
            "fields": [
                {"fieldname": "amount", "fieldtype": fieldtype, "label": label, "reqd": 1},
                {"fieldname": "section", "fieldtype": "Section Break", "label": "Layout"},
                *(extra or []),
            ],
            "permissions": [{"role": "System Manager", "read": 1}],
        }
        (self.doctype_dir / "thing.json").write_text(json.dumps(definition), encoding="utf-8")

    def _write_registry(self, proof_ids: list[str]) -> None:
        for proof_id in proof_ids:
            (self.scripts / f"prove_{proof_id}.py").write_text(STAGES, encoding="utf-8")
        entries = [{"id": proof_id, "path": f"scripts/prove_{proof_id}.py"} for proof_id in proof_ids]
        self.registry.write_text(json.dumps({"schema_version": 1, "proofs": entries}), encoding="utf-8")

    def _build(self) -> dict:
        return snapshot.build_snapshot(self.app, self.registry, repository_root=self.root)

    def test_layout_labels_and_permissions_are_not_schema(self) -> None:
        before = self._build()
        self._write_doctype(label="Renamed label")
        self.assertEqual(snapshot.describe_changes(before, self._build()), [])
        self.assertNotIn("section", before["doctypes"]["Thing"]["fields"])
        self.assertEqual(before["doctypes"]["Thing"]["fields"]["amount"], {"fieldtype": "Data", "reqd": 1})

    def test_field_type_change_requires_new_proof(self) -> None:
        before = self._build()
        self._write_doctype(label="Amount", fieldtype="Currency")
        after = self._build()
        with self.assertRaisesRegex(AssertionError, r"without a new registered migration proof:\n  Thing.amount"):
            snapshot.require_new_proof_for_change(before, after, "base")

        self._write_registry(["alpha", "beta"])
        snapshot.require_new_proof_for_change(before, self._build(), "base")

    def test_added_field_doctype_and_patch_sources_are_detected(self) -> None:
        before = self._build()
        self._write_doctype(label="Amount", extra=[{"fieldname": "note", "fieldtype": "Small Text"}])
        (self.app / "patches" / "v1_0").mkdir()
        (self.app / "patches" / "v1_0" / "backfill.py").write_text("def execute():\n    pass\n", encoding="utf-8")
        (self.app / "install.py").write_text("def after_migrate():\n    run_ddl()\n", encoding="utf-8")
        changes = snapshot.describe_changes(before, self._build())
        self.assertIn("Thing.note: None -> {'fieldtype': 'Small Text'}", changes)
        self.assertIn("schema source changed: patches/v1_0/backfill.py", changes)
        self.assertIn("schema source changed: install.py", changes)

    def test_source_hash_ignores_line_endings(self) -> None:
        before = self._build()
        (self.app / "install.py").write_bytes(b"def after_migrate():\r\n    pass\r\n")
        self.assertEqual(snapshot.describe_changes(before, self._build()), [])

    def test_check_rejects_stale_snapshot_and_update_refuses_unproven_change(self) -> None:
        path = self.root / "schema_snapshot.json"
        self.assertTrue(snapshot.update(path, self._build()))
        self.assertFalse(snapshot.update(path, self._build()))
        snapshot.check(path, self._build(), None, None)

        self._write_doctype(label="Amount", fieldtype="Int")
        with self.assertRaisesRegex(AssertionError, "out of date:\n  Thing.amount"):
            snapshot.check(path, self._build(), None, None)
        with self.assertRaisesRegex(AssertionError, "without a new registered migration proof"):
            snapshot.update(path, self._build())

        self._write_registry(["alpha", "beta"])
        self.assertTrue(snapshot.update(path, self._build()))
        snapshot.check(path, self._build(), None, None)

    def test_hand_edited_snapshot_cannot_hide_change_from_base(self) -> None:
        base = self._build()
        path = self.root / "schema_snapshot.json"
        self._write_doctype(label="Amount", fieldtype="Float")
        # Bypass attempt: write the new shape straight into the snapshot without a proof.
        path.write_text(snapshot._render(self._build()), encoding="utf-8")
        with self.assertRaisesRegex(AssertionError, "relative to base without a new registered migration proof"):
            snapshot.check(path, self._build(), base, "base")

    def test_repository_snapshot_is_current(self) -> None:
        snapshot.check(snapshot.SNAPSHOT_PATH, snapshot.build_snapshot(), None, None)


if __name__ == "__main__":
    unittest.main()
