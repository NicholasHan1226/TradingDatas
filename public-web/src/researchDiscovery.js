// Reader-facing taxonomy. Preserve original record topics and source identities.
export const researchSubjects = [
  ["all", "全部文献", "All literature", "从经典论文到行业资料，找到你的研究起点。", "Find your starting point in papers and primary research materials."],
  ["asset-pricing", "资产定价", "Asset pricing", "理解风险、收益与资产价格。", "Explore risk, returns, and asset prices."],
  ["market-microstructure", "市场微观结构", "Market microstructure", "从交易机制理解价格、成交量与流动性。", "Understand prices, volume, and liquidity through market structure."],
  ["corporate-fundamentals", "公司与财务", "Company & financials", "从财务信息、盈余质量到资产价格。", "From financial information and earnings quality to asset prices."],
  ["a-share-market", "A股市场", "China & comparative markets", "在制度与市场背景下阅读中国市场研究。", "Read Chinese-market research in its institutional and comparative context."],
  ["alternative-data", "另类数据", "Alternative data", "从文本、关注度与事件中理解新的研究材料。", "Explore text, attention, and events as research materials."],
  ["crypto-markets", "加密市场", "Crypto markets", "理解代币、交易场所与链上市场。", "Understand tokens, trading venues, and on-chain markets."],
  ["research-methods", "研究方法", "Research methods", "从样本与统计方法到结果验证。", "From sampling and statistical methods to validation."],
  ["macro-finance", "宏观金融", "Macro & fixed income", "连接经济环境、利率与金融市场。", "Connect economic conditions, interest rates, and financial markets."],
].map(([id, zh, en, descriptionZh, descriptionEn]) => ({ id, label: { zh, en }, description: { zh: descriptionZh, en: descriptionEn } }));

export const researchSubject = (topic) => topic === "quant-methods" ? "research-methods" : topic;
export const researchMatches = (paper, topic, kind) => (topic === "all" || researchSubject(paper.topic) === researchSubject(topic)) && (kind === "all" || paper.kind === kind);
export const researchPageSize = 12;

export function researchHref(state) {
  const query = new URLSearchParams();
  if (state.open) query.set("view", "topics");
  if (state.topic !== "all") query.set("topic", researchSubject(state.topic));
  if (state.kind !== "all") query.set("format", state.kind);
  if (state.page > 0) query.set("page", String(state.page + 1));
  return `/research${query.size ? `?${query}` : ""}`;
}

export function researchLocation(search, papers) {
  const query = new URLSearchParams(search);
  const candidate = researchSubject(query.get("topic"));
  const topic = researchSubjects.some((item) => item.id === candidate) ? candidate : "all";
  const kind = papers.some((paper) => paper.kind === query.get("format")) ? query.get("format") : "all";
  const count = papers.filter((paper) => researchMatches(paper, topic, kind)).length;
  const requested = Number(query.get("page"));
  const page = Number.isSafeInteger(requested) && requested > 0 ? Math.min(requested - 1, Math.max(0, Math.ceil(count / researchPageSize) - 1)) : 0;
  return { topic, kind, page, open: query.get("view") === "topics" };
}
