# TradingDatas

TradingDatas 是一个类似 Tushare 的、provider-neutral 的金融数据服务。

当前目标只有一条：把属于首期范围、且当前 QuickSync 账号经真实调用确认允许访问的 Tushare 只读数据接口，按照合适频率稳定采集到 SQLite，并通过固定 API 供内部系统调用。未来新增新闻、公告、研报、政策和客观舆情等数据源时，继续复用同一套 catalog、ingest、receipt、query 和 scheduler，不增加公共 API 路由。

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

## Tushare 数据合同与 QuickSync 运行权限

Tushare 官方接口文档用于生成普通数据集的请求、字段、schema 和 cadence 参考；它不证明当前 QuickSync 账号的接口权限、分钟/每日额度或并发能力。代码中的 `entitlement_state` 仅表示经 QuickSync 真实有界调用观测到的 provider 权限状态，不表示购买、按接口计费或订阅。

QuickSync 的正式 endpoint、凭证文件、权限码、频率和并发限制必须分别冻结证据。2026-07-21 CST（证据时间 2026-07-20Z）的受控实测只证明健康单一 HTTPS 节点的小响应 request-start 能力达到 210 次/分钟、并发 4；当前 `main` 代码设置更保守的保护门禁 200 次/60 秒、并发 4，但它不是 QuickSync 合同额度或已部署的 production 配置。混合大响应、每日额度和 DNS failover 仍待服务器验收，也不能由吞吐下限替代逐接口权限、schema、真实 receipt 和 API readback。production timer 在 provider-level transport、权限矩阵与 fresh server canary 全部通过前保持 disabled。Tushare 官方说明仍只作为数据更新周期参考：[Tushare 接口文档](https://tushare.pro/document/1)。

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

编译器当前注册 190 个首期官方接口。只有有独立 activation/entitlement
证据的接口会成为 `active`；其余接口仍可在 catalog 中发现，但固定为
`entitlement_state=unknown`、`activation_state=paused`，不会被 scheduler 调用。

这些官方合同保持可复用，不需要迁库或逐接口重写采集器；修正发生在 provider-level transport/auth/error/rate 边界。

## Entitlement 探测

默认命令只校验冻结合同并输出计划，不读取 Token、不调用 provider：

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python tools/probe_provider_entitlements.py
```

`config/tushare_request_profiles.v1.yaml` 以配置方式覆盖其余 187 个合同：153 个
具备已复核请求画像，其中 135 个可由单一通用 resolver 解析为 one-shot probe。
resolver 只接受冻结的 `literal`，或从显式 UTC `observed_at` 按
`Asia/Shanghai` 生成 `yyyymmdd`、`yyyymm`、`yyyy_qn`、`yyyyww`、
`local_datetime_seconds`，并应用有界 `offset_seconds`；字段只取官方冻结合同中的
第一个合法输出字段。既有 `bak_daily`、`fund_adj`、`fund_manager` 请求字节保持不变。
其余 52 个按缺少 fresh anchor、空参数无界或枚举未冻结等原因保持 plan-only，
不会进入 resolver。探测不是采集：它不写 facts、ingest receipts 或 activation，
也不会启用 scheduler。

执行模式只用于正式 QuickSync 凭证文件已按运行手册安装后的人工 one-shot。它要求显式传入
1–5 个属于上述 135 个 runtime-executable profile 的 `--dataset-id`、不可变 release
commit 和精确 UTC 秒。缺失、重复、未知、超过 5 个或任何 plan-only 选择都会在
读取凭证前整体拒绝。每个已选择数据集最多调用一次、零重试，每个响应在 JSON
解析前受 128 KiB 上限约束。命令只向 stdout 输出脱敏、自哈希 JSON evidence；
结果仍需独立审核，不能直接作为自动 activation 指令。

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
