"""Contract: every emitted v1 error code must be declared.

Regression guard for ``daily_limit_exceeded`` escaping ``_write_v1_error``
as an unhandled ``KeyError`` (found in review 2026-08-23).
"""

import re
from pathlib import Path

import api_server


def test_every_emitted_error_code_is_declared() -> None:
    source = Path(api_server.__file__).resolve().read_text(encoding="utf-8")
    emitted = set(re.findall(r'code="([a-z_]+)"', source))
    undeclared = sorted(emitted - set(api_server._V1_ERROR_DETAILS))
    assert undeclared == []


def test_daily_limit_exceeded_is_declared_retryable() -> None:
    message, retryable = api_server._V1_ERROR_DETAILS["daily_limit_exceeded"]
    assert message
    assert retryable is True
