import json

from collectors import polymarket_collect as pm


def test_price_rows_use_outcome_prices():
    market = {
        "id": "m1",
        "clobTokenIds": json.dumps(["yes-token", "no-token"]),
        "outcomePrices": json.dumps(["0.62", "0.38"]),
        "outcomes": json.dumps(["Yes", "No"]),
    }

    rows = list(pm.price_rows(market, "2026-07-04T00:00:00+00:00"))

    assert len(rows) == 2
    assert rows[0][1] == "m1"
    assert rows[0][2] == "yes-token"
    assert rows[0][4] == 0.62
    assert json.loads(rows[0][8])["outcome"] == "Yes"


def test_price_rows_fallback_to_midpoint():
    market = {
        "id": "m2",
        "clobTokenIds": json.dumps(["yes-token", "no-token"]),
        "bestBid": 0.51,
        "bestAsk": 0.53,
    }

    rows = list(pm.price_rows(market, "2026-07-04T00:00:00+00:00"))

    assert [row[4] for row in rows] == [0.52, 0.48]
