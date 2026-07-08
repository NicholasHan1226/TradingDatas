# SharedSignals 状态

> **给所有 agent：** 读完 [AGENTS.md](AGENTS.md) 理解规则后，读本文件理解"现在在哪、要去哪、能做什么"。
>
> **⚠️ 变更后必须更新本文件。**
>
> 最后更新：2026-07-08 (A股 P0 5分钟快车道收窄、事件 API market/symbol 过滤补齐、API health 轻量化、A股 moneyflow 盘后日频化、评分历史窗口修复、DuckDB 降载、CNFutures 空返回备源、全量同步冲突收口、CNFutures 午休新鲜度口径、Tushare 入库/API 覆盖完整性保护、health_sla 大表轻量化、新闻/公告 DB-first 事件输出)

---

## 一、当前状态

- **行情采集**：稳定运行 — Tushare（P0-P6 分层 83 个唯一接口，全部要求有 CSV→SQLite 映射且全部开放 `/tushare` 只读 API）+ Binance（9 symbols，ticker 5min 写 `market_bars_intraday`，每小时 `klines 1d` 写 `market_bars_daily`）+ Polymarket（markets+prices，经新加坡 SSH relay 优先、本地 Mihomo/Clash 兜底，默认不直连兜底）→ SQLite + CSV/NDJSON 缓存；2026-07-08 起 P0 只保留 A股盘中分钟线 `stk_mins/rt_min`，默认每轮 30 只且优先覆盖持仓、TradingAgent 当前 A股候选、模拟执行未交易/排除候选和 MarketGraph 尾盘候选，且只有 09:30-11:30、13:00-15:00 推进游标，跨交易日自动重置，避免盘前/午休空跑和日频/因子接口拖住 5 分钟交易读数；CNFutures 5 分钟新鲜度检查把 11:31-11:59 识别为 lunch、12:00-12:59 识别为 lunch_preopen，午休期间不因 11:30 bar 自然老化误报 stale，13:00 起恢复交易时段 stale 检查；服务 A股评分/候选池的 `daily`、`stk_factor`、`stk_factor_pro` 移到 P1 盘后日频并保留 90 天 lookback，保证 TradingAgent 技术面/估值类评分有足够历史；A股 `moneyflow` 已从 P0 盘中逐股轮询移到 P1 盘后日频全市场采集，避免日频接口在 5 分钟层返回 0 行和浪费限流；P6 杂项/日频层改为盘后夜间运行，`news`/`major_news`/`cctv_news`/`anns_d`/`report_rc` 统一落 `market_events`，`cb_daily` 改为按 `trade_date` 全市场快照，避免开盘期间长跑逐股任务抢占 P0/模拟交易资源；P0 股票清单优先从 read model `market_assets` 读取有名称、非退市、非基金的沪深 A股，`reference/stock_master.csv` 只作兜底，避免样本清单限制全市场轮询和退市代码浪费 5 分钟配额；分钟线不扩大为历史分钟回补，避免采集压力失控；CSV→SQLite bridge 已把 `stk_factor` 同时投到 `market_bars_daily` 与 `market_factors`，`daily_basic`/`stk_factor_pro`/`moneyflow`/`top_list`/`limit_step`/`stk_auction`/`stk_limit` 投到 `market_factors`，`concept`/`concept_detail`/`hs_const` 投到 `market_assets`，避免数据只停留在 CSV、不能被 TradingAgent/MarketGraph 通过 API/read model 消费。
- **事件采集**：RSS/RSSHub/Tavily/DeepSeek 当前不作为现役生产 collector；相关旧资产进入退役/迁移审计，恢复前必须走 SharedSignals collector + staging/bridge 契约
- **4 条现役数据管线**：Tushare、Binance、Polymarket、DuckDB 同步；Crypto/PM 不再挂在 Tushare tier 下，按各自 collector/reader 维护；Binance collector 对 transient `requests`/SSL 网络异常使用短重试，减少单次 EOF 造成整轮 5 分钟采集跳过
- **DB-first API 架构**：采集器先落 SQLite/DuckDB read model，再由 SharedSignals API 对 TradingAgent/MarketGraph 提供只读消费；CSV/SQLite 直接读取只保留为兼容或降级路径
- **reader/API 缓存失效**：读取缓存同时监听 `marketdata.sqlite`、`marketdata.sqlite-wal`、`marketdata.sqlite-shm` 和 CSV/分钟线文件变更；SQLite WAL 模式下 5 分钟新写入不会因主 DB 文件未 checkpoint 而继续返回旧缓存
- **巡查自愈**：patrol.py（6 维度 10 分钟）+ heal.py（failover/backfill/checkpoint）；patrol 阈值支持 `PATROL_*` 环境变量调优，data freshness 覆盖 daily/intraday/events/factors/PM prices；watchdog 闭环监控 API/DB/cron log/disk/memory，并纳入 `health_sla` 与 `proxy_relay_health` 外部报告扣分，低分触发 heal、critical 触发 auto_restart，重启失败才升级邮件，连续失败写 halt
- **健康口径**：2026-07-07 起 `/health` 会聚合 `tools/health_sla.py` per-table SLA 结果；API 请求只读取 `logs/watchdog_inputs/health_sla.json` 的定时产物，不在请求内重新扫大库。交易关键表 critical 保留为 `sla_status=critical` 并让 `/health` degraded，但不映射为 API error，避免数据新鲜度问题触发 API 进程误重启。研究事件“过期”仍只记 notice，不影响交易供数健康；但 tracked table 缺表/空表会至少降级为 degraded，避免 `health_sla` 出现 missing/empty 时整体仍显示 ok。`patrol.py` 的 PM freshness 已改用 `market_pm_prices.collected_at`，与现役 schema 对齐；`health_sla.py` critical 邮件发送器输出不再污染 watchdog JSON；2026-07-08 起 Crypto 不再按 `market_bars_daily.trade_date` 判定 24/7 交易新鲜度，改用 `market_bars_intraday.collected_at` 30 分钟 SLA，避免日线旧样本把正常 5 分钟采集误报 critical；同日起 `health_sla.py` 对 `market_factors`、`market_events`、`market_pm_prices`、`market_bars_intraday` 采用最近写入样本判断 freshness，并设置只读连接 busy timeout，避免 10 分钟健康任务在生产大表上全表扫描并拖到 wrapper timeout。
- **US/Global 日线 SLA**：2026-07-07 起 `market_bars_daily` 中 `US` 与 `Global` 不再只按自然小时数判断 stale，而是按“应产生并采集到的最近有效交易日”计算。US 识别常见 NYSE 假期与 P5 06:10 CST/18:10 ET 后采集窗口；Global 按 P4 08:45 CST 采集窗口处理。两者落后 1 个有效交易日以内不触发 critical，落后 2 个有效交易日仍 critical，避免美国假期/长周末后把正常休市误判为供数故障。
- **`/health` data_freshness 对齐**：2026-07-07 起旧 `data_freshness` 检查不再用另一套自然日规则判定 US/Global；Ashare/US/Global 跟随 `health_sla` 的日线判定，Crypto 改看 `market_bars_intraday.collected_at` 30 分钟新鲜度，避免 Crypto daily 旧样本和 US/Global 假期样本把 `/health` 误打 degraded。
- **采集器架构**：BaseCollector + 6 mixins + 4 采集器实现，完整生命周期（health→plan→collect→validate→dedup→save→audit→coverage）
- **旧采集器清理**：`collectors/tushare_old/`、旧 RSS/RSSHub collector、旧 Alpaca US collector 和 legacy `tools/api_server.py` 已确认无现役引用并删除；现役采集入口保留 Tushare、Binance、Polymarket 与 DuckDB 同步，不得恢复旧 Ashare/RSS/Alpaca 接口副本。
- **旧 MarketGraph 软链清理**：`bridge/marketgraph_marketdata_db.py` 已改为 SharedSignals 本仓库兼容模块；`data/association/` 和 `data/intake/` 已从断链软链改为本地目录，避免部署和 reader 默认路径依赖 MarketGraph 内部目录。
- **DuckDB 迁移**：SQLite (116MB) → sqlite_scan → DuckDB (54MB, 列存压缩)，DuckDB 只作为分析镜像，不是 5 分钟交易 read path；2026-07-07 起定时同步降为每小时一次，并用低 IO/CPU 优先级与 10 分钟超时运行，避免全量 sqlite_scan 与交易采集/模拟任务抢占主库。同步层会把 SQLite 历史空字符串数值列安全转换为 NULL，避免单列脏值导致整表镜像失败；只读查询连接不再尝试写 schema，避免 DuckDB read-only 打开失败后误回落 SQLite 导致类型口径退化
- **测试解释器口径**：DuckDB 相关测试必须使用项目/生产 venv（本地 `.venv/bin/python`，生产默认 `/opt/marketgraph/venv/bin/python3`）。系统 Python 可能缺 `duckdb`，不能据此判断 SharedSignals DuckDB 链路失败。
- **cron 解耦入口**：`cron/collectors.sh`、`cron/crypto_collect.sh`、`cron/pm_collect.sh`、`cron/refresh_industry_map.sh`、`cron/duckdb_sync.sh`、`cron/patrol.sh`、`cron/proxy_relay_health.sh`、`cron/watchdog.sh`、`cron/capability_scan.sh`、`cron/cn_futures_daily.sh` 已新增，分别负责 Tushare tier、Crypto 5 分钟 ticker、Crypto 每小时 1d klines、Polymarket markets/prices、A 股基础行业映射刷新、DuckDB 同步、patrol/heal、新加坡 relay 健康、5 分钟 watchdog、API 能力清单刷新和期货日线单独采集，均带 flock 与独立日志
- **港股采集**：hk_income/hk_balancesheet/hk_cashflow 通过 stock_list: hk 路由接入
- **全球宏观**：us_tycr/us_tbr/us_tltr 美国国债收益率曲线数据
- **存储**：`/opt/investment/MarketGraphRuntime/read_model/marketdata.sqlite` + `/opt/investment/SharedSignals/data/marketdata.duckdb`，11 表；2026-07-04 生产同步验证写入 200,202 行，staging 6 streams 活跃
- **API 契约**：`/market_data` 已透传并支持 `freq`；`freq=daily` 读 `market_bars_daily`，`freq=1m/5m/15m/30m/60m` 读 `market_bars_intraday`，未传 start/end 时只取该标的最新 intraday 交易日；美股日线读取兼容 `AAPL` 与 `AAPL.US` 两种 symbol 写法并在 read model 中互查；A股国债逆回购 `repo_daily` 保留 `market_factors` 因子写入，并额外投影到 `market_bars_daily`，因此 `204001.SH` 可按日线收益率读取；`/capital_flow` 同时支持 `date` 和 `ts_code/start/end` 调用，返回 P1 盘后采集并桥接到 `market_factors` 的 `moneyflow:*` 展开行；`/events` 只读取 SQLite `market_events`，不再回退旧 `event_candidates.csv`，并支持 `market`、`symbol/ts_code/subject_code`、`subject_type`、`event_type` 和 `limit` 过滤，A股代码兼容 `600276.SH` / `SH600276` / `600276` 形态；`/tushare` 白名单与 `collectors/tushare/config.yaml` + `storage/csv_bridge.py` 映射保持一致，避免“已采集入库但 API 不可查”；HTTP API 缺表/缺文件/无匹配时固定返回 `data: []` 并通过 `metadata.degraded` 与 `degraded_reasons` 暴露原因，不再暴露 `data: [{}]` 空壳；`/pm_markets` 已优先返回带最新价的 Polymarket 市场并透出 `price/latest_price/latest_price_time`，`/pm_prices` 直接读取 `market_pm_prices` 价格快照供 PM edge、估值和研究回放使用；`/health` 使用读模型动态样例，避免周末/空样例误报；`/sentiment` 与 `/realtime_5min` 支持 `limit` 输出限流，`/realtime_5min` 另支持 `market` 参数并规范化 `ashare/Ashare/a_share` 为同一 A股读模型入口；`/capabilities` 有生成 registry + auth scope 兜底，缺失文件时不再返回 500，能力 smoke 也改为 DB-first reader 样例；真实 `config/api_tokens.json` 已退出 Git 跟踪，仓库仅保留模板
- **API 安全**：JWT 默认禁用（需显式配置 `SHAREDSIGNALS_JWT_PUBLIC_KEY`+`SHAREDSIGNALS_JWT_ISSUER`）；Bearer token 通过 `token_hash`/`sha256` 64 位摘要认证（设置 `SHAREDSIGNALS_TOKEN_SALT` 时由 `auth._hash_token()` 生成 PBKDF2-HMAC-SHA256 摘要）；scope-based 端点访问控制；`LOCALHOST_BYPASS` 默认关闭
- **开发/生产边界**：2026-07-05 开盘前复核已将 `config/dev.yaml` 的 `server` 默认值改为 `127.0.0.1`；生产默认主服务器只保留在 `config/prod.yaml`，避免本地 dev 运行误连 `8.138.181.177`。
- **基础设施文档与 SLA**：2026-07-05 开盘前复核已更新 `docs/INFRASTRUCTURE.md`，当前口径为 SQLite + DuckDB mirror、Redis 未启用；`tools/health_sla.py` 已支持 `MARKETDATA_SQLITE` / `SHAREDSIGNALS_MARKETDATA_DB` / `MARKETGRAPH_RUNTIME_ROOT`，不再只能读硬编码生产库；SLA 已按 trading/research 分层，交易价格/日线过期才触发 degraded/critical，研究事件过期只记 `notice`；`market_bars_daily` 若存在 `market` 列会按市场分别检查最新日期，避免 A股最新掩盖 US stale；周末/周一开盘前会放宽非 24/7 日频表阈值，PM/Crypto 价格不放宽，避免周末或研究层暂停误报成交易供数故障。
- **API 线程化**：`ThreadingHTTPServer` + 30s request timeout + max 20 threads + 256 accept backlog + 503 at capacity；客户端高压断连降级为 debug 日志，避免 BrokenPipe 噪音污染 systemd 日志
- **auth 内存治理**：`_DEDUP_CACHE` entries + bytes 双上限；`_REQUEST_LOG` tenant/event 上限 + TTL
- **CSV→SQLite 桥**：`storage/csv_bridge.py` 已投产，executemany + 文件级事务 + 进程级 SQLite 写锁 + `--exit-on-failure`；Tushare P0-P6 已配置接口必须全部有 read model 映射，非空 CSV 桥接写入 0 行会标记 `failed` 并计入 tier `bridge_failure_count`，避免“采集成功但数据库/API 无数据”被误判为正常；低频宏观、Tushare 新闻事件、全球指数、ETF/期货资产已补齐 read model 映射；A股 `market_assets` 合并时不再用后续 `stock_company` 空字段覆盖 `stock_basic` 的名称、行业、上市日期等基础字段，`industry` 会规范化写入 `sector`，数值列空字符串会规范化为 NULL
- **生产部署**：主服务器 `8.138.181.177` 上 SharedSignals API 监听 `8082`；本机消费者通过 localhost bypass，外部账号必须走 token/JWT；旧 `tools/api_server.py` 已删除，当前唯一数据 API 入口为仓库根目录 `api_server.py`
- **服务器与网络路径**：杭州 `8.138.181.177`（境内采集+存储），新加坡 `47.82.153.58`（境外 relay）。PM/Crypto 当前优先走杭州本机 `127.0.0.1:18889` → SSH tunnel → 新加坡本机 tinyproxy `127.0.0.1:18888`，失败后回落杭州本地 Mihomo/Clash `127.0.0.1:7890`；不暴露公网代理端口，不直连兜底。
- **SLA 监控**：watchdog + auto_restart + halt 文件形成 5 分钟闭环；SLA monitor 消费 API/DB/cron log/disk/memory、`health_sla` per-table freshness 和 TradingAgent 跨系统健康输入；`health_sla` 输出 `summary.critical/warning/notice`，critical/degraded 会影响 watchdog 健康分，并每 10 分钟写入 `logs/watchdog_inputs/health_sla.json`。
- **生产 crontab 文档**：`crontab.txt` 与 `cron/crontab.txt` 已按 2026-07-04 主服务器实际边界重写；SharedSignals owns Tushare P0-P6、Crypto 5 分钟 ticker、Crypto 每小时 1d klines、Polymarket 5 分钟、DuckDB sync、patrol、watchdog。TradingAgent/MarketGraph 不应重新启用旧直接采集 cron。

## 二、已知问题

- libor/hibor 当前可为空返回；libor 属历史停更类接口，hibor 取决于当日源数据。`shibor_lpr` 已恢复：2026-07-04 生产 P4 回看 180 天采集 3 行，写入 `market_factors` 6 条。
- sync_daily.py CSV→SQLite bridge 已完成并接入 `storage/csv_bridge.py`；后续只保留生产 crontab 日志与 DuckDB 同步链路观察
- `market_bars_daily` provider 已从主键移除；服务器迁移已执行，保留 provider 作为普通来源字段
- [x] R15 故障注入新增：主 `marketdata.sqlite` 损坏/丢失后，`tools/sqlite_recovery.py` + `patrol.py`/`heal.py` 已实现只读检测、备份切换或 DuckDB mirror 重建，默认 dry-run/fail-safe；详见 `docs/sqlite_recovery_runbook.md`。普通 WAL crash recovery 仍覆盖主 DB 完整场景。
- R15 故障注入新增：`env_bootstrap` 默认一次性加载，运行中 `.env` 变更不会自动热加载；当前恢复方式是重启进程或显式 `override=True`。
- Crypto 生产 5 分钟行情已切到 `CryptoCollector → NDJSON staging → storage/ndjson_bridge.py → SQLite`；`/crypto` reader 改为 SQLite-first，不再读取旧 `/opt/investment/Crypto/data/market/klines.csv`。
- P0 A 股 5 分钟采集已加轮转批次保护，默认每轮 30 只股票，并只运行 `stk_mins`/`rt_min` 分钟接口；P0 会优先读取服务器持仓、TradingAgent `ashare_preopen_dry_run_latest.json` 候选、`ashare_no_trade_explanations.jsonl` / `execution_exclusions_*.jsonl` 中真实模拟执行缺价候选和 MarketGraph 尾盘候选，再用全市场轮转补足；A股连续交易窗口外直接跳过且不推进游标，游标按 `trade_date` 自动重置，避免盘前、午休或跨日空跑污染开盘覆盖；当前实时分钟接口使用实测可用的 Tushare `rt_min`，旧 `rt_k` 仅保留历史 CSV/read fallback 兼容。
- A股评分相关日频接口已从默认 7 天窗口提高到 90 天，并移到 P1 盘后日频：`daily`/`stk_factor`/`stk_factor_pro` 负责给 TradingAgent 候选池提供足够日线与估值历史，并已用测试锁定三者均按单股票 `ts_code/start_date/end_date` 参数采集；P0 A股清单已改为优先读取 `market_assets` 中有名称、非退市、非基金的沪深代码，只在 read model 不可用时回退 `reference/stock_master.csv` 样本文件；该窗口不应用到 `stk_mins`/`rt_min` 分钟接口。生产部署后需观察每只活跃股票 `market_bars_daily` 是否从 7 条逐步提高到 20 条以上，直到覆盖 90 天窗口；同时检查 `market_factors` 中 `stk_factor:*`、`stk_factor_pro:*`、`daily_basic:*` 行是否增长，确保数据不只停留在 CSV。
- RSS/RSSHub 已退出现役层：旧 RSSCollector cron 条目已从模板和生产 crontab 删除；主服务器残留 RSSHub node 已停止，`/opt/investment/RSSHub`、`/opt/investment/RSSCollector`、`/opt/investment/Users` 和顶层 `.env.bak` 已归档到 `/opt/investment/_archive/retired_residuals_20260704T172705Z`。保留 `rss_collector.db` 只作历史/迁移审计，恢复事件采集前必须重新接入 SharedSignals collector + staging/bridge。
- `bridge/__init__.py` 仍保留 MarketGraph 工具路径兼容注入，用于历史 bridge/import 兼容；当前不是数据采集入口。后续拆到独立服务器前，应改为显式依赖或移除跨仓 `sys.path` 注入。

## 三、API 接口状态（HTTP 18/18；health core 14 OK / 2 delegated skipped）

生产 HTTP API 暴露 18 个只读端点；`/health` 当前只把 SharedSignals 自身供数能力计入核心健康，`events` 已由 SQLite `market_events` 原生承担，MarketGraph 研究图谱类端点 `associations`、`impacts` 仍标记为 delegated/skipped，不再通过软链依赖 MarketGraph 内部目录。HTTP surface、`/health` reader sample 和 capability smoke 三个数字口径不同，不应混用。

| 接口 | 端点 | 状态 |
|------|------|------|
| is_trading_day | /is_trading_day | OK |
| get_market_data | /market_data | OK |
| get_fundamentals | /fundamentals | OK |
| get_reference | /reference | OK |
| get_macro_factors | /macro | OK |
| get_capital_flow | /capital_flow | OK |
| get_events | /events | OK |
| get_sentiment | /sentiment | OK |
| get_crypto_klines | /crypto | OK |
| get_pm_markets | /pm_markets | OK |
| get_pm_prices | /pm_prices | OK |
| get_associations | /associations | delegated |
| get_impacts | /impacts | delegated |
| get_industry | /industry | OK |
| get_realtime_5min | /realtime_5min | OK |
| get_tushare | /tushare | OK |
| clear_caches | /cache/invalidate | OK (GET/POST) |
| cache_status | /cache/status | OK |

- 健康检查覆盖：`/health` 当前生产验证为 SharedSignals core reader functions `14/14`，另有 2 个 MarketGraph delegated endpoint 标记 skipped；HTTP surface 仍为 18 个端点；capability smoke 的延期端点会计入 `skipped`。
- API 客户端：TradingAgent [SharedSignalsAPIClient](../tradingagent/shared/data/shared_signals_api.py) 已实现 16 接口 HTTP 封装
- 契约修复：`/market_data` `freq` 参数已进入 reader；`/capital_flow` 已兼容 TradingAgent 客户端的 `ts_code/start/end` 参数。

## 四、下一步

1. [x] DuckDB 初始同步完成（145K 行），定时同步已调度为分析镜像小时级任务（非 5 分钟交易链路）
2. [x] API 安全加固：Bearer token 认证 + scope-based 端点访问控制 + key-based 账户隔离
3. [x] fx_daily/hibor 参数调优（2026-07-02 修复：fx_daily 加 exchange=FXCM，hibor 改用 date 参数）
4. [x] hk_daily 全局查询修复（2026-07-02 修复：改为 per_stock + stock_list=hk）
5. [x] **P0：CSV→SQLite 接入桥** — `storage/csv_bridge.py` 已建成，sync_daily.py CSV 输出已接入 SQLite→DuckDB 管线
6. [x] **P0：schema 漂移检测** — schema.py 与 duckdb_schema.py 11 表自动一致性校验
7. [x] **P0：provider 从 market_bars_daily 主键移除** — 迁移脚本已执行到服务器，provider 保留为普通来源字段
8. [x] **P1：API 服务器线程化与资源上限** — ThreadingHTTPServer + request timeout + semaphore thread limiter
9. [x] **P1：auth.py 内存治理** — `_DEDUP_CACHE` 已加 entries + bytes 双上限和单条响应上限；`_REQUEST_LOG` 已有 tenant/event 上限 + TTL
10. [x] **P1：import-time env 加载统一** — 集中到进程启动入口，消除非确定性
11. [x] **P2：SharedSignals API/read model 作为默认消费入口** — TradingAgent 健康回执已通过 SharedSignals API；MarketGraph 旧 provider/RSS/Tushare 采集 cron 与 provider passthrough 已禁用，SQLite/DuckDB 只读回退保留
12. [x] **P3：自动恢复 runbook** — 主 DB 损坏后的备份切换/ DuckDB 重建流程已实现，默认 dry-run/fail-safe，详见 `docs/sqlite_recovery_runbook.md`；env 运行中热加载仍待后续迭代。
13. [x] **P3：watchdog 生产接入验证** — 服务器 crontab 已接入，已完成 API auto_restart 恢复演练、TradingAgent 回执刷新和 watchdog 100 分验证；邮件通道实发仍按系统邮件专项单独验证
14. [x] **CNFutures：期货日线每日入口与历史回补工具** — `tools/collect_cn_futures_daily.py`、`cron/cn_futures_daily.sh` 和 `collectors/tushare/backfill_fut_daily.py` 已提供单日采集、cron 调度和区间回补入口；只采集/桥接 Futures 日线，不做交易判断。
15. [x] **Polymarket：markets/prices 生产采集闭环** — `collectors/polymarket_collect.py` 写入 `market_pm_markets` 与 `market_pm_prices`，`cron/pm_collect.sh` 以 5 分钟频率运行，TradingAgent/MarketGraph 继续只读 SharedSignals API/read model。
16. [x] **CNFutures：期货 5 分钟行情入口** — `tools/collect_cn_futures_5min.py`、`cron/cn_futures_5min.sh` 和 CSV→SQLite bridge 已支持 Tushare `rt_fut_min` 写入 `market_bars_intraday`；默认合约池覆盖 `rb/cu/i/m/if/ih/ic/im` 并按产品轮询选合约，生产 cron 独立于 `P6_other_daily` 支持日盘、夜盘和跨午夜 5 分钟采集；`market_bars_intraday` 已扩展可空一级 bid/ask、盘口量、last_trade_date/expiry_date 字段，`/realtime_5min?market=Futures` 可通过 API 读取并透传这些字段，供 TradingAgent 在字段存在时增强模拟成交。
17. [x] **CNFutures：期货 5 分钟数据新鲜度验收** — `tools/check_cn_futures_5min_freshness.py` 已支持只读检查 Futures 5 分钟 bar 的 `fresh/stale/no_data/error` 状态，默认 10 分钟阈值，供 TradingAgent 5 分钟模拟交易前做数据健康依据。
18. [x] **RSS/RSSHub 退役收口** — 旧 RSSCollector cron 条目已从模板和生产 crontab 删除；RSSHub 残留进程已停止，旧顶层目录已移入 `_archive/retired_residuals_20260704T172705Z`；`rss_collector.db` 仅保留历史/迁移审计；`data/source_registry.csv` 中 616 条 RSS/RSSHub 源状态已从 `active` 改为 `deferred`，避免被 patrol/source_failover 误判为现役生产源。
19. [x] **API 能力清单生产化** — `/capabilities` 缺 registry 时返回 auth scope 兜底；`cron/capability_scan.sh` 每小时刷新 registry，若存在 degraded endpoint 但 registry 已写出则记录 WARN 不阻断 cron。
20. [x] **P0 5 分钟采集节奏保护** — `sync_daily.py` 支持 P0 rotating stock batch，`cron/collectors.sh` 默认每轮 100 只，保障 5 分钟采集不因全量 per-stock 调用重叠；A股 P0 已新增 priority hot pool，先读取持仓/本地模拟仓位/尾盘候选与 `SHAREDSIGNALS_P0_PRIORITY_STOCKS`，再用剩余配额轮询全市场，避免重点标的在 5 分钟交易频率下等待全市场一轮才刷新。
21. [x] **API 开盘高压稳定性** — 2026-07-05 生产开盘模拟读压测覆盖 `/health`、`/market_data`、`/realtime_5min`、`/capital_flow`、`/crypto`、`/pm_markets` 等端点；修复后 160/160 正常峰值请求与 640/640 尖峰请求均 200，0 超时、0 交易队列副作用。
22. [x] **Capability smoke 与 read model 对齐** — `tools/capability_scan.py` 的现役能力 smoke 已收口到 `reader.py` / `reference.market_calendar`，不再现场调用 Tushare wrapper；当前暂停的 HK/cross-border 端点显式标记 skipped，避免把架构延期误判成数据故障。
23. [x] **5 分钟 read API 市场参数化** — `reader.get_realtime_5min()` 与 HTTP `/realtime_5min` 支持 `market` 参数，默认 `Ashare` 保持旧调用兼容；`market=Futures` 等非 A股市场不再被硬编码挡住，旧 CSV 目录回退仅保留给 A股历史 5 分钟目录。
24. [x] **reader WAL 缓存失效修复** — `reader.py` 的缓存文件指纹已动态解析当前路径，并纳入 SQLite `-wal`/`-shm` sidecar；测试覆盖 sidecar mtime 更新后触发 `_files_changed()`，降低 5 分钟交易读取旧数据风险。
25. [x] **health_sla 交易/研究分层与定时启用** — `market_bars_daily` 与 `market_pm_prices` 属交易关键 freshness，超阈值影响健康；`market_factors` 为 warning；`market_events` 属研究 lane，过期只记录 notice，不再把研究事件暂停误判为 SharedSignals 交易供数故障；周末/周一开盘前会扩大非 PM/Crypto 表的有效 freshness 窗口；`cron/health_sla.sh` 每 10 分钟运行并写入 watchdog input，critical/degraded 外部报告会纳入 watchdog 分数。
26. [x] **A股 rt_min 与逆回购读模型修复** — P0 实时分钟配置从旧 `rt_k` 切到实测可用的 `rt_min`，CSV bridge 与 reader fallback 同步支持 `rt_min`；`repo_daily` 不再裁剪字段，并在保留 `market_factors` 的同时额外投影到 `market_bars_daily`，供 TradingAgent 以 `204001.SH` 日线收益率读取。

### 2026-07-07 full-sync load and CNFutures empty-row fallback

- [x] `/health` 默认恢复为轻量探针：只聚合 cron 活跃度与 watchdog/SLA 缓存，不再在请求内执行 reader functions 与 data freshness 大库读取；深度检查必须显式设置 `SHAREDSIGNALS_HEALTH_DEEP_CHECKS=1` 或走定时 patrol/health_sla/watchdog，避免健康探针本身拖慢 API。
- [x] 生产侧对 19G SQLite WAL 完成一次维护 checkpoint，WAL 清至 MB 级，磁盘占用从 74% 降至 54%；该动作仅合并/截断 SQLite WAL，不删除业务数据。
- [x] DuckDB 同步从 5 分钟全量镜像降为小时级分析镜像，并在 `duckdb_sync.sh` 中使用 `nice`/`ionice` 与 600 秒超时，避免全表扫描期间拖慢 SharedSignals API、TradingAgent 模拟盘和 SSH 运维入口。
- [x] `crontab.txt` 明确 DuckDB 不属于 5 分钟交易 read path；TradingAgent/MarketGraph 仍应通过 SQLite read model/API 读取交易所需数据。
- [x] CNFutures 5 分钟采集在 Tushare `rt_fut_min` 返回 0 行但未抛错时，会按默认开关 `CN_FUTURES_5MIN_AKSHARE_FALLBACK=1` 与 `CN_FUTURES_5MIN_AKSHARE_FALLBACK_ON_EMPTY=1` 尝试 AKShare/Sina 备源，避免“接口成功但无 bar”导致期货模拟盘科学空跑。
- [x] 边界：AKShare/Sina 备源只用于模拟研究和数据连续性，不改变未来真实期货接入必须走受控券商/CTP 接口的边界。

### 2026-07-05 PM proxy hardening

- [x] `cron/pm_collect.sh` 显式导出 `POLYMARKET_HTTP_PROXY=http://127.0.0.1:7890`、请求超时、网络短重试和 SQLite 写库短重试配置，并把 proxy 通过 `--proxy` 传入 collector；不再只依赖 Python 内部默认值。
- [x] `collectors/polymarket_collect.py` 默认禁用 direct fallback，避免本地 proxy 短故障后又直连并把错误误写成 `Network is unreachable`；如确需直连审计，必须显式设置 `POLYMARKET_DIRECT_FALLBACK_ENABLED=1` 或传 `--allow-direct-fallback`。写入 read model 时先设置 busy timeout，并对 `database is locked` 做有限短重试，减少 5 分钟多任务撞库导致的漏采。
- [x] `storage/csv_bridge.py` 同步增加 SQLite busy 短重试和按需 WAL 设置，覆盖 Tushare CSV bridge 与 PM/其它 writer 争用同一 read model 时的 `database is locked`；`SHAREDSIGNALS_CSV_BRIDGE_DB_RETRIES` 可单独调优。
- [x] `tools/watchdog.py` 的 API health 探针增加 3 次短重试，避免 SharedSignals API 单次慢响应把 watchdog 分数误打低；连续失败仍按 critical 处理。
- [x] `.env.example` 与 `.env.template` 已补齐 Polymarket proxy 配置，明确 PM 走杭州本地 Mihomo/Clash，不走新加坡 RSS mirror。
- [x] PM/Crypto 采集支持 `POLYMARKET_HTTP_PROXIES` / `BINANCE_HTTP_PROXIES` 逗号分隔代理优先级列表；生产已配置为本机 SSH tunnel 到新加坡 relay 优先、本机 Clash/Mihomo 兜底，避免直接暴露公网代理端口。
- [x] 新增 `deploy/install_singapore_proxy_relay.sh` 与 `deploy/configure_overseas_proxy_priority.sh`，用于在拿到新加坡 SSH 后安装受限 tinyproxy relay，并在杭州主服务器验证后切换为“新加坡优先、本机 Clash 备选”；操作说明见 `docs/singapore_proxy_relay.md`。

### 2026-07-05 Singapore-first PM/Crypto proxy relay verified

- [x] 新加坡 `47.82.153.58` 已安装 tinyproxy，并收敛为只监听 `127.0.0.1:18888`，不暴露公网代理端口。
- [x] 杭州主服务器已启用 `sharedsignals-sg-relay-tunnel.service`，本机监听 `127.0.0.1:18889` 并通过 SSH 隧道转发到新加坡本机 tinyproxy；隧道出口 IP 验证为 `47.82.153.58`。
- [x] 生产 `.env` 已设置 `POLYMARKET_HTTP_PROXIES=http://127.0.0.1:18889,http://127.0.0.1:7890` 与 `BINANCE_HTTP_PROXIES=http://127.0.0.1:18889,http://127.0.0.1:7890`。
- [x] 生产 PM 实采通过：100 markets / 200 prices 写入成功；生产 Crypto 实采通过：9 行 intraday 数据写入成功。
- [x] watchdog dry run 100 分；API health、DB freshness、collector status、disk、memory 均为 `ok`。

### 2026-07-05 Singapore relay health watchdog input

- [x] 新增 `tools/proxy_relay_health.py` 与 `cron/proxy_relay_health.sh`，每 5 分钟检查 PM/Crypto 新加坡 relay：本机 tunnel 代理可出网、出口 IP 符合 `47.82.153.58`，并可选检查 `sharedsignals-sg-relay-tunnel.service`。
- [x] 结果写入 `logs/watchdog_inputs/proxy_relay.json`，由现有 watchdog 外部报告机制扣分；relay critical 时不需要新增一套告警系统，继续走 watchdog 邮件/自愈闭环。

### 2026-07-05 health SLA research notice split

- [x] `tools/health_sla.py` 为每个表增加 `lane` 和 `severity`，输出 critical/warning/notice 三类 summary。
- [x] `market_events` 过期只作为 research notice，不再导致整体 `degraded`；`market_pm_prices` 过期仍是交易关键 critical。
- [x] 周末/周一开盘前对非 24/7 日频表扩大有效阈值；PM/Crypto 不放宽，防止周末仍交易市场被误放过。
- [x] `health_sla` 不再静默吞掉表查询异常；表缺失、日期列缺失或查询失败会进入 violations，并按表 severity 影响整体状态。
- [x] 新增 `cron/health_sla.sh`，每 10 分钟运行 per-table SLA，输出 `logs/watchdog_inputs/health_sla.json` 供 watchdog 汇总并参与健康扣分。
- [x] 新增 `tests/test_health_sla.py` 覆盖研究事件过期不降级、PM 价格过期 critical、周末日频表放宽但 PM 不放宽、表错误不返回 ok 四个场景。

### 2026-07-04 CNFutures 期货 5 分钟行情入口

- [x] 新增 `tools/collect_cn_futures_5min.py`：调用 Tushare `rt_fut_min`，默认 `freq=5MIN`；支持从最新 Futures 日线合约池按产品轮询自动选择 `rb/cu/i/m/if/ih/ic/im`，其中 `IF/IH/IC/IM` 供 TradingAgent 股指日内方向风格做模拟验证；也支持 `--symbols` 或 `CN_FUTURES_5MIN_SYMBOLS` 指定合约。
- [x] 新增 `cron/cn_futures_5min.sh`：带 `flock`、超时、日志、生产 venv Python 和可选降权执行；只采集/桥接行情，不写交易信号、不触发模拟或实盘执行。
- [x] CSV→SQLite bridge 已将 `rt_fut_min` 映射到 `market_bars_intraday`，兼容 `code/time` 和 `ts_code/trade_time` 字段，写入 `market=Futures`、`provider=tushare_rt_fut_min`、`interval=5min`。
- [x] `market_bars_intraday` 新增可空 `bid_price/ask_price/bid_size/ask_size/last_trade_date/expiry_date`；`rt_fut_min` CSV bridge 兼容 `bid1/ask1/bid1_volume/ask1_volume` 等字段，并可从 `market_assets` 回填合约到期字段；`fut_basic` 配置已补采 `last_ddate/delist_date` 作为回填源。
- [x] `/realtime_5min?market=Futures&ts_code=...` 已可读取 Futures 5 分钟 read model；reader 层会透传可空 L1 盘口字段，API 层仍只读、不生成交易判断。
- [x] `rt_fut_min` 采集已加强失败语义：provider 权限/接口/本地调用错误返回 `failed`；非空行情 CSV 桥接 SQLite 写入 0 行也返回 `failed`，避免把高频交易支撑链路误判为正常空跑。生产已确认 Tushare `rt_fut_min` 权限不足，采集器已增加 AKShare/Sina 5 分钟模拟盘备源，可通过 `CN_FUTURES_5MIN_AKSHARE_FALLBACK=0` 关闭；备源只用于模拟研究，不改变未来实盘券商/CTP 边界。
- [x] 排期边界：`P6_other_daily` 改为盘后夜间杂项/日频刷新；期货 5 分钟采集走独立 cron，日盘/夜盘每 5 分钟运行，跨午夜段按周二到周六凌晨覆盖。
- [x] 消费边界：TradingAgent/CNFutures 和 MarketGraph 只能读取 SharedSignals read model；SharedSignals 不生成买卖方向，不写 signal queue，不改变模拟盘或实盘权限。

### 2026-07-04 Polymarket markets/prices 生产采集闭环

- [x] `collectors/polymarket_collect.py` 从 Polymarket Gamma 拉取 active markets，并从 `outcomePrices`/`bestBid`/`bestAsk`/`lastTradePrice` 派生价格快照，写入统一 read model 的 `market_pm_markets` 与 `market_pm_prices`。
- [x] 每次采集写入 `market_ingest_runs`，source 固定为 `polymarket_gamma`，便于 freshness、失败和回放审计。
- [x] 新增 `cron/pm_collect.sh`，带 `flock`、生产 venv、proxy、`.env` bootstrap 和独立日志 `logs/cron/pm_collect.log`；生产 crontab 每 5 分钟运行。
- [x] 边界：PM 上游 API 只允许在 SharedSignals collector 层调用；TradingAgent PM 模拟/影子盘只读 `/pm_markets`、`/pm_prices` 或 read model，不直接访问 Polymarket。

### 2026-07-04 production cron and consumer-boundary audit

- [x] 主服务器 `/opt/investment/SharedSignals` 已确认 API health OK、functions 15/15、A股/加密/美股 freshness OK；A股最新交易日为 20260703，当前 2026-07-04 为周六，属合理状态。
- [x] 统一 read model 已确认写入：Ashare daily/intraday、Crypto daily、US daily、Futures daily、Global daily、Events、Factors、PM markets/prices；PM prices 最新 `price_time` 为 2026-07-04T14:30:02+00:00。
- [x] 生产 crontab 已确认 SharedSignals 负责数据采集与同步：Tushare P0 5 分钟、P1-P6 分层、Crypto 5 分钟、Polymarket 5 分钟、DuckDB sync、patrol、watchdog。
- [x] `crontab.txt` 与 `cron/crontab.txt` 已按生产边界更新；旧 2026-07-03 模板不再作为当前事实。

## 五、最近完成

### 2026-07-05 combined production crontab restored

- [x] 删除无引用旧目录 `collectors/tushare_old/`；该目录是旧 Ashare/Tushare 副本，已被现役 `collectors/tushare/` 取代。
- [x] 删除断链 MarketGraph symlink：`bridge/marketgraph_marketdata_db.py` 改为本仓库兼容模块；`data/association`、`data/intake` 改成本地目录。
- [x] 删除退役旧代码：`collectors/rss/`、`collectors/us_alpaca_*.py`、`tools/api_server.py`；RSS 恢复必须重新按 SharedSignals collector 契约设计，US 行情由 Tushare/现役 read model 负责。
- [x] `/health` 不再把 MarketGraph 研究图谱类 `associations`/`impacts` 作为 SharedSignals 核心供数健康项；`events` 已切到 SharedSignals SQLite `market_events` DB-first 输出并纳入健康检查，避免通过软链或文件复制重新耦合。
- [x] 主服务器 `marketgraph` 用户 crontab 已恢复为 Finance combined crontab：同时包含 SharedSignals 采集/同步/patrol/watchdog/capability 任务，以及 TradingAgent 模拟/复盘/健康任务。
- [x] 修复前 live crontab 只有 TradingAgent 任务，导致 SharedSignals `cn_futures_5min.sh`、P0 5分钟采集、DuckDB sync、patrol/watchdog 等调度没有安装；修复后 `SharedSignals /health` 从 `degraded` 恢复为 `ok`，cron `active_logs=2`。
- [x] 回退备份：`/opt/investment/SharedSignals/logs/cron/marketgraph_crontab_before_combined_sharedsignals_20260705T192844.bak`。

### 2026-07-05 DuckDB pytest venv baseline

- [x] 复核 DuckDB 依赖：`requirements.txt` 已声明 `duckdb>=1.1.0`，本地项目 `.venv` 已安装 DuckDB，可跑 DuckDB 同步/恢复相关测试。
- [x] 全量测试口径固定为项目 venv：`.venv/bin/python -m pytest tests/ -q --tb=short`。系统 Python 缺包只代表解释器选择错误，不代表生产采集或 DuckDB mirror 故障。
- [x] 当前全量测试基线：160 passed, 147 skipped；147 skipped 为已文档化 ghost/legacy 测试，不属于现役生产模块失败。

### 2026-07-05 SQLite 主库损坏自动恢复/备份切换

- [x] 新增 `tools/sqlite_recovery.py`：只读检测 `marketdata.sqlite` 是否损坏/缺失；支持从最近有效 `*.sqlite` 备份或 DuckDB mirror 恢复/重建；默认 dry-run，只有显式 `--apply` 才执行写操作。
- [x] `patrol.py` 的 `sqlite_health` 检查增加损坏/缺失探测，返回 `corrupt`/`missing`/`corruption_reason` 字段，供 `heal.py` 消费。
- [x] `heal.py` 的 `sqlite_health` 自愈策略增加恢复分支：检测到 corrupt/missing 时自动隔离坏库并切换/重建；无可用源时返回 `blocked_no_valid_recovery_source` 并升级 critical 告警。
- [x] 新增 `docs/sqlite_recovery_runbook.md`：覆盖触发条件、恢复源优先级、CLI 用法、apply 流程、无源可恢复时的手工步骤、验证清单与限制风险。
- [x] 新增 `tests/test_sqlite_recovery.py`：覆盖损坏检测、dry-run 不写、apply 隔离坏库并恢复/切换、无备份时 blocked、从 DuckDB 重建等场景。
- [x] 边界：只恢复 SharedSignals 数据存储层，不生成交易信号、不触发模拟/实盘执行；所有测试使用临时路径，不触碰生产 DB/mirror/备份。

### 2026-07-05 capability read-model alignment

- [x] `tools/capability_scan.py` 已把现役能力 smoke 收口为 DB-first reader 调用，动态从生产 read model 选择最新 A 股、美股、分钟线、Tushare news 和 announcements 样例；本地缺生产 DB 时只使用兜底样例，不现场调用 provider。
- [x] HK/cross-border 持仓与港股 lane 当前暂缓，`get_hk_hold`、`get_hk_etf`、`get_hk_index` 在 capability registry 中标记为 `skipped`，不会继续污染 degraded 计数。
- [x] `capability_scan` 输出 summary 增加 `skipped`，API 合同生成也能展示 skipped 状态。
- [x] 边界：该改动只影响 SharedSignals 能力自检和 `/capabilities` registry，不生成交易信号、不写 TradingAgent 队列。

### 2026-07-04 CNFutures 5 分钟数据新鲜度与下节交易时段校验

- [x] 新增 `tools/check_cn_futures_5min_freshness.py`：只读 `market_bars_intraday` 中 `market=Futures`、`interval=5min`、`provider=tushare_rt_fut_min` 的最新 bar，默认 10 分钟 stale 阈值，支持 `--sqlite-db`、`--now`、`--max-age-minutes`、`--json`；exit 码 0/1/2 对应 fresh、stale/no_data、error。
- [x] 新增 next-session verification：按中国期货市场日盘（09:00-15:00）和夜盘（21:00-02:30）判断当前/下一交易时段，若处于交易时段但尚无该时段 5 分钟 bar，则判为 stale。
- [x] 新增 `tests/test_cn_futures_5min_freshness.py`：覆盖 fresh/stale/no_data/error、日盘/夜盘/跨午夜/收盘间时段、human 与 `--json` 输出、命令行参数解析。
- [x] 边界：仅做数据健康检查，不生成交易信号、不触发模拟/实盘执行；不改动生产 crontab、不读取密钥或 `.env` 配置。

### 2026-07-04 RSS ownership and system email smoke verification

- [x] 主服务器实测系统邮件链路：SharedSignals 通过 Cloudflare Email Service 从 `notice@tradingagent.cc` 发往 `soc@coze.email` 成功；本次 smoke 邮件主题含 `[SMOKE][SharedSignals][系统]`。
- [x] 主服务器 crontab 已确认旧 RSSCollector hot/warm/@reboot 条目已从 live crontab 删除；MarketGraph 不再保留 RSS 维护入口。
- [x] 已纠正文档边界：RSS 采集归 SharedSignals；旧 RSSHub node 进程已停止，旧 `/opt/investment/RSSCollector`、`/opt/investment/RSSHub` 已归档，`rss_collector.db` 仅保留历史/迁移审计。

### 2026-07-04 CNFutures 期货日线自动化入口

- [x] 新增 `tools/collect_cn_futures_daily.py`：单日运行 `P6_other_daily/fut_daily`，支持 `--trade-date YYYYMMDD`、`--no-sqlite-bridge`、`--dry-run`，失败时透传非零退出码。
- [x] 新增 `cron/cn_futures_daily.sh`：带 `flock`、日志、生产 venv Python 和可选降权执行的 cron wrapper；只调用 SharedSignals 采集入口，不写交易信号。
- [x] 新增 `collectors/tushare/backfill_fut_daily.py`：支持 `--start-date/--end-date`、默认跳过周末、`--dry-run`、`--fail-fast` 和失败汇总，用于 6-12 个月历史期货日线回补。
- [x] 边界：`fut_daily` 输出仍只进入 CSV 与 SQLite `market_bars_daily`，`market=Futures`；TradingAgent/CNFutures 只读这些数据做模拟盘，SharedSignals 不生成买卖判断。

### 2026-07-04 低频宏观、事件/资产桥接与 watchdog 误报修复

- [x] `collectors/tushare/sync_daily.py` 支持 API 级 `lookback_days`；P4 低频宏观默认回看 180 天，避免 LPR/月度/季度数据被 7 天窗口误判为空。
- [x] 补齐 Tushare 低频宏观去重键：`shibor_lpr`/`cn_m`/`cn_ppi`/`cn_gdp`/`sf_month`/美国利率曲线/`repo_daily` 等不再 fallback 到 `ts_code,trade_date`。
- [x] 补齐 CSV→SQLite 映射：`cn_gdp`、`sf_month`、`us_tycr`、`us_tbr`、`us_tltr`、`repo_daily` 写入 `market_factors`；`cctv_news`/`news` 自动生成 `event_hash` 写入 `market_events`；`index_global` 写入 `Global` 日线，`etf_basic`/`fut_basic` 写入资产表。
- [x] `fut_daily` 期货日线改为按 `trade_date` 全品种采集，写入 `market_bars_daily` 且 `market=Futures`；定向补采可用 `sync_daily.py --tier P6_other_daily --only-api fut_daily --trade-date YYYYMMDD`。
- [x] 生产验证：P4 宏观 17/17 API 成功，`shibor_lpr` 3 行→6 条因子，P4 SQLite bridge 33,160 行；`cctv_news` 379 条事件，`index_global` 182 条，ETF 3,347 条，期货基础 10,000 条已补桥接；DuckDB sync 状态 `ok`。
- [x] `/cache/invalidate` 增加 POST 支持并保留 GET 兼容；API 已 force reload，POST 返回 200。
- [x] watchdog collector 日志扫描改为标签化失败匹配，只抓真实 `ERROR`/`FAILED`/`SQLITE_BRIDGE_ERRORS`/`bridge_failures>0`/`database is locked`，不再把 `bridge_errors=0` 误判；生产 `--no-email` 巡检恢复 `collector_status=ok`。
- [x] 验证：`pytest -q` 通过（79 passed, 147 skipped）；`py_compile` 与 cron wrapper `bash -n` 通过。

### 2026-07-04 行业映射自动刷新、force reload 与默认日期修复

- [x] 新增 `tools/refresh_stock_industry_map.py` 与 `cron/refresh_industry_map.sh`，每天 06:30 在 P3 reference 采集后从 `market_assets.sector` 生成 `stock_industry_map.csv`；生产已写出 5,521 条 A 股基础行业映射。
- [x] 修复行业映射原子写入权限：生成文件与备份固定为目录 owner/group + `664`；root cron 入口会自动降权为 `marketgraph` 执行，避免 API 因 root:root 600 文件回退 SQLite。
- [x] `tools/auto_restart.sh` 新增 `--force/--force-reload`，健康时也可显式重启加载部署后的新代码；默认 watchdog 行为仍保持“异常才重启”。
- [x] `reader.get_sentiment()` 与 `reader.get_realtime_5min()` 修复空日期处理；`/sentiment?limit=1`、`/realtime_5min?...&limit=1` 已按 limit 输出限流。
- [x] 生产验证：API PID 已强制重启至最新进程；`/health` OK，`/industry?ts_code=000001.SZ` 从 `stock_industry_map.csv` 读取且不降级，默认 realtime/sentiment 均不降级。

### 2026-07-04 reader 健康样例与 moneyflow 桥接修复

- [x] `reader.is_trading_day()` 已改为优先读取 `market_bars_daily`，周末或未来日期使用最近交易日 + weekday fallback，不再依赖旧 `reference/market_calendar.py` wrapper。
- [x] `reference/market_calendar.py` 已收口为 SharedSignals read-model 只读辅助工具，只读 `market_bars_daily`，不再导入旧 A 股 Tushare wrapper；未缓存的工作日区间明确降级。
- [x] `reference/adj_factor_cache.py` 已改为只读 `market_factors`/CSV cache，不再现场调用 Tushare；`update_daily()` 仅返回 read-side no-op，采集责任保留在 collector 层。
- [x] 已删除 `reference/` 下旧 `a_share_tushare_api.py`、RSSCollector collector/config/feed/filter/bridge 软链，避免后续 agent 误把历史兼容入口恢复成现役采集链路。
- [x] `reader.get_realtime_5min()` 已优先读取 `market_bars_intraday`，未传日期时自动使用该股票最新 intraday 日期；`reader.get_industry()` 已由 `stock_industry_map.csv` 优先读取，CSV 由 `cron/refresh_industry_map.sh` 每日 06:30 从 `market_assets.sector` 自动生成，`market_assets` 仅作为降级回退；`reader.get_sentiment()` 在 intake 空壳时回退 `data/sentiment_signals.csv`，未传日期时返回已有信号而不降级。
- [x] `reader.get_tushare("stock_basic")` 对 `market_assets` 使用 `Ashare + tushare` provider 过滤，避免 `tushare_stock_basic` 误过滤。
- [x] 已将已采集的 `data/tushare/moneyflow/20260703/*.csv` 桥接进 SQLite/DuckDB `market_factors`：3 只股票、54 条 moneyflow 指标，最新日期 `20260703`。回滚备份：`/opt/investment/MarketGraphRuntime/read_model/backups/marketdata_before_moneyflow_bridge_retry_20260704T093136Z.sqlite`。
- [x] `/health` 生产验证：SharedSignals API 进程 `marketgraph` 用户运行，`127.0.0.1:8082/health` 返回 `status=ok`、functions `15/15`、Ashare/Crypto/US freshness 均 OK。
- [x] 验证：`py_compile reader.py tools/health_check.py`、`pytest tests/test_api_server_edge.py tests/test_csv_bridge.py`（19 passed）、`pytest tests/test_reader.py`（26 passed）。

### 2026-07-04 P1 reader batch query

- [x] `reader.py` 的 `legacy_market_dataset(market_bars_daily)` 已从逐股票循环 `_sqlite_rows()` 改为单次 `WHERE symbol IN (...)` 批量查询，并按每个 symbol 保留最近 N 行。
- [x] 保持原有降级语义：SQLite 缺失或查询失败仍返回 degraded；多个 symbol 时仍按请求顺序返回首个有数据的 symbol。
- [x] 验证：本地目标 `py_compile` 与 pytest 结果见本轮回执。

### 2026-07-04 email STARTTLS TLS context

- [x] `tools/email_sender.py` 的 SMTP `starttls()` 已改为 `starttls(context=ssl.create_default_context())`，使用系统默认 CA 与安全 TLS 参数。
- [x] 验证：`python3 -m py_compile tools/email_sender.py` 通过；本仓当前没有直接覆盖该 sender 的 pytest 文件。

### 2026-07-04 SharedSignals API 与系统邮件运行时对齐

- [x] TradingAgent 生产 loader 已默认设置 `SHAREDSIGNALS_API_URL=http://127.0.0.1:8082`，A股读取链路以 SharedSignals/ShareChannel API 为第一入口，SQLite 仅保留只读回退。
- [x] SharedSignals 系统邮件发送器已改为 Cloudflare Email Service REST endpoint `/email/sending/send`，不再尝试 DeadSimple/SMTP；失败时只保存本地 fallback 证据。
- [x] 邮件配置入口统一到 `/opt/marketgraph/.env`，规范通道为交易 `notice@tradingagent.cc -> tradingadviser@coze.email`、系统 `notice@tradingagent.cc -> soc@coze.email`。

### 2026-07-04 SharedSignals-only provider 边界落地

- [x] `reader.get_tushare()` 与 `reader.get_fundamentals()` 已改为 DB-first：只读 read model/缓存；无映射或无数据返回 degraded，不现场调用 Tushare。
- [x] A 股 P2 财务采集已手动跑通并同步：`tushare_fina_indicator` 76,159 行、`tushare_dividend` 4,474 行进入 `market_factors`；`/fundamentals?symbol=000858.SZ` 返回 200。
- [x] 生产 API 已重启加载新代码，监听 `127.0.0.1:8082`；TradingAgent 健康回执已从 SharedSignals API 401 恢复为 ok。
- [x] MarketGraph 旧 RSSCollector/provider cron 已从现役 crontab 和 deploy 层清理；`/tushare/provider` passthrough 已禁用。RSSHub node 残留进程已停止并从现役层归档，不作为 MarketGraph 数据采集所有权。
- [x] crontab 回滚备份保留在 `logs/cron/crontab_before_sharedsignals_only_20260704T074002Z.txt` 和 `logs/cron/crontab_before_sharedsignals_only_pass2_20260704T074047Z.txt`。

### 2026-07-04 ghost 测试显式跳过

- [x] `tests/test_dedup.py`、`test_freshness.py`、`test_quality.py`、`test_rss_health.py`、`test_api.py` 已加模块级 skip，原因是这些文件测试本地复制 helper 或 mock client，没有绑定 SharedSignals 生产模块。
- [x] 当前处理方式是防止伪覆盖；后续如果需要恢复这些场景，应改写为直接导入 `reader.py`、`api_server.py`、RSS collector/failover 或 storage/collector mixin 的生产入口。
- [x] 验证：`python3 -m pytest tests/test_dedup.py tests/test_freshness.py tests/test_quality.py tests/test_rss_health.py tests/test_api.py -q` 结果为 147 skipped。

### 2026-07-04 Tushare 5分钟调度与 read model 桥接修复

- [x] `cron/collectors.sh` 支持按 `--tier` 单独运行，P0 可与日频层拆开调度；cron wrapper 默认使用 `/opt/marketgraph/venv/bin/python3`，避免 DuckDB 同步误用系统 Python。
- [x] `cron/crontab.txt` 已改为 P0 工作日 9-15 点每 5 分钟，P1/P2/P3/P4/P5/P6 按自然时间窗口运行，不再每 2 小时全 tier 捆绑。
- [x] `storage/csv_bridge.py` 已将 `stk_mins`/`rt_k` 映射到 `market_bars_intraday`，并为 Tushare CSV 写入补齐 `provider`、`collected_at`、`trade_date`、`interval` 等 lineage 字段。
- [x] 验证：SharedSignals 全量测试 207 项通过；DuckDB wrapper 用生产 venv 实跑通过，`duckdb_merge.py` 状态 `ok`。
- [ ] 待生产观察：下一个 A股交易时段确认 P0 每 5 分钟写入最新 `market_bars_intraday`；本轮会先补桥接已存在的 2026-07-03 `stk_mins` CSV。

### 2026-07-04 watchdog 日志失败扫描与 DuckDB venv Python

- [x] `tools/watchdog.py` 的 collector cron log 检查已从只看新鲜度扩展为扫描最近日志内容；命中 `Traceback`、`ModuleNotFoundError`、`Error`、`FAILED` 时将 `collector_status` 判为 critical，并把该项 `score_factor` 降为 0。
- [x] `cron/duckdb_sync.sh` 已新增 Python 解释器优先级：`SHAREDSIGNALS_VENV_PYTHON` → `VENV_PYTHON`（默认 `/opt/marketgraph/venv/bin/python3`）→ `/opt/marketgraph/venv/bin/python` → 系统 `python3`，避免 DuckDB 依赖落到系统 Python 缺包。
- [x] 验证：`py_compile tools/watchdog.py`、`bash -n cron/duckdb_sync.sh` 通过；本地 smoke 确认新日志内 `Traceback/ModuleNotFoundError` 会触发 collector critical。
- [x] 生产验证：主服务器已用 `marketgraph` 用户运行 DuckDB sync 成功；watchdog 误报修复后 score=100，collector_status 无 failure_patterns。

### 2026-07-04 30 天无人值守 watchdog 闭环

- [x] 新增 `tools/watchdog.py`：每轮检查 API `/health`、SQLite 最新 `trade_date`、cron log age、磁盘和内存，计算 0-100 分；`<60` 触发 heal，`<30` 调用自动重启，重启失败后升级邮件，连续 0 分写 halt 文件。
- [x] 新增 `tools/auto_restart.sh`：检查 API 端口、优雅终止、nohup 重启、健康验证，连续 3 次失败时尝试 previous binary rollback。
- [x] 新增 `cron/watchdog.sh`：5 分钟 cron wrapper，带 `flock`、`.env` bootstrap、独立 cron log。
- [x] watchdog 读取 TradingAgent 跨系统健康输入目录 `logs/watchdog_inputs/`，用于统一日志留痕；不改变 SharedSignals 供数边界。
- [x] 验证：`py_compile` 通过；`bash -n` 通过；`tests/test_watchdog.py` 4 项通过。
- [x] 生产验证：`cron/watchdog.sh` 已在主服务器以 `marketgraph` 用户运行；`tools/auto_restart.sh` 已完成一次真实 API 重启恢复演练。邮件通道实发仍按系统邮件专项单独验证。

### 2026-07-03 系统类邮件模板补齐

- [x] 新增 `tools/email_templates/`：`system_health`、`data_freshness_alert`、`collection_error`、`emergency_alert` 四个 HTML 模板，统一使用系统通道 `soc@coze.email`。
- [x] 模板包含统一深色 header、680px 白色正文、summary metrics、table sections、状态 badge、HTML5 `<figure>/<figcaption>` 和纯 inline SVG 图表；仅提供渲染层，未改动发送链路或生产 crontab。
- [x] 已补图表：健康状态 donut、检查进度条、预期/实际新鲜度柱状图、stale sparkline、采集失败横条、成功/失败 donut、紧急告警 pulse 指示器和告警 timeline。
- [x] 验证：新增模板与 helper 均已 `py_compile` 通过，并完成 4 模板最小 render smoke（均生成 2 个 figure / 2 个 svg）。

### 2026-07-03 cron 解耦入口补齐

- [x] 新增 `cron/collectors.sh`：按当前有效 Tushare tier 逐项运行 `sync_daily.py --exit-on-failure`。
- [x] 新增 `cron/duckdb_sync.sh`：独立运行 `duckdb_merge.py --json`，与旧根层 wrapper 解耦。
- [x] 新增 `cron/patrol.sh`：运行 patrol，低于阈值时触发 heal。
- [x] 新增 `cron/AGENTS.md`：约束 cron wrapper 只做调度、不内嵌业务逻辑和密钥。
- [x] 服务器部署验证：patrol/watchdog/collectors/DuckDB sync/capability scan 已写入主服务器 `marketgraph` 用户 crontab。

### 2026-07-03 P0 架构债务清零与 API 迁移状态对齐

- [x] CSV→SQLite 桥接闭环完成：`storage/csv_bridge.py` 已建成，sync_daily.py 已能把 CSV 输出接入 SQLite→DuckDB 管线。
- [x] `market_bars_daily` provider-PK 迁移已在服务器执行；provider 不再参与主键，只作为来源字段保留。
- [x] API 服务器线程化、auth 内存治理、env 启动引导统一均已完成，P0 6 项架构债务全部清零。
- [x] P2 API 消费迁移已完成当前生产边界：TradingAgent 侧客户端和核心 reader API-first 已完成；MarketGraph 旧 provider/RSS/Tushare 采集 cron 与 provider passthrough 已禁用，保留 read-model 只读消费。

### 2026-07-03 R15 故障注入与恢复路径审计

- [x] 本地完成 14 个故障/恢复 probe，报告路径：`/tmp/audit_r15_fault.md`。
- [x] 通过项：API 中断/超时客户端受控失败，TradingAgent SQLite fallback，坏 JSON 返回 400，线程池耗尽返回 503，SaveError 传播，API 重启缓存重建，部分 CSV 下次原子覆盖，全后端缺失时 endpoint 返回 degraded。
- [ ] 待补闭环：SQLite 主文件损坏后的自动恢复/备份切换；运行中配置变更热加载或明确 restart-only 文档。

### 2026-07-03 final Codex review HIGH/MEDIUM 修复

- [x] `api_server.py`：`/market_data` 透传 `freq`；`/capital_flow` 支持 `date` 或 `ts_code/start/end` 参数，修复 TradingAgent 客户端与服务器契约不一致。
- [x] `config/api_tokens.json`：已 `git rm --cached` 退出仓库追踪；`config/api_tokens.example.json` 只保留 `token_hash`/`sha256` 兼容字段模板；`.gitignore` 已确认覆盖真实 token 文件。
- [x] `tools/api_server.py`：曾标记为 deprecated capability server；2026-07-05 已删除，当前唯一数据 API 入口为根目录 `api_server.py`。
- [x] 新增 API handler 回归测试覆盖 `market_data.freq` 和 `capital_flow` range 参数传递。
- [x] 验证：`python3 -m pytest tests/ -q --tb=line` 通过（205 passed；5 个既有 `SHAREDSIGNALS_TOKEN_SALT` 未配置 warning）。

### 2026-07-02 final deep audit CRITICAL/HIGH 清零修复

- [x] `auth.py`：JWT 默认禁用；未配置 `SHAREDSIGNALS_JWT_PUBLIC_KEY` + `SHAREDSIGNALS_JWT_ISSUER` 时只允许 token-hash 认证；配置后验证签名、`exp`、`iss`，JWT scope 不再默认 `full`
- [x] `collectors/tushare/collector.py` + `sync_daily.py`：非空 rows 保存失败改为 `SaveError`；sync summary 区分 API failure、save failure、bridge failure；`--exit-on-failure` 覆盖三类失败
- [x] `env_bootstrap.py`：新增 `env_int` / `env_float` / `env_bool`，并接入 `api_server.py`、`reader.py`、`auth.py`、`storage/csv_bridge.py` 的 import-time 数字 env 读取
- [x] 新增回归测试：伪造 JWT 拒绝、issuer/exp 验证、JWT 最小 scope、保存失败计数、失败退出判定、malformed env fallback

### 2026-07-02 R7-R9 final deep audit：7 个 HIGH findings 修复

- [x] `reader.py`：缓存 key 纳入 `_CACHE_GENERATION` 快照，避免 clear 与并发 populate 竞态；新增 `SHAREDSIGNALS_CACHE_MAX_BYTES`（默认 50MB）和 `/cache/status` 字节估算；`get_associations`/`get_impacts` 大结果缓存降载
- [x] `storage/csv_bridge.py`：CSV→SQLite 默认整文件 `BEGIN IMMEDIATE` 事务，chunk 仍用于 `executemany()`；任一 chunk 失败会 rollback，避免半文件落库
- [x] `api_server.py`：`aggregate_metadata()` / `wrap_response()` 保留 reader 的 `degraded_reasons` 和 `lineage`
- [x] `collectors/tushare/collector.py` + `sync_daily.py`：采集异常显式打标，tier summary 统计每 API 失败数；新增 `--exit-on-failure` 和失败比例阈值
- [x] `collectors/tushare/sync_daily.py`：bridge 结果区分 `ok` / `failed` / `disabled` / `unmapped` / `empty`，summary 暴露 `bridge_errors`
- [x] `auth.py`：dedup 响应缓存增加 `SHAREDSIGNALS_DEDUP_MAX_BYTES`（默认 10MB）与 `SHAREDSIGNALS_DEDUP_MAX_ENTRY_BYTES`（默认 1MB），超限跳过或 LRU 驱逐
- [x] `bridge/__init__.py`：为本地 Projects 工作区补充 sibling `../MarketGraph` 模块搜索路径，避免 `/opt/investment/MarketGraph` 不存在时测试导入断链
- [x] 验证：`tests/test_api_server_edge.py` + `tests/test_csv_bridge.py` 已通过；全量验证见本轮最终回执

### 2026-07-02 TEST ROUND 3：Phase 1 边界条件验证

- [x] CSV→SQLite bridge 边界测试：空 CSV、BOM-only、全未知列、NULL byte、10 万行 chunk、特殊字符路径均通过
- [x] env_bootstrap 边界测试：空值、comment-only、`export` 前缀、缺失 `.env`、重复 bootstrap 均通过
- [x] API server 边界测试：无 query、malformed JSON query、未知 endpoint、并发 cache invalidate、超长 query 均通过
- [x] schema contract 边界测试：未知 dialect、未知 table、无主键表渲染均通过
- [x] `api_server.py` 增加显式 JSON 查询参数校验：`params`/`filters`/`payload`/`*_json` 解析失败返回 400
- [x] 验证：`python3 -m pytest tests/ -v -k "edge or test_csv or test_env" --tb=short`（23 passed, 173 deselected）和 `py_compile` 均通过

### 2026-07-02 Phase 1 HIGH findings 修复

- [x] `storage/csv_bridge.py`：CSV→SQLite 桥改为 1000 行分块 `executemany()`，每个 chunk 独立事务；按目标表主键验证必填列，坏行记录日志后跳过；行数以 `conn.total_changes` 差值统计
- [x] `reader.py`：公共读取边界接入 `_maybe_invalidate()`，缓存 TTL 和文件变更检测统一生效
- [x] `reader.py`：缓存时间源统一为 `time.time()`，避免 `time.monotonic()` 与文件 `st_mtime` epoch 时间域混用
- [x] `api_server.py`：新增 `SHAREDSIGNALS_REQUEST_TIMEOUT`（默认 30s）和 `SHAREDSIGNALS_MAX_THREADS`（默认 20）；达到并发上限时返回 503
- [x] 验证：`py_compile`、指定 `pytest`、`tools/check_schema_drift.py` 均通过

### 2026-07-02 P0 architecture debt Step 5/6

- [x] 新增 `storage/schema_contract.py`，统一渲染 SQLite/DuckDB 11 表 schema
- [x] `market_bars_daily` 契约主键改为 `(market, symbol, trade_date)`，`provider` 保留为普通来源字段
- [x] `storage/schema.py`、`storage/duckdb_schema.py` 改为从契约生成，保留 `SCHEMA_SQL`、`DUCKDB_SCHEMA_SQL`、`TABLE_PRIMARY_KEYS` 兼容导出
- [x] 新增 `tools/check_schema_drift.py`，用于 schema 契约一致性检查
- [x] 新增 dry-run 迁移脚本 `storage/migrations/20260702_remove_provider_pk.py`；实际迁移未执行
- [x] 验证：py_compile、schema drift check、migration dry-run 均通过

### 2026-07-02 P0 architecture debt Step 1/2

- [x] 新增 `env_bootstrap.py`，集中解析并一次性加载 SharedSignals `.env`
- [x] `api_server.py` 移除 import-time `.env` 加载，启动时先 bootstrap 再导入 `auth`/`reader`
- [x] `reader.py` 移除 import-time 环境写入，路径配置改为首次访问时解析
- [x] `collectors/tushare/collector.py` 改为实际 Tushare API 调用时才 bootstrap 并导入 wrapper
- [x] 修复 `api_server.py` `/tushare` allowlist 后的裸 `...` 编译错误
- [x] 新增 `test_no_import_time_env_mutation()` 覆盖导入无环境变量副作用

### 2026-07-02 Tushare API 包装器迁移

- [x] `tushare_api.py`（843 行，40+ 函数）+ `tushare_common.py`（657 行）从 `/opt/investment/Ashare/tools/` 迁移到本目录
- [x] 历史兼容性包装器 `a_share_tushare_api.py` + `a_share_common.py` 已仅保留在 collector 边界；`reference/` 不再保留旧兼容软链。
- [x] `collector.py` 移除旧 sys.path bootstrap，改用 `from .tushare_api import _call`
- [x] `reader.py` ASHARE_ROOT 默认值指向 `collectors/tushare/`
- [x] `capability_scan.py` 路径引用更新
- [x] `reference/adj_factor_cache.py` 已改为 read-model/CSV cache 只读，不再修改 `sys.path` 调用 provider。
- [x] 服务器部署 + 全路径导入验证通过（4 种导入方式）

### 2026-07-02 SharedSignals Bug 修复

- [x] fx_daily: 补 `exchange: FXCM` 参数（之前缺此参数导致 0 行）
- [x] hibor: 参数从 `start_date`/`end_date` 改为 `date`（Tushare API 只接受单日期）
- [x] hk_daily: `per_stock: false` → `per_stock: true` + `stock_list: hk`（API 需要 ts_code）

### 2026-07-02 DuckDB 初始同步

- [x] StorageAdapter 默认路径修复 — DEFAULT_SQLITE_PATH/DEFAULT_DUCKDB_PATH 指向生产路径
- [x] DuckDB 数据库创建 + schema 初始化（11 表）
- [x] 全量初始同步 — 145,391 行，SQLite 116MB → DuckDB 54MB（列存压缩 53%）
- [x] crontab 每 5 分钟自动同步（flock 锁 + JSON log）
- [x] 服务器部署验证 — duckdb_merge_cron.sh 3.16s 完成全表同步

### 2026-07-02 Goal 3 API 安全加固

- [x] auth.py 增强 — 10 scope 类别 + SCOPE_ENDPOINTS 映射 + "read" union scope + "full" wildcard
- [x] api_server.py scope enforcement — 所有端点 authenticate → check_endpoint_scope → rate limit → dispatch
- [x] /health 分层 — 无认证返回最小版，有 token+scope 返回完整健康报告
- [x] LOCALHOST_BYPASS — 127.0.0.1/::1/localhost 自动跳过认证（生产保护 internals）
- [x] 2 个 API token 配置 — tradingagent（read scope）、marketgraph（health+market_data etc+read）
- [x] SHAREDSIGNALS_API_KEY 注入 /opt/marketgraph/.env，TRADINGAGENT_ENV_LOADER chain 生效
- [x] SharedSignalsAPIClient 部署到服务器 + 3 接口测试通过（market_data/health/fundamentals）

### 2026-07-02 Goal 3 数据集成

- [x] 美国/全球宏观数据采集覆盖 — P4 新增 us_tycr, us_tbr, us_tltr（各 20 行/日）
- [x] 港股财务数据采集接入 — P5 新增 hk_income, hk_balancesheet, hk_cashflow（stock_list: hk）
- [x] sync_daily.py 港股支持 — stock_list 属性路由，hk_stock_master.csv（78 只港股）
- [x] sync_daily.py 导入修复 — sys.path 改为 SharedSignals 根，绝对包导入
- [x] hk_daily/us_daily 配置从 per_stock→global 修复
- [x] 服务器部署验证通过（P4 US 宏观 3 API，P5 HK 财务 3 API，共 701 行测试数据）

### 2026-07-02 Goal 2 审计 — SharedSignals → TradingAgent → MarketGraph 数据流

**2 轮审计，10 维度，46 发现，10 项修复全部完成。** SharedSignals 相关发现和修复：

**SharedSignals API 与数据流（Round 1 + Round 2）：**
- API 客户端 `is_trading_day()` 默认返回 False（fail-safe）、API sentinel→TTL 恢复
- 健康检查：sockstat 端口检测替代 HTTP health check（30s SIGALRM 超时）
- 配置一致性：端口 8082/8900 不一致修复

**SharedSignals 内部修复（Round 2）：**
- `reader.py`：14 个 `@lru_cache` 函数无 TTL 过期 → 添加 TTL（默认 5 分钟）+ 文件 mtime 失效 + `clear_caches()` + `_maybe_invalidate()` + `_register_cached` 装饰器模式
- `auth.py`：Token hashing 加 salt → PBKDF2-HMAC-SHA256（100k 迭代）+ 向后兼容 SHA256 fallback
- `api_server.py`：新增 `/cache/invalidate` + `/cache/status` 端点，端口默认值 8900→8082
- `.gitignore`：添加 `config/api_tokens.json` + `.env.*`（防密钥泄露）
- 数据新鲜度：`datetime.now()` 应改用 UTC-aware（TradingAgent 侧 20+ 处）

**已应用修复（10 项，SharedSignals 相关 6 项）：**
1. [x] `.gitignore`：添加 `config/api_tokens.json` + `.env.*`
2. [x] `tools/api_server.py`：端口默认值 8900 → 8082；2026-07-05 已删除，保留此项仅作历史修复记录
3. [x] `auth.py`：Salt token hashing（PBKDF2-HMAC-SHA256），`/cache/invalidate` 和 `/cache/status` 归入 `health` scope
4. [x] `reader.py`：LRU cache 失效系统 — TTL + 文件 mtime 检测 + `clear_caches()` + `/cache/invalidate` + `/cache/status`
5. [x] `api_server.py`：添加 `/cache/invalidate` 和 `/cache/status` 端点
6. [x] `tradingagent/.env.example`：`SHAREDSIGNALS_ROOT` + `MARKETGRAPH_ENV_FILE` 路径修正

### 2026-07-02 Goal 2 审计 Round 3（高强度终检）

**5 维度并行审计，~81 发现（23 CRITICAL/HIGH + 30 MEDIUM + 28 LOW），3 项修复已应用。**

审计维度：数据可追溯性、边界情况、性能/扩展性、文档/可发现性、集成契约。

**SharedSignals 相关发现（CRITICAL/HIGH）：**
- **6 条 CRITICAL 断裂数据链：** Tushare CSV→SQLite 接入桥缺失（`sync_daily.py` 只写 CSV，无 SQLite 写入路径）；RSS NDJSON→`event_candidates.csv` 断裂（不同格式/路径，`runtime_bridge.sh` 未覆盖）；Crypto NDJSON→`klines.csv` 断裂（字段不匹配）；`ts_code` vs `market+symbol` Schema 不匹配；`bar_time` vs `open_time` 字段名不匹配
- **API 服务器单线程阻塞：** `api_server.py` 使用 plain `HTTPServer`（非 ThreadedHTTPServer），并发请求排队
- **auth.py 无界内存增长：** `_DEDUP_CACHE` 和 `_REQUEST_LOG` 无容量上限，无 TTL 过期
- **评分管线 N+1 扇出：** 每只股票 5-6 次调用，20 只股票 100+ 次循环内调用
- **API 参数文档完全缺失：** 15 个数据端点无参数说明、无类型标注、无示例
- **无端点上手指南：** 新消费者不知道认证方式、端点列表、请求格式
- **SharedSignalsAPIClient 孤儿代码：** 已定义但 TradingAgent 从未导入使用
- **Capability scan 注册表与 API 实际分歧：** 扫描结果与实际端点列表不一致

**已应用修复（Round 3，3 项）：**
7. [x] `tradingagent/shared/data/reader.py`：MarketGraphCSVReader 路径修复 — `intake` 和 `get_regime()` 缺少 `data/` 目录前缀，导致 `all_weather_regime.csv`、`event_candidates.csv`、`sentiment_signals.csv` 静默加载失败
8. [x] `SharedSignals/reader.py`：`_read_csv` UTF-8 编码容错 — 添加 `errors="replace"`，防止单个损坏字节导致整文件返回空
9. [x] `SharedSignals/storage/schema.py` + `duckdb_schema.py`：`market_factors` 表添加 `(symbol, event_time)` 复合索引，消除全表扫描

**已知但延后的 CRITICAL 问题（待 Goal 3/4 修复）：**
- 6 条断裂数据链需要端到端重连（CSV→SQLite 桥、RSS NDJSON→CSV、Crypto NDJSON→CSV、Schema 对齐）
- API 服务器线程化改造
- auth.py 内存治理（LRU 上限 + TTL）
- API 文档补全 + 端点上手指南

### 2026-07-02 Goal 2 审计 Round 4（终检 — 5 新维度，83 发现，8 修复）

**5 维度并行审计：并发与线程安全、错误恢复与韧性、可观测性与监控、代码质量与可维护性、数据完整性与一致性。**

**SharedSignals 相关发现（CRITICAL/HIGH）：**
- **lru_cache 线程不安全：** 15 个 `@lru_cache(maxsize=512)` 函数在 ThreadedHTTPServer 下并发访问会损坏内部 dict/linked-list 状态
- **TOCTOU race：** `_maybe_invalidate()` L171-178 在锁外读 `_CACHE_LAST_RESET`，`clear_caches()` 在锁内写
- **log_message 完全禁用：** api_server.py L186-187 无条件 `return`，零 HTTP 请求日志记录
- **500 错误泄露原始异常：** L238-239 `except Exception as exc: return self._error(500, f"internal error: {exc}")` — 原始异常暴露给客户端，无日志
- **无 SQLite busy_timeout：** reader.py L438 连接无超时设置，写锁期间读立即失败
- **数据完整性问题：**
  - `get_market_data()` 查询不包含 `market` 过滤 — 跨市场符号冲突会返回重复行
  - event_hash 64 位截断碰撞风险（3 个收集器用 3 种不同哈希策略）
  - Tushare/RSS 收集器只写 CSV/NDJSON，不写 SQLite — 依赖 MarketGraph sync_all 作唯一 SQLite 桥
  - `market_bars_daily` 主键含 `provider` — 同 symbol+date 不同 provider 可产生重复行
  - schema.py vs duckdb_schema.py 中 INTEGER vs BIGINT 类型不匹配
- **代码质量问题：**
  - `SharedSignalsAPIClient` 214 行死代码从未被生产代码导入
  - `_get_capital_flow_cached` 死代码 — 已删除，`get_capital_flow()` 统一读取 SharedSignals read model 中的 `moneyflow` 桥接行
  - reader.py 热路径中 `sys.path.insert`（每次调用修改导入系统）
  - schema.py 和 duckdb_schema.py 11 表定义重复无漂移防护
  - `adj_factor_cache.py` 硬编码路径 `/opt/investment/...` — 已修复为环境变量 + SharedSignals read-model/CSV cache 只读

**已应用修复（Round 4，8 项）：**
10. [x] `reader.py`：SQLite 连接添加 `PRAGMA busy_timeout = 5000`（防止写锁期间读失败）
11. [x] `reader.py`：`get_market_data()` 查询添加 `market` 过滤（从 ts_code 后缀推导），防止跨市场数据污染
12. [x] `api_server.py`：`log_message()` 从 no-op 改为 logging.info（恢复 HTTP 请求日志）
13. [x] `api_server.py`：500 错误处理器改为日志记录完整 traceback，返回通用错误消息（不泄露原始异常）
14. [x] `tradingagent/shared/data/reader.py`：SharedSignalsReader 连接添加 `busy_timeout = 5000`
15. [x] `tradingagent/shared/data/reader.py`：TradingagentDataReader 添加 `_maybe_alert()` 死人手刹 — errors 每累积 10 条自动 WARNING 日志
16. [x] `collectors/rss/collector.py`：event_hash 从 64 位（`[:16]`）升级到 128 位（`[:32]`）；RSS 旧 collector 已于 2026-07-05 删除
17. [x] `collectors/rss/gap_filler.py`：同上，event_hash 升级到 128 位；RSS 旧 collector 已于 2026-07-05 删除
18. [x] `tradingagent/shared/data/shared_signals_api.py`：添加 DeprecationWarning — 标记为未使用的参考代码
19. [x] `reader.py`：删除 `_get_capital_flow_cached` 与旧 `MONEYFLOW_ROOT`，避免误导为仍存在独立 moneyflow CSV 读取路径

### 2026-07-02 Goal 2 审计 Round 5（五维度最终审计 — 58 发现，23 修复）

**5 新维度并行审计：数据保真度与静默失败、安全与信任边界、配置与部署韧性、并发与资源安全、架构与契约一致性。**

**SharedSignals 相关发现（CRITICAL/HIGH）：**
- **Look-ahead bias（CRITICAL）：** `reader.py:_as_of_filter()` 在 filter 全部移除行时回退到返回未过滤行 — 回测被未来数据污染
- **CSV 非原子写入（CRITICAL）：** `collector.py` 的 `save()` 先 `open("w")` 截断再写入 — 并发 reader 会读到空/半截文件
- **`plan()` 模板 bug（CRITICAL）：** `collector.py:plan()` 返回未解析的 `{ts_code}` 占位符 — 所有 per-stock Tushare 采集器静默 no-op
- **TOCTOU race in audit CSV（CRITICAL）：** `_write_audit_csv()` `os.path.exists()` 检查 + append 模式 — 并发 collector 产生重复 header
- **localhost bypass 默认为 on（CRITICAL）：** `auth.py` `SHAREDSIGNALS_LOCALHOST_BYPASS` 默认 `"1"` — 完全鉴权绕过
- **Token hashing 无 salt 默认（HIGH）：** 空 `SHAREDSIGNALS_TOKEN_SALT` 退化为纯 SHA256
- **env 自动加载在 import-time（HIGH）：** 3 个模块在 import 时 mutate `os.environ` — 非确定性行为
- **无 circuit breaker（HIGH）：** 3 个外部 API collector 各自重试，无全局故障追踪
- **DatabaseError 未捕获（HIGH）：** `_query()` 只捕获 `sqlite3.OperationalError`，忽略更广泛的 `DatabaseError`
- **YAML 注入 via fill_params()（HIGH）：** string→replace→YAML re-parse 循环允许参数注入
- **Tushare endpoint 无 allowlist（HIGH）：** `/tushare` 传递任意 `api_name` 到外部 API
- **Unbounded limit 参数（HIGH）：** `to_int()` 无上限 — 内存耗尽 DoS 可能
- **`st_mtime` 是 open-time 非 close-time（HIGH）：** POSIX 语义下 cache 在空文件上失效
- **Zero-vector 静默返回（MEDIUM）：** 缺少 `DEEPSEEK_API_KEY` 返回 `[[0.0]*256]` — 语义搜索退化为垃圾
- **`/dev/null` fallback（MEDIUM）：** `SharedSignalsReader(Path("/dev/null/..."))` 静默掩蔽数据完全丢失
- **heal.py Module-load 无存在检查（LOW）：** heal 脚本引用的 BRIDGE_SCRIPT/FAILOVER_SCRIPT 不检查文件存在性

**已应用修复（Round 5，15 SharedSignals 相关项）：**
1. [x] `reader.py`：`_as_of_filter` — 移除 fallback 到未过滤行，防止 look-ahead bias
2. [x] `reader.py`：`_read_csv` — 移除 `errors="replace"`，以 UnicodeDecodeError 替代静默 U+FFFD
3. [x] `collectors/tushare/collector.py`：`plan()` — 从 `stock_master.csv` 解析 `{ts_code}` 占位符
4. [x] `collectors/tushare/collector.py`：`save()` — tempfile + `os.replace()` 原子写入
5. [x] `collectors/mixins/audit.py`：`_write_audit_csv()` — 使用 tempfile + `os.replace()` 消除 TOCTOU race
6. [x] `collectors/orchestrator.py`：添加 `_running_collectors` set + `_lock` 防止收集器重叠
7. [x] `auth.py`：`LOCALHOST_BYPASS` 默认为 `"0"`，"0"→ 空 salt 触发 RuntimeWarning
8. [x] `api_server.py`：`to_int()` 添加 min_val/max_val 限制
9. [x] `api_server.py`：`/tushare` 添加 87 API 名称 allowlist
10. [x] `collectors/tushare/sync_daily.py`：`fill_params()` — data-level 替换替代 YAML re-parse
11. [x] `reader.py`：`_file_collected_at()` 拒绝空文件（st_size == 0 返回 None）
12. [x] `reader.py`：`_is_trading_day_cached()` 清理重复 `sys.path.insert`
13. [x] `reader.py`：Tushare import 路径修复（ASHARE_ROOT / "tools" → ASHARE_ROOT）
14. [x] `collectors/polymarket/collector.py`：无限翻页保护（max_iterations 计算）
15. [x] `heal.py`：BRIDGE_SCRIPT 和 FAILOVER_SCRIPT 的 module-load 存在性验证

### 2026-07-02 Goal 1 退役清理

- [x] 服务器 `/opt/investment/Crypto/` 过期数据归档
- [x] `capability_registry.json` 中的 Ashare 引用识别为历史元数据残留；当前生产能力以 `tools/capability_registry.json`、`/capabilities` 和 `/health` 的 live 输出为准。
- [x] `/opt/investment/Ashare/` 不再作为 TradingAgent active dev/runtime root；TradingAgent 已完成 A 股模拟执行依赖迁移至 `tradingagent/Ashare/sim_executor.py`，生产剩余历史路径不得被恢复为数据入口。

## 六、采集器架构

| 采集器 | 数据源 | 输出表 | 状态 |
|--------|--------|--------|------|
| Tushare | Tushare Pro（按 `collectors/tushare/config.yaml` 分层配置） | market_bars_daily 等 | 已有（参考实现） |
| Binance | Binance REST API | market_bars_daily, market_bars_intraday | 新实现 |
| Polymarket | Gamma API + CLOB API | market_pm_markets, market_pm_prices | 新实现 |
| RSS | RSS collector（deferred） | market_events / sentiment_signals | 退役旧顶层资产，恢复前需重接 SharedSignals collector |

### 运维基础设施

| 组件 | 文件 | 说明 |
|------|------|------|
| 巡查 | `patrol.py` | 6 项健康检查：source_health, data_freshness, staging_backpressure, sqlite_health, disk_usage, field_drift |
| 自愈 | `heal.py` | 6 种策略：source failover, backfill, force bridge merge, WAL checkpoint, disk cleanup, field drift update |
| 同步 | `duckdb_merge.py` | SQLite → DuckDB 定时同步 |
| 调度 | `scheduler.py` | merge → patrol → heal 统一调度入口 |

### Tushare 采集分层

| Tier | 频次 | 内容 |
|------|------|------|
| P0 | 交易时段 5 分钟 | A 股盘中行情 |
| P1 | 盘后日频 | 日线行情 |
| P2 | 盘后日频 | 财务数据 |
| P3 | 晚间日频 | 参考数据 |
| P4 | 早间日频 | 宏观数据 |
| P5 | 收盘后日频 | 港股/美股 |
| P6 | 日频 | 期货/基金/ETF/新闻 |
| P7 | 已删除 | Crypto/PM 不属于 Tushare tier，走各自 collector |

## 七、关联系统状态

- [TradingAgent STATUS](../tradingagent/STATUS.md) — 交易执行与模拟盘状态
- [MarketGraph STATUS](../MarketGraph/STATUS.md) — 研究图谱与因果状态
- [Finance STATUS](../STATUS.md) — 根工作区总览
