# TradingDatas Internal API

## GET /v1/catalog

返回首期产品范围内可发现的数据集、schema、字段、查询能力、cadence、SLA、
entitlement 和 runtime state。目录可发现性与查询/运行资格是两个独立事实：
`excluded`、`retired` 或其它未激活项仍应在 catalog 中如实展示其状态，但
`POST /v1/query` 必须继续在 SQLite 或 provider 访问前 fail closed。

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
完整的 `success` 映射为 `ready`，其它状态保持不变。HTTP 200 不得掩盖 dataset
级 degraded 状态；消费者必须逐数据集读取 metadata，不能只看 HTTP 状态码。

`lineage.providers` 来自 SQLite receipt/read-model 投影，标识数据合同与 provider-native payload 来源；`lineage.transport_service` 与 `transport_profile_*` 来自代码固定的 provider-level transport profile，该 profile 连同哈希绑定进 receipt 的 `config_hash`。这些字段均不允许客户端参数覆盖。外部受邀 Beta 不改变此固定接口；再分发条款未验证前不开放真实数据。

## 禁止接口

TradingDatas 不提供 provider 专用公共 route、SQL、SQLite 路径或交易控制接口。新增 dataset 不得新增 route。
