# Public evidence and Agent readiness

Scope: follow-on candidate to account PR #408. Keep its reviewed identity and
authorization code unchanged. No production flags, DNS, secrets, grants or schema
changes are authorized by this frontend correction. Payment and SMS stay off.

## Findings and corrections

The authored product manifest is not runtime evidence. Its illustrative daily-bar
percentage, invented receipt/coverage and synthetic quotes must not appear as live
collection health. An unbound page says **not verified on this page**, never that
collection has not started. Preserve the collection-history section and an honest
empty state; do not infer a 90-day window from a 30-dot illustration. Label synthetic
sample fields locally, not only in a footer. Product stage and collection evidence
remain separate. Historical source-landscape snapshots retain their dates and
must be clearly distinguished from the current registry/runtime.

Product slugs are navigation identifiers, not API dataset identifiers. Until an
authenticated catalog entry is selected, the inline query is a non-executable
template with explicit catalog-derived dataset/schema/fields placeholders. No
hard-coded schema major, product slug or guessed field list becomes a request.

Agent prompts compile from `docs/AGENT_INTEGRATIONS.md`, with one authored template
per language and thin named-agent wrappers. HTTP capability is not a deployed MCP
server. No API key enters prompt text, clipboard, URL, analytics or browser storage.
An unconfigured API origin is shown as pending, not a reachable public endpoint.
Copy is explicit, with confirmed success/failure, stale-copy reset and keyboard
focus handling. Copy never sends data or changes accounts.

## Acceptance

- Deterministic tests: manifest cannot contain claimed runtime history; sample and
  unverified labels are present; query templates never use product IDs/major 1.
- Every prompt variant keeps catalog-before-query, catalog-derived schema, bounded
  fields/limit/cursors, receipt/lineage/degradation checks, no provider fallback,
  no secrets and no automatic MCP provisioning. Generated source must match docs.
- Browser: desktop/mobile, both languages/themes, empty history, copy/error and
  keyboard dialog behavior. No fabricated observations in evidence positions.
- Bounded real internal readback uses existing read-only authentication and only
  catalog/query, no new keys, upstream collection or service changes. It is not
  public endpoint, customer identity, continuous health or redistribution proof.
- Record production email/API reachability, PM approval and staging gaps honestly;
  stop publication until their separate gates are satisfied.
