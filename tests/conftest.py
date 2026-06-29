"""Test-specific fixtures for SharedSignals test suite.

Root conftest fixtures (tmp_db, tmp_db_with_data, tmp_csv_dir, etc.)
are auto-discovered by pytest from the parent directory.
This file exists to allow test-specific overrides.
"""
from __future__ import annotations

from pathlib import Path
import sys

# Ensure SharedSignals root is importable from any cwd
_SHARED = Path(__file__).resolve().parent.parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
