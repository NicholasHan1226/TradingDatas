import { accountJson } from "./accountSession.js";

const tiers = ["basic", "standard", "flagship"];
const periods = ["monthly", "annual"];
const date = value => typeof value === "string" && Number.isFinite(Date.parse(value));
const text = value => typeof value === "string" && value.length > 0;
function orderValid(order) {
  return order && text(order.id) && text(order.offer_id) && text(order.offer_version)
    && tiers.includes(order.tier) && periods.includes(order.period)
    && order.currency === "CNY" && Number.isSafeInteger(order.amount_minor) && order.amount_minor > 0
    && ["pending", "verified_paid"].includes(order.payment_state)
    && ["not_provisioned", "pending", "active", "failed"].includes(order.provisioning_state)
    && date(order.created_at) && order.environment === "sandbox";
}
export function requireCommerce(payload) {
  if (!payload || !["unavailable", "sandbox"].includes(payload.mode) || typeof payload.checkout_available !== "boolean"
    || !Array.isArray(payload.orders) || !Array.isArray(payload.offers)) throw new Error("commerce_unavailable");
  if (payload.mode === "unavailable") {
    if (payload.checkout_available || payload.subscription !== null || payload.orders.length || payload.offers.length) throw new Error("commerce_unavailable");
    return payload;
  }
  const subscription = payload.subscription;
  if (subscription !== null && (!subscription || !text(subscription.id) || !tiers.includes(subscription.tier)
    || !periods.includes(subscription.period) || !["active", "expired"].includes(subscription.state)
    || !date(subscription.starts_at) || !date(subscription.expires_at) || subscription.environment !== "sandbox"
    || subscription.terms_version !== "sandbox-fixed-days-v1")) throw new Error("commerce_unavailable");
  if (!payload.orders.every(orderValid) || !payload.offers.every(offer => offer && text(offer.id) && text(offer.version)
    && tiers.includes(offer.tier) && periods.includes(offer.period) && offer.currency === "CNY"
    && Number.isSafeInteger(offer.amount_minor) && offer.amount_minor > 0
    && Number.isSafeInteger(offer.requests_per_minute) && offer.requests_per_minute > 0
    && offer.environment === "sandbox" && offer.terms_version === "sandbox-fixed-days-v1")) throw new Error("commerce_unavailable");
  return payload;
}
export async function readCommerce(identity, signal, fetchImpl = fetch) {
  return requireCommerce(await accountJson("commerce", { expectedIdentity: identity, signal }, fetchImpl));
}
export async function createSandboxOrder(identity, offer, idempotencyKey, fetchImpl = fetch) {
  const payload = await accountJson("orders", {
    method: "POST", expectedIdentity: identity,
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ offer_id: offer.id, offer_version: offer.version }),
  }, fetchImpl);
  if (payload.mode !== "sandbox" || !orderValid(payload.order) || payload.order.offer_id !== offer.id
    || payload.order.offer_version !== offer.version) throw new Error("commerce_unavailable");
  return payload.order;
}
