# Global news publication provenance: compatible minor candidate

## Scope and observed problem

Base: `a735163047e4e5fa8e5b40e08074bbd42d0c9773`. This report covers a local candidate, not production deployment, provider observation, complete news coverage, or stable capability. Parent-owned operations evidence records the 2026-08-30 20:25 global samples: stored publication values were canonical midnight and the original strings were unavailable. Their original precision cannot be reconstructed from midnight. No historical values or receipts are migrated or repaired offline.

The existing global adapter parses provider date strings, normalizes them into the America/New_York legacy `published_at` anchor, and replaces the original field. Unknown list completeness remains a separate unresolved limitation. A successful transport or receipt does not establish that all source articles were returned or that its collection timestamp is a publication watermark.

## Frozen compatible contract

Only `global.news.flash` changes from schema `1.0.0` to `1.1.0`. Three optional, nullable text fields are selectable but not filterable or sortable:

| Field | Meaning |
| --- | --- |
| `provider_published_at` | Exact source item publication string, including whitespace; never reconstructed from the normalized value. |
| `raw_item_json` | Canonical JSON serialization of the complete original structured item, captured before any normalization or replacement. JSON decoding reproduces its original key/value tree, including URL, unknown keys, nested values, and collisions with output-field names. This is not the original HTTP byte stream or source-page HTML. |
| `publication_precision` | `date`, `datetime`, `time`, or `unknown`, classified from the source string using accepted syntactic forms. Midnight in an explicit datetime remains datetime. Missing or unparseable times still fail collection; unknown classification is not permission to invent a timestamp. |

`publication_provenance_mode: raw_item_v1` is an explicit **TradingDatas-local normalization option**, not a Firecrawl upstream parameter or an assertion supported by the official Firecrawl document hash. It is consumed only by `scrape_page_global` and is never sent in an upstream request. Unsupported modes, explicit null, and enabling it for domestic scrape/search fail closed before a provider request. With no mode, legacy output is unchanged.

Legacy `published_at`, `published_local`, `event_date`, `content_uid`, primary key, default projection, request extraction schema, provider endpoint, adapter version, cadence, fanout and budgets are unchanged. A date-only legacy midnight is a normalized date anchor, **not an observed publication instant**. A bare time retains the existing day anchor and `time` precision; its date is not provider-supplied publication evidence. Consumers needing provenance must request the new fields and inspect precision. Existing CN and search behavior is not changed.

Before raw JSON serialization or reserved-field replacement, the entire original items tree is validated by the existing `ProviderCallOutcome` credential/known-secret scanner with the caller's exact `SensitiveScanBudget`. The normalized outcome is then checked by its existing guard. This preserves structured credential-key detection and depth/node accounting even for overwritten fields; no arbitrary JSON-text decoding or stricter business-prose keyword filter is introduced. Raw JSON retains those original values only if the original structured tree passes. It is never truncated to satisfy a budget. Unknown provider keys continue to produce schema drift; oversized retained payloads fail the existing admission/resource budgets before a storage write. No increased response, row, batch, nesting or sensitive-scan budget is introduced.

## Storage, metadata and rollback boundaries

The shared writer, schema, row keys and transaction receipts are unchanged. Normal future collection uses existing generic ingest semantics. Specifically, global news is `point_in_time=append_only`: its storage row key is the payload hash. New provenance on the same business primary key therefore preserves the old payload version and appends a distinct new payload version. This is not a snapshot upsert or revision-2 replacement. Other generic storage modes retain their existing semantics. No special migration, deduplication, old-fact rewrite, receipt rewrite or deletion is added.

Old payload versions lack the three new keys and remain explicitly degraded under the new schema (`missing_field`), even though each field is nullable. New fields do not provide an exemption for old data. Unrecognized keys remain visible schema drift.

`response_completeness` stays null. Even a current-config success receipt continues to produce query `partial`, `quality.valid=false`, `freshness_watermark_unverified`, `response_completeness_unverified`, and `data_through=null`. There is no claim of list completeness, publication freshness, historical PIT, global health, or repaired historical source precision.

A local SQLite regression uses the real generic collector orchestration, append-only writer, receipts, verified query snapshot, and unchanged a735163 query/storage implementation with a reconstructed exact old global contract (old config hash below):

- Old 1.0 collection followed by 1.1 collection: three old plus three new payload versions remain, with unchanged original rows and all revision values 1. Both new and old registry queries return all six rows and explicit protective partial/degraded metadata. The old reader retains unknown added fields; default-projection identity remains unchanged in the registry, not a promise that the generic reader drops unknown payload fields.
- Only new 1.1 receipts, with no old-config success receipt: old-registry rollback returns no data and `active_config_receipt_mismatch`, rather than a crash/500. Thus code rollback is **not an unconditional availability guarantee**. Release preflight must retain and inspect old receipt evidence; never delete new rows or rewrite receipts to make rollback appear healthy.

These are synthetic local tests, not authentication/network/production evidence. An eventual rollback also rolls back capture of original provenance for later collections. Existing historical loss is not reversible.

## Generation and verification

Source of truth: `config/firecrawl_upstream_contracts.v1.yaml`. Normal offline compiler:

```sh
uv run --python 3.12 --with-requirements requirements.txt python -B tools/compile_provider_native_registry.py
```

The generated registry's only changed dataset is global news. The activation-wave pin is updated to the generated byte hash; no activation or wave membership changes.

- Registry SHA256: `96ee0c21a4187d2cf6ed121513ef517e488f7bf64177001a60bac908aeffbf2f`.
- Global old ingest config: `5bff586c35ac12db3533e25e9244d7f40f55448b638359651fc4436f11031db7`.
- Global new ingest config: `364b06f7a069ee107767972d41fbd07a92c3b14ae2d479633e307831a62ec74f`.
- CN ingest config unchanged: `4043b9f24b98a6fe0bef159828c9a7c91395bde6dcff96b7bfc7cb0bacfb57df`.

Tests: `tests/test_firecrawl_global_provenance.py`, existing `tests/test_firecrawl_collector.py`, and `tests/test_compile_provider_native_registry.py`. Dedicated negatives cover missing/bad time, date versus explicit midnight, unsupported/local-only mode, reserved-key collision, sensitive value hidden only in an otherwise replaced URL, unknown-field drift, oversized complete raw payload, unchanged protective metadata and both rollback evidence cases. The initial candidate had **163 passed in 90.39s** across these three test files, but independent review subsequently reproduced a P1: a foreign credential nested in an overwritten reserved field, or an over-budget reserved subtree, could become an unchecked JSON string. The initial passing suite was insufficient. The correction adds original-tree validation before serialization; its 9 new rejection cases were first confirmed failing on the old candidate. Final corrective verification: **79 passed in 7.33s** across both Firecrawl test files, including 11 added cases (8 reserved-field foreign `api_key`/`token` cases, depth, node count, and safe business prose). The unchanged compiler had already passed in the initial suite and was not rerun for this adapter-only correction; `ruff check --select F` and `git diff --check` passed. Re-running the normal compiler reproduced the exact registry hash above. Query, storage, registry loader and ingest-config-hash implementation files are byte-identical to the base. No live provider or server was contacted.

Next: fresh independent review, parent-owned exact candidate integration and CI, then any authorized bounded collection and authenticated readback. Production readback should use an existing `content_uid` equality filter derived from a fresh receipt-associated fact, request the new fields explicitly, compare parsed raw content and precision, and continue reporting unknown completeness. It must not add filters, recast receipt collection time as publication time, or label the candidate healthy simply to pass acceptance.
