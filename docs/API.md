# TradingDatas Internal API

Agent-specific connection prompts do not create Agent-specific API routes.
Claude, Codex, OpenClaw, Hermes, and other HTTP-capable agents use the same
authenticated endpoints and metadata semantics below. The canonical prompt and
variant contract is documented in [AGENT_INTEGRATIONS.md](AGENT_INTEGRATIONS.md).

The current public data API has exactly the two `/v1` endpoints documented
below. Canonical/PIT objects, transparent Features, and executable Recipes are
target product planes described in `product/PRODUCT_PLANES.md`; this document
does not define or imply a live `/v2` route.

## GET /v1/catalog

返回首期产品范围内、已经具备 provider-neutral runtime contract 的可发现数据集、
schema、字段、查询能力、cadence、SLA、entitlement 和 runtime state。运行目录与更广
的产品能力发现 artifact 是两个版本化对象；尚未冻结 dataset identity、schema 和请求
合同的发现项不进入 runtime registry、SQLite、scheduler 或查询 API。具体数量是易变
运行事实，只在带 `observed_at` 的 `STATUS.md` 或生成报告中记录。

目录可发现性与查询/运行资格是两个独立事实：`excluded`、`retired` 或其它未激活项
仍应在 catalog 中如实展示其状态，但只有同一 provider binding 同时满足
`entitlement=active` 与 `activation=active` 才可进入 SQLite 读侧检查；其余查询必须
在 SQLite 或 provider 访问前 fail closed。

catalog 不是运行成功证明；每个数据集仍需结合 receipt 和读取时钟判断状态。
`market=CN`、`timezone=Asia/Shanghai` 的分钟/收盘日频 success 在下一配置开窗前按前一配置工作日收盘锚点
判断 freshness，开窗后恢复原 SLA 比较。该边界与 query 共用读取投影，不更改实际
`data_through`/`observed_at`，也不等于实时新数据、节假日日历或全历史完整性。缺失前一
时段数据、过期 empty、失败回执仍如实降级。固定读取 policy 不可用时 fail closed；
配置来源及边界见 [运行说明](OPERATIONS.md)。
`entitlement` 仅表示 provider 侧真实观测到的权限状态。当前 `provider=tushare` 的权限证据来自 `transport_service=quicksync` 的有界真实调用；凭证存在、官方积分、静态目录可见或 HTTP 200 都不能单独证明 QuickSync 权限、频控或数据可用性。

`schema_version` 表示当前 provider-neutral 可读合同，而不是客户端对官方文档字段的假设。
当 QuickSync 的稳定实际响应与官方参考字段不一致时，registry 只会通过受证据约束的
response-contract delta 做字段子集、类型或新增字段修正，并递增受影响 dataset 的 schema
major；详情见 [ADR-0011](adr/ADR-0011-quicksync-observed-response-contracts.md)。消费者必须
始终从 catalog 读取 schema major，不得把旧 schema 当作兼容回退。

`rt_min_daily` 的 schema 2 候选移除实际未返回的响应字段 `freq`，采集请求仍固定为
`1MIN`；不得由客户端伪造该 provider 字段。`broker_recommend` 的 schema 2 候选
保持原字段和严格 `YYYYMM` 月份语义，用真实重采建立新质量记录；不会改写 major 1
的旧 facts/receipts。固定 query 只接受当前 registry major，因此这两项版本切换需
认证 readback 与消费者合同适配，不能把源码候选称为生产生效。`fut_basic` 的
schema 2 候选同样只移除缺失的 `trade_time_desc` 响应字段，保留 `[ts_code]` identity
和全部六个交易所请求 variants；它也需要新回执与消费者 major 适配。详见
[本轮质量与覆盖证据](reports/2026-08-30-coverage-quality-recovery.md)。

后续 `rt_min_daily` major 3 保留 major 2 的八个原生字段，新增严格非空
`[ts_code,time]` identity；`time` 可筛选及排序，水位只来自通过完整本地日和实际完成时钟
校验的 provider 时间。它不回写 major 1/2 历史，也不保证全市场或收盘完整性。
消费者必须明确支持 major 3。七项财务日期续采只改变 binding 请求验证和调度，
不更改公共 schema major、字段可空性、主键或 as-of/range 合同；新成功回执不能
替旧 payload 的原始 row receipt/quality 背书。

每个 catalog row 的 `identity_fields` 是 registry `primary_key` 的有序投影；没有已声明业务主键时为 `[]`。消费者将它与该 row 的 dataset contract fingerprint 一起重算和绑定，不能猜测、替换或信任 producer 自报 hash。`cn.dataset.fut_basic` 的正式合同 identity 为 `[ts_code]`，因此 catalog 的确定性默认顺序为 `[ts_code:asc]`；该 identity 只支持有界分页与 replay，不证明 response completeness、业务时间水位或 PIT。日分区的 receipt completeness 可以声明稳定 identity 并验证请求分区、唯一性和行数上限；若同一 dataset 的 `as_of_field`、`range_field` 与 `partition_field` 都是 `null`，这不声明业务时间水位或 PIT 可用性，消费者仍只能将其作为 receipt-bound current-partition 事实读取。

每个 catalog row 还携带 `coverage`（`row_count`、`earliest_observed_at`、`latest_observed_at`），
来自同一 SQLite 快照对 `provider_dataset_rows` 的按 dataset 聚合。它是存储侧覆盖面
参考：只统计已入库行，不证明历史完整性、provider 侧覆盖或 PIT；`row_count=0` 与
runtime `unobserved`/`empty` 语义彼此独立。coverage 不参与 cursor watermark，采集
增量不会使未过期的 catalog cursor 失效。

每个 catalog row 的 `limits` 是该数据集的查询预算投影，不是账号套餐额度，也不是
覆盖或 freshness 证明。当前固定三键：

- `limits.max_page_size`：单页 `limit` 上限（dataset 合同；当前 A 股 registry 默认 500）
- `limits.max_in_values`：任一 `filters.<field>.in` 数组长度上限（来自同一 registry
  的 `query_defaults.max_in_values`，当前默认 500）。#458 起写入每一行，避免消费者把
  “目录未声明”误判为“禁止 `in` 过滤”
- `limits.max_lookback_days`：可请求回看天数上限（dataset 合同；当前 A 股 registry
  默认 36500）

消费者必须从认证 catalog 读回实际值，不得硬编码仓库默认值。Git 合入 #458 不等于
广州 GZ 已切换；生产是否露出 `max_in_values` 仍须 exact-main 发布后的认证 catalog
readback。`limits` 不含 `max_selected_fields`；显式 `fields` 数量预算只在 query
合同中强制。

## POST /v1/query

每一页返回的行都必须在同一只读 SQLite 快照内通过自身 `receipt_id` 的身份、
dataset/provider、成功状态与完整采集序列校验。缺失或无效的行回执返回
`503 service_unavailable`，不得用最新 dataset 回执替代，也不得标记
`lineage.complete=true` 后继续返回该行。校验限于当前页引用的去重回执及其
采集序列，不遍历其它数据集，也不访问 provider；定位序列成员的 SQL 仍可能
检查当前数据集的历史回执，因此页大小有界不等于历史规模对耗时完全无影响。
空页（`data=[]`）没有行回执可校验；catalog 显示 `success` 不能证明即将返回的
历史行仍绑着完整回执。

旧版本可能在同一采集 execution 的后续调用明确失败前，已提交前缀调用的 success
行。查询会在排序与分页前，通过该行自身回执及同 execution 的已验证 failed 终态识别并
排除这类已知 partial 前缀，最多有界重选 8 次；它们不构成可返回的成功事实。其余独立
success execution 的行仍可同页返回，因此 HTTP 200 且 `data` 变短是预期过滤，不是 503。
同一逻辑请求在失败 attempt 之后的成功重试属于完整 success cohort，仍可返回。这个例外
不放宽 fail closed：回执缺失、畸形、provider 不匹配、调用序列只有断档而没有明确
failed 终态，或 8 次重选仍不能形成有效页时，仍返回 `503 service_unavailable`。
该 503 的 `retryable: true` 只表示共享不可用信封，不承诺重试会补回被排除的前缀或缺失回执。

`include_receipt_proofs` 只控制是否输出逐行证明及其既有的单一采集序列限制，
不控制上述基础校验是否执行；被排除的 failed-cohort 前缀也不会出现在证明列表中。
省略该字段等于 `false`。默认查询继续允许同页
包含来自多个有效历史采集序列的行；字段投影、分页和默认响应格式不变。
同一页若行回执分属不同 `execution_id` / `request_window` / `config_hash` /
`data_through`，默认查询在各回执均有效时可返回这些行；显式 `true` 会因单一
序列合同失败并同样返回 503。

该 503 使用与其它 query fail-closed 相同的错误信封，不单独暴露哪一行或哪份
回执损坏：

```json
{
  "api_version": "v1",
  "request_id": "...",
  "error": {
    "code": "service_unavailable",
    "message": "service temporarily unavailable",
    "retryable": true
  }
}
```

`retryable` 是该错误码的固定分类（容量不足、IPC 失败与行回执损坏共用），
不是“同一页再试就会好”的承诺。行回执缺失或无效时，缩小 `filters`/`limit`
可以隔离损坏页，但相同页会持续 503，直到原始 success 回执被恢复；省略
`include_receipt_proofs`、改用后续 dataset 回执或复用旧 HTTP 200 都不能绕过。
诊断步骤见 [查询页行回执校验](OPERATIONS.md#查询页的行回执校验)。

请求：

```json
{
  "dataset_id": "cn.equity.daily",
  "schema_major": 2,
  "fields": [],
  "filters": {},
  "as_of": null,
  "limit": 500,
  "cursor": null,
  "include_receipt_proofs": false
}
```

省略 `fields` 或传空数组时返回完整 provider-native payload；显式字段、过滤和排序必须受 registry allowlist 与预算限制。`limit` 不得超过该行 `limits.max_page_size`；任一 `filters.<field>.in` 不得超过 `limits.max_in_values`；显式 `fields` 数量不得超过 registry `query_defaults.max_selected_fields`（当前默认 100，不出现在 catalog `limits`）。超预算返回 HTTP 413、`error.code=budget_exceeded`，`retryable=false`，不得截断后继续。未知字段或非法算子仍是 400 `invalid_request`。

响应至少包含：

```json
{
  "api_version": "v1",
  "catalog_version": "...",
  "request_id": "...",
  "dataset_id": "cn.equity.daily",
  "schema_version": "2.0.0",
  "data": [],
  "next_cursor": null,
  "metadata": {
    "state": "ready",
    "runtime_state": "success",
    "degraded": false,
    "freshness": {
      "state": "fresh",
      "stale": false,
      "sla_seconds": 86400
    },
    "quality": {
      "state": "valid",
      "valid": true,
      "evidence": []
    },
    "lineage": {
      "state": "complete",
      "complete": true,
      "provider_neutral": true,
      "authority": "sqlite_ingest_receipts",
      "dataset_id": "cn.equity.daily",
      "providers": ["tushare"],
      "transport_service": "quicksync",
      "receipt_watermark": "..."
    },
    "receipt_id": "...",
    "data_through": "...",
    "observed_at": "...",
    "requested_as_of": null,
    "resolved_as_of": null,
    "reasons": []
  }
}
```

`metadata.runtime_state` 必须如实区分 `success`、`empty`、`unobserved`、
`paused`、`failed`、`stale`。`metadata.state` 是面向读取方的可用状态：新鲜且
完整的 `success` 映射为 `ready`，合同未验证时可叠加为 `partial`，但客观状态仍保留在
`runtime_state`。degraded 本身不等于停止供数：可验证数据按既有查询合同返回，空结果或错误按对应窗口的真实证据返回；单个数据集状态不封锁其它数据集。HTTP 200 不得掩盖 dataset 级 degraded 状态；消费者必须逐数据集读取
metadata，不能只看 HTTP 状态码。**empty ≠ success**；合同正确时的 empty /
`provider_error` 是外部输入事实，不是 TradingDatas 工程未完成，也不是把 empty
改写成 success 的许可证。接入排期口径见 `docs/OPERATIONS.md`「Datas PM 接入口径」。

对 `event` 与 `session_minute` 的 append-only 数据集，最新可信 refresh 若以
`provider_error` 或 `config_error` 失败，catalog 的 `runtime_state` 必须立即投影为
`failed`、`degraded=true`，同时保留上一份完整成功的 `data_through` 供消费者判断可用历史；
连续失败超过 catalog 的最近收据窗口时，同样不得把仍可验证的上一成功水位静默改成
`null`。低频 append-only 数据集仍可在上一成功水位尚新鲜时保留既有读取状态；该低频容错
不得用于隐藏高频源的最新失败。Catalog 的 failed/config_error 不是把已入库
`session_minute` 事实改写成空页的许可证。

对无业务分区窗口的 `session_minute` 查询（`partition_field`/`as_of_field`/`range_field`
均为空，且请求未带精确 `time=eq` 槽位），`POST /v1/query` 必须用上一完整成功窗口的
receipt 投影当前页：已入库 append-only 行在 valid filters-dict 请求下返回
`rows>0`，且该页 `quality.evidence` / `reasons` 不得继承最新 refresh 的
`config_error`。若上一成功水位仍在 freshness SLA 内，该查询窗口为
`runtime_state=success`；超过 SLA 则为 `stale`。没有上一完整成功水位时，
`empty` 与 `config_error` 保持原状态与 `data=[]`，不得改写成 success。
精确 `time=eq` 历史槽位仍只绑定该槽位的已验证 success receipts；槽位不存在则
503 fail closed。这不把 empty 改写成 success，也不把最新 refresh 失败从 catalog
上抹掉。

新鲜度按数据时间粒度计算：`YYYYMM` 水印覆盖完整月份，以该月末作为 SLA 参考。
对于 `market=CN`、`timezone=Asia/Shanghai` 的 `session_minute` 与 `postclose_daily`，
周六/周日读取时分别以最近周五 15:00 和周六 00:00 作为新鲜度时钟，避免已覆盖周五的
数据因周末无交易被误报过期。仍缺周五数据的水印继续按 SLA 判断；事件、参考数据和
Crypto 不适用这个时钟。此规则不推断法定节假日、不证明历史完整性；周一和工作日仍
使用原有时钟（午休按既有规则处理），failed/paused/invalid receipt 不会被放宽。


中国市场的 `session_minute` 数据集在同一交易日的 11:30--13:00
（Asia/Shanghai）午间休市内暂停 freshness 时钟；13:00 起恢复严格 SLA 判断。该规则
不适用于其它市场、非 `session_minute` cadence 或前一交易日的水位。

`runtime_state=success` 或 `runtime_state=empty` 只有在所有 active provider binding 都声明
`response_completeness` 时才可被视为完整。任一 active binding 缺该合同时，success
仍可返回已有 rows，empty 仍保持 `data=[]`；两者都保留可信 receipt lineage，但公共 metadata 必须为
`state=partial`、`degraded=true`、`quality.state=degraded`、
`quality.valid=false`，并在 `reasons` 与 `quality.evidence` 中包含固定 reason code
`response_completeness_unverified`。若该数据集同时存在 `request_window_policy`，且
dataset 的 `as_of_field`、`range_field`、`partition_field` 全部为空，则 receipt 的
运行时间或 `data_through` 不能充当业务水位；公共 `data_through` 必须为 `null`、
`freshness.state=unknown`，并追加固定 reason code
`freshness_watermark_unverified`。该完整性叠加层不改写客观 `runtime_state`；已具备
完整性合同的数据集继续使用既有 `ready` / `empty`、freshness 与 valid 语义。

当 SQLite 中存在格式与行级校验均有效、但 `config_hash` 不等于当前 active binding
ingest contract 的 receipt，且没有任何当前合同 receipt 时，API 保持
`runtime_state=unobserved`、`data=[]` 与不完整 lineage，并在 `reasons` 返回
`active_config_receipt_mismatch`。这只标记 coverage gap：旧合同 receipt、历史行或
HTTP 200 都不得被复用为当前合同的 observation。

省略 `as_of` 时，`metadata.receipt_id` / `observed_at` 描述最新可信 run 的当前
execution 状态；`metadata.data_through` 是所有 exact-complete success cohort 中的最大
可信 dataset watermark，两者不要求来自同一个 receipt。后采旧 backfill 不得降低
`data_through`。显式请求 `as_of` 时，读取投影只允许使用完整 execution 内
`started_at`、`finished_at` 均不晚于 `requested_as_of`，且 `data_through` 不晚于
`resolved_as_of` 的 success receipts，返回行也必须绑定这些 receipts；metadata、
lineage 与 cursor watermark 均从该
有界 receipt authority 重建。若截止点前没有匹配的完整 success receipt，查询以 503
fail closed，不能把后采 receipt、当前 metadata 或无 lineage 的历史行拼入结果。
当 RFC3339 数据集同时使用 range field 的 `between` 与显式 `as_of` 时，允许绑定行的
success receipt 还必须与 `[range 下界, requested_as_of]` collection window 重叠；这样
固定滚动窗口的 lineage 与 SQLite 查询成本不随无关历史 receipt 总数增长。
仅对有界历史 lineage，若 append-only RFC3339 数据集把既有 range field 新声明为
同名 `partition_field`，还可接受紧邻前一版 `partition_field=null` 合同的 receipts。
当截止点前尚无活动 hash 的完整 success 时，历史 envelope 也从该前一版 cohort
重建；省略 `as_of` 的当前投影仍必须匹配活动 config hash。其它 provider、请求、
schema、主键或 payload 变化一律不兼容。
对声明 `snapshot_field` 的 cohort，watermark 必须取 provider 返回的该 snapshot 值，
不能以 collector 的开始时间代替；对未声明 `resumable_fanout` 的 cohort，同时声明
`fanout_field` 时所有请求值必须恰好出现一次且共享同一 snapshot；声明
`resumable_fanout` 的分钟批次允许请求集合内的严格子集，停牌代码带回的历史最后 bar 按
`[ts_code,time]` 独立绑定；越界或无效响应仍只能形成 failed receipt。
`metadata.data_through` 不得晚于 `resolved_as_of`，`metadata.observed_at` 不得晚于
`requested_as_of`。截止点之后新增的 receipt 不改变同一 as-of 的 cursor authority。

该约束不会把历史回填变成 PIT：receipt 的 `data_through` 可以描述较早 bar，但
`observed_at` 仍是实际 collection time。若回填在请求的 `as_of` 之后才采集，它不得进入该
历史读取投影。`lineage.receipt_watermark` 的摘要同时覆盖当前 run 与最大 success cohort
的完整 member receipt IDs；显式 as-of 还覆盖全部允许返回行的 success receipt IDs。

`as_of` 本身始终使用 RFC3339；catalog 中每个 dataset 的 `as_of_format` 决定它绑定的
业务字段编码。当前通用格式为 `yyyymmdd`、`yyyymm` 和 `rfc3339`。例如月度数据集的
`month=YYYYMM` 是一个完整月分区；读取时间在该月内时，API 只接受不晚于该月的已观测
receipt，绝不把后采集的月度记录投影到过去。
variant 缺失或真实失败时 runtime 必须 fail closed，查询 `data` 为空，不能混读先前
success rows。

对 `point_in_time=append_only` 的稳定 identity，后续 transaction 重观测到字节完全相同
的 payload 时继续写入独立 success receipt 与 `unchanged` counts，但事实行保留首次
`collected_at` / `receipt_id` / `revision`。这样较早 as-of 的行与 receipt 绑定不会被
后续重叠窗口覆盖。`current_snapshot` 数据集仍把相同 payload 的重观测绑定到最新 receipt；
append-only payload 一旦变化仍按既有合同 fail closed。该规则不迁移或反写既有历史事实，
也不把后采 backfill 伪装成历史可得。

`session_minute` 的精确已结束槽位可能被纠错 overlap 在多个完整成功 execution 中重复
观测。查询会联合同一 active config/provider 且 `data_through` 精确等于该槽位的已验证
receipt，使事实行保留首次 receipt authority；任一 execution 不完整、配置/provider 混合或
逐行证明跨采集序列时仍 fail closed。逐行证明允许 receipt 保留 registry 要求的窗口，
但窗口必须完整通过同一 active provider 的 `request_window_policy`，且起始锚点不得晚于
事实行的事件时间；未知键、错误格式、未来锚点或 provider 不匹配继续 fail closed。

交易日历是已知未来事实的例外：`entity_type=trade_calendar` 可以返回 provider 已发布的下一
交易日及其 `is_open` / `pretrade_date`。未来有效日期只保留在行字段；envelope 的
`data_through` 投影为该 success receipt 的已知/入库时间，因此仍不晚于 `observed_at`。
该例外不放宽 receipt 的 `started_at`、`finished_at` 或 `observed_at`：这些执行时间仍不得在
未来，且 calendar 以外的数据集仍对 future `data_through` fail closed。

对允许为空的数据集，最新的完整 `empty` receipt 是“该请求窗口已在 `observed_at`
检查且无行”的客观证据。其新鲜度按该 receipt 的观察时间计算，而不是按旧 success
watermark；SLA 内返回 `runtime_state=empty`、`degraded=false`、
`quality.valid=true` 和 `data=[]`，超过 SLA 才转为 `stale`。这不虚构 `data_through`：
它仍保留最近完整 success watermark 或为 `null`。

`lineage.providers` 来自 SQLite receipt/read-model 投影，标识数据合同与 provider-native payload 来源；`lineage.transport_service` 与 `transport_profile_*` 来自代码固定的 provider-level transport profile，该 profile 连同哈希绑定进 receipt 的 `config_hash`。这些字段均不允许客户端参数覆盖。外部受邀 Beta 不改变此固定接口；再分发条款未验证前不开放真实数据。

对 `runtime_state=success`，传输合同校验以当前完整 receipt cohort 为准；receipt 的
`config_hash` 必须与当前 registry 和 provider transport profile 精确匹配。旧 schema 或旧合同的
历史 receipt/facts 仍保留在 SQLite 供审计，但不得参与当前 `data_through`、freshness、receipt
watermark 或 lineage 投影，也不能把当前已验证分区降级。只有读取方实际使用历史 fallback 时，才会把
该 fallback cohort 一并纳入 lineage 校验。

`cn.dataset.rt_min` 的 registry 输入固定为 `freq=5MIN` 的 30 只沪深主板 request template，
并绑定当前冻结的完整 5,963 个 `ts_code`。该 immutable fanout 以每批 300 拆成 20 批，使用
resumable cursor v2（每轮最多 20 批，按 bar_time 窗口每根 bar 重置游标），由匹配 dataset/provider、config、universe 与 batch
identity 的 success/empty receipt 续接；失败只在该 dataset 内重试，不能跨 universe/config
复用 receipt。该绑定用于正式 compiler/registry 的可重建 authority，实际激活、完整 cohort
receipt 和 catalog/query 供应仍须由独立 release/readback 门禁确认。它不是中证500成分、研究
代表性样本或交易 Universe。
本平台把 provider 返回的
`time` 解释为该 5 分钟 bar 的结束时间；
上游字段说明仅称其为“交易时间”，因此这是本平台基于已验证 5 分钟返回形状冻结的
读取语义，不是对上游文档的额外断言。它是 OHLCV/amount bar，不是 bid/ask 或逐笔成交；
`vol` 单位为股，`amount` 单位为人民币元。只允许通过同一 catalog/query API 读取；盘后
可读到的最后一根 bar 不得被描述为 300 秒内的实时新鲜数据。

当消费者显式过滤单一已结束的 `time` 槽位时，receipt authority 绑定该槽位对应的
完整 success execution。该 execution 的 receipt 必须共享 provider、config、
`data_through` 和请求窗口；请求窗口可以是合法的 `request_window_policy`（例如
`bar_time`），不要求为空。缺 receipt、跨 execution、跨窗口或行时间与槽位不一致时，
API fail closed 返回 503。

完整 universe 仅在同一 request window 的 20 个 batch receipt 均通过 identity、schema、
时间与行完整性校验时才投影为该窗口的 `ready`；任一 batch 失败、缺代码、重复代码或
bar 时间不一致都只写该 batch 的失败 receipt，并保留已成功批次供 cursor v2 续接，不把部分
结果伪装成完整覆盖。旧 500/30 分片仍可作为独立回滚与诊断证据，但不改变当前 5,963
代码的 registry authority。

## 目录执行容量

目录进程隔离为默认关闭的运行配置，不新增 route 或请求字段。启用后，认证、endpoint
scope、分类授权、频率/日额度、租户并发仍先于目录任务执行。目录执行容量满、子进程
身份不匹配、worker 或 IPC 失败返回既有 503 `service_unavailable`，不会返回旧快照、
自动重放、调用上游或转到 query。采集写锁或 WAL sidecar 瞬时不一致时，只读 snapshot
在 2 秒内 fail closed 为同一 `503 service_unavailable`（retryable），不得把
catalog/query worker 挂在长租约上，也不得把该 503 当作盲目重启许可证。正常任务仍完整使用一次新的 verified SQLite snapshot，
分页、cursor、字段、响应字节预算及错误分类保持原合同。客户端断开不等于任务已经结束，
其占用的租户/执行容量要等真实计算结束后释放。运维配置及关闭方式见
[目录进程隔离](OPERATIONS.md#目录请求的可选进程隔离)。

## 禁止接口

TradingDatas 不提供 provider 专用公共 route、SQL、SQLite 路径或交易控制接口。新增 dataset 不得新增 route。

## Admin Console API

### Account category entitlement status

Customer data access is grouped into A-share, Crypto, and News using the stable
keys `a_share`, `crypto`, and `news`. Token records and admin mutations accept
`data_categories` as a JSON array of these keys. The server maps them to the
active registry's `market`/`domain` metadata and applies the resulting exact
dataset grants to both `GET /v1/catalog` and `POST /v1/query`.

Omitting `data_categories` preserves legacy access to all current categories.
An explicit empty array returns no catalog datasets and authorizes no dataset
query. Unknown values or non-array values are rejected; invalid stored values
fail token configuration loading closed. `GET /admin/api/tokens` returns the
effective `data_categories` and `data_category_mode` (`all` or `restricted`).
`GET /portal/api/me` returns the same two fields for the authenticated account.
This field is independent of endpoint scopes and rate/concurrency/daily limits:
all gates must pass.

管理控制台提供内部管理员使用的 token 管理、采集状态监控和用量统计接口。除 CORS 预检外，所有 admin API 路由需要 `admin` scope 或 `internal` tier 的认证。

### GET /admin/

返回管理控制台 HTML 页面（单页应用，Tailwind CSS）。

### OPTIONS /admin/api/*

跨域浏览器请求在携带 `Authorization` 前会发送无凭据预检。该请求返回 `204` 和允许的
methods/headers，不读取或返回任何管理数据；后续实际请求仍执行完整认证与 scope 校验。
当前策略以 bearer token 认证且不使用 cookie/session，因此响应明确使用 `Access-Control-Allow-Origin: *`。
若将来引入 cookie 或浏览器凭据，必须改为显式 allowlist，不能沿用 wildcard。

### GET /admin/api/tokens

返回所有已配置的 API token 列表（hash 已脱敏），包含每日用量。

### POST /admin/api/tokens

创建新 token。请求体：

```json
{
  "tenant_id": "new-tenant",
  "tier": "standard",
  "scopes": ["read"],
  "expires_at": "2027-12-31T23:59:59Z"
}
```

`tier` 决定请求频率合同；商业档只以每分钟频率区分：

| tier | 定位 | 频率上限 | 并发上限 |
|---|---|---|---|
| `free` / `starter` | 试用/入门 | 60 次/小时 | 2 |
| `research` | 研究 | 300 次/小时 | 4 |
| `pro` | 专业 | 600 次/小时 | 8 |
| `basic` | 商业·基础版 | **200 次/分钟** | 不限 |
| `standard` | 商业·专业版 | **600 次/分钟** | 不限 |
| `flagship` | 商业·旗舰版 | **1000 次/分钟** | 不限 |
| `enterprise` / `internal` | 内部 | 不限（仅日配额管控） | 不限 |

商业三档（basic/standard/flagship）采用滚动 60 秒窗口，不设每日额度或并发上限；
达到分钟上限返回 `429 code=rate_limited`。为商业档创建或更新非空 `daily_limit`
或 `max_concurrent` 会被拒绝，避免管理员界面与真实执行合同分叉。有效期
（`expires_at`）仍按 token 单独控制。

滥用防护墙（对认证与匿名请求一视同仁）按**来源 IP** 计 1200 次/60 秒，高于
最高商业套餐的 1000 次/分钟且与套餐合同相互独立；经 Cloudflare 访问时以 `CF-Connecting-IP` 识别真实来源，正常
使用不会触墙。若你的出口 IP 由多台机器共享且触发该墙，返回的同样是
`429 code=rate_limited`，等待窗口滑过即可恢复。

响应包含明文 token（仅此一次可见）：

```json
{
  "token": "raw-token-value",
  "token_hash": "...",
  "tenant_id": "new-tenant"
}
```

### PATCH /admin/api/tokens/{token_hash}

更新 token 设置。可更新字段：`enabled`、`daily_limit`、`expires_at`、`tier`、`scopes`、`max_concurrent`。商业档不接受非空 `daily_limit` 或 `max_concurrent`；后二者只用于兼容存量档位。

### DELETE /admin/api/tokens/{token_hash}

删除 token。

### GET /admin/api/usage

返回当前日用量、各租户实际限流窗口用量和系统统计。为兼容既有客户端，限流窗口仍位于
`hourly` 字段；每行必须按 `window_seconds` 解读：商业档为 60 秒，存量档为 3600 秒。

### GET /admin/api/collection/status

返回所有数据集的采集状态（activation、entitlement、runtime state）。

### GET /admin/api/data/overview

返回数据概览（按市场、Provider、cadence 分类的数据集数量）。

## Public Account session bridge

`tradingdatas.com` 的静态资源 Worker 包含一个同站 Account 代理合同。该合同是浏览器
credential-containment bridge，不是邮箱身份库，也不改变 Agent 继续使用 bearer token
调用固定数据 API 的方式。生产环境只有在 Cloudflare secret `SESSION_ENCRYPTION_KEY` 和
非密钥 binding `ACCOUNT_API_BASE` 均存在时才启用；否则认证与代理请求返回
`503 {"error":"identity_gateway_unavailable"}`，不得推断为生产已启用。

- `POST /api/account/session`：同源请求提交 `{"access_key":"..."}`，通过
  `GET /portal/api/me` 验证，且响应包含非空字符串 `portal.tenant_id`/`portal.tier` 后
  返回相同 account projection，并设置 8 小时、AES-GCM 封装的
  `HttpOnly; Secure; SameSite=Strict; Path=/api/account` cookie。原始 key 不写入响应、URL、
  analytics 或持久化浏览器存储。
- `GET /api/account/me`、`GET /api/account/usage?days=N`、`GET /api/account/keys`：从
  同站 cookie 恢复上游 credential，并分别代理到当前 Customer Portal API。
- `POST /api/account/keys`、`PATCH /api/account/keys/{key_id}`：要求同源 `Origin`，保持
  原有同租户、非管理员 scope、一次显示和不可停用当前 key 的后端约束。
- `DELETE /api/account/session`：要求同源 `Origin`，清除当前浏览器 cookie。当前桥接为
  短期无状态会话；完整的跨设备 session list、单会话服务端 revoke 与审计仍属于后续
  identity store 合同，不能由清 Cookie 冒充。

同源 DELETE 清 Cookie 不依赖上游或密钥配置，故网关配置故障时仍可退出。上游 401
也会清除当前 Cookie；403、429 与服务故障不能冒充成功或静默降级。代理按路径约束
允许的方法，请求体在流读取过程中限制为 16 KiB，登录账户响应限制为 512 KiB；
上游请求使用 Worker 支持的 `redirect: manual` 并拒绝 3xx（不跟随、不转发
Location），设 8 秒超时；网络异常返回无敏感详情的 502/504。

浏览器不再使用 direct-bearer 兼容路径，也不保存原始 key。旧 `localStorage` 与
`sessionStorage` credential 在启动时移除，旧直连用户需重新登录；服务端 Token 不变。
前端请求设 12 秒超时，登录单飞，账户变化后的迟到结果不得恢复前一账户/新密钥。
`me` 验证身份与 `usage` 可用性分离，用量服务故障仅展示可重试提示。页面重新可见时
验证现有会话；非后台轮询。此桥接仍不等于手机/邮箱身份库或可独立撤销的持久会话。

### Browser view-state mapping

`public-web/src/accountSession.js` 把传输结果映射为四态视图。登录页、Account 私有
面板和购买预览必须共用同一套状态，不能把网关故障写成退出，也不能把无效密钥写成
服务不可用。

| 条件 | 客户端 error | `getAccountViewState` |
| --- | --- | --- |
| 正在请求 `GET /api/account/me` | — | `checking` |
| 响应含有效 `portal` 或已验证 email identity | — | `authenticated` |
| `POST /api/account/session` 返回 401 | `invalid_token` | `signed_out` |
| 其它已认证读/写返回 401 | `signed_out` | `signed_out` |
| 403（通用） | `access_denied` | `unavailable` |
| 429 | `rate_limited` | `unavailable` |
| 请求超时（默认 12s） | `account_timeout` | `unavailable` |
| 5xx、非 JSON 或缺少 `tenant_id`/`tier` | `account_unavailable` | `unavailable` |

`startAccountSession` 把会话交换的 401 改写成 `invalid_token`，以便登录表单显示
“密钥无效”，而不是“已退出”。后续 `me`/`usage`/`keys` 的 401 才是会话缺失。
`usage` 的 5xx 只设置用量错误，不得 `clearAccountView`。退出必须先看到
`DELETE /api/account/session` 返回 `{"signed_out": true}`，才能清空 UI。

购买预览的 `next` 校验在 `public-web/src/purchasePreview.js`：只允许恰好一个
`next=/account`，或规范路径 `/pricing/preview` 且仅含 `plan`（`basic` /
`standard` / `flagship`）与 `period`（`monthly` / `annual`）。
重复参数、hash、外链和 `/api/*` 一律回落 `/account`。预览状态 `canPay` 恒为
`false`，与是否已登录无关。

### Independent email identity candidate

The existing Login/Account also has a local-only, separately gated email-identity
implementation. Its control-plane routes are `GET /api/account/auth-methods`,
`POST /api/account/email/challenge`, and `POST /api/account/email/verify`.
Email sessions reuse `/api/account/me` and `DELETE /api/account/session`, but use
a distinct opaque cookie with server-side revocation in a dedicated identity
store. Unlike legacy key-cookie clearing, email sign-out requires confirmation
from that store; a store outage cannot be reported as successful revocation.

The only email-account state implemented is verified and `not_subscribed`, with
no tenant, data grant, usage or API key access. This does not change catalog/query
or existing Portal authentication. Configured readiness is not delivery evidence;
missing configuration keeps email login unavailable. Detailed request/response,
limits, failure and release contracts: [Email identity v1](design/email-identity-v1.md).
Operator diagnosis of 429/503: [OPERATIONS.md](OPERATIONS.md#email-otp-admission-diagnosis).
No production storage migration, secret provisioning or email activation is
asserted by this API description.

Challenge and verify share one admission gate, then apply narrower send/verify
caps. Status values below are the Worker JSON `error` field. They are not
catalog/query codes and do not grant data access.

| HTTP | `error` | When |
| --- | --- | --- |
| 202 | (none) | Challenge accepted by the mail provider; not inbox delivery. |
| 400 | `invalid_request` / `invalid_code` | Malformed email, or verify payload/code failed. Invalid email is rejected **before** admission. Invalid verify payloads after admission still consume that attempt. |
| 429 | `rate_limited` | Coupled global+per-IP admission denied, or a later send-email / send-global / 60s cooldown cap. `Retry-After: 60`. A full global budget must not create a new per-IP bucket. |
| 503 | `email_login_unavailable` | Enable flags, D1, pepper, or Resend key incomplete. |
| 503 | `identity_unavailable` | Missing Cloudflare `CF-Connecting-IP`, D1/storage throw, or inconsistent admission rows. Do not trust `X-Forwarded-For`. |
| 503 | `delivery_unavailable` | Provider send failed after admission; an unaccepted challenge row is deleted. |

The local candidate also adds `POST /api/account/profile/deletion`: same-origin
JSON `{confirmation: "DELETE"}`, `X-TD-Identity` matching the current email identity,
current email session verified within ten
minutes, and the separate retention feature flag are required. The server derives
the user exclusively from that session. A D1 transaction queues deletion,
disables the user and revokes all its email sessions; 202 returns
`deletion: {state: "accepted", user_id, requested_at, delete_by}` and clears both cookies.
Missing/mismatched expected identity returns 409 `identity_changed`; the frontend
also validates the receipt identity so a stale tab cannot confirm another profile.
This is not a completed-purge receipt. Wrong confirmation is 400, stale
verification is 403 `recent_sign_in_required`, unauthenticated/expired email
session is 401, and unavailable configuration/storage is 503. A legacy-only
key session cannot use this route. `me.identity.deletion_available` indicates
the feature flag only, not maintenance health. Email alone grants no admin/tenant
authority; see the [retention contract](design/identity-retention-v1.md).

### Account continuity candidate (not deployed)

The gated [account/library contract](design/account-library-v1.md) adds explicit
`POST/DELETE /api/account/connection`, `GET /api/account/bookmarks`,
`PUT/DELETE /api/account/bookmarks/item`, and `POST /api/account/bookmarks/import`.
All use the verified email cookie and expected `X-TD-Identity`; mutations require
same origin. A connection requires recent verification, one existing backend-verified
key and encrypted user-bound storage, never client tenant/role input or a new grant.
`me.identity` remains grant-free; `me.data_access` is a separately revalidated backend
projection (`none/connected/invalid/unavailable`). `me.capabilities` reports switches,
not successful deployment or data health. Usage and key routes proxy the connected
credential's existing portal authority. Invalid data access does not end email sign-in.

The `/api/account/admin/*` bridge has a fixed whitelist of existing backend admin
routes and restricted data-browser catalog/query calls; it is not a public data API.
Each call revalidates admin scope/internal tier and expected identity. Administrative
writes additionally require recent email verification. Ordinary customer credentials
are rejected. Backend bearer/CORS authentication is unchanged; cookies terminate at
the same-origin gateway. Cloud bookmarks store only typed resource references, max
500 per identity; explicit import is atomic and capped at 100 references per action.
Feature flags remain false and require separate schema/release acceptance.

## Customer Portal API

客户自助端点：任意有效 token 认证后仅返回**当前租户**的套餐、限额、用量与
脱敏 API key 列表，不泄露其他租户。供 `tradingdatas.com/account` 使用；`/app/`
是独立的管理员控制面，不是第二个客户门户。

客户 token 只进入官网 Account；带 `admin` scope 或 `internal` tier 的管理员 token
进入独立管理工作台。管理工作台不切换或冒充客户视角；平台 owner token 可同时保留
`read` 与 `admin`，用于管理台内的目录/查询验证，但不会因此获得跨租户客户投影。

### OPTIONS /portal/api/*

与 admin 相同的无凭据 CORS 预检：返回 `204` 与允许的 methods/headers，bearer-only、
无 cookie/session，响应使用 `Access-Control-Allow-Origin: *`。引入浏览器凭据时必须
整体改为显式 allowlist，并同步本文件。

### GET /portal/api/me

返回当前 token 的套餐信息与当日/当小时用量：

```json
{
  "api_version": "...",
  "request_id": "...",
  "portal": {
    "tenant_id": "...",
    "tier": "research",
    "scopes": ["read"],
    "data_categories": ["a_share", "news"],
    "data_category_mode": "restricted",
    "enabled": true,
    "max_concurrent": 4,
    "hourly_request_limit": 300,
    "minute_request_limit": null,
    "daily_limit": 10000,
    "request_volume_unlimited": false,
    "expires_at": "2027-12-31T23:59:59Z",
    "usage": {
      "today_date": "2026-08-23",
      "today_count": 123,
      "hourly_count": 9,
      "hourly_window_seconds": 3600
    }
  }
}
```

`max_concurrent <= 0` 表示不限制并发。商业三档的 `max_concurrent=null`、
`daily_limit=null`、`hourly_request_limit=null`，`minute_request_limit` 分别为
200/600/1000，且 `request_volume_unlimited=false`；调用次数仍保留在 `usage` 与历史趋势中。
存量档位继续按对应小时、每日和并发合同投影。

### GET /portal/api/me/usage?days=30

返回本租户最近 N 天（钳制 1..365，默认 30）的逐日调用量：

```json
{
  "api_version": "...",
  "request_id": "...",
  "portal_usage": {
    "tenant_id": "...",
    "daily_limit": 10000,
    "today_count": 123,
    "history": [{"date": "2026-08-23", "total": 123}]
  }
}
```

**设计边界**：portal 查询是客户查看自身信息的入口，**不计入每日配额、不做 scope
检查**（否则门户页面自身的加载会烧客户的日配额）；但仍执行完整的 token 认证
（disabled/expired 拒绝）、适用的分钟/小时频率限制与存量档位并发限制。认证失败语义与 v1 一致
（401/429，同一错误信封）。

### GET /portal/api/me/keys

返回当前租户的 API key 列表。响应只包含稳定 `key_id`、用户标签、状态、创建时间、
是否为当前连接和脱敏 fingerprint；不返回原始 token 或完整 token hash。只有
token-hash credential 可管理 key，JWT 会话在同站身份网关合同完成前保持只读账户投影。

### POST /portal/api/me/keys

请求体只允许 `{"label":"Codex on MacBook"}`。新 key 固定继承当前账户的 tenant、
tier、非管理员 scopes、data categories、有效期与适用限额，不能通过请求字段提升权限。
当前 credential 没有可委派的数据 scope（例如只有 `admin`）时创建请求 fail closed，
不会回退补授 `read`。
每个租户最多保留 10 个 key。成功时原始 `key` **仅在 201 响应中出现一次**，随后只保留
脱敏投影。

### PATCH /portal/api/me/keys/{key_id}

请求体只允许 `{"enabled":false}`，且只能停用当前租户的非当前 key。正在认证本次请求的
key 不可自行停用，防止用户把当前 Account 会话锁死。重新启用、删除与跨租户操作仍由
管理员控制面处理。

## Token 配置扩展字段

`api_tokens.json` 支持以下新增字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `enabled` | bool | 是否启用（默认 true） |
| `expires_at` | string/number | 过期时间（RFC3339 或 Unix 时间戳） |
| `label` | string | 客户可读的 key 名称，1..64 字符 |
| `created_at` | string | key 创建时间（RFC3339 UTC） |
| `daily_limit` | number/null | 存量档位每日请求上限（null 或省略 = 无限；商业档不接受） |

### Account key-management business errors

Both same-site account login paths return HTTP 400 with a safe `error` code for
known key-management refusals: `invalid_key_label`, `key_limit_reached`,
`current_key_protected`, `key_not_found`, `invalid_key_id`,
`key_management_unavailable`, `key_scope_required`. These account-control routes
are unchanged; this does not add data API endpoints. Unknown or oversized backend
errors remain unavailable responses, without exposing backend text. A data-key
refusal does not revoke an independent email identity.
