from __future__ import annotations

import argparse
import ctypes
import errno
import sys
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
from typing import Any

REPO_URL = "https://github.com/AnubhavDubey02/fresko-universe"
FRAPPE_DEP_SPEC = ">=15.0.0,<16.0.0"


def export_app(repo: Path, commit: str, destination: Path) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Commit must be a 40-character lowercase hex string")

    res = subprocess.run(
        ["git", "rev-parse", f"{commit}^{{commit}}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0 or res.stdout.strip() != commit:
        raise ValueError(f"Commit {commit} cannot be resolved to canonical commit SHA")

    origin = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo, capture_output=True, text=True)
    if origin.returncode or origin.stdout.strip().removesuffix(".git") not in (
        REPO_URL, "git@github.com:AnubhavDubey02/fresko-universe"
    ):
        raise ValueError("Expected Fresko source repository origin; remote details withheld")

    tree_res = subprocess.run(
        ["git", "rev-parse", f"{commit}:fresko_universe"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if tree_res.returncode != 0:
        raise ValueError(f"Cannot resolve tree for fresko_universe at {commit}")
    source_tree = tree_res.stdout.strip()

    if os.path.lexists(destination):
        raise FileExistsError(f"Destination already exists: {destination}")

    ls_res = subprocess.run(
        ["git", "ls-tree", "-r", "-z", commit, "--", "fresko_universe"],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if ls_res.returncode != 0:
        raise ValueError("git ls-tree failed to enumerate fresko_universe")

    entries: list[tuple[str, str, str]] = []
    for raw_entry in ls_res.stdout.split(b"\0"):
        if not raw_entry:
            continue
        entry = raw_entry.decode("utf-8", errors="surrogateescape")
        header, file_path = entry.split("\t", 1)
        mode, _, _ = header.split(" ", 2)

        if mode in ("120000", "160000") or mode not in ("100644", "100755"):
            raise ValueError(f"Unsupported Git entry mode {mode} for {file_path}")

        if not file_path.startswith("fresko_universe/"):
            raise ValueError(f"Path outside fresko_universe: {file_path}")

        rel_path = file_path[len("fresko_universe/"):]
        if not rel_path or ":" in rel_path or "\\" in rel_path or ".." in Path(rel_path).parts or rel_path.startswith("/"):
            raise ValueError(f"Invalid path encountered: {rel_path}")
        if rel_path == "FRESKO_DEPLOYMENT_MANIFEST.json":
            raise ValueError("Source tree collides with manifest filename FRESKO_DEPLOYMENT_MANIFEST.json")

        entries.append((file_path, rel_path, mode))

    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix=".tmp_export_", dir=destination.parent))

    try:
        file_records = []
        for file_path, rel_path, mode in entries:
            show_res = subprocess.run(
                ["git", "show", f"{commit}:{file_path}"],
                cwd=repo,
                capture_output=True,
                check=False,
            )
            if show_res.returncode != 0:
                raise ValueError(f"Failed to extract blob for {file_path}")
            data = show_res.stdout
            out_file = tmp_dir / rel_path
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(data)
            out_file.chmod(0o755 if mode == "100755" else 0o644)

            file_records.append({
                "path": rel_path,
                "source_path": file_path,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
                "mode": mode,
            })

        pyproject = tmp_dir / "pyproject.toml"
        if not pyproject.is_file():
            raise ValueError("Export root missing pyproject.toml")

        pkg_dir = tmp_dir / "fresko_universe"
        for required_file in ("__init__.py", "hooks.py", "modules.txt", "patches.txt"):
            if not (pkg_dir / required_file).is_file():
                raise ValueError(f"Package missing required file: {required_file}")

        metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        if metadata.get("project", {}).get("name") != "fresko_universe":
            raise ValueError("pyproject.toml project.name must be 'fresko_universe'")

        bench_deps = metadata.get("tool", {}).get("bench", {}).get("frappe-dependencies", {})
        if (
            bench_deps.get("frappe") != FRAPPE_DEP_SPEC
            or bench_deps.get("erpnext") != FRAPPE_DEP_SPEC
        ):
            raise ValueError(
                f"Missing or invalid bench dependencies. frappe and erpnext must both be '{FRAPPE_DEP_SPEC}'"
            )

        file_records.sort(key=lambda item: item["path"])
        manifest = {
            "format_version": 1,
            "source_repository": REPO_URL,
            "source_commit": commit,
            "source_subdirectory": "fresko_universe",
            "source_tree": source_tree,
            "files": file_records,
        }

        manifest_path = tmp_dir / "FRESKO_DEPLOYMENT_MANIFEST.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        for directory in [tmp_dir, *[p for p in tmp_dir.rglob("*") if p.is_dir()]]:
            directory.chmod(0o755)
        _rename_no_replace(tmp_dir, destination)
        return manifest
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def _rename_no_replace(source: Path, target: Path) -> None:
    """Atomic Linux publication that cannot clobber a concurrent destination."""
    if sys.platform != "linux":
        raise RuntimeError("Deployment exporter requires Linux and Python 3.11+")
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise RuntimeError("Atomic no-replace rename unavailable on this host")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1):
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise FileExistsError("Destination appeared during export")
        raise OSError(code, "Atomic deployment export failed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Frappe deployment package from Git SHA.")
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Path to Git repository root",
    )
    parser.add_argument("--commit", type=str, required=True, help="40-hex commit SHA")
    parser.add_argument("--output", type=Path, required=True, help="Target export directory")
    args = parser.parse_args()

    manifest = export_app(args.repo, args.commit, args.output)
    print(f"Commit: {manifest['source_commit']}")
    print(f"Tree: {manifest['source_tree']}")
    print(f"Files: {len(manifest['files'])}")
    print(f"Destination: {args.output.resolve()}")


if __name__ == "__main__":
    main()
