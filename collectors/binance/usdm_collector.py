"""Binance USDⓈ-M Futures public market-data-only provider adapter.

It deliberately implements only the public ``fundingRate`` and
``openInterestHist`` history reads for the frozen USDT perpetual cohort;
there is no account, testnet, order, or API-key surface.
"""

from __future__ import annotations

from datetime import datetime, timezone
import http.client
import json
import socket
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from collectors.binance.collector import (
    _RejectRedirects,
    _api_symbol,
    _iso_ms,
    _rfc3339_to_ms,
)
from collectors.tushare.tushare_common import ProviderCallOutcome, SensitiveScanBudget
from provider_transport import BINANCE_USDM_PUBLIC_API_URL


def _recv_exactly(sock: "socket.socket", count: int) -> bytes:
    chunks = b""
    while len(chunks) < count:
        chunk = sock.recv(count - len(chunks))
        if not chunk:
            raise OSError("socks5 relay closed the connection early")
        chunks += chunk
    return chunks


class _Socks5HTTPSConnection(http.client.HTTPSConnection):
    """HTTPS through the owner-approved loopback SOCKS5 relay.

    The SOCKS5 CONNECT handshake is plain L4 tunneling: TLS is negotiated
    end-to-end with the target host afterwards, so the relay can only drop
    traffic, never read or modify it.  There is deliberately no direct-egress
    fallback.
    """

    def __init__(self, host: str, *, proxy: tuple[str, int], timeout: float):
        super().__init__(host, 443, timeout=timeout)
        self._proxy = proxy

    def connect(self) -> None:
        sock = socket.create_connection(self._proxy, timeout=self.timeout)
        try:
            sock.sendall(b"\x05\x01\x00")  # version 5, one method: no-auth
            if _recv_exactly(sock, 2) != b"\x05\x00":
                raise OSError("socks5 relay rejected no-auth negotiation")
            host = self.host.encode("idna")
            if len(host) > 255:
                raise OSError("socks5 target host is too long")
            sock.sendall(
                b"\x05\x01\x00\x03"
                + bytes([len(host)])
                + host
                + (443).to_bytes(2, "big")
            )
            reply = _recv_exactly(sock, 4)
            if reply[0] != 5 or reply[1] != 0:
                raise OSError("socks5 relay connect failed")
            atyp = reply[3]
            if atyp == 1:
                _recv_exactly(sock, 4)
            elif atyp == 3:
                _recv_exactly(sock, _recv_exactly(sock, 1)[0])
            elif atyp == 4:
                _recv_exactly(sock, 16)
            else:
                raise OSError("socks5 relay returned an invalid address type")
            _recv_exactly(sock, 2)  # bound port
        except Exception:
            sock.close()
            raise
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


_PUBLIC_OPENER = build_opener(_RejectRedirects)
_FUNDING_RATE_KEYS = frozenset({"symbol", "fundingTime", "fundingRate"})
_OPEN_INTEREST_KEYS = frozenset(
    {"symbol", "sumOpenInterest", "sumOpenInterestValue", "timestamp"}
)
_MAX_FUNDING_WINDOW_MS = 30 * 24 * 60 * 60 * 1000
_MAX_OPEN_INTEREST_WINDOW_MS = 24 * 60 * 60 * 1000


class BinanceUsdmPublicCollector:
    """No-auth, no-order adapter for the frozen USDT perpetual cohort."""

    provider = "binance_usdm"

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
            if api_name.startswith("fundingRate_"):
                rows = self._funding_rate(
                    params,
                    expected_symbol=_api_symbol(api_name, "fundingRate_"),
                )
            elif api_name.startswith("openInterestHist_"):
                rows = self._open_interest(
                    params,
                    expected_symbol=_api_symbol(api_name, "openInterestHist_"),
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
            f"{BINANCE_USDM_PUBLIC_API_URL}{path}?{urlencode(query)}",
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

    def _funding_rate(
        self,
        params: dict[str, Any],
        *,
        expected_symbol: str,
    ) -> list[dict[str, Any]]:
        symbol = params.get("symbol")
        if symbol != expected_symbol:
            raise ValueError("public funding-rate symbol does not match registry")
        start_ms = _rfc3339_to_ms(params.get("start_time"))
        end_ms = _rfc3339_to_ms(params.get("end_time"))
        if end_ms < start_ms or end_ms - start_ms > _MAX_FUNDING_WINDOW_MS:
            raise ValueError("one canary funding-rate request is bounded to thirty days")
        payload = self._get(
            "/fapi/v1/fundingRate",
            {
                "symbol": symbol,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 1000,
            },
        )
        if type(payload) is not list:
            raise ValueError("Binance funding-rate response is not an array")
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        rows: list[dict[str, Any]] = []
        for item in payload:
            if (
                type(item) is not dict
                or set(item) != _FUNDING_RATE_KEYS
                or item.get("symbol") != symbol
                or type(item.get("fundingTime")) is not int
                or type(item.get("fundingRate")) is not str
                or not item["fundingRate"]
            ):
                raise ValueError("Binance funding-rate shape is invalid")
            funding_time_ms = item["fundingTime"]
            if funding_time_ms < start_ms or funding_time_ms > end_ms or funding_time_ms >= now_ms:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "funding_time_ms": funding_time_ms,
                    "funding_time": _iso_ms(funding_time_ms),
                    "funding_rate": item["fundingRate"],
                }
            )
        return rows

    def _open_interest(
        self,
        params: dict[str, Any],
        *,
        expected_symbol: str,
    ) -> list[dict[str, Any]]:
        symbol = params.get("symbol")
        if symbol != expected_symbol or params.get("period") != "5m":
            raise ValueError("public open-interest symbol or period does not match registry")
        start_ms = _rfc3339_to_ms(params.get("start_time"))
        end_ms = _rfc3339_to_ms(params.get("end_time"))
        if end_ms < start_ms or end_ms - start_ms > _MAX_OPEN_INTEREST_WINDOW_MS:
            raise ValueError("one canary open-interest request is bounded to one day")
        payload = self._get(
            "/futures/data/openInterestHist",
            {
                "symbol": symbol,
                "period": "5m",
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 500,
            },
        )
        if type(payload) is not list:
            raise ValueError("Binance open-interest response is not an array")
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        rows: list[dict[str, Any]] = []
        for item in payload:
            if (
                type(item) is not dict
                or set(item) != _OPEN_INTEREST_KEYS
                or item.get("symbol") != symbol
                or type(item.get("timestamp")) is not int
                or type(item.get("sumOpenInterest")) is not str
                or not item["sumOpenInterest"]
                or type(item.get("sumOpenInterestValue")) is not str
                or not item["sumOpenInterestValue"]
            ):
                raise ValueError("Binance open-interest shape is invalid")
            timestamp_ms = item["timestamp"]
            if timestamp_ms < start_ms or timestamp_ms > end_ms or timestamp_ms >= now_ms:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp_ms": timestamp_ms,
                    "timestamp": _iso_ms(timestamp_ms),
                    "sum_open_interest": item["sumOpenInterest"],
                    "sum_open_interest_value": item["sumOpenInterestValue"],
                }
            )
        return rows


class BinanceUsdmRelayCollector(BinanceUsdmPublicCollector):
    """The same frozen USDⓈ-M cohort through the loopback SOCKS5 relay.

    Used only when direct egress to fapi.binance.com is blocked and the
    owner-approved relay profile is selected by the registry binding.  The
    allowlist, shape validation, and anti-redirect discipline are inherited
    unchanged; only the socket path differs.
    """

    provider = "binance_usdm_relay"
    _RELAY_PROXY = ("127.0.0.1", 17890)

    @staticmethod
    def _get(path: str, query: dict[str, str | int]) -> object:
        host = "fapi.binance.com"
        connection = _Socks5HTTPSConnection(
            host,
            proxy=BinanceUsdmRelayCollector._RELAY_PROXY,
            timeout=15,
        )
        try:
            connection.request(
                "GET",
                f"{path}?{urlencode(query)}",
                headers={
                    "Host": host,
                    "Accept": "application/json",
                    "User-Agent": "TradingDatas-Crypto-Canary/1",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                raise OSError("unexpected public market-data status")
            return json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
