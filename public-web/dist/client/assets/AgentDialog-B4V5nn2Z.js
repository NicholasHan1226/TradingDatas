import{r as p,j as t,e as v,f as x,b as _}from"./index-BZtC9up5.js";import"./react-vendor-CXZBankB.js";import"./research-catalog-u8USlL-B.js";const w=`# TradingDatas Agent integration contract

Prompt version: \`2026-08-31.1\`. The public dialog reads this Markdown as its
canonical source; \`public-web/src/agentPrompts.js\` extracts the authored blocks
and only substitutes the documented non-secret variables. Display branding is
normalized from the legacy \`TradingData\` name to \`TradingDatas\`.

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

\`\`\`text
{{TRADINGDATA_BASE_URL}}
{{AGENT_NAME}}
{{PROMPT_VERSION}}
\`\`\`

The API key is stored separately as \`TRADINGDATA_API_KEY\` in the Agent's secret,
credential, or environment-variable facility. The renderer never substitutes
the key into prompt text, a URL, analytics, localStorage, screenshots, logs, or
copy history.

## Canonical setup prompt

All Agent-specific prompts compile from the following semantic source. Wording
may adapt to the target Agent, but numbered behavior may not drift.

\`\`\`text
You have access to TradingData, an authenticated provider-neutral financial-data API.

Connection:
- Base URL: {{TRADINGDATA_BASE_URL}}
- Read the API key from the secret named TRADINGDATA_API_KEY.
- Send it as \`Authorization: Bearer <secret>\`.
- Never print, log, quote, summarize, or place the secret in a URL or response.

Required workflow for every data task:
1. Call \`GET /v1/catalog\` first. Discover only datasets visible to this account.
2. Select \`dataset_id\` and \`schema_major\` from that response. Never guess either value.
3. Call \`POST /v1/query\` with a bounded request using only catalog-supported fields and filters. Start with the smallest useful field set, date/window, and limit; never exceed the documented limit.
4. Follow \`next_cursor\` for pagination. Do not invent offsets or reuse a cursor with changed query parameters.
5. Before treating data as usable, inspect \`metadata.state\`, \`runtime_state\`, \`degraded\`, \`freshness\`, \`quality\`, \`lineage\`, \`receipt_id\`, \`data_through\`, \`observed_at\`, and \`reasons\`.
6. Treat HTTP 503 \`service_unavailable\`, missing receipt/lineage, \`partial\`, \`degraded\`, \`stale\`, \`paused\`, \`failed\`, \`unobserved\`, schema mismatch, authentication failure, and rate-limit responses as explicit limitations. Do not silently substitute another dataset, provider route, cached file, or external source. A query 503 can mean the page's own row receipts are missing or invalid even when catalog looks ready; do not invent rows or reuse an older HTTP 200.
7. Preserve dataset IDs, field names, timestamps, units, provider lineage, and revision/as-of caveats in downstream work.
8. TradingData supplies raw material. Do not describe its data as a TradingData strategy, signal, forecast, recommendation, or guaranteed research result.

When a request is ambiguous, show the relevant catalog choices and ask the user to choose. When no authorized dataset can satisfy the request, say so clearly.
\`\`\`

## Canonical setup prompt (Chinese)

\`\`\`text
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
3. 通过 POST /v1/query 发起有界请求。首次只取 limit=1，使用最小字段集与目录支持的时间筛选；分页不超过 \`limits.max_page_size\`，\`in\` 过滤值数量不超过 \`limits.max_in_values\`，未给出的限制不得自造。
4. 分页只使用返回的 next_cursor；不得自造 offset，也不得改变条件后复用游标。
5. 每次检查 metadata.state、runtime_state、degraded、freshness、quality、lineage、receipt_id、data_through、observed_at 和 reasons。HTTP 200 本身不证明数据可用。
6. 遇到缺 receipt/lineage、partial、degraded、stale、paused、failed、unobserved、schema mismatch、401、403 或 429，明确报告限制并停止自动重试。429 遵循 Retry-After；不得绕过限频、改用其它 provider route、缓存或外部数据补齐。
7. 保留字段名、时间戳、单位、provider 血缘和修订/as-of 限制。单次成功不证明完整历史、连续稳定或 PIT。
8. TradingDatas 提供数据原料，不提供策略、信号、预测、交易建议或保证的研究结果。

结果有歧义时展示目录候选请用户选择；没有符合权限的数据时明确说明。
\`\`\`

The English canonical prompt above has the same stop conditions. Its rendered
version appends the shared first-query and HTTP-error checklist documented below.

### Shared first-query checklist

\`\`\`text
First-query acceptance ({{PROMPT_VERSION}}):
- This configures an HTTP-capable tool, not a claim of a deployed MCP server.
- If the base URL is unconfigured or separate secret storage is unavailable, stop. Never guess a hostname or reuse browser cookies.
- Require queryability.queryable === true; otherwise stop and report queryability.reasons. Use selectable fields and integer schema_major from the catalog, start at limit=1, obey limits.max_page_size and limits.max_in_values, and use only supported time filters.
- HTTP 200 alone is not data readiness. One observation is not continuous stability, complete history, or point-in-time correctness.
- On 401, 403, 429 or schema mismatch, report the cause and stop automatic retries. For 429 respect Retry-After; never bypass rate limits or substitute a provider route.
\`\`\`

## Agent variants

### Claude

Prefix the canonical prompt with:

\`\`\`text
Configure or reuse an HTTP tool named \`TradingData\`. Keep the credential in the tool's secret store, not in project instructions or conversation text. Use the following operating instructions for this tool.
\`\`\`

### Codex

Prefix the canonical prompt with:

\`\`\`text
Use the available authenticated HTTP capability for a service named \`TradingData\`. Keep the credential in the workspace/user secret facility and never write it into repository files, shell history, patches, or tool output. Follow these operating instructions whenever TradingData is used.
\`\`\`

### OpenClaw

Prefix the canonical prompt with:

\`\`\`text
Create or reuse an authenticated HTTP skill named \`TradingData\`. Bind its credential from a secret and expose only the two read operations described below. Use these operating instructions for every invocation.
\`\`\`

### Hermes

Prefix the canonical prompt with:

\`\`\`text
Create or reuse an authenticated HTTP tool named \`TradingData\`. Store the key outside the prompt and pass it only in the Authorization header. Apply these operating instructions to planning and tool execution.
\`\`\`

### Other Agent

Prefix the canonical prompt with:

\`\`\`text
Configure an authenticated HTTP tool named \`TradingData\`. If the Agent cannot store a secret separately from its prompt or cannot make authenticated GET and POST requests, stop and report that this integration method is unsupported. Otherwise follow these operating instructions.
\`\`\`

These variants are capability descriptions, not claims about a particular
third-party product version. Exact setup-field screenshots and product-specific
configuration formats require current official documentation and their own
verified implementation.

## Connection-page behavior

Public \`/connect\` shows one selected Agent at a time, reached through Help &
setup and public Docs. Reading/copying tutorials and templates does not require
website login. Actual catalog/query calls still require the caller's independent
Bearer credential; a web session never supplies one. The page provides:

1. Agent selector: Claude, Codex, OpenClaw, Hermes, Other Agent;
2. base URL field sourced from deployment configuration;
3. secure key-entry or secret-storage instruction;
4. redacted prompt preview;
5. \`Copy setup prompt\` primary action;
6. optional \`Test catalog connection\` action;
7. current prompt version and fixed endpoint summary;
8. troubleshooting for invalid, expired, unauthorized, rate-limited, unavailable,
   and unsupported-Agent states.

Copying a prompt never triggers a network call. Testing the connection is an
explicit separate action and calls only \`GET /v1/catalog\`; it does not query a
dataset, consume a payment action, modify an account, or persist the raw key.

## Prompt compiler and tests

\`public-web/src/agentPrompts.js\` extracts the templates from this Markdown.
The headings below are load-bearing parser keys. Renaming them, wrapping them
in extra markup, or keeping a second full prompt in \`AgentDialog.jsx\` breaks
the dialog; there is no hardcoded fallback copy.

Locale compilation (every Agent × locale pair is tested independently):

| Locale | Concatenated source blocks |
| --- | --- |
| \`en\` | \`### \${agent}\` prefix + \`## Canonical setup prompt\` + \`### Shared first-query checklist\` |
| \`zh\` | \`## Canonical setup prompt (Chinese)\` only |

Chinese prompts do **not** receive Agent prefixes or the English checklist.
\`tests/agent-prompts.test.mjs\` requires the same semantic terms in both
languages, including \`queryability.queryable === true\`, \`queryability.reasons\`,
\`selectable\`, \`limit=1\`, \`next_cursor\`, \`Retry-After\`, and \`TRADINGDATA_API_KEY\`.
Add a required phrase to both language paths, or CI fails. Do not put a product
slug, guessed \`schema_major\`, or a live hostname into these blocks.

\`VITE_TRADINGDATAS_API_BASE_URL\` is public build configuration, never a secret
or proof that a route is live. The public build defaults it to
\`https://tradingdatas.com\` for the exact same-origin V1 gateway; an explicitly
empty override keeps the draft unconfigured. This origin currently exposes the
A-share registry, not the isolated Crypto service. \`apiOrigin()\` accepts only \`https://host\` with
no userinfo, path, query, or fragment. Anything else, including \`http://\` and
\`https://host/v1\`, stays unconfigured and the prompt uses the placeholder
\`<TRADINGDATA_BASE_URL_FROM_ACCOUNT>\`. Unresolved \`{{...}}\` placeholders and
unknown Agent names throw; the dialog must not copy a partial prompt.

Legacy spelling \`TradingData\` in these blocks is normalized to \`TradingDatas\`
at compile time. Keep \`TRADINGDATA_API_KEY\` / \`TRADINGDATA_BASE_URL\` as the
secret and variable names. Copying never sends a request. After Agent or
language changes, a late clipboard success is ignored. Escape returns focus;
Cmd/Ctrl+K is swallowed so the background search shortcut cannot fire.

Deterministic tests assert for every variant:

- exact fixed endpoints are present;
- catalog discovery precedes query;
- \`dataset_id\` and \`schema_major\` are catalog-derived;
- query guidance is bounded and cursor-aware;
- receipt, freshness, quality, lineage, degraded state, and HTTP 503
  \`service_unavailable\` are treated as explicit limitations;
- provider-specific fallback and invented data are forbidden;
- no API key or secret-shaped fixture appears in rendered text;
- copy feedback and screen-reader announcement are present;
- long prompt text scrolls inside its region without page overflow;
- mobile retains Agent selection, copy action, and security warning.

## Versioning and stop line

Prompt content is versioned independently of API runtime. A wording update does
not prove that public routing, connection testing, commerce, or production API
delivery exists. Any change to endpoint behavior, authentication, request
schema, metadata interpretation, or rate limits updates \`docs/API.md\`, this
document, product/design contracts, tests, and the enforcing code together.
`,A=["Claude","Codex","OpenClaw","Hermes","Other Agent"],P="<TRADINGDATA_BASE_URL_FROM_ACCOUNT>";function y(a,n){const i=a.split(`${n}
`)[1],s=i==null?void 0:i.match(/```text\n([\s\S]*?)\n```/);if(!s)throw new Error("agent_contract_missing");return s[1]}function D(a=""){if(!a)return null;try{const n=new URL(a);return n.protocol!=="https:"||n.username||n.password||n.search||n.hash||n.pathname!=="/"?null:n.origin}catch{return null}}function C(a,{agent:n="Codex",locale:i="en",baseUrl:s=""}={}){var c;if(!A.includes(n))throw new Error("unsupported_agent");const u=(c=a.match(/Prompt version: `([^`]+)`/))==null?void 0:c[1];if(!u)throw new Error("agent_contract_missing");const o=D(s),l=(i==="zh"?y(a,"## Canonical setup prompt (Chinese)"):[y(a,`### ${n}`),y(a,"## Canonical setup prompt"),y(a,"### Shared first-query checklist")].join(`

`)).replace(/\bTradingData\b/g,"TradingDatas").replaceAll("{{TRADINGDATA_BASE_URL}}",o||P).replaceAll("{{AGENT_NAME}}",n).replaceAll("{{PROMPT_VERSION}}",u);if(/\{\{/.test(l))throw new Error("agent_contract_unresolved");return{text:l,version:u,endpoint:o,configured:!!o}}function N({onClose:a,copy:n,locale:i}){const[s,u]=p.useState("Codex"),[o,h]=p.useState("idle"),l=p.useRef(null),c=p.useRef(0),r=i==="zh",d=p.useMemo(()=>C(w,{agent:s,locale:i,baseUrl:"https://tradingdatas.com"}),[s,i]);p.useEffect(()=>{var g;const e=document.activeElement;return(g=l.current)==null||g.focus(),()=>{++c.current,e!=null&&e.isConnected&&e.focus()}},[]),p.useEffect(()=>{++c.current,h("idle")},[s,i]);async function T(){const e=++c.current;h("pending");try{await navigator.clipboard.writeText(d.text),e===c.current&&h("copied")}catch{e===c.current&&h("failed")}}function b(e){if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==="k"){e.preventDefault(),e.stopPropagation();return}if(e.key==="Escape"){e.preventDefault(),a();return}if(e.key!=="Tab")return;const g=[...l.current.querySelectorAll('button:not(:disabled), a[href], [tabindex="0"]')],m=g[0],f=g.at(-1);e.shiftKey&&(document.activeElement===m||document.activeElement===l.current)?(e.preventDefault(),f==null||f.focus()):!e.shiftKey&&document.activeElement===f&&(e.preventDefault(),m==null||m.focus())}return t.jsx("div",{className:"dialog-backdrop",role:"presentation",onMouseDown:e=>e.target===e.currentTarget&&a(),children:t.jsxs("section",{className:"agent-dialog",role:"dialog","aria-modal":"true","aria-labelledby":"agent-dialog-title",tabIndex:"-1",ref:l,onKeyDown:b,children:[t.jsx("button",{className:"icon-button dialog-close",type:"button",onClick:a,"aria-label":n.close,children:t.jsx(v,{size:20})}),t.jsx("span",{className:"mono-kicker",children:"AGENT CONNECTIONS / HTTP"}),t.jsx("h2",{id:"agent-dialog-title",children:n.agentTitle}),t.jsx("p",{children:r?"一份接入说明，先发现目录，再验证数据。密钥单独保存；复制不会发起请求。":"One setup guide: discover the catalog, then verify the data. Keep secrets separate; copying sends no requests."}),t.jsx("div",{className:"agent-tabs",role:"group","aria-label":"Agent",children:A.map(e=>t.jsx("button",{type:"button","aria-pressed":s===e,className:s===e?"is-active":"",onClick:()=>u(e),children:e},e))}),t.jsxs("div",{className:"endpoint-row",children:[t.jsxs("span",{children:["API · ",d.configured?r?"已配置，待验证":"configured, not verified":r?"待配置":"not configured"]}),t.jsx("code",{children:d.endpoint||(r?"正式地址由账户服务提供":"Obtain the service origin from Account")})]}),t.jsx("p",{className:"agent-readiness-note",children:r?"这是 HTTP 工具接入说明，不代表 MCP 服务器已上线。先在 Agent 的安全设置保存 TRADINGDATA_API_KEY。":"These are HTTP tool instructions, not a claim of a live MCP server. Store TRADINGDATA_API_KEY in your Agent’s secure settings first."}),t.jsxs("div",{className:"prompt-block",children:[t.jsxs("div",{children:[t.jsx("span",{children:d.configured?n.setupPrompt:r?"接入草稿 · 地址待配置":"Setup draft · origin pending"}),t.jsx("span",{children:d.version})]}),t.jsx("pre",{tabIndex:"0","aria-label":r?"接入提示词":"Setup prompt",children:d.text})]}),t.jsxs("div",{className:"agent-acceptance-steps",children:[t.jsx("span",{children:"01 · Catalog"}),t.jsx("span",{children:"02 · Query · limit=1"}),t.jsx("span",{children:"03 · Receipt & limitations"})]}),t.jsxs("button",{className:"primary-button dialog-action",type:"button",onClick:T,disabled:o==="pending",children:[o==="copied"?t.jsx(x,{weight:"bold"}):t.jsx(_,{weight:"bold"}),o==="copied"?n.copied:o==="pending"?r?"正在复制…":"Copying…":d.configured?n.copyPrompt:r?"复制接入草稿":"Copy setup draft"]}),t.jsx("p",{className:"agent-copy-status",role:"status",children:o==="failed"?r?"复制未成功，请手动选择上方提示词。":"Copy failed. Select the prompt above to copy it manually.":o==="copied"?r?"已复制。尚未执行连接或数据查询。":"Copied. No connection or data query has been executed.":r?"配置成功后仍需实际验证身份、字段和回执。":"Configuration still needs real authentication, schema and receipt verification."})]})})}export{N as default};
