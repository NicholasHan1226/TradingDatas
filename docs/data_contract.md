# SharedSignals V1 Consumer Data Contract

> 状态：本文件冻结本地 Phase 2 候选的 consumer handoff。它不是 GitHub、生产
> checkout、production runtime、external route 或 real dataset 可用证明。可机读示例见
> [V1 contract fixture](../tests/fixtures/sharedsignals_v1_query_contract.json)。

## 固定边界

SharedSignals 面向消费者有 exactly two target public data routes：
`GET /v1/catalog` 与 `POST /v1/query`。新增 provider 或 dataset 只扩展 registry、
adapter、SQLite storage mapping、facts/receipt 与 metadata；不新增第三条 public data route。

消费者只绑定 provider-neutral dataset ID（例如 `cn.equity.daily`）以及该 dataset 自己的
independent dataset schema version。provider 名称、table、SQL、数据库路径、adapter 版本和
credential 都不是消费者合同。legacy route 只能翻译旧参数并调用 same QueryService，不能成为
第二个 query engine、独立 SQL、provider live fallback 或 file fallback。

一次 query 必须从 one verified SQLite snapshot 同时读取 rows 与 metadata。权威顺序是
provider-neutral registry → SQLite facts + transaction-scoped ingest receipts →
registry/receipt/read-clock metadata → public envelope。

对 provider-native dataset，`fields: []`（或省略 `fields`）返回每行完整的 provider payload，
包括 registry 尚未声明的新上游字段；显式字段、filter 与 order 仍只能引用 registry allowlist。
技术列 `payload_json`、`row_key`、receipt、provider routing 和 SQLite 结构永不直接暴露。

SharedSignals 不承担 opening、strategy、capital、position、risk、order 或 fill 责任，也不生成
候选、预测、alpha、交易建议或执行回执。TradingAgent 等消费者自己负责研究、降权、风控和执行边界。

## Request envelope

`POST /v1/query` 根对象只允许以下八个字段：

```json
{
  "dataset_id": "cn.equity.daily",
  "schema_major": 1,
  "fields": ["market", "symbol", "trade_date", "close"],
  "filters": {
    "market": "Ashare",
    "trade_date": {"eq": "20260716"}
  },
  "as_of": null,
  "order": ["market:asc", "symbol:asc", "trade_date:asc"],
  "limit": 1,
  "cursor": null
}
```

- `dataset_id` 与 native positive integer `schema_major` 必填。
- catalog dataset.market remains `CN` because it is the dataset's geographic classification;
  persisted A-share fact rows use canonical `market="Ashare"`, so row filters use `Ashare`.
  In the fixture's real SQLite slice, filtering the fact field with `CN` returns zero rows.
- `fields`、`filters`、`order`、`limit` 与 `as_of` 必须通过 catalog/registry policy。
- filter operator 仅有 `eq`、`in`、`gte`、`lte`、`between`。
- `cursor` 是 opaque signed keyset cursor，不是 offset，客户端不得解码后自行改写。

## Response envelope

成功协议响应固定包含 `api_version`、`catalog_version`、`request_id`、
`dataset_id`、`schema_version`、`data`、`next_cursor` 和 `metadata`。
`metadata` 固定包含：

- `state`、`runtime_state` 与 `degraded`；
- 非空 `freshness`、`quality`、`lineage`；
- `receipt_id`、`data_through`、`observed_at`；
- `requested_as_of`、`resolved_as_of` 与 `reasons`。

`freshness`、`quality` 和 `lineage` 必须逐 dataset 解释，不能由全局状态补写。
`lineage` 标明 provider-neutral receipt authority 和 receipt watermark；缺 receipt 或不完整
lineage 不能伪装成健康结果。

## 六状态与消费规则

| `runtime_state` | `metadata.state` | degraded | rows | consumer action |
| --- | --- | :---: | --- | --- |
| `success` | `ready` | false | 可返回 | 可按自身业务规则使用 |
| `empty` | `empty` | false | `[]` | 只按合法空集处理，不等于缺证据 |
| `unobserved` | `unobserved` | true | `[]` | fail closed |
| `paused` | `paused` | true | `[]` | fail closed |
| `failed` | `failed` | true | 仅可返回已证明 prior-success 的 last-known rows | fail closed 或显式 down-weight |
| `stale` | `stale` | true | 可返回 last-known rows | 按 freshness/SLA 显式 down-weight |

HTTP 200 只表示协议处理成功，不表示 dataset 健康；一个 global source flag 也不足以代替
逐 dataset 的 freshness、quality、lineage、receipt 与 reasons。消费者必须从每个响应的
metadata fail closed 或 down-weight，不能仅凭 HTTP 200、非空 rows 或全局绿灯放行。

## Cursor semantics

服务签发的 signed keyset cursor 是两个 unpadded base64url segment，由单个 `.` 分隔。
它绑定 catalog version、dataset/schema major、normalized query、tenant access policy、
receipt snapshot watermark、sort tuple 和 expiry。客户端只把 `next_cursor` 原样放入下一页
同一请求；跨 dataset、query、policy 或 snapshot 重用必须失败，不能改成 offset 扫描。

## Fixture 使用方式

[sharedsignals_v1_query_contract.json](../tests/fixtures/sharedsignals_v1_query_contract.json) 只含
V1 public wire fields，并固定一个 catalog row、一个 healthy query response 和一个 degraded
query response。它是消费者解析/降级测试的 handoff artifact，不是实时数据、entitlement 或部署证据。
契约测试从受控 active registry 开始，经真实 SQLite writer + transaction-scoped success receipt，
再由 CatalogService、QueryService 和 real SignedCursorCodec 重建三个 public envelope，并与
静态 JSON 做完整 serializer parity；cursor 的 HMAC、receipt watermark 和七项真实 sort tuple
也由同一纵向切片验证。

消费者可导入 JSON fixture 做 schema/parity 测试，但不得 import SharedSignals、TradingAgent 或
MarketGraph 的业务代码来形成跨仓运行耦合。

## Truth layers

以下证据必须分别报告，任何一层都不能替代另一层：

1. local worktree PASS；
2. local main；
3. origin/GitHub；
4. production checkout；
5. production runtime；
6. external route；
7. real dataset evidence。

本地 fixture、测试或文档 PASS 只证明 local worktree candidate。它不证明已进入 local main，
也不证明 origin/GitHub、production checkout、production runtime、external route 或
real dataset evidence 已改变。
