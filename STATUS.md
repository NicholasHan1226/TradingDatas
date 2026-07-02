# SharedSignals 状态

> **给所有 agent：** 读完 [AGENTS.md](AGENTS.md) 理解规则后，读本文件理解"现在在哪、要去哪、能做什么"。
>
> **⚠️ 变更后必须更新本文件。**
>
> 最后更新：2026-07-02 (Phase 1 HIGH findings 修复：CSV 批量入库、reader cache 失效、API timeout/thread bound)

---

## 一、当前状态

- **行情采集**：稳定运行 — Tushare（25 接口）+ Binance（4）+ Polymarket（3）→ SQLite + CSV
- **事件采集**：RSS（883 源）+ Tavily → NDJSON staging → runtime_bridge → CSV
- **巡查自愈**：patrol.py（6 维度 10 分钟）+ heal.py（failover/backfill/checkpoint）
- **采集器架构**：BaseCollector + 6 mixins + 4 采集器实现，完整生命周期（health→plan→collect→validate→dedup→save→audit→coverage）
- **DuckDB 迁移**：SQLite (116MB) → sqlite_scan → DuckDB (54MB, 列存压缩)，crontab 每 5 分钟同步
- **港股采集**：hk_income/hk_balancesheet/hk_cashflow 通过 stock_list: hk 路由接入
- **全球宏观**：us_tycr/us_tbr/us_tltr 美国国债收益率曲线数据
- **存储**：marketdata.sqlite（~116MB），marketdata.duckdb（~54MB），11 表 145K+ 行，staging 6 streams 活跃
- **服务器**：杭州 `8.138.181.177`（境内采集+存储），新加坡 `47.82.153.58`（境外 RSS → rsync → 杭州）

## 二、已知问题

- shibor_lpr 返回 0 行（待调查，libor 已停更属正常）
- sync_daily.py CSV 输出与 SQLite→DuckDB 管线之间无自动接入桥（当前 MarketGraph 采集器直接写 SQLite，SharedSignals CSV 为补充路径）

## 三、API 接口状态（17/17 覆盖）

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
| get_associations | /associations | OK |
| get_impacts | /impacts | OK |
| get_industry | /industry | OK |
| get_realtime_5min | /realtime_5min | OK |
| get_tushare | /tushare | OK |
| clear_caches | /cache/invalidate | OK |
| cache_status | /cache/status | OK |

- 健康检查覆盖：10 → 17 函数（health_check.py 已更新）
- API 客户端：TradingAgent [SharedSignalsAPIClient](../tradingagent/shared/data/shared_signals_api.py) 已实现 15 接口 HTTP 封装

## 四、下一步

1. [x] DuckDB 初始同步完成（145K 行），定时同步已调度（每 5 分钟 crontab）
2. [x] API 安全加固：Bearer token 认证 + scope-based 端点访问控制 + key-based 账户隔离
3. [x] fx_daily/hibor 参数调优（2026-07-02 修复：fx_daily 加 exchange=FXCM，hibor 改用 date 参数）
4. [x] hk_daily 全局查询修复（2026-07-02 修复：改为 per_stock + stock_list=hk）
5. [ ] **P0：CSV→SQLite 接入桥** — sync_daily.py CSV 输出接入 SQLite→DuckDB 管线
6. [x] **P0：schema 漂移检测** — schema.py 与 duckdb_schema.py 11 表自动一致性校验
7. [x] **P0：provider 从 market_bars_daily 主键移除** — 已生成安全迁移脚本，尚未执行实际数据库迁移
8. [x] **P1：API 服务器线程化与资源上限** — ThreadingHTTPServer + request timeout + semaphore thread limiter
9. [ ] **P1：auth.py 内存治理** — `_DEDUP_CACHE`/`_REQUEST_LOG` 加 LRU 上限 + TTL
10. [x] **P1：import-time env 加载统一** — 集中到进程启动入口，消除非确定性
11. [ ] **P2：SharedSignals API 作为唯一消费入口** — 推动 TradingAgent/MarketGraph 通过 HTTP API 而非直接 SQLite 读取

## 五、最近完成

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
- [x] 兼容性包装器 `a_share_tushare_api.py` + `a_share_common.py` 放在同目录（re-export + `os.path.realpath` 解析，PYTHONPATH 兼容）
- [x] `collector.py` 移除旧 sys.path bootstrap，改用 `from .tushare_api import _call`
- [x] `reader.py` ASHARE_ROOT 默认值指向 `collectors/tushare/`
- [x] `capability_scan.py` 路径引用更新
- [x] `reference/adj_factor_cache.py` sys.path 更新
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
2. [x] `tools/api_server.py`：端口默认值 8900 → 8082
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
  - `_get_capital_flow_cached` 死代码 — `get_capital_flow()` 直接调用 `get_tushare("moneyflow")`
  - reader.py 热路径中 `sys.path.insert`（每次调用修改导入系统）
  - schema.py 和 duckdb_schema.py 11 表定义重复无漂移防护
  - `adj_factor_cache.py` 硬编码路径 `/opt/investment/...`

**已应用修复（Round 4，8 项）：**
10. [x] `reader.py`：SQLite 连接添加 `PRAGMA busy_timeout = 5000`（防止写锁期间读失败）
11. [x] `reader.py`：`get_market_data()` 查询添加 `market` 过滤（从 ts_code 后缀推导），防止跨市场数据污染
12. [x] `api_server.py`：`log_message()` 从 no-op 改为 logging.info（恢复 HTTP 请求日志）
13. [x] `api_server.py`：500 错误处理器改为日志记录完整 traceback，返回通用错误消息（不泄露原始异常）
14. [x] `tradingagent/shared/data/reader.py`：SharedSignalsReader 连接添加 `busy_timeout = 5000`
15. [x] `tradingagent/shared/data/reader.py`：TradingagentDataReader 添加 `_maybe_alert()` 死人手刹 — errors 每累积 10 条自动 WARNING 日志
16. [x] `collectors/rss/collector.py`：event_hash 从 64 位（`[:16]`）升级到 128 位（`[:32]`）
17. [x] `collectors/rss/gap_filler.py`：同上，event_hash 升级到 128 位
18. [x] `tradingagent/shared/data/shared_signals_api.py`：添加 DeprecationWarning — 标记为未使用的参考代码
19. [x] `reader.py`：`_get_capital_flow_cached` 添加注释说明其为未来本地采集器保留的参考代码

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
- [x] `capability_registry.json` 中的 Ashare 引用识别为元数据残留（symlink 在服务器端仍正常解析）
- [x] `/opt/investment/Ashare/` 退役目录待删除（TradingAgent 已完成 `a_share_simulated_trade_executor` 依赖迁移至 `tradingagent/Ashare/sim_executor.py`）

## 六、采集器架构

| 采集器 | 数据源 | 输出表 | 状态 |
|--------|--------|--------|------|
| Tushare | Tushare Pro（21 API） | market_bars_daily 等 | 已有（参考实现） |
| Binance | Binance REST API | market_bars_daily, market_bars_intraday | 新实现 |
| Polymarket | Gamma API + CLOB API | market_pm_markets, market_pm_prices | 新实现 |
| RSS | RSSCollector bridge（883 源） | market_events | 新实现 |

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
