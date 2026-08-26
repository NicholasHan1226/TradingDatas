# TradingDatas public site design QA

## Evidence

- Source visual truth: `/var/folders/gg/h6vhh_j50tvg5x4ktqwgxy4r0000gn/T/codex-clipboard-508cacfa-7b19-4f1e-9843-ab3e91f23771.png`
- Final desktop implementation: `qa/implementation-desktop-final.jpg`
- Final mobile implementation: `qa/implementation-mobile-final.jpg`
- Final side-by-side comparison: `qa/design-comparison-final.jpg`
- Research desktop implementation: `qa/research-desktop-final.jpg`
- Research mobile implementation: `qa/research-mobile.jpg`
- Research visual-language comparison: `qa/research-visual-language-comparison.jpg`
- Account preferences, desktop light: `qa/account-preferences-desktop.jpg`
- Account preferences, desktop Chinese dark: `qa/account-preferences-zh-dark.jpg`
- Account preferences, mobile: `qa/account-preferences-mobile.jpg`
- Final routed homepage: `qa/implementation-desktop-routed.jpg`
- Final routed homepage comparison: `qa/design-comparison-routed.jpg`
- Independent Research page: `qa/research-page-desktop.jpg`
- Account workspace overview: `qa/account-workspace-overview.jpg`
- Account workspace preferences: `qa/account-workspace-preferences-final.jpg`
- Account workspace mobile: `qa/account-workspace-mobile.jpg`
- Data depth, desktop: `qa/data-viewport-desktop.jpg`
- Research depth, desktop: `qa/research-viewport-desktop.jpg`
- Pricing depth, desktop: `qa/pricing-viewport-desktop.jpg`
- Docs hub, desktop: `qa/docs-viewport-desktop.jpg`
- Deep-page desktop contact sheet: `qa/deep-pages-desktop-contact.jpg`
- Deep-page mobile contact sheet: `qa/deep-pages-mobile-contact.jpg`
- Deep-page visual-language comparison: `qa/deep-pages-visual-language-comparison.jpg`
- Local route: `http://127.0.0.1:4173/`
- State: English, light theme, signed-out public homepage, hero at scroll position 0.
- Desktop viewport: 1440 x 1024 CSS px, implementation 1440 x 1024 px at 1x density.
- Source: 1488 x 1058 px, normalized to 1440 x 1024 px before comparison.
- Mobile viewport: 390 x 844 CSS px, implementation 390 x 844 px at 1x density.
- Research uses the confirmed homepage as its visual-system source rather than a
  same-screen layout mock. The 2880 x 1024 comparison therefore evaluates
  typography, palette, spacing rhythm, line treatment, and editorial density,
  not pixel-for-pixel Research geometry.

## Findings

- No actionable P0, P1, or P2 mismatch remains in the final desktop comparison.
- Typography: the final hierarchy, weight, line height, wrapping, and subdued body-copy contrast track the selected source. `TradingDatas` is intentionally longer than the source wordmark because the product name was corrected after the mock was selected.
- Spacing and layout rhythm: navigation, hero copy, CTA, generative data material, and receipt section align to the same above-the-fold composition and density as the reference.
- Colors and tokens: warm paper background, near-black type, restrained gray metadata, cobalt blue, cyan, and receipt yellow are preserved across the implementation.
- Image quality and assets: the selected generative data material is used as a real raster asset, with a dedicated dark-theme variation. The logo mark is a real transparent image asset; interface icons use Phosphor Icons.
- Copy and content: the reference hero copy is retained. The corrected `TradingDatas` brand and the registered `tradingdatas.com` domain are reflected in page metadata and planned API copy.
- Responsive behavior: the mobile layout preserves hierarchy and artwork while collapsing navigation into a menu. Measured page width equals the 390 px viewport with no horizontal overflow.
- Research: the external-literature library extends the same warm editorial
  system with a TradingDatas-owned taxonomy, search, topic filters, paper
  metadata, learning summaries, related data materials, external source links,
  and a clear external-conclusion disclaimer. No actionable P0/P1/P2 issue was
  found in desktop or mobile review.
- Account preferences: the separate globe control was removed. Language and
  appearance are now distinct groups inside Account in desktop and mobile
  layouts, with clear selected states in both light and dark themes.
- Page architecture: Data, Research, Cookbook, Pricing, Docs, and Account now
  resolve to independent history-aware paths rather than same-page anchors.
  The routed homepage retains the approved hero focus. The final normalized
  homepage comparison has no actionable P0/P1/P2 mismatch.
- Account workspace: the former header dropdown was replaced by a dedicated
  page grouped as Account, Data access, Integrations, Billing, and Settings.
  Desktop and mobile views preserve hierarchy without horizontal page overflow.
- Deep product pages: Data now explains core taxonomy, the shared data template,
  receipts, alternative-data families, and a truthful order path; Research
  separates format from topic and adds a reading path; Pricing shows three
  complete A-share workflow proposals plus optional add-ons; Docs is now the
  searchable platform help hub rather than an API-only hero. The four pages
  preserve the selected warm editorial visual language and use thin structural
  rules, low-radius controls, mono metadata, and restrained blue/aqua accents.

## Open Questions

- Production DNS, HTTPS, public hosting, and the future `api.tradingdatas.com` endpoint remain outside this local visual build and are not claimed as active.

## Comparison History

1. Initial comparison: the hero copy sat slightly lower than the source, and prototype-only eyebrow/secondary-link content weakened the selected composition. These P2 differences were fixed by moving the hero copy upward and removing the extra content.
2. Final comparison: `qa/design-comparison-final.jpg` confirms the revised implementation has no remaining actionable P0/P1/P2 visual difference.
3. Research extension: the first rendered Research pass established the
   two-column editorial composition. It was then refined with the complete
   TradingDatas taxonomy and learning summaries. The final visual-language
   comparison is `qa/research-visual-language-comparison.jpg`.
4. Account annotation: the top-level globe control was removed and its language
   and appearance controls were moved into Account. Final desktop, Chinese dark,
   and mobile evidence is listed above.
5. Navigation-depth annotation: same-page anchors and the large Account dropdown
   were replaced by independent `/data`, `/research`, `/cookbook`, `/pricing`,
   `/docs`, and `/account` pages. The Account categories were regrouped and the
   page header was made sticky. A first automated preferences capture exposed
   the page header scrolling away; correcting the sticky inset removed that P2.
   Post-fix evidence is `qa/account-workspace-preferences-final.jpg`.
6. Product-content annotation: the first independent pages were still too
   shallow—Data did not explain its taxonomy/order path, Research lacked format
   and reading guidance, Pricing did not enumerate packages, and Docs looked
   API-only. Those P1 information-architecture gaps were replaced with the four
   deep pages recorded in `qa/deep-pages-desktop-contact.jpg`. The normalized
   side-by-side visual-language review in
   `qa/deep-pages-visual-language-comparison.jpg` found no remaining actionable
   P0/P1/P2 issue; mobile evidence is `qa/deep-pages-mobile-contact.jpg`.

## Focused Region Review

A separate crop was not needed after the normalized full-view comparisons: the
navigation, wordmark, headline, CTA, generative material, metadata, Research
filters, paper rows, and receipt heading are legible at 2880 x 1024. Account
preferences were reviewed in dedicated open-state screenshots, and mobile was
reviewed as its own full viewport.

## Interaction and Runtime Checks

- Primary CTA opens the Agent connection modal.
- Agent tabs cover Claude, Codex, OpenClaw, Hermes, and other agents; the setup prompt can be copied.
- Account preferences support English/Chinese and system/light/dark appearance choices.
- Account menu exposes overview, subscription, usage, API keys, Agent Connections, billing, security, and preferences.
- Mobile navigation opens and remains usable at 390 x 844.
- Research search returns matching title/author/journal/data/summary content;
  format and topic filters reduce the list, and an explicit empty state appears
  for no match. The Cases filter returned 2 entries after render settlement.
- Research external source actions point to title-specific Google Scholar
  searches and open in a new tab.
- Language and system/light/dark settings work inside Account; the global header
  exposes no duplicate language or appearance control.
- All five primary navigation items were click-tested from the homepage and
  resolved to the expected pathname and visible page heading. Account resolves
  to `/account` without opening a header dropdown.
- Direct HTTP reads for `/`, `/research`, and `/account` returned HTML 200 through
  the local prototype runtime.
- Docs search returned 2 receipt-related entries; Plans & account returned 3
  entries. Pricing's subscription action opened `/account` with Subscription &
  add-ons selected.
- Desktop page width matched the 1440 px viewport and mobile page width matched
  the 390 px viewport on Data, Research, Pricing, and Docs; no horizontal
  overflow was measured. Chinese rendering was also checked at 390 x 844.
- Browser console: no application errors or warnings in the final interaction pass.
- Build: `npm run build` passed.
- Hosting contract tests: `npm run test:sites` passed, 4/4.

## Implementation Checklist

- [x] Match the selected desktop hero composition.
- [x] Use `TradingDatas` consistently for the current product.
- [x] Add bilingual and appearance controls.
- [x] Add account and Agent connection flows.
- [x] Add the external Research library with platform-owned classification.
- [x] Move language and appearance settings under Account.
- [x] Replace homepage anchors with independent primary pages.
- [x] Replace the Account dropdown with a grouped Account workspace.
- [x] Expand Data, Research, Pricing, and Docs into task-complete deep pages.
- [x] Separate alternative data from base packages and label commerce as pending.
- [x] Verify Research and Docs filters plus the package-to-account handoff.
- [x] Verify desktop and mobile rendering in the in-app browser.
- [x] Compare the normalized source and implementation side by side.

## Follow-up Polish

- P3: replace the raster logo mark with the final production vector when a canonical brand master is available.
- P3: repeat this QA at the production domain after DNS, HTTPS, and hosting are configured.

## Navigation object-system review — 2026-08-26

The shared-product conversation was reconciled with the repository's current
authority boundaries. The public navigation now exposes Data, Features,
Recipes, Research, Pricing, and Docs, with Account kept as the compact right-side
entry. The home primary action is `Explore A-share data`; Agent connection is a
secondary delivery action.

Fresh rendered evidence:

- `qa/navigation-v2-features.jpg`: Features index, desktop, Chinese/light;
- `qa/navigation-v2-dataset-detail.jpg`: Dataset detail grammar and maturity;
- `qa/navigation-v2-research-detail.jpg`: internal external-research record;
- `qa/navigation-v2-docs-detail.jpg`: Docs article route and authority block;
- `qa/navigation-v2-recipes-mobile.jpg`: Recipes index at 390 x 844.

No P0/P1/P2 visual defect was found. Desktop pages retain the approved warm
editorial canvas, strong typographic hierarchy, thin rule system, low-radius
controls, mono evidence labels, and restrained blue/aqua accents. The mobile
Recipes page has no visible horizontal overflow, preserves section navigation,
and keeps object status and actions legible.

The new object grammar is consistent:

- index: orientation -> taxonomy -> object list -> evidence -> usage -> access;
- detail: identity -> maturity/availability -> trust/limitations ->
  schema/version -> related objects -> sample -> next action.

Feature, PIT, commerce, and alternative-data purchase states remain explicitly
labelled product-definition/planned. The prototype manifest is not represented
as runtime authority. Research list actions now open TradingDatas' own curated
record before the external source. Docs cards now open real article routes.

The final build and Sites worker contract passed after these changes. A public
production-domain and deployment QA remains intentionally separate.

final result: passed
