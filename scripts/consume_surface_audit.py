#!/usr/bin/env python3
"""Consume-surface audit — ensures sift-pdf does not reimplement codex geometry.

Mirrors compile-pdf's scripts/consume_surface_audit.py tripwire pattern.

Banned patterns (by symbol):
- Defining Box, Point, Polygon, Path, CellPlacement classes (re-declaration)
- Direct pyclipr imports outside the approved list
- Any polygon clipping logic that isn't delegated to codex_pdf.geom

Approved direct-codex imports (cite at use site in source):
- codex_pdf.geom: Box, CellPlacement, TileGrid, TileResult, tile_grid, MarksZone, GEOM_SCHEMA_VERSION
- codex_pdf.geom: polygon_intersect, polygon_union, polygon_difference, polygon_offset
- codex_pdf.errors: build_problem, problems, PROBLEM_CONTENT_TYPE, ProblemDetails
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src" / "sift_pdf"
REPORT_DIR = ROOT / "reports" / "audit"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# Codex surfaces that sift-pdf is allowed to import directly.
APPROVED_CODEX_IMPORTS: set[str] = {
    "codex_pdf.geom",
    "codex_pdf.geom.box",
    "codex_pdf.geom.tile",
    "codex_pdf.geom.path",
    "codex_pdf.geom.units",
    "codex_pdf.geom.matrix",
    "codex_pdf.errors",
    "codex_pdf",
}

# Names that must NOT be re-defined (owned by codex).
BANNED_CLASS_NAMES: set[str] = {"Box", "Point", "Polygon", "Path", "CellPlacement", "MarksZone"}

# Direct pyclipr imports are banned — use codex polygon ops.
BANNED_DIRECT_IMPORTS: set[str] = {"pyclipr"}

# Files exempt from the audit (e.g. this script itself).
EXEMPT_FILES: set[str] = {str(Path(__file__).resolve())}

findings: list[dict[str, object]] = []


def _check_file(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        findings.append({"file": str(path), "rule": "syntax-error", "detail": str(exc)})
        return

    for node in ast.walk(tree):
        # Check for banned class definitions
        if isinstance(node, ast.ClassDef) and node.name in BANNED_CLASS_NAMES:
            findings.append(
                {
                    "file": str(path),
                    "line": node.lineno,
                    "rule": "banned-class-redefinition",
                    "detail": f"Class '{node.name}' is owned by codex_pdf.geom — do not redefine.",
                }
            )

        # Check for banned direct imports
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = ""
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name.startswith(b) for b in BANNED_DIRECT_IMPORTS):
                        findings.append(
                            {
                                "file": str(path),
                                "line": node.lineno,
                                "rule": "banned-import",
                                "detail": f"Direct import of '{alias.name}' is banned — use codex_pdf.geom polygon ops.",
                            }
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if any(module.startswith(b) for b in BANNED_DIRECT_IMPORTS):
                    findings.append(
                        {
                            "file": str(path),
                            "line": node.lineno,
                            "rule": "banned-import",
                            "detail": f"Direct import from '{module}' is banned — use codex_pdf.geom polygon ops.",
                        }
                    )


def main() -> int:
    py_files = [p for p in SRC.rglob("*.py") if str(p.resolve()) not in EXEMPT_FILES]

    for path in sorted(py_files):
        _check_file(path)

    report = {
        "files_checked": len(py_files),
        "findings": findings,
        "status": "pass" if not findings else "fail",
    }
    report_path = REPORT_DIR / "consume_surface.json"
    report_path.write_text(json.dumps(report, indent=2))

    if findings:
        print(f"FAIL — {len(findings)} surface audit finding(s):")
        for f in findings:
            print(f"  {f['file']}:{f.get('line', '?')} [{f['rule']}] {f['detail']}")
        return 1

    print(f"OK — {len(py_files)} files checked, no violations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
