# TradingDatas Operations

## 目标生产布局

```text
/opt/investment/releases/tradingdatas/<immutable-release>
/opt/investment/releases/tradingdatas/current
/opt/investment/releases/tradingdatas/manifests/<immutable-release>.json
/opt/investment-data/tradingdatas/read_model/provider_native.sqlite
/etc/tradingdatas/internal-api.env
```

仓库当前只定义以下 systemd 服务面：

- `tradingdatas-v1-internal.service`
- `tradingdatas-provider-native-collect.service`
- `tradingdatas-provider-native-collect.timer`

API service 只监听 `127.0.0.1:18082`，只提供 `GET /v1/catalog` 与
`POST /v1/query`，并以独立 `tradingdatas` 账号只读访问数据目录。仓库不安装
公网入口或 provider 专用路由。

采集调度只允许一个 registry-driven runner；timer 每五分钟只唤醒一次 cadence
planner，不拥有 dataset 或 provider API 清单。不再使用项目 crontab，也不按
Tushare API 增加 service/timer。生产 timer 默认只采集每个 automatic dataset 的最新
eligible window；显式声明下述 `partition_continuation` 的绑定可续采已经开始的有界旧日期。
其它历史回填必须经同一 registry 的外部、有界
one-shot manifest 明确选择，且继续受同一 transport budget 约束。没有正式 QuickSync
凭证文件、冻结的 transport budget、真实 latest collection 与 fresh readback
前，不在 production 启用采集 timer。采集 unit 只调用一次不带 dataset 参数的通用 cadence
planner：所有 registry 中 `active` 且 cadence 为 automatic 的绑定由同一计划器按预算、窗口和
receipt 状态选择；`on_demand` 绑定始终不会被 timer 自动执行。受审沪深主板
`cn.dataset.rt_min` 5MIN 是其中一个受控 canary：当前 registry 的 5,963 个冻结代码以每批 300
拆为 20 个确定性批次；resumable cursor v2 每轮最多推进 20 批，并以 bar_time 窗口在每根
5 分钟 bar 独立重置游标，因此一个 bar 内完整扫完 5,963 个冻结代码。只有带匹配
dataset/provider、config hash、frozen universe、batch identity 与
success/empty 状态的 receipt 才能推进游标；失败批次只在本数据集内优先重试，不能借用其它
dataset、其它 universe 或其它 config 的 receipt。这只证明配置在 intraday 每轮账号/provider 48、
rt_min 单 API override 60 的本地门禁内，不证明 provider entitlement、完整率、稳定性、低延迟或 production runtime
已接纳。每轮仍须保留实际 bar time、observed_at 和 receipt；上游晚一根 bar 时不得声明低延迟或执行
可用。它不是研究或交易 Universe。`cn.dataset.rt_min_daily` 的 security-master fanout 每批 5（单批最多约 5×241 根 1 分钟线，午后 payload 最大），`max_rows_per_attempt=1500`，resumable cursor v2 每轮最多 20 批；敏感扫描包络按该乘积定价且必须 ≤ 2,000,000 节点。确定性 `resource_budget`/`config_error`/`validation_failed` 失败批次不得优先钉死同一窗口的 pending 批次。该绑定经 `active_evidence` 恢复采集；回滚时切回上一 immutable registry/release 并更新 activation-wave
输入 hash；不删除既有 facts/receipts，也不新增服务或 timer。

`resumable_fanout.progress_mode` 默认 `complete_window`，保持既有合同与配置哈希。
`rt_min_daily` 的 major 3 显式选择 `session_day_rotation`：完整本地日窗口只用于验证和
游标，不发送给上游；采集开始与结束必须仍在请求日，逐行校验非空 `[ts_code,time]`
和真实 provider 时间，拒绝旧日、混日、未来或跨午夜响应。水位取真实最大 provider 时间。
在精确日/config/universe/batch/variant 内先采未尝试批次，再轮换最久未尝试批次；
成功、空响应和失败都不会永久占据前缀或终止当日刷新。预算、开市窗口和每轮 20 批不变，
不新增收盘补采。现有容量不足以承诺全市场或收盘完整覆盖。

七项单代码公告日期绑定显式选择 `partition_continuation`，以 binding-only
`partition_date_field` 验证返回日期等于实际请求日期、代码属于请求集合。财务公共 schema、
可空字段、主键和 as-of/range 合同不变。当前日期与最早未完成且已开始的旧日期交替，
每轮仍只选一个窗口；旧日期最多续采 31 天，不推造缺失日期。当前日期的空响应会继续轮换，
旧日期只有精确批次与 variant 的成功/空回执才计入已观察覆盖。新配置不能借用旧配置回执；
超龄债务保留但不再自动消耗预算，不能标成完整。该能力不改变每日容量不足的事实。
合同及失败测试入口见
[`resumable collection contract`](reports/2026-08-30-resumable-collection-contract.md)；
生产是否使用这些模式仍以 exact-release、真实 receipt 和认证 readback 为准。

`session_minute` 还必须同时命中 registry 的开市日历和配置的本地上午/下午窗口；
午休与收盘后均为 `not_due`，不得为“补一根分钟线”继续请求上游。在同一计划优先级内，
所有 `session_minute` 合同先于其它 automatic 合同执行；该排序只按 cadence class 决定，
不为某个 dataset、provider 或消费者增加专用分支。

`market=CN`、`timezone=Asia/Shanghai` 的 `session_minute`、`postclose_daily` 成功水位读取，在下一配置
开窗前或配置工作日之外，以前一配置工作日的既有收盘锚点计算 freshness。开窗时间和
工作日来自本物理 release 的 `config/provider_native_schedule.yaml`，复用既有纯解析器，
不接受环境路径覆盖；当前值为分钟 09:30、日频 16:30。到达开窗即恢复普通比较，不加
额外宽限、放宽 SLA 或修改 `data_through`。不完整的前一交易时段仍应过期；empty、
failed、event、Crypto 和 config mismatch 不获得该保护。固定配置缺失、畸形或符号链接
会 fail closed；已加载 policy 仅按 immutable release 缓存，变更需新 release/重启。
这不实现节假日日历，也不把上个交易日的最后一根 bar 称为实时新数据。问题与测试见
[开窗前读取时钟修正](reports/2026-08-31-cn-prewindow-clock.md)。

读取已结束的精确分钟槽位时，receipt cohort 的 `request_window` 可以保留该 dataset
合同要求的窗口（例如 `bar_time`）；同一 execution 内必须保持窗口、provider、config
和 `data_through` 一致，不能用空窗口或跨窗口 receipt 冒充当前槽位证据。

`daily_reference` 的下一日期窗口只适用于 registry 声明为 `trade_calendar` 的已知未来事实，
用于在 provider 已发布时提前写入下一交易日的 `is_open` / `pretrade_date`。其它日参考数据仍只
请求当前可用日期，不能因日历预取而创建未来数据 receipt。

`session_minute` 的最小成功间隔为 240 秒：五分钟 timer 在上一个窗口于临界时刻完成
（例如完成后 265 秒触发下一次）时，仍会规划下一窗口；失败重试、开市日历、窗口和预算
规则不变。当前 `standard` budget 每轮最多 64 个账号请求、64 个 provider 请求，
同一 provider API 最多 16 个请求；`intraday` 为 48/48/6（分钟 API override 60），
`event` 为 36/36/4（major_news override 16），`low_frequency` 为 16/16/4。
这些是配置上限，不是上游每日额度或实际已完成调用数。runner 仍是串行、每五分钟最多运行一次；历史
QuickSync 小响应探测不是当前 scheduler 容量或上游合同额度。发布前必须在目标 release 上证明完整
一轮能在下一次 timer 触发前结束；若超时、出现上游限流或任一 current-window receipt 失败，
回退到前一 immutable release，不通过重试或静默跳过伪造连续性。

`event` cadence 可选 `freshness_refresh_lead_seconds`（缺省为 0，当前生产配置不启用）。
只有正常 success/empty 的重观测可以提前：非零值将间隔取为
`min(minimum_interval_seconds, max(1, dataset.freshness_sla_seconds - lead))`；失败重试、
窗口、receipt、SLA 与账号/provider/API 预算不变。该值必须为非 bool 整数，且
`0 <= lead < minimum_interval_seconds`；其它 cadence 不允许非零值。提前量用于为 timer
触发与排队留余量，不代表 provider 更新更频繁。启用前须核验实际新增调用量、当前账号
每日额度与完整一轮运行时间；仅维持 per-run 上限不证明每日成本不增加。默认 0 保留旧行为。

回滚固定为先 `systemctl disable --now tradingdatas-provider-native-collect.timer`，再由已验证
release manifest 切回不含该 canary 的 release；不删除 SQLite facts 或 receipts。

planner 对每个 `dataset + provider + request_window` 只生成一个包含 registry 全部 request variants 的 plan；snapshot 数据集只要任一 variant 到期，就重新运行完整 cohort，不能因一个 sibling receipt 跳过其余 variants。scheduler 每次 run 生成显式 UUID root，并按稳定 plan ordinal 派生 window attempt root；one-shot collection 也必须执行完整 registry cohort，但只把自己的 root 视为单 window execution。生产 timer 只处理当前/最新 window；有界历史回填不占用它的周期。

收据的完整性校验按 dataset 隔离：某一 dataset 的损坏、伪造或时间非法 receipt 必须让该 dataset 以 `invalid_receipt_authority` 停止计划和 provider 调用；它不能为自身或其它 dataset 提供事实，也不能让无关 dataset 的受控计划停摆。该 skip 的 scheduler 输出只附带验证器已生成、稳定排序的 `reasons` 代码列表，不暴露 receipt payload、provider rows 或运行路径；其它 skip 的输出结构保持不变。

分批续采读取历史时复用 `validated_receipt_history_for_dataset`，仅扫描当前 dataset 的
完整回执历史；不能在每个分批任务中重复调用全目录 history loader。两者使用同一
authority 校验器，目标 dataset 的损坏回执仍 fail closed，不使用缓存、截断历史、跳过
校验或其它 dataset 的回执推进游标。该内部性能修正不改变 provider 预算、调度频率或
发布时长门禁；生产提速必须经自然轮次单独验证。

### `market_ingest_runs` 的收据读取索引

`market_ingest_runs` 是追加式收据运行日志。收据历史、evidence 与 journal 的验证读取必须按
目标 dataset 隔离：已知其它 dataset 的行不消耗该 dataset 的读取预算，未知 source 的 tombstone
行仍须纳入验证，避免以索引跳过未知 authority。`market_ingest_runs_source_idx (source)` 是可选的
单列索引合同：旧 SQLite 在索引缺失时仍可验证；目标 release 首次成功写入 receipt 时，会在同一
写入事务内幂等创建该索引。若存在同名但列定义不精确的自定义索引，schema 验证必须失败，不能
继续读取或静默替换。该变更不需要单独数据库迁移，也不表示 production release 已切换。

若已验证的 release 需要回退索引本身，可在维护窗口执行
`DROP INDEX market_ingest_runs_source_idx`；不得删除 `market_ingest_runs` 或任一 receipt/fact。
代码回滚继续遵循 immutable release 切换与同层 receipt/API readback，索引缺失在旧 release 中是
允许状态。

catalog 先取每个 envelope `source` 最近 100 条收据作为初始窗口。达到 100 条的已注册
source 对窗口内所有可识别的有效 execution 补齐兄弟收据，不能根据尚未完整验证的时间
上下文猜测只有最旧一组被截断。初始窗口中的无效收据全部保留；初始读取及补读共用
400,000 条原始读取预算，补读中重复命中的行也计入预算，超限立即 fail closed。

随后按 envelope `source` 与 payload `dataset_id` 建立数据集相关行索引；跨数据集
envelope/payload 不一致必须同时进入两个相关数据集，不能因性能索引而被跳过。经补齐
并明确标记完整的物理 execution 必须从 `physical_call_index=0` 开始；重复、内部缺口、
混合 physical/non-physical 状态、context 漂移或 retry 序列不一致仍报
`receipt_execution_inconsistent`。其它读取入口原有的连续后缀校验不因此放宽。
dataset 与 interface 投影共用扩展后的收据集合；本规则不补写、删除或重排历史 receipt，
不把 provider/storage 失败改成成功，也不证明上游数据完整或连续健康。

对于已经执行的 dataset，scheduler summary 可附带 `receipt_provenance`：它只按本轮已持久化且通过同一 receipt validator 的 receipt ID 投影 `status`、`returned`/`validated`/`rejected`/`committed` 计数、稳定的 `error_layer`、原始结构化 `error_codes` 与 `validation_reasons`。无法通过验证的 receipt 只保留其稳定 reason code，计数字段为 `null`；`validation_failed` 默认归入通用 `ingest_validation` 层，`transport_error` 归入 `transport` 层，只有持久化证据证明更具体层级时才细分，未持久化时不推断确切谓词；读取 provenance 失败不会改变采集结果。失败的 scheduler dataset 摘要还可携带经上游 outcome 边界清洗、单行且长度受限的 `error_message`，便于区分安全的 transport/provider 诊断；它不写入 receipt、不会替代 receipt authority，也不包含 provider payload、请求凭据或本机路径。

非可恢复 fanout 的覆盖缺口在公开采集路径中保留顶层 `validation_failed`，并附带脱敏的
`validation_fanout_coverage_incomplete` reason code；scheduler 的 `error_layer` 仍为
`ingest_validation`，不会暴露 fanout 值、provider rows、摘要或路径。声明
`resumable_fanout` 的分钟批次允许保留请求集合内实际返回的严格子集，单只股票缺失只降低
该批 coverage；停牌代码带回的历史最后 bar 也按 `[ts_code,time]` 独立保留。越界代码、重复
主键和非可恢复批次的跨日快照仍失败。允许空结果和禁止空结果继续遵循各自既有策略。

内容流页面全部早于当前窗口时，既有窗口过滤可能移除所有行。允许空结果的数据集此时写入
`empty` terminal receipt（`data_through=null`），聚合结果同样为 `empty`；不得把零行交给
非空行写入器而误报 `validation_failed`。混合页面只保留窗口内行，未来时间、重复主键和
上游失败仍按原合同拒绝，禁止空结果的数据集仍失败。这里不声明原始页面覆盖完整。

生产 one-shot 必须通过安装好的 collector service 启动，使 systemd 按 unit 合同创建并回收
`RuntimeDirectory=tradingdatas`。不得从 shell 直接执行 runner 却继续使用
`/run/tradingdatas/collect.lock`；这种调用绕过 systemd，运行账号无权创建 `/run` 子目录。
隔离验证如需直接运行，只能使用该隔离目录内的私有 lock path，不能借此启用 timer、改变
正式 cadence 或新增第二套调度入口。

生产 SQLite 的 journal mode 由可写采集连接请求 `PRAGMA journal_mode=WAL`；catalog/query
的已验证快照在检测到 `-wal`/`-shm` sidecar 时只使用 `mode=ro`，不再附加 `immutable=1`
（SQLite `immutable=1` 会跳过 WAL，可能读到未 checkpoint 的陈旧主文件）。connect timeout
仍为 180 秒，与 authority lock 等待上限一致，不另设 synchronous 或其它耐久性 pragma。
本仓库变更只把该行为写进代码与测试，**不**通过 SSH、deploy script 或 `current` 切换去改
广州生产库的 journal mode。

生产文件在独立的 write-pause + exact-main release 步骤完成前仍可能是 rollback-journal。
该运维步骤不属于本代码 PR：停采集 timer、切到含 WAL 请求的 immutable release、重启
API、再由一次有界可写 open（或该 release 下的首轮 collect）完成 journal 切换，然后用认证
catalog/query 回读。切换窗口内不得让仍使用无条件 `immutable=1` 的旧 reader 对着已进入
WAL 的库提供服务。回退 journal mode 不是默认动作；若必须回到 rollback-journal，同样要在
停写下 checkpoint 并确认 sidecar 已清空。目录/查询的长只读快照仍可能与写事务短暂重叠；
超时后仍必须失败并写稳定错误码，禁止跳过事务 readback 或改写已有 receipt。宽字段（超过 256 个声明
字段）的 transport 敏感信息扫描使用独立 400 万节点硬上限，普通合同继续保持 200 万节点；
两者仍受 registry 行数、16 MiB provider response、64 MiB batch 和深度上限共同约束。

## Activation wave

`config/provider_native_activation_waves.v1.yaml` 是 repository-owned 的受审波次
清单。它只记录 canonical `dataset_id` 与 runtime registry、schedule 的输入 SHA-256；
不得放入 provider 参数、字段、token、request values 或任何 dataset-specific 行为。选择
`--activation-wave <wave_id>` 时，runner 会在打开 SQLite、执行 provider 调用或产生写入前
一次读取 registry 与 schedule 原始字节，先核对输入 hash，再从同一份字节解析实际用于
active 检查、规划和执行的对象，避免路径复读或外部对象造成合同脱绑定。清单内所有 wave
都会在选择前验证 exact keys、canonical ID、排序、全局去重与 active/entitled 状态；未知
wave、布尔版本、别名、额外字段、非 active/entitled 项或任一输入 hash 漂移均 fail
closed。波次外的 active dataset 以
`not_selected` 记录，global flock、planner/runtime budgets、retry、receipt 和公开输出
redaction 均不变。

省略 `--activation-wave` 时保持完整 automatic scheduler 行为；这是正式采集 unit 的唯一入口。
`pilot_existing` 仅用于受控、只选择当前窗口的历史复现，不是 production 范围开关。其中的
`cn.dataset.rt_min` 5 分钟 canary 不是新增 entitlement、全市场分钟覆盖、研究/交易
Universe 或低延迟执行证据：每轮必须保留实际 bar time、observed_at 和 receipt，不能把上游
延迟伪装成实时数据。上述 5,963-code / 300-per-batch / cursor-v2 只是受审的 registry 请求形状；真实供应能力
仍须由目标 release 的 provider、receipt、catalog/query 与 consumer fresh readback 分层证明。

正式 registry 还可以声明受审的 `dependency_seed_authorities`。它只绑定已持久化
receipt、来源字段/schema 与明确列出的依赖 API；编译器仅把这些依赖标为
`probe_state=executable`、`ingest_contract_state=ready`，仍保持 `activation_state=paused`。
未列出的 sibling、缺少 receipt authority 或其它未解析 requiredness/anchor 的 API 继续
fail-closed，不会因为同一 source dataset 自动扩张。receipt payload、provider rows 和 token
不写入仓库；receipt_id 与 data_through 作为不可变 authority binding 保留。Controller 发布前
必须用同一 registry/compiler、collector receipt 与 catalog/query 做有界 readback。
raw HTTPS sidecar 可以引用已经 formal 注册的 dependency seed authority，而不必在同一批次再次
把 seed producer 作为 result 发出；compiler 仍逐字段精确比较 dataset、field、schema、receipt_id
与 data_through，并要求 dependent API 已在 authority 的显式清单中。不匹配、未列出的 sibling
或缺少 fresh result 的 API 都保持 fail-closed/paused，不会由 seed authority 推断 provider rows
或扩大 activation。
只读 plan 可按以下方式检查：

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python tools/run_provider_native_schedule.py --activation-wave pilot_existing
```

`daily_reference` 不假设上游提前提供下一自然年的完整交易日历；历史覆盖仍由
bounded backfill 逐段补齐。固定未来天数不能被当成 provider 能力事实：只有
registry 明确声明、transport 实际观测且独立回归覆盖的日历窗口才能受控请求下一日。
future-empty 响应必须按既有完整性合同诚实处理，不能把其它日参考数据推进到未来。

## 国际新闻原始发布时间与精度

`global.news.flash` 的 `1.1.0` minor合同增加三个可空文本字段：
`provider_published_at` 保留上游原发布时间字符串，`raw_item_json` 可还原规范化前
完整item，`publication_precision` 表示原值的 `date` / `datetime` / `time` / `unknown`
精度。仅全球新闻显式启用本地provenance处理模式，模式参数不得发送上游；国内新闻
及其它Firecrawl调用保持原合同。

旧 `published_at`、`published_local`、主键和默认投影保持兼容。源值只有日期或时间时，
旧字段只能视为归一化锚点，不能当作已证明的发布时间instant；使用者必须结合精度
和原值解释。旧行没有新增字段时仍保留 `missing_field` 质量证据，不做通用校验豁免。
不离线回写历史事实/回执；全球新闻沿用 `append_only`，真实重采按payload hash保留
新版本及事务receipt，同一业务主键可同时存在旧、新payload，不能按content_uid只取
第一行就断言已读到新字段。回退旧release依赖保留旧合同成功回执；只有新合同回执时，
旧registry仍会以 `active_config_receipt_mismatch` 降级，不得删除新事实来伪造恢复。

此合同不证明网站列表完整性。`response_completeness=null`、query的
`freshness_watermark_unverified` / `response_completeness_unverified` 以及
`data_through=null` 均保留；缺失或不可解析发布时间仍按既有规则失败，不借用采集
时钟补值，也不放宽敏感内容或资源预算。源码合同、候选测试不等于生产启用；仍需
精确release、真实provider新回执及认证读取这三个新增字段分别验收。

## 有界 one-shot batch

`tools/collect_provider_dataset.py --batch-file <external-json>` 是唯一的按需批量
采集入口，不新增 systemd unit、timer、cron 或公共 API。外部 JSON manifest 固定为：

```json
{
  "version": 1,
  "items": [
    {"dataset_id": "cn.example.dataset", "request_window": {}}
  ]
}
```

最多 32 项，`dataset_id` 必须 canonical、唯一且排序；每项只能使用该 registry 已声明的
window keys。plan 模式会先校验整批所有 item，失败时不会构造 provider client 或打开
SQLite；execute 模式随后串行调用相同的通用 adapter，每个 dataset 保持自己的
facts + receipt transaction。manifest 不得含 token、provider API name、fields、路径或
业务逻辑，也不进入仓库。`on_demand` 仍不会被 scheduler 自动计划：只有已验证的
window 被明确放进该 manifest，才会采集。

生产按需 batch 复用唯一的 `tradingdatas-provider-native-collect.service`，不创建第二个
service 或 timer。该 unit 以 `RuntimeDirectoryPreserve=yes` 保留其私有 `0700` runtime
目录，使 operator 能在 unit 空闲时安全暂存下一次手工启动所需的 selector；普通 timer
没有 selector 时仍走原 cadence planner。发布 operator 只能在该 unit 空闲时，在其 `RuntimeDirectory` 写入由
`tradingdatas` 账号拥有、`0600`、无链接且单链接的
`/run/tradingdatas/on-demand-batch.json` 与 `/run/tradingdatas/on-demand.env`。后者只能
逐字节指定该固定 batch 路径，不能含任何其它环境变量；手工启动同一 service 后，通用 dispatcher 先消费 selector，再以
同一 `/run/tradingdatas/collect.lock` 串行执行 batch。无 selector 时 timer 保持原有 cadence
planner 路径。无论成功、合法 empty、失败或 validation，batch 文件均在本轮结束时删除，
避免下一次 timer 重放。batch 仍需先经过同 release 的 no-write plan，且不得含 token、
provider API 名、字段或专用行为。

按需 batch 的合法 empty 是当前窗口的有效采集事实，因此该 service 将 CLI 的 empty
exit code `3` 与并发 busy code `75` 都视为完成；validation 与 provider failure 仍为失败，
不会被该映射掩盖。

## 只读 onboarding 与稀有分区审计

`tools/report_dataset_onboarding_status.py` 只读取已验证的 SQLite 快照、runtime registry 与可选的脱敏 formal API snapshot；不得调用 provider、写数据库或触碰 API/timer。可选的 `config/readiness_partition_audit.v1.json` 预注册少量已经完成的精确分区，汇总 receipt、provider、行数、身份空值/重复、上限与 terminal-empty 事实。它不是采集 manifest，也不会激活、调度或提升数据集。

普通读取仍仅按 receipt authority 做单遍历。只有 onboarding、合同漂移、事故恢复和每日 scrub 才执行独立双遍历验证。合法 empty 只证明该观察窗口没有数据；历史读取默认仍为 `observation_only`，除非另有 immutable receipt、as-of、first-seen 与 revision-vintage 的完整证据，不能据此声称 PIT 或非空完整性。

## Release 与回滚身份

`tools/release_manifest.py` 只管理 Git release 字节与 `current` 指针，不安装 unit、
不读取凭证、不打开 SQLite、不调用 provider，也不启停服务或 timer。manifest 由 clean
Git HEAD 的 commit、tree 和全部 tracked blob 生成，保存在 release 目录之外；release
必须是以完整 commit 命名的直接子目录，且只包含 manifest 声明的文件。目录固定
`0555`，普通文件 `0444`，Git executable 为 `0555`，无链接、额外文件、`.git` 或
`__pycache__`。验证器从 commit object 重算 commit/tree 关系，从 manifest entries 重算
Git tree，并从 release 实际字节重算每个 Git blob 与 SHA256；manifest 本身也必须匹配
`--expected-uid/--expected-gid` 且不可被 group/world 写入。

发布前的一致性检查只比较 manifest 声明的精确 Git tree 文件及其 mode/blob/hash，不能先
对普通服务器 worktree 做整目录相等比较。现役 worktree 中未纳入 manifest 的缓存、运行输出
或其它已登记未跟踪资产必须原样保留并单独报告；它们既不能进入 release，也不能因发布而被
清理。只有 manifest 声明文件发生漂移才阻断该 release。

生产 release 内的任何 Python 诊断都必须同时设置
`PYTHONDONTWRITEBYTECODE=1` 并使用 `python3 -B`；只读诊断也不能在 immutable release
生成 `__pycache__` 或 `.pyc`。诊断前后都要运行 trusted `verify-current`，并检查 release
内不存在 manifest 外文件。若误生成缓存，只能先冻结精确路径、字节数和 SHA-256，确认
全部为 manifest 外缓存且声明文件零漂移后，再删除精确缓存目录并重新验证；不得借此做
广义目录清理。

本地从 clean checkout 生成确定性 manifest。构建、服务器验证和切换必须使用已审查的
trusted verifier，不能从尚未验证的 target release 执行 `release_manifest.py`；常规升级
使用当前已验证 release 中的 verifier，首次 bootstrap 则先把本地已审查 verifier 作为
独立文件传入并核对其 SHA256 后再运行：

```bash
python3 tools/release_manifest.py build \
  --source-root /absolute/path/to/TradingDatas \
  --output /private/tmp/<commit>.release.json
```

### Source 与 API readiness preflight

每次发布必须读回 GitHub `main`、将要 archive 的 target commit 与 clean working tree。
服务器可用时，先从 clean source checkout 执行受限的 `fetch origin main`；该通道只能使用独立、
root-only 的只读 deploy key，以及严格校验的 GitHub host key，不得复用个人 GitHub key、在
Git config/环境变量中保存 token，或把 source checkout 当作运行中的 release。若 fetch 或
commit 比对失败，服务器 checkout 不能被当作 target；此时可使用已验证为 GitHub/main 的本地
clean commit，传输它的受控 Git archive 与 manifest 到新的 immutable staging 目录。不得用旧
release、已运行 API 或未经核对的本地文件猜测源码身份。

重启 API 后，发布脚本必须在一个短、有界的循环内等待 loopback `/v1/catalog` 返回预期的
认证状态；连接被拒绝只表示 listener 尚未就绪，不能立即将已验证 target 回滚。循环超时、
非预期认证状态或 service/timer 未恢复时才执行既定 rollback，并分别记录 pointer、unit 和
HTTP/consumer readback。

### 发布通道选择（强制顺序）

生产发布的权威通道是：**本地已验证的 clean Git commit -> `marketgraph-main` 的
immutable release staging -> manifest/rollback 验证 -> 原子 `current` 切换 -> service
与消费者 readback**。目标 ECS 使用 Finance `PRODUCTION_ACCESS.md` 登记的 `marketgraph-main`
（严格 host-key 校验）进行 root-only
release 操作；`marketgraph-server` 仅可用于最小权限诊断。服务器工作树能否从 GitHub 拉取，
只是可选的源码同步能力，绝不能作为“是否可以发布”的前置条件或阻塞结论。

当服务器 GitHub deploy key、known_hosts 或网络异常时，保留已审查本地 commit 的 Git archive
与其 manifest，通过同一已核验 SSH identity 写入一个**不存在的新 commit 目录**，再按本节验证；不得
覆盖已有 release、复制未受 manifest 覆盖的文件，或把服务器 checkout 当作未经核对的发布源。
Aliyun CLI 是 ECS 身份、实例状态和应急控制面的备选验证渠道，不替代 release manifest，也不
改变 SSH host identity 的校验要求。每次发布记录必须分别写明：选择了哪条通道、GitHub/main
状态、server checkout 状态、active release、rollback release、service/timer 与 HTTP/consumer
readback，避免把任意单层状态合并成“已部署”。

服务器 staging 完成且尚未切换 `current` 时，以 root owner 身份只读验证：

```bash
/opt/tradingdatas/venv/bin/python3 \
  /opt/investment/releases/tradingdatas/current/tools/release_manifest.py verify \
  --release-root /opt/investment/releases/tradingdatas/<commit> \
  --manifest /opt/investment/releases/tradingdatas/manifests/<commit>.json \
  --expected-uid 0 --expected-gid 0
```

`switch-current` 只允许从已验证的 rollback manifest 切到已验证的 target manifest；
在 releases 根目录加排他锁，以相对 40 位 commit symlink、`os.replace` 和目录 fsync
完成原子切换，post-switch 失败时恢复旧 pointer。执行前必须由外部 safe-release
preflight 证明 API/collector 均 inactive、timer disabled、18082 切换方案与旧服务回滚
已冻结。重复验证使用 `verify-current`；它持共享锁覆盖 pointer 读取、release 验证和
pointer 重读，不能与协作切换交错产生伪 readback。manifest 不记录 secret 内容或 SQLite hash；
回滚不覆盖 SQLite，也不恢复旧 official-direct collector。

早期 bootstrap 可能遗留一个绝对 `current` pointer。普通 `verify-current` 与
`switch-current` 继续只接受相对 40 位 commit，不兼容或跟随该遗留形式。只允许在
API/collector 均 inactive、timer disabled，且 rollback release 与外置 rollback
manifest 已独立验证后，使用已审查并核对 SHA256 的 trusted verifier 执行一次：

```bash
/opt/tradingdatas/venv/bin/python3 \
  /path/to/reviewed/trusted-release_manifest.py normalize-current \
  --releases-root /opt/investment/releases/tradingdatas \
  --rollback-manifest /opt/investment/releases/tradingdatas/manifests/<rollback-commit>.json \
  --expected-uid 0 --expected-gid 0
```

该命令只接受原始 pointer 逐字等于 canonical absolute
`/opt/investment/releases/tradingdatas/<rollback-commit>` 的单一遗留情形，在同一排他锁
内验证 rollback release 后原子改写为相对 `<rollback-commit>`，目录 fsync 并读回。
任意其它绝对路径、不同 rollback、已经相对的 pointer、链接链或不安全 releases root
都必须拒绝。相对 pointer 完成 `replace`、目录 fsync 和 post-readback 后即为提交点；
提交点之前的改写失败会恢复原绝对 pointer，恢复失败必须高声失败并停止发布。提交点
之后的 unlock/close 只是 cleanup，不得反向覆盖已提交 pointer 或把成功伪报为失败；
关闭前必须先解绑本地 descriptor 状态，不能因 close-after-close 异常误关复用的 FD。
成功后立即用同一 rollback manifest 运行 `verify-current`，再进入常规
`switch-current`。该 normalization 不安装 unit、不启停服务、不读取凭证、不打开或
覆盖 SQLite，也不能用作第二种常驻 pointer 格式。

systemd 仅从 `current` 启动入口脚本。入口立即解析到同一物理 immutable release，
registry 与 schedule 不接受 `/current/config/...` 环境覆盖；execute 模式也拒绝非本物理
release 的 `--schedule-config`，避免代码/配置跨版本混配。

`provider=tushare` 与 `transport_service=quicksync` 是两个独立身份。Tushare
官方文档只负责 dataset/schema/cadence 参考；QuickSync 文档与真实有界探测才负责
endpoint、认证、权限码和流控事实。凭证只建立账号身份，不代表接口权限，
`entitled_active` 也不是购买或计费状态。并发、分钟/每日额度、scheduler budget 和
DNS failover 都从目标 release 配置及带时间戳的有界探测读回，不在长期运维文档中
硬编码。timer 仅在 target release 的 preflight、rollback 与 server readback 通过后
显式启用，单个接口成功不会自动扩权。

## 运行顺序

1. 安装代码与只读配置；
2. 以独立运行账号初始化全新 SQLite schema（不会迁移或读取旧库）。入口使用
   绝对路径，因此不依赖调用方当前目录：

   ```bash
   /opt/tradingdatas/venv/bin/python3 \
     /opt/investment/releases/tradingdatas/current/tools/init_tradingdatas_store.py \
     --database /opt/investment-data/tradingdatas/read_model/provider_native.sqlite
   ```

3. 创建 `root:tradingdatas` 持有、权限为 `0750` 且不含 symlink 的
   `/etc/tradingdatas` 父目录。API 认证加载器会逐级打开并绑定目录，只有执行位的
   `0710` 不足以完成安全读取；Tushare loader 当前只使用 `O_NOFOLLOW` 绑定 Token
   叶子文件，因此发布 preflight 必须另外拒绝父目录 symlink。再创建由
   `tradingdatas:tradingdatas` 持有且权限严格为 `0600` 的
   `/etc/tradingdatas/api_tokens.json`、`/etc/tradingdatas/token_salt` 与
   `/etc/tradingdatas/quicksync.token`。QuickSync token 必须是单一硬链接的普通文件，
   文件 owner 必须等于采集进程的有效 UID；因此采集进程会拒绝 root-owned 或
   其他账号持有的 token。采集 runner 与 API service 都使用独立 `tradingdatas` 账号，使采集写入
   和 API 只读访问协作于同一 SQLite 权限模型，不以 root 运行采集器。内部
   loopback 调用同样必须携带显式 token 或 JWT；没有 localhost 免认证路径；

   TradingAgent 使用独立的只读 token，不能复用 bootstrap 或 QuickSync 凭证。token 明文的
   持久源固定为 root-owned、`0600`、单链接普通文件
   `/etc/tradingagent/tradingdatas-read.token`；API registry 只保存带
   `/etc/tradingdatas/token_salt` 的 PBKDF2 hash、`tenant_id=tradingagent`、`scopes=[read]`
   和有界并发。运行时文件固定为
   `/run/secrets/tradingagent/tradingdatas-read.token`，必须是
   `tradingagent:tradingagent`、`0600`、单链接普通文件，父路径不得含 symlink。生产使用
   最终切换后，TradingAgent release 提供的 `/etc/tmpfiles.d/tradingagent-runtime.conf` 只拥有
   `root:tradingagent 0710` runtime 父目录合同；TradingDatas credential publisher 的
   `/etc/tmpfiles.d/tradingagent-secrets.conf` 只拥有从持久源重建 leaf 的 `C` 规则。两个文件
   不得重复定义 parent。配置、日志、evidence、任务消息和环境变量均不得包含 token 值。
   轮换分为两个有回滚的阶段：先在 root-only staging 生成新 credential，把新旧两个 hash
   同时注册并重启 API，证明旧/新都可读而 canonical source 与 runtime 完全不变；只有消费者
   明确给出 freeze-window GO 后，才原子提升持久源、父目录和 runtime leaf。消费者 metadata
   与 bounded parity 通过后再删除旧 hash、重启 API，并证明旧 credential 为 401、新
   credential 为 200。consumer 尚未暂停且 legacy front 尚未隔离时，阶段 A 失败可以恢复
   旧 registry、source/runtime 与 tmpfiles 合同；一旦 TradingAgent 已暂停 recurring job、
   隔离 legacy front 并进入 publisher freeze，后续失败必须保持 consumer unavailable、freeze
   和零 holder，只能保存证据并受控前滚，禁止恢复旧 credential、旧 runtime leaf、旧 front、
   8082 fallback 或旧 tmpfiles owner。两种阶段都不得改 SQLite 或临时放宽权限。
4. 在不读取凭证、不调用 provider 的情况下，从目标 immutable release 的物理
   `FINAL` 路径重新编译 registry。`FINAL` 必须是以完整 commit 命名的直接目录，不得是
   `/current`、其它 symlink 或可写 checkout。compiler 的 `--output` 必须指向 release 之外
   由 `mktemp` 创建的私有临时文件，不得使用会改写 checked-in registry 的默认输出：

   ```bash
   (
     set -eu
     TARGET_COMMIT="<40-character-commit>"
     test "${#TARGET_COMMIT}" -eq 40
     case "$TARGET_COMMIT" in *[!0-9a-f]*) exit 1 ;; esac
     FINAL="/opt/investment/releases/tradingdatas/$TARGET_COMMIT"
     test -d "$FINAL"
     test ! -L "$FINAL"
     REGISTRY_VERIFY="$(umask 077 && mktemp /tmp/tradingdatas-registry.verify.XXXXXX)"
     trap 'rm -f -- "$REGISTRY_VERIFY"' EXIT
     trap 'exit 1' HUP INT TERM

     PYTHONDONTWRITEBYTECODE=1 \
       /opt/tradingdatas/venv/bin/python3 \
       "$FINAL/tools/compile_provider_native_registry.py" \
       --upstream-contracts "$FINAL/config/tushare_upstream_contracts.v1.yaml" \
       --observations "$FINAL/config/quicksync_interface_observations.v1.yaml" \
       --output "$REGISTRY_VERIFY"
     cmp --silent \
       "$REGISTRY_VERIFY" \
       "$FINAL/config/provider_native_dataset_registry.yaml"

     rm -f -- "$REGISTRY_VERIFY"
     trap - EXIT HUP INT TERM
   )
   ```

   `cmp --silent` 成功才证明重建结果与该 release 内 checked-in registry 逐字节一致；
   无论成功、失败或中断都必须清理临时文件。验证过程不得从 `/current` 执行 compiler，
   也不得改写 release 内任何文件。目标 release 必须从同版本的
   `quicksync_interface_observations.v1.yaml` 重建其 190 个 runtime contract，并与
   checked-in registry 逐字节一致；active/paused 的精确计数由该次目标 release 的读回
   决定，不能在本说明中写死或由旧候选推断。
   scope v2 的产品目录已扩为 222，但新增 32 项在正式合同、HTTPS entitlement 与
   runtime registry 接线完成前只允许 `unobserved/paused`，不得由 MCP 可见性自动加入
   采集计划。观测配置必须保持
   `interface_probe_scheme=http`、`production_ready=false` 和生产 transport
   blocked；它不读取 Token，也不是正式 HTTPS 采集证明。旧 manual entitlement probe
   与 policy 已退役；request-profile 配置与 resolver 仅作官方输入映射迁移资料，既不是
   entitlement/activation authority，也不得接入 collector、scheduler 或生产命令；
   runtime contract compiler 与 HTTPS probe plan 还必须分别从磁盘重新读取并核对其
   official/request/transport/reviewed 或 registered 四类冻结输入；调用方传入的映射不能
   绕过原始字节 SHA。seed receipt 的 producer schema 必须与 registry 精确一致；

   HTTPS probe 的 `--scope executable` 仅从同一冻结 190 项 plan 中选择已经标记
   `probe_state=executable` 的条目，保留 blocked 条目及其原因，不改写 registry、SQLite、
   activation 或 scheduler。它用于一次批量复验安全请求形状；`all` 仍在任一 blocked 条目
   存在时 fail closed。若完整选择会超过单次响应字节预算，调用方必须保持同一 plan 和
   SHA-256，使用 `--start-index` 与 `--max-interfaces` 生成连续、不重叠的受控批次；每份
   evidence 都会保留完整 scope 的 `planned/executable` 数及该批的 `selected/executed` 数，
   不能把一个批次的成功写成全体接口成功。
   当 `selected < executable` 时，该 evidence 只能提升其 `results` 中实际成功、且已具备
   ingestion contract 的接口 cohort；它必须保留既有 active 集合，且绝不能提升未执行接口。

   若上游失败响应被 transport 判定为含敏感回显，probe 只可把它记录为失败，使用
   `response_redacted=true` 与 `response_sha256=null`；不会保存响应正文或降级为成功。
   成功或有效空响应仍必须携带合法 SHA-256，否则整批 fail closed。

   HTTPS activation evidence 必须保存在仓外，由调用方先核对 sidecar SHA-256，再通过
   显式 `--activation-evidence /outside/repository/path` 传入；现有 QuickSync probe 直接
   写出的 evidence sidecar 可作为该输入，compiler 会重新计算其结果、cohort 与 activation
   projection，不能信任调用方自报投影。仓库、release、CI fixture 和 formal 编译均不得内置
   或默认寻找真实 evidence。只有同时指定
   `--compilation-mode preactivation_candidate` 且把 `--output` 指向仓外私有临时路径时，
   compiler 才会生成 canary registry。正式 release 的 activation 只来自同版本、已审查的
   `active_evidence` 配置；因此 active/paused 计数必须由 immutable target 的 compiler 和
   checked-in registry 共同读回。宽 schema 候选必须在编译器安全上限内自动下调每批行数，
   且在 fresh release/readback 前不是 production activation。受控 one-shot 不会把 active
   状态等同于 ready；collector timer 的实际状态必须由当前 release/runtime readback 判定，
   而不是仓库文本、历史 sidecar 或 CI fixture。历史 release SHA、active/paused 数量与
   timer 状态只保留在 Git 历史、带时间戳的 `STATUS.md` 或生成报告中。
5. 运行一次受控 latest/current collection；
6. 验证 facts、receipts、catalog/query 与 impaired negative cases；
7. 在 generic runner 独立验收后安装唯一采集 service/timer；仅在发布 preflight 和回滚验证
   都通过后，按数据集 cadence 显式启用。

   生产 collector unit 不传入 activation wave 或 dataset 参数，始终由同一 registry-driven
   planner 选择所有 automatic cadence。发布前必须在目标 release 和正式 SQLite 上做 plan
   readback：计划只能包含 active/entitled automatic bindings，`on_demand` 必须显式跳过；超出
   本轮 budget 的计划项必须是 `rate_budget` skip，不能生成失败 receipt。再以受控 one-shot 或
   一个完整 timer 周期验证 facts、receipts 和 API readback。`direct_wave_3` 等保留作有界历史
   batch 选择，但其 `on_demand` 合同不会被 scheduler 自动执行。
8. 正式 QuickSync 凭证、权限/流控 evidence、受控 latest collection 和 API readback 通过后才启用 timer，并观察完整 cadence 周期；
9. 如有批准的历史需求，再运行独立、有界且可回滚的 backfill manifest；它不得影响当前 timer 的 latest-window 可用性。

`POST /v1/query` 的稳定性证明必须符合数据集粒度。对于 `daily`、`sw_daily` 等按
`trade_date` 分区的数据集，latest/current readback 使用显式 `eq` 或有界日期范围并完整
翻页；不得用无筛选第一页成功代替完整查询证明。无界跨多分区读取仍受 SQLite VM-step
预算约束，消费者应缩小日期范围，不能通过无限重试或旧 route fallback 绕过。非分区
snapshot（如 security master）及有界 calendar 可按 registry 默认排序完整翻页。

## 管理控制台公网回源

管理控制台前端继续由 Cloudflare Pages 提供，生产 API 主机名固定为
`td-admin-api.tradingagent.cc`。管理 API 本体仍运行在广州 ECS 的
`tradingdatas-admin.service`（端口 `18084`）；公网回源故障不得通过改 Token、改数据库、
改采集 timer 或把浏览器降级为直连 HTTP IP 处理。

当广州到 Cloudflare edge 的直连 Tunnel 持续握手超时时，可以启用独立的新加坡中继回源：

- 广州 `tradingdatas-admin-relay-origin.service` 只建立到中继机
  `127.0.0.1:18084` 的 SSH reverse forward；它不复用、重启或修改数据采集使用的 SOCKS
  relay。
- 中继机 `tradingdatas-admin-api-tunnel.service` 只把既有 Cloudflare Tunnel 路由到上述
  reverse-forward origin；Tunnel token 只保存在中继机 root-only 文件中，不进入仓库、
  systemd unit、日志或运行报告。
- 两个 unit 都必须在启用后分别读回 `active` 与 `enabled`；中继机 origin 和公网
  `/portal/api/me` 无凭据均应返回 `401`，管理 API CORS preflight 应返回 `204`。
- 该链路只承载管理/客户控制台 API，不改变 `127.0.0.1:18082` 数据 API、本地 SQLite、
  collector service/timer、provider 凭据或任何用户 API Key。

回退时先在中继机执行
`systemctl disable --now tradingdatas-admin-api-tunnel.service`，再在广州执行
`systemctl disable --now tradingdatas-admin-relay-origin.service`。不得删除 Token 文件、
修改 DNS、重启采集 timer 或清理 facts/receipts。回退后重新验证广州本地 `18084` 的
`401`，再单独修复或恢复广州直连 Tunnel；公网主机名恢复前不能宣称控制台可用。

## 公开站 Account 同站会话桥接

`public-web/worker/index.js` 包含 `/api/account/*` 同站代理。仓库只提交非密钥上游
binding；加密密钥必须通过 GitHub Actions secret 注入 Cloudflare Worker。仅代码合入或
Worker 静态页发布不能声称会话桥接已启用。启用前必须：

1. 确认目标 Worker 是 `tradingdatas`、目标 route 是 `tradingdatas.com`，且现有静态资源
   回退可回滚；
2. 将高熵 `SESSION_ENCRYPTION_KEY` 保存为 GitHub Actions repository secret；发布工作流
   在 `public-web` 工作目录内以显式 `--config wrangler.jsonc` 写入同名 Cloudflare Worker
   secret，不能进入 shell history、仓库、Actions 输出、Worker vars 或运行报告；
3. 确认 `public-web/wrangler.jsonc` 中的非密钥 Worker binding 为
   `ACCOUNT_API_BASE=https://td-admin-api.tradingagent.cc`，并确认该 origin 的无凭据 Portal
   readback 仍为 `401`；
4. 发布 immutable main SHA，依次验证登录 exchange、`/api/account/me`、usage、key list、
   create/disable 的后端权限语义，以及 `DELETE /api/account/session` 后再次读取为 `401`；
5. 在浏览器确认响应 cookie 为 `HttpOnly; Secure; SameSite=Strict; Path=/api/account`，
   Account 页面及持久化 `localStorage` 都不再持有原始 key。不得把前端显示“安全会话”当作
   上述响应证据。

任一项失败时，先移除或禁用这两个 Worker binding 使桥接回到显式 `503
identity_gateway_unavailable`，再重新发布上一已验证公开站 SHA。前端只会回退为当前标签页
`sessionStorage` 的兼容连接；不得因此修改客户 key、管理 API、数据 API、采集 runtime 或
SQLite。完整邮箱身份、跨设备 session list、服务端单会话 revoke 和审计仍是独立后续发布。

运行证据的校验清单不得包含清单自身。payload 全部关闭后生成仅列 payload 的
`PAYLOADS.sha256`，再用独立 sidecar 记录该清单的 SHA-256；交接前必须分别执行
`sha256sum -c PAYLOADS.sha256` 和 sidecar 校验。若已生成自引用或不自洽清单，保留原件
作为事故证据，在相邻只读目录新增修正版；若修正版使用相对 payload 路径，必须从原
payload 目录执行 `sha256sum -c /absolute/fix/PAYLOADS.sha256`，再进入修复目录校验
sidecar。不得覆盖原始 payload 或把失败清单改写成通过。

## 公开站 Research 静态页与教程下载

`public-web` 的研究文献库（200 条记录、24 篇导读、3 个虚构教程）在 `main` 的 PR
#385 已合入代码树。内容合同与维护流程见 `docs/product/RESEARCH_LIBRARY.md`。
合入、CI 绿和本机 `npm run build` 都不能代替公开 Worker 发布与资源回读。

发布前在 `public-web` 目录执行：

```text
npm run test:sites
npm run build
python3 scripts/verify-tutorial-notebooks.py
```

`npm run build` 在 Vite 与 Sites 准备之后生成 208 个带 bilingual
title/description/canonical/OG 的目录 HTML，以及
`dist/client/downloads/research/<tutorial-id>/` 下的 `inputs.json`、
`example.mjs`、`tutorial-zh.ipynb` 与 `tutorial-en.ipynb`。不要手改 `dist/`。
构建投影会从读者包中去掉内部 `evidence`/`verifiedAt`/`readiness`/`checks`。

生产读回应分别打开精确当前 SHA 的：

- `/research/` 与 `/research/?view=topics`；
- 至少一条 `/research/<slug>/` 与一条 `/research/paths/<id>/`；
- 三个 `/recipes/<id>/` 教程页；
- 对应 `/downloads/research/<id>/inputs.json` 与所选语言 notebook。

无 JavaScript 时静态 HTML 只保证分享元数据，不保证正文 SSR。斜杠形式以
Worker/`auto-trailing-slash` 的目录 URL 为准；Vite preview 对无斜杠 URL
可能只返回根 SPA，不能当作生产回读。教程锚点
（`#tutorial-example` 等）依赖客户端在懒加载挂载后再滚动，最长等待 2s；
离开该 hash 必须取消未完成的 restore，否则会滚到错误页面。

回滚是 scoped revert 上一已验证公开站 SHA 并重新发布其构建产物，不是删除
文献种子、教程示例或任何 SQLite/凭据。文献库变更不得触碰 collector、
catalog/query、Token 或 Recipe/Feature 运行面。

## 发布门禁

必须分别验证：local、origin/GitHub、production checkout、active release、service/timer、SQLite、真实 provider receipt、API readback 和消费者调用。

旧 `api.tushare.pro` official-direct release 只保留代码与回滚证据，不得启动为生产采集 runtime；修正版必须 fresh 验证 QuickSync endpoint/TLS、禁止 redirect、权限码分类、200 次/60 秒账号门禁、并发 4、单一 deadline、仅 pre-send DNS failover 和 impaired API readback。历史 190 接口本机矩阵、222 静态能力目录或分钟吞吐证明都不能替代服务器 provider -> SQLite -> receipt -> API readback；每日额度未知时仍不启用自动历史回填。

## 旧系统退役

新 TradingDatas runtime 和消费者切换通过后：

1. 停止旧写任务；
2. 观察无旧调用；
3. 保留可验证回滚快照；
4. 删除旧服务、cron、代码、文档和依赖；
5. 数据删除另走单独保留策略，不与代码退役混在一起。

2026-07-21 已验证的旧运行面清单如下，不得用模糊的“旧 cron”概括后一次性删除：

- root crontab：`opening_gate.sh` 的 preopen、morning_first_sample、afternoon_resume、close_check 四个时点，以及 `external_api_probe.sh`；
- `marketgraph` crontab：`SharedSignals/cron/` 下的 Tushare collectors、CNFutures、Crypto、事件、低频、patrol、proxy health、watchdog、SLA、governance、capability scan 和 PM 采集任务；
- systemd override：`/etc/systemd/system/tradingagent-front-api.service.d/sharedsignals.conf`，其 `SHAREDSIGNALS_API_URL` 仍指向 `127.0.0.1:8082`；
- 旧 `8082` 服务、旧 SharedSignals 代码与数据路径。

**2026-07-29 20:46 CST 退役 readback：** 已先生成 root-only 回滚快照，随后停用
`sharedsignals-api.service` 与 `sharedsignals-sg-relay-tunnel.service`。随后 7 个历史
SharedSignals service/timer 的 unit 均已移出 systemd 搜索路径并 `masked`，因此不能被意外
启动；原 unit 副本和摘要保留在受限退役证据目录。`127.0.0.1:8082` 已无监听；root 的 5 条与
`marketgraph` 的 22 条非注释旧 SharedSignals 计划任务均已移除。TradingDatas 18082 仍为
active，自己的 collector timer 继续 disabled。基础退役证据位于受限目录
`/opt/investment/release-evidence/tradingdatas/20260729T124623Z-sharedsignals-runtime-retirement`。
旧 SharedSignals 的代码、runtime、release candidate、systemd unit/override 与 active-path
归档已经完成退役和物理清理，不再是可用 rollback 或恢复入口，也不得重新创建旧 unit、cron、
provider route 或 SQLite 直读。TradingDatas 回滚只允许切换到已验证的 immutable release。
历史 Tushare 数据归档与退役证据是独立的数据保留范围；未取得单独批准前继续只读保留，不能因
代码/runtime 已清理而一并删除。具体删除时间、路径清单、数量、服务状态和 readback 属于带
`observed_at` 的运行事实，记录在 `STATUS.md`，不复制为长期运行合同。

退役必须分项执行并保留证据：

1. 新 TradingDatas 完成真实 provider -> SQLite facts/receipts -> `catalog/query` readback；
2. TradingAgent 及其它批准消费者只读新 API，完成 same-as-of、impaired 状态和无 legacy fallback parity；
3. 记录旧/新采集边界及最后成功 receipt，证明无数据窗口；
4. 冻结 root 与 `marketgraph` crontab、systemd override、旧服务和数据快照，生成可逐项回滚的 manifest；
5. 先禁用旧 writer/probe 并观察无旧调用，再删除 cron/override/service/code/docs；数据库与历史数据仍需独立批准。

## 回滚

回滚只切回已验证的 immutable release，不覆盖 SQLite，不恢复旧 cron，不把旧 provider route 重新引入新系统。

外部账户不属于当前运行范围；内部运行凭证和 API token 不得复用于任何外部账户或公网入口。

## Firecrawl 凭证与额度运维

Firecrawl 是境内新闻/公告/舆情采集的第三个 provider-level adapter（transport 协议与
QuickSync 实质不同，按根合同允许单独 adapter）。其凭证边界与 Tushare/QuickSync 完全一致：

- 凭证只从 `FIRECRAWL_API_KEY_FILE` 读取：绝对路径、单一硬链接普通文件、owner 等于采集进程
  有效 UID（当前 `tradingdatas`）、mode `0600`、非空且为单行 UTF-8。当前生产文件为
  `/etc/tradingdatas/firecrawl.token`，不在仓库内。
- Firecrawl key 是一次性成品号、按 credit 计费。换 key 只替换该文件内容并保持 owner/mode，
  零代码、零 registry 改动；替换后下一轮 event 采集自然使用新 key，无需重启服务。
- 402/429 → 该 dataset 记 `rate_limited` terminal receipt、planner 跳过、runtime 降级
  degraded，不阻塞 tushare/binance 管线。401/403 → `permission_denied`（key 失效即 entitlement
  降级，同样 dataset 级隔离）。
- 额度消费以 Firecrawl 后台 `creditsUsed` 为准；本仓库不持久化任何 Firecrawl 凭据或额度数字。
  全部 key 耗尽且暂无新 key 时，把 `config/firecrawl_upstream_contracts.v1.yaml` 中
  `cn.news.flash` 的 `activation.activation_state` 改回 `paused`（registry/config 改动），
  管线形态不变，恢复新 key 后按同一路径改回 `active` 并重编 registry。
- 生产采集单元的环境变量 `FIRECRAWL_API_KEY_FILE` 由
  `/etc/systemd/system/tradingdatas-provider-native-collect.service.d/20-firecrawl.conf`
  提供；修改凭证文件路径时必须同步该 drop-in，并 `systemctl daemon-reload`。

Firecrawl 的 `search_news`（`POST /v2/search`）当前无 registry binding，仅作为 on_demand
补充手段设计，不在自动调度内；激活前需先验证其真实响应契约。

## 目录请求的可选进程隔离

进程间任务 JSON 上限为 1 MiB；返回体继续服从 registry 的既有响应字节预算。

`TRADINGDATAS_CATALOG_WORKERS` 缺省或精确值 `0` 保留原进程内执行；精确值 `1`、`2`
启用同一 API unit/OS 账号内的相应数量持久 `spawn` 子进程。其它值不接受，不做静默
回退。仅 `GET /v1/catalog` 的完整 `CatalogService.list_datasets` 移入子进程，查询、
认证、endpoint scope、分类授权、频率/日额度和租户并发仍由原 HTTP 进程处理。
没有新服务、端口、凭据、provider 调用、数据库写入或跨请求投影缓存。

每个目录任务重新打开原 verified SQLite snapshot；runtime、coverage、queryability 和
cursor 由该完整请求的同一快照产生。子进程启动时核对物理代码目录/文件 hash、完整
registry hash、SQLite 路径、账号及既有 cursor signer 指纹；不经任务队列传原 token、
账号字典或 signer 密钥。监听启动前必须完成全部子进程身份检查，此步骤不读取 catalog
事实，也不构成数据健康证明。初始化失败关闭该候选服务；不能回退到未隔离的计算。

目录运行任务总数最多等于 worker 数，没有隐式等待队列。容量满或 worker/IPC 失败返回
既有 503 `service_unavailable`，不自动重放或改走 query。父请求一直等待已接收的任务
真正结束；客户端断开不释放仍在计算的任务/租户名额。Python 的正常 shutdown 停止接收
新任务并等待自有任务结束。systemd 停止整个 control group 时会同时发送 SIGTERM，
在途只读请求可能中断或返回 503；这不是无中断排空承诺，不自动重试。仅在预监听
初始化失败时，允许有界终止并回收该次初始化创建的子进程；
不终止 collector、正常客户任务或其它服务进程。systemd 仍须 `KillMode=control-group`，
并预留启动/退出时间；不得为该功能放宽 SQLite、凭据和 filesystem 保护。

启用先完成默认路径、真实 spawn、异常/容量/退出和 HTTP 授权顺序测试；随后在原运行面
验证冷/热目录、两个同时目录与既有 query 混合负载、完整 240 项/适用目录及查询摘要。
15 秒请求门禁不含预监听初始化，但初始化自身必须有界。现有服务、timer、锁、数据库
模式、清单和认证材料分别读回；不以独立进程性能实验代替真实 HTTP 验收。
配置切换必须与精确 release 一起保留回退：恢复原 worker 配置和原 release，停止/启动
同一 API unit 并完成认证读取，保留全部事实与回执。当前事故与实验见
[进程隔离候选记录](reports/2026-08-31-catalog-process-isolation.md)。

Crypto目录的UTF-8回执候选扫描先尝试有界的数据库原生字节匹配：首个共同前缀后的
精确后缀命中即可返回；首个未命中而有后续/重叠前缀时，仍调用原完整Python matcher。
无共同前缀、后缀长度种类过多、参数或SQL文本超出优化上限时回到原匹配路径；
这些优化上限不构成新的查询拒绝或扫描预算豁免。非UTF-8仍使用原SQLite语义。
不以JSON预解析或跨请求投影缓存跳过损坏候选及receipt authority检查。
同一次catalog请求内可按含typeof的完整原始行tuple复用该dataset已验证的seed分类与
execution身份；必须先完成siblings原始读取及预算收费，任一字段不同、新行或invalid
仍走原校验。此映射不跨请求、不按run_id单独判等，也不改变其它scanner调用者。

UTF-8回执候选扫描仍使用进程内锁，覆盖Python UDF注册、SQL读取和注销，
用于避免多个SQLite连接同时回调Python时的争用；不串行化整个HTTP服务，也不放宽
原始候选、损坏回执与扫描预算检查。发布须验证两个同时发起的认证目录请求均在15秒内
完成，单请求速度不能替代并发验收。当前4bb/WAL之后的运行时升级必须保持WAL，
回退到4bb/WAL时不得沿用早期恢复DELETE的脚本。详见
[原生匹配与验收记录](reports/2026-08-30-runtime-native-candidate.md)。

## 采集巡检脚本

已安装的 `/usr/local/sbin/tradingdatas-collector-watch.sh` 对应仓库
`deploy/tradingdatas-collector-watch.sh`；本文件是既有巡检的可审计源，不创建新 timer，
也不发送通知。退出码 `1` 表示发现告警，不能单凭 systemd `failed` 断言巡检程序损坏。
Polymarket 的新失败回执不能刷新成功捕获时间：使用 capture 内的 `observed_at`，并核对
非空 market/snapshot 数量；超过 26 小时无成功捕获、损坏回执或缺失成功捕获报 ALERT，
最近六份去重回执至少四次失败报 WARN，同一次判断不得同时输出 OK。这仅是运行诊断，
不取代 SQLite receipt、认证 API 或 activation/stable 门禁。既有 TA 账本告警保持独立，
修复 TD 不会抹除或伪造 TA 结果。

更新脚本需先记录现有字节 hash、备份到新的 root-only 路径、通过
`bash -n` 与 `tests/test_collector_watch.py`，再原子安装并读回 hash；不改 timer 排期。
回滚只恢复该备份脚本，保留既有日志和数据。读取日志应区分告警内容与工具执行错误。
