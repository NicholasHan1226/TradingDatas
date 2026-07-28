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

`metadata.receipt_id` / `observed_at` 描述最新可信 run 的当前 execution 状态；`metadata.data_through` 是所有 exact-complete success cohort 中的最大可信 dataset watermark，两者不要求来自同一个 receipt。后采旧 backfill 不得降低 `data_through`。`lineage.receipt_watermark` 的摘要同时覆盖当前 run 与最大 success cohort 的完整 member receipt IDs；variant 缺失或真实失败时 runtime 必须 fail closed，查询 `data` 为空，不能混读先前 success rows。

对允许为空的数据集，最新的完整 `empty` receipt 是“该请求窗口已在 `observed_at`
检查且无行”的客观证据。其新鲜度按该 receipt 的观察时间计算，而不是按旧 success
watermark；SLA 内返回 `runtime_state=empty`、`degraded=false`、
`quality.valid=true` 和 `data=[]`，超过 SLA 才转为 `stale`。这不虚构 `data_through`：
它仍保留最近完整 success watermark 或为 `null`。

`lineage.providers` 来自 SQLite receipt/read-model 投影，标识数据合同与 provider-native payload 来源；`lineage.transport_service` 与 `transport_profile_*` 来自代码固定的 provider-level transport profile，该 profile 连同哈希绑定进 receipt 的 `config_hash`。这些字段均不允许客户端参数覆盖。外部受邀 Beta 不改变此固定接口；再分发条款未验证前不开放真实数据。

`cn.dataset.rt_min` 的正式首批合同固定为 `freq=5MIN` 的三十只主板 canary。其身份为
`[ts_code, time]`。本平台把 provider 返回的 `time` 解释为该 5 分钟 bar 的结束时间；
上游字段说明仅称其为“交易时间”，因此这是本平台基于已验证 5 分钟返回形状冻结的
读取语义，不是对上游文档的额外断言。它是 OHLCV/amount bar，不是 bid/ask 或逐笔成交；
`vol` 单位为股，`amount` 单位为人民币元。只允许通过同一 catalog/query API 读取；盘后
可读到的最后一根 bar 不得被描述为 300 秒内的实时新鲜数据。

## 禁止接口

TradingDatas 不提供 provider 专用公共 route、SQL、SQLite 路径或交易控制接口。新增 dataset 不得新增 route。
