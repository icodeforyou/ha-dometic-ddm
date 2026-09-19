#!/usr/bin/env python3
"""Cut a release: bump manifest.json version, commit, tag.

    python scripts/release.py 0.2.0            # bump + commit + tag v0.2.0
    python scripts/release.py --check v0.2.0   # exit 1 unless manifest version == 0.2.0

Then ``git push && git push --tags``; .github/workflows/release.yml publishes the GitHub
release HACS picks up. The pyddm version in pyproject.toml is independent (it will follow
its own PyPI releases) and is not touched here.
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


def check(tag: str) -> int:
    version = tag.removeprefix("v")
    current = manifest_version()
    if version != current:
        sys.stderr.write(f"tag {tag} does not match manifest.json version {current}\n")
        return 1
    return 0


def bump(version: str) -> int:
    if not VERSION_RE.match(version):
        sys.stderr.write(f"not a semantic version: {version}\n")
        return 1
    tag = f"v{version}"
    if subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout:
        sys.stderr.write("working tree is not clean\n")
        return 1
    if subprocess.run(
        ["git", "tag", "--list", tag], capture_output=True, text=True, check=True
    ).stdout:
        sys.stderr.write(f"tag {tag} already exists\n")
        return 1
    write_manifest_version(version)
    subprocess.run(["git", "add", str(MANIFEST)], check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"chore(release): {tag}"], check=True)
    subprocess.run(["git", "tag", "-a", tag, "-m", f"Release {tag}"], check=True)
    sys.stdout.write(f"{tag} tagged. Now: git push && git push --tags\n")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--check":
        return check(argv[1])
    if len(argv) == 1 and not argv[0].startswith("-"):
        return bump(argv[0])
    sys.stderr.write(__doc__ or "")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
