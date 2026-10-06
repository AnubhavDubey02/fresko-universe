import hashlib
import importlib.util
from unittest.mock import patch
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


def load_exporter():
    exporter_path = Path(__file__).resolve().parent / "export_deployment_app.py"
    spec = importlib.util.spec_from_file_location("export_deployment_app", exporter_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


exporter = load_exporter()


def git_cmd(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return res.stdout.strip()


TOML_TEMPLATE = """[project]
name = "{name}"
version = "0.0.1"

[tool.bench.frappe-dependencies]
frappe = "{frappe}"
erpnext = "{erpnext}"
"""


class TestDeploymentPackage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git_cmd(self.repo, "init")
        git_cmd(self.repo, "remote", "add", "origin", exporter.REPO_URL)
        git_cmd(self.repo, "config", "user.email", "synthetic@example.invalid")
        git_cmd(self.repo, "config", "user.name", "SyntheticFixture")

        (self.repo / "OUTSIDE_ROOT.txt").write_text("outside app content", encoding="utf-8")

        app = self.repo / "fresko_universe"
        pkg = app / "fresko_universe"
        pkg.mkdir(parents=True)

        (app / "pyproject.toml").write_text(
            TOML_TEMPLATE.format(name="fresko_universe", frappe=">=15.0.0,<16.0.0", erpnext=">=15.0.0,<16.0.0"),
            encoding="utf-8",
        )
        (app / "README.md").write_text("# Fresko Universe\nUnicode ✨", encoding="utf-8")
        (pkg / "__init__.py").write_text('__version__ = "0.0.1"\n', encoding="utf-8")
        (pkg / "hooks.py").write_text("app_name = 'fresko_universe'\n", encoding="utf-8")
        (pkg / "modules.txt").write_text("Fresko Universe\n", encoding="utf-8")
        (pkg / "patches.txt").write_text("\n", encoding="utf-8")
        (pkg / "data.json").write_text('{"key": "value"}', encoding="utf-8")
        (pkg / "script.js").write_text("console.log('hello');", encoding="utf-8")

        self.binary_payload = bytes(range(256))
        (pkg / "payload.bin").write_bytes(self.binary_payload)

        script_file = pkg / "run.sh"
        script_file.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
        script_file.chmod(0o755)

        git_cmd(self.repo, "add", "-A")
        git_cmd(self.repo, "commit", "-m", "Initial commit")
        self.commit = git_cmd(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_export_committed_data_and_reproducibility(self):
        (self.repo / "fresko_universe" / "README.md").write_text("MODIFIED WORKING TREE", encoding="utf-8")
        (self.repo / "fresko_universe" / "untracked.txt").write_text("UNTRACKED", encoding="utf-8")

        out1 = self.root / "export1"
        out2 = self.root / "export2"

        m1 = exporter.export_app(self.repo, self.commit, out1)
        m2 = exporter.export_app(self.repo, self.commit, out2)

        self.assertEqual(m1, m2)
        self.assertEqual(m1["source_tree"], git_cmd(self.repo, "rev-parse", f"{self.commit}:fresko_universe"))
        for row in m1["files"]:
            data = (out1 / row["path"]).read_bytes()
            expected = subprocess.check_output(["git", "show", f"{self.commit}:{row['source_path']}"], cwd=self.repo)
            self.assertEqual(data, expected)
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"])
            self.assertEqual(len(data), row["size_bytes"])
        self.assertEqual((out1.stat().st_mode & 0o777), 0o755)
        self.assertEqual(m1["source_commit"], self.commit)
        self.assertEqual(m1["source_repository"], "https://github.com/AnubhavDubey02/fresko-universe")

        self.assertIn("Unicode ✨", (out1 / "README.md").read_text(encoding="utf-8"))
        self.assertFalse((out1 / "untracked.txt").exists())
        self.assertFalse((out1 / "OUTSIDE_ROOT.txt").exists())
        self.assertEqual((out1 / "fresko_universe" / "payload.bin").read_bytes(), self.binary_payload)
        self.assertTrue((out1 / "fresko_universe" / "run.sh").stat().st_mode & 0o111)

    def test_reject_branch_and_invalid_sha(self):
        out = self.root / "export_fail"
        for bad in ("main", "HEAD", self.commit[:8], self.commit.upper(), "g" * 40):
            with self.assertRaises(ValueError):
                exporter.export_app(self.repo, bad, out)
            self.assertFalse(out.exists())

    def test_reject_existing_destination(self):
        out = self.root / "existing_dir"
        out.mkdir()
        with self.assertRaises(FileExistsError):
            exporter.export_app(self.repo, self.commit, out)

    def test_reject_invalid_metadata_and_cleanup(self):
        bad_toml = self.repo / "fresko_universe" / "pyproject.toml"
        bad_toml.write_text(
            TOML_TEMPLATE.format(name="wrong_name", frappe=">=15.0.0,<16.0.0", erpnext=">=15.0.0,<16.0.0"),
            encoding="utf-8",
        )
        git_cmd(self.repo, "commit", "-am", "Wrong name")
        bad_commit = git_cmd(self.repo, "rev-parse", "HEAD")

        out = self.root / "out_bad_meta"
        with self.assertRaises(ValueError):
            exporter.export_app(self.repo, bad_commit, out)
        self.assertFalse(out.exists())

    def test_reject_symlink_fixture(self):
        link = self.repo / "fresko_universe" / "symlink_file"
        try:
            link.symlink_to(Path("README.md"))
            git_cmd(self.repo, "add", "fresko_universe/symlink_file")
            git_cmd(self.repo, "commit", "-m", "Add symlink")
            symlink_commit = git_cmd(self.repo, "rev-parse", "HEAD")
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("Host cannot create symlink fixture")

        out = self.root / "out_symlink"
        with self.assertRaises(ValueError):
            exporter.export_app(self.repo, symlink_commit, out)
        self.assertFalse(out.exists())

    def test_concurrent_destination_is_preserved(self):
        out = self.root / "racing"
        original = exporter._rename_no_replace
        def racer(source, target):
            target.mkdir()
            original(source, target)
        with patch.object(exporter, "_rename_no_replace", racer):
            with self.assertRaises(FileExistsError):
                exporter.export_app(self.repo, self.commit, out)
        self.assertTrue(out.is_dir())
        self.assertEqual(list(out.iterdir()), [])
        self.assertEqual(list(self.root.glob(".tmp_export_*")), [])

    def test_reject_dangling_destination_and_wrong_repository(self):
        out = self.root / "dangling"
        out.symlink_to(self.root / "missing")
        with self.assertRaises(FileExistsError):
            exporter.export_app(self.repo, self.commit, out)
        git_cmd(self.repo, "remote", "set-url", "origin", "https://example.invalid/unrelated")
        with self.assertRaisesRegex(ValueError, "source repository"):
            exporter.export_app(self.repo, self.commit, self.root / "wrong-repo")

    def test_reject_drive_path(self):
        (self.repo / "fresko_universe" / "C:unsafe").write_text("unsafe")
        git_cmd(self.repo, "add", "-A")
        git_cmd(self.repo, "commit", "-m", "Invalid portable path")
        with self.assertRaisesRegex(ValueError, "Invalid path"):
            exporter.export_app(self.repo, git_cmd(self.repo, "rev-parse", "HEAD"), self.root / "drive")


if __name__ == "__main__":
    unittest.main()
