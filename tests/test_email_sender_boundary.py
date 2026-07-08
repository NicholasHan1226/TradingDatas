from __future__ import annotations

from pathlib import Path


def test_email_sender_does_not_load_marketgraph_env() -> None:
    source = (Path(__file__).resolve().parents[1] / "tools" / "email_sender.py").read_text(encoding="utf-8")
    forbidden_env = "MARKET" + "GRAPH_ENV_FILE"
    forbidden_opt = "/opt/" + "marketgraph"
    forbidden_repo = "/opt/investment/" + "MarketGraph"

    assert forbidden_env not in source
    assert forbidden_opt not in source
    assert forbidden_repo not in source
    assert "SHAREDSIGNALS_ENV_FILE" in source
