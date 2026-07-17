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

SharedSignals 当前 local `main`、`origin/main` 与 GitHub `main` 均为：

```text
e9f06cad62b4e783dfca5e0fc0d09feee845bafb
```

tracked/index clean；既有 `.codegraphcontext/` 为 CodeGraph 占用的 untracked 目录，未修改、未暂存、
未删除。

已经进入 GitHub 的纠偏链：

1. `9627aa0`：冻结类似 Tushare 的产品边界、防漂移规则和核心文档；
2. `f026114`：加入 registry-driven generic provider runner；默认只生成安全计划，只有显式
   `--execute` 才允许调用 provider，并且不能从 CLI 覆盖 provider API、字段或预算；
3. `e9f06ca`：provider-native query 在省略/空 `fields` 时返回完整上游 payload；显式字段、
   filter、order、cursor、tenant policy 与 response budget 仍受 registry/query policy 约束，
   typed-v1 compatibility 路径不变。

`e9f06ca` 在目标主线 fresh readback 的相关回归为 `216 passed`；其独立 clean-overlay reviewer
结论为 PASS，P0/P1/P2=0。完整 provider-native payload 不包含 SQLite 的 `payload_json`、
`row_key`、receipt 等技术列。

这些结论只证明 local/GitHub 代码与文档层，不能代替生产发布、runtime 或真实租户调用。

## 正在独立验收的两个本地候选

### Canonical provider-row SQLite schema

- 目标：一个通用 `provider_dataset_rows` authority，而不是 114 张接口专用表；
- additive SQLite-only schema：14 列、复合主键、CHECK 与 4 个索引；
- 专用迁移只对显式指定的已存在数据库执行，`BEGIN IMMEDIATE` 单事务，DDL 与 postflight
  同事务，失败完整 rollback，重复执行幂等；
- 不 rename/copy/update/delete typed-v1 表或数据，不操作生产数据库；
- writer 自验为 `2287 passed`；当前必须在最新主线 clean overlay 重新验收，旧 base 结果不能复用。

### 114-dataset registry bulk compiler

- 目标：从现有 catalog/config 机械生成 provider-native registry，不逐接口写 Python；
- 普通 Tushare binding 统一 `requested_fields=[]`，让上游返回完整字段；旧 config `fields`
  只作历史 hint，不作为阻断或投影；
- 当前冻结结果为 113 个机械转换；唯一未自动转换的是 `rt_fut_min`，因为缺 collector config
  且存在额外 provider binding，保持 paused；
- 工具不得包含 API-specific 分支，不调用 provider，不改默认 registry/DB/cron/生产；
- writer focused 为 `163 passed`；当前必须在最新主线 clean overlay fresh review 后才可集成。

候选没有 fresh PASS、没有被精确吸收到 `main` 并完成 GitHub readback 前，均不得写成“已完成”。

## 生产现状（只读证据）

- **生产未改变**；下列事实来自本轮只读盘点。
- 生产 SharedSignals checkout 仍是旧提交 `ccff5c8`；本轮没有 deploy、restart、cron/env、DB
  或外部路由写入。
- 服务仍在旧 runtime 上运行；`/health` 可读，但目标 `/v1/catalog`、`/v1/query` 仍返回 404。
- 生产 SQLite 约 22 GB；`market_ingest_runs` 存在且仍有旧调度写入，canonical
  `provider_dataset_rows` 尚不存在。
- 当前没有与生产数据库同一时点的新鲜完整 rollback snapshot；旧 writer/cron 仍活跃，因此
  不能直接在该数据库上执行 migration 或切换 authority。
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

1. 完成 canonical schema 与 registry compiler 的 fresh review，P0/P1=0 后精确集成并同步 GitHub；
2. 在服务器创建与旧生产 DB、cron、端口隔离的 canary：用一个小 `trade_cal` 窗口完成
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
