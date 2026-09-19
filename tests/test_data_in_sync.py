"""The JSON bundled in pyddm/data must be byte-identical to the source of truth in docs/."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["ddm1_cfx3_parameters.json", "ddm2_parameters.json"])
def test_bundled_table_matches_docs(name: str) -> None:
    docs = (ROOT / "docs" / name).read_bytes()
    bundled = (ROOT / "pyddm" / "data" / name).read_bytes()
    assert bundled == docs, f"pyddm/data/{name} differs from docs/{name}; copy docs → pyddm/data"
