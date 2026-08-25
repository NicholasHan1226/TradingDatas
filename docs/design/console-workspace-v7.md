# TradingDatas console workspace v7

## Purpose and compatibility

v7 is a static-console refinement of the existing v4/v5/v6 product contract.
It preserves bearer-token login, hash routes, API contracts, role routing,
customer-preview behaviour, local-only interface preferences, and the built
`static/app/` release path. It does not change token values, account grants,
collectors, databases, schedulers, or service processes.

## Design direction

The shared direction is **luminous data workspace**: a deep navy brand rail
anchors both workspaces, while a cool light data canvas carries operational and
customer content. This retains the login page's blue/cyan energy without
turning the content area into a black terminal. The product mark remains the
typography-only `TradingDatas` wordmark.

- The desktop admin and customer shells now share the same 244px navigation
  rail, footer actions, responsive mobile header, focus treatment, and exit
  location. Admin grouping is `Access` / `Data`; customer navigation stays
  task-oriented.
- Accent colour differentiates navigation and market families. It is not a
  substitute for health. Green remains limited to a healthy state.
- Content remains predominantly light and legible. Code, API definitions and
  copy actions use a light developer surface; the former broad dark code block
  treatment is not used.

## Data-state language

Runtime data remains authoritative from the existing collection, health and
query endpoints. v7 changes only the presentation layer:

| Runtime input | Visible language | Operator guidance |
| --- | --- | --- |
| `freshness_sla_exceeded` | 超过预期更新窗口 | 核对最近成功回执与下一采集窗口 |
| `data_through_in_future` | 数据时间需要校验 | 保留真实水位，不把后续数据回填为早时点 |
| `storage_failed` | 本次写入未完成 | 核对采集回执与存储状态 |
| provider unavailable/error | 上游服务暂不可用 / 上游调用未成功 | 检查上游响应、授权、限流后有界重试 |
| `no_recognized_receipt` | 尚未找到有效运行回执 | 确认正式采集计划与首次回执 |

The visible console does not expose these raw machine codes by default.
Collection rows show a plain-language state and reason. Health cards separate
the reason from the suggested action. Data Browser makes 429 and 503 responses
actionable; in particular, a 503 explains that the service did not substitute
data from another point in time.

## Component changes

- `WorkspaceShell`: unified rail, mobile header, workspace switch and persistent
  logout. An admin customer preview is labelled as a preview and remains a
  projection of the admin's own account.
- `RuntimeStatus`: one accessible state badge and optional human-readable
  reason line shared by the collection table and data browser.
- `ErrorBanner`, controls, cards, tables and developer panels: navy-tinted
  tokens, clearer focus ring, 8-12px surface geometry and restrained elevation.
- Collection: an explicit attention strip explains that abnormal rows retain
  truthful receipts instead of inferred values.

## Quality gate

v7 is expected to meet the following visual-acceptance score before release:

| Dimension | Score | Basis |
| --- | ---: | --- |
| Hierarchy and readability | 11/12 | One clear task heading and compact rail grouping |
| Brand coherence | 11/12 | Shared wordmark, navy/cyan anchor and token system |
| Layout and density | 11/12 | Full-width data work area; dense tables retain containment |
| Interaction clarity | 11/12 | Persistent exit/switch, in-place copy confirmation, focus states |
| Data-state clarity | 12/12 | Human language, no hidden substitution claim, practical next action |
| Responsive behaviour | 10/12 | Shared mobile header and horizontal rail verified at 390px |
| Accessibility and semantics | 10/12 | Named navigation, headings, tabs, table labels and focus treatment |
| Consistency and implementation quality | 10/12 | Shared tokens and components; no API or runtime divergence |
| **Total** | **86/100** | Production candidate after CI, Pages and production readback |

## Validation and rollback

Local visual validation uses the isolated mock service and covers both role
routes, all admin panels, all customer sections, the admin preview return path,
desktop and 390px widths. It is interface evidence only and does not assert
production data freshness or data-plane health.

Reverting the frontend merge commit restores the preceding static bundle. No
backend service restart, token rotation, collector change, or database rollback
is required.
