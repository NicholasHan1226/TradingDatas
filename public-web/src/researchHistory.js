// Ephemeral, per-entry navigation positions. No account or persistent history.
export function researchSectionTarget(route, hash) {
  return /^research\/(?!paths\/)[^/]+$/.test(route) && /^#research-section-[1-9]\d*$/.test(hash) ? hash.slice(1) : null;
}

export function isInPageNavigation(previous, next) {
  const before = new URL(previous), after = new URL(next);
  return before.origin === after.origin && before.pathname === after.pathname && before.search === after.search && before.hash !== after.hash;
}

export function createReadingPositions() {
  const entries = new Map();
  return {
    save(key, y) { if (key != null && Number.isFinite(y)) entries.set(key, Math.max(0, y)); },
    restore(key) { return entries.get(key) ?? 0; },
  };
}
