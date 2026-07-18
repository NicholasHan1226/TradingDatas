# SharedSignals 当前状态

> 先读 [AGENTS.md](AGENTS.md)。本文件只记录当前可执行状态、证据分层、阻塞和下一步；
> 旧阶段、事故和作废候选保留在
> [docs/status_history_2026-07.md](docs/status_history_2026-07.md) 与仓外 evidence 中，
> 不再混入当前判断。

最后更新：2026-07-18。

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
fae8f7c01d8c41c088ea20e6d2e11dc0999ba1ad
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
13. `3b18eee`：同步双注册表完成后的状态文档；local/origin/GitHub readback 一致；
14. `58face6`：加入版本化 Tushare upstream contract bundle、严格离线 compiler 与通用
    response completeness 合同。目标 registry 只接受已解析合同；未提供合同的 dataset
    保持 typed `unresolved`，不会被伪装成可采可查；
15. `fae8f7c`：固定 zero-code 端到端测试的 storage/receipt/API 同一时钟，消除
    日期推进导致的基线误报；生产 freshness 判定未修改。

`58face6` + `fae8f7c` 在最终主线字节上 fresh 全量为 `2384 passed`，Ruff、
Python 3.12 compile、YAML、文档链接、确定性 compiler 和 `git diff --check` 全绿；
local/origin/live GitHub 三方 readback 为 `fae8f7c01d8c41c088ea20e6d2e11dc0999ba1ad`。

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

- bulk compiler 已进入 GitHub；新 contract bundle 完整定义了首个
  `cn.market.trade_calendar / trade_cal` 合同。离线重复编译结果确定一致：legacy
  catalog 共 114 个 dataset，当前仅 1 个 resolved，其余 113 个因
  `missing_upstream_contract` 保持 typed `unresolved` 且不进入 target；
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
- default registry SHA 保持 `d6f58ff...`；当前 target registry SHA 为 `77db9af...`，与
  compiler 逐字节一致，严格只包含已解析的 `trade_cal` 一项；该项当前
  `paused`，entitlement 仍为 `unknown`，请求、tenant 与普通 CLI 均不能选择 registry；
- `trade_cal` 已在 2026-07-18 的全新隔离 server canary 中完成一次真实 entitlement、受限
  backfill、SQLite fact/receipt 与统一 API readback；该证据只绑定 exact `4088a2d` 和独立
  canary 数据库。生产 runtime、完整首批 consumer 数据包与 consumer parity 仍未验证，默认
  registry 切换继续受 backfill/parity/consumer/no-use/rollback 门禁约束。

### Provider contract bundle 与 `trade_cal` 首个纵向切片

- upstream contract bundle 是 provider-native 字段、时间窗口、完整性、资源预算和 provenance
  的唯一编译输入；缺失、无效、重复或冲突均 fail closed；
- `trade_cal` 申明的 provider-native 字段为
  `exchange/cal_date/is_open/pretrade_date`，主键与 completeness 要求确保请求窗口内
  每个日历日恰好一行；缺失、重复、越界、错误 exchange 或日期格式均在 SQLite
  writer 前拒绝，只记 `validation_failed` receipt；
- 生产 Python 不包含 `trade_cal` 或 dataset-id 特殊分支；新 dataset 仍通过同一
  bundle/compiler/registry/generic ingest/query 管线接入；
- 当前证据包含 local/GitHub 代码层 PASS，以及一个受限 `trade_cal` 窗口的真实隔离
  server canary PASS；它不证明生产、完整 Tushare dataset 覆盖、受邀账户网关或外部 Beta
  已完成。

### TradingAgent consumer handoff contract

- TradingAgent 已明确只消费 `GET /v1/catalog` 与 `POST /v1/query`，不直读 SQLite、不使用
  `/tushare`、`/source_status`、provider 专用 route 或 localhost fallback；
- exact8 r2 已由 fresh reviewer 判定 PASS（P0/P1=0）并在 `6c7ded4` 进入 GitHub；
  `schema_major`、same-as-of/receipt watermark 实证、healthy/stale fixture 与 2331 项全量回归
  均绿，三份文档的核心 truth statement 逐字一致；
- 该提交没有新增 TA 业务表、因子、交易语义、provider 分支或公共 route。虽然
  `trade_cal` 的真实 generic backfill/server canary/query readback 已完成，TA 首批要求的
  `stock_basic`、`daily`、行业宽度 dataset、冻结 catalog、只读 base URL 与认证接入仍未完成，
  因此状态继续固定为 **TradingAgent 当前不可接入**。

候选没有 fresh PASS、没有被精确吸收到 `main` 并完成 GitHub readback 前，均不得写成“已完成”。

### 隔离服务器 canary（2026-07-17 13:25–14:00 CST）

- canary 位于 `/opt/investment/canaries/sharedsignals/20260717T1325-3b18eee`，使用 detached
  `3b18eee`、独立 SQLite、独立两把锁和 `127.0.0.1:18082`；没有创建 systemd、cron、nginx
  或外部路由，也没有触碰生产数据库；
- additive base/provider migration 在全新 canary SQLite 上成功，`provider_dataset_rows` 为
  14 列、5 个索引；缺失 DB 的负例先行失败且未隐式创建数据库；
- 真实采集前，`/v1/catalog` 与 `/v1/query` 正确返回
  `unobserved/degraded`、空数据和 null receipt/data-through/observed-at；相同请求除
  `request_id` 外可复现，伪装外部来源且无凭证时返回 401；
- 两次 `trade_cal` generic runner 都 fail closed：第一次是 30 秒 transport timeout；第二次
  收到 provider code 0 后因默认敏感扫描预算不足而拒绝。canary SQLite 最终为 0 facts、2 条
  failed receipt，API 投影为 `failed/degraded`，没有伪装 success/empty；
- 独立 transport probe 证明上游仍可用：一次 HTTP 200 返回 13,162 行、4 个真实字段
  `exchange/cal_date/is_open/pretrade_date`。这同时暴露当前 target registry 的真实 P1：
  `cn.market.trade_calendar` 仍继承旧 `market_factors.v1` 字段合同
  `factor_hash/event_time/value/...`，不是 provider-native field manifest；空窗口还超过统一
  `max_rows_per_attempt=10000`。因此当前生成的 113 个 native 条目只能证明机械 storage/runtime
  转换，不能证明其字段、窗口和资源预算已经达到可采可查合同；
- canary 已安全停止，`18082` 不再监听；生产 `8082` 继续运行，生产 checkout 仍为 clean
  `ccff5c8`，生产数据库仍没有 `provider_dataset_rows`，systemd/cron 中没有 canary 引用。

结论：旧 canary 正确阻止了错误 schema 进入生产。通用、版本化的
provider field/window manifest 与 compiler 修正已在 `58face6` 进入 GitHub；旧 canary
证据没有被复用；下列 2026-07-18 canary 已从后续精确 GitHub 主线独立重建。

### 隔离服务器 canary（2026-07-18 12:30–12:47 CST）

- canary 位于 `/opt/investment/canaries/sharedsignals/20260718T123044-4088a2d`，detached
  checkout 精确为 GitHub `4088a2de49ecfd45aff7c910d00d58cd20a238c5`；唯一 tracked overlay
  是 target registry 的 `entitlement_state: unknown -> active` 与
  `activation_state: paused -> active` 两行。原 registry SHA 为 `77db9af...`，canary registry
  SHA 为 `86b88d4...`；没有 dataset 专用 Python、route 或生产配置改动；
- 使用全新独立 SQLite、独立两把锁与 `127.0.0.1:18082`。base/provider migration 成功；
  no-write plan 明确 `will_call_provider=false`、`will_write_database=false`，且计划前后数据库
  inode/size/mtime 不变；
- 真实采集前，`GET /v1/catalog` 可发现唯一 dataset，`POST /v1/query` 返回 0 行及
  `unobserved/degraded`，`receipt_id/data_through/observed_at` 均为 null，证明没有从生产
  SQLite、legacy 表、文件或 provider live fallback 借数据；
- 随后只执行一次 2026-07-13 至 2026-07-18 的真实 Tushare `trade_cal` 调用。结果为 6 行
  provider-native facts 与 1 条同事务 `success` receipt，`returned/validated/inserted/committed`
  均为 6，stderr 为空；receipt 为
  `receipt:4c79cdfb2caf83cc16154487a691f01679307360455f1f07c429337e88b9810b`；
- 采集后 catalog/query 返回 6 行真实字段
  `exchange/cal_date/is_open/pretrade_date`，runtime/API 状态为
  `success/ready/fresh/valid/complete`，lineage authority 为 `sqlite_ingest_receipts`，未暴露
  `payload_json/row_key/receipt_id` 等技术列；两次相同 `as_of` 查询除 `request_id` 外一致；
- 两路 fresh 独立只读验收均为 PASS，`P0/P1/P2=0/0/0`。24 份 evidence 保留在 canary
  目录，manifest SHA 为
  `4ccba06186a03c63774f5360443046c8d74024e96c29b4077ffc79278f5a6482`，23 个受管文件全部
  通过 SHA-256 校验，敏感值/private-key 扫描为 0；
- canary 已停止：PID/18082/open files/systemd/cron/nginx 引用均为 0。生产 checkout 仍是 clean
  `ccff5c8`，生产 API 仍只监听 `127.0.0.1:8082`；生产与 canary SQLite 位于不同设备和
  inode，生产数据库 inode/owner/mode 未改变。

结论：首个 `trade_cal` provider-to-API 纵向切片已在隔离 canary 中真实通过。它只证明该
dataset 和该受限窗口，不等于生产发布、TA 可接入、其余 113 个 dataset 可用或外部 Beta 开放。

## 生产现状（2026-07-18 12:47 CST fresh 只读证据）

- **生产未改变**；下列事实来自本轮只读盘点。
- 生产 SharedSignals checkout clean，仍是旧提交 `ccff5c8`；本轮没有 deploy、restart、cron/env、DB
  或外部路由写入。
- 服务仍在旧 runtime 上运行；`/health` 返回 200，但目标 `/v1/catalog`、`/v1/query` fresh
  readback 仍为 404。
- 生产 SQLite 当前为 23,048,323,072 bytes，inode `1048617`、mode `0644`、uid/gid
  `1000/1000`；审计窗口内旧 writer 仍使 size/mtime 正常变化。canary 使用另一设备上的
  inode `1329393` 独立 SQLite，没有替换或链接生产数据库；生产 canonical
  `provider_dataset_rows` 仍未被本轮创建或迁移。
- 当前没有与生产数据库同一时点的新鲜完整 rollback snapshot；现有 predata/backup 明显早于
  live DB，旧 writer/cron 仍活跃，因此
  不能直接在该数据库上执行 migration 或切换 authority。
- `127.0.0.1:18082` 已在 canary 停止后恢复为空闲；没有 canary systemd、cron 或 nginx
  引用。隔离 canary 证明已购买上游和统一调用协议可用，并证明 `trade_cal` generic
  SQLite/API 纵向切片可运行；生产代码和 runtime 仍未发布。
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

1. canonical schema、TA consumer handoff、双注册表 runtime 与首个 upstream contract bundle 已进入
   GitHub；当前 target 只有 `trade_cal` 一项，其余 113 项保持明确 unresolved；
2. 2026-07-18 隔离 canary 已用受限 `trade_cal` 窗口完成
   `Tushare -> generic SQLite row+receipt -> /v1/catalog -> /v1/query`，并经两路 fresh reviewer
   证明 catalog 字段与真实 provider payload 一致；
3. 现在按同一 contract bundle 增加 `stock_basic`、`daily` 和经批准的
   行业宽度数据合同，再逐批对其余境内 dataset 做 entitlement probe、cadence、限流、
   增量 backfill 与 `success/empty/unobserved/paused/failed/stale` 运行矩阵；
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
