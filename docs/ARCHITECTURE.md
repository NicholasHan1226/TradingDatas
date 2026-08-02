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

`dimension_fanout` 和 `event_or_intraday_window` 可以声明 `literal_values`：这是 provider 合同中固定、有限的官方枚举（例如新闻来源），必须为非空、类型稳定且不重复的值，并由通用 executor 按声明的 `batch_size` 稳定分批。它不依赖 SQLite seed，也不能用于 `entity_fanout`。离线 HTTPS probe-plan 只取第一个声明值验证 transport 可达；所有枚举分片的真实调用、receipt 和完整性仍由运行时 cohort 决定，单值 probe 绝不构成完整性或 activation 证据。

`windowed_unique_primary_key` 是 event/intraday window 的通用完整性合同：每条非空事件必须具有唯一主键、落在请求时间窗内、并属于本次实际请求的枚举分片；每个分片可以合法为空。它不把“每个来源必须有数据”误判为完整性，也不会把越窗事件或未请求来源写成 success。

同一 `dataset + provider + request_window` 的 request variants 是一个不可拆分的采集 cohort：一次 execution 必须覆盖 registry 中的 exact variant set，并让所有真实调用继续各自写入 `request_identity` receipt。任一 variant 缺失或真实失败时 cohort failed；至少一个 variant success 且其余合法 empty 时 cohort success；只有全部 variants empty 时才应用 dataset 的 `empty_data_policy`。scheduler 用显式 run root 派生每个 window 的 plan root，不以时间戳或随机 UUID 排序拼接独立 execution。

### `cn.dataset.tdx_daily` provider profile

`cn.dataset.tdx_daily` 是 Tushare `tdx_daily` 的 provider-native、按需读取合同：请求使用单个
`trade_date=YYYYMMDD` 分区，默认投影固定为已复核的 38 个 provider 字段。其稳定 identity 为
`[trade_date, ts_code]`，默认排序、筛选与分页均由 catalog 的通用 allowlist 和 limits 决定；
消费者不得假设整表读取或自行拼接 cursor。每个请求分区必须以
`single_partition_unique_primary_key` 完整性规则验证：主键非空、唯一、与请求日期一致且未触及
行数上限，才可写入 success receipt。该合同的 `on_demand` cadence 表示不会被 timer 自动调度；
`activation=active` 仅允许通用 collector 按显式有界请求执行，仍必须由实际 receipt、lineage 和
读取时 freshness/quality 投影决定是否可消费。隔离验证或历史分区的成功不构成持续 fresh 保证。

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

## 跨市场数据语义（非分析）

运行隔离是可用性与安全边界，不是数据格式各自为政。TradingDatas 对 A 股、期货、美股、
Crypto、全球新闻和自建另类数据只提供足以正确读取的**客观字段语义**；它不做跨市场
关联、实体推断、图谱、情绪打分、事件影响、因子、预测或策略判断。

每个新 dataset 在 registry 中至少明确：资产类别、市场/交易所、币种、provider 原生标的
身份、时间字段及其语义（事件发生、bar open/bar end、披露、可得、采集观察）、时区、
provider/transport、schema major、quality/freshness/lineage 与 receipt 口径。原始 payload
始终保留；标准化字段只补充来源已经给出的或可机械验证的公共语义，不能抹平来源差异、
未知字段或不确定性。

- 新闻、公告、舆情和其它另类数据可保存原文/原始事件、来源、以及 `event_at`、
  `published_at`、`available_at`、`observed_at`（适用时）。后采历史内容不能被伪装成当时
  可用的信息；TradingDatas 不生成情绪分数、关联标签或“利好/利空”结论。
- 首批 Tushare 事件证据切片固定为 `anns_d`、`cctv_news`、`irm_qa_sh`、
  `irm_qa_sz` 与 `research_report`。它们复用境内通用 collector，按通用 `event`
  cadence 独立于盘中分钟行情约每 15 分钟采集，并以各自日期分区、公开 identity 和
  transaction receipt 判定完整性；`event_evidence_wave_1` 只用于有界验收，不新增专用
  route 或 collector。HTTP 200、旧 receipt 或空行数均不等于 ready，消费者仍须逐数据集
  检查 `ready/fresh/valid/non-degraded`。
- 证券代码、合约、交易对或新闻对象的原生 identity 可以作为事实字段暴露。若 provider
  提供官方映射表，也可按原样作为 reference dataset 提供；平台不自行推断或维护跨市场
  entity graph。
- 自建另类数据源遵循同一 provider adapter、raw payload、receipt 与 catalog/query 合同，
  先作为客观数据发布。任何关联、特征、预测或策略解释均由读取侧承担。
- 跨市场图谱、相关性、候选、预测、资金与交易判断属于 MarketGraph 或 TradingAgent 的
  读取侧职责。TradingDatas 只交付带来源和时间证据的数据快照，不能在数据平台内形成
  交易信号或反向控制采集。

## 扩展模型

新增普通 Tushare dataset 只改 registry/config。新增 provider 仅在 transport、auth 或 pagination 不同时增加 provider adapter。公共 API 不随数据源增长。

本次从官方直连改为 QuickSync 不改变 registry、SQLite facts/receipts、catalog/query 或数据库 schema，也不要求逐接口开发；只修正 provider-level transport、凭证、错误分类、budget 和 lineage。
