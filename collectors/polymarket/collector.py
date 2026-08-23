"""Public Polymarket Gamma snapshot collector draft.

This is deliberately a provider-level, read-only boundary.  It has one
allowlisted Gamma path (``GET /markets``), two injectable transports, bounded
offset pagination, and no trading, account, wallet, or order surface.

The module returns ``ProviderCallOutcome`` so a later reviewed integration can
reuse TradingDatas' transaction-scoped receipt writer.  Its standalone CLI is
only a draft harness: it writes an atomic JSON envelope on success, or an
atomic terminal receipt on failure; it never writes a partial capture.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from collectors.tushare.tushare_common import (
    ProviderCallOutcome,
    SensitiveScanBudget,
    safe_provider_exception_message,
)


POLYMARKET_RELAY_HOST_ENV = "POLYMARKET_RELAY_HOST"
POLYMARKET_RELAY_USER_ENV = "POLYMARKET_RELAY_USER"
GAMMA_API_URL = "https://gamma-api.polymarket.com"
_GAMMA_MARKETS_PATH = "/markets"
_ALLOWED_API_NAMES = frozenset({"market_snapshot"})
_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SSH_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}")
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_MAX_PAGE_SIZE = 100
_MAX_PAGES = 5
_MAX_TIMEOUT_SECONDS = 120
# The relay account's authorized_keys carries restrict + a forced-command
# wrapper whose sole input is the bare URL as the SSH remote command; the
# wrapper re-validates the URL against its own allowlist and runs curl
# itself.  argv form (no shell on either side), URL validated before use.
SSH_RELAY_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=10")


class JsonTransport(Protocol):
    """A bounded JSON GET boundary suitable for fake test transports."""

    def get_json(self, url: str, *, timeout_seconds: int) -> object: ...


@dataclass(frozen=True)
class StarterMarket:
    slug: str
    question: str
    category: str
    verification_required: bool


@dataclass(frozen=True)
class SnapshotReceipt:
    capture_id: str
    state: str
    provider: str
    api_name: str
    transport: str
    observed_at: str
    market_count: int
    snapshot_count: int
    error_code: str | None
    error_message: str | None


class DirectHttpTransport:
    """Development/test direct HTTPS transport; production should use relay."""

    def get_json(self, url: str, *, timeout_seconds: int) -> object:
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "TradingDatas/1"},
            method="GET",
        )
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
            if response.status != 200 or response.geturl() != url:
                raise OSError("unexpected Polymarket response status or origin")
            body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ValueError("Polymarket response exceeds the size budget")
        return json.loads(body.decode("utf-8"))


class SshRelayTransport:
    """Production relay transport using a fixed curl template and no shell."""

    name = "ssh_relay"

    def __init__(
        self,
        *,
        host: str,
        user: str | None = None,
        run_command: Callable[[list[str], int], bytes] | None = None,
    ) -> None:
        if _SSH_NAME_PATTERN.fullmatch(host) is None:
            raise ValueError("relay host is invalid")
        if user is not None and _SSH_NAME_PATTERN.fullmatch(user) is None:
            raise ValueError("relay user is invalid")
        self._destination = f"{user}@{host}" if user else host
        self._run_command = run_command or _run_ssh_command

    def command_for(self, url: str, *, timeout_seconds: int) -> list[str]:
        _validate_gamma_url(url)
        _validate_timeout(timeout_seconds)
        # The remote wrapper caps curl itself; the local subprocess timeout
        # (timeout_seconds + 5 in get_json) still bounds the whole call.
        del timeout_seconds
        return ["ssh", *SSH_RELAY_OPTIONS, self._destination, url]

    def get_json(self, url: str, *, timeout_seconds: int) -> object:
        completed = self._run_command(
            self.command_for(url, timeout_seconds=timeout_seconds), timeout_seconds + 5
        )
        if len(completed) > _MAX_RESPONSE_BYTES:
            raise ValueError("Polymarket relay response exceeds the size budget")
        return json.loads(completed.decode("utf-8"))


def _run_ssh_command(command: list[str], timeout_seconds: int) -> bytes:
    completed = subprocess.run(
        command,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=timeout_seconds,
    )
    return completed.stdout


def _validate_timeout(value: object) -> int:
    if type(value) is not int or not 1 <= value <= _MAX_TIMEOUT_SECONDS:
        raise ValueError("timeout_seconds is outside the frozen bounds")
    return value


def _validate_positive_int(value: object, name: str, maximum: int) -> int:
    if type(value) is str and re.fullmatch(r"[0-9]{1,9}", value):
        value = int(value)
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} is outside the frozen bounds")
    return value


def _require_text(value: object, name: str, *, max_chars: int = 4096) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > max_chars:
        raise ValueError(f"Polymarket {name} is invalid")
    return value


def _require_slug(value: object) -> str:
    slug = _require_text(value, "slug", max_chars=180)
    if _SLUG_PATTERN.fullmatch(slug) is None:
        raise ValueError("Polymarket slug is invalid")
    return slug


def _validate_gamma_url(url: str) -> None:
    expected_prefix = f"{GAMMA_API_URL}{_GAMMA_MARKETS_PATH}?"
    if not url.startswith(expected_prefix) or "'" in url or "\n" in url or "\r" in url:
        raise ValueError("Polymarket relay URL is outside the allowlist")


def _gamma_markets_url(*, slug: str, limit: int, offset: int) -> str:
    return (
        f"{GAMMA_API_URL}{_GAMMA_MARKETS_PATH}?"
        + urlencode({"slug": slug, "limit": limit, "offset": offset})
    )


def _as_json_list(value: object, name: str) -> list[object]:
    if type(value) is str:
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Polymarket {name} is invalid JSON") from exc
    if type(value) is not list:
        raise ValueError(f"Polymarket {name} must be an array")
    return value


def _as_number(value: object, name: str, *, probability: bool = False) -> float:
    if type(value) in (int, float):
        number = float(value)
    elif type(value) is str:
        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError(f"Polymarket {name} is not numeric") from exc
    else:
        raise ValueError(f"Polymarket {name} is not numeric")
    if not math.isfinite(number) or number < 0 or (probability and number > 1):
        raise ValueError(f"Polymarket {name} is outside valid bounds")
    return number


def _normalize_market(raw: object, *, selection: StarterMarket, captured_at: str) -> dict[str, Any]:
    if type(raw) is not dict:
        raise ValueError("Polymarket market item must be an object")
    question_id = _require_text(raw.get("id"), "id", max_chars=256)
    slug = _require_slug(raw.get("slug"))
    if slug != selection.slug:
        raise ValueError("Polymarket response slug does not match the requested market")
    question = _require_text(raw.get("question"), "question")
    outcomes = [_require_text(item, "outcome", max_chars=256) for item in _as_json_list(raw.get("outcomes"), "outcomes")]
    prices = [
        _as_number(item, "outcomePrices", probability=True)
        for item in _as_json_list(raw.get("outcomePrices"), "outcomePrices")
    ]
    if not outcomes or len(outcomes) != len(prices) or len(set(outcomes)) != len(outcomes):
        raise ValueError("Polymarket outcomes and outcomePrices do not match")
    end_date = _require_text(raw.get("endDate"), "endDate", max_chars=64)
    try:
        datetime.fromisoformat(end_date.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Polymarket endDate is invalid") from exc
    if type(raw.get("active")) is not bool or type(raw.get("closed")) is not bool:
        raise ValueError("Polymarket active/closed flags are invalid")
    resolution = raw.get("resolution", raw.get("resolvedOutcome", raw.get("outcome")))
    if resolution is not None and type(resolution) is not str:
        raise ValueError("Polymarket resolution is invalid")
    row = dict(raw)  # preserve provider-native fields for drift review.
    row.update(
        {
            "question_id": question_id,
            "slug": slug,
            "question": question,
            "category": selection.category,
            "end_date": end_date,
            "outcomes": outcomes,
            "outcome_prices": prices,
            "volume": _as_number(raw.get("volume"), "volume"),
            "liquidity": _as_number(raw.get("liquidity"), "liquidity"),
            "active": raw["active"],
            "closed": raw["closed"],
            "resolution": resolution,
            "captured_at": captured_at,
            "snapshot_id": hashlib.sha256(
                f"{question_id}|{captured_at}".encode("utf-8")
            ).hexdigest(),
            "selection_question": selection.question,
            "selection_verification_required": selection.verification_required,
        }
    )
    return row


class PolymarketSnapshotCollector:
    """Serializable Gamma collector for the draft ``pm.dataset.*`` family."""

    name = "polymarket"
    provider = "polymarket"

    def __init__(self, *, transport: JsonTransport, transport_name: str = "direct") -> None:
        self._transport = transport
        self._transport_name = _require_text(transport_name, "transport", max_chars=32)

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
            if api_name not in _ALLOWED_API_NAMES:
                raise ValueError("Polymarket API is not in the snapshot allowlist")
            allowed = {
                "slug",
                "question",
                "category",
                "lookback_hours",
                "page_size",
                "max_pages",
                "timeout_seconds",
            }
            if set(params) - allowed:
                raise ValueError("Polymarket params do not match the registry")
            selection = StarterMarket(
                slug=_require_slug(params.get("slug")),
                question=_require_text(params.get("question"), "question"),
                category=_require_text(params.get("category"), "category", max_chars=128),
                verification_required=True,
            )
            _validate_positive_int(params.get("lookback_hours", 24), "lookback_hours", 24 * 31)
            page_size = _validate_positive_int(params.get("page_size", 1), "page_size", _MAX_PAGE_SIZE)
            max_pages = _validate_positive_int(params.get("max_pages", 1), "max_pages", _MAX_PAGES)
            timeout_seconds = _validate_positive_int(
                params.get("timeout_seconds", 30), "timeout_seconds", _MAX_TIMEOUT_SECONDS
            )
            captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            rows: list[dict[str, Any]] = []
            for page_index in range(max_pages):
                payload = self._transport.get_json(
                    _gamma_markets_url(slug=selection.slug, limit=page_size, offset=page_index * page_size),
                    timeout_seconds=timeout_seconds,
                )
                if type(payload) is not list:
                    raise ValueError("Polymarket markets response must be an array")
                if len(payload) > page_size:
                    raise ValueError("Polymarket response exceeds requested page size")
                rows.extend(
                    _normalize_market(item, selection=selection, captured_at=captured_at)
                    for item in payload
                )
                if len(payload) < page_size:
                    break
            return ProviderCallOutcome(
                state="success" if rows else "empty",
                rows=tuple(rows),
                provider_code=0,
                error_code=None,
                error_message=None,
                scan_budget=scan_budget,
            )
        except Exception as exc:
            transport_error = isinstance(
                exc,
                (HTTPError, URLError, TimeoutError, ConnectionError, OSError, subprocess.SubprocessError),
            )
            return ProviderCallOutcome(
                state="failed",
                rows=(),
                provider_code=None,
                error_code="transport_error" if transport_error else "provider_error",
                error_message=safe_provider_exception_message(exc, invalid_outcome=not transport_error),
                scan_budget=scan_budget,
            )


def load_starter_markets(path: Path) -> tuple[StarterMarket, ...]:
    """Read JSON-form YAML (a YAML 1.2 subset) without a third-party parser."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("starter markets file is invalid") from exc
    if type(payload) is not dict or payload.get("version") != 1 or type(payload.get("markets")) is not list:
        raise ValueError("starter markets file does not match v1")
    markets: list[StarterMarket] = []
    for item in payload["markets"]:
        if type(item) is not dict or set(item) != {"slug", "question", "category", "verification_required"}:
            raise ValueError("starter market entry is invalid")
        markets.append(
            StarterMarket(
                slug=_require_slug(item["slug"]),
                question=_require_text(item["question"], "question"),
                category=_require_text(item["category"], "category", max_chars=128),
                verification_required=item["verification_required"] is True,
            )
        )
    if not markets or len({item.slug for item in markets}) != len(markets):
        raise ValueError("starter market slugs must be non-empty and unique")
    return tuple(markets)


def _write_json_atomically(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".pending-", delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _receipt(capture_id: str, outcome: ProviderCallOutcome, transport: str) -> SnapshotReceipt:
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return SnapshotReceipt(
        capture_id=capture_id,
        state=outcome.state,
        provider="polymarket",
        api_name="market_snapshot",
        transport=transport,
        observed_at=observed_at,
        market_count=len(outcome.rows),
        snapshot_count=len(outcome.rows),
        error_code=outcome.error_code,
        error_message=outcome.error_message,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--markets-file", type=Path, default=Path("config/polymarket_starter_markets.v1.yaml"))
    parser.add_argument("--lookback", "--lookback-hours", dest="lookback_hours", type=int, default=24)
    parser.add_argument("--page-size", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--transport", choices=("direct", "ssh_relay"), default="direct")
    parser.add_argument("--relay-host")
    parser.add_argument("--relay-user")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    capture_id = hashlib.sha256(
        f"{datetime.now(timezone.utc).isoformat()}|{args.markets_file}".encode("utf-8")
    ).hexdigest()
    try:
        _validate_timeout(args.timeout_seconds)
        markets = load_starter_markets(args.markets_file)
        if args.transport == "ssh_relay":
            host = args.relay_host or os.environ.get(POLYMARKET_RELAY_HOST_ENV)
            user = args.relay_user or os.environ.get(POLYMARKET_RELAY_USER_ENV)
            if not host:
                raise ValueError("relay host is required for ssh_relay")
            transport: JsonTransport = SshRelayTransport(host=host, user=user)
        else:
            transport = DirectHttpTransport()
        collector = PolymarketSnapshotCollector(transport=transport, transport_name=args.transport)
        all_rows: list[dict[str, Any]] = []
        for market in markets:
            outcome = collector.collect_outcome(
                "market_snapshot",
                {
                    "slug": market.slug,
                    "question": market.question,
                    "category": market.category,
                    "lookback_hours": args.lookback_hours,
                    "page_size": args.page_size,
                    "max_pages": args.max_pages,
                    "timeout_seconds": args.timeout_seconds,
                },
            )
            if outcome.state != "success":
                if outcome.state == "empty":
                    outcome = ProviderCallOutcome(
                        "failed",
                        (),
                        None,
                        "provider_error",
                        "Polymarket requested market returned no rows",
                    )
                receipt = _receipt(capture_id, outcome, args.transport)
                _write_json_atomically(args.out_root / "receipts" / f"{capture_id}.json", asdict(receipt))
                return 1
            all_rows.extend(outcome.mutable_rows())
        success = ProviderCallOutcome("success" if all_rows else "empty", tuple(all_rows), 0, None, None)
        receipt = _receipt(capture_id, success, args.transport)
        _write_json_atomically(
            args.out_root / "captures" / f"{capture_id}.json",
            {"receipt": asdict(receipt), "market_records": all_rows, "snapshot_records": all_rows},
        )
        return 0
    except Exception as exc:
        failed = ProviderCallOutcome(
            "failed", (), None, "provider_error", safe_provider_exception_message(exc, invalid_outcome=True)
        )
        receipt = _receipt(capture_id, failed, args.transport)
        _write_json_atomically(args.out_root / "receipts" / f"{capture_id}.json", asdict(receipt))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
