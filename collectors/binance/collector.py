"""Binance Spot public market-data-only provider adapter.

It deliberately implements only public ``klines`` and ``exchangeInfo`` reads;
there is no account, testnet, order, or API-key surface.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from collectors.tushare.tushare_common import ProviderCallOutcome, SensitiveScanBudget
from provider_transport import BINANCE_SPOT_PUBLIC_API_URL


class _RejectRedirects(HTTPRedirectHandler):
    """Keep the public market-data origin pinned to the frozen endpoint."""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        del req, fp, code, msg, headers, newurl
        raise OSError("public market-data redirect rejected")


_PUBLIC_OPENER = build_opener(_RejectRedirects)
_PUBLIC_USDT_SYMBOL = re.compile(r"[A-Z0-9]{2,16}USDT")


def _api_symbol(api_name: str, prefix: str) -> str:
    if not api_name.startswith(prefix):
        raise ValueError("Binance API is not in the public market-data allowlist")
    symbol = api_name.removeprefix(prefix).upper()
    if _PUBLIC_USDT_SYMBOL.fullmatch(symbol) is None:
        raise ValueError("Binance API symbol is invalid")
    return symbol


def _rfc3339_to_ms(value: object) -> int:
    if type(value) is not str:
        raise ValueError("kline window must use RFC3339 timestamps")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("kline window must be timezone-aware")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _iso_ms(value: object) -> str:
    if type(value) is not int:
        raise ValueError("Binance timestamp must be an integer")
    return (
        datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class BinanceSpotPublicCollector:
    """No-auth, no-order adapter for the frozen public market-data cohort."""

    provider = "binance_spot"

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
            if api_name.startswith("klines_"):
                rows = self._klines(
                    params,
                    expected_symbol=_api_symbol(api_name, "klines_"),
                )
            elif api_name.startswith("bookTicker_"):
                rows = self._book_ticker(
                    params,
                    expected_symbol=_api_symbol(api_name, "bookTicker_"),
                )
            elif api_name.startswith("exchangeInfo_"):
                rows = self._exchange_info(
                    params,
                    expected_symbol=_api_symbol(api_name, "exchangeInfo_"),
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
    def _get(path: str, query: dict[str, str | int]) -> object:
        request = Request(
            f"{BINANCE_SPOT_PUBLIC_API_URL}{path}?{urlencode(query)}",
            headers={
                "Accept": "application/json",
                "User-Agent": "TradingDatas-Crypto-Canary/1",
            },
            method="GET",
        )
        with _PUBLIC_OPENER.open(request, timeout=10) as response:  # nosec B310
            if response.status != 200:
                raise OSError("unexpected public market-data status")
            if response.geturl() != request.full_url:
                raise OSError("public market-data origin changed")
            return json.loads(response.read().decode("utf-8"))

    def _klines(
        self,
        params: dict[str, Any],
        *,
        expected_symbol: str,
    ) -> list[dict[str, Any]]:
        symbol = params.get("symbol")
        if symbol != expected_symbol or params.get("interval") != "5m":
            raise ValueError("public kline symbol or interval does not match registry")
        start_ms = _rfc3339_to_ms(params.get("start_open_time"))
        end_ms = _rfc3339_to_ms(params.get("end_open_time"))
        if end_ms < start_ms or end_ms - start_ms > 3 * 24 * 60 * 60 * 1000:
            raise ValueError("one canary kline request is bounded to three days")
        payload = self._get(
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": "5m",
                "startTime": start_ms,
                "endTime": end_ms + 299_999,
                "limit": 1000,
            },
        )
        if type(payload) is not list:
            raise ValueError("Binance kline response is not an array")
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        rows: list[dict[str, Any]] = []
        for item in payload:
            if (
                type(item) is not list
                or len(item) != 12
                or not isinstance(item[0], int)
                or not isinstance(item[6], int)
            ):
                raise ValueError("Binance kline shape is invalid")
            if item[0] < start_ms or item[0] >= end_ms or item[6] >= now_ms:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "open_time_ms": item[0],
                    "open_time": _iso_ms(item[0]),
                    "open": item[1],
                    "high": item[2],
                    "low": item[3],
                    "close": item[4],
                    "volume": item[5],
                    "close_time_ms": item[6],
                    "close_time": _iso_ms(item[6]),
                    "quote_volume": item[7],
                    "trade_count": item[8],
                    "taker_buy_base_volume": item[9],
                    "taker_buy_quote_volume": item[10],
                    "ignore": item[11],
                }
            )
        return rows

    def _book_ticker(
        self,
        params: dict[str, Any],
        *,
        expected_symbol: str,
    ) -> list[dict[str, Any]]:
        if params != {"symbol": expected_symbol}:
            raise ValueError("public book ticker request does not match registry")
        payload = self._get("/api/v3/ticker/bookTicker", {"symbol": expected_symbol})
        required = ("symbol", "bidPrice", "bidQty", "askPrice", "askQty")
        if (
            type(payload) is not dict
            or payload.get("symbol") != expected_symbol
            or any(
                type(payload.get(name)) is not str or not payload[name]
                for name in required
            )
        ):
            raise ValueError("Binance book ticker shape is invalid")
        return [
            {
                "symbol": expected_symbol,
                "bid_price": payload["bidPrice"],
                "bid_qty": payload["bidQty"],
                "ask_price": payload["askPrice"],
                "ask_qty": payload["askQty"],
            }
        ]

    def _exchange_info(
        self,
        params: dict[str, Any],
        *,
        expected_symbol: str,
    ) -> list[dict[str, Any]]:
        symbol = params.get("symbol")
        if symbol != expected_symbol:
            raise ValueError("public symbol rule request does not match registry")
        payload = self._get("/api/v3/exchangeInfo", {"symbol": symbol})
        if (
            type(payload) is not dict
            or type(payload.get("symbols")) is not list
            or len(payload["symbols"]) != 1
        ):
            raise ValueError("Binance exchangeInfo shape is invalid")
        item = payload["symbols"][0]
        if (
            type(item) is not dict
            or item.get("symbol") != symbol
            or type(item.get("filters")) is not list
        ):
            raise ValueError("Binance symbol rule is invalid")
        filters = {
            entry.get("filterType"): entry
            for entry in item["filters"]
            if type(entry) is dict
        }
        price, lot = filters.get("PRICE_FILTER"), filters.get("LOT_SIZE")
        notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL")
        if (
            not isinstance(price, dict)
            or not isinstance(lot, dict)
            or not isinstance(notional, dict)
        ):
            raise ValueError("required Binance symbol filters are absent")
        return [
            {
                "symbol": symbol,
                "status": item.get("status"),
                "base_asset": item.get("baseAsset"),
                "quote_asset": item.get("quoteAsset"),
                "price_filter_tick_size": price.get("tickSize"),
                "lot_size_step_size": lot.get("stepSize"),
                "lot_size_min_qty": lot.get("minQty"),
                "min_notional": notional.get("minNotional"),
            }
        ]
