# SharedSignals

> **阅读顺序：** 进入 SharedSignals 后，按以下顺序阅读：
> 1. 本文件 — 理解 SharedSignals 的规则和边界
> 2. **[STATUS.md](STATUS.md)** — 理解当前状态、已知问题、下一步任务
> 3. 跨系统协作前，读 [根目录 AGENTS.md](../AGENTS.md) 和 [根 STATUS.md](../STATUS.md) 了解三系统架构和全局状态

## 层级披露

- 上层 `~/Projects/Finance/AGENTS.md` 只定义 Finance 工作区三项目边界和跨项目协作规则。
- 本文件只定义 SharedSignals 的数据采集、存储、直接入库、patrol/heal 和输出契约。
- 进入具体采集器、storage、bridge、reference 或 docs 后，继续读取最近层级文档；采集命令、schema 和运行边界以本仓库文档为准。

## 目标
统一数据采集与存储，供研究线和交易线共享读取。


## 三系统协作边界

- SharedSignals 是供数层，只负责采集、去重、缓存和健康巡查；不做投资分析、交易判断、执行路由或回执处理。
- `market_factors` 只表示事实型 read-model 投影：provider 原始财务/资金/宏观/参考字段、必要字段展开和来源留痕。SharedSignals 不计算 alpha、买卖方向、策略评分、仓位权重或交易触发条件；这些交易因子提取、标准化、组合、风控和决策属于 TradingAgent。
- MarketGraph 和 TradingAgent 生产运行只能消费 SharedSignals 暴露的 HTTP API；SQLite/DuckDB read model 是 SharedSignals 内部存储和本仓只读诊断/批处理入口，不是跨系统生产兜底。
- 对 TradingAgent 而言，SharedSignals/ShareChannel API 是唯一生产市场数据入口。生产 reader/API 不得回退旧 CSV、NDJSON、旧目录或其它系统内部文件；缺表、缺数据或缺映射必须返回 degraded/fail-closed，不能把旧文件当兜底。
- 未来对外提供服务接口时，默认只暴露数据读取、健康状态和来源留痕；任何交易信号、下单、模拟执行或邮件通知都属于 TradingAgent/Hermes 边界。SharedSignals 支撑分钟级/5 分钟级供数，不承诺毫秒级 HFT、订单簿撮合、下单或资金执行。
## 边界
- 做什么: 采集行情/事件/基本面/资金/宏观, 去重入库
- 不做什么: 不分析, 不分类, 不做交易决策
- 存储: SQLite read model + DuckDB mirror；仓库和生产 reader/API 不保留 CSV/NDJSON/Parquet 文件桥、冷归档读路由或旧样本数据。

## 现状
- 行情: Tushare/Binance/PM(markets/prices) → SQLite read model + DuckDB mirror；具体接口数以 `collectors/tushare/config.yaml` 和 `STATUS.md` 当前记录为准。采集结果必须以 rows 直接写入 read model，不得恢复 CSV/NDJSON/Parquet staging 或样本文件路径。
- 事件: RSS/RSSHub/Tavily/DeepSeek 当前不作为现役生产 collector；恢复前必须走新的 SharedSignals collector 直接写 SQLite read model，不得恢复旧文件 staging、旧 bridge 或跨系统运行层入口
- 基本面: Tushare 财务/分红/融资融券等由分层定时任务采集落库，写入 `market_factors`；reader/API 只读缓存，不现场调用 provider
- 运行审计: collector 写入 `market_ingest_runs`，cron/watchdog/health_sla 读取数据库和日志

## 依赖
- 采集输入: 外部 API (Tushare/Binance/PM/RSS/Tavily/DeepSeek) 只允许在 SharedSignals collector 层调用；未启用的数据源不得被 MarketGraph/TradingAgent 绕过 SharedSignals 直接调用
- 输出: HTTP API → MarketGraph 和 TradingAgent 按契约读取。SQLite/DuckDB read model 保留给 SharedSignals 内部和明确授权的只读诊断；CSV/NDJSON 不作为跨系统生产消费入口。

## 入库与输出硬规则（2026-07-08）

- 采集成功的定义是 provider rows 经过校验后直接写入 SQLite read model；非空采集结果写入 0 行必须标记 failed，并进入 watchdog/系统告警。
- P0-P7 Tushare、CNFutures、Crypto、PM 等现役 collector 不得提供 CSV-only 成功路径，也不得通过 `--no-sqlite-bridge` 一类开关绕过 read model 入库。
- `collectors/tushare/config.yaml` 中启用的接口必须同时具备 read model 表映射、HTTP API 白名单、采集频率声明和限流保护；新增接口必须补测试，证明“能采、能入库、能通过 API 查到”。
- 生产定时任务必须覆盖 5 分钟交易供数、日频研究供数、健康巡查、能力扫描和 watchdog；修改 cron 前后必须运行能力/频率闭环测试。
- SharedSignals 不读取 TradingAgent/MarketGraph 的候选、持仓、输出或旧缓存来决定采集范围；短周期优先股票只能来自本仓库 read model 中的资产池或显式环境变量。

## 巡查自愈系统 (patrol + heal)

### patrol.py — 10min巡检
检查6个维度:
- source_health: 每个source最近采集时间, 超时→stale (只标记已采集过的源)
- data_freshness: marketdata.sqlite最新trade_date, 超过1天→stale
- data_artifact_guard: 仓库和 runtime 不应出现被当成 read path 的 CSV/NDJSON/Parquet 文件；出现时告警并清理来源
- sqlite_health: WAL文件大小(>100MB→checkpoint), 锁等待→告警, 完整性检查
- disk_usage: >80%告警, >90%停止采集
- schema_contract: provider rows 字段与 read-model schema / expected_fields 契约不匹配→告警

输出: JSON {checks: [{name, status, value, threshold, alert}], overall_score}

### heal.py — 自愈动作
- source stale → 记录 stale collector 告警，要求重跑对应 direct-DB collector；不做旧 RSS/source failover
- 数据缺失 → 触发补采(重跑marketdata_db --ingest)
- 文件桥残留 → 告警并清理；要求所属 collector 改为 provider rows 直接入库，不运行旧 runtime bridge
- SQLite锁 → 等待5s重试, 清理WAL(PRAGMA wal_checkpoint)
- 磁盘满 → 清理日志、缓存和运行产物；不得引入 Parquet 冷归档 read path
- 字段漂变 → 更新expected_fields.json + 告警
- 自愈失败 → 紧急告警(emergency_alerts.log) → 人工介入

### memory/ — 闭环记录
- patrol_history.jsonl: 每次巡查结果
- heal_actions.jsonl: 每次自愈动作
- patterns.jsonl: 发现的模式(周复盘迭代规则)
- failover_history.jsonl: 源切换历史

## 文件结构
- collectors/ — 各数据源采集器
- storage/ — schema文档 (当前SQLite, 计划DuckDB)
- bridge/ — read-model 兼容辅助模块；旧跨仓 CSV/staging bridge 已退役
- reference/ — 参考数据、expected_fields.json 与只读缓存辅助工具；不得放回旧 Ashare/RSSCollector 软链入口
- memory/ — 采集层记忆 + 巡查/自愈历史
- staging/ — 退役目录名；不得作为生产采集成功路径或 reader/API 兜底
- patrol.py — 10min巡查 (6维度健康检查)
- heal.py — 自愈引擎 (failover/backfill/merge/checkpoint/cleanup/drift)
- logs/ — 紧急告警 (emergency_alerts.log)

## Projects 工作区同步补充

本仓库位于 `/Users/nicholashan/Projects/Finance/SharedSignals` 时，按 Projects 工作区统一同步规则执行：

- 仓库地址、remote 名称和默认分支以本仓库内 `git remote -v`、`git branch --show-current` 和项目文档为准，不从其它项目继承。
- 开发前检查 `git status -sb`、`git remote -v`、当前分支和是否落后远端；发现采集、存储、桥接或其它 agent 的未提交改动时，先确认来源，不得覆盖。
- 涉及采集源、SQLite read model、schema、API contract、patrol/heal 或对 MarketGraph/TradingAgent 的输出契约时，必须同步更新核心文档，例如 `README.md`、`STATUS.md`、`API_CONTRACT.md`、`LOG.md` 或 `docs/` 下对应说明。
- 提交时只暂存本次审计过的文件；数据库、缓存、日志、staging、密钥和本机运行产物默认不提交，除非项目文档明确要求并已审计。
- 不得提交或恢复 CSV/NDJSON/SQLite/DB/Parquet/冷归档样本、`storage/cold`、`storage/archive_manager.py`、`storage/query_router.py`、Polymarket parquet loader 配置或 `ingest_csv_to_sqlite` 一类文件桥入口；测试门禁必须阻止这些内容回归。
- 从旧 `Desktop/Works/02.AI_Projects` 或其它 iCloud 管理目录迁移时，优先使用当前 Projects 下真实 clone；旧目录只作为对照和补漏来源。

## 2026-07-01 定时采集与 Tushare tier 口径修正

- SharedSignals 到 TradingAgent 的关系是“定时采集沉淀 + reader/read model 按需读取”，不是 TradingAgent 每次判断时重新现场采集。
- Tushare `sync_daily.py` 当前按配置支持：`P0_trading_5min`、`P1_eod_daily`、`P2_financial_daily`、`P3_reference_daily`、`P4_macro_daily`、`P5_hk_us_daily`、`P6_other_daily`、`P7_low_frequency`。
- A股盘中 P0 采集保持交易时段每 5 分钟；P1/P2/P3/P4 分别按盘后、晚间、盘前、早间日频维护。
- HK/US Tushare daily 采集使用 `P5_hk_us_daily`，按港股收盘后和美股收盘后日频维护；期货/基金/ETF/支持数据使用 `P6_other_daily` 日频维护；A股/指数周月线使用 `P7_low_frequency` 每周独立维护。
- `collectors/tushare/config.yaml` 已删除无效 `P7_crypto_pm_5min` 顶层配置；Crypto/PM 不属于 Tushare tier，必须走各自 collector/reader，不得重新启用旧 `P7_crypto_pm` cron。

## 2026-07-04 SharedSignals-only 数据边界

- SharedSignals 是三系统唯一外部数据采集入口；MarketGraph 和 TradingAgent 不得重新启用独立 Tushare/RSS/PM/Crypto provider 采集任务。
- `reader.py` 和 HTTP API 必须读取 `/opt/investment/SharedSignals/runtime/read_model/marketdata.sqlite` 与本仓库 DuckDB mirror；无缓存、无映射或无数据时返回 degraded，不现场调用 Tushare，也不回退 CSV/NDJSON/旧目录或其它系统目录。
- 生产 API 默认绑定 `127.0.0.1:8082`；本机消费者可通过 `SHAREDSIGNALS_LOCALHOST_BYPASS=1` 访问，外部账号接入必须配置 token/JWT 和账号并发限制。
- `/health` 是轻量存活与汇总健康探针，默认读取 cron 与 watchdog/SLA 缓存，不得在请求内跑 reader functions、大库 freshness 扫描、compile 或架构审计；如需深度检查，只能显式设置 `SHAREDSIGNALS_HEALTH_DEEP_CHECKS=1` 或走定时 `health_sla` / patrol / watchdog 产物。
- Tushare 无积分消耗但有并发/频率约束；P0 交易时段每 5 分钟采集，P1-P7 按交易/研究/低频参考需要分层调度，所有结果先落库再供 MarketGraph/TradingAgent/外部 agent 通过 API 读取。
- DuckDB/SQLite 同步和 watchdog 必须以 `marketgraph` 运行用户执行；若手工维护导致数据或日志文件变成 root 属主，应恢复为 `marketgraph:marketgraph` 后再验证 cron。
- RSS/RSSHub 边界：RSS 采集代码和旧故障切换入口已退出现役层；恢复事件采集前必须重新接入 SharedSignals collector、直接入库、健康检查和回滚方案，不得恢复旧 RSS collector、旧文件 staging 或旧跨系统运行层入口。
