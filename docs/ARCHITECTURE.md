# TradingDatas Architecture

## 产品边界

TradingDatas 是金融数据基础设施，不是研究或交易系统。它负责 provider catalog、采集、无损标准化、SQLite facts、transaction receipts、数据质量元数据和只读 API。

## 权威顺序

1. dataset registry：数据集身份、provider binding、schema、cadence、entitlement 和 query policy；
2. SQLite facts + transaction-scoped receipts：真实采集结果；
3. registry + receipts + 读取时钟：runtime metadata；
4. HTTP API：只读投影。

JSON 缓存、日志、HTTP 200、静态接口数量、消费者状态和旧数据库都不是权威。

## 通用采集

普通 Tushare 请求统一为：

```text
api_name + params + fields -> fields/items
```

当前身份分层固定为：

- `provider=tushare`：dataset contract、provider-native schema 与原始 payload 的来源；
- `transport_service=quicksync`：服务器实际 endpoint、认证、TLS、权限返回、错误码、限频与并发边界。

Tushare 官方目录和接口文档只生成 dataset/schema/cadence 参考，不能证明 QuickSync 账号的 runtime 权限或调用预算。QuickSync 只在 provider-level transport adapter 中出现；普通 dataset 不因 transport 修正而增加 collector、业务表、公共 route 或 scheduler 分支。

能力目录还必须区分四个事实层：官方目录、transport/tool 可见性、账号真实
entitlement、runtime activation。当前 scope v2 将 239 个官方名称与 258 个 MCP 工具
合并为 268 个唯一能力名，首期产品目录为 222 个境内只读 dataset；其中 190 个已有
官方文档合同，新增 32 个在合同或 HTTPS 证据缺失时仅可发现、不可执行。MCP
visibility 不能自动生成文档 URL、权限或 scheduler 激活。

`config/tushare_capability_catalog.v2.yaml` 是上述 222 项的离线、可重建产品能力发现
artifact，不是 runtime registry。32 个 discovery-only 项不得伪造成
`DatasetDefinition`，也不得猜测 dataset ID、schema、字段、主键、cadence 或请求模板；
它们在正式合同冻结前不进入 SQLite、collector、scheduler 或 `POST /v1/query`。当前
runtime registry 仍为 190 项，其中仅 12 项 `active+active` 可进入 SQLite 读侧检查：
`trade_cal`、`stock_basic`、`daily`、`index_classify`、`sw_daily`，以及独立
`direct_wave_1` 中的 `adj_factor`、`stk_auction`、`stk_limit`、`suspend_d`，以及
`direct_wave_2` 中的 `hsgt_top10`、`limit_list_ths`、`moneyflow_ind_ths`。
新增七项只放宽 activation，不改写 schema、cadence 或 completeness；在完整性未证明时
API 仍返回 `partial/degraded`。

registry 声明 request template、variants、window、fanout、pagination、字段、主键、分区、预算、频率和回填。executor 不包含 dataset_id 或 api_name 条件分支。

`dataset_field` 参数可以声明可选的正整数 `batch_size`，未声明时默认为 `1`；compiler 将该值原样投影到通用 fanout 合同。executor 对已验证的来源值做稳定去重和有界分批，同一批的多个值作为一个逗号分隔的 provider 参数发送。该能力只描述通用请求形状，不改变 entitlement、activation、receipt 或数据完整性门禁，也不允许按 dataset 或 API 增加执行分支。

同一 `dataset + provider + request_window` 的 request variants 是一个不可拆分的采集 cohort：一次 execution 必须覆盖 registry 中的 exact variant set，并让所有真实调用继续各自写入 `request_identity` receipt。任一 variant 缺失或真实失败时 cohort failed；至少一个 variant success 且其余合法 empty 时 cohort success；只有全部 variants empty 时才应用 dataset 的 `empty_data_policy`。scheduler 用显式 run root 派生每个 window 的 plan root，不以时间戳或随机 UUID 排序拼接独立 execution。

生产 `current` 只承担进程入口的原子版本选择。入口脚本用 `Path(__file__).resolve()`
绑定一个物理 immutable release，registry 和 schedule 必须从该物理 release 内读取；
systemd 或环境文件不得再用 `/current/config/...` 覆盖它们。这样 `current` 即使在另一次
受控发布中切换，已启动进程也不会混用两个 release 的代码与配置。

官方接口文档只通过批量 compiler 进入 registry：`tools/snapshot_tushare_contracts.py` 读取固定能力目录，批量解析输入/输出表与更新说明，冻结 URL 和内容哈希；`config/tushare_cadence_policy.v1.yaml` 是 190 个已有正式文档合同的唯一 cadence authority，按排序 `api_name` 精确覆盖、逐项绑定官方文档 SHA，并只允许八个通用 cadence class、正 freshness SLA 和固定安全闭集内且与 cadence 语义一致的 reason code；`tools/compile_tushare_runtime_contracts.py` 保留已复核合同，并把其余官方接口编译为可发现但 paused 的 append-only 合同；registry compiler 再结合独立 activation/entitlement 声明生成运行 registry。更具体的 reviewed contract cadence/SLA 优先于该通用政策，`reviewed_contract_exact` 只能用于 reviewed bundle 中 cadence/SLA 精确一致的合同。不能确定的 entitlement、主键、频率或参数模板必须保持 paused，不用猜测填充。

activation evidence 不能绕过 provider payload 的绝对扫描上限。registry compiler 按声明字段数通用、确定性地收窄 active binding 的 `max_rows_per_attempt`；字段、深度或最小窗口在现有绝对上限内无法安全编译时，该 binding 继续保持 paused。runtime 仍复核同一硬上限，不因单个 dataset 放宽。

请求合同的输入权威也必须按原始文件字节绑定，不能只信任调用方传入的已解析对象。runtime compiler 固定核对 official document、request observation、transport observation 和 reviewed contract 四类输入；HTTPS probe plan 固定核对 official document、request observation、transport observation 和 registered runtime contract 四类输入。任一文件内容与其冻结 SHA 不一致时，在生成请求或调用 provider 前失败。dataset-field seed 只有在 fresh success receipt 存在且 producer schema 与 registry 精确相等时才可使用；migration hint、旧 schema 或未来 schema 都不能替代生产者合同。

四种 request shape：

- snapshot/date range；
- entity fanout；
- dimension fanout；
- event/intraday window。

当前数据优先于历史回填；回填必须有界、可恢复、可观察，并遵守账号级和 API 级预算。

## Provider 权限与 Transport 预算

registry 的 `entitlement` 是 provider-neutral 技术状态。对当前 Tushare 数据集，它表示通过 QuickSync transport 受控真实调用观测到的账号接口权限；它不表示购买、计费或订阅。凭证只建立 transport 账号身份，不证明接口权限。

Tushare 官方接口说明给出的积分门槛、单次行数、分钟频次和每日总量只适用于官方合同参考，不能自动套用到 QuickSync。activation 与 scheduler budget 必须由 QuickSync 文档、真实有界探测和人工审核共同确定。当前受控证据只证明健康单一 HTTPS 节点的小响应 request-start 能力至少 200 次/分钟、并发 4；`main` 中的 200 次/60 秒和并发 4 是本地保护门禁，不是供应商合同额度或已部署 production 配置。混合大响应、每日额度与 DNS failover 仍未知，逐接口权限继续由真实矩阵决定。任何并发都要受 transport 账号级与 API 级预算共同约束，不能因为单次调用成功自动扩大。

## 通用存储

所有 provider-native 数据进入同一类通用事实表。provider 返回的 payload 必须无损保留；技术列不能覆盖 provider 字段。每个真实写事务必须同时提交 success receipt；rollback 后不得留下 success。

empty、failed、permission denied、rate limited、validation failed 和 storage failed 必须分开记录。未知字段保留并标记 schema drift，不能静默删除。

runtime 投影把“最新可信 scheduler run 的当前状态”和“全部完整 success cohort 的最大 `data_through`”分开计算。旧 backfill 后采不能让 dataset watermark 回退；同一 scheduler run 有多个 window 时，任一 window failed/incomplete 使 run failed，否则由目标 window 最大的 cohort 决定当前状态。watermark lineage 绑定该 cohort 的完整 member receipt IDs，不能由一个 sibling receipt 代表整个 cohort。

## 数据服务

catalog 和 query 只读 SQLite。缺数据库、缺表、缺 receipt、损坏或 metadata 不一致时 fail closed；不得同步调用 provider 或回退旧文件/旧数据库。

API lineage 必须同时保留 `provider=tushare` 与 `transport_service=quicksync`，使消费者能区分数据合同来源和实际采集通道。HTTP 200 不能抹平 QuickSync permission denied、rate limited 或其它 impaired 状态。

## 扩展模型

新增普通 Tushare dataset 只改 registry/config。新增 provider 仅在 transport、auth 或 pagination 不同时增加 provider adapter。公共 API 不随数据源增长。

本次从官方直连改为 QuickSync 不改变 registry、SQLite facts/receipts、catalog/query 或数据库 schema，也不要求逐接口开发；只修正 provider-level transport、凭证、错误分类、budget 和 lineage。
