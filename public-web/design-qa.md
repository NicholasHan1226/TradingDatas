# TradingDatas data catalog design QA

## Result

passed

## Compared surfaces

- Selected reference: `/Users/nicholashan/.codex/generated_images/01a03dc3-3fc5-76c1-be8a-d2b9226d1c29/exec-5ea12567-b372-4526-883f-55e56c262623.png`
- Final desktop catalog: `qa/data-products-desktop.jpg`
- Alternative-data family variants: `qa/data-products-alternative-desktop.jpg`
- Final desktop product detail: `qa/data-product-detail-desktop.jpg`
- Final mobile catalog: `qa/data-products-mobile.jpg`
- Final mobile product detail: `qa/data-product-detail-mobile.jpg`
- Side-by-side comparison: `qa/data-products-visual-comparison.jpg`

## Viewports and state

- Desktop: 1440 × 1024, Chinese, light theme, `/data`
- Mobile: 390 × 844, Chinese, light theme
- Catalog states tested: All, Observed, Planned, Pending release
- Category states tested: all nine categories, including Alternative data and Crypto assets
- Product detail tested: `/datasets/global-pizza-index`
- Product-specific data contract and query example render inline without routing to Docs; the query example can be copied but does not execute automatically.

## Functional checks

- Category filters return the expected product families.
- State filters return 1 observed example, 34 planned products, and 6 pending-release candidates.
- Search for `Pizza` returns exactly one product and opens its directly addressable detail page.
- The unfiltered landing state shows nine lightweight category shelves rather than forty-one fully expanded product rows.
- Category, status, and search choices reveal a focused product list with an explicit return-to-directory action.
- Focused rows now pair product stage with a concise collection-evidence line. Products without observations state `No collection history` plus planned cadence; only observed products expose a stability percentage and history track.
- Product details keep stage beside product identity and remove it from the 90-day history visualization. That history area now contains only observed stability/gaps or a truthful no-history state.
- Product detail collection evidence also exposes source, last success, stored coverage, cadence, receipt, and a clearly labelled future disclosure set for success/empty/failure mix, delivery lag, row growth, schema drift, and revision volume. No future metric is presented as already observed.
- All nine categories now have distinct raster base grammars; five new generated companion assets cover indices/funds, macro/rates, news/text, global markets, and crypto assets.
- Search now matches dataset ID, cadence, source, and onboarding plan in addition to names, descriptions, and tags.
- Alternative data contains nine individually packaged products instead of presenting the category as a product. The ninth is the planned `Notable Investor 13F Holdings` product: quarterly delayed SEC disclosure data, not real-time holdings or a trading signal.
- Related products prioritize the current category.
- Every category has a stable color family and base geometric grammar.
- Products within a category use up to eight restrained arrangement variants while preserving family recognition.
- Desktop and mobile layouts retain hierarchy, readable metadata, working links, and horizontally scrollable sample data.
- Browser console warnings/errors: none.

## Visual comparison judgment

- The implemented layout preserves the selected reference's light editorial canvas, thin rules, search-first hierarchy, compact product rows, and abstract mini-cover marks.
- The implementation intentionally adds category/status filtering and truthful roadmap states; it does not copy the reference's unverified operational percentages for planned products.
- No P0, P1, or P2 visual defects remain. No blocking overflow, crop, alignment, or interaction issue was observed.

---

# TradingDatas question-led Research atlas design QA

## Result

passed

## Compared surfaces

- Selected option 1 reference: `qa/research-question-atlas/source-option-1.png`
- Final desktop viewport: `qa/research-question-atlas/implementation-desktop-viewport.png`
- Final mobile viewport: `qa/research-question-atlas/implementation-mobile.png`
- Side-by-side source and implementation: `qa/research-question-atlas/comparison-source-implementation.png`
- Light/dark theme cover comparison: `qa/research-question-atlas/research-theme-comparison-v2.png`
- Mobile titled-cover check: `qa/research-question-atlas/research-mobile-covers-v2.png`
- Annotated light-theme reference state: `qa/research-question-atlas/research-light-theme-covers.png`
- Final light companion covers, desktop: `qa/research-question-atlas/research-light-theme-companion-covers-desktop-v3.png`
- Final dark companion covers, desktop: `qa/research-question-atlas/research-dark-theme-companion-covers-v3.png`
- Final light companion covers, mobile: `qa/research-question-atlas/research-mobile-light-companion-covers-v3.png`
- Final light featured-paper wrapper: `qa/research-question-atlas/research-featured-light-companion-cover-v2.png`
- Focused Data collection evidence: `qa/research-question-atlas/data-list-collection-evidence.png`
- Supporting Mobbin references: `qa/mobbin-research-references/`

## Viewports and state

- Desktop: 1440 × 1024, English, dark theme, `/research`
- Mobile: 390 × 844, English, dark theme, `/research`
- Progressive states tested: default atlas, curated prompt selection, full library open/close, topic filtering, and direct paper-detail navigation.
- Both themes and both languages remain available through the existing Account preferences; locale and theme still default from the system setting.

## Functional checks

- The default surface starts with a research question rather than a filter-heavy paper index.
- Three curated A-share paths connect a question to external papers, estimated orientation time, and raw data materials.
- All three research-path raster covers now integrate their persistent path title into the artwork; title spelling and narrow-card crops were visually checked.
- Light and dark themes now load separate, composition-matched raster covers for all three paths and the featured-paper wrapper. The theme switch changes contrast and surface weight without changing the research product identity.
- The featured paper is packaged with authorship, venue, year, reading status, orientation link, why-it-matters context, and related Data/Recipes.
- Opening a suggested question reveals the full library and activates the matching topic filter.
- Full-library open/close works on desktop and mobile; all 12 research records remain directly addressable.
- The first curated path navigates to `/research/the-cross-section-of-expected-stock-returns` and renders the correct paper detail.
- Desktop horizontal overflow: none at 1440 px. Mobile horizontal overflow: none at 390 px.
- Browser console warnings/errors: none.

## Visual comparison judgment

- The implementation preserves the selected reference's dark editorial field, large question-led orientation, search-first entry point, three visual research paths, compact featured-paper product row, restrained aqua/blue accents, and external-literature boundary.
- TradingDatas-specific content replaces the reference's generic social-science examples without changing its visual hierarchy.
- Light theme uses warm ivory/mist-blue companion artwork on the cooler editorial card surface; dark theme keeps the original deep navy/cyan artwork. No brightness filter is used as a substitute for theme-specific art. Cover titles, artwork, borders, metadata, and search controls remain legible in both.
- The full taxonomy is progressively disclosed below the primary experience, reducing initial reading and visual cost.
- No P0, P1, or P2 visual defects remain. No blocking overflow, crop, spacing, hierarchy, or interaction issue was observed.

final result: passed


---

# Superseded TradingDatas package decision-flow QA

## Result

superseded by the base-plan-only contract below

## Compared surfaces

- Previous desktop package-carousel baseline: `qa/pricing-workload-ladder-2026-08-28/pricing-simple-desktop.png`
- Current desktop decision flow: `qa/pricing-decision-flow-2026-08-28/desktop.jpg`
- Current mobile decision flow: `qa/pricing-decision-flow-2026-08-28/mobile.jpg`
- Current dark-theme decision flow: `qa/pricing-decision-flow-2026-08-28/dark.jpg`

## Mobbin reference synthesis

- Aside pricing informed the direct three-tier scan and restrained shared surface: `https://mobbin.com/sites/sections/de9e1a65-59c9-41f0-8c73-01df009482e1`.
- Replit add-ons informed the visual and semantic separation of optional products from the required base plan: `https://mobbin.com/sites/sections/5ca511ca-7171-452b-a0c1-af9491ef8cbe`.
- Vercel add-ons informed the treatment of an add-on as a small product with its own identity rather than a feature checkbox: `https://mobbin.com/sites/sections/6e7232f4-333b-4e77-ae55-8ee880890bd9`.
- Pipedrive purchase flow informed the explicit `base + add-on` setup summary: `https://mobbin.com/flows/5d1c7bc1-98be-4ec9-988c-67422502e76b`.

## Functional checks

- The page contains only two package families: complete base-data packages and independently purchased alternative-data add-ons.
- The page follows the user decision order: choose one required base package, explicitly add or skip one alternative-data package, then review the combined setup.
- All base tiers remain visible together for direct scope comparison; alternative tiers use a lighter add-on product list instead of repeating the base-package anatomy.
- A-share Research, Systematic Research, and Trading Data form the three proposed base tiers.
- Alternative Observe, Expand, and Panorama form three proposed add-on tiers containing three, six, and nine planned products.
- Price, concurrency grant, real-time access, payment, and entitlement remain explicitly unconfirmed until the commerce backend exists.
- Alternative packages explicitly require a base package and never imply overlap, replacement, silent inclusion, automatic charging, or default selection.
- Base selection, add-on selection, and the `暂不加购 / No add-on` action all update the combined summary correctly.
- Desktop and 390 px mobile layouts have no horizontal page overflow. Light and dark themes retain readable contrast and hierarchy.
- Chinese and English content both expose the same required-base, optional-add-on, and combined-summary logic.
- Browser console warnings/errors: none.
- `npm run test:search`, `npm run build`, `npm run test:sites`, and `git diff --check` pass.

## Design QA scorecard

| Dimension | Score |
| --- | ---: |
| Visual hierarchy | 19/20 |
| Typography quality | 14/15 |
| Color semantics | 14/15 |
| Spacing rhythm | 14/15 |
| Interaction feedback | 10/10 |
| Accessibility baseline | 9/10 |
| Originality / brand fit | 10/10 |
| Responsive integrity | 5/5 |
| **Total** | **95/100** |

The page read as one compact purchase narrative rather than two unrelated carousels, but Nicholas rejected the base-plus-add-on structure. It is retained only as historical evidence of the superseded direction.

final result: superseded

---

# TradingDatas three base-plan showcase QA

## Result

passed

## Compared surfaces

- Desktop, light: `qa/pricing-base-plans-2026-08-28/desktop.jpg`
- Mobile, light: `qa/pricing-base-plans-2026-08-28/mobile.jpg`
- Desktop, dark: `qa/pricing-base-plans-2026-08-28/dark.jpg`

## Product contract

- Pricing now fixes exactly three non-alternative-data plans: Basic / 基础版, Professional / 专业版, and Flagship / 旗舰版.
- Basic is the complete domestic daily/company/event/reference foundation; Professional adds historical minutes, auctions, and broader domestic trading history; Flagship adds proposed real-time candidates and the highest runtime profile.
- The plan contract differs only by a rolling per-minute request limit: Basic 200, Professional 600, and Flagship 1000. Commercial plans have no daily quota or concurrency limit. Production behavior still requires exact-main release and authenticated Account readback.
- Alternative data is absent from the main Pricing page. There is no add-on selector, default add-on, combined receipt, or alternative-data sales copy.
- Price stays `To be announced / 待正式发布`; no payment, checkout, or entitlement is fabricated.

## Interaction and visual checks

- One plan is presented as a focused product at a time. Direct tier tabs and previous/next arrows switch among all three plans and wrap correctly.
- The focused product keeps plan identity, included data, coverage, history, target runtime, price state, and request action in one bounded surface.
- Shared Catalog/Query, receipt, Agent-access, and bilingual foundations appear once below the plan rather than repeating in every tier.
- Desktop 1280 x 900, mobile 390 x 844, light, dark, Chinese, and English were checked in the in-app browser.
- Mobile contains no three-card squeeze; the plan becomes a readable single-column product while tier switching remains available above it.
- `npm run test:search`, `npm run test:sites`, `npm run build`, and `git diff --check` pass.

## Design QA scorecard

| Dimension | Score |
| --- | ---: |
| Visual hierarchy | 19/20 |
| Typography quality | 14/15 |
| Color semantics | 14/15 |
| Spacing rhythm | 14/15 |
| Interaction feedback | 10/10 |
| Accessibility baseline | 9/10 |
| Originality / brand fit | 10/10 |
| Responsive integrity | 5/5 |
| **Total** | **95/100** |

The page now sells one thing: access to progressively broader base financial data. The single-product showcase preserves the requested horizontal switching behavior without making the user compare three heavy cards or configure an alternative-data bundle.

final result: passed

---

# TradingDatas floating navigation and Account convergence QA

## Result

passed

## Compared surfaces

- Desktop grouped search with keyboard active state: `qa/navigation-search-hierarchy-2026-08-28/04-desktop-grouped-keyboard.png`
- Mobile grouped search inside the expanded floating navigation: `qa/navigation-search-hierarchy-2026-08-28/06-mobile-grouped-search.png`
- Mobile pinyin recall with intent-aware ranking: `qa/navigation-search-hierarchy-2026-08-28/07-mobile-pinyin-ranking.png`
- Mobile no-result recovery suggestions: `qa/navigation-search-hierarchy-2026-08-28/08-mobile-empty-suggestions.png`
- Mobile bounded typo recovery: `qa/navigation-search-hierarchy-2026-08-28/09-mobile-fuzzy-recovery.png`
- Desktop no-result state after keyboard focus: `qa/navigation-search-hierarchy-2026-08-28/10-desktop-empty-shortcut.png`
- 1024 px tablet no-result state: `qa/navigation-search-hierarchy-2026-08-28/11-tablet-empty-suggestions.png`
- Mobile approximate-match explanation: `qa/navigation-search-hierarchy-2026-08-28/12-mobile-match-reasons.png`
- Hovvi-informed single-layer desktop navigation at 1280 px: `qa/navigation-search-hierarchy-2026-08-28/13-hovvi-single-layer-desktop.png`
- Mobile expanded navigation at 390 px after the desktop treatment changed: `qa/navigation-search-hierarchy-2026-08-28/14-hovvi-single-layer-mobile.png`
- Dark-theme single-layer navigation at 1280 px: `qa/navigation-search-hierarchy-2026-08-28/15-hovvi-single-layer-dark.png`
- Balanced desktop search width on the homepage at 1280 px: `qa/navigation-search-hierarchy-2026-08-28/16-balanced-search-width-desktop.png`
- English desktop navigation balance on Data at 1280 px: `qa/navigation-search-hierarchy-2026-08-28/17-english-header-balance-desktop.png`
- Chinese homepage navigation balance at 1280 px: `qa/navigation-search-hierarchy-2026-08-28/18-chinese-header-balance-home.png`
- Unboxed section navigation and tightened Pricing intro at 1280 px: `qa/navigation-search-hierarchy-2026-08-28/19-unboxed-section-navigation-pricing.png`
- Account popover aligned below the homepage header at 1280 px: `qa/navigation-search-hierarchy-2026-08-28/20-aligned-account-popover-home.png`

## Functional checks

- Global navigation exposes only Data, Research, and Pricing as persistent primary destinations.
- The floating header retains one global search spanning data products, external research, preparation methods, and documentation.
- Data, Research, the expanded research library, and Documentation no longer duplicate keyword search inputs; their remaining controls are category, topic, format, or status filters.
- Search results are grouped by Data, Research, Methods, and Docs. Arrow Up/Down changes the active result, Home/End jumps to the first/last visible result, Enter opens it, and Escape closes the result surface. Home/End and wraparound index behavior are covered by a pure-function test; fresh running-browser readback for these additions remains pending because the local URL was blocked by the browser security policy during this QA pass.
- The complete result count uses a polite live region. Groups show four results first and expand in place rather than reopening page-local search. Source/build verification passed; fresh visual evidence for the expanded state remains pending for the same browser-policy reason.
- Up to five recent query strings are stored only in the current browser; each can be removed independently or cleared together. Source/build verification passed; fresh visual evidence for per-item removal remains pending for the same browser-policy reason.
- Keyboard wraparound, Enter navigation, recent-query clearing, and rebuilding recent history after a new result selection were checked in the running browser.
- Global discovery now recalls both authored languages, stable IDs, category/market/cadence metadata, common aliases, and bounded pinyin terms without adding another page-level search control.
- `gupiao` and `rixian` lead with A 股日线行情; `caiwu` leads with 时点一致财务数据; `lunwen` promotes Research; `wendang` promotes Docs; and exact `cn-equity-daily` resolves to one product.
- Search behavior is covered by eleven pure-function tests: punctuation normalization, cross-language/pinyin recall, intent-group priority, catalog-order ties, bounded one-edit typo recovery, short-token/multiple-edit rejection, match-reason classification, Command/Ctrl K recognition, Home/End and arrow navigation, exact-ID priority, token completeness, and per-group limits with complete result counts.
- Running-page checks confirmed `gupio`, `lunwe`, `wendnag`, and `fundamntals` recover the intended product or group, while `guxxxx` remains empty and exposes exactly three authored query suggestions. Clicking a suggestion restores normal grouped results.
- macOS `Command + K` opens and focuses global search from a closed mobile navigation; the desktop field exposes the compact `⌘K` hint, while mobile hides it. Windows `Ctrl + K` event recognition is unit-tested but was not claimed as a native Windows browser readback from this macOS host.
- Desktop 1280 px, tablet 1024 px, and mobile 390 px empty/recovery states were visually checked. `ID`, alias, and approximate notes appear only on non-obvious matches; direct title matches remain unlabelled.
- Products, papers, methods, and documentation can still be bookmarked from their task-specific surfaces and appear in Account saved materials.
- Bookmarks explicitly state that they are browser-local and that authenticated account sync is not connected.
- The compact Account menu groups Your library, Account, and Connect & learn; Documentation, Agent connections, and Appearance route into the dedicated Account workspace.
- Documentation renders as a categorized browser inside Account while direct `/docs/:slug` routes remain addressable.
- Research includes a progressive preparation-method section and keeps direct `/recipes/:id` compatibility links without restoring Cookbook/Recipes to global navigation.
- Desktop navigation is a compact floating rounded surface with Data/Research/Pricing placed directly on the shared surface, a fine underline for current location, a wider global-search lane, and Bookmarks/Account grouped at the right. It intentionally avoids a nested segmented pill.
- Mobile navigation preserves the same floating surface and moves global search above Data/Research/Pricing inside the expanded menu.
- Fresh browser readback confirmed Data, Research, and Pricing each receive the correct `aria-current="page"` state after navigation. At 1280 px the desktop search lane measures 744 px, the primary-navigation wrapper has no background or border, and the active underline is rendered. At 390 px the desktop links are hidden, the mobile menu exposes all three destinations plus the single search field, and document width equals viewport width. The dark-theme active underline resolves to the dark-system blue token and remains visible against the floating surface.
- After search-width convergence, fresh homepage readback measured the bounded field at 486 px inside a 1224 px header at 1280 px, and 389 px inside a 968 px header at 1024 px. At 390 px the desktop field remains hidden and search continues through the expanded mobile navigation. All three widths matched the viewport exactly with no horizontal overflow.
- Final header-system readback replaced equal gap distribution with a compact left group and a flexible right spacer. In English at 1280 px, brand-to-navigation measured 36 px and navigation-to-search 44 px; at 1024 px they converged to 29 px and 36 px without clipping `Data / Research / Pricing` or the full English search placeholder. Homepage and inner-page desktop headers both begin 14 px from the viewport edge. Mobile retains its denser 12 px edge, hides desktop search, exposes the menu trigger, and keeps document width equal to the 390 px viewport. Locale was restored to `zh-CN` after QA.
- Section-navigation convergence removed its border, surface fill, and shadow, leaving a 36 px-high text index with a one-pixel active underline. Pricing's primary title moved from 219 px to 145 px below the global header while retaining a distinct secondary-navigation tier. The Account popover moved from a 2 px header overlap to a measured 9 px gap, with its right edge aligned 13 px inside the header edge beside the Account button. At 390 px, the Pricing section index fits without overflow and the fixed Account popover stays within a 25 px / 25 px viewport inset. Locale and the final preview were restored to `zh-CN` at 1280 px.

## Design QA scorecard

| Dimension | Score |
| --- | ---: |
| Visual hierarchy | 19/20 |
| Typography quality | 14/15 |
| Color semantics | 14/15 |
| Spacing rhythm | 14/15 |
| Interaction feedback | 10/10 |
| Accessibility baseline | 9/10 |
| Originality / brand fit | 9/10 |
| Responsive integrity | 5/5 |
| **Total** | **94/100** |

The navigation now reads as one calm object floating above the warm editorial canvas. The Hovvi-informed single-layer primary navigation removes the previous capsule-inside-capsule hierarchy while retaining the TradingDatas blue current-location cue. Pricing begins near the task header, Account headings keep readable line breaks, section navigation inherits the same pill grammar, and Data rows add only localized hover feedback rather than card-heavy chrome.

final result: passed

---

# Research dual-view implementation QA

Date: 2026-08-30. Scope: PR #385, Featured/Topics discovery and its existing
reader navigation. This is local candidate verification, not a production audit.

## Findings and iteration

- Fixed P2 — the first desktop render added excessive space below the existing
  floating header. Reduced hub top padding and bounded the architectural hero
  height; the final spread restores the editorial hierarchy and visible paths.
- Fixed P2 — the Chinese hero title was undersized and broke at an unintended
  point. Increased the desktop display scale and authored the two editorial
  lines; the mobile rule preserves readable wrapping rather than clipping.
- Fixed P2 — the selected subject could be offscreen in the mobile horizontal
  index after returning or switching language. Reveal the selected link on
  subject/language/viewport changes without scrolling the whole document.
- Fixed P2 — the inherited primary-button treatment was not the selected solid
  blue/white action. Applied the local button token and retained visible focus.
- Accepted P3 — the new original architectural image is more neutral than the
  blue source mock. Its curved colonnade, stairs, crop, sharpness and quiet role
  match the composition; it is decorative, not evidence or a real venue claim.
- Accepted product constraints — retain the established global floating header,
  original bibliographic order and maintained source metadata. The mock's sample
  rows are illustrative: the implementation does not rewrite source titles or
  reorder authoritative records to mimic them. All Chinese rows show original
  titles, so density varies with actual title/author length.

No unresolved P0/P1/P2 was found in the implemented dual-view scope.

## Source and combined comparison evidence

Selected source: `exec-2aec2b00-09b7-4fc7-a312-9735bb302624.png`, a 1054 × 1492
combined mock. Split its two 1054 × 746 panels and normalize each to 1440 × 1024;
this introduces approximately 0.5% aspect normalization. Browser captures are
1440 × 1024 CSS/pixel viewports at DPR 1, Chinese/light, signed out, Featured and
Topics / Company & financials. Source and candidate were placed together, then
opened and inspected, not judged from filenames or separate screenshots.

Local evidence folder: `/tmp/tradingdatas-dual-view-5ccY8R` (temporary QA artifacts,
not published site assets or durable release evidence).

- Initial comparison: `featured-comparison-v1.png`.
- Final full-frame comparisons: `featured-comparison-final.png`,
  `topics-comparison-final.png` (source left, candidate right).
- Focused typography comparison: `featured-type-comparison.png`.
- Responsive captures: `featured-zh-light-390-final.png`,
  `topics-zh-light-390-final.png`, `topics-zh-light-768.png`,
  `featured-en-dark.png`, `featured-en-dark-390.png`,
  `topics-en-dark-390-final.png`.

## Required fidelity surfaces

- Fonts/typography: Songti/Georgia editorial display, existing sans body, italic
  original titles; checked Chinese two-line hero, English long title, authors
  and wrapped publication metadata. Local font fallback can differ by OS.
- Spacing/layout: unboxed local views, split editorial spread, two path links,
  subject index and ruled bibliography; no status-card grid. Desktop, 768px
  tablet and 390px mobile have no document horizontal overflow. Only the mobile
  subject index intentionally scrolls horizontally.
- Colors/tokens: warm light and existing dark surfaces, quiet separators,
  blue active/action states, sufficient solid-button contrast, visible focus.
  This is a visual/basic contrast check, not a full WCAG certification.
- Image quality: original 1024 × 1024 WebP, 118708 bytes, responsive crop; no
  fabricated data, logos, charts, CSS illustration or distorted stretching.
  Empty alt correctly marks decorative art; existing Phosphor icons retained.
- Copy/content: two explicit reading views; 200 external materials, eight
  derived subjects, no translated duplicates; reader retains authors, original
  source and concise limitations. The reported Tokenomics status grid is absent.

## Interaction and validation evidence

- Both views switch and preserve discovery filters/page; selecting another
  subject resets incompatible publication type and page.
- Company & financials contains 28 records; book-only produces an actionable
  zero-result state. Clearing the type restores all 28.
- Page 2 → Law and Finance → reader return preserves page/scroll. Refresh
  preserves the query/page. Native Back/Forward was exercised across that visit.
- Bookmark and copy-citation success verified in the reader; bookmark state
  reflected in the list. Test bookmark removed after verification.
- All three reading paths opened, the method disclosure expanded, and an
  existing preparation-method deep link resolved.
- Global search for Tokenomics returned the stable paper route and opened its
  content-led Chinese reader. No research-local duplicate search was added.
- Signed-out Account Chinese/English and light/dark switching exercised;
  system-language resolution remains covered by the existing automated tests.
- Native links/selects/buttons, selected states, disabled pagination and visible
  keyboard focus checked. Pagination explicitly focuses the result region.
- Browser error/warning log returned an empty list during the final path/search
  checks. The earlier stopped local preview server was restarted and rechecked.
- `npm run test:sites`: 47 passed, including all 200 readers in both languages,
  all subject/type combinations and URL normalization. Build and diff whitespace
  check passed; generated distribution is committed with its source.

## Boundaries and follow-up

- The retained `/recipes/:id` pages still show their pre-existing planned
  product-contract content; this pass verifies reachability, not completed
  tutorials. They need a separate content pass before being promoted as guides.
- Physical-device touch, screen-reader audit, text-only zoom, clipboard-denied
  runtime and divergent multi-visit scroll history are not verified here.
- Existing main-chunk warning remains (about 647 kB, 192 kB gzip). No dependency,
  backend, authentication, registry, provider or production changes were made.
- Project design-rule text was inspected; discovery in a new agent session was
  not tested. CI, merge, deployment and source/full-text review are separate.

Implementation checklist: dual views, shared identities, URL state, empty state,
responsive index, source access, bilingual rendering, scoped documentation and
local verification completed. Revert the scoped commit through a PR to roll back;
no data migration or server operation is involved.

final result: passed

---

# Reading depth, tutorials and sharing follow-up — 2026-08-30

Scope: same PR #385; keep the accepted Featured/Topics layout. This follow-up
supersedes the earlier planned-tutorial and main-bundle follow-up items, not the
historical evidence above. It does not claim production publication.

## Delivered and checked

- 200 distinct external works remain unchanged in identity. Twelve records now
  have four bilingual source-grounded sections plus specific limitations, and
  appear in the Featured shelf. All eight topics have three reading stages.
- Three bilingual preparation tutorials replace the generic planned-object body
  at the existing method URLs. Their examples are local, synthetic and read-only.
  Source functions and copyable examples share one implementation; production
  preserves readable snippets rather than exposing minified function bodies.
- Build-generated HTML contains title, description, canonical and Open Graph
  metadata for 200 records, three paths, three tutorials and both index pages
  (208 routes). Plain HTTP readback of a built Tokenomics route confirmed metadata
  without running JavaScript. No full-body SSR or crawler-indexing claim.
- `npm run build`: passed. `npm run test:sites`: 62 passed, including all 200
  records in both languages, tutorial rendering, example execution, invalid
  inputs, source IDs, reading sequences, projection, metadata escaping and
  fulfilled/denied/unavailable clipboard helper outcomes.
- `node scripts/verify-research-sources.mjs`: 186 requested metadata records,
  186 verified, zero unresolved; cached identity verification, not 186 new full
  source reads. Twelve new editorial reviews retain distinct evidence scopes.
- In-app browser against the production build at port 5186: twelve guides opened
  in Chinese at 390px and in English at 1280px; all retained four body sections,
  source links and original identities, with no page-level horizontal overflow.
  Eight Chinese topic sequences clicked individually; empty publication type
  and reset verified. Native dropdown and pointer pagination worked.
- All three examples ran in English/desktop and Chinese/320px with the expected
  outputs: 50/50/51 adjusted prices; pre-revision financial value 100; one aligned
  event plus one date-only review record. Main example buttons measured 44px high.
  Light/dark, explicit language persistence, default System selection, native
  headings/landmarks/status roles, bookmarks, citation-copy and share-copy success
  were inspected. Browser errors/warnings were empty during these checks.
- Current build: main app about 476.93 kB / 139.00 kB gzip; React cache chunk
  193.01 / 60.26; tutorial chunk 19.44 / 6.86, loaded on demand. A same-content
  comparison without catalogue projection was about 517.08 / 155.74 for the main
  app. This measures emitted bytes, not network latency or Core Web Vitals.

Screenshots: `/tmp/tradingdatas-depth-qa-j9zYVy/01-featured-mobile-zh.png`,
`02-topics-mobile-zh.png`, `03-guide-mobile-zh.png`,
`04-guide-desktop-en-dark.png`, `05-event-demo-en.png`, `06-tutorial-320-zh.png`.

## Remaining verification and release gate

- The browser control focused native buttons but did not produce an observable
  Enter activation, including on the pre-existing pagination control. Do not call
  keyboard behavior passed based on focus styling alone. Manual native keyboard
  acceptance remains open; no speculative custom key handler was added.
- Clipboard rejection is covered by deterministic helper tests and selectable
  fallback markup; an actual browser permission-denied run is not verified.
- Physical touch, real screen-reader speech, text-only zoom and divergent
  multi-visit scroll history remain unverified. Basic in-tab page/filter return
  worked; exact scroll comparisons are affected by automated click auto-scrolling.
- Current main advanced only in backend/tests/operations outside this edit's
  writing scope. Protected Worker/Sites files, dependencies/lockfile, workflows,
  registry, accounts, secrets and provider runtimes are unchanged.
- Await exact-head GitHub CI and the project's independent PM acceptance before
  merge. `pm-merge` was absent at preflight. Main CI, Cloudflare deploy and public
  route/asset readback remain separate gates; no production write was made here.

Result: content/build/function checks passed; accessibility/manual acceptance and
release gates remain explicitly open.

### Final hosting-path follow-up

Cloudflare local runtime (existing Wrangler 4.127.1, `dev --local`, loopback 8788)
verified all 208 slashless routes redirect to their directory forms and all 208
directory responses contain the expected static sharing metadata. Canonical and
copy-link URLs now use those final trailing-slash forms; legacy navigation and
bookmark IDs are unchanged. This follows the existing Assets
[HTML handling contract](https://developers.cloudflare.com/workers/static-assets/routing/advanced/html-handling/),
without changing Worker code or deployment configuration. Vite preview alone
does not reproduce these slashless redirects.

Rebuilt and reran tests after this correction: **63 passed**. Browser readback of
the revised Tokenomics page matched its canonical and OG URL, with no overflow.
Local Wrangler used a default Request.cf placeholder after a certificate failure
fetching that optional object; no TLS verification was disabled. This is local
route evidence only, not a Cloudflare edge deployment or production readback.

# Research continuity and offline tutorials — 2026-08-30

Follow-up scope: `docs/design/research-reading-continuity-v5.md`, PR #385.
This extends the preceding 12-guide baseline; 200 external source identities
remain unchanged. It is local acceptance evidence, not a publication claim.

## Delivered and verified

- 24 bilingual four-section guides now cover all 24 stations in eight topic
  journeys. Each of 16 adjacent relationships has an authored bilingual reason;
  first/middle/last articles show the appropriate next/both/previous links.
  These are editorial connections, not inferred citations or rankings.
- Twelve new guides record the primary source and exact reading scope internally.
  Abstract/introduction/draft access is not described as full-text review.
  Draft numerical results are not transplanted into final-publication claims.
- Three tutorials now generate 12 same-origin files: three synthetic JSON inputs,
  three standalone JavaScript examples, and six localized Python notebooks.
  Inputs, expected outputs and copyable browser code share maintained sources.
- `npm run build` passed: 208 static metadata entries plus all 12 download files.
  `npm run test:sites`: 69 passed, including all 200 records in both languages,
  journey relationships, history isolation, native hash-navigation detection,
  notebook execution, JS/Python sample parity and bounded failure cases.
- `python3 scripts/verify-tutorial-notebooks.py` executed every code cell of all
  six notebooks in order (four code cells each), with expected-output assertions.
  This uses standard-library execution, not a Jupyter kernel/UI integration run.
- Local HTTP readback compared all 12 served downloads byte-for-byte with their
  generated files: all returned 200 and matched. This does not certify the
  operating-system download dialog or the production edge's response headers.
- Browser inspection opened all 24 guides in Chinese at 390px and English/dark
  at 1280px. Each had six body sections (four editorial plus data and limits),
  a topic sequence and no horizontal page overflow. Article-to-article navigation
  focused the destination heading without moving the page below its opening.
- All three Chinese examples executed at 320px with the expected results;
  English event alignment also ran at 768px. Localized download targets and
  48px link heights were checked. Desktop dark and mobile light screenshots were
  visually inspected; English guide/body and Chinese download copy stayed legible.
- Browser testing found and fixed route-level scrolling overriding native
  tutorial anchors. Example/download jumps now position the section about 110px
  below the viewport top; back navigation to Downloads restored the same margin.
- Separate in-app list visits retained independent history: page 2 at 3425.5px
  and page 3 at 791px; returning through the intervening article restored the
  older page 2 position exactly. Explicit article return also restored the list.
  Forward traversal restored the later page 3 position at 791px as well.
  Entry IDs remain distinct after reload; positions themselves are memory-only.
- Main JS is approximately 283.94 kB / 80.74 kB gzip, research catalog
  231.33 / 75.12, React 193.01 / 60.26, lazy tutorial 22.58 / 7.78.
  Catalog chunk separation improves cache isolation, not total initial bytes;
  these are build sizes, not measured loading latency or Core Web Vitals.

Screenshots: `/tmp/tradingdatas-continuity-qa-1t0Wtr/01-guide-en-dark.png`,
`02-offline-en-desktop.png`, `03-downloads-320-zh.png`.

## Remaining acceptance / release boundary

- Native keyboard activation is still unverified: the browser-control surface
  focused controls without observable Enter activation. Real screen-reader
  speech, physical touch, text-only zoom, actual clipboard-denied runtime and
  Jupyter UI/kernel integration remain manual acceptance items.
- Source identity, unit/render tests and synthetic outputs do not demonstrate
  provider availability, historical completeness, paper replication or returns.
- No protected Worker/Sites files, lockfile/dependencies, workflows, registry,
  account authority, credentials or provider runtimes changed. Generated public
  build and maintained documents accompany the source.
- Exact-head CI, independent Datas PM review / `pm-merge`, exact-main CI,
  Cloudflare deployment and public deep-route/download readback are separate
  gates. No merge or production write is claimed by this record.
