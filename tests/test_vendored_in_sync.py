"""custom_components/dometic_ddm/pyddm must be an exact copy of pyddm/."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_sync_script() -> object:
    spec = importlib.util.spec_from_file_location(
        "sync_vendored", ROOT / "scripts" / "sync_vendored.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vendored_copy_is_current() -> None:
    module = _load_sync_script()
    diff = module.differences()  # type: ignore[attr-defined]
    assert diff == [], "run `python scripts/sync_vendored.py`: " + "; ".join(diff)
