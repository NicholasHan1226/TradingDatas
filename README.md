# SharedSignals

> 阅读顺序：[AGENTS.md](AGENTS.md) → [STATUS.md](STATUS.md) →
> [外部 Beta 设计规格](docs/superpowers/specs/2026-07-15-sharedsignals-external-data-platform-beta-design.md) →
> [Phase 1 实施计划](docs/superpowers/plans/2026-07-15-sharedsignals-phase1-registry-receipts-retirement.md)。

SharedSignals 是**独立外部多源金融数据平台**。它以 Tushare 为首个主要上游和能力基准，把行情、基本面、资金事实、参考数据、公告、新闻、研报、政策和未来客观舆情等数据统一采集、标准化、质检、入库，并通过稳定 API 提供给受邀外部账户和内部消费者。

它不是 TradingAgent 或 MarketGraph 的内部模块，也不是交易控制层。

## 产品边界

SharedSignals 做：

- provider-neutral dataset registry 与 provider adapter；
- canonical schema、校验、标准化、去重和质量控制；
- SQLite facts 与同事务的 SQLite ingest receipt；
- freshness、quality、lineage、degraded、data-through 和 runtime state；
- DB-first HTTP API/SDK，以及受邀账户的读取隔离、限流和审计。

SharedSignals 不做：opening gate、候选、预测、策略评分、alpha、资金决策、持仓、风控、下单、成交、执行回执或交易建议；不与 TradingAgent/MarketGraph 共享数据库、跨系统事务或业务 callback。

## 权威数据流

```text
Tushare / future providers
  → provider adapter
  → validation / normalization / deduplication
  → SQLite facts + transaction-scoped ingest receipt
  → provider-neutral dataset registry + metadata projection
  → fixed query service
  → GET /v1/catalog + POST /v1/query
  → invited external tenants / internal consumers
```

权威顺序：

1. registry 定义 dataset/schema/provider/entitlement/cadence/SLA/query policy；
2. SQLite facts + receipts 定义真实采集与写入结果；
3. registry、receipts 和读取时钟生成 API metadata；
4. JSON、日志、监控摘要和旧 endpoint 只作缓存或兼容材料。

HTTP 200、allowlist、配置存在、旧数据行或“114/114”不能替代逐 dataset 的运行事实。API 必须区分 `success`、`empty`、`unobserved`、`paused`、`failed`、`stale`。

## 固定 API 方向

- `GET /v1/catalog`：发现当前账户可见的 dataset、schema、查询能力、cadence、SLA、entitlement 和 runtime state。
- `POST /v1/query`：按 registry 白名单执行字段、过滤、排序、时间和 keyset cursor 查询。
- `/tushare` 与现有专用端点是 legacy compatibility surface；迁移后必须调用同一个 QueryService。
- **新增数据源不得新增公共 API 路由**。横向扩展通过 registry、adapter、storage mapping、receipt 和 metadata 完成。

以上 `/v1` 接口当前仍是已批准目标合同，不是已部署能力；以 [STATUS.md](STATUS.md) 的当前证据为准。

## Consumer contract handoff

- [V1 consumer data contract](docs/data_contract.md) 冻结 provider-neutral dataset ID、independent
  dataset schema version、request/response envelope、六种 runtime state 与 signed keyset cursor 语义。
- [Machine-readable contract fixture](tests/fixtures/sharedsignals_v1_query_contract.json) 只含 V1 public
  fields，提供一个 catalog row、一个 healthy query response 与一个 degraded query response；
  测试用受控 active registry、真实 SQLite writer/ingest receipt、CatalogService、QueryService 和
  SignedCursorCodec 重建完整结果并逐字段比对，JSON 不是手工自证。
- 消费者必须按每个 dataset 的 `freshness`、`quality`、`lineage`、receipt 和 reasons fail
  closed 或 down-weight；HTTP 200、非空 rows 或 global source flag 都不足以证明数据健康。
- fixture 和本地测试是 handoff evidence，不证明 local main、origin/GitHub、production checkout、
  production runtime、external route 或 real dataset 已改变。

## 首期 Beta 范围

- 首期只做中国境内市场和当前账户实际有权使用的 Tushare dataset。
- 预测市场、加密货币、港股和美股不进入首期激活目录或默认调度。
- SQLite 是首期权威存储；DuckDB 不在 Beta 关键读路径，保持停用直至独立设计验收。
- 公告、新闻、研报、政策、互动和客观舆情属于未来横向数据源，但继续复用固定 catalog/query API。
- 受邀外部账户 Beta 需要 tenant credential、dataset/field/lookback policy、rate/concurrency、quota、revocation 和 usage ledger；未实现前不得声称外部 Beta 已开放。

## 数据完整性

- 每个真实 SQLite 写事务必须把成功数据和 success receipt 同事务提交。
- rollback 后不能残留 success receipt；成功数据不能没有对应 receipt。
- legitimate empty、provider failure、permission denied、rate limit、validation failure、storage failure 和 resource budget 必须分别记录。
- reader/API 只读 SQLite，不现场调用 provider，不回退 CSV/NDJSON/Parquet/旧目录，也不创建缺失数据库。
- 新 dataset 的完成定义是：registry 可发现、adapter 可采、事实与 receipt 原子入库、API 可查、metadata 真实、限流/降级/回滚可验证。

## 防漂移开发方式

每个任务先冻结产品边界、权威层、接口、威胁模型、写域、验收和停止线，再 TDD 实现。候选冻结后 reviewer 不能临时扩大合同；合同外加固进入 backlog。连续出现结构性 P1 时回到架构裁决，不继续堆补丁。

详见 [AGENTS.md](AGENTS.md) 的 **Acceptance Freeze**。

## 本地验证

```bash
uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q
uv run --python 3.12 --with-requirements requirements.txt ruff check \
  tests/test_data_platform_docs.py tests/test_capability_coverage.py \
  tests/test_capability_scan.py tests/test_source_expansion_priority.py
git diff --check
```

Ruff 必须检查任务冻结的精确 Python 路径；不得用当前非零 legacy baseline 的
`ruff check .` 冒充绿色门禁。Phase 1 完整路径和已归因的 baseline 例外见实施计划
Task 12 Step 4。

测试通过只证明本地候选；GitHub、生产 checkout、runtime、外部 route、真实采集和回滚必须分别验证。

## 安全边界

- 不提交生产数据库、凭证、日志、缓存或运行证据。
- 未经 Nicholas 明确授权，不做 DB migration、生产 cron/systemd/nginx、真实邮件、外部写回或不可逆删除。
- 旧 opening gate、Green Gate 邮件、研究关系、交易式 blocking、旧调度和专用 endpoints 按“替代 → 迁移消费者 → deprecate → safe-delete”退役；不会继续扩展，也不会在依赖未知时直接删除。

## 仓库

<https://github.com/NicholasHan1226/SharedSignals.git>
