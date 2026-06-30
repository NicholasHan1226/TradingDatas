# SharedSignals API Contract

> **版本**: 1.1.0 | **状态**: active | **边界**: 只读数据接口，研究线和交易线共享读取

---

## 目录

1. [概述](#概述)
2. [数据字典](#数据字典)
3. [Reader 函数](#reader-函数)
   - [市场数据读取](#市场数据读取)
   - [事件和信号](#事件和信号)
   - [预测市场](#预测市场)
   - [Crypto 市场](#crypto-市场)
   - [元数据和健康检查](#元数据和健康检查)
4. [Freshness / Quality 元数据](#freshness--quality-元数据)
5. [错误处理指南](#错误处理指南)
6. [版本策略](#版本策略)

---

## 概述

SharedSignals 提供统一的只读数据访问层。所有消费者（Tradings、MarketGraph、研究工具）通过以下两个入口读取数据：

| 入口 | 实现文件 | 适用场景 |
|------|---------|---------|
| **SQLite Read Model** | `bridge/marketgraph_marketdata_db.py` | 直接 Python import，用于 cron 任务 / 批处理 / 本地脚本 |
| **MCP Server (34 tools)** | `MarketGraph/08-Market-Interfaces/tools/marketgraph_mcp_server.py` | 远程 agent / 外部进程通过 stdio JSON-RPC 调用 |

本文档聚焦 **SQLite Read Model** 的 Python 函数接口。MCP 工具的参数映射见[附录](#附录-mcp-工具映射)。

### 存储概览

```
marketdata.sqlite (11 表)
├── market_assets              —— 品种主表
├── market_bars_daily          —— 日线 OHLCV
├── market_bars_intraday       —— 分钟线 OHLCV
├── market_events              —— 新闻/事件流
├── market_pm_markets          —— 预测市场元数据
├── market_pm_prices           —— 预测市场价格快照
├── market_factors             —— 派生因子
├── market_ingest_runs         —— 采集运行审计
├── market_coverage_status     —— 逐股覆盖状态
├── market_backfill_status     —— 回填进度
└── provider_interface_matrix  —— 数据源能力注册
```

---

## 数据字典

### market 枚举

| market | 含义 | 数据源 |
|--------|------|--------|
| `Ashare` | A 股 | Tushare (60+ 接口) — SharedSignals now has native Tushare collector via `reader.get_tushare()` |
| `HK` | 港股 | A 股 ETF 代理 (6 ETF + HSI) |
| `US` | 美股 | Tushare 美股接口 / Alpaca |
| `Crypto` | 加密 | Binance (4 接口) |
| `PredictionMarkets` | 预测市场 | Polymarket (3 接口) |

### 核心表字段

#### market_bars_daily (日线)

| 字段 | 类型 | 说明 |
|------|------|------|
| `market` | TEXT | 市场代码 |
| `symbol` | TEXT | 品种代码 |
| `trade_date` | TEXT | 交易日 YYYYMMDD |
| `open` / `high` / `low` / `close` | REAL | OHLC 价格 |
| `volume` | REAL | 成交量 |
| `amount` | REAL | 成交额 |
| `provider` | TEXT | 数据源 (tushare / binance / polymarket) |
| `source_file` | TEXT | 来源 CSV 路径 |
| `collected_at` | TEXT | 采集时间 ISO8601 |
| `raw_json` | TEXT | 原始响应 JSON |

#### market_events (事件)

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_hash` | TEXT PK | 事件唯一哈希 |
| `provider` | TEXT | 来源 (rss / tavily / agents) |
| `event_type` | TEXT | 事件类型 |
| `event_time` | TEXT | 事件时间 |
| `market` | TEXT | 相关市场 |
| `symbol` | TEXT | 相关品种 |
| `title` | TEXT | 标题 |
| `content` | TEXT | 内容 |
| `url` | TEXT | 来源 URL |
| `source` | TEXT | 源名称 |
| `collected_at` | TEXT | 采集时间 |

#### market_coverage_status (覆盖状态)

| 字段 | 类型 | 说明 |
|------|------|------|
| `market` | TEXT | 市场 |
| `trade_date` | TEXT | 交易日 |
| `symbol` | TEXT | 品种 |
| `coverage_status` | TEXT | 状态: `bar_present` / `missing` / `suspended` / `delisted` / `no_data` |
| `reason` | TEXT | 缺失原因 |

---

## Reader 函数

所有 reader 函数位于 `bridge/marketgraph_marketdata_db.py`，以及辅助的 `reference/market_calendar.py`。

### 市场数据读取

#### `read_daily(market, symbol="", start_date="", end_date="", limit=200)`

读取日线 OHLCV 行情数据。

**参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `market` | `str` | 必填 | 市场代码: `Ashare` / `US` / `Crypto` 等 |
| `symbol` | `str` | `""` | 品种代码。为空返回市场全部 |
| `start_date` | `str` | `""` | 起始日期 YYYYMMDD 或 YYYY-MM-DD |
| `end_date` | `str` | `""` | 截止日期 |
| `limit` | `int` | `200` | 最大返回行数 (上限 5000) |

**返回**: `list[dict]` — 按 `trade_date` 升序排列的日线记录

**示例**:
```python
from marketgraph_marketdata_db import read_daily

# BTC 最近 30 个交易日
rows = read_daily("Crypto", symbol="BTCUSDT", limit=30)
for row in rows:
    print(f"{row['trade_date']}: O={row['open']} C={row['close']}")

# A 股某标的 6 月行情
rows = read_daily("Ashare", symbol="600519.SH", start_date="20260601", end_date="20260630")
```

**错误处理**: 参数无效时静默返回空列表 `[]`；DB 不可访问时抛出 `sqlite3.OperationalError`。

---

#### `read_intraday(market, symbol="", trade_date="", interval="", limit=200)`

读取分钟/小时级 OHLCV。

**参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `market` | `str` | 必填 | 市场代码 |
| `symbol` | `str` | `""` | 品种代码 |
| `trade_date` | `str` | `""` | 交易日 |
| `interval` | `str` | `""` | 周期: `1min` / `5min` / `15min` / `30min` / `60min` |
| `limit` | `int` | `200` | 最大返回行数 (上限 5000) |

**返回**: `list[dict]` — 按 `bar_time` 升序排列

**示例**:
```python
from marketgraph_marketdata_db import read_intraday

# 今日 A 股 1 分钟线
rows = read_intraday("Ashare", symbol="600519.SH", trade_date="20260630", interval="1min")
```

---

### 事件和信号

#### `read_events(provider="", event_type="", limit=200)`

读取新闻/事件流。

**参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `provider` | `str` | `""` | 来源: `rss` / `tavily` / `agents` |
| `event_type` | `str` | `""` | 事件类型 |
| `limit` | `int` | `200` | 最大返回行数 (上限 5000) |

**返回**: `list[dict]` — 按 `collected_at` 降序排列

**示例**:
```python
from marketgraph_marketdata_db import read_events

# 最近 100 条 RSS 事件
events = read_events(provider="rss", limit=100)
```

---

### 预测市场

#### `read_pm_markets(limit=100)`

读取 Polymarket 预测市场列表。

**返回**: `list[dict]` — 按 `collected_at` 降序 + `volume` 降序

**示例**:
```python
from marketgraph_marketdata_db import read_pm_markets
markets = read_pm_markets(limit=50)
```

---

#### `read_pm_prices(limit=200)`

读取 Polymarket 价格历史快照。

**返回**: `list[dict]` — 按 `price_time` 降序

**示例**:
```python
from marketgraph_marketdata_db import read_pm_prices
prices = read_pm_prices(limit=200)
```

---

### Crypto 市场

#### `read_crypto_markets()`

读取所有 Crypto 品种的最新行情摘要。

**返回**: `list[dict]` — 每品种一行，含 `symbol`, `latest_date`, `latest_price`, `days` (数据天数)

**示例**:
```python
from marketgraph_marketdata_db import read_crypto_markets
for m in read_crypto_markets():
    print(f"{m['symbol']}: {m['latest_price']} ({m['days']} days)")
```

---

### 因子

#### `read_factors(market="Crypto", factor_name="", limit=200)`

读取派生因子值。

**参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `market` | `str` | `Crypto` | 市场代码 |
| `factor_name` | `str` | `""` | 因子名称 |
| `limit` | `int` | `200` | 最大返回行数 |

**返回**: `list[dict]` — 按 `event_time` 升序

---

### 元数据和健康检查

#### `coverage_summary()`

返回各市场数据覆盖摘要。

**返回**: `dict` — 包含每个市场键，每键含 `asset_count`, `latest_trade_date`, `latest_coverage_pct`, `latest_bar_coverage_pct` 等

**示例**:
```python
from marketgraph_marketdata_db import coverage_summary
cov = coverage_summary()
print(f"A 股覆盖: {cov['Ashare']['latest_coverage_pct']}%")
```

---

#### `health_summary()`

返回整体健康状态，含各表行数、数据新鲜度、最近采集运行。

**返回**: `dict` — 含 `tables` (表行数), `freshness` (pm_prices / crypto_market / crypto_factors 的 age_minutes 和 state), `recent_ingest_runs`

**新鲜度状态**:
| `state` | 含义 |
|---------|------|
| `fresh` | 数据在预期延迟内 |
| `stale_or_missing` | 超出预期延迟或数据缺失 |

**示例**:
```python
from marketgraph_marketdata_db import health_summary
h = health_summary()
# 检查 Crypto 数据是否新鲜
is_fresh = h["freshness"]["crypto_market"]["state"] == "fresh"
```

---

#### `read_coverage_status(market="Ashare", trade_date="", status="", limit=200)`

查询逐股覆盖状态。

**参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `market` | `str` | `Ashare` | 市场 |
| `trade_date` | `str` | `""` | 交易日，为空取最新 |
| `status` | `str` | `""` | 筛选状态: `bar_present` / `missing` / `suspended` 等 |
| `limit` | `int` | `200` | 最大返回行数 |

---

#### `read_interface_matrix(provider="", layer="", interface_name="", limit=200)`

查询数据源/接口能力注册。

**返回**: `dict` — `{storage, db_path, row_count, counts (按 provider/layer/actual_state 聚合), rows}`

---

#### `read_backfill_progress(limit=100)`

查询历史回填进度和失败记录。

**返回**: `dict` — `{storage, db_path, state_file, state, counts, recent, failures}`

---

### 交易日历 (reference/market_calendar.py)

#### `is_trading_day(d=None) -> bool`

判断是否为 A 股交易日。

**参数**: `d` — `date` / `datetime` / `str` (YYYYMMDD / YYYY-MM-DD)，默认今天

**示例**:
```python
from market_calendar import is_trading_day
if is_trading_day("20260630"):
    print("交易日")
```

---

#### `get_trading_days(start, end) -> list[date]`

获取区间内所有 A 股交易日。

**返回**: 升序排列的 `datetime.date` 列表

**错误**: 区间无交易日或不含工作日 → `TradingCalendarUnavailableError`

---

#### `get_next_trading_day(d=None, *, include_today=False) -> date | None`

获取下一个 A 股交易日。

---

## Freshness / Quality 元数据

### 采集延迟预期

| 数据类型 | 采集频率 | 预期延迟 | fresh 阈值 |
|---------|--------|---------|-----------|
| Crypto 行情 | 15min | ~5min DB sync | ≤ 30min |
| Polymarket 价格 | 15min | ~5min DB sync | ≤ 30min |
| Crypto 因子 | 15min | ~5min DB sync | ≤ 60min |
| A 股日线 | 盘后 EOD | 日级 | 最新交易日 |
| 美股日线 | 盘后 EOD | 日级 | 最新交易日 |
| RSS 事件 | 10-15min | staging → bridge 延迟 | 最新 collected_at |
| 基本面 | 日级预计算 | 按需 | 季度报告期后 |

### 数据质量标记

每行数据携带以下质量元数据：

| 字段 | 说明 |
|------|------|
| `provider` | 数据源标识，用于溯源 |
| `source_file` | 来源文件路径 |
| `collected_at` | 采集时间戳 |
| `coverage_status` | 覆盖状态（`bar_present` / `missing` / `suspended` / `delisted`） |
| `reason` | 缺失原因文字描述 |

消费者应始终检查 `coverage_summary()` 和 `health_summary()` 在消费数据前验证新鲜度。

---



---

### Tushare 原生读取

#### `get_tushare(api_name, ts_code=None, start_date=None, end_date=None, **params)`

**NEW** — 通过 SharedSignals reader 直接读取 Tushare API 数据。路由到 `a_share_tushare_api._call()`，返回与其他 reader 函数一致的 metadata-wrapped 格式。结果 LRU-cached（maxsize=512）。

**参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `api_name` | `str` | 必填 | Tushare API 名，如 `daily`、`moneyflow`、`fina_indicator`、`income`、`balancesheet`、`adj_factor`、`margin`、`limit_list`、`hk_hold`、`stock_minutes`、`news_list` 等 |
| `ts_code` | `str` | `None` | 股票代码，自动注入到 params 中 |
| `start_date` | `str` | `None` | 起始日期 YYYYMMDD，自动注入到 params 中 |
| `end_date` | `str` | `None` | 截止日期 YYYYMMDD，自动注入到 params 中 |
| `**params` | — | — | 透传的 Tushare API 额外参数 |

**返回**: `list[dict]` — 每条含 `data` / `provenance` / `freshness` / `quality` / `degraded` / `lineage`

**示例**:
```python
from reader import get_tushare

# 读取贵州茅台日线行情
rows = get_tushare("daily", ts_code="600519.SH", start_date="20260601", end_date="20260630")
for row in rows:
    d = row["data"]
    print(f"{d['trade_date']}: O={d['open']} C={d['close']}")

# 读取个股资金流向
rows = get_tushare("moneyflow", ts_code="000001.SZ", start_date="20260629", end_date="20260629")

# 读取财务指标
rows = get_tushare("fina_indicator", ts_code="600519.SH", start_date="20250101")

# 读取任意 Tushare API，传额外参数
rows = get_tushare("income", ts_code="600519.SH", period="20251231")
```

**错误处理**: Tushare API 不可用时返回 degraded 空包装，不抛异常。

**数据新鲜度**: Tushare 数据 `stale_after_hours=48.0`；日线数据通常盘后 EOD 级别。

### 数据维度来源标注

以下标注哪些数据维度由 SharedSignals **natively collected**（原生采集）vs **bridged**（桥接）：

| 数据维度 | 来源 | 方式 |
|---------|------|------|
| A 股日线 OHLCV | Tushare `daily` | **Native: `reader.get_tushare("daily", ...)`** |
| A 股资金流向 | Tushare `moneyflow` | **Native: `reader.get_tushare("moneyflow", ...)`** + CSV cache |
| A 股财务指标 | Tushare `fina_indicator` | **Native: `reader.get_tushare("fina_indicator", ...)`** / `reader.get_fundamentals()` |
| A 股利润表 / 资产负债表 | Tushare `income` / `balancesheet` | **Native: `reader.get_tushare("income", ...)`** |
| A 股复权因子 | Tushare `adj_factor` | **Native: `reader.get_tushare("adj_factor", ...)`** |
| A 股融资融券 | Tushare `margin` | **Native: `reader.get_tushare("margin", ...)`** |
| A 股涨跌停列表 | Tushare `limit_list` | **Native: `reader.get_tushare("limit_list", ...)`** |
| A 股北向资金 | Tushare `hk_hold` | **Native: `reader.get_tushare("hk_hold", ...)`** |
| A 股分钟线 | Tushare `stock_minutes` | **Native: `reader.get_tushare("stock_minutes", ...)`** / `reader.get_realtime_5min()` |
| A 股新闻 | Tushare `news_list` | **Native: `reader.get_tushare("news_list", ...)`** |
| Crypto klines | Binance → marketdata.sqlite | Bridged: `read_daily("Crypto", ...)` |
| Crypto markets | marketdata.sqlite | Bridged: `read_crypto_markets()` |
| US 日线 | marketdata.sqlite | Bridged: `read_daily("US", ...)` |
| HK ETF 日线 | marketdata.sqlite | Bridged: `read_daily("HK", ...)` via `get_hk_etf` |
| Polymarket 市场/价格 | Polymarket API → marketdata.sqlite | Bridged: `read_pm_markets()` / `read_pm_prices()` |
| 事件/信号 | RSS / Tavily → intake CSV | Bridged: `reader.get_events()` / `reader.get_sentiment()` |
| 交易日历 | reference/market_calendar.py | Bridged: `reader.is_trading_day()` |
| 参考表 | reference/*.csv | Bridged: `reader.get_reference()` |
| 宏观因子 | macro_factors.csv (from MG) | Bridged: `reader.get_macro_factors()` |

## 错误处理指南

### 分级策略

| 级别 | 场景 | 处理 |
|------|------|------|
| **正常** | 空结果、无数据 | 返回空列表 `[]`，不抛异常 |
| **降级** | 数据新鲜度不足 | 使用 `health_summary()` 检查，降权/标记而非阻断 |
| **可恢复** | DB 锁定、临时不可用 | 重试 (最多 3 次，指数退避 1s/2s/4s) |
| **硬错误** | SQLite 损坏、磁盘满 | 记录日志，走备用路径 (CSV fallback) |

### 示例：带健康检查的数据读取

```python
from marketgraph_marketdata_db import health_summary, read_daily

def safe_read_daily(market, **kwargs):
    health = health_summary()
    freshness = health["freshness"].get(market.lower(), {})
    if freshness.get("state") == "stale_or_missing":
        logger.warning(f"{market} 数据过期: {freshness.get('age_minutes')}min")

    try:
        rows = read_daily(market, **kwargs)
        if not rows:
            logger.info(f"{market}: 无数据返回 (可能非交易日)")
        return rows
    except sqlite3.OperationalError as e:
        logger.error(f"DB 读取失败: {e}")
        # 降级到 CSV fallback
        return fallback_csv_reader(market, **kwargs)
```

### 交易日验证

```python
from market_calendar import is_trading_day

def safe_trade_date_check(date_str):
    try:
        return is_trading_day(date_str)
    except TradingCalendarUnavailableError:
        # 无法确认，保守处理：假定非交易日
        logger.warning(f"交易日历不可用，假定 {date_str} 非交易日")
        return False
```

---

## 版本策略

### 语义化版本

`MAJOR.MINOR.PATCH` (例如 `2.0.0`)

| 变更类型 | 版本影响 | 示例 |
|---------|--------|------|
| 新增 reader 函数 | MINOR++ | 新增 `read_options_flow()` |
| 新增可选参数 | MINOR++ | `read_daily` 增加 `provider` 参数 |
| 返回字段新增 | MINOR++ | 在 dict 中追加新 key |
| 返回字段删除/重命名 | MAJOR++ | 删除 `raw_json` 字段 |
| 参数签名变更 | MAJOR++ | 将 `symbol` 改为必填 |
| Bug 修复（不改契约） | PATCH++ | 修正日期排序 |
| 存储迁移 | MAJOR++ | SQLite → DuckDB |
| 表结构变更 | MAJOR++ | 新增/删除/重命名列 |

### 弃用策略

- 旧接口保留至少 1 个 MAJOR 版本（MINOR 累积 ≥ 2 后再移除）
- 弃用函数在 docstring 添加 `@deprecated` 标记和替代方案
- 消费者在下一个 MINOR 发布前完成迁移

### 向后兼容保证

- 现有函数签名不变 (同 MAJOR 版本内)
- 新增的返回字段不影响已有 key
- `limit` 上限（5000）不会降低
- 日期格式同时接受 `YYYYMMDD` 和 `YYYY-MM-DD`

---

## 附录：MCP 工具映射

MCP 工具 `read_marketdata_db` 通过 `dataset` 参数映射到 reader 函数：

| `dataset` 值 | 对应 reader 函数 |
|-------------|----------------|
| `daily` | `read_daily()` |
| `intraday` | `read_intraday()` |
| `events` | `read_events()` |
| `pm_markets` | `read_pm_markets()` |
| `pm_prices` | `read_pm_prices()` |
| `crypto_markets` | `read_crypto_markets()` |
| `factors` | `read_factors()` |
| `coverage` | `coverage_summary()` |
| `coverage_status` | `read_coverage_status()` |
| `health` | `health_summary()` |
| `interface_matrix` | `read_interface_matrix()` |
| `backfill_progress` | `read_backfill_progress()` |

其他 MCP 工具（如 `get_tushare_daily`, `get_crypto_klines`, `get_pm_markets`）是独立封装，内部也可能调用上述 reader 函数，但提供了更业务化的参数（如 `ts_codes` 格式）。

---

## 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-30 | 1.1.0 | 新增 `reader.get_tushare()` + `/tushare` endpoint + 数据维度来源标注 |
| 2026-06-30 | 1.0.0 | 初始版本，文档化全部 reader 函数 |
