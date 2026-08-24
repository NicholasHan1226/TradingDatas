# TradingDatas Agent workbench design QA

## Evidence

- Source visual truth: `/Users/nicholashan/.codex/generated_images/01a03158-d267-7ba3-b153-91258073cbe3/exec-e5dd9abc-3f5b-41b8-bd56-d520ae88f6dc.png`
- Browser-rendered implementation: `/Users/nicholashan/Projects/Finance/TradingDatas/.artifacts/design-v10/customer-agent-workbench-desktop-final.png`
- Mobile implementation: `/Users/nicholashan/Projects/Finance/TradingDatas/.artifacts/design-v10/customer-agent-workbench-mobile-final.png`
- Normalized full-view comparison: `/Users/nicholashan/Projects/Finance/TradingDatas/.artifacts/design-v10/source-vs-implementation.png`
- Desktop viewport: 1440 x 1024 CSS px. Source pixels: 1487 x 1058. Implementation pixels: 1432 x 1018. Both were proportionally scaled into 720 x 512 comparison cells at density 1.
- Mobile viewport: 390 x 844 CSS px. Implementation pixels: 382 x 827 at density 1.
- State: authenticated administrator previewing the customer workspace, `概览`, Claude, `接入提示词`.

## Full-view comparison

The implementation preserves the selected direction: typography-only wordmark, two-row horizontal navigation, warm light canvas, left Agent workbench, right entitlement ledger, compact cobalt/lilac/orange accents, and low-radius bordered surfaces. The implementation intentionally omits the mock's request-level Agent activity table because the current portal contract exposes daily usage history but not truthful per-request Agent, market, dataset, latency, or result data.

## Focused comparison

- Typography: Inter/SF Pro Text and Chinese system fallbacks reproduce the tight display hierarchy and compact operational labels without overflow.
- Spacing/layout: the workbench and access ledger keep the source's major-region proportions; the mobile layout stacks without hiding persistent switch or logout controls.
- Colors/tokens: warm porcelain, ink, cobalt, lilac and orange map to the source without gradients or green link treatments.
- Image/assets: this screen has no raster imagery. The wordmark is intentionally typography-only; all interface and Agent selector icons come from Phosphor rather than handmade SVG/CSS art.
- Copy/content: copy actions name the real artifact (`复制提示词`、`复制定义`、`复制示例`) and do not imply a one-click connection or a nonexistent MCP package. The service address is not visible in the workbench.
- Interactions: Agent tabs, setup tabs, in-place copied state, documentation link, admin/customer switch, all customer sections, all five admin sections, logout, and re-login were exercised in the in-app browser. Browser logs contained no error-level entries.

## Comparison history

1. P2 mobile Agent selector wrapped Hermes onto a second line. Fixed by converting the selector to a single compact Phosphor icon row and tuning the mobile type/padding; final 390 px capture shows all four choices.
2. P2 section changes could retain a deep scroll position beneath the sticky header. Fixed by returning content to the top when the active workspace section changes; verified across permissions, documents, and all admin panels.
3. P2 copy/link controls and raw slash-prefixed scopes felt like generic system chrome. Fixed with an embedded in-place copy state, a compact bordered documentation action, and customer-readable scope labels (`读取`、`查询`、`目录`、`管理`).

## Findings

- No actionable P0/P1/P2 visual or interaction differences remain.
- Accepted constraint: the implementation uses daily usage history instead of fabricating the mock's request-level activity table.
- P3 follow-up: apply the same Phosphor migration and reduced-surface density to deeper legacy admin cards in a later scoped iteration.

## Implementation checklist

- [x] Selected visual target resolved and compared.
- [x] Desktop and mobile browser captures reviewed.
- [x] Primary controls and workspace routes exercised.
- [x] Console error-level output checked.
- [x] Build, lint and focused API/console tests passed.

final result: passed
