#!/usr/bin/env python3
"""Fail CI on direct database writes to immutable Fresko truth DocTypes."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "fresko_universe" / "fresko_universe"
PROTECTED_DOCTYPES = {
    "Fresko Outward",
    "Fresko Field Assertion",
    "Fresko Container Quantity Assertion",
}
PROTECTED_TABLES = {f"tab{name}" for name in PROTECTED_DOCTYPES}
WRITE_SQL = re.compile(
    r"^\s*(?:UPDATE|INSERT|DELETE|REPLACE|ALTER|TRUNCATE|DROP)\b", re.I
)


def _call_name(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _static_text(node: ast.AST) -> tuple[str | None, bool]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, False
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        dynamic = False
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append("{dynamic}")
                dynamic = True
        return "".join(parts), dynamic
    return None, True


def scan_file(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        return [f"{path}: cannot scan Python source: {exc}"]
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name.endswith(".set_value"):
            target, dynamic = _static_text(node.args[0]) if node.args else (None, True)
            if dynamic or target in PROTECTED_DOCTYPES:
                violations.append(
                    f"{path}:{node.lineno}: direct db.set_value may write a protected DocType"
                )
        elif name.endswith(".db_set"):
            violations.append(
                f"{path}:{node.lineno}: direct Document.db_set bypass is forbidden in runtime code"
            )
        elif name.endswith(".sql") and node.args:
            sql, dynamic = _static_text(node.args[0])
            if sql and WRITE_SQL.search(sql):
                mentions_protected = any(table.lower() in sql.lower() for table in PROTECTED_TABLES)
                if mentions_protected or dynamic:
                    reason = "protected-table write SQL" if mentions_protected else "dynamic write SQL cannot be proven safe"
                    violations.append(f"{path}:{node.lineno}: {reason}")
    return violations


def runtime_python_files(root: Path = APP_ROOT) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if "tests" in relative.parts or "patches" in relative.parts:
            continue
        if path.name.startswith("test_") or path.name == "install.py":
            continue
        files.append(path)
    return sorted(files)


def scan_paths(paths: list[Path]) -> list[str]:
    return [violation for path in paths for violation in scan_file(path)]


def main() -> int:
    violations = scan_paths(runtime_python_files())
    if violations:
        print("Protected DocType write guard failed:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1
    print("Protected DocType write guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
