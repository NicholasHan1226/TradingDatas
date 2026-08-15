# TradingDatas

TradingDatas 是一个类似 Tushare 的、provider-neutral 的金融数据服务。

它在 Finance 中只承担跨市场数据平台职责：接入数据接口、稳定采集、规范化写入数据库、持续积累、保留 lineage/receipt，并通过固定 `catalog/query` API 稳定供应各市场。TradingAgent/Quant Core 才是终局个人自动量化交易系统；TradingCopilot 只是过渡性的 A 股实盘辅助与观察工具。TradingDatas 不拥有预测、策略、模型晋级、资金、风险或订单 authority。

当前主目标是把属于首期范围、且当前 QuickSync 账号经真实调用确认允许访问的 Tushare 只读数据接口，按照合适频率稳定采集到 SQLite，并通过固定 API 供内部系统调用。Binance 公共数据作为隔离的第二 provider 纵向切片，覆盖冻结 10 个 USDT 标的的现货 5 分钟行情与公开 exchangeInfo 交易约束元数据，以及同一冻结标的的 USDⓈ-M 永续 funding rate / open interest 公共只读历史（当前为 contract_ready 候选，timer 未启用），并使用独立 OS 服务账号、release、SQLite、内部 API 认证材料、loopback 服务和 timer；无需且禁止 Binance 账户/API key。未来新增新闻、公告、研报、政策和客观舆情等数据源时，继续复用同一套 catalog、ingest、receipt、query 和 scheduler，不增加公共 API 路由。Crypto 运行合同见 [docs/CRYPTO_LOOPBACK_RUNTIME.md](docs/CRYPTO_LOOPBACK_RUNTIME.md)，实际部署状态以 [STATUS.md](STATUS.md) 为准。

## 当前开发优先级

当前阶段只服务 Nicholas 自己的内部量化研究与模拟盘：先把已批准的 Tushare/QuickSync 数据稳定写入 SQLite，再通过 loopback `catalog/query` API 交给内部消费者。不得把这一目标扩展成公网数据产品、多账户、计费、配额、外部网关、专用数据路由或按接口拆分的服务/定时任务。受邀外部账户和更广的数据产品形态只保留为后续合同与合规评估项，除非另有明确批准，不进入当前实现或生产验收。

接口接入按广度优先推进：每批 valid rows/receipts 立即入库积累；单个 dataset 的 empty、partial、429、provider `5xx` 或 cadence 失败只降级并排队修正该 dataset，不阻断下一独立批次。locked、excluded、unknown 或 required params 未解决的能力保持显式暂停。`stable` 仍按 dataset 独立验证，但不是全部接口继续接入的总门禁。

当前接入必须区分两个身份：`provider=tushare` 定义数据集与 provider-native payload，`transport_service=quicksync` 定义服务器实际连接、认证、权限返回、错误码和流控。Tushare 官方文档只作为 dataset/schema/cadence 参考；生产不能再按 `api.tushare.pro` 官方直连假设运行。

## 唯一数据链

```text
Tushare / future providers
  -> provider adapter
  -> provider-native payload validation
  -> SQLite facts + transaction-scoped receipt
  -> runtime metadata projection
  -> GET /v1/catalog + POST /v1/query
  -> internal consumers
```

TradingDatas 不做预测、策略、候选、资金、持仓、风控、订单、成交或交易建议。消费者负责自己的加工与交易闭环。

## 能力状态：先可开发，再观察，后稳定

首期接口不再把开发、一次真实试读与稳定生产混成同一门禁：

| 状态 | 最小证据 | 可做什么 | 不能声称什么 |
|---|---|---|---|
| `contract_ready` | registry/config、编译与失败测试 | 进入 capability manifest、TA 兼容测试、候选 PR | 上游权限、真实数据、生产可用 |
| `observed` | 一次有界的真实 receipt 与固定 `catalog/query` 回读 | 明确标注的一次性内部只读试用 | 连续健康、历史 PIT、自动调度 |
| `stable` | 跨适用 cadence 连续成功，且适用 TA/Copilot 已 readback | 稳定生产能力声明与相应常规运行 | 覆盖所有无关消费者或未适用 cadence |

缺少高一层证据不会阻断普通接口的批量合同/config、测试、候选发布或 TA 受控消费开发；它只限制对应层级的运行声明和自动化。所有状态仍只通过通用 registry -> collector -> SQLite receipt -> `catalog/query` 链路验证，不为单个 dataset 新增 collector、route、service、timer、表或发布流程。

## 普通数据集零代码接入

普通 Tushare 数据集只能通过 registry/config 接入：

- `api_name`
- 参数模板与 request shape
- 字段、主键、分区与时间语义
- 权限与激活状态
- 频率、发布延迟、修订窗口与回填策略
- 请求和响应资源预算

不得为普通数据集增加专用 collector、业务表、scheduler 分支、query 分支或公共 route。只有 transport、auth 或 pagination 协议真正不同，才增加 provider-level adapter。

对于没有自动 cadence 的已激活数据集，使用同一个
`tools/collect_provider_dataset.py --batch-file <external-json>` 做有界、串行的
one-shot 入库。batch 只列既有 `dataset_id` 和已冻结的 request window；它不增加
route、service、timer、provider 参数逻辑或业务表。所有项先在 plan 模式一起校验，才会
在 execute 模式逐项以各自的 SQLite transaction receipt 写入。它是当前数据的受控采集
入口，不把 `on_demand` 伪装成自动调度，也不替代每个数据集的 receipt/API readback。

## Tushare 数据合同与 QuickSync 运行权限

Tushare 官方接口文档用于生成普通数据集的请求、字段、schema 和 cadence 参考；它不证明当前 QuickSync 账号的接口权限、分钟/每日额度或并发能力。代码中的 `entitlement_state` 仅表示经 QuickSync 真实有界调用观测到的 provider 权限状态，不表示购买、按接口计费或订阅。

QuickSync 的正式 endpoint、凭证文件、权限码、频率和并发限制必须分别冻结证据。2026-07-21 CST（证据时间 2026-07-20Z）的受控实测只证明健康单一 HTTPS 节点的小响应 request-start 能力达到 210 次/分钟、并发 4；当前 `main` 代码设置更保守的保护门禁 200 次/60 秒、并发 4，但它不是 QuickSync 合同额度或已部署的 production 配置。混合大响应、每日额度和 DNS failover 仍待服务器验收，也不能由吞吐下限替代逐接口权限、schema、真实 receipt 和 API readback。timer 只能在 provider transport、权限矩阵、fresh server canary 与可回滚发布均通过后由受控发布流程显式启用；实际状态以 `STATUS.md` 和服务器 readback 为准。Tushare 官方说明仍只作为数据更新周期参考：[Tushare 接口文档](https://tushare.pro/document/1)。

## 固定内部 API

- `GET /v1/catalog`
- `POST /v1/query`

API 只读 SQLite，不同步调用上游，不回退文件、旧数据库或 provider 专用接口。每次响应保留 dataset 级的 `state`、`degraded`、`freshness`、`quality`、`lineage`、`receipt_id`、`data_through`、`observed_at` 和 `reasons`。

详见：

- [产品与开发规则](AGENTS.md)
- [路线图](ROADMAP.md)
- [当前状态](STATUS.md)
- [架构](docs/ARCHITECTURE.md)
- [API 合同](docs/API.md)
- [运行与发布](docs/OPERATIONS.md)
- [clean-slate 决策](docs/adr/ADR-0010-tradingdatas-clean-slate.md)

官方 Tushare 合同批量快照入口：

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python tools/snapshot_tushare_contracts.py \
  --catalog config/tushare_capability_catalog.v1.yaml \
  --output config/tushare_document_contracts.v1.yaml \
  --cache-dir /path/to/reviewed-cache
```

该命令只冻结官方文档合同，不调用真实数据接口，也不把 `in_scope` 误判成账号积分/单独权限已允许或运行时已激活。

文档快照批量编译为统一运行合同与 registry：

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python tools/compile_tushare_runtime_contracts.py
uv run --python 3.12 --with-requirements requirements.txt \
  python tools/compile_provider_native_registry.py
```

当前能力范围分为两层，不能再把旧的 190 当作全部能力：

- `config/tushare_capability_scope.v2.yaml` 将官方固定目录 239 个名称与当前 MCP
  可见的 258 个工具合并为 268 个唯一能力名，并按首期边界冻结 222 个境内只读
  dataset；其余为 41 个海外项、4 个账号操作和 1 个 helper。
- 其中 190 个已有官方文档合同和历史 QuickSync HTTP compatibility 观测；新增 32
  个只进入可发现目录，缺正式合同或 HTTPS 权限证据时一律保持
  `unobserved/paused`，MCP 可见性不能推导 entitlement 或 activation。

当前 runtime registry 仍是上述 190 个合同子集，并只从
`config/quicksync_interface_observations.v1.yaml` 读取其 QuickSync 权限与兼容性观测。
该历史矩阵绑定脱敏证据及 API 集合 SHA、`production_ready=false`，不能替代正式
HTTPS provider -> SQLite -> receipt -> API readback，也不能代表新增 32 项已可调用。

190 个正式合同的 cadence authority 是
`config/tushare_cadence_policy.v1.yaml`。它按 `api_name` 精确覆盖每个官方文档合同，
逐项绑定 `source_document_sha256`，并只声明八种通用 cadence class、正 freshness SLA
和可审计 reason code。运行合同编译器拒绝缺失、重复、未知、未排序或文档哈希漂移的策略项；
reason code 还必须属于固定安全闭集，并与声明的 cadence class 语义一致；自由文本、未知码和
伪造的 reviewed-exact 绑定一律 fail closed。
这只决定数据新鲜度目标，不推导 QuickSync entitlement、activation 或 scheduler 启用。已有
五个 reviewed contract 的更具体 cadence/SLA 保持优先级，不会被通用政策改写。

生产状态不在 README 固化 commit、active 数量或 timer 状态。它们会随 immutable release、
receipt 和窗口而变化，必须以 [STATUS.md](STATUS.md) 的最新快照和本轮服务器
`current`/catalog/query readback 为准。catalog active、HTTP 200、历史 probe 或单次 success
都不能替代 dataset 级的 receipt、freshness、quality、lineage 与 completeness 验收。

HTTPS activation evidence 是仓外、hash-bound 的运行 sidecar，不是 repository config，
也不进入正式编译默认输入。`preactivation_candidate` 只接受显式
`--activation-evidence /outside/repository/path`，并且只把候选 registry 写到仓外路径。仓外
sidecar、CI fixture 或仓内配置都不能替代 immutable production release 的 compiler/readback。

旧 manual entitlement probe 与 policy 已退役。request-profile 配置及 resolver 仅作为
官方输入参数迁移资料：它们不是 entitlement/activation authority，不得被 collector、scheduler
或生产命令执行。正式验证统一走 registry-driven collector 的受控 one-shot，使事实数据与
transaction receipt 同事务，再通过固定 catalog/query API readback。

## 本地验证

```bash
uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q
uv run --python 3.12 --with-requirements requirements.txt ruff check <changed-python-paths>
git diff --check
```

测试通过只证明当前候选。local main、GitHub、生产文件、生产 runtime、真实采集、内部 API readback 和消费者调用必须分别验证。

## Onboarding 状态报告

`tools/report_dataset_onboarding_status.py` 生成稳定排序、无敏感信息的机器可读状态报告，用于区分
“已在 catalog 中”与“已经由正式 receipt/API 证明可消费”。它只读取已验证的 SQLite 快照和
registry，绝不调用 provider 或写入数据库；可选的正式 catalog/query 响应快照也只作为受检输入，
必须以 `api_version=v1`、当前 registry 的 `catalog_version` 和 registry SHA-256 作为根绑定，且与
SQLite receipt、时间水位和 provider lineage 精确一致，才能标记 `formal_ready`。

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python tools/report_dataset_onboarding_status.py \
  --db-path /trusted/read-only/provider_native.sqlite \
  --now 2026-08-01T15:34:00+08:00 \
  --api-snapshot /redacted/formal-api-snapshot.json \
  --output /tmp/tradingdatas-onboarding-status.json
```

报告不会输出 token、SQLite 路径或 provider payload。没有正式 API 快照、或根版本/目录/hash、
query envelope 的 dataset、`degraded`、receipt、时间/lineage 任一绑定不一致时，结果保持
`observed_isolated_only`，不能替代生产验收。

外部账户、再分发、缓存和对外服务不属于当前开发计划；即使未来重新评估，也必须先完成独立的上游条款书面核验，不能由当前内部 API 或上游可调用性推导授权。

## 内部消费者合同能力清单

`tools/compile_consumer_capability_manifest.py` 从当前 registry 与受审 consumer profile
编译稳定排序的机器可读清单，供 TradingAgent 在调用固定 API 前发现 dataset、cadence、
request shape、identity、freshness SLA、可读字段、默认 projection、entity scope 和合同层适用性。它不会打开 SQLite、调用 provider 或断言
`ready`、`live`、`stable`；这些状态只能由上节的 receipt/API 绑定 onboarding 报告证明。

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python tools/compile_consumer_capability_manifest.py \
  --output /tmp/tradingdatas-consumer-capabilities.json
```

当 `request_template.ts_code` 是已声明的多代码 literal 时，清单会输出
`entity_scope.kind=versioned_literal_values`、`frozen=true`、稳定的 values SHA-256 和
单请求 batch semantics；普通单值 filter 不会被误判为 universe。`frozen=true` 只表示
registry 合同中的值集合固定，仍不证明 receipt、freshness 或 API runtime 可消费。相反，
`entity_scope.frozen=false` 表示 registry 仍依赖运行时 seed/fanout；500 标的候选只有在
经审核的冻结 universe 合同、完整 receipt 和 formal API readback 都具备后，才可描述为可消费覆盖。

## 500 标的 minute universe 候选合同

仓库当前不保存 500 标的名单。`tools/generate_cn_minute_universe.py` 只接受外部已审核的
security-master snapshot rows、其完整 success receipt、receipt/registry/snapshot SHA-256、
UTC `as_of` 与精确旧选择规则；它以 `as_of` 的上海日期重放
`market=主板`、`list_status=L`、`curr_type=CNY`、`list_date≤as_of−30天` 和 `stable_hash`，
生成候选后立即交给 `tools/validate_cn_minute_universe.py`。两者均不调用 provider、打开
SQLite 或修改当前 30 标的合同。

从 receipt-bound 500 universe 编译单个 100 标的暂停候选时，使用：

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python tools/compile_cn_minute_capacity_registry.py \
  --universe /path/to/reviewed-cn-minute-universe.yaml \
  --base-registry config/provider_native_dataset_registry.yaml \
  --shard-index 0 \
  --registry-output /private/tmp/rt-min-shard-0.candidate.yaml \
  --reference-output /private/tmp/rt-min-shard-0.reference.json
```

该工具只输出 `activation_state=paused` 的候选，且会拒绝任何偏离冻结 30 标的 rollback canary
的 base registry。它不会调用 provider、修改 SQLite、替换 release 或启用 timer。真实试采和提升
必须按 [A 股 5 分钟 cohort：事实源与扩容门](docs/ASHARE_MINUTE_COHORTS.md) 完成 receipt、API、
TA 与 Copilot 的独立验收。

生成器输入为单个外部 YAML：`universe_id`、UTC `as_of`、source、selection、完整 receipt 与
`snapshot_rows`。source 必须携带 security-master 的 `receipt_id`、`receipt_sha256`、
`registry_sha256` 与 `snapshot_sha256`；`receipt_id` 必须与成功 receipt 一致，`receipt_sha256`
和 rows 由本地 canonical JSON 重算绑定，registry hash 保留为外部已审核 registry 的引用。validator
强制精确 500 个唯一的 `.SH`/`.SZ`
`ts_code`，并固定生成五个各 100 标的 shard。缺 snapshot、hash 不匹配或不足 500 个合格标的
均 fail closed。生成器输出 receipt-hash-bound schema v2 candidate；既有 schema v1 validator
输入仍可审计。历史动态 fanout 或 STATUS 中的候选描述不能替代输入。

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python tools/generate_cn_minute_universe.py \
  --input /path/to/reviewed-security-master-snapshot.yaml \
  --output /tmp/cn-minute-universe-reference.json
```

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python tools/validate_cn_minute_universe.py \
  --universe /path/to/reviewed-cn-minute-universe.yaml \
  --output /tmp/cn-minute-universe-reference.json
```

## 仓库

<https://github.com/NicholasHan1226/TradingDatas>
