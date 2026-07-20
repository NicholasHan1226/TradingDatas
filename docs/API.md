# TradingDatas Internal API

## GET /v1/catalog

返回当前账户可见的数据集、schema、字段、查询能力、cadence、SLA、entitlement 和 runtime state。

catalog 不是运行成功证明；每个数据集仍需结合 receipt 和读取时钟判断状态。
`entitlement` 仅表示 provider 侧真实观测到的权限状态。对 Tushare，它可能来自积分门槛或单独权限；Token 存在、静态目录可见或 HTTP 200 都不能单独证明权限、频控或数据可用性。

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

## 禁止接口

TradingDatas 不提供 provider 专用公共 route、SQL、SQLite 路径或交易控制接口。新增 dataset 不得新增 route。
