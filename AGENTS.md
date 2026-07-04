# SharedSignals

> **阅读顺序：** 进入 SharedSignals 后，按以下顺序阅读：
> 1. 本文件 — 理解 SharedSignals 的规则和边界
> 2. **[STATUS.md](STATUS.md)** — 理解当前状态、已知问题、下一步任务
> 3. 跨系统协作前，读 [根目录 AGENTS.md](../AGENTS.md) 和 [根 STATUS.md](../STATUS.md) 了解三系统架构和全局状态

## 层级披露

- 上层 `~/Projects/Finance/AGENTS.md` 只定义 Finance 工作区三项目边界和跨项目协作规则。
- 本文件只定义 SharedSignals 的数据采集、存储、staging、桥接、patrol/heal 和输出契约。
- 进入具体采集器、storage、bridge、reference 或 docs 后，继续读取最近层级文档；采集命令、schema 和运行边界以本仓库文档为准。

## 目标
统一数据采集与存储，供研究线和交易线共享读取。


## 三系统协作边界

- SharedSignals 是供数层，只负责采集、去重、缓存和健康巡查；不做投资分析、交易判断、执行路由或回执处理。
- MarketGraph 和 TradingAgent 可以读取 SharedSignals 暴露的 SQLite/CSV/NDJSON 或未来服务接口；这种关系是数据契约消费，不是 MCP 强耦合互调。
- 对 TradingAgent 而言，SharedSignals/ShareChannel API 是默认消费入口；SQLite/CSV/NDJSON 只保留为兼容和故障降级，不能重新引入 TradingAgent/MarketGraph 独立采集。
- 未来对外提供服务接口时，默认只暴露数据读取、健康状态和来源留痕；任何交易信号、下单、模拟执行或邮件通知都属于 tradingagent/Hermes 边界。
## 边界
- 做什么: 采集行情/事件/基本面/资金/宏观, 去重入库
- 不做什么: 不分析, 不分类, 不做交易决策
- 存储: SQLite read model + DuckDB mirror + CSV + NDJSON staging

## 现状
- 行情: Tushare/Binance/PM(markets/prices) → SQLite + DuckDB + CSV/NDJSON 缓存；具体接口数以 `collectors/tushare/config.yaml` 和 `STATUS.md` 当前记录为准
- 事件: RSS/RSSHub/Tavily/DeepSeek 当前不作为现役生产 collector；恢复前必须走 SharedSignals collector + staging/bridge 契约
- 基本面: Tushare 财务/分红/融资融券等由分层定时任务采集落库，写入 `market_factors`；reader/API 只读缓存，不现场调用 provider
- staging: 6 streams (collection_runs/sentiment_signals/event_candidates/...)

## 依赖
- 采集输入: 外部 API (Tushare/Binance/PM/RSS/Tavily/DeepSeek) 只允许在 SharedSignals collector 层调用；未启用的数据源不得被 MarketGraph/TradingAgent 绕过 SharedSignals 直接调用
- 输出: SQLite + DuckDB + CSV + NDJSON/只读服务接口 → MarketGraph 和 TradingAgent 按契约读取

## 巡查自愈系统 (patrol + heal)

### patrol.py — 10min巡检
检查6个维度:
- source_health: 每个source最近采集时间, 超时→stale (只标记已采集过的源)
- data_freshness: marketdata.sqlite最新trade_date, 超过1天→stale
- staging_backpressure: pending NDJSON文件数, >100→backpressure
- sqlite_health: WAL文件大小(>100MB→checkpoint), 锁等待→告警, 完整性检查
- disk_usage: >80%告警, >90%停止采集
- field_drift: 实际CSV字段 vs expected_fields不匹配→告警

输出: JSON {checks: [{name, status, value, threshold, alert}], overall_score}

### heal.py — 自愈动作
- source down → 切换备用源(source_failover.py)
- 数据缺失 → 触发补采(重跑marketdata_db --ingest)
- staging积压 → 强制运行runtime_bridge --apply
- SQLite锁 → 等待5s重试, 清理WAL(PRAGMA wal_checkpoint)
- 磁盘满 → 清理旧archive(>30天Parquet), >90%发出停止采集信号
- 字段漂变 → 更新expected_fields.json + 告警
- 自愈失败 → 紧急告警(emergency_alerts.log) → 人工介入

### memory/ — 闭环记录
- patrol_history.jsonl: 每次巡查结果
- heal_actions.jsonl: 每次自愈动作
- patterns.jsonl: 发现的模式(周复盘迭代规则)
- failover_history.jsonl: 源切换历史

### source_failover.py — 源故障切换
预配置FAILOVER_MAP: 主源↔备用源映射, 覆盖A股/港股/美股/Crypto/PM/全球新闻/宏观等源。

## 文件结构
- collectors/ — 各数据源采集器
- storage/ — schema文档 (当前SQLite, 计划DuckDB)
- bridge/ — staging→CSV/SQLite 归并桥
- reference/ — 参考数据、expected_fields.json 与只读缓存辅助工具；不得放回旧 Ashare/RSSCollector 软链入口
- memory/ — 采集层记忆 + 巡查/自愈历史
- staging/ — 本层staging缓冲
- patrol.py — 10min巡查 (6维度健康检查)
- heal.py — 自愈引擎 (failover/backfill/merge/checkpoint/cleanup/drift)
- source_failover.py — 源故障切换映射
- logs/ — 紧急告警 (emergency_alerts.log)

## Projects 工作区同步补充

本仓库位于 `/Users/nicholashan/Projects/Finance/SharedSignals` 时，按 Projects 工作区统一同步规则执行：

- 仓库地址、remote 名称和默认分支以本仓库内 `git remote -v`、`git branch --show-current` 和项目文档为准，不从其它项目继承。
- 开发前检查 `git status -sb`、`git remote -v`、当前分支和是否落后远端；发现采集、存储、桥接或其它 agent 的未提交改动时，先确认来源，不得覆盖。
- 涉及采集源、SQLite/CSV/NDJSON staging、schema、API contract、bridge、patrol/heal、failover 或对 MarketGraph/TradingAgent 的输出契约时，必须同步更新核心文档，例如 `README.md`、`STATUS.md`、`API_CONTRACT.md`、`LOG.md` 或 `docs/` 下对应说明。
- 提交时只暂存本次审计过的文件；数据库、缓存、日志、staging、密钥和本机运行产物默认不提交，除非项目文档明确要求并已审计。
- 从旧 `Desktop/Works/02.AI_Projects` 或其它 iCloud 管理目录迁移时，优先使用当前 Projects 下真实 clone；旧目录只作为对照和补漏来源。

## 2026-07-01 定时采集与 Tushare tier 口径修正

- SharedSignals 到 TradingAgent 的关系是“定时采集沉淀 + reader/read model 按需读取”，不是 TradingAgent 每次判断时重新现场采集。
- Tushare `sync_daily.py` 当前只支持：`P0_trading_5min`、`P1_eod_daily`、`P2_financial_daily`、`P3_reference_daily`、`P4_macro_daily`、`P5_hk_us_daily`、`P6_other_daily`。
- A股盘中 P0 采集保持交易时段每 5 分钟；P1/P2/P3/P4 分别按盘后、晚间、盘前、早间日频维护。
- HK/US Tushare daily 采集使用 `P5_hk_us_daily`，按港股收盘后和美股收盘后日频维护；期货/基金/ETF/新闻等使用 `P6_other_daily` 日频维护。
- `collectors/tushare/config.yaml` 已删除无效 `P7_crypto_pm_5min` 顶层配置；Crypto/PM 不属于 Tushare tier，必须走各自 collector/reader，不得重新启用旧 `P7_crypto_pm` cron。

## 2026-07-04 SharedSignals-only 数据边界

- SharedSignals 是三系统唯一外部数据采集入口；MarketGraph 和 TradingAgent 不得重新启用独立 Tushare/RSS/PM/Crypto provider 采集任务。
- `reader.py` 和 HTTP API 必须优先读取 `/opt/investment/MarketGraphRuntime/read_model/marketdata.sqlite` 与本仓库 DuckDB/CSV 产物；无缓存、无映射或无数据时返回 degraded，不现场调用 Tushare。
- 生产 API 默认绑定 `127.0.0.1:8082`；本机消费者可通过 `SHAREDSIGNALS_LOCALHOST_BYPASS=1` 访问，外部账号接入必须配置 token/JWT 和账号并发限制。
- Tushare 无积分消耗但有并发/频率约束；P0 交易时段每 5 分钟采集，P1-P6 按交易/研究需要分层调度，所有结果先落库再供 MarketGraph/TradingAgent 读取。
- DuckDB/SQLite 同步和 watchdog 必须以 `marketgraph` 运行用户执行；若手工维护导致数据或日志文件变成 root 属主，应恢复为 `marketgraph:marketgraph` 后再验证 cron。
- RSS/RSSHub 边界：RSS 采集代码和数据消费契约归 SharedSignals；旧 RSSCollector cron 已禁用，旧 RSSHub/RSSCollector 顶层运行资产应退出现役层。`/opt/investment/MarketGraphRuntime/rss_collector.db` 仅作历史/迁移审计，恢复事件采集前必须重新接入 SharedSignals collector、staging/bridge、健康检查和回滚方案。
