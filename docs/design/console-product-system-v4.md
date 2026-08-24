# TradingDatas console product system v4

## Product roles

The console is one application with two distinct task environments:

- **Admin workspace**: owner-only operations for customer credentials, usage,
  collection state, alerts, and catalog/query verification.
- **Customer workspace**: a self-service portal for the authenticated customer's
  plan, entitlements, expiry, usage, and Agent integration documentation.

Customer credentials cannot enter admin. An owner credential is expected to
have both `read` and `admin`, opens admin by default, and can switch into a
clearly labelled customer-view preview. Preview uses the owner's own portal
projection; it is not customer impersonation and does not mutate credentials.

## Design direction

The shared direction is **precision infrastructure / calm fintech**. The login
and both workspaces use the same typography-only TradingDatas wordmark, warm
porcelain canvas, ink text, cobalt action colour, and restrained lilac/orange
accents. The workspace is intentionally horizontal rather than a conventional
tall admin sidebar: brand and role sit in the first header row, task navigation
in the second, and every page follows decision summary -> primary task -> detail.

The design avoids ornamental glass, oversized gradients, excessive same-weight
cards, fake live numbers, security-product language, and green link markers.
Green is reserved for healthy state. Cyan, violet, and orange identify market
context or navigation position, never authorization or runtime health.

## Tokens

### Typography

- UI: Inter/SF Pro Text with PingFang SC, Hiragino Sans GB, Microsoft YaHei and
  Noto Sans SC fallbacks.
- Data and identifiers: system monospace.
- Scale: 10 / 11 / 12 / 13 / 14 / 17 / 20 / 26 / 30 / 36px.
- Headings use 600 weight and tight tracking. Labels use 500-600. Body text uses
  400-500 with 1.5-1.7 line height.

### Colour

- `--td-shell`: near-black action and code chrome, not a persistent dark header.
- `--td-canvas`, `--td-surface*`: neutral working layers.
- `--td-ink*`, `--td-muted`, `--td-faint`: four text levels.
- `--td-accent*`: selection, focus and primary actions.
- `--td-cyan`, `--td-violet`, `--td-orange`: market and section accents.
- `--td-success`, `--td-warning`, `--td-danger`, `--td-info`: status only.

### Geometry and motion

- 4px base rhythm: 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40.
- Radius: 5px compact controls, 7px task panels, 10px large surfaces/dialogs.
- Shadow 1 separates interactive panels; shadow 2 is for dialogs and the login
  task. Dense data tables use borders rather than elevation.
- Functional colour/border feedback uses 120ms. Pages and cards do not animate
  into view. Reduced-motion remains global.

## Component contract

- **Workspace shell**: two-row warm light header, persistent logout, optional
  workspace switch, horizontally scrollable mobile navigation, and visible
  customer-preview notice. Route changes return page content to the top.
- **Page header**: small contextual rule/eyebrow, one clear title, one sentence
  of task guidance, and at most one action cluster. Context labels are concise
  Chinese task nouns rather than decorative uppercase system language.
- **Button / input**: minimum 36-40px hit area, explicit hover/focus/disabled/
  loading states, semantic danger styling, and readable icon labels.
- **Card**: 7px radius, hairline or low elevation, clear internal header. Cards group tasks;
  they are not used to give every metric equal weight.
- **Table**: sticky quiet header, 44px minimum rows, tabular numbers, local
  horizontal scrolling, row actions at the end, and responsive containment.
- **Dialog**: labelled modal, Escape/backdrop close, destructive copy separated
  from the action, and one-time secrets clearly isolated.
- **Chart**: Recharts with neutral grids, token-driven series colour, responsive
  container, readable tooltip, and explicit empty state.
- **Icons**: Phosphor regular-weight icons for the shared shell and first-level
  navigation. Existing feature icons may migrate incrementally, but one visible
  control cannot mix icon families. The TradingDatas product mark remains
  typography-only.
- **Copy actions**: the action sits inside the code/task surface and confirms
  success in place (`已复制`). Success toasts are avoided; failures remain
  explicit. Labels describe the real artifact: `复制提示词`、`复制定义`、`复制示例`.
- **Permission tags**: known scopes are customer-readable nouns (`读取`、`查询`、
  `目录`、`管理`), with neutral surfaces instead of slash-prefixed system tokens.

## Page information architecture

### Admin

1. Customers and keys: search, create, edit, pause, delete, scopes, market
   categories, expiry, quota and usage.
2. Usage and capacity: daily/hour windows, trend and per-tenant pressure.
3. Data runtime: activation, receipt/runtime state, freshness and coverage.
4. Incident centre: severity-filtered operator signals.
5. Data browser: catalog selection, current metadata, sample query and cursor.

### Customer

1. Home: an Agent connection workbench with Claude/Codex/OpenClaw/Hermes
   context tabs, truthful prompt/tool/API artifacts, account/market limits,
   expiry and 30-day usage. It must never imply a one-click connection or MCP
   package that the product does not provide.
2. Permissions and limits: server-projected market entitlements, endpoint
   abilities, expiry and every active ceiling. This page uses one account
   contract surface and a ledger hierarchy rather than four same-weight cards.
3. Documentation: API quickstart, Agent prompt/tool definitions, pagination,
   throttling, read-only boundary and secret-handling rules. Navigation and
   article content share one editorial frame; code actions stay adjacent to the
   artifact they copy.

## Deep-surface conventions

- Runtime and activation values retain their backend identifiers internally,
  but visible labels use customer-readable Chinese (`运行正常`、`本次无新增`、
  `已启用`、`已暂停`). Raw identifiers remain available in data and receipts.
- Desktop credential management uses the full comparison table. Below 640px it
  becomes a task card per customer so scopes, markets, quota, expiry and actions
  remain legible without squeezing nine columns into the viewport.
- Metric collections use bordered ledgers or divided strips before introducing
  another layer of independent cards. Accent colour identifies focus or market
  family; healthy state alone may use green.
- Code panels use one near-black neutral surface, 11px monospace text and a
  local copy action. They never expose or prefill an actual API key.

## Reference implementation choices

- Recharts remains the chart layer to avoid an unnecessary migration.
- Phosphor React supplies the shared shell and first-level navigation icons and
  is tree-shakable. No hand-drawn SVG or glyph substitutes are used.
- shadcn/ui composition patterns inform the shell, tables and chart tokens, but
  its entire runtime is not installed; TradingDatas owns its visual language.
- Radix Dialog provides focus trapping, Escape handling and screen-reader title
  semantics for credential workflows. The later productivity contract in
  `console-productivity-v5.md` adopts TanStack Table and Virtual for operator
  sorting, column visibility and large-row rendering without replacing this
  visual system.

## Responsive and QA contract

- Verify desktop, tablet and mobile widths; the document layout stacks on
  mobile and the global navigation scrolls without hiding logout.
- Every admin panel must load its real endpoint without an error placeholder.
- Customer and admin role routing must be tested separately; admin preview and
  return must not re-authenticate or alter the token.
- Visual QA compares before/after screenshots at the same viewport and checks
  hierarchy, overflow, density, focus, empty/error/loading and destructive
  states.

## Runtime boundary and rollback

This release changes static frontend source/build output and documentation only.
It does not rotate tokens, change databases, alter collectors/schedulers, or
restart data-plane services. Reverting the frontend merge commit restores the
previous bundle without modifying the data pipeline.
