# SharedSignals

> 阅读顺序：[AGENTS.md](AGENTS.md) → [ROADMAP.md](ROADMAP.md) →
> [内部优先 ADR](docs/adr/ADR-0008-development-priority.md) → [STATUS.md](STATUS.md) →
> [内部 V1 服务计划](docs/superpowers/plans/2026-07-19-sharedsignals-internal-v1-service.md)。
> 外部 Beta 规格是内部服务稳定后的后续阶段，不是当前发布入口。

SharedSignals 是**独立外部多源金融数据平台**。它以 Tushare 为首个主要上游和能力基准，把行情、基本面、资金事实、参考数据、公告、新闻、研报、政策和未来客观舆情等数据统一采集、技术校验、质检、入库；开发与发布顺序先通过稳定 API 服务内部消费者，内部运行稳定后再开放受邀外部账户 Beta。

它不是 TradingAgent 或 MarketGraph 的内部模块，也不是交易控制层。

## 产品形态与 Tushare 复用

SharedSignals 对外提供的是**类似 Tushare 的多源金融数据服务**：客户使用稳定的 catalog/query/SDK 获取数据，但不直接接触 Tushare 或其它上游。Tushare 是已购买的现成上游数据能力，SharedSignals 直接复用其统一 `api_name + params + fields -> fields/items` 协议，不重新生产或爬取 Tushare 已提供的数据。

普通 Tushare 接口不得逐个开发 collector、业务表、查询器或公共路由。接口清单、参数模板、字段发现、频率、权限和资源预算由 registry/config 批量声明；同一个 generic Tushare adapter 负责调用，同一个 provider-row SQLite/receipt 管线负责持久化，同一个 `/v1/catalog`、`/v1/query` 数据面负责对外服务。未来自建的新闻、公告、舆情或其它来源只在 transport/auth/pagination 真正不同时增加 provider-level adapter，仍复用相同存储、元数据和公共 API。

provider-native 查询省略 `fields` 或传空数组时返回每行完整的上游 payload，供 TradingAgent 或外部客户自行加工；显式字段、filter 和 order 仍受 registry allowlist 约束，技术存储列永不对外暴露。

SharedSignals 不把上游事实加工成预测、策略、候选、资金决策、持仓、风险或交易建议；这些属于 TradingAgent、MarketGraph 或外部客户自己的系统。

## 产品边界

SharedSignals 做：

- provider-neutral dataset registry 与 provider-level transport adapter；
- provider-native 字段无损入库、技术校验、去重和质量标注；
- SQLite facts 与同事务的 SQLite ingest receipt；
- freshness、quality、lineage、degraded、data-through 和 runtime state；
- DB-first HTTP API/SDK，以及受邀账户的读取隔离、限流和审计。

SharedSignals 不做：opening gate、候选、预测、策略评分、alpha、资金决策、持仓、风控、下单、成交、执行回执或交易建议；不与 TradingAgent/MarketGraph 共享数据库、跨系统事务或业务 callback。

## 权威数据流

```text
Tushare / future providers
  → provider adapter
  → lossless provider-native rows / technical validation / deduplication
  → generic SQLite dataset rows + transaction-scoped ingest receipt
  → provider-neutral dataset registry + metadata projection
  → fixed query service
  → GET /v1/catalog + POST /v1/query
  → internal consumers
  → invited external tenants (after the internal stop line)
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
- **新增数据源不得新增公共 API 路由**。普通 Tushare dataset 只改 registry/config，复用同一 generic ingest、receipt 和 query 管线；只有 transport 协议变化才增加 provider-level adapter。

内部 provider-native 运行面固定为 `127.0.0.1:18082`、独立 SQLite 和五个独立 systemd
units（API、采集 service/timer、probe service/timer）；新库固定为
`/opt/investment-data/sharedsignals-v1/read_model/provider_native.sqlite`。API、collector、probe
分别只读取各自的 credential `EnvironmentFile`，不得互相加载。旧 `127.0.0.1:8082` 与旧数据库
属于受保护 legacy 运行面，且 `REAL_TRADING_ENABLED=false` 必须保持不变。以上是内部 V1 候选合同；
是否已部署、已采集和可供内部消费者接入，只认 [STATUS.md](STATUS.md) 的 fresh 生产证据，不能从
本段设计文字推断。

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
- legitimate empty、provider failure、permission denied、rate limit、硬 admission failure、storage failure 和 resource budget 必须分别记录；provider 字段/schema/type mismatch 或未知字段原样入库，只标记 quality/degraded。
- credential/provider-token 防泄漏优先于无损入库；命中既有敏感信息合同的响应按损坏安全 envelope fail closed，不能进入 facts、日志或 API。
- reader/API 只读 SQLite，不现场调用 provider，不回退 CSV/NDJSON/Parquet/旧目录，也不创建缺失数据库。
- 新普通 Tushare dataset 的完成定义是：只改 registry/config 即可发现、采集、事实与 receipt 原子入库、API 查询并返回真实 metadata；若必须新增 dataset-specific Python 或 route，架构验收直接失败。
- 现有 SQLite 增加 generic fact table 必须使用 [provider-native 专用原子迁移](docs/provider_dataset_rows_migration.md)，不得走会吞 DDL 错误的 legacy 通用迁移路径。

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

## Registry-driven provider runner

`tools/collect_provider_dataset.py` 只接受 canonical `dataset_id` 与 registry
模板所需的 request-window；provider API、静态参数、字段和预算不能从 CLI
覆盖。默认只生成无敏感值的 plan，不调用 provider，也不打开或创建数据库：

```bash
python3 tools/collect_provider_dataset.py \
  --db-path /path/to/already-migrated.sqlite \
  --dataset-id cn.example.dataset \
  --request-window-json '{"start_date":"20260701","end_date":"20260717"}'
```

只有显式增加 `--execute` 才会调用 provider 并写入已存在、已完成独立迁移验收的
generic SQLite authority。request-window 也可通过 `--request-window-file` 提供；
`--attempt-id` 与 `--started-at` 可选。退出码固定为 `0=success/plan`、
`2=validation`、`3=empty`、`4=failed`。输出不包含数据库路径、window 值、
provider token、provider 错误原文或 receipt ID。

双注册表迁移期，未设置进程环境变量时继续使用 legacy compatibility registry。
受信任进程只能把 `SHAREDSIGNALS_DATASET_REGISTRY_PATH` 设置为当前仓库内
`config/provider_native_dataset_registry.yaml` 的绝对路径，才能让 generic runner
和 V1 data plane 使用 target registry；HTTP request、tenant、dataset 和普通 CLI
都不能选择注册表路径。迁移期 `/tushare` 与 canonical
`/reference?table=stock_master` 的 HTTP 和 in-process reader compatibility surface
始终由 default registry 翻译，并使用与该 default registry 绑定的独立 legacy
QueryService；target 进程选择不能改变其表或查询合同。

## 安全边界

- 不提交生产数据库、凭证、日志、缓存或运行证据。
- 未经 Nicholas 明确授权，不做 DB migration、生产 cron/systemd/nginx、真实邮件、外部写回或不可逆删除。
- 旧 opening gate、Green Gate 邮件、研究关系、交易式 blocking、旧调度和专用 endpoints 按“替代 → 迁移消费者 → deprecate → safe-delete”退役；不会继续扩展，也不会在依赖未知时直接删除。

## 仓库

<https://github.com/NicholasHan1226/SharedSignals.git>
