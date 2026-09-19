#!/usr/bin/env python3
"""Bump the integration version and commit it.

    python scripts/release.py 0.2.0

Then ``git push``. The Release workflow sees a manifest.json version without a release,
tags the commit v0.2.0 and publishes the GitHub release HACS picks up. No manual tagging.
The pyddm version in pyproject.toml is independent (it will follow its own PyPI releases)
and is not touched here.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "custom_components" / "dometic_ddm" / "manifest.json"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+.][0-9A-Za-z.-]+)?$")


def manifest_version() -> str:
    return str(json.loads(MANIFEST.read_text())["version"])


def write_manifest_version(version: str) -> None:
    data = json.loads(MANIFEST.read_text())
    data["version"] = version
    MANIFEST.write_text(json.dumps(data, indent=2) + "\n")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def bump(version: str) -> int:
    if not VERSION_RE.match(version):
        sys.stderr.write(f"not a semantic version: {version}\n")
        return 1
    current = manifest_version()
    if version == current:
        sys.stderr.write(f"manifest.json is already at {version}\n")
        return 1
    if _git("status", "--porcelain"):
        sys.stderr.write("working tree is not clean\n")
        return 1
    if _git("tag", "--list", f"v{version}"):
        sys.stderr.write(f"v{version} was already released\n")
        return 1
    write_manifest_version(version)
    _git("add", str(MANIFEST))
    _git("commit", "-q", "-m", f"chore(release): v{version}")
    sys.stdout.write(f"{current} → {version} committed. Now: git push\n")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 1 and not argv[0].startswith("-"):
        return bump(argv[0])
    sys.stderr.write(__doc__ or "")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
