# SharedSignals 当前状态

> 先读 [AGENTS.md](AGENTS.md)。本文件只记录当前可执行状态、证据分层、阻塞和下一步；
> 旧阶段、事故和作废候选保留在
> [docs/status_history_2026-07.md](docs/status_history_2026-07.md) 与仓外 evidence 中，
> 不再混入当前判断。

最后更新：2026-07-17。

## 当前结论

- SharedSignals 的唯一批准定位是：面向受邀外部账户和内部消费者的**独立外部多源金融数据平台**，
  产品形态是**类似 Tushare 的多源金融数据服务**，内部合同保持 provider-neutral。
- Tushare 是已购买的现成上游。普通 Tushare dataset 只通过统一
  `api_name + params + fields -> fields/items` transport、registry/config、generic SQLite writer、
  receipt 和固定 query service 接入；禁止重新采集 Tushare 已提供的数据，也禁止按接口新增
  collector、业务表、scheduler branch、query branch 或公共 route。
- 未来自建新闻、公告、研报、政策、互动或客观舆情来源，只在 transport/auth/pagination
  确实不同时增加 provider-level adapter；仍进入同一个 provider-native 数据面。
- SharedSignals 不承载 opening gate、候选、预测、策略、资金决策、持仓、风险、订单、成交、
  执行回执或交易建议；这些由 TradingAgent、MarketGraph 或外部客户处理。
- 公共数据面固定为 `GET /v1/catalog` 与 `POST /v1/query`。新增 provider 或 dataset 不得新增
  公共路由；`/tushare` 和其它专用端点只属于迁移期兼容面。

## 本地与 GitHub 已验证

最近完成 local `main`、`origin/main` 与 GitHub `main` 三方 readback 的代码 checkpoint 为：

```text
53e2b96b24f89185abe88d294f6528152b472cae
```

本文件后续的 doc-only 状态提交会自然推进 HEAD；精确当前 HEAD 必须用 `git rev-parse HEAD` 与
`git ls-remote origin refs/heads/main` fresh readback，不能把本文件中的 checkpoint 当作永久 HEAD。
tracked/index clean；既有 `.codegraphcontext/` 为 CodeGraph 占用的 untracked 目录，未修改、
未暂存、未删除。

已经进入 GitHub 的纠偏链：

1. `9627aa0`：冻结类似 Tushare 的产品边界、防漂移规则和核心文档；
2. `f026114`：加入 registry-driven generic provider runner；默认只生成安全计划，只有显式
   `--execute` 才允许调用 provider，并且不能从 CLI 覆盖 provider API、字段或预算；
3. `e9f06ca`：provider-native query 在省略/空 `fields` 时返回完整上游 payload；显式字段、
   filter、order、cursor、tenant policy 与 response budget 仍受 registry/query policy 约束，
   typed-v1 compatibility 路径不变；
4. `5e6b382`：重置 `STATUS.md`，把已推送代码、生产旧 runtime 和待验候选重新分层；
5. `5e1fe19`：加入离线、确定性的 Tushare registry bulk compiler；它不调用 provider、不改默认
   registry，已 fresh PASS 证明 114 个现有 dataset 中 113 个可机械转为 provider-native，普通
   Tushare binding 统一 `requested_fields=[]`，唯一 `rt_fut_min` 保持 paused；
6. `aaeafec`：把双注册表迁移写成强制门禁，禁止用机械生成结果直接覆盖 legacy 默认注册表，
   并禁止 HTTP/request/tenant/普通 CLI 选择目标注册表；
7. `88d66a5`：纠正直接覆盖默认 registry 的旧状态表述，记录双注册表迁移；
8. `9ade8c0`：把 legacy cron、基础设施和生成型 capability 文档明确标为历史兼容面，禁止把它们
   当成 provider-native onboarding 或生产就绪证明；
9. `6e98b52`：记录 canonical schema 的 symlink 路径阻塞和作废证据；
10. `5ee3cf9`：加入 provider-native 通用事实表与专用原子迁移，fresh reviewer P0/P1=0，主仓
    Python 3.12 全量 `2330 passed`，local/origin/GitHub readback 一致；
11. `6c7ded4`：冻结 TradingAgent 的 V1 consumer handoff：catalog 暴露原生正整数
    `schema_major`，same-as-of 由 verified SQLite snapshot 与 receipt watermark 共同定义，
    三份合同统一声明当前停止线。fresh reviewer P0/P1=0、全量 `2331 passed`，
    local/origin/GitHub readback 一致；
12. `53e2b96`：加入独立 provider-native target registry，并把 V1/generic runner 与 legacy
    registry/query 彻底分离。第三轮 fresh reviewer P0/P1=0、focused `493 passed`、全量
    `2341 passed`；local/origin/GitHub readback 一致。

`e9f06ca` 在目标主线 fresh readback 的相关回归为 `216 passed`；其独立 clean-overlay reviewer
结论为 PASS，P0/P1/P2=0。完整 provider-native payload 不包含 SQLite 的 `payload_json`、
`row_key`、receipt 等技术列。

这些结论只证明 local/GitHub 代码与文档层，不能代替生产发布、runtime 或真实租户调用。

## 当前实现与本地候选

### Canonical provider-row SQLite schema

- 已在 `5ee3cf9` 进入 local/origin/GitHub `main`：一个通用 `provider_dataset_rows` authority，
  不是 114 张接口专用表；
- additive SQLite-only schema：14 列、复合主键、CHECK 与 4 个索引；
- 专用迁移只对显式指定的已存在数据库执行，`BEGIN IMMEDIATE` 单事务，DDL 与 postflight
  同事务，失败完整 rollback，重复执行幂等；
- 不 rename/copy/update/delete typed-v1 表或数据，不操作生产数据库；
- 最终 exact8 fresh review 覆盖 leaf/ancestor symlink、non-regular file、connect/BEGIN/COMMIT
  前后路径身份漂移、rollback、0-byte existing SQLite 与 no-follow；定向 `82 passed`、独立 race
  `7 passed`、全量 `2330 passed`，Ruff/compile/diff-check 全绿；
- 这只完成代码与 GitHub 层。生产约 22 GB 数据库尚未迁移，仍需隔离 canary、备份/回退和
  fresh production preflight；不得把 `5ee3cf9` 写成生产 schema 已存在。

### 双注册表迁移

- bulk compiler 已进入 GitHub；离线重复编译结果确定一致：114 个 dataset、113 个
  provider-native、1 个 unresolved typed；普通 Tushare binding 的 `requested_fields=[]`，不会把旧
  config `fields` 误当作采集投影；
- **直接把生成结果写入默认 `config/dataset_registry.yaml` 的候选已结构性 FAIL 并作废**：在隔离
  回归中为 `476 passed / 48 failed / 3 errors`。根因是 `paused` 只控制调度，旧 `sync_daily`、
  receipt projector、catalog/query fixtures 仍会读取默认合同并被污染；该候选未 commit、未 push、
  未进入 main/GitHub/生产；
- 正确方案是保留默认 registry 作为 legacy compatibility，另行提交确定性生成的
  `config/provider_native_dataset_registry.yaml` 作为 generic target。仅受信进程配置
  `SHAREDSIGNALS_DATASET_REGISTRY_PATH` 可选择 target；请求、tenant、dataset 参数与普通 CLI
  均不能切换；
- exact12 第三轮 fresh review 已 PASS（P0/P1=0）并在 `53e2b96` 进入 GitHub。target env 下
  V1 catalog/query 与 generic runner 读取 target；`/tushare`、canonical stock-master、
  `reader.get_tushare` 与 `reader.get_reference` 始终读取 default legacy registry/query；
- default registry SHA 保持 `d6f58ff...`；target 与 compiler 逐字节一致，114 个 dataset =
  113 provider-native + 1 unresolved typed，当前全 paused、active entitlement 为 0，
  native `requested_fields` 全为空；请求、tenant 与普通 CLI 均不能选择 registry；
- 这只完成代码/GitHub 层。真实 entitlement、backfill、receipt、server runtime 与 consumer parity
  尚未验证，默认 registry 切换继续受 backfill/parity/consumer/no-use/rollback 门禁约束。

### TradingAgent consumer handoff contract

- TradingAgent 已明确只消费 `GET /v1/catalog` 与 `POST /v1/query`，不直读 SQLite、不使用
  `/tushare`、`/source_status`、provider 专用 route 或 localhost fallback；
- exact8 r2 已由 fresh reviewer 判定 PASS（P0/P1=0）并在 `6c7ded4` 进入 GitHub；
  `schema_major`、same-as-of/receipt watermark 实证、healthy/stale fixture 与 2331 项全量回归
  均绿，三份文档的核心 truth statement 逐字一致；
- 该提交没有新增 TA 业务表、因子、交易语义、provider 分支或公共 route。generic target registry、
  真实 backfill、server canary、认证和真实 query readback 仍未完成，因此状态继续固定为
  **TradingAgent 当前不可接入**。

候选没有 fresh PASS、没有被精确吸收到 `main` 并完成 GitHub readback 前，均不得写成“已完成”。

## 生产现状（2026-07-17 12:50 CST fresh 只读证据）

- **生产未改变**；下列事实来自本轮只读盘点。
- 生产 SharedSignals checkout clean，仍是旧提交 `ccff5c8`；本轮没有 deploy、restart、cron/env、DB
  或外部路由写入。
- 服务仍在旧 runtime 上运行；`/health` 可读，但目标 `/v1/catalog`、`/v1/query` 仍返回 404。
- 生产 SQLite 为 22,193,909,760 bytes；`market_ingest_runs` 存在且旧调度仍活跃，40 秒只读
  对比确认 DB 大小/mtime 和 collector/watchdog 日志继续变化，canonical
  `provider_dataset_rows` 尚不存在。
- 当前没有与生产数据库同一时点的新鲜完整 rollback snapshot；现有 predata/backup 明显早于
  live DB，旧 writer/cron 仍活跃，因此
  不能直接在该数据库上执行 migration 或切换 authority。
- `127.0.0.1:18082` 空闲，服务器内存/磁盘/Python 3.12 与独立目录权限满足隔离 canary。
  双注册表代码门禁现已在 `53e2b96` 完成；正式创建 canary 前仍须针对该精确提交重新执行
  safe-release preflight，并确认独立 checkout/new SQLite/两把协作锁/无 systemd-cron-nginx。
- 只读真实上游 smoke 已用现有 Tushare transport 调用 `trade_cal`：SSE、20260715 返回
  `success`、1 行。这证明已购买上游和统一调用协议可用；不证明 generic SQLite/API 纵向切片
  已发布。
- 生产仍是 NO-GO。HTTP 200、配置存在、旧表有数据或“114/114”都不能代替逐 dataset 的
  receipt、freshness、quality、lineage 和真实 query 证据。

## 权威层与验收分层

权威顺序固定为：

```text
provider-neutral registry
-> provider-level transport adapter
-> provider-native SQLite rows + transaction-scoped SQLite ingest receipt
-> read-clock freshness/quality/lineage/degraded projection
-> GET /v1/catalog + POST /v1/query
-> invited tenant
```

每次汇报必须分开：

1. local worktree PASS；
2. local main；
3. origin/GitHub；
4. production checkout；
5. production runtime；
6. external route；
7. real dataset evidence（provider receipt 与 API response）。

任一层通过都不能替代后续层。

## 退役边界

旧 typed mapping、opening gate、Green Gate 邮件、交易式 blocking、研究关系、旧专用 endpoint、
旧 cron/patrol/heal、DuckDB critical path 和已作废 worktree 都不是目标架构，但当前不能为了
“清洁”直接删除。固定顺序为：

```text
generic replacement PASS
-> migrate consumers
-> deprecate
-> no-use observation
-> fresh rollback evidence
-> safe-delete
```

禁止删除或覆盖生产 DB、数据、Journal、ledger、history、evidence、未知消费者仍使用的入口或
尚未证明可重建的 worktree。

## 下一步

1. canonical schema、TA consumer handoff 与双注册表 runtime 已进入 GitHub；
2. 对 `53e2b96` 做 fresh safe-release preflight 后，在服务器创建与旧生产 DB、cron、端口隔离
   的 canary：用一个小 `trade_cal` 窗口完成
   `Tushare -> generic SQLite row+receipt -> /v1/catalog -> /v1/query`；
3. canary 通过后批量编译 113 个境内 dataset，做 entitlement probe、cadence、限流、增量 backfill
   与 `success/empty/unobserved/paused/failed/stale` 运行矩阵；
4. 再完成受邀账户 credential、scope、rate/concurrency、quota、revocation、usage ledger 与网关；
5. 最后做 fresh production preflight、完整 rollback、旧 writer quiesce、additive migration、
   code/runtime readback 和分批启用；
6. 替代链稳定并完成 no-use 观察后，才退役旧代码、文档、cron 和 worktree。

## 本地验证入口

```bash
uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q
uv run --python 3.12 --with-requirements requirements.txt ruff check <本次精确 Python 路径>
uv run --python 3.12 python -m compileall -q <本次精确 Python 路径>
git diff --check
```

完整测试、reviewer PASS、manifest 和哈希只证明对应候选字节；candidate 变化或 base 变化后必须
重新生成 fresh evidence，旧 PASS/JUnit/哈希不得复用。
