# SharedSignals API Contract

> **Note**: This is an auto-generated capability snapshot. The authoritative API contract is `../API_CONTRACT.md`.
>
> Auto-generated from `capability_registry.json` at 2026-07-05T15:40:54+08:00
> Service: SharedSignals v1.0.0

## Summary

| Metric | Count |
|--------|-------|
| Total endpoints | 15 |
| OK | 12 |
| Degraded | 0 |
| Down | 0 |
| Skipped | 3 |

---

## Calendar

### [OK] `is_trading_day`

- **Status**: `ok`
- **Path**: `reference/market_calendar.py`
- **Version**: `1.0.0`
- **Latency**: 3.0ms
- **Rows returned**: 1
- **SLA**: 24h freshness
- **Fields**: date, result
- **Description**: Check if a given date is an A-share trading day
- **Last success**: 2026-07-05T15:40:54+08:00

### [OK] `get_trading_days`

- **Status**: `ok`
- **Path**: `reference/market_calendar.py`
- **Version**: `1.0.0`
- **Latency**: 9.7ms
- **Rows returned**: 4
- **SLA**: 24h freshness
- **Fields**: start, end, trading_days
- **Description**: Return all A-share trading days in a date range
- **Last success**: 2026-07-05T15:40:54+08:00

---

## Cross Border

### [SKIPPED] `get_hk_hold`

- **Status**: `skipped`
- **Path**: `reader.py`
- **Version**: `1.0.0`
- **Latency**: 0ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, vol, hold_vol, hold_ratio
- **Description**: Get northbound (HK->A) holdings for a trading day
- **Degraded reason**: HK/cross-border holdings are deferred for the current production trading scope

---

## Crypto

### [OK] `get_crypto_klines`

- **Status**: `ok`
- **Path**: `reader.py`
- **Version**: `1.0.0`
- **Latency**: 2.9ms
- **Rows returned**: 10
- **SLA**: 24h freshness
- **Fields**: symbol, trade_date, open, high, low, close, volume
- **Description**: Read Crypto OHLCV from the SharedSignals read model
- **Last success**: 2026-07-05T15:40:54+08:00

---

## Events

### [OK] `get_tushare_news`

- **Status**: `ok`
- **Path**: `reader.py`
- **Version**: `1.0.0`
- **Latency**: 14.5ms
- **Rows returned**: 233
- **SLA**: 24h freshness
- **Fields**: datetime, content, source, title
- **Description**: Read Tushare news from the SharedSignals read model
- **Last success**: 2026-07-05T15:40:54+08:00

### [PENDING REFRESH] `get_announcements`

- **Status**: `pending registry refresh`
- **Path**: `reader.py`
- **Description**: Read Tushare listed-company announcements from the SharedSignals read model

---

## Hk Market

### [SKIPPED] `get_hk_etf`

- **Status**: `skipped`
- **Path**: `reader.py`
- **Version**: `1.0.0`
- **Latency**: 0ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, open, high, low, close, vol
- **Description**: Read HK ETF daily data from unified marketdata DB
- **Degraded reason**: HK market lane is deferred

### [SKIPPED] `get_hk_index`

- **Status**: `skipped`
- **Path**: `reader.py`
- **Version**: `1.0.0`
- **Latency**: 0ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: symbol, trade_date, open, high, low, close, volume
- **Description**: Read HSI index data from unified marketdata DB
- **Degraded reason**: HK market lane is deferred

---

## Intraday

### [OK] `get_stock_minutes`

- **Status**: `ok`
- **Path**: `reader.py`
- **Version**: `1.0.0`
- **Latency**: 4.2ms
- **Rows returned**: 49
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_time, open, high, low, close, vol
- **Description**: Read intraday minute-level bars from the SharedSignals read model
- **Last success**: 2026-07-05T15:40:54+08:00

---

## Market Data

### [OK] `get_market_data`

- **Status**: `ok`
- **Path**: `reader.py`
- **Version**: `2.0.0`
- **Latency**: 5.0ms
- **Rows returned**: 1
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, open, high, low, close, vol, amount
- **Description**: Read A-share daily OHLCV data from the SharedSignals read model
- **Last success**: 2026-07-05T15:40:54+08:00

---

## Market Depth

### [OK] `get_moneyflow`

- **Status**: `ok`
- **Path**: `reader.py`
- **Version**: `1.0.0`
- **Latency**: 195.2ms
- **Rows returned**: 54
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, buy_sm_vol, sell_sm_vol, net_mf_vol
- **Description**: Read A-share money flow data from the SharedSignals read model
- **Last success**: 2026-07-05T15:40:54+08:00

### [OK] `get_margin`

- **Status**: `ok`
- **Path**: `reader.py`
- **Version**: `1.0.0`
- **Latency**: 181.2ms
- **Rows returned**: 12
- **SLA**: 24h freshness
- **Fields**: trade_date, rzye, rzmre, rqye, rqmcl
- **Description**: Read margin trading summary from the SharedSignals read model
- **Last success**: 2026-07-05T15:40:54+08:00

### [OK] `get_limit_list`

- **Status**: `ok`
- **Path**: `reader.py`
- **Version**: `1.0.0`
- **Latency**: 2.7ms
- **Rows returned**: 1
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, limit, pct_chg, close
- **Description**: Read limit-up/limit-down list from the SharedSignals read model
- **Last success**: 2026-07-05T15:40:54+08:00

---

## Prediction Markets

### [OK] `get_pm_markets`

- **Status**: `ok`
- **Path**: `reader.py`
- **Version**: `1.0.0`
- **Latency**: 8.5ms
- **Rows returned**: 50
- **SLA**: 24h freshness
- **Fields**: market_name, outcome, price, volume, updated_at
- **Description**: Read Polymarket market list from unified marketdata DB
- **Last success**: 2026-07-05T15:40:54+08:00

---

## Reference

### [OK] `get_reference`

- **Status**: `ok`
- **Path**: `reader.py`
- **Version**: `1.0.0`
- **Latency**: 2.8ms
- **Rows returned**: 12
- **SLA**: 24h freshness
- **Fields**: market, symbol_count, earliest_date, latest_date, status
- **Description**: Read data coverage status from unified marketdata DB
- **Last success**: 2026-07-05T15:40:54+08:00

---

## Us Market

### [OK] `get_us_daily`

- **Status**: `ok`
- **Path**: `reader.py`
- **Version**: `1.0.0`
- **Latency**: 2.5ms
- **Rows returned**: 1
- **SLA**: 24h freshness
- **Fields**: symbol, trade_date, open, high, low, close, volume
- **Description**: Read US stock daily data from the SharedSignals read model
- **Last success**: 2026-07-05T15:40:54+08:00

---

## All Endpoints

| Name | Status | Latency (ms) | Rows | SLA (h) | Category | Path |
|------|--------|-------------|------|---------|----------|------|
| `is_trading_day` | `ok` | 3.0 | 1 | - | calendar | `reference/market_calendar.py` |
| `get_trading_days` | `ok` | 9.7 | 4 | - | calendar | `reference/market_calendar.py` |
| `get_market_data` | `ok` | 5.0 | 1 | - | market_data | `reader.py` |
| `get_moneyflow` | `ok` | 195.2 | 54 | - | market_depth | `reader.py` |
| `get_margin` | `ok` | 181.2 | 12 | - | market_depth | `reader.py` |
| `get_limit_list` | `ok` | 2.7 | 1 | - | market_depth | `reader.py` |
| `get_hk_hold` | `skipped` | 0 | 0 | - | cross_border | `reader.py` |
| `get_stock_minutes` | `ok` | 4.2 | 49 | - | intraday | `reader.py` |
| `get_tushare_news` | `ok` | 14.5 | 233 | - | events | `reader.py` |
| `get_announcements` | `pending registry refresh` | - | - | - | events | `reader.py` |
| `get_crypto_klines` | `ok` | 2.9 | 10 | - | crypto | `reader.py` |
| `get_us_daily` | `ok` | 2.5 | 1 | - | us_market | `reader.py` |
| `get_hk_etf` | `skipped` | 0 | 0 | - | hk_market | `reader.py` |
| `get_hk_index` | `skipped` | 0 | 0 | - | hk_market | `reader.py` |
| `get_pm_markets` | `ok` | 8.5 | 50 | - | prediction_markets | `reader.py` |
| `get_reference` | `ok` | 2.8 | 12 | - | reference | `reader.py` |
