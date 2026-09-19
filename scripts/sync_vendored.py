#!/usr/bin/env python3
"""Copy pyddm/ into custom_components/dometic_ddm/pyddm/ (HACS ships only that folder).

Run after changing anything under pyddm/. ``--check`` exits 1 if the copy is stale; the
test-suite runs the same check. Delete this once pyddm is published on PyPI and listed in
manifest.json ``requirements``.
"""

from __future__ import annotations

import filecmp
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "pyddm"
TARGET = ROOT / "custom_components" / "dometic_ddm" / "pyddm"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".mypy_cache")


def _files(base: Path) -> set[Path]:
    return {
        p.relative_to(base)
        for p in base.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }


def differences() -> list[str]:
    """Relative paths that differ between source and vendored copy."""
    if not TARGET.exists():
        return ["<vendored copy missing>"]
    src, dst = _files(SOURCE), _files(TARGET)
    out = [f"only in pyddm/: {p}" for p in sorted(src - dst)]
    out += [f"only in vendored copy: {p}" for p in sorted(dst - src)]
    out += [
        f"differs: {p}"
        for p in sorted(src & dst)
        if not filecmp.cmp(SOURCE / p, TARGET / p, shallow=False)
    ]
    return out


def sync() -> None:
    """Replace the vendored copy with the current source."""
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(SOURCE, TARGET, ignore=IGNORE)


def main(argv: list[str]) -> int:
    if "--check" in argv:
        diff = differences()
        if diff:
            sys.stderr.write("vendored pyddm is stale:\n  " + "\n  ".join(diff) + "\n")
            sys.stderr.write("run: python scripts/sync_vendored.py\n")
            return 1
        return 0
    sync()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
