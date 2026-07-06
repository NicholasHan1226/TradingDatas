# SharedSignals API Contract

> **版本**: 1.1.11 | **状态**: active | **边界**: 只读数据接口，研究线和交易线共享读取

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

SharedSignals 提供统一的只读数据访问层。所有消费者（TradingAgent、MarketGraph、研究工具）通过以下两个入口读取数据：

**生产数据边界（2026-07-04）**：外部 provider 调用只允许发生在 SharedSignals collector 层。`reader.py`、HTTP API 和消费者系统必须读取已采集的 SQLite/DuckDB/CSV read model；没有映射或没有缓存数据时返回 degraded 包装，不再现场调用 Tushare/DashScope/其它 provider。

**HTTP 服务**：生产 API 默认监听 `127.0.0.1:8082`。本机 MarketGraph/TradingAgent 可使用 localhost bypass；外部账号必须配置 token/JWT，账号可设置 `max_concurrent`，未配置时按 scope 默认并发限制执行。


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
| `US` | 美股 | Tushare 美股接口 |
| `Crypto` | 加密 | Binance (4 接口) |
| `PredictionMarkets` | 预测市场 | Polymarket (3 接口) |
| `Global` | 全球指数 | Tushare `index_global` |
| `ETF` | ETF 基础信息 | Tushare `etf_basic` |
| `Futures` | 期货基础信息、日线和分钟线 | Tushare `fut_basic` / `fut_daily` / `rt_fut_min` |

### CNFutures 行情采集合同

SharedSignals 只负责采集和桥接国内期货行情，不生成交易信号。

| 能力 | 入口 | 输出 |
| --- | --- | --- |
| 单日采集 | `python3 tools/collect_cn_futures_daily.py --trade-date YYYYMMDD` | `data/tushare/fut_daily/YYYYMMDD/fut_daily_YYYYMMDD.csv` + SQLite `market_bars_daily` |
| cron wrapper | `bash cron/cn_futures_daily.sh --trade-date YYYYMMDD` | `logs/cron/cn_futures_daily.log` + 同上 |
| 历史回补 | `python3 collectors/tushare/backfill_fut_daily.py --start-date YYYYMMDD --end-date YYYYMMDD` | 逐日 CSV + SQLite bridge，失败汇总 JSON |
| 5 分钟采集 | `python3 tools/collect_cn_futures_5min.py --trade-date YYYYMMDD` | `data/tushare/rt_fut_min/YYYYMMDD/rt_fut_min_YYYYMMDD_5min.csv` + SQLite `market_bars_intraday` |
| 5 分钟 cron wrapper | `bash cron/cn_futures_5min.sh` | `logs/cron/cn_futures_5min.log` + 同上 |
| 5 分钟新鲜度验收 | `python3 tools/check_cn_futures_5min_freshness.py --json` | 只读检查 `market_bars_intraday` 最新 Futures 5 分钟 bar，返回 `fresh/stale/no_data/error` |

`fut_daily` 固定使用 `P6_other_daily` tier 的 global API，参数为 `trade_date`。SQLite bridge 写入：

- `market="Futures"`
- `provider="tushare_fut_daily"`
- `symbol` 使用 Tushare 期货合约代码
- `trade_date` 使用 `YYYYMMDD`
- `open/high/low/close/volume/amount` 来自 Tushare 日线字段映射

`rt_fut_min` 使用独立的 CNFutures 5 分钟采集入口，不进入 `P6_other_daily`，避免日频杂项层阻塞盘中交易频率。默认从最新 Futures 日线合约池按产品轮询选择 `rb/cu/i/m/if/ih/ic/im` 重点品种，避免远月合约过多时挤掉股指产品；其中 `IF/IH/IC/IM` 供 TradingAgent 股指日内方向风格做模拟验证。也可通过 `CN_FUTURES_5MIN_SYMBOLS` 或 `--symbols` 指定合约。SQLite bridge 写入：

- `market="Futures"`
- `provider="tushare_rt_fut_min"`
- `interval="5min"`
- `symbol` 兼容 Tushare 返回的 `ts_code`、`symbol` 或 `code`
- `trade_date` 从 `time`/`trade_time` 派生，`bar_time` 保留分钟时间戳
- `/realtime_5min` 默认仍读取 A 股分钟线；期货读取需显式传 `market=Futures`，例如 `/realtime_5min?market=Futures&ts_code=RB2609.SHF&date=20260703`
- 可选一级盘口字段会透传到 `market_bars_intraday`：`bid_price` 兼容 `bid1`/`best_bid`，`ask_price` 兼容 `ask1`/`best_ask`，`bid_size` 兼容 `bid_volume`/`bid1_volume`，`ask_size` 兼容 `ask_volume`/`ask1_volume`
- 可选到期字段会透传到 `market_bars_intraday`：`last_trade_date`、`expiry_date`；若分钟 CSV 未带这些字段但 `market_assets` 的同一 Futures 合约已有 `last_trade_date`/`expiry_date`，CSV bridge 会补齐
- 这些字段均为可空增量字段；Tushare 当前返回缺失时不阻断 OHLCV 写入，TradingAgent 只能在字段存在时使用盘口/到期保护增强
- `rt_fut_min` 采集必须区分三种状态：provider 正常返回 0 行时为 `empty`；provider 返回权限、接口或本地调用错误时为 `failed`；非空行情 CSV 写入后 SQLite bridge 写入 0 行时为 `failed`。交易时段内持续 `empty` 或任何 `failed` 都应进入 SharedSignals watchdog/系统告警排查，不能被解释为 TradingAgent 无交易信号。
- 当 Tushare/QuickSync `rt_fut_min` 返回权限或接口错误时，采集器可通过 AKShare/Sina `futures_zh_minute_sina` 作为模拟盘备源补入 5 分钟 OHLCV；该备源仅支撑模拟研究与开盘验收，不改变未来实盘券商/CTP 行情边界。备源写入同一 `market_bars_intraday`，`provider="akshare_sina_rt_fut_min"`，并保留 `fallback_from` 与 `fallback_reason` 便于复盘；可通过 `CN_FUTURES_5MIN_AKSHARE_FALLBACK=0` 关闭。

`tools/check_cn_futures_5min_freshness.py` 是只读数据健康检查，默认 10 分钟阈值，可通过 `--sqlite-db`、`--now`、`--max-age-minutes` 和 `--json` 调整。它只报告数据是否新鲜、当前/下一交易时段是否已有 5 分钟 bar，不生成交易信号、不触发补采、不写 TradingAgent 队列。

消费者边界：

- TradingAgent/CNFutures 可按 `market="Futures"` 从 `market_bars_daily` 读取日线做模拟盘。
- TradingAgent/CNFutures 可按 `market="Futures"`、`interval="5min"` 从 `market_bars_intraday` 读取盘中数据做 5 分钟模拟/影子盘研究。
- MarketGraph 可只读同一份 Futures 行情做商品、宏观和跨市场研究证据。
- SharedSignals 不写 TradingAgent signal queue，不生成买卖方向，不改变实盘或模拟盘权限。

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

Tushare `news` / `major_news` / `cctv_news` 进入 `market_events` 时由 bridge 自动补齐 `event_hash`、`event_type`、`event_time`、`trade_date`、`provider` 和 `source_file`。

#### market_factors (因子/宏观/资金)

| 字段 | 类型 | 说明 |
|------|------|------|
| `factor_hash` | TEXT PK | 因子唯一哈希 |
| `market` | TEXT | 市场代码，可为空 |
| `symbol` | TEXT | 品种代码，可为空 |
| `factor_name` | TEXT | `api_name:metric` 格式 |
| `event_time` | TEXT | 指标对应期，优先取 `trade_date/ann_date/end_date/report_date/date/period/month/quarter/year` |
| `value` | REAL | 数值化指标 |
| `provider` | TEXT | 例如 `tushare_shibor_lpr` |
| `source_file` | TEXT | 来源 CSV 文件 |
| `collected_at` | TEXT | 采集时间 |
| `raw_json` | TEXT | 原始行 JSON |

低频宏观接口（`cn_cpi`、`cn_pmi`、`cn_m`、`cn_ppi`、`cn_gdp`、`sf_month`、`shibor`、`shibor_lpr`、`us_tycr`、`us_tbr`、`us_tltr`、`repo_daily`）先按 P4/P6 定时采集落 CSV，再展开为 `market_factors`。月度/季度字段只作为 `event_time`，不作为数值因子。

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

所有 reader 函数位于 `bridge/marketgraph_marketdata_db.py`，以及辅助的 `reference/market_calendar.py`。`reference/market_calendar.py` 只读 SharedSignals read model，不再导入旧 A 股 Tushare wrapper 或现场调用 provider。

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

# 最近 100 条 RSS 事件（RSS 源当前为 deferred，恢复生产采集前仅返回历史数据或空结果）
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

### 交易日历 (reader DB-first)

#### `is_trading_day(d=None) -> bool`

判断是否为 A 股交易日。`reader.is_trading_day()` 优先读取 `market_bars_daily`；若请求日期晚于最新 read model 日期，则使用 weekday fallback 返回明确布尔值；DB 缺失或读取失败才返回 degraded。

**参数**: `d` — `date` / `datetime` / `str` (YYYYMMDD / YYYY-MM-DD)，默认今天

**示例**:
```python
from reader import is_trading_day
if is_trading_day("20260630")[0]["data"]["is_trading_day"]:
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
| Crypto 行情 | 5min | ~5min DB sync | ≤ 30min |
| Polymarket 价格 | 5min | ~5min DB sync | ≤ 30min |
| Crypto 因子 | 按需/低频 | ~5min DB sync | ≤ 60min |
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

**DB-first** — 通过 SharedSignals reader 读取已采集 Tushare 数据。该接口只查询 read model 映射表；不再路由到 `a_share_tushare_api._call()` 做现场 provider 调用。无映射或无缓存数据时返回 degraded 包装。

**参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `api_name` | `str` | 必填 | Tushare API 名，如 `daily`、`moneyflow`、`fina_indicator`、`income`、`balancesheet`、`adj_factor`、`margin`、`limit_list`、`hk_hold`、`stock_minutes`、`news_list` 等 |
| `ts_code` | `str` | `None` | 股票代码，自动注入到 params 中 |
| `start_date` | `str` | `None` | 起始日期 YYYYMMDD，自动注入到 params 中 |
| `end_date` | `str` | `None` | 截止日期 YYYYMMDD，自动注入到 params 中 |
| `**params` | — | — | 查询 read model 的过滤参数；不透传现场 provider 调用 |

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

**错误处理**: read model 未映射、无缓存、DB 不可用或数据为空时返回 degraded 包装，不抛异常，不现场补采。

**数据新鲜度**: Tushare 数据由 P0-P6 定时 collector 维护；A 股 P0 交易时段 5 分钟级，P1-P6 按日频/研究频率维护。

### 数据维度来源标注

以下标注哪些数据维度由 SharedSignals **natively collected**（原生采集）vs **bridged**（桥接）：

| 数据维度 | 来源 | 方式 |
|---------|------|------|
| A 股日线 OHLCV | Tushare `daily` | DB-first: `reader.get_tushare("daily", ...)` / HTTP `/tushare` |
| A 股资金流向 | Tushare `moneyflow` | DB-first: `reader.get_tushare("moneyflow", ...)`；collector CSV 必须通过 `storage/csv_bridge.py` 写入 `market_factors` |
| A 股财务指标 | Tushare `fina_indicator` | P2 collector → `market_factors`; `reader.get_fundamentals(ts_code=...)`（HTTP 也兼容 `symbol`） |
| A 股利润表 / 资产负债表 | Tushare `income` / `balancesheet` | P2 collector → read model / degraded if no recent rows |
| A 股复权因子 | Tushare `adj_factor` | P0/P1 collector → read model |
| A 股融资融券 | Tushare `margin`/`margin_secs` | P0/P1 collector → `market_factors`/read model |
| A 股涨跌停列表 | Tushare `limit_list` | P0/P1 collector → read model |
| A 股北向资金 | Tushare `hk_hold` | P0/P1 collector → read model |
| A 股分钟线 | Tushare `stk_mins` / `rt_min` realtime snapshot | P0 5 分钟 collector → `market_bars_intraday`; `reader.get_realtime_5min(market="Ashare")` / HTTP `/realtime_5min?market=Ashare` DB-first，未传日期时使用该股票最新 intraday 日期；SQLite 暂未刷入时会回退 SharedSignals `data/tushare/stk_mins` / `rt_min` CSV，旧 `rt_k` 目录仅作历史兼容 |
| A 股国债逆回购 | Tushare `repo_daily` | P1/P4 collector → `market_factors`，同时投影到 `market_bars_daily`；`204001.SH` 等逆回购代码可通过 `/market_data` 读取 `close` 作为年化利率百分值 |
| A 股新闻 | Tushare `news_list` / news sources | collector → `market_events`; no live provider fallback |
| Crypto klines/ticker | Binance → NDJSON staging → marketdata.sqlite | Bridged: `/crypto`, `read_daily("Crypto", ...)` |
| Crypto markets | marketdata.sqlite | Bridged: `read_crypto_markets()` |
| US 日线 | marketdata.sqlite | Bridged: `read_daily("US", ...)` |
| HK ETF 日线 | marketdata.sqlite | Bridged: `read_daily("HK", ...)` via `get_hk_etf` |
| 全球指数日线 | Tushare `index_global` | collector → `market_bars_daily`，market=`Global` |
| ETF 基础信息 | Tushare `etf_basic` | collector → `market_assets`，market=`ETF` |
| 期货基础信息 | Tushare `fut_basic` | collector → `market_assets`，market=`Futures`；需采集 `last_ddate` 与 `delist_date`，分别映射到 `last_trade_date` 与 `expiry_date` |
| 期货日线 OHLCV | Tushare `fut_daily` | collector → `market_bars_daily`，market=`Futures`；按 `trade_date` 全品种采集，不使用 A 股股票列表 |
| 期货 5 分钟 OHLCV | Tushare `rt_fut_min` | CNFutures 5 分钟 collector → `market_bars_intraday`，market=`Futures`，interval=`5min`；HTTP `/realtime_5min?market=Futures` 可读取同一 read model 并透传可空 bid/ask/size 字段；独立调度，不进入日频 `P6_other_daily` |
| Polymarket 市场/价格 | Polymarket API → marketdata.sqlite | Bridged: `read_pm_markets()` / `read_pm_prices()` |
| 事件/信号 | RSS(deferred) / Tavily → intake CSV | Bridged: `reader.get_events()` / `reader.get_sentiment()`；sentiment intake 空时回退 `data/sentiment_signals.csv` 并保留 provenance；未传日期时不过滤日期；RSS 源在 `source_registry.csv` 中已标记 `deferred`，当前不作为现役生产 collector |
| 交易日历 | `market_bars_daily` read model | DB-first: `reader.is_trading_day()`；未来/周末日期使用 weekday fallback，不现场调用 provider |
| 参考表 | reference/*.csv | Bridged: `reader.get_reference()` |
| 宏观因子 | Tushare P4 macro + read model | P4 collector → `market_factors`; `reader.get_macro_factors()` DB-first |

### 关联查询 (Association Queries)

#### `get_industry(ts_code)`

**NEW** — 查询股票的行业/产业链/板块/概念信息。

优先读取 `stock_industry_map.csv`。该文件由 `tools/refresh_stock_industry_map.py` / `cron/refresh_industry_map.sh` 在生产上每日 06:30 从 `market_assets.sector` 生成基础行业映射；当前基础映射覆盖 5,521 条 A 股。若文件缺失、权限异常或无匹配，则回退 `market_assets` 中的 `sector/industry` 基础行业字段，并在 provenance/lineage 中标记为 `sqlite:market_assets`。

**参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `ts_code` | `str` | 必填 | 股票代码，如 `600519.SH` |

**返回**: `list[dict]` — 含 `sw_l1_name`, `sw_l2_name`, `sw_l3_name`, `chain_name`, `segment_name`, `csrc_name`, `cni_name`, `concept`, `gics_sector` 等字段

**示例**:
```python
from reader import get_industry

rows = get_industry("600519.SH")
if rows and not rows[0].get("degraded"):
    d = rows[0]["data"]
    print(f"{d['name']}: {d['sw_l1_name']} / {d['chain_name']}")
```

**错误处理**: ts_code 未找到或文件缺失时返回 degraded 空包装。

---

#### `get_associations(ts_code=None, event_id=None)`

**NEW** — 查询事件↔股票关联关系。

读取 MarketGraph `event_signal_associations.csv`（1,374 条 event→stock 映射）和 `target_stock_map.csv`（71 条 target→stock 映射）。

- 传入 `ts_code`：通过 target_stock_map 逆向查找哪些事件影响了该股票
- 传入 `event_id`：查找事件影响了哪些股票（自动关联 target_stock_map 补全 ts_codes）
- 两者都不传：返回全部关联记录

**参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `ts_code` | `str` | `None` | 股票代码，如 `600519.SH` |
| `event_id` | `str` | `None` | 事件 ID，如 `evt:ee78c0c3ad7b4fbf` |

**返回**: `list[dict]` — 含 `subject_type`, `subject_name`, `target_type`, `target_name`, `polarity`, `impact_strength`, `effective_confidence` 等字段。event_id 查询时额外含 `ts_codes` 字段

**示例**:
```python
from reader import get_associations

# 查询事件影响了哪些股票
rows = get_associations(event_id="evt:ee78c0c3ad7b4fbf")
for row in rows:
    d = row["data"]
    print(f"{d['target_name']}: {d.get('ts_codes', 'N/A')}")

# 查询某股票受哪些事件影响
rows = get_associations(ts_code="600519.SH")
```

---

#### `get_impacts(event_type=None, target=None)`

**NEW** — 查询影响关系边（31,206 条）。

读取 MarketGraph `impact_relations.csv`，支持按事件类型和/或目标筛选。

**参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `event_type` | `str` | `None` | 影响类型，如 `liquidity`, `sentiment`, `policy` |
| `target` | `str` | `None` | 目标，模糊匹配 `target_id` / `target_name` / `target_type` |

**返回**: `list[dict]` — 含 `event_id`, `impact_type`, `target_type`, `target_id`, `target_name`, `polarity`, `strength`, `confidence`, `evidence` 等字段

**示例**:
```python
from reader import get_impacts

# 查询流动性相关影响
rows = get_impacts(event_type="liquidity")

# 查询影响有色金属的所有事件
rows = get_impacts(target="有色金属")
```

---


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
| 2026-07-06 | 1.1.12 | CNFutures 5 分钟采集加强失败语义：`rt_fut_min` provider 错误和非空 CSV 桥接 0 行会返回 `failed`；生产确认 Tushare `rt_fut_min` 权限不足后，增加 AKShare/Sina 5 分钟模拟盘备源；SharedSignals API 白名单补入 `rt_fut_min`，便于只读接口自检。 |
| 2026-07-06 | 1.1.11 | A股 P0 实时分钟接口从旧 `rt_k` 收口到 Tushare `rt_min`，CSV bridge/reader fallback 支持 `rt_min`；`repo_daily` 保留因子写入并额外投影到 `market_bars_daily`，使 `204001.SH` 可通过 `/market_data` 读取逆回购日线收益率。 |
| 2026-07-05 | 1.1.10 | `/realtime_5min` 增加 `market` 参数，默认兼容 A股，同时支持 `market=Futures` 等非 A股 5 分钟 read model 输出；reader 会透传新增 L1 盘口字段。 |
| 2026-07-05 | 1.1.9 | CNFutures `market_bars_intraday` 增加可空一级 bid/ask、盘口量、last_trade_date/expiry_date 字段；CSV bridge 支持 `rt_fut_min` 盘口字段透传，并可从 `market_assets` 补合约到期字段；`fut_basic` 配置补采 `last_ddate/delist_date`；`/realtime_5min` 支持 `market=Futures` 读取期货分钟线。 |
| 2026-07-05 | 1.1.8 | CNFutures 5 分钟默认合约池加入股指期货 `IF/IH/IC/IM`，并按产品轮询自动选合约，供 TradingAgent 股指日内方向风格读取同一 SharedSignals 数据层。 |
| 2026-07-04 | 1.1.7 | 新增 CNFutures 5 分钟数据新鲜度验收工具，只读检查 `market_bars_intraday` Futures 5 分钟 bar 的 stale/no_data/error 状态。 |
| 2026-07-04 | 1.1.6 | 新增 CNFutures 5 分钟采集入口 `rt_fut_min`，写入 `market_bars_intraday`，并以独立 cron 支持日盘、夜盘和跨午夜夜盘采集。 |
| 2026-07-04 | 1.1.5 | `fut_daily` 改为按交易日全品种采集并写入 `market_bars_daily`，market=`Futures`；`sync_daily.py` 支持 `--trade-date` 与 `--only-api` 定向补采。 |
| 2026-07-04 | 1.1.4 | 低频宏观接口支持 API 级回看窗口并补齐去重键/SQLite 映射；Tushare 新闻自动生成 `event_hash`；`index_global`/`etf_basic`/`fut_basic` 进入 read model；`/cache/invalidate` 支持 POST。 |
| 2026-07-04 | 1.1.3 | 行业映射每日自动刷新并修复原子写入权限；`auto_restart.sh --force` 支持部署后显式 reload；`get_sentiment()`/`get_realtime_5min()` 修复空日期默认行为；HTTP `/sentiment` 与 `/realtime_5min` 支持 `limit`。 |
| 2026-07-04 | 1.1.2 | `reader.is_trading_day()`、`get_realtime_5min()`、`get_industry()`、`get_sentiment()` 改为 read-model/真实 CSV 优先；`/health` 改为动态样例并放宽权益市场周末 freshness 阈值；moneyflow CSV 桥接进 `market_factors`。 |
| 2026-07-04 | 1.1.1 | `reader.get_tushare()`/`get_fundamentals()` 改为 DB-first；移除现场 provider fallback；HTTP `/fundamentals` 兼容 `symbol`；记录账号并发限制与本机 API 运行边界 |
| 2026-06-30 | 1.1.0 | 新增 `reader.get_tushare()` + `/tushare` endpoint + 数据维度来源标注 |
| 2026-06-30 | 1.0.0 | 初始版本，文档化全部 reader 函数 |
