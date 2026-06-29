"""Test-specific fixtures for SharedSignals test suite.

Re-exports root conftest fixtures and adds test-only helpers.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Import all root fixtures so pytest discovers them
_TEST_DIR = Path(__file__).resolve().parent
_SHARED = _TEST_DIR.parent

# Manually re-export fixtures from root conftest
# (pytest collects from parent dirs automatically, but explicit is safer)
pytest_plugins = ["conftest"]
