# TradingDatas Internal API

## GET /v1/catalog

返回首期产品范围内、已经具备 provider-neutral runtime contract 的可发现数据集、
schema、字段、查询能力、cadence、SLA、entitlement 和 runtime state。当前运行目录
为 190 项；另有 32 项只存在于 222 项产品能力发现 artifact 中，在 dataset identity、
schema 和请求合同冻结前不进入 runtime registry、SQLite、scheduler 或查询 API。

目录可发现性与查询/运行资格是两个独立事实：`excluded`、`retired` 或其它未激活项
仍应在 catalog 中如实展示其状态，但只有同一 provider binding 同时满足
`entitlement=active` 与 `activation=active` 才可进入 SQLite 读侧检查；其余查询必须
在 SQLite 或 provider 访问前 fail closed。

catalog 不是运行成功证明；每个数据集仍需结合 receipt 和读取时钟判断状态。
`entitlement` 仅表示 provider 侧真实观测到的权限状态。当前 `provider=tushare` 的权限证据来自 `transport_service=quicksync` 的有界真实调用；凭证存在、官方积分、静态目录可见或 HTTP 200 都不能单独证明 QuickSync 权限、频控或数据可用性。

`schema_version` 表示当前 provider-neutral 可读合同，而不是客户端对官方文档字段的假设。
当 QuickSync 的稳定实际响应与官方参考字段不一致时，registry 只会通过受证据约束的
response-contract delta 做字段子集、类型或新增字段修正，并递增受影响 dataset 的 schema
major；详情见 [ADR-0011](adr/ADR-0011-quicksync-observed-response-contracts.md)。消费者必须
始终从 catalog 读取 schema major，不得把旧 schema 当作兼容回退。

每个 catalog row 的 `identity_fields` 是 registry `primary_key` 的有序投影；没有已声明业务主键时为 `[]`。消费者将它与该 row 的 dataset contract fingerprint 一起重算和绑定，不能猜测、替换或信任 producer 自报 hash。`cn.dataset.fut_basic` 的正式合同 identity 为 `[ts_code]`，因此 catalog 的确定性默认顺序为 `[ts_code:asc]`；该 identity 只支持有界分页与 replay，不证明 response completeness、业务时间水位或 PIT。日分区的 receipt completeness 可以声明稳定 identity 并验证请求分区、唯一性和行数上限；若同一 dataset 的 `as_of_field`、`range_field` 与 `partition_field` 都是 `null`，这不声明业务时间水位或 PIT 可用性，消费者仍只能将其作为 receipt-bound current-partition 事实读取。

## POST /v1/query

请求：

```json
{
  "dataset_id": "cn.equity.daily",
  "schema_major": 2,
  "fields": [],
  "filters": {},
  "as_of": null,
  "limit": 500,
  "cursor": null
}
```

省略 `fields` 或传空数组时返回完整 provider-native payload；显式字段、过滤和排序必须受 registry allowlist 与预算限制。

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
`runtime_state`。HTTP 200 不得掩盖 dataset 级 degraded 状态；消费者必须逐数据集读取
metadata，不能只看 HTTP 状态码。

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
当前投影仍必须匹配活动 config hash；其它 provider、请求、schema、主键或 payload
变化一律不兼容。
对声明 `snapshot_field` 的 cohort，watermark 必须取 provider 返回的该 snapshot 值，
不能以 collector 的开始时间代替；同时声明 `fanout_field` 时，所有请求值必须恰好出现
一次且共享同一 snapshot，否则该 cohort 只能形成 failed receipt。
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

`cn.dataset.rt_min` 的正式首批合同固定为 `freq=5MIN` 的 30 只沪深主板 canary。代码列表是
registry 中冻结的多代码 request，不依赖 security-master fanout；其身份为 `[ts_code, time]`。
500 只动态分片只属于隔离压力候选，在完整 cohort、receipt 和 fresh review 通过前不属于正式
catalog/query 生产合同。首批 30 只也不是中证500成分、研究代表性样本或交易 Universe。
本平台把 provider 返回的
`time` 解释为该 5 分钟 bar 的结束时间；
上游字段说明仅称其为“交易时间”，因此这是本平台基于已验证 5 分钟返回形状冻结的
读取语义，不是对上游文档的额外断言。它是 OHLCV/amount bar，不是 bid/ask 或逐笔成交；
`vol` 单位为股，`amount` 单位为人民币元。只允许通过同一 catalog/query API 读取；盘后
可读到的最后一根 bar 不得被描述为 300 秒内的实时新鲜数据。

500 只 canary 仅在同一轮的全部五个分片都返回、恰好覆盖冻结的 500 个 `ts_code`、无
重复且所有行具有同一个 `time` 时才投影为 `ready`。任一分片失败、缺代码、重复代码或
bar 时间不一致都只写失败 receipt 并使该数据集 fail-closed；不会把部分分片或上一轮数据
伪装成完整 500 只快照。现行 30 只生产 canary 保留为独立回滚点。

## 禁止接口

TradingDatas 不提供 provider 专用公共 route、SQL、SQLite 路径或交易控制接口。新增 dataset 不得新增 route。
