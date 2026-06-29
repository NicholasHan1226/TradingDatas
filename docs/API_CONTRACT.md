# SharedSignals API Contract

> Auto-generated from `capability_registry.json` at 2026-06-30T02:31:32+08:00
> Service: SharedSignals v1.0.0

## Summary

| Metric | Count |
|--------|-------|
| Total endpoints | 15 |
| OK | 7 |
| Degraded | 8 |
| Down | 0 |
| New this week | 12 |

---

## Uncategorized

### [DEGRADED] `is_trading_day`

- **Status**: `degraded`
- **Path**: `reference/market_calendar.py`
- **Version**: `1.0.0`
- **Latency**: 0.1ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: date, result
- **Description**: N/A
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
- **Description**: N/A
- **Last error**: `KeyError: 'token'`
- **Degraded reason**: Auth/config missing: KeyError: 'token'

### [DEGRADED] `get_market_data`

- **Status**: `degraded`
- **Path**: `reference/a_share_tushare_api.py`
- **Version**: `2.0.0`
- **Latency**: 0.0ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, open, high, low, close, vol, amount
- **Description**: N/A
- **Last error**: `KeyError: 'token'`
- **Degraded reason**: Auth/config missing: KeyError: 'token'

### [OK] `get_moneyflow`

- **Status**: `ok`
- **Path**: `reference/a_share_tushare_api.py`
- **Version**: `1.0.0`
- **Latency**: 15.9ms
- **Rows returned**: 5193
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, buy_sm_vol, sell_sm_vol, net_mf_vol
- **Description**: N/A
- **Last success**: 2026-06-30T02:31:32+08:00

### [OK] `get_margin`

- **Status**: `ok`
- **Path**: `reference/a_share_tushare_api.py`
- **Version**: `1.0.0`
- **Latency**: 0.6ms
- **Rows returned**: 2
- **SLA**: 24h freshness
- **Fields**: trade_date, rzye, rzmre, rqye, rqmcl
- **Description**: N/A
- **Last success**: 2026-06-30T02:31:32+08:00

### [OK] `get_limit_list`

- **Status**: `ok`
- **Path**: `reference/a_share_tushare_api.py`
- **Version**: `1.0.0`
- **Latency**: 0.7ms
- **Rows returned**: 60
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, limit, pct_chg, close
- **Description**: N/A
- **Last success**: 2026-06-30T02:31:32+08:00

### [DEGRADED] `get_hk_hold`

- **Status**: `degraded`
- **Path**: `reference/a_share_tushare_api.py`
- **Version**: `1.0.0`
- **Latency**: 0.0ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, vol, hold_vol, hold_ratio
- **Description**: N/A
- **Last error**: `KeyError: 'token'`
- **Degraded reason**: Auth/config missing: KeyError: 'token'

### [DEGRADED] `get_stock_minutes`

- **Status**: `degraded`
- **Path**: `reference/a_share_tushare_api.py`
- **Version**: `1.0.0`
- **Latency**: 0.0ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_time, open, high, low, close, vol
- **Description**: N/A
- **Last error**: `KeyError: 'token'`
- **Degraded reason**: Auth/config missing: KeyError: 'token'

### [DEGRADED] `get_news_list`

- **Status**: `degraded`
- **Path**: `reference/a_share_tushare_api.py`
- **Version**: `1.0.0`
- **Latency**: 0.0ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: datetime, content, source, title
- **Description**: N/A
- **Last error**: `KeyError: 'token'`
- **Degraded reason**: Auth/config missing: KeyError: 'token'

### [OK] `get_crypto_klines`

- **Status**: `ok`
- **Path**: `bridge/marketgraph_marketdata_db.py`
- **Version**: `1.0.0`
- **Latency**: 0.8ms
- **Rows returned**: 8
- **SLA**: 24h freshness
- **Fields**: symbol, trade_date, open, high, low, close, volume
- **Description**: N/A
- **Last success**: 2026-06-30T02:31:32+08:00

### [OK] `get_us_daily`

- **Status**: `ok`
- **Path**: `bridge/marketgraph_marketdata_db.py`
- **Version**: `1.0.0`
- **Latency**: 0.5ms
- **Rows returned**: 1
- **SLA**: 24h freshness
- **Fields**: symbol, trade_date, open, high, low, close, volume
- **Description**: N/A
- **Last success**: 2026-06-30T02:31:32+08:00

### [DEGRADED] `get_hk_etf`

- **Status**: `degraded`
- **Path**: `bridge/marketgraph_marketdata_db.py`
- **Version**: `1.0.0`
- **Latency**: 0.5ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: ts_code, trade_date, open, high, low, close, vol
- **Description**: N/A
- **Degraded reason**: Returned 0 rows (possibly stale or empty)

### [DEGRADED] `get_hk_index`

- **Status**: `degraded`
- **Path**: `bridge/marketgraph_marketdata_db.py`
- **Version**: `1.0.0`
- **Latency**: 0.5ms
- **Rows returned**: 0
- **SLA**: 24h freshness
- **Fields**: symbol, trade_date, open, high, low, close, volume
- **Description**: N/A
- **Degraded reason**: Returned 0 rows (possibly stale or empty)

### [OK] `get_pm_markets`

- **Status**: `ok`
- **Path**: `bridge/marketgraph_marketdata_db.py`
- **Version**: `1.0.0`
- **Latency**: 0.9ms
- **Rows returned**: 50
- **SLA**: 24h freshness
- **Fields**: market_name, outcome, price, volume, updated_at
- **Description**: N/A
- **Last success**: 2026-06-30T02:31:32+08:00

### [OK] `get_reference`

- **Status**: `ok`
- **Path**: `bridge/marketgraph_marketdata_db.py`
- **Version**: `1.0.0`
- **Latency**: 9.4ms
- **Rows returned**: 200
- **SLA**: 24h freshness
- **Fields**: market, symbol_count, earliest_date, latest_date, status
- **Description**: N/A
- **Last success**: 2026-06-30T02:31:32+08:00

---

## All Endpoints

| Name | Status | Latency (ms) | Rows | SLA (h) | Category | Path |
|------|--------|-------------|------|---------|----------|------|
| `is_trading_day` | `degraded` | 0.1 | 0 | - | - | `reference/market_calendar.py` |
| `get_trading_days` | `degraded` | 0.8 | 0 | - | - | `reference/market_calendar.py` |
| `get_market_data` | `degraded` | 0.0 | 0 | - | - | `reference/a_share_tushare_api.py` |
| `get_moneyflow` | `ok` | 15.9 | 5193 | - | - | `reference/a_share_tushare_api.py` |
| `get_margin` | `ok` | 0.6 | 2 | - | - | `reference/a_share_tushare_api.py` |
| `get_limit_list` | `ok` | 0.7 | 60 | - | - | `reference/a_share_tushare_api.py` |
| `get_hk_hold` | `degraded` | 0.0 | 0 | - | - | `reference/a_share_tushare_api.py` |
| `get_stock_minutes` | `degraded` | 0.0 | 0 | - | - | `reference/a_share_tushare_api.py` |
| `get_news_list` | `degraded` | 0.0 | 0 | - | - | `reference/a_share_tushare_api.py` |
| `get_crypto_klines` | `ok` | 0.8 | 8 | - | - | `bridge/marketgraph_marketdata_db.py` |
| `get_us_daily` | `ok` | 0.5 | 1 | - | - | `bridge/marketgraph_marketdata_db.py` |
| `get_hk_etf` | `degraded` | 0.5 | 0 | - | - | `bridge/marketgraph_marketdata_db.py` |
| `get_hk_index` | `degraded` | 0.5 | 0 | - | - | `bridge/marketgraph_marketdata_db.py` |
| `get_pm_markets` | `ok` | 0.9 | 50 | - | - | `bridge/marketgraph_marketdata_db.py` |
| `get_reference` | `ok` | 9.4 | 200 | - | - | `bridge/marketgraph_marketdata_db.py` |
