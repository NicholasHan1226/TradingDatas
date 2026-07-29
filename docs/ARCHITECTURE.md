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

能力目录必须区分四个事实层：官方目录、transport/tool 可见性、账号真实 entitlement、
runtime activation。能力目录是离线、可重建的产品发现 artifact，不是 runtime registry；
discovery-only 项不得伪造成 `DatasetDefinition`，也不得猜测 dataset ID、schema、字段、
主键、cadence 或请求模板。它们在正式合同冻结前不进入 SQLite、collector、scheduler 或
`POST /v1/query`。MCP visibility 不能自动生成文档 URL、权限或 scheduler 激活。

架构文档不固化会漂移的 active/paused 数量、release 或某次探测结论；这些都以
`STATUS.md` 和正式 catalog/query server readback 为准。无论 catalog 显示什么，消费者
仍必须依据 query envelope 的 receipt、freshness、quality 与 degraded 判定可用性。

registry 声明 request template、variants、window、fanout、pagination、字段、主键、分区、预算、频率和回填。executor 不包含 dataset_id 或 api_name 条件分支。

自动 cadence 统一支持 `yyyymmdd`、`yyyymm`、`yyyy_qn` 与 `yyyyww` 四种已验证窗口编码；它们
都由同一个 planner 生成。`local_datetime_seconds` 只允许显式有界 one-shot，不能由 scheduler 猜测
盘中窗口。窗口格式本身不构成 activation 证据，仍须经过 provider → SQLite receipt → query readback。

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

所有 provider-native 数据进入同一类通用事实表。provider 返回的 payload 必须无损保留；技术列不能覆盖 provider 字段。每个真实写事务必须同时提交 success receipt；rollback 后不得留下 success。对 `current_snapshot`，上游再次返回相同 payload 时，事实的 payload 与数据 revision 不变，但同一事务会把其 provenance 绑定到新的 success receipt；因此当前合同只能依赖本轮重新验证的事实，不能借用旧合同 receipt，也不会因 SQLite 的 payload 去重而丢失 scheduler authority。

empty、failed、permission denied、rate limited、validation failed 和 storage failed 必须分开记录。未知字段保留并标记 schema drift，不能静默删除。

runtime 投影把“最新可信 scheduler run 的当前状态”和“全部完整 success cohort 的最大 `data_through`”分开计算。旧 backfill 后采不能让 dataset watermark 回退；同一 scheduler run 有多个 window 时，任一 window failed/incomplete 使 run failed，否则由目标 window 最大的 cohort 决定当前状态。watermark lineage 绑定该 cohort 的完整 member receipt IDs，不能由一个 sibling receipt 代表整个 cohort。

`postclose_daily` 的纯日期（或本地午夜）分区在 freshness 比较中代表该本地交易日结束，而不是零点开始。这样周五已经完整写入的日线在周末不会被提前标为 stale；带实际时分秒的数据时间保持原样。该规则只影响读取时的 freshness 投影，不改变 facts、receipt、provider 返回或调度。

## 数据服务

catalog 和 query 只读 SQLite。缺数据库、缺表、缺 receipt、损坏或 metadata 不一致时 fail closed；不得同步调用 provider 或回退旧文件/旧数据库。

API lineage 必须同时保留 `provider=tushare` 与 `transport_service=quicksync`，使消费者能区分数据合同来源和实际采集通道。HTTP 200 不能抹平 QuickSync permission denied、rate limited 或其它 impaired 状态。

## 运行面隔离与未来扩展

TradingDatas 是一个产品和一套固定数据合同，不是一个必须共享所有运行状态的单体服务。
所有 lane 复用同一 registry → provider adapter → SQLite facts/receipts → catalog/query
链路；但 cadence、上游、凭证、市场时间、监管边界或故障域不同的数据，必须保持独立
运行面。

- 当前境内 Tushare/QuickSync 与 Crypto/Binance 分别拥有独立 immutable release、SQLite、
  lock/runtime 目录、timer、loopback port 和凭证边界；它们不得合并数据库、timer 或
  transaction receipt。
- 新闻、公告、研报、政策、客观舆情等事件源，以及期货、美股等市场，先按其 provider、
  cadence 和凭证判断是否新建 lane。只有这些边界确实相同，才可复用既有 lane；不能只因
  都属于“金融数据”而强行共库或共调度。
- 新 lane 不新增公共 route。它仍只暴露 `GET /v1/catalog` 与 `POST /v1/query`，由 dataset
  registry 定义数据集、schema、过滤、排序、receipt 与 metadata 合同。
- 内部消费者只保存“lane base URL + 允许的 dataset IDs”，不直连 SQLite，也不跨 lane
  transaction。TradingAgent 只消费 envelope，不能反向控制采集、研究或交易逻辑。
- 只有确有一个消费者需要同一次调用跨多个 lane 查询时，才评估一个薄的只读 gateway：它只
  聚合 catalog、按 dataset_id 转发 query，不复制 facts、不做跨库 join、不改写 metadata、
  不成为采集或交易控制层。当前个人内部使用不预先实现该 gateway。

未来扩展的最小步骤固定为：冻结 provider 合同与通用 request shape → 隔离有界 canary →
provider-to-receipt-to-query readback → 在该 lane 启用节奏。普通数据集只改 registry/config；
只有 transport/auth/pagination 真正不同才增加 provider-level adapter。

## 跨市场语义与另类数据

运行隔离是可用性与安全边界，不是语义孤岛。TradingDatas 必须让后续 A 股、期货、
美股、Crypto、全球新闻和自建另类数据能够在**读取侧**以可审计方式关联；但这种关联
不得变成跨 lane 写事务、采集回调或交易判断。

每个新 dataset 在 registry 中至少要明确：资产类别、市场/交易所、币种、原生标的身份、
时间字段及其语义（事件发生、bar open/bar end、披露、可得、采集观察）、时区、provider
身份、transport、schema major、quality/freshness/lineage 与 receipt 口径。原始 payload
始终保留；标准化字段只补充可解释的公共语义，不能抹平来源差异或未知字段。

- 跨市场读取使用受版本约束的 entity mapping 与时间语义，而不是用代码字符串、收盘价或
  采集时间作隐式猜测。股票、指数、期货合约、加密交易对和新闻实体可有不同原生身份；
  映射须保留来源、有效期与置信状态。
- 新闻、公告、舆情和其它另类数据必须分开保存 `event_at`、`published_at`、
  `available_at` 与 `observed_at`（适用时）。后采历史内容不能被伪装成当时可用的信息，
  也不能以情绪分数或关联标签覆盖原文、来源或时间证据。
- 自建另类数据源遵循同一 provider adapter、raw payload、receipt 与 catalog/query 合同；
  先作为客观事实数据发布，研究侧再决定如何做实体关联、特征、预测或策略解释。
- 跨市场图谱、相关性、候选、预测、资金与交易判断属于 MarketGraph 或 TradingAgent 的
  读取侧职责。TradingDatas 只交付带来源和时间证据的数据快照，不能在数据平台内形成
  交易信号或反向控制采集。

## 扩展模型

新增普通 Tushare dataset 只改 registry/config。新增 provider 仅在 transport、auth 或 pagination 不同时增加 provider adapter。公共 API 不随数据源增长。

本次从官方直连改为 QuickSync 不改变 registry、SQLite facts/receipts、catalog/query 或数据库 schema，也不要求逐接口开发；只修正 provider-level transport、凭证、错误分类、budget 和 lineage。
