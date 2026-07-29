# TradingDatas

TradingDatas 是一个类似 Tushare 的、provider-neutral 的金融数据服务。

当前主目标是把属于首期范围、且当前 QuickSync 账号经真实调用确认允许访问的 Tushare 只读数据接口，按照合适频率稳定采集到 SQLite，并通过固定 API 供内部系统调用。Binance 公共现货行情作为隔离的第二 provider 纵向切片，只覆盖 BTCUSDT/ETHUSDT 5 分钟行情与公开 exchangeInfo 交易约束元数据，并使用独立 OS 服务账号、release、SQLite、内部 API 认证材料、loopback 服务和 timer；无需且禁止 Binance 账户/API key。未来新增新闻、公告、研报、政策和客观舆情等数据源时，继续复用同一套 catalog、ingest、receipt、query 和 scheduler，不增加公共 API 路由。Crypto 运行合同见 [docs/CRYPTO_LOOPBACK_RUNTIME.md](docs/CRYPTO_LOOPBACK_RUNTIME.md)，实际部署状态以 [STATUS.md](STATUS.md) 为准。

## 当前开发优先级

当前阶段只服务 Nicholas 自己的内部量化研究与模拟盘：先把已批准的 Tushare/QuickSync 数据稳定写入 SQLite，再通过 loopback `catalog/query` API 交给内部消费者。不得把这一目标扩展成公网数据产品、多账户、计费、配额、外部网关、专用数据路由或按接口拆分的服务/定时任务。受邀外部账户和更广的数据产品形态只保留为后续合同与合规评估项，除非另有明确批准，不进入当前实现或生产验收。

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

外部受邀账户 Beta 只有在内部服务稳定且 QuickSync/Tushare 的再分发、缓存和对外服务条款完成书面核验后才进入下一阶段；当前实现与生产验收不把上游可调用误当成可对外再分发授权。

## 仓库

<https://github.com/NicholasHan1226/TradingDatas>
