# SharedSignals 当前状态

> 先读 [AGENTS.md](AGENTS.md)。本文件只记录当前可执行状态、证据分层、阻塞和下一步；
> 旧阶段、事故和作废候选保留在
> [docs/status_history_2026-07.md](docs/status_history_2026-07.md) 与仓外 evidence 中，
> 不再混入当前判断。

最后更新：2026-07-19。

## 当前结论

- SharedSignals 的唯一批准定位是：面向受邀外部账户和内部消费者的**独立外部多源金融数据平台**，
  产品形态是**类似 Tushare 的多源金融数据服务**，内部合同保持 provider-neutral。
- 当前开发和发布顺序是 **provider-native → 内部服务 → 内部生产稳定 → 受邀外部 Beta**。
  外部网关、租户治理和更多 dataset 不能延误内部 `GET /v1/catalog`、`POST /v1/query`
  的真实服务停止线。
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
685f3d7599d6b0238ba9f9928af2844635df3403
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
    日期推进导致的基线误报；生产 freshness 判定未修改；
16. `4088a2d` + `4d3da59`：记录并复核 `trade_cal` 的全新隔离 server canary；真实
    `Tushare -> provider-native SQLite fact+receipt -> catalog/query` 纵向切片通过，canary 已停止，
    生产 checkout、数据库、服务和定时任务未改变；
17. `5964cc9` 至 `630211e`：把 provider response completeness、通用 ingest/storage、
    Tushare transport 字段省略语义，以及 `stock_basic`、`daily` 的 provider-native 合同接入同一
    bundle/compiler/registry/generic pipeline；没有新增 dataset 专用 collector、表或公共 route。
18. `a8f9258`：记录 `stock_basic`、`daily` provider 合同和受限服务器证据；
19. `0d0f1ad`：按受信 registry binding 的行数/字段/字节合同计算敏感扫描预算，真实
    `stock_basic`、`daily` 批量响应不再误触统一默认节点上限；
20. `50ac13f` + `98a9ea3`：把 internal-first 路线写入 ROADMAP 与 ADR，外部 Beta 后置；
21. `0be6f83`：普通 Tushare binding 按 reviewed upstream contract 发送字段清单；
22. `7f5e20a -> 43af5c2 -> 976ad6b -> 2468f80`：加入内部 V1 的 activation、通用
    scheduler/probe、隔离 runtime/release control 与原子 store 初始化；截至 2026-07-19
    16:48 CST，`2468f80` 已完成 local/origin/live GitHub 三方 readback。
23. `e49d059`：严格 probe 改为比较 catalog/query 的语义时间证据，同时继续精确绑定 receipt，
    fresh reviewer P0/P1/P2=0、定向 54 与全量 2565 项通过；已发布到隔离内部 lane 并完成三
    dataset 严格 probe。
24. `685f3d7`：QuickSync Tushare-compatible transport 只允许 canonical HTTPS endpoint，使用
    系统 CA、证书/hostname 校验并暂时双向 pin TLS 1.3；scheduler 在 credential 进入 collector
    前执行同一目的地门禁，禁止 HTTP fallback。两路 fresh reviewer 均无 P0/P1，定向 495、
    全量 2574 项通过，local/origin/GitHub 与 production release 均已 readback。

`685f3d7` 是当前 provider-native 内部 V1 代码与 production runtime 的共同 checkpoint。
它已经包含三个首批 dataset 的通用 transport、provider-native facts/receipts、固定 catalog/query
数据面、activation、scheduler/probe 和隔离发布控制。Authenticated API、现有 facts/receipts、
严格 probe 与真实 TLS 1.3 handshake 已 fresh 验证；采集/probe timers 仍因上游 token 轮换门禁
保持 disabled，因此尚不能写成持续采集闭环完成。后续 doc-only 状态提交会自然推进仓库 HEAD，
代码 checkpoint、生产 release 与运行状态必须继续分层说明。

### 内部 V1 API lane 已发布，持续采集尚未启用

当前 production release 为 `685f3d7`。线性代码链在内部 V1 activation、registry-driven
scheduler/strict HTTP probe、loopback-only runtime/release control 和原子 store 初始化之上，
增加 probe 语义时间比较与 QuickSync TLS 1.3/canonical endpoint 门禁。运行面固定
`127.0.0.1:18082`、
`/opt/investment-data/sharedsignals-v1/read_model/provider_native.sqlite`、
`GET /v1/catalog` 与 `POST /v1/query`；首批仅
`cn.market.trade_calendar`、`cn.equity.security_master`、`cn.equity.daily` 三个 dataset，五个
新 units 仅属于该独立 lane。

新 API service 已 active/enabled，认证 catalog/query、strict probe、三 dataset SQLite
facts/receipts、same-snapshot 可复现与 cursor continuation 均通过。legacy
`127.0.0.1:8082` 与约 23 GB legacy SQLite 保持原 device/inode/path，外部 ingress 与
`REAL_TRADING_ENABLED=false` 未改变。Collection/probe timers 仍 disabled；上游旧 token 曾经由
HTTP 用于手动 bootstrap，必须先吊销并轮换，随后以 canonical HTTPS 运行一次受控 collector
oneshot，才允许启用 timers。不得用当前健康 API 或历史 facts 代替持续采集停止线。

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
- 内部 V1 不迁移、复制或改写 legacy 约 22 GB SQLite；它在独立新路径从 canonical schema
  bootstrap 一个 fresh store。legacy 数据库继续受 dev/inode/bytes/owner/mode 守恒保护。

### 双注册表迁移

- bulk compiler 已进入 GitHub；contract bundle 当前完整定义
  `cn.market.trade_calendar / trade_cal`、`cn.reference.security_master / stock_basic` 与
  `cn.market.daily / daily` 三个合同。离线重复编译结果确定一致：legacy catalog 共 114 个
  dataset，当前 3 个 resolved，其余 111 个因
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
- default registry SHA 保持不变；provider-native target 严格只包含上述三个已解析 dataset。
  内部 V1 发布候选用独立 activation manifest 决定 active+entitled 集合，并由 compiler 逐字节
  生成 target registry；请求、tenant 与普通 CLI 均不能选择 registry 或修改 activation。
  checked-in active 状态只授权隔离 scheduler 读取合同，不等于 provider 已调用、SQLite 已写入
  或 API 已 ready；
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
- `stock_basic` 与 `daily` 已以同一机制进入 GitHub：`stock_basic` 合同定义 17 个
  provider 字段，`daily` 定义 13 个 provider 字段；transport 在字段清单为空时省略上游
  `fields` 参数，在非空时逐字传递。离线 zero-code 证据已证明原始 `fields/items` 可经通用
  collector 写入 SQLite fact+receipt 并由 `POST /v1/query` 读回；2026-07-19 又从精确
  `0be6f83` 在全新隔离 server canary 中完成真实 `stock_basic`、`daily` 采集与 query readback；
- 当前证据包含 local/GitHub 代码层 PASS，以及三个首批 dataset 的受限真实隔离 canary PASS。
  它仍不证明内部生产服务、完整 Tushare dataset 覆盖、受邀账户网关或外部 Beta 已完成。

### TradingAgent consumer handoff contract

- TradingAgent 已明确只消费 `GET /v1/catalog` 与 `POST /v1/query`，不直读 SQLite、不使用
  `/tushare`、`/source_status`、provider 专用 route 或 localhost fallback；
- exact8 r2 已由 fresh reviewer 判定 PASS（P0/P1=0）并在 `6c7ded4` 进入 GitHub；
  `schema_major`、same-as-of/receipt watermark 实证、healthy/stale fixture 与 2331 项全量回归
  均绿，三份文档的核心 truth statement 逐字一致；
- 相关提交没有新增 TA 业务表、因子、交易语义、provider 分支或公共 route。当前生产 catalog
  version `v1-18bfcb88c92f3232`、schema major 2、三个 dataset ID、loopback base URL 与认证
  catalog/query 已有 fresh readback；但 collector/probe timers 尚未通过 fresh-token 持续运行停止线。
  在该停止线通过并形成消费者 handoff 前，**TradingAgent 当前不可接入生产 lane**。

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
  `exchange/cal_date/is_open/pretrade_date`。这同时暴露当时 target registry 的真实 P1：
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
dataset 和该受限窗口，不等于生产发布、TA 可接入、其它 dataset 可用或外部 Beta 开放。

### 隔离服务器 canary（2026-07-19 04:15 CST）

- canary 位于
  `/opt/investment/canaries/sharedsignals/20260719T0415Z-0be6f83-stock-daily-v3`，代码精确绑定
  `0be6f83247eddd489489cdf64c310e785b9cd14e`，使用独立 checkout、SQLite、锁和临时服务；
- `cn.equity.security_master` 通过一次真实 Tushare `stock_basic` 调用写入 5,607 行
  provider-native facts 与匹配 success receipt；`cn.equity.daily` 通过一次真实 `daily` 调用写入
  5,522 行 facts 与匹配 success receipt；
- 两个 dataset 都完成 authenticated catalog/query、pagination、same-as-of 可复现和
  facts/latest-success-receipt 守恒检查；没有 dataset 专用 collector、表、route 或字段加工；
- 证据只证明这两个受限真实切片及当时精确字节。它没有启用 systemd/timer、没有替换生产
  checkout 或数据库，也不等于内部 V1 已稳定运行。

至此三个首批 dataset 都已有独立真实 provider-to-API canary 证据；同一通用管线现已发布到
独立 `18082`/新 SQLite 运行面。下一停止线是轮换暴露 token、以 canonical HTTPS 完成受控
collector oneshot，并启用/观察持续 probe 与 scheduler；不是继续逐接口重写采集器。

## 生产现状（2026-07-19 20:18 CST fresh 证据）

- SharedSignals provider-native source checkout、`origin/main` 与 active immutable release 均为
  `685f3d7599d6b0238ba9f9928af2844635df3403`，source checkout clean；release evidence 位于
  `/opt/investment/releases/sharedsignals-v1/evidence/`，不含 secret value。
- 新 `sharedsignals-v1-internal.service` active/enabled，唯一监听 `127.0.0.1:18082`；未认证
  catalog 为 401、认证 catalog 为 200、legacy route 为 404、错误 method 为 405。旧
  `sharedsignals-api.service` 仍 active/enabled 并监听 `127.0.0.1:8082`。
- 新 SQLite 位于 `/opt/investment-data/sharedsignals-v1/read_model/provider_native.sqlite`，
  `PRAGMA quick_check=ok`，dev `66308`、inode `15466502`、mode `0600`。现有真实 facts/receipt：
  `cn.equity.daily` 5,522 行、`cn.equity.security_master` 5,607 行、
  `cn.market.trade_calendar` 7 行；每个 dataset 各有一条匹配 success receipt。
- Catalog version 为 `v1-18bfcb88c92f3232`，三个 dataset 的 schema major 均为 2，runtime 均
  `success`、`degraded=false` 且 receipt 存在。三个 query 均为
  `ready/success/fresh/valid/complete`，provider lineage 为 `tushare`，receipt/data-through/
  observed-at 均非空；同一 verified snapshot 的重复请求除 `request_id` 外一致，signed cursor
  第二页返回不同的下一行。
- 手动 strict probe 结果为 `success`、exit 0。生产同一 Python 3.12 runtime 通过实际网络验证
  `https://api.quicksync.cn` 返回 HTTP 200 且协商 `TLSv1.3`；该握手未发送 provider token。
- 旧生产 SQLite 保持路径 `/opt/investment-data/SharedSignals/runtime/read_model/marketdata.sqlite`、
  dev `66308`、inode `1048617`、mode `0644`；约 23 GB 旧库和 8082 lane 没有被新 release
  打开、迁移、替换或停止。
- `sharedsignals-provider-native-collect.timer` 与 `sharedsignals-v1-probe.timer` 仍为
  disabled/inactive。旧 collector token 曾由早期手动 bootstrap 经 HTTP 使用，按暴露处理；
  在吊销/轮换、以 canonical HTTPS 完成一次受控 collector oneshot 并再次 strict probe 前，
  禁止启用 timers，禁止 HTTP fallback，也禁止把 API 当前健康写成持续采集完成。

## 权威层与验收分层

权威顺序固定为：

```text
provider-neutral registry
-> provider-level transport adapter
-> provider-native SQLite rows + transaction-scoped SQLite ingest receipt
-> read-clock freshness/quality/lineage/degraded projection
-> GET /v1/catalog + POST /v1/query
-> internal consumer
-> invited tenant (only after the internal stop line)
```

每次汇报必须分开：

1. local worktree PASS；
2. local main；
3. origin/GitHub；
4. production checkout；
5. production runtime；
6. internal authenticated route；
7. real dataset evidence（provider receipt 与 API response）；
8. external route（仅外部 Beta 阶段）。

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

1. 立即吊销并轮换曾经由 HTTP 使用的 collector token；secret value 不进入 Git、任务消息、日志
   或 release evidence。将 root-owned `0600` collector secret 原子替换为 canonical HTTPS URL 与
   fresh token，旧 token 不得成为 rollback 内容；
2. 两个 timers 保持 disabled，先运行一次受控 generic collector oneshot，证明真实 provider
   response、SQLite facts/receipt、catalog/query metadata 与日志脱敏；随后再次执行 strict probe；
3. 只有 fresh-token oneshot 与 probe 均通过，才启用 collection/probe timers，并至少观察一个
   probe 周期和一个 scheduler 周期，验证无 overlap、无 HTTP fallback、无 secret leakage；
4. 向 TA/MG 交付冻结 catalog version、schema major 2、三个 dataset ID、loopback base URL、认证
   接入方式与 healthy/impaired envelope；消费者只通过 catalog/query，不直读 SQLite 或 legacy
   route；
5. 内部持续采集稳定后再逐批扩境内 dataset。其余 111 项必须先补 reviewed upstream contract，
   普通 dataset 继续只扩 registry/config，不新增 collector/table/scheduler/query/public route；
6. 受邀账户 credential、scope、rate/concurrency、quota、revocation、usage ledger、网关和外部
   ingress 全部后置到 external Beta；替代链稳定并完成 no-use 观察后，才退役旧代码、文档、
   cron 和 worktree。

## 本地验证入口

```bash
uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q
uv run --python 3.12 --with-requirements requirements.txt ruff check <本次精确 Python 路径>
uv run --python 3.12 python -m compileall -q <本次精确 Python 路径>
git diff --check
```

完整测试、reviewer PASS、manifest 和哈希只证明对应候选字节；candidate 变化或 base 变化后必须
重新生成 fresh evidence，旧 PASS/JUnit/哈希不得复用。
