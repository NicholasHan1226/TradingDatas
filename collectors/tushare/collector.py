#!/usr/bin/env python3
"""Minimal generic Tushare provider transport adapter."""

from __future__ import annotations

import logging
import re
import urllib.error
from typing import Any, Callable

from .tushare_common import (
    ProviderCallOutcome,
    SensitiveScanBudget,
    get_token,
    provider_outcome_log_fields,
    safe_provider_exception_message,
    tushare_rows_outcome,
)


logger = logging.getLogger(__name__)
_SAFE_PARAM_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
_TUSHARE_CALL: Callable[..., ProviderCallOutcome] | None = None


class RequestBudgetExceeded(RuntimeError):
    """The process-wide scheduler request budget rejected a provider call."""


def _parameter_log_summary(params: dict[str, Any]) -> dict[str, Any]:
    """Describe parameter structure without retaining any parameter value."""

    keys = []
    for key in params:
        text = str(key)
        keys.append(
            text if _SAFE_PARAM_KEY.fullmatch(text) else "<untrusted-param-key>"
        )
    return {"param_count": len(params), "param_keys": tuple(sorted(set(keys)))}


def _call_tushare(
    api_name: str,
    params: dict[str, Any],
    fields: str | None = None,
    scan_budget: SensitiveScanBudget | None = None,
) -> ProviderCallOutcome:
    """Call the single approved transport using the file-backed token source."""

    if _TUSHARE_CALL is not None:
        if scan_budget is None:
            return _TUSHARE_CALL(api_name, params, fields)
        return _TUSHARE_CALL(api_name, params, fields, scan_budget)
    return tushare_rows_outcome(
        api_name,
        get_token(),
        params=params,
        fields=fields,
        scan_budget=scan_budget,
    )


class TushareCollector:
    """Ordinary generic collector with no dataset-specific behavior."""

    name = "tushare"
    provider = "tushare"

    def __init__(
        self,
        *,
        test_token: str | None = None,
        request_gate: Callable[[str], None] | None = None,
    ) -> None:
        if test_token is not None:
            if (
                type(test_token) is not str
                or not test_token
                or test_token != test_token.strip()
                or any(
                    ord(character) < 33 or ord(character) == 127
                    for character in test_token
                )
            ):
                raise ValueError("injected test token is invalid")
        if request_gate is not None and not callable(request_gate):
            raise TypeError("request_gate must be callable")
        self._test_token = test_token
        self._request_gate = request_gate
        self.last_collect_failed = False
        self.last_collect_error = ""
        self.last_collect_outcome: ProviderCallOutcome | None = None
        self.collect_call_count = 0
        self.collect_failure_count = 0

    def collect_outcome(
        self,
        api_name: str,
        params: dict[str, Any],
        fields: str | None = None,
        *,
        scan_budget: SensitiveScanBudget | None = None,
    ) -> ProviderCallOutcome:
        """Call one provider API and retain the strict typed outcome."""

        self.collect_call_count += 1
        self.last_collect_failed = False
        self.last_collect_error = ""
        candidate: Any = None
        try:
            if self._request_gate is not None:
                self._request_gate(api_name)
            logger.info(
                "collect %s with params=%s",
                api_name,
                _parameter_log_summary(params),
            )
            if self._test_token is None:
                if scan_budget is None:
                    candidate = _call_tushare(api_name, params, fields)
                else:
                    candidate = _call_tushare(api_name, params, fields, scan_budget)
            else:
                candidate = tushare_rows_outcome(
                    api_name,
                    self._test_token,
                    params=params,
                    fields=fields,
                    scan_budget=scan_budget,
                )
            if not isinstance(candidate, ProviderCallOutcome):
                raise TypeError("collector returned an invalid provider outcome type")
            candidate.validate_invariants()
            outcome = candidate
        except RequestBudgetExceeded:
            outcome = ProviderCallOutcome(
                state="failed",
                rows=(),
                provider_code=None,
                error_code="resource_budget",
                error_message="local rate budget exceeded",
                scan_budget=scan_budget,
            )
        except Exception as exc:
            transport = isinstance(
                exc,
                (
                    urllib.error.HTTPError,
                    urllib.error.URLError,
                    TimeoutError,
                    ConnectionError,
                    OSError,
                ),
            )
            outcome = ProviderCallOutcome(
                state="failed",
                rows=(),
                provider_code=None,
                error_code="transport_error" if transport else "provider_error",
                error_message=safe_provider_exception_message(
                    exc,
                    invalid_outcome=candidate is not None,
                ),
                scan_budget=scan_budget,
            )

        self.last_collect_outcome = outcome
        if outcome.state == "failed":
            self.last_collect_failed = True
            self.last_collect_error = (
                outcome.error_message or outcome.error_code or "provider call failed"
            )
            self.collect_failure_count += 1
            logger.error(
                "collect %s failed: outcome=%s",
                api_name,
                provider_outcome_log_fields(outcome),
            )
        else:
            logger.info(
                "collect %s -> %d rows (%s)", api_name, len(outcome.rows), outcome.state
            )
        return outcome
