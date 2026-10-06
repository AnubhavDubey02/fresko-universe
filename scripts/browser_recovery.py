"""Recover one explicitly synthetic test site into a separate, new site."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile


def prove(bench: Path, site: str, manifest: Path, output: Path):
    if Path(site).name != site or (bench / "sites" / site).is_symlink():
        raise ValueError("Recovery source must be an explicit local site name")
    if output.exists() or output.is_symlink():
        raise ValueError("Recovery report must be a new file")
    fixture = json.loads(manifest.read_text())
    if fixture.get("synthetic_only") is not True:
        raise ValueError("Synthetic-only recovery manifest required")
    config_path = bench / "sites" / site / "site_config.json"
    source_config = json.loads(config_path.read_text())
    if not source_config.get("fresko_browser_fixture_only") or not source_config.get("allow_tests") or not source_config.get("fresko_disposable_browser_site"):
        raise ValueError("Source site must explicitly enable synthetic browser fixtures")
    restore_site = f"browser-restore-{secrets.token_hex(16)}.localhost"
    if (bench / "sites" / restore_site).exists():
        raise ValueError("Restore destination must be a new, isolated site")
    bench_command = os.environ.get("FRESKO_BENCH_COMMAND", "bench")
    def call(target, *args):
        result = subprocess.run([bench_command, "--site", target, *args], cwd=bench, capture_output=True)
        if result.returncode:
            # Private diagnostics are optional and never placed in public artifacts.
            log_path = os.environ.get("FRESKO_RECOVERY_PRIVATE_LOG")
            if log_path:
                log = Path(log_path).resolve()
                if log.is_relative_to(output.parent.resolve()):
                    raise ValueError("Recovery diagnostics must be outside public artifacts")
                detail = (result.stdout + result.stderr).decode(errors="replace")
                for index, value in enumerate(args[:-1]):
                    if value in ("--db-root-password", "--admin-password"):
                        detail = detail.replace(args[index + 1], "[REDACTED]")
                with os.fdopen(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as stream:
                    stream.write(f"Step {args[0]}, isolated destination {restore_site}\n{detail}\n")
            raise RuntimeError(f"Recovery step {args[0]} failed; isolated destination {restore_site} may be retained for private cleanup; runner output withheld")
    with tempfile.TemporaryDirectory(prefix="fresko-recovery-") as folder:
        private = Path(folder)
        before, after = private / "before.json", private / "after.json"
        def snapshot(target, path):
            call(target, "execute", "fresko_universe.tests.browser_fixture.recovery_snapshot", "--kwargs",
                json.dumps({"manifest_path": str(manifest.resolve()), "snapshot_path": str(path)}))
        snapshot(site, before)
        database, public, protected, config = [private / name for name in ["database.sql.gz", "public.tgz", "private.tgz", "config.json"]]
        call(site, "backup", "--with-files", "--compress", "--ignore-backup-conf",
            "--backup-path-db", str(database), "--backup-path-files", str(public),
            "--backup-path-private-files", str(protected), "--backup-path-conf", str(config))
        paths = [database, public, protected, config]
        if not all(path.is_file() and path.stat().st_size > 0 for path in paths):
            raise RuntimeError("Full four-component backup is incomplete")
        saved_config = json.loads(config.read_text())
        # Plain synthetic CI backup only. Never silently downgrade encrypted live backups.
        if database.suffix == ".enc" or source_config.get("encrypt_backup"):
            raise RuntimeError("Encrypted hosting restore requires explicit key-assisted procedure")
        root_password = os.environ["DB_ROOT_PASSWORD"]
        common_config = json.loads((bench / "sites" / "common_site_config.json").read_text())
        call(restore_site, "new-site", restore_site, "--db-root-password", root_password,
            "--admin-password", secrets.token_urlsafe(24), "--db-host",
            source_config.get("db_host") or common_config.get("db_host") or "127.0.0.1",
            "--no-mariadb-socket", "--mariadb-user-host-login-scope", "%")
        call(restore_site, "restore", str(database), "--db-root-password", root_password,
            "--admin-password", secrets.token_urlsafe(24), "--with-public-files", str(public),
            "--with-private-files", str(protected), "--force")
        restored_path = bench / "sites" / restore_site / "site_config.json"
        restored = json.loads(restored_path.read_text())
        for key in ["encryption_key", "backup_encryption_key"]:
            if saved_config.get(key):
                restored[key] = saved_config[key]
        restored.update(allow_tests=True, fresko_browser_fixture_only=True, fresko_disposable_browser_site=True)
        restored_path.write_text(json.dumps(restored))
        restored_path.chmod(0o600)
        call(restore_site, "migrate")
        snapshot(restore_site, after)
        if before.read_bytes() != after.read_bytes():
            raise AssertionError(f"Restored protected records or source files differ; isolated destination {restore_site} retained for private inspection")
        report = {"synthetic_only": True, "source_site": site, "restore_site": restore_site,
            "fixture_snapshot_equal": True, "scope": "Selected protected records and two public/private sentinels", "record_counts": {key: len(value) for key, value in json.loads(before.read_text()).items() if isinstance(value, list)}, "restore_site_retained": True, "encryption_key_restored": bool(saved_config.get("encryption_key")),
            "backup_components": [{"component": path.name, "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths],
            "snapshot_sha256": hashlib.sha256(before.read_bytes()).hexdigest(),
            "hosting_recovery": "PENDING_Frappe_Cloud_access"}
        output.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            json.dump(report, stream, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench", type=Path, required=True)
    parser.add_argument("--site", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prove(args.bench, args.site, args.manifest, args.output)
