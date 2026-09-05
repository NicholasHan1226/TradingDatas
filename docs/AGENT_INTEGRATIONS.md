# TradingDatas Agent integration contract

Prompt version: `2026-08-31.1`. The public dialog reads this Markdown as its
canonical source; `public-web/src/agentPrompts.js` extracts the authored blocks
and only substitutes the documented non-secret variables. Display branding is
normalized from the legacy `TradingData` name to `TradingDatas`.

## Purpose

TradingData is designed for Claude, Codex, OpenClaw, Hermes, and other Agents
that can call authenticated HTTP tools. This document freezes the copy-ready
setup prompt, Agent-specific wrappers, security behavior, and frontend
acceptance rules.

The integration surface is documentation and client setup. It does not add an
Agent-specific API, bypass authentication, install software into a third-party
account, or prove a production endpoint is available.

## Canonical variables

Every rendered prompt receives only these non-secret variables:

```text
{{TRADINGDATA_BASE_URL}}
{{AGENT_NAME}}
{{PROMPT_VERSION}}
```

The API key is stored separately as `TRADINGDATA_API_KEY` in the Agent's secret,
credential, or environment-variable facility. The renderer never substitutes
the key into prompt text, a URL, analytics, localStorage, screenshots, logs, or
copy history.

## Canonical setup prompt

All Agent-specific prompts compile from the following semantic source. Wording
may adapt to the target Agent, but numbered behavior may not drift.

```text
You have access to TradingData, an authenticated provider-neutral financial-data API.

Connection:
- Base URL: {{TRADINGDATA_BASE_URL}}
- Read the API key from the secret named TRADINGDATA_API_KEY.
- Send it as `Authorization: Bearer <secret>`.
- Never print, log, quote, summarize, or place the secret in a URL or response.

Required workflow for every data task:
1. Call `GET /v1/catalog` first. Discover only datasets visible to this account.
2. Select `dataset_id` and `schema_major` from that response. Never guess either value.
3. Call `POST /v1/query` with a bounded request using only catalog-supported fields and filters. Start with the smallest useful field set, date/window, and limit; never exceed the documented limit.
4. Follow `next_cursor` for pagination. Do not invent offsets or reuse a cursor with changed query parameters.
5. Before treating data as usable, inspect `metadata.state`, `runtime_state`, `degraded`, `freshness`, `quality`, `lineage`, `receipt_id`, `data_through`, `observed_at`, and `reasons`.
6. Treat HTTP 503 `service_unavailable`, missing receipt/lineage, `partial`, `degraded`, `stale`, `paused`, `failed`, `unobserved`, schema mismatch, authentication failure, and rate-limit responses as explicit limitations. Do not silently substitute another dataset, provider route, cached file, or external source. A query 503 can mean the page's own row receipts are missing or invalid even when catalog looks ready; do not invent rows or reuse an older HTTP 200.
7. Preserve dataset IDs, field names, timestamps, units, provider lineage, and revision/as-of caveats in downstream work.
8. TradingData supplies raw material. Do not describe its data as a TradingData strategy, signal, forecast, recommendation, or guaranteed research result.

When a request is ambiguous, show the relevant catalog choices and ask the user to choose. When no authorized dataset can satisfy the request, say so clearly.
```

## Canonical setup prompt (Chinese)

```text
你正在为 {{AGENT_NAME}} 准备 TradingDatas HTTP 数据工具（版本 {{PROMPT_VERSION}}）。
这不是 MCP 服务已部署或第三方 Agent 已自动配置成功的声明。

连接：
- API Base URL：{{TRADINGDATA_BASE_URL}}
- 从独立的安全密钥存储读取 TRADINGDATA_API_KEY，以 Authorization: Bearer <secret> 发送。
- 不在提示词、仓库、URL、浏览器存储、日志、截图或回复里输出密钥。
- 若 Base URL 尚未配置，或 Agent 无法独立保存密钥与执行认证 HTTP 请求，停止并报告不支持；不要猜测域名或使用浏览器 Cookie。

每次取数必须遵循：
1. 先调用 GET /v1/catalog，仅发现本账户可见的数据集。
2. 从返回结果选择 dataset_id、整数 schema_major 和 selectable 字段，不使用网页产品 slug 或猜测的版本；仅在 queryability.queryable === true 时查询，否则停止并说明 queryability.reasons。
3. 通过 POST /v1/query 发起有界请求。首次只取 limit=1，使用最小字段集与目录支持的时间筛选；分页不超过 `limits.max_page_size`，`in` 过滤值数量不超过 `limits.max_in_values`，未给出的限制不得自造。
4. 分页只使用返回的 next_cursor；不得自造 offset，也不得改变条件后复用游标。
5. 每次检查 metadata.state、runtime_state、degraded、freshness、quality、lineage、receipt_id、data_through、observed_at 和 reasons。HTTP 200 本身不证明数据可用。
6. 遇到缺 receipt/lineage、partial、degraded、stale、paused、failed、unobserved、schema mismatch、401、403 或 429，明确报告限制并停止自动重试。429 遵循 Retry-After；不得绕过限频、改用其它 provider route、缓存或外部数据补齐。
7. 保留字段名、时间戳、单位、provider 血缘和修订/as-of 限制。单次成功不证明完整历史、连续稳定或 PIT。
8. TradingDatas 提供数据原料，不提供策略、信号、预测、交易建议或保证的研究结果。

结果有歧义时展示目录候选请用户选择；没有符合权限的数据时明确说明。
```

The English canonical prompt above has the same stop conditions. Its rendered
version appends the shared first-query and HTTP-error checklist documented below.

### Shared first-query checklist

```text
First-query acceptance ({{PROMPT_VERSION}}):
- This configures an HTTP-capable tool, not a claim of a deployed MCP server.
- If the base URL is unconfigured or separate secret storage is unavailable, stop. Never guess a hostname or reuse browser cookies.
- Require queryability.queryable === true; otherwise stop and report queryability.reasons. Use selectable fields and integer schema_major from the catalog, start at limit=1, obey limits.max_page_size and limits.max_in_values, and use only supported time filters.
- HTTP 200 alone is not data readiness. One observation is not continuous stability, complete history, or point-in-time correctness.
- On 401, 403, 429 or schema mismatch, report the cause and stop automatic retries. For 429 respect Retry-After; never bypass rate limits or substitute a provider route.
```

## Agent variants

### Claude

Prefix the canonical prompt with:

```text
Configure or reuse an HTTP tool named `TradingData`. Keep the credential in the tool's secret store, not in project instructions or conversation text. Use the following operating instructions for this tool.
```

### Codex

Prefix the canonical prompt with:

```text
Use the available authenticated HTTP capability for a service named `TradingData`. Keep the credential in the workspace/user secret facility and never write it into repository files, shell history, patches, or tool output. Follow these operating instructions whenever TradingData is used.
```

### OpenClaw

Prefix the canonical prompt with:

```text
Create or reuse an authenticated HTTP skill named `TradingData`. Bind its credential from a secret and expose only the two read operations described below. Use these operating instructions for every invocation.
```

### Hermes

Prefix the canonical prompt with:

```text
Create or reuse an authenticated HTTP tool named `TradingData`. Store the key outside the prompt and pass it only in the Authorization header. Apply these operating instructions to planning and tool execution.
```

### Other Agent

Prefix the canonical prompt with:

```text
Configure an authenticated HTTP tool named `TradingData`. If the Agent cannot store a secret separately from its prompt or cannot make authenticated GET and POST requests, stop and report that this integration method is unsupported. Otherwise follow these operating instructions.
```

These variants are capability descriptions, not claims about a particular
third-party product version. Exact setup-field screenshots and product-specific
configuration formats require current official documentation and their own
verified implementation.

## Connection-page behavior

`/account/agent-connections` shows one selected Agent at a time. The page provides:

1. Agent selector: Claude, Codex, OpenClaw, Hermes, Other Agent;
2. base URL field sourced from deployment configuration;
3. secure key-entry or secret-storage instruction;
4. redacted prompt preview;
5. `Copy setup prompt` primary action;
6. optional `Test catalog connection` action;
7. current prompt version and fixed endpoint summary;
8. troubleshooting for invalid, expired, unauthorized, rate-limited, unavailable,
   and unsupported-Agent states.

Copying a prompt never triggers a network call. Testing the connection is an
explicit separate action and calls only `GET /v1/catalog`; it does not query a
dataset, consume a payment action, modify an account, or persist the raw key.

## Prompt compiler and tests

`public-web/src/agentPrompts.js` extracts the templates from this Markdown.
The headings below are load-bearing parser keys. Renaming them, wrapping them
in extra markup, or keeping a second full prompt in `AgentDialog.jsx` breaks
the dialog; there is no hardcoded fallback copy.

Locale compilation (every Agent × locale pair is tested independently):

| Locale | Concatenated source blocks |
| --- | --- |
| `en` | `### ${agent}` prefix + `## Canonical setup prompt` + `### Shared first-query checklist` |
| `zh` | `## Canonical setup prompt (Chinese)` only |

Chinese prompts do **not** receive Agent prefixes or the English checklist.
`tests/agent-prompts.test.mjs` requires the same semantic terms in both
languages, including `queryability.queryable === true`, `queryability.reasons`,
`selectable`, `limit=1`, `next_cursor`, `Retry-After`, and `TRADINGDATA_API_KEY`.
Add a required phrase to both language paths, or CI fails. Do not put a product
slug, guessed `schema_major`, or a live hostname into these blocks.

`VITE_TRADINGDATAS_API_BASE_URL` is public build configuration, never a secret
or proof that a route is live. The public build defaults it to
`https://tradingdatas.com` for the exact same-origin V1 gateway; an explicitly
empty override keeps the draft unconfigured. This origin currently exposes the
A-share registry, not the isolated Crypto service. `apiOrigin()` accepts only `https://host` with
no userinfo, path, query, or fragment. Anything else, including `http://` and
`https://host/v1`, stays unconfigured and the prompt uses the placeholder
`<TRADINGDATA_BASE_URL_FROM_ACCOUNT>`. Unresolved `{{...}}` placeholders and
unknown Agent names throw; the dialog must not copy a partial prompt.

Legacy spelling `TradingData` in these blocks is normalized to `TradingDatas`
at compile time. Keep `TRADINGDATA_API_KEY` / `TRADINGDATA_BASE_URL` as the
secret and variable names. Copying never sends a request. After Agent or
language changes, a late clipboard success is ignored. Escape returns focus;
Cmd/Ctrl+K is swallowed so the background search shortcut cannot fire.

Deterministic tests assert for every variant:

- exact fixed endpoints are present;
- catalog discovery precedes query;
- `dataset_id` and `schema_major` are catalog-derived;
- query guidance is bounded and cursor-aware;
- receipt, freshness, quality, lineage, degraded state, and HTTP 503
  `service_unavailable` are treated as explicit limitations;
- provider-specific fallback and invented data are forbidden;
- no API key or secret-shaped fixture appears in rendered text;
- copy feedback and screen-reader announcement are present;
- long prompt text scrolls inside its region without page overflow;
- mobile retains Agent selection, copy action, and security warning.

## Versioning and stop line

Prompt content is versioned independently of API runtime. A wording update does
not prove that public routing, connection testing, commerce, or production API
delivery exists. Any change to endpoint behavior, authentication, request
schema, metadata interpretation, or rate limits updates `docs/API.md`, this
document, product/design contracts, tests, and the enforcing code together.
