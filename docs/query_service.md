# SharedSignals Phase 2 Query Service Contract

> 状态：本文件冻结 provider-neutral V1 query contract。Tasks 1–6 已进入当前隔离 worktree
> 本地候选，Task 7 冻结 consumer fixture/docs/tests。local main、origin/GitHub、生产 runtime、
> external route 和真实 tenant query 尚未由发布层验证，不能称为已上线。

## 边界与权威

公共数据面固定为 `GET /v1/catalog` 和 `POST /v1/query`。新增 provider 或 dataset 只能扩展
registry/config；普通 Tushare dataset 复用 generic provider-row SQLite facts/receipt 和 query
compiler，不得增加 dataset-specific adapter、storage mapping、Python branch 或公共 route。

权威顺序固定为：provider-neutral registry → SQLite facts + transaction-scoped ingest receipts
→ registry/receipt/read-clock metadata → catalog/query envelope。查询只读同一个 verified SQLite
snapshot；不现场调用 provider，不读 CSV/NDJSON/Parquet、兄弟数据库或其它系统文件，也不把
HTTP 200、缓存、dashboard 或消费者状态当作数据健康证明。

generic provider-row 查询只把 registry 声明的字段编译为内部受限 JSON extraction，并强制
`dataset_id/provider/schema_major` 隔离。客户端不能提交 JSON path、SQL 或表名；响应扁平返回
provider-native 字段，不暴露 `payload_json` 或技术存储列。现有 typed-table 查询仅是迁移期
compatibility surface，不能成为新 dataset 的目标路径。

对 provider-native dataset，`fields` 省略或传空数组表示返回每行完整的上游 payload；这与
Tushare 省略 `fields` 时返回全部字段的使用方式一致，也保证新增上游字段无需逐接口修改 SS。
显式 `fields`、filter 和 order 仍只能使用 registry 已声明且获准的字段，客户端始终不能读取
`payload_json`、`row_key`、receipt 或其它技术存储列。

声明时间格式不符的 provider-native 原值仍可被普通字段选择，并以 `failed/degraded`、
`data_through=null` 和真实 receipt/quality lineage 返回；该字段一旦参与 filter、order、as-of
或 latest-partition 就 fail closed。dataset-wide quality 与 operation issue 检查必须绑定既有
quality index 并只扫描 degraded rows；缺失该 index 时查询不可用，不能退回全分区扫描。

SharedSignals 不处理 opening gate、候选、预测、策略、alpha、资金、持仓、风险、订单、成交、
执行回执或交易建议。

消费者 handoff 由 [V1 Consumer Data Contract](data_contract.md) 与
[machine-readable fixture](../tests/fixtures/sharedsignals_v1_query_contract.json) 冻结。fixture
只含 V1 public fields；消费者不得依赖 table、SQL、provider token 或内部 cursor claims。

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

## HTTP ingress 与认证合同

公共操作只有精确的 `GET /v1/catalog` 与 `POST /v1/query`；`OPTIONS` 仅是无 body 的 204
preflight。尾斜杠、大小写变体和其它 `/v1/*` 返回 404；精确路径上的错误方法返回 405，并分别
给出 `Allow: GET, OPTIONS` 或 `Allow: POST, OPTIONS`。新增 provider 或 dataset 不得生成新路由。

处理顺序固定为：stdlib transport → exact route/method → framing/media/body budget → 认证 → endpoint
scope → tenant rate/concurrency → JSON/业务合同 → lazy service → 完整响应序列化与预算。成功 claim
concurrency 后，所有成功、异常、超限和客户端断开路径都必须释放；V1 不读写 legacy response cache
或 request dedup。过长 request line/header 的 414/431 在 V1 request context 之前发生，因此只要求
关闭连接，不承诺 V1 JSON envelope。

- `GET /v1/catalog` 不接受 request body、`Transfer-Encoding` 或非零 `Content-Length`。
- `POST /v1/query` 必须恰有一个 canonical ASCII non-negative decimal `Content-Length`，禁止任何
  `Transfer-Encoding`；short read、duplicate/non-canonical length 都 fail closed。
- `Content-Type` 必须唯一且为 `application/json`，只允许省略参数或唯一 `charset=utf-8`；任何
  `Content-Encoding` 都不支持。raw body 在 JSON decode 前受 `max_request_bytes` 限制。
- JSON 使用严格 UTF-8，拒绝 BOM、duplicate object key、lone surrogate、NaN/Infinity、非 object
  根值和过深递归；不得回显或记录 raw body。

认证复用真实 middleware。缺失、无效、过期、同时提供两类 credential 或 duplicate credential
均为 401；external/forwarded header 不得触发 localhost bypass。只有 `market_data`、`events`、
`external_read`、`read`、`full`、`*` 可进入 V1；其它 legacy narrow scope 返回 403。

启用 JWT 时必须显式配置 `SHAREDSIGNALS_JWT_ALGORITHM`，且只接受大小写完全一致的 `HS256`
或 `RS256`；JWT header 的 `alg` 必须与服务端配置完全一致，服务不得按 token 自选算法、猜测或
fallback。`HS256` 的 `SHAREDSIGNALS_JWT_PUBLIC_KEY` 按共享 secret 使用，UTF-8 编码后至少 32 bytes
且不得是 PEM 形态；`RS256` 只接受 `PUBLIC KEY` 或 `RSA PUBLIC KEY` PEM 公钥验证材料，禁止私钥、
共享 secret 或其它 PEM 类型。algorithm 缺失/未知、header 不匹配、key 类型或格式不兼容都按无效
credential 返回固定 401 envelope；token、key 和验签内部值不得出现在响应或日志。

每个进入 V1 namespace 的请求使用 server-owned UUIDv4 `request_id`，忽略客户端同名 header。
`QueryAccessContext` 只从已认证账户的 canonical tenant/scopes 新建，`allowed_dataset_ids=()`，并重算
`policy_id`；不信任账户携带的旧 policy/grant。不同 tenant 复用合法 signed cursor 必须因 policy
binding 返回 409。

`CatalogService`、`QueryService`、verified read-model binding 和 cursor signing key 只在第一次 V1
请求时通过线程安全路径构造。缺失/短 signing key、read model 或 server clock 配置只让 V1 返回
503，不得阻止 process/health 启动，也不得回退 provider、文件或其它数据库。现有 registry
import-time topology 不在 Task 5 重构范围内，不能据此声称整个 registry 已完全 lazy。

process `main()` 只加载环境与 HTTP server 配置；不得预加载 legacy `reader` 或 sector-flow runtime。
精确 V1 路由和轻量 `/health` 也不依赖这些 legacy 模块；只有实际 legacy route dispatch 才按需加载
它们。此隔离只改变加载时机，不删除、迁移或改变 legacy route 的响应语义。

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
      "providers": ["tushare"],
      "receipt_watermark": "receipt-20260716-0001"
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
消费者必须按逐 dataset metadata fail closed 或 down-weight；HTTP 200、非空 rows 或 global
source flag 都不能替代 freshness、quality、lineage 与 receipt evidence。

## Query hash 与 cursor invalidation

normalized query hash 不包含 cursor token 本身，但绑定 resolved dataset/schema、effective projection、
canonical filters/order、requested/resolved as-of、limit、全部 internal execution options 和 resolved
partition。对象 key 顺序不改变 hash；任何影响结果的差异必须改变 hash。

signed keyset cursor 是两个以单个 `.` 分隔的 non-empty、unpadded base64url segment；只接受
`[A-Za-z0-9_-]`，解码后必须能逐字节重新编码为原 segment。payload 是 compact、sorted-key、
`allow_nan=false` 的 canonical UTF-8 JSON，固定键为 `v`、`kind`、`catalog_version`、`dataset_id`、
`schema_major`、`query_hash`、`policy_id`、`receipt_watermark`、`sort_key` 和 `expires_at`，当前只接受
native integer `v=1`。`kind=catalog` 时 dataset/schema 必须为 null；`kind=query` 时必须是 canonical
dataset ID 与 native positive schema major。`sort_key` 只允许 finite JSON scalar tuple，禁止 nested
container、NaN 或 infinity。

token 使用 HMAC-SHA256 保护完整性，并不加密；有效 keyset sort values（包括隐藏 SQLite rowid
tie-breaker 的值）可能被解码，但 payload 不得携带其它 hidden row、path、SQL、credential、provider
token，`data` 也不得返回 `__ss_rowid`。签名密钥只在构造 V1/compatibility service 时由
`SHAREDSIGNALS_CURSOR_SIGNING_KEY` lazy 读取，UTF-8 编码后至少 32 bytes；无默认、fallback 或
import-time 读取，缺失/空/短/不可编码配置属于 503，而不是 client cursor 错误。

验证顺序固定为 strict envelope/base64url → constant-time HMAC → canonical JSON/schema → expiry →
expected binding。expiry 使用 timezone-aware server clock，`expires_at <= floor(now.timestamp())` 即失效；
naive/无效 server clock 属于 503 配置错误。malformed、签名错误、不支持版本或过期 token 返回 400；
合法签名 token 与当前 kind/catalog/dataset/schema/query/policy/receipt 任一绑定不匹配返回 409。公开错误
只给 category，不回显 token、claims、sort values、secret、path、SQL 或 expected/actual value。

## Error contract

除 transport-level 414/431 外，所有 V1 错误都使用固定、category-only envelope；公开
`message` 不拼接内部异常、路径、SQL、credential、raw body、cursor、tenant 或 expected/actual：

```json
{
  "api_version": "v1",
  "request_id": "123e4567-e89b-42d3-a456-426614174000",
  "error": {
    "code": "invalid_request",
    "message": "request is invalid",
    "retryable": false
  }
}
```

| HTTP | `code` | 固定 `message` | `retryable` | 条件 |
| ---: | --- | --- | :---: | --- |
| 400 | `invalid_request` | `request is invalid` | false | malformed/unknown request、field/operator/type/order/as-of/cursor 格式错误 |
| 401 | `unauthenticated` | `authentication required` | false | 未认证或 credential 无效/歧义 |
| 403 | `forbidden` | `request is forbidden` | false | endpoint scope 或已知首期 dataset scope 不足 |
| 404 | `not_found` | `resource not found` | false | route/dataset 未知、excluded 或结构上不可发现 |
| 405 | `method_not_allowed` | `method is not allowed` | false | 精确 V1 path 使用错误 method，并返回固定 `Allow` |
| 409 | `cursor_mismatch` | `cursor does not match request` | false | cursor 与 dataset/schema/query/policy/catalog/receipt snapshot 不匹配 |
| 413 | `budget_exceeded` | `request exceeds allowed budget` | false | request/response、field/filter/`in`/order/page/lookback 预算超限 |
| 415 | `unsupported_media_type` | `unsupported media type` | false | media type、charset 或 content encoding 不支持 |
| 429 | `rate_limited` | `rate limit exceeded` | true | 当前进程内 tenant rate 或 concurrency 超限 |
| 503 | `service_unavailable` | `service temporarily unavailable` | true | verified read model、signing key/clock/config 或 SQLite capacity 不可用 |
| 500 | `internal_error` | `internal error` | false | 未预期内部错误 |

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
`/reference?table=stock_master&limit=500` 只可解析为 `cn.equity.security_master`，并沿用 registry 的
`provider=tushare_stock_basic` fixed filter；不得混入 `tushare_stock_company`。legacy `limit` 必须是
1..500 的 canonical integer，超过 500 返回 413。调用方通过 signed `cursor` 耗尽所有页并逐页保留
receipt metadata；一页健康探针不等于完整股票池，也不得在工具内聚合成另一套查询引擎。
trim 后 case-insensitive 的 `stock_master` spelling 由一个共用 normalizer 收口；cache bypass、HTTP
dispatch 与 reader 不得各自发明判断。HTTP endpoint scope 通过后，adapter 先解析 dataset，再从真实
account 仅提取 tenant 与 normalized scopes，并以唯一 resolved dataset 的 request-local exact grant
重算 policy；不得信任 account 自带 policy/grant，也不得借此读取 catalog 或其它 dataset。跨 tenant、
scope 或 resolved dataset 的 cursor 必须按 policy mismatch 失败。
deprecation 与删除必须等待 semantic parity、observed no-use window 和 rollback evidence。
