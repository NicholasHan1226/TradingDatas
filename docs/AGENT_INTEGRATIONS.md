# TradingData Agent integration contract

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
6. Treat missing receipt/lineage, `partial`, `degraded`, `stale`, `paused`, `failed`, `unobserved`, schema mismatch, authentication failure, rate-limit responses, and HTTP 503 `service_unavailable` as explicit limitations. A 503 may be marked `retryable: true`; that does not mean a retry reconstructs missing receipts or rows omitted from an explicitly failed collection sequence. Query may return HTTP 200 while omitting those failed-sequence prefix rows; do not invent the omitted rows, and do not silently substitute another dataset, provider route, cached file, or external source.
7. Preserve dataset IDs, field names, timestamps, units, provider lineage, and revision/as-of caveats in downstream work.
8. TradingData supplies raw material. Do not describe its data as a TradingData strategy, signal, forecast, recommendation, or guaranteed research result.

When a request is ambiguous, show the relevant catalog choices and ask the user to choose. When no authorized dataset can satisfy the request, say so clearly.
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

The future frontend maintains one typed canonical template and thin Agent
prefixes. It must not keep separate complete prompt strings in UI components.

Deterministic tests assert for every variant:

- exact fixed endpoints are present;
- catalog discovery precedes query;
- `dataset_id` and `schema_major` are catalog-derived;
- query guidance is bounded and cursor-aware;
- receipt, freshness, quality, lineage, and degraded state are checked;
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
