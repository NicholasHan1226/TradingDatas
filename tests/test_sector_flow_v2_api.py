from __future__ import annotations

from typing import Any

import pytest

import api_server
import auth


class _SectorFlowReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @staticmethod
    def _rows(kind: str, runtime_status: str = "success") -> list[dict[str, Any]]:
        return [
            {
                "data": {"snapshot_id": "snap-1", "fact_kind": kind, "runtime_status": runtime_status},
                "provenance": {"source_id": "sqlite:market_sector_flow_snapshots_v2"},
                "freshness": {"available_at": "2026-07-14T10:31:00+08:00"},
                "quality": {"industry_coverage_ratio": 0.5},
                "degraded": runtime_status != "success",
                "degraded_reasons": [f"runtime {runtime_status}"] if runtime_status != "success" else [],
                "lineage": {"snapshot_id": "snap-1", "fact_kind": kind},
            }
        ]

    def get_snapshot(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("snapshot", kwargs))
        return self._rows(kwargs["fact_kind"], "unobserved")

    def get_industries(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("industries", kwargs))
        return self._rows(kwargs["fact_kind"])

    def get_constituents(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("constituents", kwargs))
        return self._rows(kwargs["fact_kind"])


@pytest.fixture()
def reader(monkeypatch: pytest.MonkeyPatch) -> _SectorFlowReader:
    fake = _SectorFlowReader()
    monkeypatch.setattr(api_server, "sector_flow_v2", fake)
    return fake


def _dispatch(path: str, params: dict[str, str]) -> dict[str, Any]:
    handler = object.__new__(api_server.Handler)
    return handler._dispatch(path, params)


def test_snapshot_route_preserves_runtime_five_state_semantics(reader: _SectorFlowReader) -> None:
    response = _dispatch(
        "/v2/sector-flow/snapshot",
        {"fact_kind": "intraday_proxy", "as_of": "2026-07-14T10:35:00+08:00"},
    )
    assert response["data"][0]["runtime_status"] == "unobserved"
    assert response["metadata"]["degraded"] is True
    assert response["metadata"]["degraded_reasons"] == ["runtime unobserved"]
    assert reader.calls == [
        (
            "snapshot",
            {
                "fact_kind": "intraday_proxy",
                "snapshot_id": None,
                "as_of": "2026-07-14T10:35:00+08:00",
            },
        )
    ]


def test_industries_route_forwards_filters(reader: _SectorFlowReader) -> None:
    _dispatch(
        "/v2/sector-flow/industries",
        {"fact_kind": "official_eod", "industry_code": "801080", "limit": "25"},
    )
    assert reader.calls[0] == (
        "industries",
        {
            "fact_kind": "official_eod",
            "snapshot_id": None,
            "as_of": None,
            "industry_code": "801080",
            "limit": 25,
        },
    )


def test_constituents_route_requires_industry_or_symbol(reader: _SectorFlowReader) -> None:
    with pytest.raises(ValueError, match="industry_code or symbol"):
        _dispatch("/v2/sector-flow/constituents", {"fact_kind": "official_eod"})


def test_sector_flow_v2_scope_is_exact_and_in_read_composites() -> None:
    expected = {
        "/v2/sector-flow/snapshot",
        "/v2/sector-flow/industries",
        "/v2/sector-flow/constituents",
    }
    assert auth.SCOPE_ENDPOINTS["sector_flow_v2"] == expected
    for path in expected:
        assert auth.check_endpoint_scope({"scopes": ["sector_flow_v2"]}, path)
        assert auth.check_endpoint_scope({"scopes": ["external_read"]}, path)
        assert auth.check_endpoint_scope({"scopes": ["read"]}, path)
    assert not auth.check_endpoint_scope(
        {"scopes": ["sector_flow_v2"]}, "/capital_flow"
    )
    assert not auth.check_endpoint_scope(
        {"scopes": ["status"]}, "/v2/sector-flow/snapshot"
    )
