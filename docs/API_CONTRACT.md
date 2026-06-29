# SharedSignals API Contract

> Auto-generated from `capability_registry.json` at 2026-06-30T02:32:08+08:00
> Service: SharedSignals v1.0.0

## Summary

| Metric | Count |
|--------|-------|
| Total endpoints | 15 |
| OK | 7 |
| Degraded | 8 |
| Down | 0 |

---

## Calendar

### [DEGRADED] `is_trading_day`

- **Status**: `degraded`
- **Path**: `reference/market_calendar.py`
- **Version**: `1.0.0`
- **Latency**: 0.1ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: date, result
- **Description**: Check if a given date is an A-share trading day
- **Last error**: `KeyError: 'token'`
- **Degraded reason**: Auth/config missing: KeyError: 'token'

### [DEGRADED] `get_trading_days`

- **Status**: `degraded`
- **Path**: `reference/market_calendar.py`
- **Version**: `1.0.0`
- **Latency**: 0.8ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: start, end, trading_days
- **Description**: Return all A-share trading days in a date range
- **Last error**: `KeyError: 'token'`
- **Degraded reason**: Auth/config missing: KeyError: 'token'

---

## Cross Border

### [DEGRADED] `get_hk_hold`

- **Status**: `degraded`
- **Path**: `reference/a_share_tushare_api.py`
- **Version**: `1.0.0`
- **Latency**: 0.0ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, vol, hold_vol, hold_ratio
- **Description**: Get northbound (HK->A) holdings for a trading day
- **Last error**: `KeyError: 'token'`
- **Degraded reason**: Auth/config missing: KeyError: 'token'

---

## Crypto

### [OK] `get_crypto_klines`

- **Status**: `ok`
- **Path**: `bridge/marketgraph_marketdata_db.py`
- **Version**: `1.0.0`
- **Latency**: 0.8ms
- **Rows returned**: 8
- **SLA**: 24h freshness
- **Fields**: symbol, trade_date, open, high, low, close, volume
- **Description**: Read Crypto daily OHLCV from unified marketdata DB
- **Last success**: 2026-06-30T02:32:08+08:00

---

## Events

### [DEGRADED] `get_news_list`

- **Status**: `degraded`
- **Path**: `reference/a_share_tushare_api.py`
- **Version**: `1.0.0`
- **Latency**: 0.0ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: datetime, content, source, title
- **Description**: Get news headlines for a date range
- **Last error**: `KeyError: 'token'`
- **Degraded reason**: Auth/config missing: KeyError: 'token'

---

## Hk Market

### [DEGRADED] `get_hk_etf`

- **Status**: `degraded`
- **Path**: `bridge/marketgraph_marketdata_db.py`
- **Version**: `1.0.0`
- **Latency**: 0.5ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, open, high, low, close, vol
- **Description**: Read HK ETF daily data from unified marketdata DB
- **Degraded reason**: Returned 0 rows (possibly stale or empty)

### [DEGRADED] `get_hk_index`

- **Status**: `degraded`
- **Path**: `bridge/marketgraph_marketdata_db.py`
- **Version**: `1.0.0`
- **Latency**: 0.6ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: symbol, trade_date, open, high, low, close, volume
- **Description**: Read HSI index data from unified marketdata DB
- **Degraded reason**: Returned 0 rows (possibly stale or empty)

---

## Intraday

### [DEGRADED] `get_stock_minutes`

- **Status**: `degraded`
- **Path**: `reference/a_share_tushare_api.py`
- **Version**: `1.0.0`
- **Latency**: 0.0ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_time, open, high, low, close, vol
- **Description**: Get intraday minute-level bars for a stock
- **Last error**: `KeyError: 'token'`
- **Degraded reason**: Auth/config missing: KeyError: 'token'

---

## Market Data

### [DEGRADED] `get_market_data`

- **Status**: `degraded`
- **Path**: `reference/a_share_tushare_api.py`
- **Version**: `2.0.0`
- **Latency**: 0.0ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, open, high, low, close, vol, amount
- **Description**: Get A-share daily OHLCV data for one or more stocks
- **Last error**: `KeyError: 'token'`
- **Degraded reason**: Auth/config missing: KeyError: 'token'

---

## Market Depth

### [OK] `get_moneyflow`

- **Status**: `ok`
- **Path**: `reference/a_share_tushare_api.py`
- **Version**: `1.0.0`
- **Latency**: 15.2ms
- **Rows returned**: 5193
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, buy_sm_vol, sell_sm_vol, net_mf_vol
- **Description**: Get A-share money flow data for a trading day
- **Last success**: 2026-06-30T02:32:08+08:00

### [OK] `get_margin`

- **Status**: `ok`
- **Path**: `reference/a_share_tushare_api.py`
- **Version**: `1.0.0`
- **Latency**: 0.1ms
- **Rows returned**: 2
- **SLA**: 24h freshness
- **Fields**: trade_date, rzye, rzmre, rqye, rqmcl
- **Description**: Get margin trading summary for a trading day
- **Last success**: 2026-06-30T02:32:08+08:00

### [OK] `get_limit_list`

- **Status**: `ok`
- **Path**: `reference/a_share_tushare_api.py`
- **Version**: `1.0.0`
- **Latency**: 0.2ms
- **Rows returned**: 60
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, limit, pct_chg, close
- **Description**: Get limit-up/limit-down list for a trading day
- **Last success**: 2026-06-30T02:32:08+08:00

---

## Prediction Markets

### [OK] `get_pm_markets`

- **Status**: `ok`
- **Path**: `bridge/marketgraph_marketdata_db.py`
- **Version**: `1.0.0`
- **Latency**: 0.9ms
- **Rows returned**: 50
- **SLA**: 24h freshness
- **Fields**: market_name, outcome, price, volume, updated_at
- **Description**: Read Polymarket market list from unified marketdata DB
- **Last success**: 2026-06-30T02:32:08+08:00

---

## Reference

### [OK] `get_reference`

- **Status**: `ok`
- **Path**: `bridge/marketgraph_marketdata_db.py`
- **Version**: `1.0.0`
- **Latency**: 8.4ms
- **Rows returned**: 200
- **SLA**: 24h freshness
- **Fields**: market, symbol_count, earliest_date, latest_date, status
- **Description**: Read data coverage status from unified marketdata DB
- **Last success**: 2026-06-30T02:32:08+08:00

---

## Us Market

### [OK] `get_us_daily`

- **Status**: `ok`
- **Path**: `bridge/marketgraph_marketdata_db.py`
- **Version**: `1.0.0`
- **Latency**: 0.6ms
- **Rows returned**: 1
- **SLA**: 24h freshness
- **Fields**: symbol, trade_date, open, high, low, close, volume
- **Description**: Read US stock daily data from unified marketdata DB
- **Last success**: 2026-06-30T02:32:08+08:00

---

## All Endpoints

| Name | Status | Latency (ms) | Rows | SLA (h) | Category | Path |
|------|--------|-------------|------|---------|----------|------|
| `is_trading_day` | `degraded` | 0.1 | 0 | - | calendar | `reference/market_calendar.py` |
| `get_trading_days` | `degraded` | 0.8 | 0 | - | calendar | `reference/market_calendar.py` |
| `get_market_data` | `degraded` | 0.0 | 0 | - | market_data | `reference/a_share_tushare_api.py` |
| `get_moneyflow` | `ok` | 15.2 | 5193 | - | market_depth | `reference/a_share_tushare_api.py` |
| `get_margin` | `ok` | 0.1 | 2 | - | market_depth | `reference/a_share_tushare_api.py` |
| `get_limit_list` | `ok` | 0.2 | 60 | - | market_depth | `reference/a_share_tushare_api.py` |
| `get_hk_hold` | `degraded` | 0.0 | 0 | - | cross_border | `reference/a_share_tushare_api.py` |
| `get_stock_minutes` | `degraded` | 0.0 | 0 | - | intraday | `reference/a_share_tushare_api.py` |
| `get_news_list` | `degraded` | 0.0 | 0 | - | events | `reference/a_share_tushare_api.py` |
| `get_crypto_klines` | `ok` | 0.8 | 8 | - | crypto | `bridge/marketgraph_marketdata_db.py` |
| `get_us_daily` | `ok` | 0.6 | 1 | - | us_market | `bridge/marketgraph_marketdata_db.py` |
| `get_hk_etf` | `degraded` | 0.5 | 0 | - | hk_market | `bridge/marketgraph_marketdata_db.py` |
| `get_hk_index` | `degraded` | 0.6 | 0 | - | hk_market | `bridge/marketgraph_marketdata_db.py` |
| `get_pm_markets` | `ok` | 0.9 | 50 | - | prediction_markets | `bridge/marketgraph_marketdata_db.py` |
| `get_reference` | `ok` | 8.4 | 200 | - | reference | `bridge/marketgraph_marketdata_db.py` |
