// Ephemeral, per-entry navigation positions. No account or persistent history.
export function researchSectionTarget(route, hash) {
  return /^research\/(?!paths\/)[^/]+$/.test(route) && /^#research-section-[1-9]\d*$/.test(hash) ? hash.slice(1) : null;
}

export function isInPageNavigation(previous, next) {
  const before = new URL(previous), after = new URL(next);
  return before.origin === after.origin && before.pathname === after.pathname && before.search === after.search && before.hash !== after.hash;
}

export function locationHashId(hash) {
  if (!hash || hash === "#") return "";
  try {
    return decodeURIComponent(hash.slice(1));
  } catch {
    return hash.slice(1);
  }
}

export function restoreLocationHashTarget({ windowObject = window, documentObject = document, Observer = MutationObserver } = {}) {
  const targetId = locationHashId(windowObject.location.hash);
  if (!targetId) return () => {};

  let observer;
  let timeoutId;
  const cleanup = () => {
    observer?.disconnect();
    if (timeoutId) windowObject.clearTimeout(timeoutId);
  };
  const revealTarget = () => {
    const target = documentObject.getElementById(targetId);
    if (!target) return false;
    target.scrollIntoView({ behavior: "instant" });
    cleanup();
    return true;
  };

  if (!revealTarget()) {
    observer = new Observer(revealTarget);
    observer.observe(documentObject.querySelector("main") ?? documentObject.body, { childList: true, subtree: true });
    timeoutId = windowObject.setTimeout(cleanup, 2000);
  }
  return cleanup;
}

export function observeHashLocation(windowObject, onChange) {
  const sync = () => onChange(windowObject.location.href);
  windowObject.addEventListener("hashchange", sync);
  return () => windowObject.removeEventListener("hashchange", sync);
}

export function createReadingPositions() {
  const entries = new Map();
  return {
    save(key, y) { if (key != null && Number.isFinite(y)) entries.set(key, Math.max(0, y)); },
    restore(key) { return entries.get(key) ?? 0; },
  };
}
