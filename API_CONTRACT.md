# SharedSignals API Contract

> **版本**: 1.1.34 | **状态**: active | **边界**: 只读数据接口，研究线和交易线共享读取

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

**生产数据边界（2026-07-08）**：外部 provider 调用只允许发生在 SharedSignals collector 层。`reader.py`、HTTP API 和消费者系统必须读取已采集的 SQLite/DuckDB read model；没有映射或没有缓存数据时返回 degraded 包装，不再现场调用 Tushare/DashScope/其它 provider，也不得回退旧 CSV、NDJSON、旧目录或其它系统内部文件。

**空结果边界（2026-07-08）**：HTTP API 遇到缺表、缺文件或无匹配行时，业务数据固定返回 `data: []`，降级原因保留在 `metadata.degraded=true` 与 `metadata.degraded_reasons`。不得把 degraded 空包装暴露为 `data: [{}]`，避免消费者误判为“一条空数据”。

**入库完整性边界（2026-07-09）**：`collectors/tushare/config.yaml` 中已启用的 P0-P7 Tushare 接口必须全部有 read model 表映射、API 白名单、采集频率声明和限流保护。非空 provider rows 直接写入 SQLite 为 0 行时必须标记为 `failed` 并计入 tier `sqlite_failure_count`；不能把“采集成功但未入库”当作正常空返回。

**交易供数边界（2026-07-09）**：SharedSignals 是 5 分钟级/分钟级交易数据供给层，负责采集、整理、增量入库、健康标记和只读 API 输出；不承诺毫秒级 HFT、订单簿撮合、下单、资金、账户、执行回执或交易判断。

**横向扩源边界（2026-07-09）**：新增外部数据源先进入 `config/source_expansion_priority.yaml` 的 planned 队列，并按 `config/api_module_catalog.yaml` 归类到模块、read-model 表和默认 HTTP surface；再通过 collector、SQLite read model、API/read surface、freshness SLA、限流、降级语义、测试和生产 pilot 验收后才能进入定时采集。计划中的源不是生产供数，消费者不得绕过 SharedSignals 直接调用 provider 或本地文件。

**新增 API 边界（2026-07-09）**：横向扩源默认复用现有 API。只有当数据具备新的查询形态、独立 freshness/SLA、独立 auth scope、分页/限流模型，且不能由现有 endpoint 清晰表达时，才新增 HTTP endpoint，并同步更新 `/agent_config`、能力测试、auth scope、文档和外部 agent prompt。

**Green Gate 维护边界（2026-07-09）**：`/source_status` 是外部 agent 与运行人员判断接口、频率、模块、Tushare active、扩源 planned 队列、cron、SLA 和 capability registry 的 API 事实源。每日 Green Gate 邮件只复用该事实源并追加旧文件产物守门，不新增交易判断或 provider 直连能力。

**因子边界（2026-07-09）**：`market_factors` 是 SharedSignals 的事实型 read-model 投影，用于保存 provider 已给出的财务、资金流、宏观、参考限制、持仓排名等结构化数据，或必要的字段展开。SharedSignals 不计算 alpha、买卖方向、策略评分、仓位权重或交易触发条件；TradingAgent 应从 SharedSignals API 读取行情/事件/事实型因子后，自行完成交易因子提取、标准化、打分、组合、风控和决策。

**频率参数边界（2026-07-08）**：`/market_data` 的 `freq=daily` 读取 `market_bars_daily`；`freq=1m/5m/15m/30m/60m` 读取 `market_bars_intraday`，并规范化为 `1min/5min/15min/30min/60min`。未传 start/end 时，分钟请求只读取该标的最新一个 intraday 交易日，避免误扫全量分钟表。

**HTTP 服务**：生产 API 默认监听 `127.0.0.1:8082`（可通过 `SHAREDSIGNALS_API_HOST` 覆盖）。正式外部入口为 `https://signals.tradingagent.cc`，Cloudflare 橙云 A 记录指向主服务器 Nginx origin，再反代到 SharedSignals；本机 MarketGraph/TradingAgent 仅在显式设置 `SHAREDSIGNALS_LOCALHOST_BYPASS=1` 且请求没有外部 token/代理来源头时走 localhost bypass；外部账号必须配置 Bearer token、`X-API-Key` 或 JWT，账号可设置 `max_concurrent`，未配置时按 tier 默认并发限制执行。`external_read` 是外部隔离账号的完整数据读 scope，可读取健康/配置、业务数据和 `/tushare` read-model 输出，但不允许 `/cache/invalidate` 等运维控制。

**账号层级**：内部账号使用 `internal` tier，面向 Nicholas 批准的内部用户或可信内部 agent，可设置较高 `max_concurrent` 且无小时额度；仍不等于运维权限。未来外部套餐使用 `starter`（60/hour, 2 concurrent）、`research`（300/hour, 4 concurrent）、`pro`（600/hour, 8 concurrent）和 `enterprise`（定制，需容量和审计评估）。旧 `free` tier 保留为 `starter` 等价兼容口径。

### HTTP API 端点概览

| 端点 | scope | 说明 |
|------|-------|------|
| `GET /health` | `health` | 服务、cron、SLA 和 read model 健康状态 |
| `GET /capabilities` | `health` | 返回当前 API/read-model 能力登记；能力登记缺失时返回 degraded fallback，帮助消费者发现可用端点 |
| `GET /agent_config` | `health` | 返回外部 agent 接入机器配置、频率标签、禁止绕过规则和推荐调用端点 |
| `GET /source_status` | `health` | 返回数据源治理 green/yellow/red 状态，检查接口纳管、模块/API 目录、扩源 planned 队列、调度重复、SLA 和能力 registry |
| `GET /opening_gate` | `health` | 返回最近一次预开盘、首样本、午后恢复或收盘轻量供数门状态；不触发全库扫描 |
| `GET /cache/status` | `health` | 返回 API 进程内 cache generation、TTL、容量、条目数和鉴权去重缓存摘要 |
| `GET/POST /cache/invalidate` | `health` | 清理 API 进程内缓存；仅影响 API cache，不删除 read model 数据 |
| `GET /market_data` | `market_data` | 日线/分钟行情，只读 SQLite read model |
| `GET /realtime_5min` | `market_data` | A股/期货 5 分钟 read model 输出 |
| `GET /is_trading_day` | `market_data` | 交易日判断，优先 read model，未来/周末使用 weekday fallback |
| `GET /fundamentals` | `fundamentals` | 基本面/财务因子 read model |
| `GET /reference` | `fundamentals` | 明确参考表读取；旧 CSV reference 返回 degraded |
| `GET /industry` | `fundamentals` | 行业/产业链/板块基础字段 |
| `GET /macro` | `macro` | 宏观因子 read model |
| `GET /capital_flow` | `macro` | A股资金流向因子 read model |
| `GET /events` | `events` | 新闻/公告/事件 read model |
| `GET /sentiment` | `events` | 事件/情绪类 read model |
| `GET /crypto` | `crypto` | Crypto 行情 read model |
| `GET /pm_markets` | `pm` | Polymarket 市场元数据和最新价 |
| `GET /pm_prices` | `pm` | Polymarket 价格快照 |
| `GET /associations` | `associations` | 事件和标的关联查询，只读已同步的 research/read-model 投影 |
| `GET /impacts` | `associations` | 影响关系查询，只读已同步的 research/read-model 投影 |
| `GET /tushare` | `tushare` | 白名单 Tushare 能力的 DB-first 输出；不现场调用 provider |


| 入口 | 实现文件 | 适用场景 |
|------|---------|---------|
| **SQLite Read Model** | `reader.py` / `bridge/marketgraph_marketdata_db.py`（兼容模块） | 直接 Python import，用于 SharedSignals 内部 cron / 批处理 / 本地脚本；非跨系统生产入口 |
| **MCP Server (34 tools)** | `MarketGraph/08-Market-Interfaces/tools/marketgraph_mcp_server.py` | 远程 agent / 外部进程通过 stdio JSON-RPC 调用 |

本文档聚焦 **SQLite Read Model** 的 Python 函数接口。MCP 工具的参数映射见[附录](#附录-mcp-工具映射)。

### 存储概览

```
marketdata.sqlite (13 表)
├── market_assets              —— 品种主表
├── market_relationships       —— 指数/主题/行业成分关系
├── market_bars_daily          —— 日线 OHLCV
├── market_bars_intraday       —— 分钟线 OHLCV
├── market_events              —— 新闻/事件流
├── market_pm_markets          —— 预测市场元数据
├── market_pm_prices           —— 预测市场价格快照
├── market_factors             —— 事实型因子/结构化参考
├── market_fund_portfolio      —— 基金持仓披露明细
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
| `HK` | 港股 | Tushare `hk_daily` / `hk_basic` / 港股财务接口 |
| `US` | 美股 | Tushare 美股接口 |
| `Crypto` | 加密 | Binance (4 接口) |
| `PredictionMarkets` | 预测市场 | Polymarket (3 接口) |
| `Global` | 全球指数 | Tushare `index_global` |
| `ETF` | ETF 基础信息 | Tushare `etf_basic` |
| `Futures` | 期货基础信息、日线和分钟线 | Tushare `fut_basic` / `fut_daily` + AkShare/Sina 5 分钟 |

市场参数在 HTTP API 和 reader 内统一规范化。规范值仍以表中 `market` 为准；常见别名如 `CNFutures`、`cn_futures`、`cn-futures` 会映射到 `Futures`，`PM` / `Polymarket` 会映射到 `PredictionMarkets`，`hong_kong` 会映射到 `HK`。未知市场名不做模糊兜底，应返回空/降级结果并由调用方修正。

### CNFutures 行情采集合同

SharedSignals 只负责采集和桥接国内期货行情，不生成交易信号。

| 能力 | 入口 | 输出 |
| --- | --- | --- |
| 单日采集 | `python3 tools/collect_cn_futures_daily.py --trade-date YYYYMMDD` | SQLite `market_bars_daily` + 采集运行审计 |
| cron wrapper | `bash cron/cn_futures_daily.sh --trade-date YYYYMMDD` | `logs/cron/cn_futures_daily.log` + 同上 |
| 历史回补 | `python3 collectors/tushare/backfill_fut_daily.py --start-date YYYYMMDD --end-date YYYYMMDD` | 逐日直接写入 SQLite，失败汇总 JSON |
| 5 分钟采集 | `python3 tools/collect_cn_futures_5min.py --trade-date YYYYMMDD` | SQLite `market_bars_intraday` + 采集运行审计 |
| 5 分钟 cron wrapper | `bash cron/cn_futures_5min.sh` | `logs/cron/cn_futures_5min.log` + 同上 |
| 5 分钟新鲜度验收 | `python3 tools/check_cn_futures_5min_freshness.py --json` | 只读检查 `market_bars_intraday` 最新 Futures 5 分钟 bar，返回 `fresh/stale/no_data/error` |

`fut_daily` 固定使用 `P6_other_daily` tier 的 global API，参数为 `trade_date`。直接写入 SQLite read model：

- `market="Futures"`
- `provider="tushare_fut_daily"`
- `symbol` 使用 Tushare 期货合约代码
- `trade_date` 使用 `YYYYMMDD`
- `open/high/low/close/volume/amount` 来自 Tushare 日线字段映射

`P6_other_daily` 只在盘后夜间运行，避免开盘期间与 P0 5 分钟行情和 TradingAgent 模拟执行争用 SQLite/read model。`cb_daily` 使用 `trade_date` 全市场快照，不再按 A 股股票池逐股调用。

CNFutures 5 分钟采集使用独立入口，不进入 `P6_other_daily`，避免日频杂项层阻塞盘中交易频率。当前默认 provider 为 AkShare/Sina 分钟行情；Tushare `rt_fut_min` 只保留为显式 `CN_FUTURES_5MIN_PROVIDER=tushare_rt_fut_min` 时的可选 provider。默认从最新 Futures 日线合约池按产品轮询选择 `rb/cu/i/m/if/ih/ic/im` 重点品种，避免远月合约过多时挤掉股指产品；其中 `IF/IH/IC/IM` 供 TradingAgent 股指日内方向风格做模拟验证。也可通过 `CN_FUTURES_5MIN_SYMBOLS` 或 `--symbols` 指定合约。直接写入 SQLite read model：

- `market="Futures"`
- `provider="sina_futures_minute"`（默认）或显式配置下的 `provider="tushare_rt_fut_min"`
- `interval="5min"`
- `symbol` 兼容 Tushare 返回的 `ts_code`、`symbol` 或 `code`
- `trade_date` 从 `time`/`trade_time` 派生，`bar_time` 保留分钟时间戳
- `/realtime_5min` 默认仍读取 A 股分钟线；期货读取需显式传 `market=Futures`，例如 `/realtime_5min?market=Futures&ts_code=RB2609.SHF&date=20260703`
- 可选一级盘口字段会透传到 `market_bars_intraday`：`bid_price` 兼容 `bid1`/`best_bid`，`ask_price` 兼容 `ask1`/`best_ask`，`bid_size` 兼容 `bid_volume`/`bid1_volume`，`ask_size` 兼容 `ask_volume`/`ask1_volume`
- 可选到期字段会透传到 `market_bars_intraday`：`last_trade_date`、`expiry_date`；若分钟 provider rows 未带这些字段但 `market_assets` 的同一 Futures 合约已有 `last_trade_date`/`expiry_date`，入库层会补齐
- 这些字段均为可空增量字段；Tushare 当前返回缺失时不阻断 OHLCV 写入，TradingAgent 只能在字段存在时使用盘口/到期保护增强
- CNFutures 5 分钟采集必须区分三种状态：provider 正常返回 0 行时为 `empty`；provider 返回权限、接口或本地调用错误时为 `failed`；非空 provider rows 直接写入 SQLite 为 0 行时为 `failed`。交易时段内持续 `empty` 或任何 `failed` 都应进入 SharedSignals watchdog/系统告警排查，不能被解释为 TradingAgent 无交易信号。
- 不允许在 TradingAgent 或 MarketGraph 内另起期货 5 分钟直采；两者只通过 SharedSignals HTTP API 读取同一 SQLite read model。

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
| `source_file` | TEXT | 来源标识（采集运行 key/路径），仅作迁移/审计参考；现役数据由 collector 直接入库 |
| `collected_at` | TEXT | 采集时间 ISO8601 |
| `raw_json` | TEXT | 原始响应 JSON |

#### market_events (事件)

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_hash` | TEXT PK | 事件唯一哈希 |
| `provider` | TEXT | 来源，例如 `tushare_news`、`tushare_anns_d`、`tushare_report_rc`；RSS/Tavily/agent 文件源不是现役生产 collector |
| `event_type` | TEXT | 事件类型 |
| `event_time` | TEXT | 事件时间 |
| `market` | TEXT | 相关市场 |
| `symbol` | TEXT | 相关品种 |
| `title` | TEXT | 标题 |
| `content` | TEXT | 内容 |
| `url` | TEXT | 来源 URL |
| `source` | TEXT | 源名称 |
| `collected_at` | TEXT | 采集时间 |

Tushare `news` / `major_news` / `cctv_news` / `anns_d` / `report_rc` 进入 `market_events` 时由直接入库层补齐 `event_hash`、`event_type`、`event_time`、`trade_date`、`provider` 和 `source_file`。SEC EDGAR filings manual pilot collector 也写入 `market_events`，provider 为 `sec_edgar`，event_type 形如 `sec_edgar:10-K`。`/events` 只读取 SQLite `market_events`，不再回退旧事件候选文件。

SEC EDGAR pilot rows use `market="US"` and `symbol="CIK##########"`; for example, query Apple filing rows through `/events?market=US&event_type=sec_edgar:4&subject_code=CIK0000320193&limit=5`. This remains a manual pilot until scheduled cadence and SLA evidence are approved.

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
| `source_file` | TEXT | 来源标识（采集运行 key/路径），仅作迁移/审计参考 |
| `collected_at` | TEXT | 采集时间 |
| `raw_json` | TEXT | 原始行 JSON |

低频宏观接口（`cn_cpi`、`cn_pmi`、`cn_m`、`cn_ppi`、`cn_gdp`、`sf_month`、`shibor`、`shibor_lpr`、`us_tycr`、`us_tbr`、`us_tltr`、`repo_daily`）由 P4/P6 定时采集直接写入 read model，再展开为 `market_factors`；CSV 仅作为 staging/历史迁移材料。A股 `moneyflow` 是盘后日频资金流，按 P1 全市场采集后展开为 `moneyflow:*` 因子；盘中 5 分钟交易不依赖当天 `moneyflow` 即时更新。月度/季度字段只作为 `event_time`，不作为数值因子。

SEC EDGAR `companyfacts` 手动 pilot 写入 `market_factors`，provider 为 `sec_edgar_companyfacts`，symbol 使用 `CIK##########`，factor_name 形如 `sec_edgar_companyfacts:Assets`、`sec_edgar_companyfacts:RevenueFromContractWithCustomerExcludingAssessedTax`。该模式只采集显式 allowlist 概念，不批量导入全部 XBRL facts；通过 `/fundamentals?ts_code=CIK0000320193&limit=20` 读取。

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

所有 reader 函数位于 SharedSignals `reader.py`（HTTP API 与内部读取入口），`bridge/marketgraph_marketdata_db.py` 仅保留跨仓兼容辅助模块。辅助的 `reference/market_calendar.py` 只读 SharedSignals read model，不再导入旧 A 股 Tushare wrapper 或现场调用 provider。

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

#### `read_events(provider="", event_type="", market="", symbol="", subject_code="", limit=200)`

读取新闻/事件流。

**参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `provider` | `str` | `""` | 来源过滤，例如 `tushare_news`、`tushare_anns_d`、`tushare_report_rc`；RSS/Tavily/agent 文件源不是现役生产 collector |
| `event_type` | `str` | `""` | 事件类型 |
| `market` | `str` | `""` | 过滤市场，如 `Ashare`、`US`、`Futures` |
| `symbol` | `str` | `""` | 过滤标的代码 |
| `subject_code` | `str` | `""` | 过滤事件主体代码，兼容 `600276.SH` / `SH600276` / `600276` |
| `limit` | `int` | `200` | 最大返回行数 (上限 5000) |

**返回**: `list[dict]` — 按 `collected_at` 降序排列

**示例**:
```python
from marketgraph_marketdata_db import read_events

# 最近 100 条新闻/公告事件（事件采集当前由 Tushare event lane 提供；RSS/RSSHub 已退役，恢复前需按 SharedSignals collector 重新接入）
events = read_events(provider="tushare_news", limit=100)
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

**HTTP**: `GET /pm_prices?market_id=<market_id>&limit=200`

`market_id` 可省略；省略时返回最近价格快照。该端点只读取 `market_pm_prices`，用于 TradingAgent/MarketGraph 获取市场价格，不承载 `research_probability`、`marketgraph_probability`、`model_probability` 等判断字段。

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
| Crypto 行情 | 30min | SQLite read model | ≤ 45min |
| Polymarket 价格 | 30min | SQLite read model | ≤ 45min |
| Crypto 因子 | 按需/低频 | SQLite read model | ≤ 6h |
| A 股日线 | 盘后 EOD | 日级 | 最新交易日 |
| 美股日线 | 盘后 EOD | 日级 | 最新交易日 |
| Tushare 新闻/公告事件 | 30min event lane | SQLite read model | 最新 collected_at |
| 基本面 | 日级预计算 | 按需 | 季度报告期后 |
| A股/指数周月线 | P7 weekly wrapper | 周级刷新 | 最新周/月周期 |

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

**DB-first** — 通过 SharedSignals reader 读取已采集 Tushare 数据。该接口只查询 read model 映射表；不再路由到旧 A 股兼容 wrapper 做现场 provider 调用。无映射或无缓存数据时返回 degraded 包装。

**参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `api_name` | `str` | 必填 | Tushare API 名，如 `daily`、`moneyflow`、`fina_indicator`、`income`、`balancesheet`、`adj_factor`、`margin`、`limit_list`、`rt_min`、`news`、`major_news`、`cctv_news`、`anns_d`、`report_rc` 等；已配置采集且已映射 SQLite 的接口应全部开放 |
| `ts_code` | `str` | `None` | 股票代码，自动注入到 params 中 |
| `start_date` | `str` | `None` | 起始日期 YYYYMMDD，自动注入到 params 中 |
| `end_date` | `str` | `None` | 截止日期 YYYYMMDD，自动注入到 params 中 |
| `**params` | — | — | 查询 read model 的过滤参数；不透传现场 provider 调用 |

**返回**: `list[dict]` — 每条含 `data` / `provenance` / `freshness` / `quality` / `degraded` / `lineage`

**日线批量读取边界**：`get_tushare("daily")` / `GET /tushare?api_name=daily`
在未传 `ts_code`、`start_date`、`end_date` 时，只读取
`market_bars_daily` 中 `market="Ashare"` 且 `provider="tushare_daily"`
的最新交易日 rows，并将 `limit` 下推到 SQL。该路径用于 TradingAgent
盘前覆盖检查、流动性排序和外部 API 批量读取，不现场调用 Tushare，也不扫全量
历史日线表。

**示例**:
```python
from reader import get_tushare

# 读取贵州茅台日线行情
rows = get_tushare("daily", ts_code="600519.SH", start_date="20260601", end_date="20260630")
for row in rows:
    d = row["data"]
    print(f"{d['trade_date']}: O={d['open']} C={d['close']}")

# 读取个股资金流向；返回 market_factors 展开行，如 moneyflow:net_mf_amount
rows = get_tushare("moneyflow", ts_code="000001.SZ", start_date="20260629", end_date="20260629")

# 读取财务指标
rows = get_tushare("fina_indicator", ts_code="600519.SH", start_date="20250101")

# 读取任意 Tushare API，传额外参数
rows = get_tushare("income", ts_code="600519.SH", period="20251231")
```

**错误处理**: read model 未映射、无缓存、DB 不可用或数据为空时返回 degraded 包装，不抛异常，不现场补采。

**数据新鲜度**: Tushare 数据由 P0-P7 定时 collector 维护；A 股 P0 和 China futures 交易时段保留 5 分钟级，Crypto/Polymarket 在当前服务器上按 30 分钟供数，P1-P7 按日频、研究频率或低频参考频率维护，其中 P7 周/月线按低频 wrapper 独立维护；新闻/公告/研报事件通过 30 分钟 full event lane 维护，`news/major_news` 另有 15 分钟 supplemental pilot。

### 外部 Agent 调用规则

外部 agent 只能把 SharedSignals HTTP API 当作数据入口，不得绕过 SharedSignals 直接调用 Tushare、Binance、Polymarket、CSV、NDJSON、SQLite 文件、RSS 旧目录或其它 sibling repo 内部文件。

调用时必须：

1. 先读取 `/health`、`/agent_config`、`/source_status` 与 `/opening_gate`，确认服务健康、接入规则、频率标签、接口纳管状态、当前交易时点供数门和禁止绕过边界。
2. 优先使用业务端点：`/market_data`、`/realtime_5min`、`/events`、`/fundamentals`、`/macro`、`/pm_markets`、`/pm_prices`。
3. 需要 Tushare 原生维度时使用 `/tushare?api_name=...&limit=...`；该接口仍然只读数据库，不现场调用 Tushare。
4. 每次读取都检查 `metadata.degraded`、`metadata.degraded_reasons`、`freshness`、`provenance.source_id`、行内 `trade_date/event_time/collected_at`。
5. 按市场和频率理解数据：A股/期货保留 5 分钟交易输入；Crypto/PM 当前是 30 分钟供数；日频、周月线、财务、宏观、研报、公告不得当作 5 分钟行情。
6. 无数据或 degraded 时 fail closed：返回“数据不足/不可用”，不要自动改走 provider、旧文件或其它仓库。

隔离外部账号建议使用 `external_read` scope。它覆盖完整数据读取面，包括 `/health`、`/agent_config`、`/source_status`、`/opening_gate`、业务端点和 `/tushare` 数据库输出；不覆盖 `/cache/invalidate`、生产写入、provider key、数据库文件或运维权限。

复制给外部 agent 的一键接入 prompt 维护在 `docs/external_agent_api_prompt.md`；机器可读配置维护在 `config/external_agent_api_config.json`，并通过 `GET /agent_config` 输出。完整 HTTP 路径以本文档“HTTP API 端点概览”为准，外部 agent 配置同步列出 23 个可发现路径，并用 `cadence_class` 区分交易、研究、session readiness、delegated projection、source governance 和 operator health/control。新增数据源接入规则维护在 `docs/data_source_onboarding.md`；事件 lane 独立说明维护在 `docs/event_lane.md`。Tushare 接口激活台账维护在 `docs/tushare_activation_backlog.md`；当前 114 个 allowlisted 接口中 113 个进入生产配置层，`rt_fut_min` 保持独立 5 分钟期货入口，0 个 planned 待启用。

### 数据维度来源标注

以下标注哪些数据维度由 SharedSignals 原生采集直接写入 read model；历史 "bridge" 仅指迁移/兼容辅助层，不作为现役采集成功路径：

| 数据维度 | 来源 | 方式 |
|---------|------|------|
| A 股日线 OHLCV | Tushare `daily` | DB-first: `reader.get_tushare("daily", ...)` / HTTP `/tushare` |
| A 股资金流向 | Tushare `moneyflow` / `moneyflow_hsgt` / `margin` / `margin_detail` | P1 盘后日频采集；DB-first: HTTP `/capital_flow` 读取 `market_factors` 中 `tushare_moneyflow`、`tushare_moneyflow_hsgt`、`tushare_margin`、`tushare_margin_detail` 展开行；也支持 `reader.get_tushare("moneyflow", ...)` 等原生维度 |
| A 股财务指标 | Tushare `fina_indicator` | P2 collector → `market_factors`; `reader.get_fundamentals(ts_code=...)`（HTTP 也兼容 `symbol`） |
| A 股审计/主营构成 | Tushare `fina_audit` / `fina_mainbz` | P2 collector → `market_factors`; 报告期优先作为 `event_time`，公告日保留在 `raw_json`；DB-first `/fundamentals` / `/tushare` |
| A 股利润表 / 资产负债表 | Tushare `income` / `balancesheet` | P2 collector → read model / degraded if no recent rows |
| A 股复权因子 | Tushare `adj_factor` | P0/P1 collector → read model |
| A 股融资融券 | Tushare `margin`/`margin_secs` | P0/P1 collector → `market_factors`/read model |
| A 股涨跌停列表 | Tushare `limit_list` | P0/P1 collector → read model |
| A 股龙虎榜/竞价/涨跌停价格 | Tushare `top_list` / `stk_auction` / `limit_step` / `stk_limit` | P1 collector → `market_factors`; 只作为结构化行情/盘口参考，不生成交易判断 |
| A 股题材/指数成分参考 | Tushare `concept` / `concept_detail` / `hs_const` | P3 collector → `market_assets`; 只作为参考/归因维度，不作为行情价格 |
| A 股题材/行业/名称参考 | Tushare `namechange` / `ths_index` / `dc_index` / `index_classify` | P3 collector → `market_events` 或 `market_assets`; 只作为参考/归因维度，不生成交易判断 |
| A 股主题/指数成分关系 | Tushare `ths_member` / `dc_member` / `index_member` / `index_member_all` | P3 collector → `market_relationships`; 保留 parent/child 多对多关系，DB-first `/tushare` |
| A 股主题/行业日线 | Tushare `ths_daily` / `dc_daily` | P3 collector → `market_bars_daily`; 日频主题/行业参考，不进入 5 分钟交易通道 |
| A 股筹码/备用基础/热度 | Tushare `cyq_perf` / `cyq_chips` / `bak_basic` / `ths_hot` | P1/P3 collectors → `market_factors`; 日频或 pilot 因子，不进入 P0 5 分钟快车道 |
| A 股北向资金/沪深港通资金 | Tushare `moneyflow_hsgt` | P1 collector → `market_factors`; DB-first `/tushare?api_name=moneyflow_hsgt` |
| A 股分钟线 | Tushare `rt_min` 盘中快照 | P0 每 5 分钟从 SQLite `market_assets` 读取完整 active universe，并按 provider 上限每 300 只一批调用 `rt_min` 后直接写 `market_bars_intraday`，自然累积全天 5 分钟历史；不使用轮转、优先池、跨系统文件或重复 `stk_mins` 路径。任一预期非空批次返回空即计入关键采集失败。`health_sla` 在连续交易窗口按完整股票池检查新鲜覆盖率，默认低于 80% 为 critical；`reader.get_realtime_5min(market="Ashare")` / HTTP `/realtime_5min?market=Ashare` 只读 SQLite read model，无数据返回 degraded/empty，不回退 CSV 或旧目录 |
| A 股/指数周月线 | Tushare `weekly` / `monthly` / `index_weekly` / `index_monthly` | P7 low-frequency wrapper → `market_bars_intraday` with interval=`weekly`/`monthly`/`index_weekly`/`index_monthly`; DB-first `/tushare` |
| A 股国债逆回购 | Tushare `repo_daily` | P1/P4 collector → `market_factors`，同时投影到 `market_bars_daily`；`204001.SH` 等逆回购代码可通过 `/market_data` 读取 `close` 作为年化利率百分值 |
| A 股新闻/公告/研报 | Tushare `news` / `major_news` / `cctv_news` / `anns_d` / `report_rc` | 30min full event lane → `market_events`; `news/major_news` 另有 15min supplemental pilot；`/events` 与 `/tushare` 均 DB-first；no live provider fallback |
| Crypto klines/ticker | Binance collector → marketdata.sqlite | Direct DB: `/crypto`, `read_daily("Crypto", ...)` |
| Crypto markets | marketdata.sqlite | Direct DB: `read_crypto_markets()` |
| US 日线 | marketdata.sqlite | Direct DB: `read_daily("US", ...)` |
| HK 日线/基础/财务 | Tushare `hk_daily` / `hk_basic` / `hk_income` / `hk_balancesheet` / `hk_cashflow` | P5 collector → read model; DB-first `/market_data` and `/tushare` |
| 全球指数日线 | Tushare `index_global` | collector → `market_bars_daily`，market=`Global` |
| ETF 基础信息 | Tushare `etf_basic` | collector → `market_assets`，market=`ETF` |
| 期货基础信息 | Tushare `fut_basic` | collector → `market_assets`，market=`Futures`；需采集 `last_ddate` 与 `delist_date`，分别映射到 `last_trade_date` 与 `expiry_date` |
| 期货日线 OHLCV | Tushare `fut_daily` | collector → `market_bars_daily`，market=`Futures`；按 `trade_date` 全品种采集，不使用 A 股股票列表 |
| 期货 5 分钟 OHLCV | AkShare/Sina 默认；Tushare `rt_fut_min` 可显式启用 | CNFutures 5 分钟 collector → `market_bars_intraday`，market=`Futures`，interval=`5min`；HTTP `/realtime_5min?market=Futures` 或 `market=CNFutures` 可读取同一 read model 并透传可空 bid/ask/size 字段；独立调度，不进入日频 `P6_other_daily` |
| 期货参考限制 | Tushare `ft_limit` | P6 collector → `market_factors`; DB-first `/tushare?api_name=ft_limit` |
| 期货持仓排名 | Tushare `fut_holding` | P6 collector → `market_factors`; 日频持仓/席位参考，不作为订单簿或执行数据 |
| 基金/可转债/期权支持数据 | Tushare `fund_share` / `fund_div` / `fund_adj` / `fund_portfolio` / `cb_basic` / `cb_issue` / `opt_basic` | P3/P6 collectors → `market_factors` / `market_fund_portfolio` / `market_assets` / `market_events`; fund portfolio 保留基金代码、持仓股票、公告日、报告期和持仓市值明细，不展开为通用因子；DB-first `/tushare` |
| 期权日线 | Tushare `opt_daily` | P6 collector → `market_bars_daily`; 期权 EOD 支持数据，不作为实时盘口 |
| Polymarket 市场/价格 | Polymarket collector → marketdata.sqlite | Internal reader: `read_pm_markets()` / `read_pm_prices()`；HTTP `/pm_markets` 返回市场元数据和联表最新价，`/pm_prices` 返回价格快照 |
| 事件/信号 | Tushare news/announcements/sentiment-style events → `market_events`; RSS/Tavily retired/deferred | `reader.get_events()` 只读 SQLite `market_events`；`reader.get_sentiment()` 读取 `reference/sentiment_event_types.yaml` 中配置的 sentiment 源事件类型（默认含 `sentiment`、`major_news`、`news`、`cctv_news`），不回退旧情绪文件 |
| 交易日历 | `market_bars_daily` read model | DB-first: `reader.is_trading_day()`；未来/周末日期使用 weekday fallback，不现场调用 provider |
| 参考表 | Read model tables | `reader.get_reference()` 对旧 CSV reference 返回 degraded；生产消费者应使用明确 HTTP API 端点 |
| 宏观因子 | Tushare P4 macro/rates/FX/global + read model | P4 collector → `market_factors`；`/macro` 读取 `cn_cpi/cn_gdp/cn_m/cn_pmi/cn_ppi/sf_month/shibor/shibor_lpr/hibor/libor/us_tycr/us_tbr/us_tltr/fx_daily/repo_daily/index_global/index_dailybasic` 展开行，并兼容 `event_time` 为月度/季度格式 |

### 关联查询 (Association Queries)

#### `get_industry(ts_code)`

**NEW** — 查询股票的行业/产业链/板块/概念信息。

只读取 SQLite `market_assets` 中的 `sector/industry` 基础行业字段，并在 provenance/lineage 中标记为 `sqlite:market_assets`。旧行业映射文件不作为生产 API 兜底。

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

读取 SharedSignals 暴露的 associations read-model 投影。该投影可由 MarketGraph 研究图谱生成并同步到 SharedSignals，但消费者只能通过 SharedSignals API/reader 查询，不直接读取 MarketGraph 仓库文件。

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

读取 SharedSignals 暴露的 impacts read-model 投影。该投影可由 MarketGraph 研究图谱生成并同步到 SharedSignals，但消费者只能通过 SharedSignals API/reader 查询，不直接读取 MarketGraph 仓库文件。

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
| **硬错误** | SQLite 损坏、磁盘满 | 记录日志并返回 degraded/error；由 watchdog/heal 触发恢复，不回退 CSV 或旧目录 |

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
        # Fail closed: no CSV/legacy fallback in production readers.
        return degraded_empty_response(market, reason="sqlite_unavailable")
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
| 2026-07-10 | 1.1.39 | A股 P0 从每轮 30 只优先/轮转改为 `rt_min` 每批最多 300 只、每 5 分钟覆盖完整 active universe；移除旧游标与优先池配置，空批次计关键失败；退役重复且盘中无数据的 `stk_mins` 生产能力；health SLA 新增盘中 active-universe 覆盖率门禁。 |
| 2026-07-10 | 1.1.38 | 修复 SQL 时间格式的开盘闸门解析和控制面缓存；DuckDB 大表改为受限资源的哈希增量镜像，并把闸门与镜像结果纳入 `/health`、`/source_status`。外部入口文档统一为 Cloudflare 橙云 A 记录/Nginx。 |
| 2026-07-10 | 1.1.37 | 增加 `/opening_gate` 与四个交易时点轻量供数门，外部 agent 可在使用行情前读取当前门状态。 |
| 2026-07-10 | 1.1.36 | 外部入口统一为 `https://signals.tradingagent.cc` 并通过 Cloudflare Tunnel/DNS 对外可达；API 账号层级拆分为 `internal` 内部使用与未来 `starter/research/pro/enterprise` 分级套餐，`free` 保留兼容。 |
| 2026-07-10 | 1.1.35 | 新增外部隔离账号 `external_read` scope，并让 token 鉴权支持 `X-API-Key` header；该 scope 提供完整数据读权限（含 `/tushare` read-model 输出），但不含 `/cache/invalidate` 运维控制。 |
| 2026-07-09 | 1.1.34 | `/source_status` 增加 API/module catalog 与 source expansion plan 映射检查，确认 planned 数据源没有误启用、候选模块能映射到默认 HTTP surface 和 read-model 表、扩源默认复用现有 API。 |
| 2026-07-09 | 1.1.33 | 新增 `config/api_module_catalog.yaml` 模块/API 规划目录，规定新增数据源先按模块映射到 read-model 表和默认 HTTP surface，默认复用现有 API；只有新查询形态、独立 SLA/auth/分页/限流等情况才新增 endpoint。 |
| 2026-07-09 | 1.1.32 | 新增 `config/source_expansion_priority.yaml` 横向数据源扩展队列，并在 `/agent_config` 的 `data_source_onboarding` 中暴露 planned-only 扩源状态、优先批次和准入门槛；计划源不代表生产 collector 已启用。 |
| 2026-07-09 | 1.1.31 | 新增 `/source_status` 与 `tools/source_governance_monitor.py`，按 green/yellow/red 输出接口纳管、调度重复、SLA 和能力 registry 治理状态；外部 agent 配置扩展到 22 个 HTTP 路径。 |
| 2026-07-09 | 1.1.30 | 事件 lane 增加 `news/major_news` 15 分钟 supplemental pilot，公告/研报/CCTV 仍保持 30 分钟 full event lane；明确 `market_factors` 是事实型 read-model 输出，TradingAgent 负责交易因子提取、打分和决策。 |
| 2026-07-09 | 1.1.29 | 补齐外部 agent 机器配置的完整 21 个 HTTP 路径，新增 `docs/event_lane.md` 与 `docs/data_source_onboarding.md`，明确事件 lane 和未来数据源接入治理规则；P6 生产配置接口补齐 frequency 声明。 |
| 2026-07-09 | 1.1.28 | 生产热路径降载：Crypto ticker 与 Polymarket markets/prices 从 5 分钟改为 30 分钟，Crypto 1d support bars 改为 6 小时；DuckDB mirror 与 capability scan 避开 09:00-15:59 中国交易高峰，patrol/health_sla 改为错峰运行。 |
| 2026-07-09 | 1.1.27 | `/tushare?api_name=daily` 无代码/无日期请求改为限定 A股最新交易日和 `provider=tushare_daily` 后读取，避免生产大日线表无界排序超时；用于 TradingAgent 盘前批量日线覆盖和流动性排序。 |
| 2026-07-09 | 1.1.26 | 将 Tushare `fund_portfolio` 从 `market_factors` 因子展开迁移到专用 `market_fund_portfolio` 明细表，保留 `symbol` 基金代码、`holding_symbol` 持仓股票、`ann_date`、`end_date`、市值和占比字段；减少单公告日写入放大和大表索引压力。 |
| 2026-07-09 | 1.1.25 | 启用最后 8 个 planned Tushare 接口：`bak_basic`、`cyq_perf`、`cyq_chips`、`fina_audit`、`fina_mainbz`、`fund_adj`、`fund_portfolio`、`ths_hot` 全部写入 `market_factors`；Tushare 生产配置接口从 106 增至 114，planned backlog 从 8 降至 0。 |
| 2026-07-09 | 1.1.24 | 启用 B2 日频支持数据：`ths_daily`、`dc_daily`、`opt_daily` 写入 `market_bars_daily`，`fut_holding` 写入 `market_factors`；Tushare 生产配置接口从 102 增至 106，planned backlog 从 12 降至 8。 |
| 2026-07-09 | 1.1.23 | 启用 B1 关系/成分数据：新增 `market_relationships` read model，`ths_member`、`dc_member`、`index_member`、`index_member_all` 进入 P3 日频参考层；Tushare 生产配置接口从 98 增至 102，planned backlog 从 16 降至 12。 |
| 2026-07-09 | 1.1.22 | 新增 `/agent_config` 外部 agent 机器接入配置端点，补充一键复制 prompt 与 16 个 planned Tushare 接口的分批激活 backlog，明确外部 agent 应先读健康/配置再按市场和频率调用。 |
| 2026-07-09 | 1.1.21 | 明确 SharedSignals 是分钟级/5 分钟级交易数据供给层，不是毫秒级 HFT 或执行系统；Tushare 生产 tier 扩展到 P0-P7，新增 P7 周/月线低频 lane、事件 30 分钟 lane、第一批 planned-to-scheduled 数据维度和外部 agent 调用规则。 |
| 2026-07-09 | 1.1.20 | 补齐 HTTP `/capabilities` 与 `/cache/status` 合同；澄清 `/associations`、`/impacts` 是 SharedSignals API/read-model 输出，消费者不得直接读取 MarketGraph 仓库文件；保留 localhost bypass 默认关闭的安全边界。 |
| 2026-07-09 | 1.1.20-cleanup | 删除仓库跟踪的旧 Parquet 冷归档样本、旧 `storage/archive_manager.py` / `storage/query_router.py` cold path、Polymarket parquet loader 配置和 `ingest_csv_to_sqlite` 文件桥入口；read-model 写入只保留 rows-only `ingest_rows_to_sqlite()`，并加测试门禁防恢复。 |
| 2026-07-09 | 1.1.19 | 统一 reader/API 市场名规范化：`CNFutures`、`cn_futures` 等别名映射到 `Futures`，`PM`/`Polymarket` 映射到 `PredictionMarkets`；`/realtime_5min`、`/tushare` 资产读取和事件过滤共用同一市场识别规则。同步更正 CNFutures 5 分钟默认 provider 为 AkShare/Sina，Tushare `rt_fut_min` 仅保留为显式可选 provider。 |
| 2026-07-08 | 1.1.18 | 删除 SharedSignals 仓库内旧 `data/*.csv` 样本和 Tushare wrapper 的 repo CSV cache；现役采集结果必须直接写 SQLite/DuckDB read model，再通过 HTTP API 输出。 |
| 2026-07-08 | 1.1.17 | `/tushare?api_name=fut_basic`、`hk_basic`、`us_basic`、`etf_basic` 等资产类接口按对应 market 过滤 `market_assets`，不再把所有资产接口默认限定为 A股；TradingAgent/CNFutures 可通过 SharedSignals API 获取期货合约资产列表。 |
| 2026-07-08 | 1.1.16 | 生产采集链路收口为 provider rows 直接写 SQLite read model；删除 CSV-only 成功开关、旧 `rt_k` 映射和 reader/API CSV fallback 文档口径；非空 rows 写入 0 行会标记 `failed` 并计入 `sqlite_failure_count`。 |
| 2026-07-08 | 1.1.15 | 历史记录：当时 Tushare P0-P6 配置接口增加入库完整性门禁；当前生产已扩展到 P0-P7。该轮补齐 `top_list`、`limit_step`、`stk_auction`、`stk_limit`、`concept`、`concept_detail`、`hs_const` 的 read model 映射；非空采集结果写入 SQLite 0 行会标记 `failed`，防止数据只停留在 staging 而 HTTP API 不可见；`/market_data` 的 `freq=1m/5m/15m/30m/60m` 改为读取 `market_bars_intraday`，不再返回误导性的 unsupported。 |
| 2026-07-08 | 1.1.14 | 历史记录：A股 P0 曾短暂读取 TradingAgent no-trade/execution-exclusion 文件补价；当前已退役，P0 优先池只允许来自 SharedSignals read model 或显式环境变量。 |
| 2026-07-08 | 1.1.13 | A股 P0 5分钟通道收窄为 `stk_mins`/`rt_min` 分钟行情，默认 30 只优先/轮转批次；P0 只在 09:30-11:30、13:00-15:00 推进游标并按交易日重置；优先池仅来自 SharedSignals read model 或显式环境变量，不读取 TradingAgent/MarketGraph 内部文件；`daily`/`stk_factor`/`stk_factor_pro` 转入 P1 盘后日频 90 天窗口，避免日频重任务或盘前空跑拖住交易时段 `market_bars_intraday` 更新。 |
| 2026-07-06 | 1.1.12 | 历史记录：CNFutures 5 分钟采集曾增加 AKShare/Sina 模拟盘备源；当前该备源已退役，`rt_fut_min` provider 错误和非空写库 0 行必须返回 `failed`。 |
| 2026-07-06 | 1.1.11 | A股 P0 实时分钟接口从旧分钟接口收口到 Tushare `rt_min`；`repo_daily` 保留因子写入并额外投影到 `market_bars_daily`，使 `204001.SH` 可通过 `/market_data` 读取逆回购日线收益率。 |
| 2026-07-05 | 1.1.10 | `/realtime_5min` 增加 `market` 参数，默认兼容 A股，同时支持 `market=Futures` 等非 A股 5 分钟 read model 输出；reader 会透传新增 L1 盘口字段。 |
| 2026-07-05 | 1.1.9 | CNFutures `market_bars_intraday` 增加可空一级 bid/ask、盘口量、last_trade_date/expiry_date 字段；入库层支持 `rt_fut_min` 盘口字段透传，并可从 `market_assets` 补合约到期字段；`fut_basic` 配置补采 `last_ddate/delist_date`；`/realtime_5min` 支持 `market=Futures` 读取期货分钟线。 |
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
