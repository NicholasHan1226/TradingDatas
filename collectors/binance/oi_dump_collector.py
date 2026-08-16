"""Binance USDⓈ-M public daily-dump provider adapter.

It deliberately implements only the public daily zip downloads from
``https://data.binance.vision`` for the frozen USDT perpetual cohort.  This is
the owner-approved degradation source while ``fapi.binance.com`` is blocked at
the SNI layer.  Two dump families are covered:

- ``metrics``: one zip per symbol per UTC day whose rows carry the same
  5-minute open-interest facts as ``openInterestHist``.
- ``premiumIndexKlines``: one 5-minute-kline zip per symbol per UTC day whose
  OHLC rows are the premium-index series — the main observable driver of
  funding-rate pressure, not the funding rate itself.

There is no account, testnet, order, or API-key surface, and funding rate
itself is not available from the dump at all.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import io
import math
from typing import Any
from urllib.request import Request, build_opener
from zipfile import ZipFile

from collectors.binance.collector import (
    _RejectRedirects,
    _api_symbol,
    _iso_ms,
)
from collectors.tushare.tushare_common import ProviderCallOutcome, SensitiveScanBudget
from provider_transport import BINANCE_USDM_DUMP_PUBLIC_DATA_URL


_PUBLIC_OPENER = build_opener(_RejectRedirects)
_METRICS_HEADER = (
    "create_time",
    "symbol",
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
)
_ROWS_PER_DAY = 288
_MAX_MEMBER_BYTES = 4 * 1024 * 1024
_PREMIUM_INTERVAL = "5m"
_PREMIUM_HEADER = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
)


def _utc_day(value: object) -> datetime:
    if type(value) is not str:
        raise ValueError("metrics-dump window must use a YYYY-MM-DD date")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError("metrics-dump window must use a YYYY-MM-DD date") from None
    if parsed.strftime("%Y-%m-%d") != value:
        raise ValueError("metrics-dump window must use a YYYY-MM-DD date")
    day = parsed.replace(tzinfo=timezone.utc)
    if day >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0):
        raise ValueError("metrics-dump date must be a fully closed UTC day")
    return day


def _metric_text(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("Binance metrics-dump numeric cell is empty")
    try:
        number = float(text)
    except ValueError:
        raise ValueError("Binance metrics-dump numeric cell is invalid") from None
    if not math.isfinite(number):
        raise ValueError("Binance metrics-dump numeric cell is invalid")
    return text


class BinanceUsdmMetricsDumpCollector:
    """No-auth, no-order adapter for the frozen daily metrics-dump cohort."""

    provider = "binance_usdm_dump"

    def collect_outcome(
        self,
        api_name: str,
        params: dict[str, Any],
        fields: str | None = None,
        *,
        scan_budget: SensitiveScanBudget | None = None,
    ) -> ProviderCallOutcome:
        del fields
        try:
            if api_name.startswith("metricsDump_"):
                rows = self._metrics_dump(
                    params,
                    expected_symbol=_api_symbol(api_name, "metricsDump_"),
                )
            elif api_name.startswith("premiumIndexKlinesDump_"):
                rows = self._premium_index_dump(
                    params,
                    expected_symbol=_api_symbol(api_name, "premiumIndexKlinesDump_"),
                )
            else:
                raise ValueError("Binance API is not in the public canary allowlist")
            return ProviderCallOutcome(
                state="success" if rows else "empty",
                rows=tuple(rows),
                provider_code=0,
                error_code=None,
                error_message=None,
                scan_budget=scan_budget,
            )
        except Exception as exc:
            return ProviderCallOutcome(
                state="failed",
                rows=(),
                provider_code=None,
                error_code="transport_error",
                error_message=type(exc).__name__,
                scan_budget=scan_budget,
            )

    @staticmethod
    def _get(path: str) -> bytes:
        request = Request(
            f"{BINANCE_USDM_DUMP_PUBLIC_DATA_URL}{path}",
            headers={
                "Accept": "application/zip",
                "User-Agent": "TradingDatas-Crypto-Canary/1",
            },
            method="GET",
        )
        with _PUBLIC_OPENER.open(request, timeout=30) as response:  # nosec B310
            if response.status != 200:
                raise OSError("unexpected public metrics-dump status")
            if response.geturl() != request.full_url:
                raise OSError("public metrics-dump origin changed")
            payload = response.read(_MAX_MEMBER_BYTES + 1)
        if len(payload) > _MAX_MEMBER_BYTES:
            raise OSError("public metrics-dump payload exceeds the bounded size")
        return payload

    @staticmethod
    def _probe(path: str) -> bool:
        request = Request(
            f"{BINANCE_USDM_DUMP_PUBLIC_DATA_URL}{path}",
            headers={"User-Agent": "TradingDatas-Crypto-Canary/1"},
            method="HEAD",
        )
        try:
            with _PUBLIC_OPENER.open(request, timeout=10) as response:  # nosec B310
                if response.geturl() != request.full_url:
                    return False
                return response.status == 200
        except Exception:
            return False

    @staticmethod
    def probe_published(*, symbol: str, day: str) -> bool:
        """HEAD whether one daily metrics zip is already published.

        Publication of the daily dump lags the UTC day close by hours; probing
        before an ingest attempt keeps that expected lag from polluting the
        receipt chain (and therefore the dataset runtime state) with failed
        attempts.  Any transport error is reported as unpublished; the next
        timer tick simply probes again.
        """

        date_text = _utc_day(day).strftime("%Y-%m-%d")
        return BinanceUsdmMetricsDumpCollector._probe(
            f"/data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{date_text}.zip"
        )

    @staticmethod
    def probe_premium_index_published(*, symbol: str, day: str) -> bool:
        """HEAD whether one daily premiumIndexKlines zip is already published.

        Same publication-lag contract as ``probe_published``: any transport
        error is reported as unpublished and retried by the next timer tick.
        """

        date_text = _utc_day(day).strftime("%Y-%m-%d")
        return BinanceUsdmMetricsDumpCollector._probe(
            f"/data/futures/um/daily/premiumIndexKlines/{symbol}/"
            f"{_PREMIUM_INTERVAL}/{symbol}-{_PREMIUM_INTERVAL}-{date_text}.zip"
        )

    def _metrics_dump(
        self,
        params: dict[str, Any],
        *,
        expected_symbol: str,
    ) -> list[dict[str, Any]]:
        symbol = params.get("symbol")
        if symbol != expected_symbol or set(params) != {"symbol", "date"}:
            raise ValueError("public metrics-dump request does not match registry")
        day = _utc_day(params.get("date"))
        date_text = day.strftime("%Y-%m-%d")
        payload = self._get(
            f"/data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{date_text}.zip"
        )
        rows = self._parse(payload, symbol=symbol, day=day)
        return rows

    @staticmethod
    def _parse(
        payload: bytes,
        *,
        symbol: str,
        day: datetime,
    ) -> list[dict[str, Any]]:
        date_text = day.strftime("%Y-%m-%d")
        member_name = f"{symbol}-metrics-{date_text}.csv"
        try:
            archive = ZipFile(io.BytesIO(payload))
        except Exception:
            raise ValueError("Binance metrics-dump payload is not a zip") from None
        with archive:
            names = archive.namelist()
            if names != [member_name]:
                raise ValueError("Binance metrics-dump zip member is unexpected")
            info = archive.getinfo(member_name)
            if info.file_size > _MAX_MEMBER_BYTES or info.file_size == 0:
                raise ValueError("Binance metrics-dump member size is unexpected")
            with archive.open(member_name) as member:
                text = io.TextIOWrapper(member, encoding="utf-8", newline="")
                records = list(csv.reader(text))
        if not records or tuple(records[0]) != _METRICS_HEADER:
            raise ValueError("Binance metrics-dump header is invalid")
        body = records[1:]
        if len(body) != _ROWS_PER_DAY:
            raise ValueError("Binance metrics-dump day is not a complete 5m grid")
        # The dump's grid phase is not frozen by the provider: some days run
        # 00:00-23:55, others 00:05-next-day 00:00.  Accept any complete,
        # consecutive, duplicate-free 5-minute grid inside [day, day+1d].
        day_start_ms = int(day.timestamp() * 1000)
        day_end_ms = int((day + timedelta(days=1)).timestamp() * 1000)
        seen_ms: set[int] = set()
        rows: list[dict[str, Any]] = []
        for record in body:
            if len(record) != len(_METRICS_HEADER) or record[1] != symbol:
                raise ValueError("Binance metrics-dump row shape is invalid")
            create_time = record[0]
            try:
                timestamp_ms = int(
                    datetime.strptime(create_time, "%Y-%m-%d %H:%M:%S")
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                    * 1000
                )
            except ValueError:
                raise ValueError("Binance metrics-dump timestamp is invalid") from None
            if (
                timestamp_ms < day_start_ms
                or timestamp_ms > day_end_ms
                or (timestamp_ms - day_start_ms) % 300_000 != 0
                or timestamp_ms in seen_ms
            ):
                raise ValueError("Binance metrics-dump timestamp is outside the day grid")
            seen_ms.add(timestamp_ms)
            open_interest = _metric_text(record[2])
            open_interest_value = _metric_text(record[3])
            for cell in record[4:]:
                _metric_text(cell)
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp_ms": timestamp_ms,
                    "timestamp": _iso_ms(timestamp_ms),
                    "sum_open_interest": open_interest,
                    "sum_open_interest_value": open_interest_value,
                }
            )
        # 288 unique, aligned, in-range 5m marks: the day grid is complete up
        # to the provider's phase-shift convention (one endpoint omitted).
        rows.sort(key=lambda row: row["timestamp_ms"])
        return rows

    def _premium_index_dump(
        self,
        params: dict[str, Any],
        *,
        expected_symbol: str,
    ) -> list[dict[str, Any]]:
        symbol = params.get("symbol")
        if symbol != expected_symbol or set(params) != {"symbol", "date"}:
            raise ValueError("public premium-index dump request does not match registry")
        day = _utc_day(params.get("date"))
        date_text = day.strftime("%Y-%m-%d")
        payload = self._get(
            f"/data/futures/um/daily/premiumIndexKlines/{symbol}/"
            f"{_PREMIUM_INTERVAL}/{symbol}-{_PREMIUM_INTERVAL}-{date_text}.zip"
        )
        return self._parse_premium(payload, symbol=symbol, day=day)

    @staticmethod
    def _parse_premium(
        payload: bytes,
        *,
        symbol: str,
        day: datetime,
    ) -> list[dict[str, Any]]:
        date_text = day.strftime("%Y-%m-%d")
        member_name = f"{symbol}-{_PREMIUM_INTERVAL}-{date_text}.csv"
        try:
            archive = ZipFile(io.BytesIO(payload))
        except Exception:
            raise ValueError("Binance premium-index dump payload is not a zip") from None
        with archive:
            names = archive.namelist()
            if names != [member_name]:
                raise ValueError("Binance premium-index dump zip member is unexpected")
            info = archive.getinfo(member_name)
            if info.file_size > _MAX_MEMBER_BYTES or info.file_size == 0:
                raise ValueError("Binance premium-index dump member size is unexpected")
            with archive.open(member_name) as member:
                text = io.TextIOWrapper(member, encoding="utf-8", newline="")
                records = list(csv.reader(text))
        if not records or tuple(records[0]) != _PREMIUM_HEADER:
            raise ValueError("Binance premium-index dump header is invalid")
        body = records[1:]
        if len(body) != _ROWS_PER_DAY:
            raise ValueError("Binance premium-index dump day is not a complete 5m grid")
        day_start_ms = int(day.timestamp() * 1000)
        expected = {
            day_start_ms + 300_000 * index for index in range(_ROWS_PER_DAY)
        }
        rows: list[dict[str, Any]] = []
        for record in body:
            if len(record) != len(_PREMIUM_HEADER):
                raise ValueError("Binance premium-index dump row shape is invalid")
            try:
                open_time_ms = int(record[0])
                close_time_ms = int(record[6])
            except ValueError:
                raise ValueError(
                    "Binance premium-index dump timestamp cell is invalid"
                ) from None
            if open_time_ms not in expected:
                raise ValueError(
                    "Binance premium-index dump open time is outside the day"
                )
            expected.discard(open_time_ms)
            if close_time_ms != open_time_ms + 299_999:
                raise ValueError(
                    "Binance premium-index dump close time is inconsistent"
                )
            open_value = _metric_text(record[1])
            high_value = _metric_text(record[2])
            low_value = _metric_text(record[3])
            close_value = _metric_text(record[4])
            for cell in record[5:6] + record[7:]:
                _metric_text(cell)
            rows.append(
                {
                    "symbol": symbol,
                    "open_time_ms": open_time_ms,
                    "open_time": _iso_ms(open_time_ms),
                    "close_time_ms": close_time_ms,
                    "close_time": _iso_ms(close_time_ms),
                    "open": open_value,
                    "high": high_value,
                    "low": low_value,
                    "close": close_value,
                }
            )
        if expected:
            raise ValueError(
                "Binance premium-index dump day is not a complete 5m grid"
            )
        rows.sort(key=lambda row: row["open_time_ms"])
        return rows
