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
and both workspaces use the same typographic TradingDatas wordmark, graphite
shell, neutral work canvas, cobalt action colour, and restrained market accents.
The workspace is intentionally horizontal rather than a conventional tall
admin sidebar: brand and role sit in the first header row, task navigation in
the second, and every page follows decision summary -> primary task -> detail.

The design avoids ornamental glass, oversized gradients, excessive same-weight
cards, fake live numbers, security-product language, and green link markers.
Green is reserved for healthy state. Cyan, violet, and orange identify market
context or navigation position, never authorization or runtime health.

## Tokens

### Typography

- UI: system sans with PingFang SC, Hiragino Sans GB, Microsoft YaHei and Noto
  Sans SC fallbacks.
- Data and identifiers: system monospace.
- Scale: 10 / 11 / 12 / 13 / 14 / 17 / 20 / 26 / 30 / 36px.
- Headings use 600 weight and tight tracking. Labels use 500-600. Body text uses
  400-500 with 1.5-1.7 line height.

### Colour

- `--td-shell`: graphite application chrome.
- `--td-canvas`, `--td-surface*`: neutral working layers.
- `--td-ink*`, `--td-muted`, `--td-faint`: four text levels.
- `--td-accent*`: selection, focus and primary actions.
- `--td-cyan`, `--td-violet`, `--td-orange`: market and section accents.
- `--td-success`, `--td-warning`, `--td-danger`, `--td-info`: status only.

### Geometry and motion

- 4px base rhythm: 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40.
- Radius: 7px controls, 12px panels, 16-18px feature surfaces/dialogs.
- Shadow 1 separates interactive panels; shadow 2 is for dialogs and the login
  task. Dense data tables use borders rather than elevation.
- Functional colour/border feedback uses 120ms. Pages and cards do not animate
  into view. Reduced-motion remains global.

## Component contract

- **Workspace shell**: two-row graphite header, persistent logout, optional
  workspace switch, horizontally scrollable mobile navigation, and visible
  customer-preview notice.
- **Page header**: small contextual rule/eyebrow, one clear title, one sentence
  of task guidance, and at most one action cluster.
- **Button / input**: minimum 36-40px hit area, explicit hover/focus/disabled/
  loading states, semantic danger styling, and readable icon labels.
- **Card**: 12px radius, low elevation, clear internal header. Cards group tasks;
  they are not used to give every metric equal weight.
- **Table**: sticky quiet header, 44px minimum rows, tabular numbers, local
  horizontal scrolling, row actions at the end, and responsive containment.
- **Dialog**: labelled modal, Escape/backdrop close, destructive copy separated
  from the action, and one-time secrets clearly isolated.
- **Chart**: Recharts with neutral grids, token-driven series colour, responsive
  container, readable tooltip, and explicit empty state.
- **Icons**: Lucide React only for interface icons. The TradingDatas product mark
  remains typography-only.

## Page information architecture

### Admin

1. Customers and keys: search, create, edit, pause, delete, scopes, market
   categories, expiry, quota and usage.
2. Usage and capacity: daily/hour windows, trend and per-tenant pressure.
3. Data runtime: activation, receipt/runtime state, freshness and coverage.
4. Incident centre: severity-filtered operator signals.
5. Data browser: catalog selection, current metadata, sample query and cursor.

### Customer

1. Home: account status, plan, enabled markets, current usage, rate/concurrency,
   expiry, 30-day trend and a three-step onboarding path.
2. Permissions and limits: server-projected market entitlements, endpoint
   abilities, expiry and every active ceiling.
3. Documentation: API quickstart, Agent prompt/tool definitions, pagination,
   throttling, read-only boundary and secret-handling rules.

## Reference implementation choices

- Recharts remains the chart layer to avoid an unnecessary migration.
- Lucide React replaces locally drawn interface icons and is tree-shakable.
- shadcn/ui composition patterns inform the shell, tables and chart tokens, but
  its entire runtime is not installed; TradingDatas owns its visual language.
- Radix Dialog provides focus trapping, Escape handling and screen-reader title
  semantics for credential workflows. TanStack Table remains a later candidate
  if sorting or large-table virtualization becomes a real product requirement.

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
