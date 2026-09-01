import { researchSectionTarget } from "./researchHistory.js";

export function createResearchGuideLoader(importers) {
  const cache = new Map();
  return function load(id) {
    if (!Object.hasOwn(importers, id)) return Promise.reject(new Error("unknown_research_guide"));
    if (!cache.has(id)) {
      const pending = Promise.resolve().then(() => importers[id]()).then(module => module.default).catch(error => {
        cache.delete(id);
        throw error;
      });
      cache.set(id, pending);
    }
    return cache.get(id);
  };
}

export function observeResearchGuide(id, load, onState) {
  let active = true;
  onState({ status: "loading", body: null });
  Promise.resolve().then(() => load(id)).then(body => {
    if (active) onState({ status: "ready", body });
  }).catch(() => {
    if (active) onState({ status: "error", body: null });
  });
  return () => { active = false; };
}

export function restoreGuideFragment(id, location, document) {
  const route = location.pathname.replace(/^\/+|\/+$/g, "");
  if (route !== `research/${id}`) return false;
  const target = researchSectionTarget(route, location.hash);
  const element = target && document.getElementById(target);
  if (!element) return false;
  element.scrollIntoView({ block: "start", behavior: "instant" });
  element.focus({ preventScroll: true });
  return true;
}
