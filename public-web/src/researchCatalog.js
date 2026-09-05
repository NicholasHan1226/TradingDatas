import legacy from "./researchLegacy.json" with { type: "json" };
import bibliography from "./researchBibliography.json" with { type: "json" };
import sourcePages from "./researchSourcePages.json" with { type: "json" };
import { researchSeeds } from "./researchSeeds.js";
import { researchReaderNotes, sourceSpecificReaderLimits } from "./researchReaderNotes.js";
import { researchGuideMaterials } from "./researchGuideMaterials.js";
import { researchSummaryMaterials } from "./researchSummaryMaterials.js";

export const researchUpdatedAt = "2026-08-31";
const cleanText = (value) => value?.replace(/<[^>]*>/g, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'");
export const paperSlug = (paper) => paper.id || paper.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
export const researchTitle = (paper, locale) => locale === "zh" ? paper.titleZh : (paper.sourceTitle || paper.title);
export const researchData = (paper, locale) => locale === "zh" ? paper.dataZh : paper.data;
export const researchYear = (paper, locale) => paper.year === "living" ? (locale === "zh" ? "持续更新资料" : "Living reference") : paper.year;

const legacyTranslations = [
  ["股票与债券收益中的共同风险因子", "收益；基本面；组合构造"],
  ["买入赢家与卖出输家：市场效率研究", "日价格；复权收益；形成期与持有期"],
  ["连续竞价与知情交易", "成交；报价；成交量"],
  ["组合交易的最优执行", "日内价格；成交量；价差"],
  ["价格动量与交易量", "收益；换手率；组合"],
  ["预期股票收益的横截面", "价格；市值；财务报表"],
  ["中国股票市场的发展及其全球经济意义", "A股价格；所有权；基本面"],
  ["媒体覆盖与股票收益横截面", "新闻覆盖；收益；企业特征"],
  ["沪深300指数编制方法", "成分股；自由流通市值；公司行动"],
  ["上海证券交易所统计年鉴（2025卷）", "市场统计；上市公司；成交；融资"],
  ["2010年5月6日市场事件联合调查报告", "成交；报价；订单流；期货"],
  ["2021年初股票与期权市场结构工作人员报告", "价格；期权；卖空余额；参与者活动"],
  ["已实现波动率的建模与预测", "分钟收益；采样间隔；交易时段；缺失观测"],
  ["中国股票市场的日内信息效率", "逐笔成交；报价；买卖价差；成交量"],
  ["赋予投资者情绪以内容：媒体在股市中的作用", "新闻文本；发布时间；实体映射；收益；成交量"],
  ["加密货币市场的交易与套利", "跨交易所价格；带方向成交量；法币市场；场所身份"],
  ["为何使用DeFi借贷？来自Aave V2的证据", "协议交易；抵押物；借贷利率；治理代币"],
  ["Form 13F：官方申报指引与EDGAR数据访问", "机构范围；13F文件；修订；CIK；提交时点"],
  ["Binance USDⓈ-M市场数据：资金费率与持仓量", "固定标的范围；资金费率历史；持仓量；请求限制"],
];

export const researchProfiles = {
  "asset-pricing": {
    related: { datasets: ["cn-equity-daily", "cn-pit-fundamentals"], recipes: ["pit-fundamentals-panel"] },
    limits: { en: "Theory and historical samples do not establish a current premium. Retain delistings, dated universe membership, financing assumptions, and the original market's institutional context.", zh: "理论与历史样本不能证明当前溢价。需保留退市证券、带日期的样本成员、融资假设及原市场制度背景。" },
    checks: { en: ["Freeze the historical universe and include exits.", "Align accounting inputs to when investors could obtain them.", "Separate model assumptions from empirical observations."], zh: ["冻结历史样本范围并纳入退出证券。", "按投资者当时可获得的时点对齐会计输入。", "分开记录模型假设与实际观测。"] },
  },
  "market-microstructure": {
    related: { datasets: ["cn-equity-minute"], features: ["liquidity-measures"] },
    limits: { en: "Minute OHLCV cannot replace order-book messages, trade direction, participant identities, or synchronized venue quotes. Original venue rules and timestamp precision matter.", zh: "分钟OHLCV不能替代订单簿报文、交易方向、参与者身份或同步场所报价。必须核对原交易场所规则与时间戳精度。" },
    checks: { en: ["Keep exchange time, receive time, and timezone distinct.", "Identify auction, continuous trading, and overnight intervals.", "List unavailable quote, queue, or participant fields explicitly."], zh: ["区分交易所时间、接收时间与时区。", "标识竞价、连续交易与隔夜区间。", "明确列出缺少的报价、队列或参与者字段。"] },
  },
  "corporate-fundamentals": {
    related: { datasets: ["cn-pit-fundamentals", "cn-company-master"], recipes: ["pit-fundamentals-panel"] },
    limits: { en: "Fiscal period-end is not publication time. Restatements, unit changes, accounting standards, and historical security mappings can change the result of a replication.", zh: "报告期末不是披露时点。重述、单位变化、会计准则和历史证券映射都可能改变复现结果。" },
    checks: { en: ["Preserve filing and amendment versions.", "Record units, consolidation scope, and fiscal calendar.", "Join by as-of availability, not the latest restated value."], zh: ["保留披露文件与修订版本。", "记录单位、合并范围和会计日历。", "按当时可得性连接，不能使用最新重述值回填历史。"] },
  },
  "alternative-data": {
    related: { datasets: ["cn-news-flashes", "cn-announcements"], recipes: ["company-event-timeline"] },
    limits: { en: "Public visibility does not establish redistribution rights. Text, attention, and social activity are proxies whose entity mapping, timing, and selection bias must be checked.", zh: "公开可见不等于拥有再分发权。文本、关注度和社交活动是代理变量，需要核对实体映射、时点与选择偏差。" },
    checks: { en: ["Record publisher, source URL, permissions, and first-seen time.", "Deduplicate syndication and map entities before aggregation.", "Keep labels and validation samples outside model training."], zh: ["记录发布方、来源链接、权限与首次可见时点。", "汇总前去除转载重复并完成实体映射。", "将标签和验证样本与模型训练隔离。"] },
  },
  "crypto-markets": {
    related: {},
    limits: { en: "One exchange is not the whole crypto market. Spot, perpetuals, lending protocols, and on-chain transactions have different units, clocks, collateral rules, and coverage.", zh: "单一交易所不代表整个加密市场。现货、永续、借贷协议与链上交易的单位、时间、抵押规则和覆盖范围均不同。" },
    checks: { en: ["Freeze venue, contract type, token universe, and quote currency.", "Separate funding rates, premium indices, and open interest.", "Track contract changes, missing periods, and protocol versions."], zh: ["冻结场所、合约类型、代币范围与计价币。", "区分资金费率、溢价指数与持仓量。", "追踪合约变化、缺失区间与协议版本。"] },
  },
  "a-share-market": {
    related: { datasets: ["cn-equity-daily", "cn-company-master", "cn-market-reference"] },
    limits: { en: "Chinese and comparative-market evidence is specific to its sample and institutional period. Preserve share classes, ownership changes, suspensions, and dated eligibility rules.", zh: "中国市场及比较市场证据受样本与制度时期限制。需保留股份类别、所有权变化、停牌及带生效日期的资格规则。" },
    checks: { en: ["Record the study's geography and policy regime.", "Retain historical listing, ownership, and eligibility states.", "Distinguish corporate events from mechanical price adjustments."], zh: ["记录研究地区与政策制度阶段。", "保留历史上市、所有权与准入状态。", "区分公司事件与机械价格调整。"] },
  },
  "research-methods": {
    related: { recipes: ["pit-fundamentals-panel", "adjusted-price-series"] },
    limits: { en: "A method's assumptions need validation on the chosen sample. Dependence, model selection, repeated testing, and time leakage can invalidate otherwise standard procedures.", zh: "方法假设需要在所选样本上验证。观测依赖、模型选择、重复检验和时间泄漏都可能使标准程序失效。" },
    checks: { en: ["Declare the sampling unit, dependence structure, and estimand.", "Freeze chronological training, validation, and test periods.", "Record all tried specifications and sensitivity checks."], zh: ["声明采样单位、依赖结构与估计目标。", "冻结按时间顺序划分的训练、验证与测试期。", "记录所有尝试过的设定和敏感性检查。"] },
  },
  "macro-finance": {
    related: { datasets: ["cn-macro-calendar", "cn-yield-curve", "global-macro-indicators"] },
    limits: { en: "Latest revised macro series are not historical information sets. Country definitions, release lags, seasonal adjustment, yield conventions, and currencies must remain explicit.", zh: "最新修订宏观序列不等于历史信息集。国家口径、发布滞后、季调、收益率惯例和币种都必须明确。" },
    checks: { en: ["Preserve release dates and data vintages.", "Standardize units, maturities, currencies, and calendars.", "Keep identification assumptions separate from observed correlations."], zh: ["保留发布日期与数据版本。", "统一单位、期限、币种与日历。", "将识别假设与观测相关性分别记录。"] },
  },
};
researchProfiles["quant-methods"] = researchProfiles["research-methods"];

const officialOverrides = {
  "Form 13F: Official Filing Guidance and EDGAR Data Access": { year: "living" },
  "Binance USDⓈ-M Futures Market Data: Funding Rate and Open Interest": { year: "living" },
  "CSI 300 Index Methodology": { year: "2023", sourceNote: { en: "September 2023 PDF edition; a historical methodology version.", zh: "2023年9月PDF版本；属于历史方法论版本。" } },
  "SSE Statistical Yearbook": { year: "2025", sources: [{ label: "SSE statistical yearbook archive", url: "https://www.sse.com.cn/aboutus/publication/yearly/" }], sourceNote: { en: "2025 volume covers 2024 statistics; use the selected volume's definitions.", zh: "2025卷收录2024年统计；使用时以所选卷次的定义为准。" } },
  "Findings Regarding the Market Events of May 6, 2010": { sources: [{ label: "SEC / CFTC joint report", url: "https://www.sec.gov/files/marketevents-report.pdf" }] },
  "Staff Report on Equity and Options Market Structure Conditions in Early 2021": { sources: [{ label: "SEC staff report", url: "https://www.sec.gov/about/reports-publications/staff-report-equity-options-market-structure-conditions-early-2021" }] },
  "Why DeFi Lending? Evidence from Aave V2": { data: "protocol transactions; collateral; lending rates; governance tokens", year: "2024 · rev. 2025" },
};

// Historical checks are per source, never inherited from the library update date.
export const legacySourceChecks = {
  "CSI 300 Index Methodology": "2026-08-30",
  "SSE Statistical Yearbook": "2026-08-30",
  "Findings Regarding the Market Events of May 6, 2010": "2026-08-30",
  "Staff Report on Equity and Options Market Structure Conditions in Early 2021": "2026-08-30",
  "Why DeFi Lending? Evidence from Aave V2": "2026-08-30",
  "Form 13F: Official Filing Guidance and EDGAR Data Access": "2026-08-30",
  "Binance USDⓈ-M Futures Market Data: Funding Rate and Open Interest": "2026-08-30",
};

function assemble(seed, legacyIndex) {
  const metadata = sourcePages[seed.title] || bibliography[seed.title];
  const original = legacyIndex !== undefined;
  const translation = original ? legacyTranslations[legacyIndex] : null;
  const profile = researchProfiles[seed.topic];
  const official = officialOverrides[seed.title] || {};
  if (!metadata && (!original || seed.kind === "paper" || !legacySourceChecks[seed.title] || !(official.sources || seed.sources)?.length)) {
    throw new Error(`Research source verification required: ${seed.title}`);
  }
  const kind = ["book", "monograph", "book-chapter"].includes(metadata?.type) ? "book" : metadata?.type === "institutional-report" ? "industry-research" : metadata?.type === "posted-content" || metadata?.type === "report" || /SSRN Electronic Journal/.test(metadata?.venue || "") ? "working-paper" : seed.kind || "paper";
  return {
    ...seed, ...official,
    id: paperSlug(seed),
    titleZh: seed.titleZh || translation?.[0],
    dataZh: seed.dataZh || translation?.[1],
    sourceTitle: cleanText(metadata?.title || seed.title),
    authors: metadata?.authors?.join(" · ") || seed.authors,
    venue: metadata?.doi?.startsWith("10.2139/") ? "SSRN" : cleanText(metadata?.venue || seed.venue),
    year: metadata?.year ? String(metadata.year) : official.year || seed.year,
    kind,
    sources: metadata ? [{ label: metadata.doi ? "DOI" : metadata.venue, url: metadata.sourceUrl }] : official.sources || seed.sources,
    evidence: metadata || { verification: "official_source_page", checkedAt: legacySourceChecks[seed.title] },
    verifiedAt: metadata?.checkedAt || legacySourceChecks[seed.title],
    readiness: original ? seed.readiness || "orientation_only" : "orientation_only",
    related: researchReaderNotes[seed.title]?.related ?? researchGuideMaterials[seed.title] ?? researchSummaryMaterials[seed.title] ?? {},
    limits: seed.limits || profile.limits,
    checks: profile.checks,
    readingNotes: researchReaderNotes[seed.title]?.sections,
    guideSectionCount: researchReaderNotes[seed.title]?.sections.length ?? 0,
    readerLimits: researchReaderNotes[seed.title]?.limits || sourceSpecificReaderLimits[seed.title],
    readerReviewedAt: researchReaderNotes[seed.title]?.reviewedAt,
    // An orientation estimate for this concise record, never the full source.
    orientationMinutes: 3,
  };
}

export const papers = [...legacy.map((seed, index) => assemble(seed, index)), ...researchSeeds.map((seed) => assemble(seed))];

export const readingPaths = [
  { id: "pit-fundamentals", title: { en: "Point-in-time fundamentals", zh: "时点一致财务" }, titles: ["The Cross-Section of Expected Stock Returns", "Do Stock Prices Fully Reflect Information in Accruals and Cash Flows about Future Earnings?", "The Quality of Accruals and Earnings: The Role of Accrual Estimation Errors", "Replicating Anomalies"] },
  { id: "market-microstructure", title: { en: "A-share microstructure", zh: "A股微观结构" }, titles: ["Continuous Auctions and Insider Trading", "Intraday Information Efficiency on the Chinese Equity Market", "Modeling and Forecasting Realized Volatility", "A Simple Way to Estimate Bid-Ask Spreads from Daily High and Low Prices"] },
  { id: "announcement-events", title: { en: "Announcements and events", zh: "公告与事件" }, titles: ["Event Studies in Economics and Finance", "Giving Content to Investor Sentiment: The Role of Media in the Stock Market", "When Is a Liability Not a Liability? Textual Analysis, Dictionaries, and 10-Ks", "Lazy Prices"] },
];
