"""Scaffolding test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    """Repository root directory."""
    return Path(__file__).resolve().parent.parent.parent
