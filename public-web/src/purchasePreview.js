import { privateAccountSections } from "./accountNavigation.js";
import { BASE_PLANS, getPlanPrice } from "./pricing.js";

// Display-only selection, not an offer quote, order, or authorization record.
// No runtime flag can enable payment; that requires a reviewed server contract.
export function buildPreviewPath(planId, period) {
  getPlanPrice(planId, period);
  return `/pricing/preview?plan=${planId}&period=${period}`;
}

export function readPreviewSelection(search) {
  const params = new URLSearchParams(search);
  if ([...params.keys()].length !== 2 || params.getAll("plan").length !== 1 || params.getAll("period").length !== 1) return null;
  const plan = BASE_PLANS.find((candidate) => candidate.id === params.get("plan"));
  const period = params.get("period");
  if (!plan || !["monthly", "annual"].includes(period)) return null;
  return { plan, period, price: getPlanPrice(plan.id, period), mode: "preview_only", canPay: false, order: null };
}

export function safeLoginDestination(search) {
  const params = new URLSearchParams(search);
  if (params.getAll("next").length !== 1) return "/account";
  const next = params.get("next");
  if (next === "/account" || privateAccountSections.some(section => next === `/account/${section}`)) return next;
  if (!next?.startsWith("/pricing/preview?") || next.includes("#")) return "/account";
  const selection = readPreviewSelection(next.slice("/pricing/preview?".length));
  return selection ? buildPreviewPath(selection.plan.id, selection.period) : "/account";
}

export function getPreviewState(selection, identity) {
  return {
    status: selection ? "payment_paused" : "invalid_selection",
    identity: ["checking", "signed_out", "unavailable", "authenticated"].includes(identity) ? identity : "unavailable",
    canSignIn: Boolean(selection) && identity === "signed_out",
    canPay: false,
    order: null,
    accessChanged: false,
  };
}
