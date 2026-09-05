// Public display contract only. Checkout must use server-owned, versioned offers.
export const BASE_PLANS = Object.freeze([
  Object.freeze({ id: "basic", monthlyMinor: 9900, requestsPerMinute: 200, tone: "research", name: { zh: "基础版", en: "Basic" }, short: { zh: "基础", en: "Basic" } }),
  Object.freeze({ id: "standard", monthlyMinor: 29900, requestsPerMinute: 600, tone: "systematic", name: { zh: "专业版", en: "Professional" }, short: { zh: "专业", en: "Pro" } }),
  Object.freeze({ id: "flagship", monthlyMinor: 49900, requestsPerMinute: 1000, tone: "trading", name: { zh: "旗舰版", en: "Flagship" }, short: { zh: "旗舰", en: "Flagship" } }),
]);

export function getPlanPrice(planId, period) {
  const plan = BASE_PLANS.find((candidate) => candidate.id === planId);
  if (!plan || !["monthly", "annual"].includes(period)) throw new RangeError("Unknown plan or billing period");
  const annual = period === "annual";
  const undiscountedMinor = plan.monthlyMinor * (annual ? 12 : 1);
  const totalMinor = annual ? undiscountedMinor * 90 / 100 : undiscountedMinor;
  return { currency: "CNY", period, totalMinor, monthlyEquivalentMinor: totalMinor / (annual ? 12 : 1), savingsMinor: undiscountedMinor - totalMinor };
}

export function formatCny(minor, locale = "en") {
  return new Intl.NumberFormat(locale === "zh" ? "zh-CN" : "en-US", {
    style: "currency", currency: "CNY", currencyDisplay: "narrowSymbol",
    minimumFractionDigits: minor % 100 === 0 ? 0 : 2, maximumFractionDigits: 2,
  }).format(minor / 100);
}

export function getBasePlanCards(locale) {
  const zh = locale === "zh";
  return BASE_PLANS.map((plan, index) => ({
    ...plan, name: plan.name[locale], short: plan.short[locale], label: `BASE DATA / 0${index + 1}`,
    audience: zh ? "相同的基础数据，只需选择适合你的请求频率。" : "The same base data. Choose the request rate that fits your needs.",
    position: zh ? "同一基础数据范围，不按档位缩减" : "The same base-data scope across all tiers",
    coverage: zh ? "三档相同 · 不含 Crypto 与另类数据" : "Same across tiers · excludes Crypto and alternative data",
    history: zh ? "以各数据产品披露为准" : "As disclosed by each data product",
    runtime: zh ? `${plan.requestsPerMinute.toLocaleString("en-US")} 次 / 分钟` : `${plan.requestsPerMinute.toLocaleString("en-US")} requests / minute`,
    includes: zh ? ["相同的基础数据范围", "统一 Catalog / Query 接口", "来源、时间与采集凭证", "不设每日请求额度"] : ["The same base-data scope", "One Catalog / Query interface", "Source, time, and collection receipts", "No daily request quota"],
  }));
}
