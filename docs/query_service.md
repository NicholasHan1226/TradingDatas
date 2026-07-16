# SharedSignals Phase 2 Query Service Contract

> 状态：本文件冻结 provider-neutral V1 query contract。当前 Task 1 只完成 registry 与
> request-contract 候选；HTTP handler、SQLite QueryService、signed cursor、legacy adapter、
> GitHub、生产 runtime、external route 和真实 tenant query 仍未完成，不能称为已上线。

## 边界与权威

公共数据面固定为 `GET /v1/catalog` 和 `POST /v1/query`。新增 provider 或 dataset 只能扩展
registry、adapter、SQLite facts/receipt、storage mapping 和 metadata，不得增加公共 route。

权威顺序固定为：provider-neutral registry → SQLite facts + transaction-scoped ingest receipts
→ registry/receipt/read-clock metadata → catalog/query envelope。查询只读同一个 verified SQLite
snapshot；不现场调用 provider，不读 CSV/NDJSON/Parquet、兄弟数据库或其它系统文件，也不把
HTTP 200、缓存、dashboard 或消费者状态当作数据健康证明。

SharedSignals 不处理 opening gate、候选、预测、策略、alpha、资金、持仓、风险、订单、成交、
执行回执或交易建议。

## Registry query policy

registry 根层 `query_defaults` 是请求资源预算的单一声明：

| 字段 | 默认值 |
| --- | ---: |
| `max_request_bytes` | 65,536 |
| `max_response_bytes` | 4,194,304 |
| `max_page_size` | 500 |
| `max_lookback_days` | 36,500 |
| `max_selected_fields` | 100 |
| `max_filter_terms` | 16 |
| `max_in_values` | 100 |
| `max_order_terms` | 8 |
| `max_catalog_search_chars` | 128 |
| `cursor_ttl_seconds` | 900 |
| `sqlite_progress_steps` | 1,000,000 |

schema profile 可以声明更小的 page/lookback override；省略或 `null` 时使用根层默认值，不能
扩大根层预算。每个 profile 必须显式声明可空的 `as_of_field`、`as_of_format`、`range_field`
和 `partition_field`。`null` 表示不支持，服务不得猜测映射。

- `as_of_field` 必须是已声明且 selectable/filterable/sortable 的 text 字段；格式只能是
  `yyyymmdd` 或 `rfc3339`，语义固定为 `field <= normalized_cutoff`。
- `range_field` 只供 legacy `start_date/end_date` 翻译使用。
- `partition_field` 只供 compatibility-only latest-partition 执行选项使用。
- 每个 filterable 字段支持 `eq`、`in`；有序 `text`、`integer`、`float` 还支持 `gte`、
  `lte`、`between`。operator 由 registry 字段合同确定，不能由客户端扩展。

异构事件 profile 默认不声明日期能力。只有 canonical-row 回归测试已经证明能稳定生成
`yyyymmdd trade_date` 的事件 dataset 才使用 dated event profile；月度推荐、停牌日期、名称变更等
尚未形成 canonical `trade_date` 的 dataset 保持四项能力为 `null`，服务和 legacy adapter 都不得猜测。

`catalog_version` 是 `v1-` 加 provider-neutral public contract 的 canonical SHA-256 前缀。dataset
identity、schema、query policy、cadence、SLA 或 access policy 变化会改变它；storage table、
DB path、adapter internals、provider token 和 runtime receipt 不参与，也不得从 fingerprint 反推。

## `GET /v1/catalog`

只支持固定过滤项：`market`、`domain`、`cadence`、`state`、`q`、`cursor`、`limit`。
响应只包含当前 access context 可发现的 dataset；越权和首期 excluded dataset 不以脱敏行暴露。

```json
{
  "api_version": "v1",
  "catalog_version": "v1-a1b2c3d4e5f60708",
  "request_id": "123e4567-e89b-42d3-a456-426614174000",
  "data": [],
  "next_cursor": null
}
```

catalog row 只暴露 provider-neutral identity、aliases、domain/market/entity/classification、schema、
default fields、filter/sort capability、cadence、timezone、SLA、有效 limits、point-in-time、scope、
quota、entitlement/activation summary 与 receipt-derived runtime metadata。不得暴露 table、SQL、
DB path、adapter version、provider credential 或内部 hostname。

## `POST /v1/query`

### Canonical request

```json
{
  "dataset_id": "cn.equity.daily",
  "schema_major": 1,
  "fields": ["symbol", "trade_date", "close"],
  "filters": {
    "symbol": "600519.SH",
    "trade_date": {"between": ["20260701", "20260716"]}
  },
  "as_of": null,
  "order": ["trade_date:desc", "symbol:asc"],
  "limit": 100,
  "cursor": null
}
```

根对象只允许以上八个字段。`dataset_id` 和 native positive integer `schema_major` 必填；Boolean、
float、numeric string 不能代替 integer。unknown root key、SQL、table、provider token、credential、
任意表达式、non-finite number 和 duplicate JSON key 均拒绝。

- `fields`：可省略或传空数组，表示 registry `default_projection`；非空时必须是 duplicate-free
  field identifier 列表，最多 100 项。最终字段仍受 dataset selectable contract 约束。
- `filters`：可省略，默认空对象。scalar 是 `eq` 简写；operator object 必须恰好只有一个
  `eq`、`in`、`gte`、`lte` 或 `between`。`in` 是 1–100 个无重复 scalar；`between` 恰好两个
  scalar。最多 16 个 field terms。字段、operator 与 native value type 还须通过 registry 校验。
- `as_of`：可省略或为 `null`；非空时必须是 timezone-aware RFC3339。服务在 dataset timezone
  归一化并按 profile 格式编码，再应用 inclusive `as_of_field <= cutoff`。请求里的同字段上界更
  严时取更严上界；该字段的有限 `in` 集合先按声明格式逐项解码，再以集合最大值参与收紧，任一
  无效成员都返回 400。支持的严格子集只使用 ASCII digits、uppercase `T`/`Z` 和真实 calendar
  date；hour 为 `00–23`、minute/second 为 `00–59`（不支持 leap second `60`）；fractional seconds 可省略或为
  1–6 位；numeric offset hour 为 `00–23`、minute 为 `00–59`。`Z` 与 `+00:00` 有效；表示
  unknown-local-offset 的 `-00:00`、非法组件、lowercase `t`/`z` 和 7 位以上 fraction 均返回 400，
  不得交给 datetime 静默归一化。`requested_as_of` 回显 canonical aware request；`resolved_as_of`
  报告实际 applied aware cutoff。未请求时二者均为 `null`；profile 未声明能力、naive/invalid
  timestamp 返回 400。
- `order`：省略或 `null` 时由 registry primary key 决定；显式值必须是 non-empty、无重复字段的
  `field:asc` / `field:desc` 列表，最多 8 项。QueryService 后续追加缺失 primary-key 与隐藏 rowid
  tie-breaker，隐藏字段不返回到 `data`。
- `limit`：省略时使用根层 500；必须是 native positive integer，并同时受根层与 profile 有效
  page limit 限制。
- `cursor`：可省略或为 `null`；非空时只能是 opaque signed keyset token，从不解释为 offset。

public parser 与 frozen `QueryRequest` 的每条构造路径都会重新 canonicalize 并深冻结 fields、filters、
order 和其它值；外部 dict/list 或 `dataclasses.replace()` 后续变化不得改变已生成请求或 query hash。

### Internal compatibility options

`latest_partition` 与 `any_of_eq_filters` 不是 public JSON 字段，public parser 必须拒绝。legacy
adapter 仅可在 registry 声明 `partition_field` 时请求 same-snapshot `MAX(partition_field)`；最多四个
`any_of_eq_filters` 只能是 registry-declared filterable field 的 equality OR group，并位于 mandatory
fixed dataset filters 之后；第五项属于 413 资源预算错误。两种选项、resolved partition 与 OR terms
都参与 query hash/cursor 绑定。

### Response

```json
{
  "api_version": "v1",
  "catalog_version": "v1-a1b2c3d4e5f60708",
  "request_id": "123e4567-e89b-42d3-a456-426614174000",
  "dataset_id": "cn.equity.daily",
  "schema_version": "1.0.0",
  "data": [],
  "next_cursor": null,
  "metadata": {
    "state": "ready",
    "runtime_state": "success",
    "degraded": false,
    "freshness": {"state": "fresh", "stale": false, "sla_seconds": 259200},
    "quality": {"state": "valid", "valid": true, "evidence": []},
    "lineage": {
      "state": "complete",
      "complete": true,
      "provider_neutral": true,
      "authority": "sqlite_ingest_receipts",
      "dataset_id": "cn.equity.daily",
      "providers": ["tushare"]
    },
    "receipt_id": "4a9ef4bfdd9f4f8e8a2f4a146b09c1a3",
    "data_through": "2026-07-16T00:00:00+08:00",
    "observed_at": "2026-07-16T15:35:00+08:00",
    "requested_as_of": null,
    "resolved_as_of": null,
    "reasons": []
  }
}
```

状态映射固定如下；HTTP 200 只表示协议成功，不表示数据健康：

| `runtime_state` | top-level `metadata.state` | `degraded` | rows |
| --- | --- | --- | --- |
| `success` | `ready`（仅完整且非 degraded） | `false` | 可返回 |
| `empty` | `empty` | `false` | `[]` |
| `unobserved` | `unobserved` | `true` | `[]` |
| `paused` | `paused` | `true` | `[]` |
| `failed` | `failed` | `true` | 仅有已证明 prior-success watermark 时可返回 last-known |
| `stale` | `stale` | `true` | 可返回 last-known，并带明确 reasons |

`freshness`、`quality`、`lineage` 始终是非空对象。healthy `success` 必须同时有 receipt、
data-through、observed-at 与 complete provider-neutral lineage；缺 receipt 不能伪装成 healthy empty。

## Query hash 与 cursor invalidation

normalized query hash 不包含 cursor token 本身，但绑定 resolved dataset/schema、effective projection、
canonical filters/order、requested/resolved as-of、limit、全部 internal execution options 和 resolved
partition。对象 key 顺序不改变 hash；任何影响结果的差异必须改变 hash。

signed keyset cursor 还绑定 `catalog_version`、access `policy_id`、receipt watermark、最后 sort tuple
与 expiry。以下任一变化必须拒绝旧 cursor：dataset、schema major、normalized query、tenant/scopes、
exact dataset grant、catalog contract、receipt snapshot、requested/resolved as-of、internal options、
resolved partition 或 TTL。格式/签名错误返回 400；合法 token 与当前 contract/snapshot 不匹配返回 409。

## Error contract

| HTTP | 含义 |
| ---: | --- |
| 400 | malformed/unknown request、field/operator/type/order/as-of/cursor 格式错误 |
| 401 | 未认证或 credential 无效 |
| 403 | 已知且首期可用 dataset，但当前 context 缺 query scope/精确 grant |
| 404 | dataset 未知、excluded 或结构上不可发现 |
| 409 | cursor 与 dataset/schema/query/policy/catalog/receipt snapshot 不匹配 |
| 413 | request/response、field/filter/`in`/order/page/lookback 预算超限 |
| 429 | rate、concurrency 或 quota 超限（Phase 4 持久治理） |
| 503 | verified read model 不可用或 SQLite capacity/progress budget 用尽 |
| 500 | 内部错误；不得回显 stack trace、path、SQL 或 secret |

## Phase 2 access limitation

Phase 2 只注入 `tenant_id`、normalized `scopes`、request-local exact `allowed_dataset_ids` 和它们的
canonical SHA-256 `policy_id`。catalog discovery 需要 registry `required_scope` 或既有 aggregate
`external_read` / `read` / `full` / `*`；exact dataset grant 只能授权该次 direct query，不能让 dataset
出现在 catalog，也不能授权另一个 dataset。

`QueryAccessContext` 在 direct construction、factory 与 `dataclasses.replace()` 的每条路径都重新排序、
去重并验证 scopes/grants，同时重算 `policy_id`；调用方传入或沿用的旧 hash 不能覆盖该恒等式。

Phase 2 不实现 public signup、tenant key issuance、field/lookback tenant policy、persistent quota、
usage ledger、billing、revocation automation 或 gateway changes；这些属于 Phase 4。当前合同与测试只
证明 local candidate，不证明 local main、GitHub、生产 checkout、production runtime、external route
或真实 dataset query。

## Legacy compatibility

`/tushare?api_name=daily` 只可把 alias `tushare.daily` 翻译为 `cn.equity.daily` 后调用同一
QueryService；代表性 `/reference?table=stock_master` 同理。adapter 可以翻译旧参数和旧 envelope，
但不得包含 SQL、table/path、provider call、file fallback、独立 cursor 或独立 metadata aggregation。
deprecation 与删除必须等待 semantic parity、observed no-use window 和 rollback evidence。
