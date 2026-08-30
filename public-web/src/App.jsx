import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowSquareOut,
  BookmarkSimple,
  BookOpenText,
  Check,
  Clock,
  ClockCounterClockwise,
  Copy,
  Database,
  FileText,
  FunnelSimple,
  GraduationCap,
  GlobeSimple,
  List,
  MagnifyingGlass,
  Moon,
  ShieldCheck,
  Sun,
  TerminalWindow,
  UserCircle,
  X,
} from "@phosphor-icons/react";
import { productManifest } from "./productManifest";
import { formatCny, getBasePlanCards, getPlanPrice } from "./pricing";
import { buildPreviewPath, readPreviewSelection, safeLoginDestination } from "./purchasePreview";
import { PurchasePreview } from "./PurchasePreview.jsx";
import connectedInterfaceSnapshot from "./connectedInterfaceSnapshot.json";
import {
  collectionHistory,
  connectedCoverage,
  landscapeMeta,
  roadmapPhases,
  sourceCandidates,
} from "./dataSourceLandscape";
import { createSearchDocument, getSearchNavigationIndex, isGlobalSearchShortcut, normalizeSearchValue, searchGroups } from "./searchIndex";
import { accountJson, confirmAccountSignOut, getAccountViewState, readAccountIdentity, startAccountSession, startEmailSession } from "./accountSession";
import { LoginPage } from "./LoginPage";
import { EmailAccountPanel } from "./EmailAccountPanel";

const agents = ["Claude", "Codex", "OpenClaw", "Hermes", "Other Agent"];
const productRoutes = ["home", "data", "datasets", "features", "recipes", "research", "pricing", "docs", "status", "changelog", "login", "account"];
const LEGACY_ACCOUNT_TOKEN_KEY = "td-account-token";
const TAB_ACCOUNT_TOKEN_KEY = "td-account-tab-token";

function clearLegacyAccountToken() {
  // Retire the direct bearer bridge. Existing server credentials are untouched.
  try { localStorage.removeItem(LEGACY_ACCOUNT_TOKEN_KEY); } catch { /* Storage may be disabled. */ }
  try { sessionStorage.removeItem(TAB_ACCOUNT_TOKEN_KEY); } catch { /* Cookie login remains available. */ }
}

function getRouteFromPath() {
  const candidate = window.location.pathname.replace(/^\/+|\/+$/g, "") || "home";
  const [primary] = candidate.split("/");
  if (primary === "cookbook") return candidate.replace(/^cookbook/, "recipes");
  return productRoutes.includes(primary) ? candidate : "home";
}

const papers = [
  {
    title: "Common risk factors in the returns on stocks and bonds",
    authors: "Eugene F. Fama · Kenneth R. French",
    venue: "Journal of Financial Economics",
    year: "1993",
    kind: "paper",
    topic: "asset-pricing",
    data: "returns · fundamentals · portfolios",
    summary: {
      en: "Examines how market, size, value, term, and default factors relate to stock and bond returns.",
      zh: "研究市场、规模、价值、期限与违约等因素如何与股票及债券收益相关。",
    },
  },
  {
    title: "Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency",
    authors: "Narasimhan Jegadeesh · Sheridan Titman",
    venue: "The Journal of Finance",
    year: "1993",
    kind: "paper",
    topic: "quant-methods",
    data: "daily prices · adjusted returns",
    summary: {
      en: "Studies return persistence through portfolios formed from prior winners and losers.",
      zh: "通过历史赢家与输家组合，研究收益的延续性及其市场效率含义。",
    },
  },
  {
    title: "Continuous Auctions and Insider Trading",
    authors: "Albert S. Kyle",
    venue: "Econometrica",
    year: "1985",
    kind: "paper",
    topic: "market-microstructure",
    data: "trades · quotes · volume",
    summary: {
      en: "Models how private information, order flow, and market-maker pricing interact in continuous auctions.",
      zh: "建模分析连续竞价中私人信息、订单流与做市定价之间的关系。",
    },
  },
  {
    title: "Optimal Execution of Portfolio Transactions",
    authors: "Robert Almgren · Neil Chriss",
    venue: "Journal of Risk",
    year: "2001",
    kind: "paper",
    topic: "market-microstructure",
    data: "intraday prices · volume · spread",
    summary: {
      en: "Frames execution as a balance between market impact, timing risk, and trading horizon.",
      zh: "从市场冲击、时间风险与交易周期之间的权衡来刻画执行问题。",
    },
  },
  {
    title: "Price Momentum and Trading Volume",
    authors: "Charles M. C. Lee · Bhaskaran Swaminathan",
    venue: "The Journal of Finance",
    year: "2000",
    kind: "paper",
    topic: "quant-methods",
    data: "returns · turnover · portfolios",
    summary: {
      en: "Examines how trading volume can help interpret the persistence and reversal of price momentum.",
      zh: "研究交易量如何帮助理解价格动量的延续与反转。",
    },
  },
  {
    title: "The Cross-Section of Expected Stock Returns",
    authors: "Eugene F. Fama · Kenneth R. French",
    venue: "The Journal of Finance",
    year: "1992",
    kind: "paper",
    topic: "corporate-fundamentals",
    data: "prices · market cap · financials",
    summary: {
      en: "Studies how firm size, book-to-market, leverage, and earnings-to-price relate to expected returns.",
      zh: "研究公司规模、账面市值比、杠杆及盈价比与预期收益的关系。",
    },
  },
  {
    title: "China's Stock Market: A Marriage of Capitalism and State Control",
    authors: "Jennifer N. Carpenter · Fangzhou Lu · Robert F. Whitelaw",
    venue: "The Review of Financial Studies",
    year: "2021",
    kind: "paper",
    topic: "a-share-market",
    data: "A-share prices · ownership · fundamentals",
    summary: {
      en: "Reviews the ownership, institutional structure, and market development of China's stock market.",
      zh: "梳理中国股票市场的所有权、制度结构与市场发展特征。",
    },
  },
  {
    title: "Media Coverage and the Cross-section of Stock Returns",
    authors: "Lily Fang · Joel Peress",
    venue: "The Journal of Finance",
    year: "2009",
    kind: "paper",
    topic: "alternative-data",
    data: "news coverage · returns · firm characteristics",
    summary: {
      en: "Examines how differences in media coverage relate to the cross-section of stock returns.",
      zh: "研究媒体覆盖差异如何与股票横截面收益表现相关。",
    },
  },
  {
    title: "CSI 300 Index Methodology",
    authors: "China Securities Index Company",
    venue: "Index methodology",
    year: "2025",
    kind: "industry-research",
    topic: "a-share-market",
    data: "constituents · free-float market cap · corporate actions",
    summary: {
      en: "Explains the index universe, selection, weighting, review, and adjustment methodology.",
      zh: "说明指数样本空间、选样、加权、定期审核与调整方法。",
    },
  },
  {
    title: "SSE Statistical Yearbook",
    authors: "Shanghai Stock Exchange",
    venue: "Market statistics",
    year: "2025",
    kind: "industry-research",
    topic: "a-share-market",
    data: "market statistics · listings · turnover · financing",
    summary: {
      en: "Provides a structured reference for market scale, listings, trading activity, and financing statistics.",
      zh: "提供市场规模、上市公司、交易活动与融资统计的结构化年度参考。",
    },
  },
  {
    title: "Findings Regarding the Market Events of May 6, 2010",
    authors: "U.S. SEC · CFTC",
    venue: "Joint staff report",
    year: "2010",
    kind: "case",
    topic: "market-microstructure",
    data: "trades · quotes · order flow · futures",
    summary: {
      en: "Reconstructs a market-structure event using synchronized order, trade, quote, and futures evidence.",
      zh: "使用同步的订单、成交、报价与期货证据重建一次市场结构事件。",
    },
  },
  {
    title: "Staff Report on Equity and Options Market Structure Conditions in Early 2021",
    authors: "U.S. Securities and Exchange Commission",
    venue: "Staff report",
    year: "2021",
    kind: "case",
    topic: "alternative-data",
    data: "prices · options · short interest · account activity",
    summary: {
      en: "Organizes market, options, short-interest, and participation evidence around a high-attention trading episode.",
      zh: "围绕一次高关注交易事件，整理市场、期权、卖空与参与者活动证据。",
    },
  },
];

const paperSlug = (paper) => paper.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");

const messages = {
  en: {
    nav: ["Data", "Research", "Pricing"],
    eyebrow: "RAW MATERIALS FOR FINANCIAL RESEARCH",
    title: "Research-ready\nfinancial data.",
    subtitle: "One API for high-quality, traceable, composable financial data.",
    connect: "Connect your Agent",
    explore: "Explore the data catalog",
    receipts: "Data, with receipts.",
    receiptsCopy: "Every batch includes verifiable source, time, quality status, and collection receipt.",
    receiptAction: "See how transparency works",
    receiptLabel: "RECEIPT PROOF",
    observed: "observed",
    validated: "schema validated",
    catalogTitle: "Choose material, not permissions.",
    catalogCopy: "A-share market data is grouped by the work you need to do—not by upstream API names.",
    core: "Core market data",
    coreCopy: "Daily prices, corporate actions, financials, indices and reference data.",
    intraday: "Intraday data",
    intradayCopy: "Historical minutes, auction observations and session-level market material.",
    alternative: "Alternative data",
    alternativeCopy: "Clean third-party announcements, news, policy, research and interaction data as explicit add-ons.",
    browse: "Browse datasets",
    addOn: "Explore add-ons",
    cookbookTitle: "Learn how the materials fit together.",
    cookbookCopy: "Cookbook methods show preparation, joins, time alignment and validation. Your research remains yours.",
    recipes: ["Prepare a company-event timeline", "Build a point-in-time financial panel", "Align adjusted daily and minute observations"],
    researchTitle: "Read the field. Find the data behind it.",
    researchCopy: "A curated index of external financial research for learning—mapped to the raw data materials each paper relies on.",
    researchSearch: "Search title, author, journal, or data material",
    researchTopics: [
      ["all", "All"], ["asset-pricing", "Asset pricing"], ["market-microstructure", "Market microstructure"],
      ["corporate-fundamentals", "Corporate fundamentals"], ["alternative-data", "Alternative data"],
      ["quant-methods", "Quant methods"], ["a-share-market", "A-share market"],
    ],
    researchKinds: [["all", "All formats"], ["paper", "Papers"], ["industry-research", "Industry research"], ["case", "Cases"]],
    researchResults: "items in this curated sample",
    researchEmpty: "No research items match these filters.",
    requiredData: "DATA MATERIALS",
    sourcePaper: "Open source record",
    researchNotice: "External literature · TradingDatas does not publish the conclusions",
    pricingTitle: "Complete packages for A-share workflows.",
    pricingCopy: "Start with the data needed for your workflow. Add alternative data only when you choose to.",
    plans: ["Research", "Systematic", "Trading"],
    proposal: "Package proposal",
    docsTitle: "One interface. Clear contracts.",
    docsCopy: "Catalog and query stay provider-neutral, authenticated and ready for HTTP-capable Agents.",
    account: "Account",
    accountItems: ["Overview", "Data & subscription", "Usage & limits", "API keys", "Agent Connections", "Billing & invoices", "Security"],
    environment: "Environment",
    language: "Language",
    appearance: "Appearance",
    system: "System",
    light: "Light",
    dark: "Dark",
    agentTitle: "Connect an Agent",
    agentCopy: "Choose your Agent, then copy a safe setup prompt. Secrets stay outside the prompt.",
    setupPrompt: "Setup prompt",
    copyPrompt: "Copy setup prompt",
    copied: "Copied",
    endpoint: "Authenticated endpoint",
    close: "Close",
    menu: "Open navigation",
  },
  zh: {
    nav: ["数据", "研究", "套餐"],
    eyebrow: "金融研究的高质量原料",
    title: "面向研究的\n金融数据。",
    subtitle: "一个接口，获得高质量、可追溯、可组合的金融数据。",
    connect: "接入你的 Agent",
    explore: "浏览数据目录",
    receipts: "数据，自带凭证。",
    receiptsCopy: "每一批数据都包含可验证的来源、时间、质量状态和采集凭证。",
    receiptAction: "了解透明度机制",
    receiptLabel: "数据凭证",
    observed: "已观测",
    validated: "结构已验证",
    catalogTitle: "选择数据材料，而不是理解上游权限。",
    catalogCopy: "A 股数据按你的工作场景组织，而不是按上游接口名称堆叠。",
    core: "核心市场数据",
    coreCopy: "日线、复权、公司行动、财务、指数和基础参考数据。",
    intraday: "日内数据",
    intradayCopy: "历史分钟、集合竞价与交易时段级市场材料。",
    alternative: "另类数据",
    alternativeCopy: "经过清洗的第三方公告、新闻、政策、研报与互动数据，可按需加购。",
    browse: "浏览数据集",
    addOn: "查看另类数据",
    cookbookTitle: "了解这些材料如何组合使用。",
    cookbookCopy: "Cookbook 讲清准备、连接、时间对齐和验证方法；研究判断始终属于你。",
    recipes: ["准备公司事件时间线", "构建时点一致的财务面板", "对齐复权日线与分钟观测"],
    researchTitle: "阅读行业研究，找到背后的数据材料。",
    researchCopy: "面向学习的外部金融研究论文索引，并标明每篇论文所依赖的原始数据类型。",
    researchSearch: "搜索题目、作者、期刊或数据材料",
    researchTopics: [
      ["all", "全部"], ["asset-pricing", "资产定价"], ["market-microstructure", "市场微观结构"],
      ["corporate-fundamentals", "公司基本面"], ["alternative-data", "另类数据"],
      ["quant-methods", "量化方法"], ["a-share-market", "A 股市场"],
    ],
    researchKinds: [["all", "全部形式"], ["paper", "论文"], ["industry-research", "行业研究"], ["case", "案例"]],
    researchResults: "条内容收录于当前示例",
    researchEmpty: "没有匹配的研究内容。",
    requiredData: "所需数据材料",
    sourcePaper: "打开来源记录",
    researchNotice: "外部文献 · TradingDatas 不发表其中的研究结论",
    pricingTitle: "面向 A 股工作流的完整套餐。",
    pricingCopy: "从工作所需的数据开始；只有在你明确选择时，才添加另类数据。",
    plans: ["研究", "量化", "交易"],
    proposal: "套餐方案",
    docsTitle: "一个接口，清晰的数据合同。",
    docsCopy: "Catalog 与 Query 保持供应商中立、全程认证，可直接供支持 HTTP 的 Agent 使用。",
    account: "账户",
    accountItems: ["概览", "数据与订阅", "用量与限制", "API 密钥", "Agent 接入", "账单与发票", "安全"],
    environment: "显示设置",
    language: "语言",
    appearance: "外观",
    system: "跟随系统",
    light: "明亮",
    dark: "暗色",
    agentTitle: "接入 Agent",
    agentCopy: "选择 Agent，然后复制安全的接入提示词。密钥不会写入提示词。",
    setupPrompt: "接入提示词",
    copyPrompt: "复制接入提示词",
    copied: "已复制",
    endpoint: "认证接口",
    close: "关闭",
    menu: "打开导航",
  },
};

function getSystemLocale() {
  return typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
}

function getSystemTheme() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function Brand({ onNavigate }) {
  return (
    <a className="brand" href="/" onClick={(event) => onNavigate(event, "/")} aria-label="TradingDatas home">
      <img src="/assets/tradingdata-mark.png" alt="" width="36" height="36" />
      <span>TradingDatas</span>
    </a>
  );
}

function AgentDialog({ open, onClose, copy, locale }) {
  const [agent, setAgent] = useState("Codex");
  const [copied, setCopied] = useState(false);
  const dialogRef = useRef(null);
  const prompt = useMemo(
    () => locale === "zh"
      ? `请为 ${agent} 配置 TradingDatas MCP。使用安全的本地密钥存储，不要把 API Key 写入提示词、URL 或日志。首先调用 GET /v1/catalog 验证连接；只通过 POST /v1/query 请求已授权数据，并遵守游标与限额。`
      : `Configure TradingDatas MCP for ${agent}. Keep the API key in secure local secret storage; never place it in prompts, URLs, or logs. Test with GET /v1/catalog first. Use POST /v1/query only for authorized data and respect cursors and limits.`,
    [agent, locale],
  );

  useEffect(() => {
    if (!open) return;
    const onKey = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    requestAnimationFrame(() => dialogRef.current?.focus());
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  async function copyPrompt() {
    await navigator.clipboard.writeText(prompt);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  if (!open) return null;
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="agent-dialog" role="dialog" aria-modal="true" aria-labelledby="agent-dialog-title" tabIndex="-1" ref={dialogRef}>
        <button className="icon-button dialog-close" type="button" onClick={onClose} aria-label={copy.close}><X size={20} /></button>
        <span className="mono-kicker">AGENT CONNECTIONS</span>
        <h2 id="agent-dialog-title">{copy.agentTitle}</h2>
        <p>{copy.agentCopy}</p>
        <div className="agent-tabs" role="tablist" aria-label="Agent">
          {agents.map((name) => (
            <button key={name} type="button" role="tab" aria-selected={agent === name} className={agent === name ? "is-active" : ""} onClick={() => setAgent(name)}>{name}</button>
          ))}
        </div>
        <div className="endpoint-row"><span>{copy.endpoint} · planned</span><code>https://api.tradingdatas.com</code></div>
        <div className="prompt-block">
          <div><span>{copy.setupPrompt}</span><span>catalog + query</span></div>
          <pre>{prompt}</pre>
        </div>
        <button className="primary-button dialog-action" type="button" onClick={copyPrompt}>
          {copied ? <Check weight="bold" /> : <Copy weight="bold" />}
          {copied ? copy.copied : copy.copyPrompt}
        </button>
      </section>
    </div>
  );
}

function ReceiptProof({ copy }) {
  return (
    <div className="receipt-proof" aria-label="Synthetic receipt example">
      <div className="receipt-heading"><span>{copy.receiptLabel}</span><span>example · synthetic</span></div>
      <dl>
        <div><dt>dataset</dt><dd>A-share daily prices</dd></div>
        <div><dt>coverage</dt><dd>2010—2026</dd></div>
        <div><dt>freshness</dt><dd>{copy.observed} 18:04 CST</dd></div>
        <div><dt>quality</dt><dd>{copy.validated}</dd></div>
        <div><dt>receipt</dt><dd>rcpt_9f3b7e21...14c8d2a7</dd></div>
      </dl>
      <div className="receipt-track" aria-hidden="true"><span /><span /><span /><span /><span /><span /><span /><span /></div>
      <div className="receipt-foot"><span>2010</span><span>verified · 2026-08-26</span></div>
    </div>
  );
}

function MaturityTag({ status, locale }) {
  const labels = {
    observed_example: locale === "zh" ? "已观测" : "Observed",
    pending_open: locale === "zh" ? "待开放" : "Pending release",
    product_definition: locale === "zh" ? "产品定义" : "Product definition",
    planned: locale === "zh" ? "规划中" : "Planned",
  };
  return <span className={`maturity-tag status-${status}`}>{labels[status] || status}</span>;
}

function SectionNav({ items, active, onNavigate, locale }) {
  return (
    <nav className="section-nav" aria-label={locale === "zh" ? "本板块分类" : "Section categories"}>
      {items.map((item) => <a key={item.path} href={item.path} className={active === item.path ? "is-active" : ""} onClick={(event) => onNavigate(event, item.path)}>{item.label}</a>)}
    </nav>
  );
}

function BasePlanShowcase({ locale, plans, activeIndex, onChange, onNavigate, billingPeriod, setBillingPeriod }) {
  const plan = plans[activeIndex];
  const zh = locale === "zh";
  const price = getPlanPrice(plan.id, billingPeriod);
  const move = (direction) => onChange((activeIndex + direction + plans.length) % plans.length);

  const sharedFacts = zh ? [
    ["每日总量", "不限"],
    ["质量凭证", "来源、时间与 receipt"],
    ["Agent 接入", "账户内 MCP 与提示词"],
    ["统一接口", "Catalog 与 Query"],
  ] : [
    ["Daily total", "Unlimited"],
    ["Data receipts", "Source, time, and receipt"],
    ["Agent access", "MCP and prompts in Account"],
    ["One interface", "Catalog and Query"],
  ];

  return <section className="base-plan-showcase" aria-labelledby="base-plan-showcase-title">
    <header className="base-plan-switcher">
      <div><span className="mono-kicker">{zh ? "3 档基础套餐" : "3 BASE PLANS"}</span><h2 id="base-plan-showcase-title">{zh ? "选择你的请求频率。" : "Choose your request rate."}</h2></div>
      <div className="base-plan-controls">
        <button type="button" className="base-plan-arrow is-prev" onClick={() => move(-1)} aria-label={zh ? "上一档套餐" : "Previous plan"}><ArrowRight /></button>
        <div role="group" aria-label={zh ? "基础套餐" : "Base plans"}>{plans.map((candidate, index) => <button type="button" aria-pressed={activeIndex === index} className={activeIndex === index ? "is-active" : ""} key={candidate.name} onClick={() => onChange(index)}><span>0{index + 1}</span>{candidate.short}</button>)}</div>
        <button type="button" className="base-plan-arrow is-next" onClick={() => move(1)} aria-label={zh ? "下一档套餐" : "Next plan"}><ArrowRight /></button>
      </div>
    </header>

    <div className="base-plan-billing">
      <div role="group" aria-label={zh ? "付款周期" : "Billing period"}>
        {["monthly", "annual"].map((period) => <button key={period} type="button" aria-pressed={billingPeriod === period} onClick={() => setBillingPeriod(period)}>{period === "monthly" ? (zh ? "月付" : "Monthly") : (zh ? "年付" : "Annual")}{period === "annual" && <small>{zh ? "9 折" : "Save 10%"}</small>}</button>)}
      </div>
      <span>{zh ? "人民币 CNY · 支付暂未开放" : "CNY · Checkout not yet available"}</span>
    </div>

    <article className={`base-plan-product tone-${plan.tone}`} aria-live="polite">
      <div className="base-plan-art" aria-hidden="true"><span /><span /><span /><i /><i /></div>
      <div className="base-plan-identity">
        <span>{plan.label}</span>
        <h3>{plan.name}</h3>
        <div className="base-plan-price">
          <div><strong>{formatCny(price.totalMinor, locale)}</strong><span>{billingPeriod === "annual" ? (zh ? "/ 年" : "/ year") : (zh ? "/ 月" : "/ month")}</span></div>
          <p>{billingPeriod === "annual" ? (zh ? `按年一次支付，折合 ${formatCny(price.monthlyEquivalentMinor, locale)} / 月；每年省 ${formatCny(price.savingsMinor, locale)}。` : `Billed annually. Equivalent to ${formatCny(price.monthlyEquivalentMinor, locale)} / month; save ${formatCny(price.savingsMinor, locale)} per year.`) : (zh ? "按月支付。选择年付可节省 10%。" : "Billed monthly. Save 10% with annual billing.")}</p>
        </div>
        <p>{plan.audience}</p>
        <div className="base-plan-position"><small>{zh ? "适用范围" : "POSITION"}</small><strong>{plan.position}</strong></div>
      </div>
      <div className="base-plan-includes">
        <span>{zh ? "包含的数据" : "DATA INCLUDED"}</span>
        <ul>{plan.includes.map((item) => <li key={item}><Check weight="bold" /><span>{item}</span></li>)}</ul>
      </div>
      <div className="base-plan-facts">
        <div><span>{zh ? "数据覆盖" : "COVERAGE"}</span><strong>{plan.coverage}</strong></div>
        <div><span>{zh ? "历史深度" : "HISTORY"}</span><strong>{plan.history}</strong></div>
        <div><span>{zh ? "请求频率" : "REQUEST RATE"}</span><strong>{plan.runtime}</strong></div>
        <a href={buildPreviewPath(plan.id, billingPeriod)} onClick={(event) => onNavigate(event, buildPreviewPath(plan.id, billingPeriod))}>{zh ? "查看购买预览" : "Preview this plan"}<ArrowRight /></a>
        <a className="base-plan-access" href={`/login?next=${encodeURIComponent(buildPreviewPath(plan.id, billingPeriod))}`} onClick={(event) => onNavigate(event, `/login?next=${encodeURIComponent(buildPreviewPath(plan.id, billingPeriod))}`)}>{zh ? "已有访问密钥？登录" : "Have an access key? Sign in"}<ArrowRight /></a>
      </div>
      <span className="base-plan-count">0{activeIndex + 1} / 0{plans.length}</span>
    </article>

    <div className="base-plan-shared" aria-label={zh ? "所有套餐共同包含" : "Included in every plan"}>
      <span>{zh ? "所有套餐共同包含" : "INCLUDED IN EVERY PLAN"}</span>
      {sharedFacts.map(([label, value]) => <div key={label}><small>{label}</small><strong>{value}</strong></div>)}
    </div>
  </section>;
}

function ProductMark({ item, compact = false }) {
  const familyItems = productManifest.objects.datasets.filter((candidate) => candidate.family === item.family);
  const variant = Math.max(0, familyItems.findIndex((candidate) => candidate.id === item.id)) % 8;
  return <span className={`data-product-mark family-${item.family} variant-${variant} ${compact ? "is-compact" : ""}`} aria-hidden="true"><img className="mark-primary" src={item.icon} alt="" /><img className="mark-echo" src={item.icon} alt="" /></span>;
}

function StabilityTrack({ item, locale, compact = false, showStage = true }) {
  const available = item.stability !== "—";
  return (
    <div className={`stability-block ${compact ? "is-compact" : ""} ${available ? "" : "is-unavailable"}`}>
      {(showStage || available) && <div className="stability-heading">
        {showStage && <MaturityTag status={item.status} locale={locale} />}
        {available && <strong>{item.stability}</strong>}
      </div>}
      {available ? <div className="stability-dots" aria-label={item.stabilityNote[locale]}>
        {Array.from({ length: compact ? 18 : 30 }, (_, index) => <span key={index} className={item.delayedDays.includes(index) ? "is-delayed" : ""} />)}
      </div> : <span className="stability-empty-line" aria-hidden="true" />}
      {(!compact || !available) && <small>{available ? item.stabilityNote[locale] : (locale === "zh" ? `尚无采集历史 · ${item.cadence}` : `No collection history · ${item.cadence}`)}</small>}
    </div>
  );
}

function DatasetSample({ item, locale, compact = false }) {
  return (
    <div className={`dataset-sample ${compact ? "is-compact" : ""}`}>
      <div className="dataset-sample-heading">
        <span>{locale === "zh" ? "数据内容示例" : "Sample data"}</span>
        <small>{item.fields ? `${item.fields} ${locale === "zh" ? "个字段" : "fields"}` : (locale === "zh" ? "合同预览 · 非真实数据" : "Contract preview · not live data")}</small>
      </div>
      <div className="dataset-sample-scroll">
        <table>
          <thead><tr>{item.sampleColumns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
          <tbody>{item.sampleRows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((value, columnIndex) => <td key={`${rowIndex}-${columnIndex}`}>{value}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}

function DatasetProductDetail({ item, locale, onNavigate }) {
  const [queryCopied, setQueryCopied] = useState(false);
  if (!item) {
    return <section className="object-detail-page"><a className="object-back" href="/data" onClick={(event) => onNavigate(event, "/data")}>← {locale === "zh" ? "返回数据目录" : "Back to Data"}</a><div className="object-detail-hero"><div><h1>{locale === "zh" ? "数据产品未找到" : "Data product not found"}</h1></div></div></section>;
  }
  const sameCategory = productManifest.objects.datasets.filter((candidate) => candidate.id !== item.id && candidate.family === item.family);
  const otherCategories = productManifest.objects.datasets.filter((candidate) => candidate.id !== item.id && candidate.family !== item.family);
  const related = [...sameCategory, ...otherCategories].slice(0, 3);
  const queryExample = `POST /v1/query\nAuthorization: Bearer <API_TOKEN>\nContent-Type: application/json\n\n${JSON.stringify({
    dataset_id: item.id,
    schema_major: 1,
    fields: item.sampleColumns,
    filters: {},
    as_of: null,
    limit: 100,
    cursor: null,
  }, null, 2)}`;
  const copyQueryExample = async () => {
    await navigator.clipboard.writeText(queryExample);
    setQueryCopied(true);
    window.setTimeout(() => setQueryCopied(false), 1600);
  };
  return (
    <section className="dataset-product-page">
      <a className="object-back" href="/data" onClick={(event) => onNavigate(event, "/data")}>← {locale === "zh" ? "返回数据目录" : "Back to Data products"}</a>
      <div className="dataset-product-layout">
        <main>
          <div className="dataset-product-identity">
            <ProductMark item={item} />
            <div>
              <span className="mono-kicker">{item.category[locale].toUpperCase()} / {item.market} / VERSIONED PRODUCT</span>
              <h1>{item.title[locale]}</h1>
              <p>{item.description[locale]}</p>
              <div className="dataset-tags">{item.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
              <div className="dataset-product-stage"><MaturityTag status={item.status} locale={locale} /><span>{locale === "zh" ? "产品阶段 · 与采集历史证据分开表达" : "Product stage · separate from collection evidence"}</span></div>
            </div>
          </div>
          <section className="dataset-inline-access" aria-label={locale === "zh" ? "数据合同与查询示例" : "Data contract and query example"}>
            <div className="dataset-contract-inline">
              <span className="mono-kicker">DATA CONTRACT</span>
              <h2>{locale === "zh" ? "数据合同" : "Data contract"}</h2>
              <p>{locale === "zh" ? "当前产品的身份、范围和接入边界直接在本页公开。" : "Identity, scope, and onboarding boundaries are published on this page."}</p>
              <dl>
                <div><dt>{locale === "zh" ? "产品 ID" : "Product ID"}</dt><dd>{item.id}</dd></div>
                <div><dt>{locale === "zh" ? "市场" : "Market"}</dt><dd>{item.market}</dd></div>
                <div><dt>{locale === "zh" ? "频率" : "Cadence"}</dt><dd>{item.cadence}</dd></div>
                <div><dt>{locale === "zh" ? "接入" : "Onboarding"}</dt><dd>{item.plan}</dd></div>
              </dl>
            </div>
            <div className="dataset-query-inline">
              <div className="dataset-query-heading">
                <div><span className="mono-kicker">POST /v1/query</span><h2>{locale === "zh" ? "查询示例" : "Query example"}</h2></div>
                <button type="button" onClick={copyQueryExample}>{queryCopied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}{queryCopied ? (locale === "zh" ? "已复制" : "Copied") : (locale === "zh" ? "复制请求" : "Copy request")}</button>
              </div>
              <pre><code>{queryExample}</code></pre>
              <p>{locale === "zh" ? "示例不会发起请求。使用前请先通过 GET /v1/catalog 确认正式 dataset_id、schema_major 与账户权限。" : "This example does not send a request. Confirm dataset_id, schema_major, and account access with GET /v1/catalog first."}</p>
            </div>
          </section>
          <DatasetSample item={item} locale={locale} />
          <section className="dataset-history">
            <div><span className="mono-kicker">90 DAY COLLECTION HISTORY</span><h2>{locale === "zh" ? "公开采集稳定性与缺口" : "Public collection stability and gaps"}</h2></div>
            <StabilityTrack item={item} locale={locale} showStage={false} />
          </section>
          <dl className="dataset-evidence-rail">
            <div><dt>{locale === "zh" ? "来源" : "Source"}</dt><dd>{item.source}</dd></div>
            <div><dt>{locale === "zh" ? "最近成功" : "Last success"}</dt><dd>{item.lastSuccess}</dd></div>
            <div><dt>{locale === "zh" ? "覆盖" : "Coverage"}</dt><dd>{item.coverage}</dd></div>
            <div><dt>{locale === "zh" ? "频率" : "Cadence"}</dt><dd>{item.cadence}</dd></div>
            <div><dt>Receipt</dt><dd>{item.receipt}</dd></div>
          </dl>
          <div className="collection-disclosure-roadmap"><span>{locale === "zh" ? "形成真实观测后继续披露" : "Disclosed after real observations exist"}</span><div>{(locale === "zh" ? ["成功 / 空响应 / 失败分布", "数据延迟趋势", "入库行数增长", "字段漂移", "修订量"] : ["success / empty / failure mix", "delivery-lag trend", "stored-row growth", "schema drift", "revision volume"]).map((signal) => <small key={signal}>{signal}</small>)}</div></div>
          <p className="catalog-authority-note">{locale === "zh" ? "当前页面展示产品合同与示例证据。真实可用性只来自 Registry、SQLite facts/receipts、认证 Catalog/Query 回读与账户授权。" : "This page presents the product contract and example evidence. Live availability comes only from the Registry, SQLite facts/receipts, authenticated Catalog/Query readback, and account entitlement."}</p>
        </main>
        <aside className="related-products">
          <span className="mono-kicker">{locale === "zh" ? "相关数据产品" : "RELATED PRODUCTS"}</span>
          {related.map((candidate) => <a key={candidate.id} href={`/datasets/${candidate.id}`} onClick={(event) => onNavigate(event, `/datasets/${candidate.id}`)}>
            <ProductMark item={candidate} compact />
            <div><span className="product-category-label">{candidate.category[locale]}</span><h2>{candidate.title[locale]}</h2><p>{candidate.description[locale]}</p><StabilityTrack item={candidate} locale={locale} compact /><small>{candidate.stability !== "—" ? candidate.lastSuccess : candidate.cadence}</small></div>
            <ArrowRight />
          </a>)}
        </aside>
      </div>
    </section>
  );
}

function AlternativeProductList({ locale, onNavigate, compact = false, limit }) {
  const products = productManifest.objects.datasets.filter((item) => item.family === "alternative").slice(0, limit);
  return <div className={`alternative-product-list ${compact ? "is-compact" : ""}`}>{products.map((item) => <a key={item.id} href={`/datasets/${item.id}`} onClick={(event) => onNavigate(event, `/datasets/${item.id}`)}>
    <ProductMark item={item} compact />
    <div><span className="product-category-label">{item.category[locale]}</span><h3>{item.title[locale]}</h3><p>{item.description[locale]}</p></div>
    <span className="alternative-plan"><MaturityTag status={item.status} locale={locale} />{item.plan}</span>
    <ArrowRight />
  </a>)}</div>;
}

function ProductObjectDetail({ type, item, locale, onNavigate }) {
  if (type === "datasets") return <DatasetProductDetail item={item} locale={locale} onNavigate={onNavigate} />;
  const typeLabel = type === "datasets" ? (locale === "zh" ? "数据集" : "Dataset") : type === "features" ? (locale === "zh" ? "透明特征" : "Transparent feature") : (locale === "zh" ? "数据 Recipe" : "Data recipe");
  const title = item?.title?.[locale] || (locale === "zh" ? "对象未找到" : "Object not found");
  const facts = type === "datasets" ? [
    [locale === "zh" ? "身份与范围" : "Identity & scope", "canonical ID candidate · A-share · provider-native lineage"],
    [locale === "zh" ? "结构与版本" : "Schema & version", "fields · primary key · cadence · coverage · revision policy"],
    [locale === "zh" ? "信任证据" : "Trust evidence", "source · validation · receipt · known limitations"],
  ] : type === "features" ? [
    [locale === "zh" ? "精确定义" : "Exact definition", "formula · inputs · alignment · lookback"],
    [locale === "zh" ? "版本合同" : "Version contract", "missingness · revision policy · fixtures · changelog"],
    [locale === "zh" ? "明确边界" : "Explicit boundary", "derived data only · no signal · no recommendation"],
  ] : [
    [locale === "zh" ? "研究任务" : "Research task", "question · required inputs · assumptions"],
    [locale === "zh" ? "可复现步骤" : "Reproducible steps", "query · align · join · validate"],
    [locale === "zh" ? "交付物" : "Output", "output schema · checks · limitations · related research"],
  ];
  return (
    <section className="object-detail-page">
      <a className="object-back" href={`/${type === "datasets" ? "data" : type}`} onClick={(event) => onNavigate(event, `/${type === "datasets" ? "data" : type}`)}>← {locale === "zh" ? "返回目录" : "Back to index"}</a>
      <div className="object-detail-hero">
        <div><span className="mono-kicker">{typeLabel.toUpperCase()} / VERSIONED OBJECT</span><h1>{title}</h1><p>{item?.detail}</p></div>
        {item && <MaturityTag status={item.status} locale={locale} />}
      </div>
      <div className="object-fact-grid">{facts.map(([label, value], index) => <article key={label}><span>0{index + 1}</span><h2>{label}</h2><p>{value}</p></article>)}</div>
      <section className="object-boundary"><span className="mono-kicker">CURRENT / TARGET BOUNDARY</span><h2>{locale === "zh" ? "这是一份可审查的产品合同，不是虚构的上线状态。" : "A reviewable product contract—not a fictional live state."}</h2><p>{locale === "zh" ? "真实可用性只能来自 Registry、事实与 receipt、认证 API 回读以及账户授权。当前未实现部分会一直标明为产品定义或规划中。" : "Live availability can only come from the Registry, facts and receipts, authenticated API readback, and account entitlement. Unimplemented parts remain labelled product definition or planned."}</p></section>
    </section>
  );
}

function ResearchAtlasPage({
  locale,
  theme,
  copy,
  atlas,
  featuredPaper,
  visiblePapers,
  researchTopic,
  setResearchTopic,
  researchKind,
  setResearchKind,
  browseOpen,
  setBrowseOpen,
  libraryRef,
  onShowLibrary,
  onNavigate,
  topicLabels,
  kindLabels,
  methods,
  bookmarks,
  onToggleBookmark,
}) {
  return <div className="research-page research-atlas" id="research">
    <section className="research-atlas-shell">
      <div className="research-atlas-hero">
        <div className="research-atlas-copy">
          <span className="mono-kicker">{atlas.eyebrow}</span>
          <h1>{atlas.title}</h1>
          <p>{atlas.copy}</p>
        </div>
        <div className="research-question-prompts">
          <span>{locale === "zh" ? "从一个问题开始" : "START WITH A QUESTION"}</span>
          <div>{atlas.suggestions.map((prompt) => <button key={prompt.label} type="button" onClick={() => onShowLibrary({ topic: prompt.topic })}>{prompt.label}<ArrowRight /></button>)}</div>
        </div>
      </div>

      <section className="research-paths" aria-labelledby="research-paths-title">
        <header><div><h2 id="research-paths-title">{atlas.pathsTitle}</h2><p>{atlas.pathsCopy}</p></div><button type="button" onClick={() => onShowLibrary({ topic: "all" })}>{atlas.browse}<ArrowRight /></button></header>
        <div className="research-path-grid">{atlas.paths.map((path) => {
          const linkedPaper = papers.find((paper) => paper.title === path.paperTitle);
          const href = linkedPaper ? `/research/${paperSlug(linkedPaper)}` : "/research";
          return <a className="research-path-card" key={path.label} href={href} onClick={(event) => onNavigate(event, href)}>
            <img src={theme === "dark" ? path.image : path.imageLight} alt="" />
            <div><span>{path.label}</span><h3>{path.question}</h3><div className="research-path-meta"><small><Clock />{path.time}</small><small><FileText />{path.count}</small></div><strong>{locale === "zh" ? "所需数据材料" : "Raw data materials"}</strong><p>{path.data}</p></div>
          </a>;
        })}</div>
      </section>

      {featuredPaper && <section className="research-featured" aria-labelledby="featured-paper-title">
        <header><div><h2>{atlas.featured}</h2><p>{atlas.featuredCopy}</p></div><button type="button" onClick={() => onShowLibrary({ topic: "all" })}>{atlas.browse}<ArrowRight /></button></header>
        <div className="research-featured-grid">
          <img className="research-paper-cover" src={theme === "dark" ? "/assets/research/featured-china-stock-market.png" : "/assets/research/featured-china-stock-market-light-v2.png"} alt="China's Stock Market — Capitalism and State Control cover" />
          <div className="research-featured-identity"><span>{locale === "zh" ? "推荐" : "FEATURED"}</span><h3 id="featured-paper-title">{featuredPaper.title}</h3><p>{featuredPaper.authors}</p><small>{featuredPaper.venue} · {featuredPaper.year}</small><div className="research-reading-actions"><span><i />{atlas.notStarted}</span><a href={`/research/${paperSlug(featuredPaper)}`} onClick={(event) => onNavigate(event, `/research/${paperSlug(featuredPaper)}`)}><BookOpenText />{atlas.overview}</a></div></div>
          <div className="research-featured-why"><strong>{atlas.why}</strong><p>{atlas.whyCopy}</p></div>
          <div className="research-featured-links"><strong>{atlas.linked}</strong><a href="/data" onClick={(event) => onNavigate(event, "/data")}><Database /><span>{locale === "zh" ? "数据产品" : "Datasets"}<small>{locale === "zh" ? "行情、基础参考、公司与财务" : "market, reference, company, fundamentals"}</small></span><ArrowRight /></a><a href="#research-methods"><BookOpenText /><span>{locale === "zh" ? "研究方法" : "Methods"}<small>{locale === "zh" ? "时点对齐、事件时间线、验证" : "point-in-time, event timeline, validation"}</small></span><ArrowRight /></a></div>
        </div>
      </section>}

      <section className="research-methods" id="research-methods" aria-labelledby="research-methods-title">
        <header>
          <div><span className="mono-kicker">METHODS / FOR REPRODUCIBLE PREPARATION</span><h2 id="research-methods-title">{locale === "zh" ? "从阅读进入数据准备。" : "Move from reading to data preparation."}</h2></div>
          <p>{locale === "zh" ? "原 Cookbook 收拢为研究方法：解释如何查询、对齐、连接和验证原始数据，但不替用户完成研究结论。" : "Cookbook is now progressively disclosed as research methods: query, align, join, and validate raw data without supplying the conclusion."}</p>
        </header>
        <div className="research-method-list">{methods.slice(0, 3).map((method, index) => <a key={method.id} href={`/recipes/${method.id}`} onClick={(event) => onNavigate(event, `/recipes/${method.id}`)}><span>{String(index + 1).padStart(2, "0")}</span><div><small>{locale === "zh" ? "可复现方法" : "REPRODUCIBLE METHOD"}</small><h3>{method.title[locale]}</h3><p>{method.detail}</p></div><ArrowRight /></a>)}</div>
      </section>

      <div className="research-atlas-notice"><span><GraduationCap weight="duotone" />{atlas.external}</span><span>{locale === "zh" ? "更新于 2026-08-27" : "Updated Aug 27, 2026"}</span></div>

      <section className={`research-library-drawer ${browseOpen ? "is-open" : ""}`} ref={libraryRef} aria-hidden={!browseOpen}>
        <header><div><span className="mono-kicker">RESEARCH LIBRARY / EXTERNAL SOURCES</span><h2>{locale === "zh" ? "完整研究库" : "Full research library"}</h2></div><button type="button" onClick={() => setBrowseOpen(false)}>{locale === "zh" ? "收起" : "Close"}<X /></button></header>
        <div className="research-library-controls">
          <div><span className="filter-label">{locale === "zh" ? "内容形式" : "FORMAT"}</span><div className="research-topics research-kinds" aria-label="Research formats">{copy.researchKinds.map(([kind, label]) => <button key={kind} type="button" className={researchKind === kind ? "is-active" : ""} onClick={() => setResearchKind(kind)}>{label}</button>)}</div></div>
          <div><span className="filter-label">{locale === "zh" ? "研究主题" : "TOPIC"}</span><div className="research-topics" aria-label="Research topics">{copy.researchTopics.map(([topic, label]) => <button key={topic} type="button" className={researchTopic === topic ? "is-active" : ""} onClick={() => setResearchTopic(topic)}>{label}</button>)}</div></div>
        </div>
        <div className="research-count"><span>{String(visiblePapers.length).padStart(2, "0")}</span>{copy.researchResults}</div>
        <div className="paper-list">{visiblePapers.length ? visiblePapers.map((paper, index) => {
          const bookmarkKey = `research:${paperSlug(paper)}`;
          const isSaved = bookmarks.includes(bookmarkKey);
          return <article className="paper-row" key={paper.title}><span className="paper-index">{String(index + 1).padStart(2, "0")}</span><div className="paper-main"><div className="paper-meta"><span>{kindLabels[paper.kind]}</span><span>{topicLabels[paper.topic]}</span><span>{paper.year}</span><span>{paper.venue}</span></div><h3>{paper.title}</h3><p>{paper.authors}</p><p className="paper-summary">{paper.summary[locale]}</p><div className="paper-data"><span>{copy.requiredData}</span><code>{paper.data}</code></div></div><div className="paper-actions"><button type="button" className={isSaved ? "is-saved" : ""} onClick={() => onToggleBookmark(bookmarkKey)} aria-label={isSaved ? (locale === "zh" ? "取消收藏" : "Remove bookmark") : (locale === "zh" ? "收藏" : "Bookmark")}><BookmarkSimple weight={isSaved ? "fill" : "regular"} /></button><a href={`/research/${paperSlug(paper)}`} onClick={(event) => onNavigate(event, `/research/${paperSlug(paper)}`)} aria-label={`${locale === "zh" ? "阅读 TradingDatas 整理页" : "Read TradingDatas record"}: ${paper.title}`}><ArrowRight /></a></div></article>;
        }) : <div className="research-empty">{copy.researchEmpty}</div>}</div>
      </section>
    </section>
  </div>;
}

function DataSourceLandscapePage({ locale, onNavigate }) {
  const familyLabels = {
    "china-markets": { zh: "中国市场", en: "China markets" },
    "global-markets": { zh: "全球市场", en: "Global markets" },
    "funds-indices": { zh: "基金与指数", en: "Funds & indices" },
    derivatives: { zh: "期货与期权", en: "Futures & options" },
    "macro-rates": { zh: "宏观与利率", en: "Macro & rates" },
    "company-regulatory": { zh: "公司与监管", en: "Company & regulatory" },
    "news-events": { zh: "新闻与事件", en: "News & events" },
    crypto: { zh: "加密与链上", en: "Crypto & on-chain" },
    "web-attention": { zh: "Web 与关注度", en: "Web & attention" },
    "physical-world": { zh: "实体世界", en: "Physical world" },
  };
  const connected = connectedInterfaceSnapshot.interfaces;
  const activeCount = connected.filter((item) => item.activation === "active").length;

  return (
    <section className="data-source-page">
      <SectionNav locale={locale} active="/data/sources" onNavigate={onNavigate} items={locale === "zh" ? [
        { path: "/data", label: "数据产品" }, { path: "/data/sources", label: "来源与计划" }, { path: "/data/alternative", label: "另类数据" }, { path: "/data/receipts", label: "凭证与覆盖" },
      ] : [
        { path: "/data", label: "Data products" }, { path: "/data/sources", label: "Sources & roadmap" }, { path: "/data/alternative", label: "Alternative data" }, { path: "/data/receipts", label: "Receipts & coverage" },
      ]} />
      <header className="data-source-hero">
        <span className="mono-kicker">SOURCE LANDSCAPE / CONNECTED + CANDIDATE</span>
        <h1>{locale === "zh" ? "把已接入、历史观测与下一步分开看。" : "Separate connected data, historical observations, and what comes next."}</h1>
        <p>{locale === "zh" ? "这里公开接口合同、候选来源与接入门槛；任何规划都不自动等于已购买、可再分发或正在稳定采集。" : "This view publishes interface contracts, candidate sources, and onboarding gates. A plan never means purchased, redistributable, or stably collected."}</p>
        <dl>
          <div><dt>{locale === "zh" ? "合同接口" : "Contract interfaces"}</dt><dd>{connected.length}</dd></div>
          <div><dt>{locale === "zh" ? "配置 active" : "Configured active"}</dt><dd>{activeCount}</dd></div>
          <div><dt>{locale === "zh" ? "候选来源" : "Candidate sources"}</dt><dd>{sourceCandidates.length}</dd></div>
          <div><dt>{locale === "zh" ? "最后审阅" : "Last reviewed"}</dt><dd>{landscapeMeta.reviewedAt}</dd></div>
        </dl>
      </header>
      <section className="source-evidence-section">
        <div className="section-heading compact-heading"><span className="mono-kicker">01 / CONNECTED CONTRACTS</span><h2>{locale === "zh" ? "已接入合同按运行面汇总。" : "Connected contracts by runtime plane."}</h2></div>
        <div className="source-summary-grid">{connectedCoverage.map((item) => <article key={item.id}><span>{item.market}</span><strong>{item.provider}</strong><b>{item.contractCount}</b><small>{item.unit}</small><p>{item.note[locale]}</p></article>)}</div>
      </section>
      <section className="source-evidence-section">
        <div className="section-heading compact-heading"><span className="mono-kicker">02 / OBSERVATION HISTORY</span><h2>{locale === "zh" ? "历史只说明当时发生了什么。" : "History only states what happened then."}</h2></div>
        <div className="source-history-list">{collectionHistory.map((event) => <article key={`${event.date}-${event.provider}`}><time>{event.date}</time><ClockCounterClockwise size={17} /><div><strong>{event.title[locale]}</strong><p>{event.detail[locale]}</p><small>{event.provider} · {event.status.replaceAll("_", " ")}</small></div></article>)}</div>
      </section>
      <section className="source-evidence-section">
        <div className="section-heading compact-heading"><span className="mono-kicker">03 / CANDIDATE SOURCES</span><h2>{locale === "zh" ? "候选来源保持轻量可读。" : "Candidate sources, kept lightweight."}</h2><p>{locale === "zh" ? "不增加第二个搜索框；使用全站搜索发现具体来源。" : "No second search box; use global search to discover a specific source."}</p></div>
        <div className="source-candidate-list">{sourceCandidates.map((source) => <article key={source.id}><div><span>{familyLabels[source.family]?.[locale] || source.family}</span><strong>{source.name}</strong><small>{source.region} · {source.access.replaceAll("_", " ")}</small></div><p>{source.materials}</p><div><span>{source.stage.replaceAll("_", " ")}</span><small>{source.rights.replaceAll("_", " ")}</small></div><a href={source.officialUrl} target="_blank" rel="noreferrer" aria-label={`${source.name} official source`}><ArrowSquareOut /></a></article>)}</div>
      </section>
      <section className="source-evidence-section source-roadmap-section">
        <div className="section-heading compact-heading"><span className="mono-kicker">04 / INTEGRATION ROADMAP</span><h2>{locale === "zh" ? "按证据门槛，而不是接口数量推进。" : "Progress by evidence gates, not interface count."}</h2></div>
        <div className="source-roadmap-grid">{roadmapPhases.map((phase) => <article key={phase.id}><span>{phase.id} · {phase.horizon[locale]}</span><h3>{phase.title[locale]}</h3><ol>{phase.gates.map((gate) => <li key={gate}>{gate}</li>)}</ol></article>)}</div>
        <p className="source-roadmap-boundary"><ShieldCheck weight="duotone" />{locale === "zh" ? "只有明确再分发权、provider-native 验证、正式 receipt 与认证 API 回读都成立的数据，才可能进入可售范围。" : "Only data with clear redistribution rights, provider-native validation, formal receipts, and authenticated API readback may enter a sellable scope."}</p>
      </section>
    </section>
  );
}

export function App() {
  const [locale, setLocale] = useState(() => localStorage.getItem("td-locale") || getSystemLocale());
  const [themeChoice, setThemeChoice] = useState(() => localStorage.getItem("td-theme") || "system");
  const [theme, setTheme] = useState(() => themeChoice === "system" ? getSystemTheme() : themeChoice);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [route, setRoute] = useState(getRouteFromPath);
  const [routeSearch, setRouteSearch] = useState(() => window.location.search);
  const [accountSection, setAccountSection] = useState("overview");
  const [accountDocSlug, setAccountDocSlug] = useState("start-1");
  const [bookmarks, setBookmarks] = useState(() => {
    try { return JSON.parse(localStorage.getItem("td-bookmarks") || "[]"); } catch { return []; }
  });
  const [globalQuery, setGlobalQuery] = useState("");
  const [globalSearchOpen, setGlobalSearchOpen] = useState(false);
  const [activeSearchIndex, setActiveSearchIndex] = useState(-1);
  const [expandedSearchGroups, setExpandedSearchGroups] = useState([]);
  const [recentSearches, setRecentSearches] = useState(() => {
    try { return JSON.parse(localStorage.getItem("td-recent-searches") || "[]"); } catch { return []; }
  });
  const [researchTopic, setResearchTopic] = useState("all");
  const [researchKind, setResearchKind] = useState("all");
  const [researchBrowseOpen, setResearchBrowseOpen] = useState(false);
  const researchLibraryRef = useRef(null);
  const desktopSearchInputRef = useRef(null);
  const mobileSearchInputRef = useRef(null);
  const [dataFamily, setDataFamily] = useState("all");
  const [dataStage, setDataStage] = useState("all");
  const [docsCategory, setDocsCategory] = useState("all");
  const [pricingPlanIndex, setPricingPlanIndex] = useState(() => Math.max(0, getBasePlanCards("en").findIndex((plan) => plan.id === readPreviewSelection(window.location.search)?.plan.id)));
  const [pricingBillingPeriod, setPricingBillingPeriod] = useState(() => readPreviewSelection(window.location.search)?.period || "monthly");
  const [accountConnectionRevision, setAccountConnectionRevision] = useState(0);
  const [accountTokenInput, setAccountTokenInput] = useState("");
  const [accountData, setAccountData] = useState(null);
  const [accountUsage, setAccountUsage] = useState(null);
  const [accountKeys, setAccountKeys] = useState([]);
  const [accountKeysLoading, setAccountKeysLoading] = useState(false);
  const [accountKeyLabel, setAccountKeyLabel] = useState("");
  const [accountNewKey, setAccountNewKey] = useState("");
  const [accountKeyLoading, setAccountKeyLoading] = useState(false);
  const [accountKeyError, setAccountKeyError] = useState("");
  const [accountLoading, setAccountLoading] = useState(true);
  const [accountUsageError, setAccountUsageError] = useState(false);
  const [accountLoginPending, setAccountLoginPending] = useState(false);
  const [accountError, setAccountError] = useState("");
  const [accountSignOutPending, setAccountSignOutPending] = useState(false);
  const [accountSignOutError, setAccountSignOutError] = useState(false);
  const accountSignOutInFlight = useRef(false);
  const accountLoginInFlight = useRef(false);
  const accountKeyInFlight = useRef(false);
  const accountEpoch = useRef(0);
  const accountReadAbort = useRef(null);
  const accountViewState = getAccountViewState({ loading: accountLoading, account: accountData, error: accountError });
  const accountChecking = accountViewState === "checking";
  const accountPrivateSection = ["overview", "subscription", "usage", "keys", "security", "billing"].includes(accountSection);
  const accountEntryLabel = accountChecking ? (locale === "zh" ? "正在验证账户…" : "Checking account…") : accountViewState === "unavailable" ? (locale === "zh" ? "重试账户连接" : "Retry account connection") : accountData ? (locale === "zh" ? "账户已连接" : "Account connected") : (locale === "zh" ? "登录账户" : "Sign in");
  const copy = messages[locale];

  function clearAccountView() {
    accountEpoch.current += 1;
    accountReadAbort.current?.abort();
    setAccountData(null);
    setAccountUsage(null);
    setAccountKeys([]);
    setAccountKeysLoading(false);
    setAccountNewKey("");
    setAccountKeyLabel("");
    setAccountKeyError("");
    setAccountUsageError(false);
    setAccountKeyLoading(false);
    setAccountLoading(false);
  }

  useEffect(() => {
    clearLegacyAccountToken();
    const controller = new AbortController();
    accountReadAbort.current = controller;
    const epoch = accountEpoch.current;
    const current = () => !controller.signal.aborted && accountEpoch.current === epoch;
    setAccountLoading(true);
    setAccountError("");
    setAccountUsageError(false);
    readAccountIdentity({ signal: controller.signal }).then(async (account) => {
      if (!current()) return;
      setAccountData(account);
      setAccountLoading(false);
      if (account.identity_kind === "email") { setAccountUsage(null); return; }
      // Usage availability is not an identity check. Never log out on a 5xx here.
      try {
        const usage = await accountJson("usage?days=30", { signal: controller.signal });
        if (!usage?.portal_usage || !Array.isArray(usage.portal_usage.history)) throw new Error("usage_unavailable");
        if (current()) setAccountUsage(usage.portal_usage);
      } catch (error) {
        if (!current()) return;
        if (error.message === "signed_out") { clearAccountView(); return; }
        setAccountUsage(null);
        setAccountUsageError(true);
      }
    }).catch((error) => {
      if (!current()) return;
      clearAccountView();
      setAccountError(error.message === "signed_out" ? "" : error.message);
    }).finally(() => {
      if (current()) setAccountLoading(false);
    });
    return () => controller.abort();
  }, [accountConnectionRevision]);

  useEffect(() => {
    if (!accountData || accountData.identity_kind === "email") return undefined;
    const controller = new AbortController();
    const epoch = accountEpoch.current;
    const current = () => !controller.signal.aborted && accountEpoch.current === epoch;
    setAccountKeyError("");
    setAccountKeys([]);
    setAccountKeysLoading(true);
    accountJson("keys", {
      signal: controller.signal,
    }).then((payload) => {
      if (current()) setAccountKeys(payload.api_keys || []);
    }).catch((error) => {
      if (!current()) return;
      if (error.message === "signed_out") clearAccountView();
      else setAccountKeyError(error.message);
    }).finally(() => { if (current()) setAccountKeysLoading(false); });
    return () => controller.abort();
  }, [accountData]);

  useEffect(() => {
    if (accountSection !== "keys") setAccountNewKey("");
  }, [accountSection]);

  useEffect(() => {
    if (route !== "login") setAccountTokenInput("");
  }, [route]);

  useEffect(() => {
    // Recheck after returning to the page, without a background polling loop.
    const refresh = () => {
      if (document.visibilityState !== "visible" || accountLoginInFlight.current || accountSignOutInFlight.current || accountKeyInFlight.current) return;
      setAccountConnectionRevision((value) => value + 1);
    };
    document.addEventListener("visibilitychange", refresh);
    return () => document.removeEventListener("visibilitychange", refresh);
  }, []);

  useEffect(() => {
    if (accountViewState !== "authenticated" || route !== "login") return;
    setAccountTokenInput("");
    const destination = safeLoginDestination(routeSearch);
    window.history.replaceState({}, "", destination);
    setRoute(getRouteFromPath());
    setRouteSearch(window.location.search);
  }, [accountViewState, route, routeSearch]);

  async function connectAccount(event) {
    event.preventDefault();
    const token = accountTokenInput.trim();
    if (!token || accountLoginInFlight.current || accountSignOutInFlight.current || accountLoading) return;
    accountLoginInFlight.current = true;
    accountReadAbort.current?.abort();
    const epoch = ++accountEpoch.current;
    setAccountLoginPending(true);
    setAccountLoading(true);
    setAccountError("");
    try {
      const account = await startAccountSession(token);
      if (accountEpoch.current !== epoch) return;
      clearLegacyAccountToken();
      setAccountData(account);
      setAccountTokenInput("");
      setAccountConnectionRevision((value) => value + 1);
    } catch (error) {
      if (accountEpoch.current === epoch) setAccountError(error.message);
    } finally {
      accountLoginInFlight.current = false;
      setAccountLoginPending(false);
      setAccountLoading(false);
    }
  }

  async function disconnectAccount() {
    if (accountSignOutInFlight.current) return;
    accountSignOutInFlight.current = true;
    setAccountSignOutPending(true);
    setAccountSignOutError(false);
    try {
      await confirmAccountSignOut();
      clearLegacyAccountToken();
      clearAccountView();
      setAccountError("");
      // Abort older Account reads before they can restore a signed-out UI.
      setAccountConnectionRevision((value) => value + 1);
    } catch {
      setAccountSignOutError(true);
    } finally {
      accountSignOutInFlight.current = false;
      setAccountSignOutPending(false);
    }
  }

  async function connectEmailAccount(payload) {
    if (accountLoginInFlight.current || accountSignOutInFlight.current) throw new Error("account_unavailable");
    accountLoginInFlight.current = true;
    accountReadAbort.current?.abort();
    const epoch = ++accountEpoch.current;
    setAccountLoginPending(true); setAccountLoading(true); setAccountError("");
    try {
      const account = await startEmailSession(payload);
      if (accountEpoch.current !== epoch) return;
      clearLegacyAccountToken(); setAccountTokenInput(""); setAccountData(account);
      setAccountUsage(null); setAccountKeys([]); setAccountNewKey("");
      setAccountConnectionRevision(value => value + 1);
    } finally {
      accountLoginInFlight.current = false;
      setAccountLoginPending(false); setAccountLoading(false);
    }
  }

  async function createAccountKey(event) {
    event.preventDefault();
    const label = accountKeyLabel.trim();
    if (!label || !accountData || accountSignOutInFlight.current || accountKeyInFlight.current) return;
    accountKeyInFlight.current = true;
    const epoch = accountEpoch.current;
    setAccountKeyLoading(true);
    setAccountKeyError("");
    setAccountNewKey("");
    try {
      const payload = await accountJson("keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label }),
      });
      if (accountEpoch.current !== epoch) return;
      setAccountKeys((current) => [...current, payload.api_key]);
      setAccountNewKey(payload.key);
      setAccountKeyLabel("");
    } catch (error) {
      if (accountEpoch.current !== epoch) return;
      if (error.message === "signed_out") clearAccountView();
      else setAccountKeyError(error.message);
    } finally {
      accountKeyInFlight.current = false;
      if (accountEpoch.current === epoch) setAccountKeyLoading(false);
    }
  }

  async function disableAccountKey(key) {
    if (!accountData || accountSignOutInFlight.current || accountKeyInFlight.current || key.is_current || !window.confirm(locale === "zh" ? `停用“${key.label}”？已使用它的 Agent 将立即失去访问。` : `Disable “${key.label}”? Agents using it will immediately lose access.`)) return;
    accountKeyInFlight.current = true;
    const epoch = accountEpoch.current;
    setAccountKeyLoading(true);
    setAccountKeyError("");
    try {
      const payload = await accountJson(`keys/${key.key_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: false }),
      });
      if (accountEpoch.current !== epoch) return;
      setAccountKeys((current) => current.map((item) => item.key_id === key.key_id ? payload.api_key : item));
    } catch (error) {
      if (accountEpoch.current !== epoch) return;
      if (error.message === "signed_out") clearAccountView();
      else setAccountKeyError(error.message);
    } finally {
      accountKeyInFlight.current = false;
      if (accountEpoch.current === epoch) setAccountKeyLoading(false);
    }
  }

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const sync = () => setTheme(themeChoice === "system" ? (media.matches ? "dark" : "light") : themeChoice);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, [themeChoice]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
  }, [theme, locale]);

  useEffect(() => {
    localStorage.setItem("td-bookmarks", JSON.stringify(bookmarks));
  }, [bookmarks]);

  useEffect(() => {
    localStorage.setItem("td-recent-searches", JSON.stringify(recentSearches));
  }, [recentSearches]);

  useEffect(() => {
    setExpandedSearchGroups([]);
  }, [globalQuery]);

  useEffect(() => {
    const syncRoute = () => { setRoute(getRouteFromPath()); setRouteSearch(window.location.search); };
    window.addEventListener("popstate", syncRoute);
    return () => window.removeEventListener("popstate", syncRoute);
  }, []);

  useEffect(() => {
    if (route !== "pricing") return;
    const selection = readPreviewSelection(routeSearch);
    if (!selection) return;
    setPricingPlanIndex(getBasePlanCards("en").findIndex((plan) => plan.id === selection.plan.id));
    setPricingBillingPeriod(selection.period);
  }, [route, routeSearch]);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [route]);

  useEffect(() => {
    const focusGlobalSearch = (event) => {
      if (!isGlobalSearchShortcut(event)) return;
      event.preventDefault();
      setGlobalSearchOpen(true);
      if (window.matchMedia("(max-width: 1020px)").matches) {
        setMobileOpen(true);
        window.setTimeout(() => mobileSearchInputRef.current?.focus(), 0);
      } else {
        desktopSearchInputRef.current?.focus();
      }
    };
    document.addEventListener("keydown", focusGlobalSearch);
    return () => document.removeEventListener("keydown", focusGlobalSearch);
  }, []);

  function chooseLocale(next) {
    setLocale(next);
    localStorage.setItem("td-locale", next);
  }

  function chooseTheme(next) {
    setThemeChoice(next);
    localStorage.setItem("td-theme", next);
  }

  const primaryRoute = route.split("/")[0];
  const routeSlug = route.split("/").slice(1).join("/");
  const sections = ["data", "research", "pricing"];
  const navPaths = sections.map((section) => `/${section}`);
  function goTo(path) {
    window.history.pushState({}, "", path);
    const pathname = new URL(path, window.location.origin).pathname;
    setRoute(pathname === "/" ? "home" : pathname.replace(/^\/+|\/+$/g, ""));
    setRouteSearch(window.location.search);
    setMobileOpen(false);
    setAccountMenuOpen(false);
  }
  function navigate(event, path) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    goTo(path);
  }
  function openAccountSection(key) {
    setAccountSection(key);
    goTo("/account");
  }
  function toggleBookmark(key) {
    setBookmarks((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key]);
  }
  const topicLabels = Object.fromEntries(copy.researchTopics);
  const kindLabels = Object.fromEntries(copy.researchKinds);
  const visiblePapers = papers.filter((paper) => {
    const matchesTopic = researchTopic === "all" || paper.topic === researchTopic;
    const matchesKind = researchKind === "all" || paper.kind === researchKind;
    return matchesTopic && matchesKind;
  });
  const featuredPaper = papers.find((paper) => paper.title === "China's Stock Market: A Marriage of Capitalism and State Control");
  const researchAtlas = locale === "zh" ? {
    eyebrow: "研究地图",
    title: "问题驱动的研究地图。",
    copy: "从问题开始，把它连接到外部研究、原始数据材料和准备方法。你不必先读完一篇论文，才能找到正确的研究起点。",
    search: "输入你想理解的研究问题",
    suggestions: [
      { label: "财务数据如何避免未来信息？", topic: "corporate-fundamentals" },
      { label: "价格、成交量与流动性如何关联？", topic: "market-microstructure" },
      { label: "公告应按哪个时点进入研究？", topic: "alternative-data" },
    ],
    pathsTitle: "精选研究路径",
    pathsCopy: "三个经过整理的起点，把问题连接到论文和所需的数据材料。",
    browse: "浏览完整研究库",
    paths: [
      { label: "时点一致财务", question: "财务数据如何避免未来信息？", time: "42 分钟", count: "4 篇资料", data: "财务报表 · 公告时点 · 修订记录", image: "/assets/research/path-pit-fundamentals-cover-v2.png", imageLight: "/assets/research/path-pit-fundamentals-cover-light-v3.png", paperTitle: "The Cross-Section of Expected Stock Returns" },
      { label: "A 股微观结构", question: "价格、成交量与流动性如何关联？", time: "36 分钟", count: "3 篇资料", data: "日线与分钟 · 成交量 · 集合竞价", image: "/assets/research/path-market-microstructure-cover-v2.png", imageLight: "/assets/research/path-market-microstructure-cover-light-v3.png", paperTitle: "Continuous Auctions and Insider Trading" },
      { label: "公告与事件", question: "公告应按哪个时点进入研究？", time: "31 分钟", count: "3 篇资料", data: "公告 · 新闻 · 公司事件 · 价格", image: "/assets/research/path-announcement-events-cover-v2.png", imageLight: "/assets/research/path-announcement-events-cover-light-v3.png", paperTitle: "Media Coverage and the Cross-section of Stock Returns" },
    ],
    featured: "推荐阅读",
    featuredCopy: "一篇值得先花十分钟理解的高信息密度资料。",
    why: "为什么值得读",
    whyCopy: "这篇论文从所有权、制度结构和市场演进理解中国股票市场，为后续研究数据的范围、可得性和市场语境提供基础。",
    linked: "关联到 TradingDatas",
    overview: "10 分钟导读",
    notStarted: "尚未开始",
    external: "外部文献 · TradingDatas 不发表其中的研究结论",
  } : {
    eyebrow: "RESEARCH ATLAS",
    title: "Question-led research atlas.",
    copy: "Start with the question. We map it to external research, raw data materials, and preparation methods—so you can find the right entry point before reading every paper.",
    search: "Ask a research question",
    suggestions: [
      { label: "How do fundamentals avoid look-ahead?", topic: "corporate-fundamentals" },
      { label: "How do price, volume, and liquidity interact?", topic: "market-microstructure" },
      { label: "When should an announcement enter a study?", topic: "alternative-data" },
    ],
    pathsTitle: "Curated research paths",
    pathsCopy: "Three prepared starting points connect a question to papers and the raw data that matter.",
    browse: "Browse the full library",
    paths: [
      { label: "POINT-IN-TIME FUNDAMENTALS", question: "How do fundamentals avoid look-ahead?", time: "42 min", count: "4 readings", data: "financials · announcement time · revisions", image: "/assets/research/path-pit-fundamentals-cover-v2.png", imageLight: "/assets/research/path-pit-fundamentals-cover-light-v3.png", paperTitle: "The Cross-Section of Expected Stock Returns" },
      { label: "A-SHARE MICROSTRUCTURE", question: "How do price, volume, and liquidity interact?", time: "36 min", count: "3 readings", data: "daily & minute · volume · auctions", image: "/assets/research/path-market-microstructure-cover-v2.png", imageLight: "/assets/research/path-market-microstructure-cover-light-v3.png", paperTitle: "Continuous Auctions and Insider Trading" },
      { label: "ANNOUNCEMENTS & EVENTS", question: "When should an announcement enter a study?", time: "31 min", count: "3 readings", data: "announcements · news · events · prices", image: "/assets/research/path-announcement-events-cover-v2.png", imageLight: "/assets/research/path-announcement-events-cover-light-v3.png", paperTitle: "Media Coverage and the Cross-section of Stock Returns" },
    ],
    featured: "Featured paper",
    featuredCopy: "One high-signal paper worth ten minutes of orientation.",
    why: "Why it matters",
    whyCopy: "This paper uses ownership, institutions, and market development to frame China's stock market—useful context for data scope, availability, and interpretation.",
    linked: "Linked in TradingDatas",
    overview: "10 min overview",
    notStarted: "Not started",
    external: "External literature · TradingDatas does not publish the conclusions",
  };

  function showResearchLibrary({ topic = researchTopic } = {}) {
    setResearchTopic(topic);
    setResearchBrowseOpen(true);
    window.setTimeout(() => researchLibraryRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 30);
  }
  const accountGroups = locale === "zh" ? [
    { label: "你的资料库", items: [{ key: "bookmarks", label: "已收藏", description: "集中查看保存的数据产品、研究内容、方法和文档。" }] },
    { label: "账户", items: [{ key: "overview", label: "账户概览", description: "查看订阅、用量、密钥和另类数据状态的统一摘要。" }] },
    { label: "数据访问", items: [
      { key: "subscription", label: "订阅与加购", description: "管理基础套餐、另类数据试用、有效期和续费选择。" },
      { key: "usage", label: "用量与限制", description: "查看每分钟请求上限、请求历史和分类授权。" },
      { key: "keys", label: "API 密钥", description: "创建、停用和轮换用于 catalog/query 的访问密钥。" },
    ] },
    { label: "连接与学习", items: [
      { key: "agents", label: "Agent 与 MCP", description: "为 Claude、Codex、OpenClaw、Hermes 和其它 Agent 生成安全接入说明。" },
      { key: "docs", label: "文档", description: "查阅平台说明、数据合同、API、Agent 接入和账户帮助。" },
    ] },
    { label: "账单", items: [{ key: "billing", label: "账单与发票", description: "查看订单、续费、支付记录和发票资料。" }] },
    { label: "设置", items: [
      { key: "preferences", label: "语言与外观", description: "设置网站语言以及跟随系统、明亮或暗色外观。" },
      { key: "security", label: "安全", description: "管理登录会话、账户安全和访问审计。" },
    ] },
  ] : [
    { label: "Your library", items: [{ key: "bookmarks", label: "Bookmarks", description: "Review saved datasets, research, methods, and documentation in one place." }] },
    { label: "Account", items: [{ key: "overview", label: "Overview", description: "A single summary of subscription, usage, keys, and alternative-data access." }] },
    { label: "Data access", items: [
      { key: "subscription", label: "Subscription & add-ons", description: "Manage base packages, alternative-data trials, expiry, and renewal choices." },
      { key: "usage", label: "Usage & limits", description: "Review per-minute request limits, request history, and category access." },
      { key: "keys", label: "API keys", description: "Create, disable, and rotate credentials for catalog and query." },
    ] },
    { label: "Connect & learn", items: [
      { key: "agents", label: "Agents & MCP", description: "Generate safe setup guidance for Claude, Codex, OpenClaw, Hermes, and other Agents." },
      { key: "docs", label: "Documentation", description: "Browse platform guidance, data contracts, APIs, Agent setup, and account help." },
    ] },
    { label: "Billing", items: [{ key: "billing", label: "Billing & invoices", description: "Review orders, renewals, payment records, and invoice details." }] },
    { label: "Settings", items: [
      { key: "preferences", label: "Language & appearance", description: "Choose the site language and system, light, or dark appearance." },
      { key: "security", label: "Security", description: "Manage sign-in sessions, account security, and access audit." },
    ] },
  ];
  const packageCards = getBasePlanCards(locale);
  const readingSteps = locale === "zh" ? [
    ["01", "先看研究问题", "这篇内容试图解释、测量或重建什么。"],
    ["02", "再看证据与数据", "需要哪些市场、财务、另类数据和时间窗口。"],
    ["03", "理解方法与限制", "识别对齐、样本、假设以及不能外推的部分。"],
    ["04", "进入 Data 与研究方法", "找到对应数据材料和可复现的数据准备方法。"],
  ] : [
    ["01", "Start with the question", "What is the work trying to explain, measure, or reconstruct?"],
    ["02", "Inspect evidence and data", "Which market, fundamental, alternative datasets, and time windows are required?"],
    ["03", "Understand method and limits", "Identify alignment, samples, assumptions, and what cannot be generalized."],
    ["04", "Continue in Data and Methods", "Find the matching raw materials and reproducible preparation method."],
  ];
  const docsCategories = locale === "zh" ? [
    { key: "start", label: "开始使用", items: [["平台概览", "了解 Data、Research、Pricing、全站搜索与 Account 的关系。"], ["首次接入", "创建账户、选择套餐、生成密钥并完成第一条 Catalog 查询。"]] },
    { key: "data", label: "数据说明", items: [["数据分类与模板", "市场、domain、字段、覆盖、更新时间与 receipt 的统一结构。"], ["另类数据", "来源、再分发边界、试用、加购和授权读回。"], ["数据凭证", "如何阅读 source、quality、freshness、coverage 与 receipt。"]] },
    { key: "api", label: "API 与 Agent", items: [["Catalog", "发现已授权数据集及其结构、覆盖与限制。"], ["Query", "字段、游标、预算、错误和 fail-closed 行为。"], ["Agent 与 MCP", "Claude、Codex、OpenClaw、Hermes 的安全接入说明。"]] },
    { key: "learn", label: "学习与方法", items: [["Research 阅读指南", "如何阅读外部论文、行业研究和案例。"], ["研究方法", "查询、连接、时点对齐、复权、缺失与验证。"]] },
    { key: "commerce", label: "套餐与账户", items: [["套餐比较", "相同基础数据，三档请求频率及月付、年付价格；支付尚未开放。"], ["订阅与账单", "有效期、试用、加购、续费、账单和发票。"], ["账户与安全", "用量、密钥、会话、语言、主题与访问审计。"]] },
  ] : [
    { key: "start", label: "Get started", items: [["Platform overview", "How Data, Research, Pricing, site search, and Account fit together."], ["First connection", "Create an account, choose a package, generate a key, and make the first Catalog request."]] },
    { key: "data", label: "Data guide", items: [["Classification & template", "The shared market, domain, field, coverage, update, and receipt structure."], ["Alternative data", "Source, redistribution boundary, trial, add-on, and entitlement readback."], ["Data receipts", "How to read source, quality, freshness, coverage, and receipt evidence."]] },
    { key: "api", label: "API & Agents", items: [["Catalog", "Discover authorized datasets, schemas, coverage, and limitations."], ["Query", "Fields, cursors, budgets, errors, and fail-closed behavior."], ["Agents & MCP", "Safe setup for Claude, Codex, OpenClaw, Hermes, and other Agents."]] },
    { key: "learn", label: "Learning & methods", items: [["Research reading guide", "How to read external papers, industry research, and cases."], ["Research methods", "Querying, joins, point-in-time alignment, adjustment, missingness, and validation."]] },
    { key: "commerce", label: "Plans & account", items: [["Compare packages", "The same base data, three request rates, and monthly/annual prices; checkout is not yet available."], ["Subscription & billing", "Expiry, trials, add-ons, renewal, billing, and invoices."], ["Account & security", "Usage, keys, sessions, language, appearance, and access audit."]] },
  ];
  const allDocs = docsCategories.flatMap((category) => category.items.map(([title, description], index) => ({ category: category.key, categoryLabel: category.label, title, description, slug: `${category.key}-${index + 1}` })));
  const visibleDocs = allDocs.filter((entry) => {
    const matchesCategory = docsCategory === "all" || entry.category === docsCategory;
    return matchesCategory;
  });
  const selectedDoc = allDocs.find((entry) => entry.slug === routeSlug);
  const activeAccountItem = accountGroups.flatMap((group) => group.items).find((item) => item.key === accountSection) || accountGroups[0].items[0];
  const activeAccountDoc = allDocs.find((entry) => entry.slug === accountDocSlug) || allDocs[0];
  const accountPlanLabels = locale === "zh" ? { basic: "基础版", standard: "专业版", flagship: "旗舰版", free: "免费版", starter: "入门版", research: "研究版", pro: "专业版", enterprise: "企业版", internal: "内部账户" } : { basic: "Basic", standard: "Professional", flagship: "Flagship", free: "Free", starter: "Starter", research: "Research", pro: "Pro", enterprise: "Enterprise", internal: "Internal" };
  const accountCategoryLabels = locale === "zh" ? { a_share: "A 股基础数据", crypto: "加密资产", news: "新闻与事件" } : { a_share: "A-share base data", crypto: "Crypto", news: "News & events" };
  const isEmailAccount = accountData?.identity_kind === "email";
  const accountPlanLabel = isEmailAccount ? (locale === "zh" ? "未订阅" : "Not subscribed") : accountData ? (accountPlanLabels[accountData.tier] || accountData.tier) : "";
  const accountCategories = accountData ? (accountData.data_categories || []).map((category) => accountCategoryLabels[category] || category) : [];
  const accountUsageHistory = accountUsage?.history || [];
  const accountUsagePeak = Math.max(1, ...accountUsageHistory.map((entry) => Number(entry.total) || 0));

  const globalIndex = [
    ...productManifest.objects.datasets.map((item) => ({ key: `dataset:${item.id}`, id: item.id, group: "data", type: locale === "zh" ? "数据" : "Data", label: item.title[locale], description: item.description[locale], aliases: [item.title.en, item.title.zh, item.description.en, item.description.zh, item.category.en, item.category.zh, item.family, item.market, item.cadence, item.tags], path: `/datasets/${item.id}` })),
    ...papers.map((paper) => ({ key: `research:${paperSlug(paper)}`, id: paperSlug(paper), group: "research", type: locale === "zh" ? "研究" : "Research", label: paper.title, description: `${paper.authors} · ${paper.year}`, aliases: [paper.venue, paper.kind, paper.topic, paper.data, paper.summary.en, paper.summary.zh], path: `/research/${paperSlug(paper)}` })),
    ...productManifest.objects.recipes.map((item) => ({ key: `method:${item.id}`, id: item.id, group: "methods", type: locale === "zh" ? "研究方法" : "Method", label: item.title[locale], description: item.detail, aliases: [item.title.en, item.title.zh, item.status], path: `/recipes/${item.id}` })),
    ...allDocs.map((entry) => ({ key: `doc:${entry.slug}`, id: entry.slug, group: "docs", type: locale === "zh" ? "文档" : "Docs", label: entry.title, description: entry.description, aliases: [entry.category, entry.categoryLabel], path: "/account", accountSection: "docs", docSlug: entry.slug })),
  ].map((item) => ({ ...item, searchDocument: createSearchDocument([item.id, item.type, item.label, item.description, item.aliases]) }));
  const savedItems = globalIndex.filter((item) => bookmarks.includes(item.key));
  const normalizedGlobalQuery = normalizeSearchValue(globalQuery);
  const globalSearchGroupDefinitions = [
    { key: "data", label: locale === "zh" ? "数据产品" : "DATA" },
    { key: "research", label: locale === "zh" ? "研究" : "RESEARCH" },
    { key: "methods", label: locale === "zh" ? "方法" : "METHODS" },
    { key: "docs", label: locale === "zh" ? "文档" : "DOCS" },
  ];
  const globalSearchGroups = searchGroups(globalIndex, normalizedGlobalQuery, globalSearchGroupDefinitions, Number.POSITIVE_INFINITY)
    .map((group) => ({
      ...group,
      items: expandedSearchGroups.includes(group.key) ? group.items : group.items.slice(0, 4),
    }));
  const globalResults = globalSearchGroups.flatMap((group) => group.items);
  const globalResultCount = globalSearchGroups.reduce((total, group) => total + group.totalCount, 0);
  const accountMenuGroups = locale === "zh" ? [
    { label: "你的资料库", items: [{ key: "bookmarks", label: `已收藏 · ${bookmarks.length}` }] },
    { label: "账户", items: [{ key: "overview", label: "账户概览" }, { key: "subscription", label: "订阅与套餐" }, { key: "preferences", label: "语言与外观" }] },
    { label: "连接与学习", items: [{ key: "agents", label: "Agent 与 MCP" }, { key: "docs", label: "文档" }] },
  ] : [
    { label: "Your library", items: [{ key: "bookmarks", label: `Bookmarks · ${bookmarks.length}` }] },
    { label: "Account", items: [{ key: "overview", label: "Overview" }, { key: "subscription", label: "Access & plan" }, { key: "preferences", label: "Appearance" }] },
    { label: "Connect & learn", items: [{ key: "agents", label: "Agent connections" }, { key: "docs", label: "Documentation" }] },
  ];
  function openSearchItem(event, item) {
    event.preventDefault();
    if (item.accountSection) {
      setAccountSection(item.accountSection);
      if (item.docSlug) setAccountDocSlug(item.docSlug);
    }
    const query = globalQuery.trim();
    if (query) setRecentSearches((current) => [query, ...current.filter((value) => value.toLowerCase() !== query.toLowerCase())].slice(0, 5));
    setGlobalQuery("");
    setGlobalSearchOpen(false);
    setActiveSearchIndex(-1);
    goTo(item.path);
  }

  function renderGlobalSearch(className = "") {
    const placeholder = locale === "zh" ? "搜索数据、研究、方法或文档" : "Search data, research, methods, or docs";
    const searchSuggestions = locale === "zh" ? ["A 股日线", "时点一致财务", "论文"] : ["A-share daily", "Point-in-time fundamentals", "Papers"];
    const isMobileSearch = className.includes("mobile");
    const searchInputRef = isMobileSearch ? mobileSearchInputRef : desktopSearchInputRef;
    const searchShortcut = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘K" : "Ctrl K";
    const resultsId = className.includes("mobile") ? "mobile-global-search-results" : "desktop-global-search-results";
    const activeResultId = activeSearchIndex >= 0 ? `${resultsId}-${activeSearchIndex}` : undefined;
    function handleSearchKeyDown(event) {
      if (event.key === "Escape") {
        setGlobalSearchOpen(false);
        setActiveSearchIndex(-1);
        event.currentTarget.blur();
        return;
      }
      if (!globalResults.length) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setGlobalSearchOpen(true);
        setActiveSearchIndex((current) => getSearchNavigationIndex(current, globalResults.length, event.key));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setGlobalSearchOpen(true);
        setActiveSearchIndex((current) => getSearchNavigationIndex(current, globalResults.length, event.key));
      } else if (event.key === "Home") {
        event.preventDefault();
        setGlobalSearchOpen(true);
        setActiveSearchIndex((current) => getSearchNavigationIndex(current, globalResults.length, event.key));
      } else if (event.key === "End") {
        event.preventDefault();
        setGlobalSearchOpen(true);
        setActiveSearchIndex((current) => getSearchNavigationIndex(current, globalResults.length, event.key));
      } else if (event.key === "Enter" && activeSearchIndex >= 0) {
        event.preventDefault();
        openSearchItem(event, globalResults[activeSearchIndex]);
      }
    }
    return <div className={`global-search-wrap ${className}`} onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setGlobalSearchOpen(false);
    }}>
      <label className="global-search-field">
        <MagnifyingGlass aria-hidden="true" />
        <span className="sr-only">{placeholder}</span>
        <input ref={searchInputRef} type="search" role="combobox" aria-autocomplete="list" aria-expanded={globalSearchOpen && Boolean(normalizedGlobalQuery || recentSearches.length)} aria-controls={resultsId} aria-activedescendant={activeResultId} value={globalQuery} placeholder={placeholder} onFocus={() => setGlobalSearchOpen(true)} onChange={(event) => { setGlobalQuery(event.target.value); setGlobalSearchOpen(true); setActiveSearchIndex(-1); }} onKeyDown={handleSearchKeyDown} />
        {globalQuery ? <button type="button" onClick={() => setGlobalQuery("")} aria-label={locale === "zh" ? "清除搜索" : "Clear search"}><X /></button> : <kbd aria-hidden="true">{searchShortcut}</kbd>}
      </label>
      {globalSearchOpen && normalizedGlobalQuery && <div className="global-search-results" id={resultsId} role={globalSearchGroups.length ? "listbox" : "status"} aria-label={locale === "zh" ? "全站搜索结果" : "Site search results"}>
        <div className="global-search-result-heading"><span>{locale === "zh" ? "搜索结果" : "SEARCH RESULTS"}</span><small aria-live="polite" aria-atomic="true">{globalResultCount}</small></div>
        {globalSearchGroups.length ? globalSearchGroups.map((group) => <section className="global-search-group" key={group.key} aria-label={group.label}>
          <h3>{group.label}</h3>
          {group.items.map((item) => {
            const resultIndex = globalResults.findIndex((result) => result.key === item.key);
            return <div className={`global-search-result ${activeSearchIndex === resultIndex ? "is-active" : ""}`} key={item.key}>
              <a id={`${resultsId}-${resultIndex}`} role="option" aria-selected={activeSearchIndex === resultIndex} href={item.path} onMouseEnter={() => setActiveSearchIndex(resultIndex)} onClick={(event) => openSearchItem(event, item)}><span className="global-search-result-title"><strong>{item.label}</strong>{item.matchKind && <em>{item.matchKind === "id" ? "ID" : item.matchKind === "fuzzy" ? (locale === "zh" ? "近似" : "CLOSE") : (locale === "zh" ? "别名" : "ALIAS")}</em>}</span><small>{item.description}</small></a>
              <button type="button" className={bookmarks.includes(item.key) ? "is-saved" : ""} onClick={() => toggleBookmark(item.key)} aria-label={bookmarks.includes(item.key) ? (locale === "zh" ? "取消收藏" : "Remove bookmark") : (locale === "zh" ? "收藏" : "Bookmark")}><BookmarkSimple weight={bookmarks.includes(item.key) ? "fill" : "regular"} /></button>
            </div>;
          })}
          {group.totalCount > group.items.length && <button className="global-search-expand" type="button" onClick={() => setExpandedSearchGroups((current) => current.includes(group.key) ? current : [...current, group.key])}>{locale === "zh" ? `查看全部 ${group.totalCount}` : `Show all ${group.totalCount}`}<ArrowRight /></button>}
        </section>) : <div className="global-search-empty"><p>{locale === "zh" ? "没有匹配内容。" : "No matching content."}</p><small>{locale === "zh" ? "可以试试" : "TRY"}</small><div>{searchSuggestions.map((suggestion) => <button type="button" key={suggestion} onClick={() => { setGlobalQuery(suggestion); setActiveSearchIndex(-1); }}>{suggestion}</button>)}</div></div>}
      </div>}
      {globalSearchOpen && !normalizedGlobalQuery && recentSearches.length > 0 && <div className="global-search-results global-search-recents" id={resultsId}>
        <div className="global-search-result-heading"><span>{locale === "zh" ? "最近搜索 · 仅此浏览器" : "RECENT · THIS BROWSER"}</span><button type="button" onClick={() => setRecentSearches([])}>{locale === "zh" ? "清除" : "Clear"}</button></div>
        {recentSearches.map((query) => <div className="global-recent-row" key={query}><button className="global-recent-query" type="button" onClick={() => { setGlobalQuery(query); setActiveSearchIndex(-1); }}><Clock /><span>{query}</span><ArrowRight /></button><button className="global-recent-remove" type="button" onClick={() => setRecentSearches((current) => current.filter((value) => value !== query))} aria-label={locale === "zh" ? `删除最近搜索：${query}` : `Remove recent search: ${query}`}><X /></button></div>)}
      </div>}
    </div>;
  }

  const selectedDataset = productManifest.objects.datasets.find((item) => item.id === routeSlug);
  const selectedFeature = productManifest.objects.features.find((item) => item.id === routeSlug);
  const selectedRecipe = productManifest.objects.recipes.find((item) => item.id === routeSlug);
  const selectedPaper = routeSlug ? papers.find((paper) => paper.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") === routeSlug) : null;
  const dataCategories = locale === "zh" ? [
    { family: "market", label: "行情", description: "价格、交易状态与市场基础参考" },
    { family: "fundamentals", label: "公司与财务", description: "公司身份、财务披露与所有权结构" },
    { family: "events", label: "事件", description: "公告、公司行动与上市里程碑" },
    { family: "funds", label: "指数与基金", description: "指数、ETF、基金与可转债" },
    { family: "macro", label: "宏观与利率", description: "宏观发布、利率、央行与商品" },
    { family: "text", label: "新闻与文本", description: "新闻、政策、研报与版本化文档" },
    { family: "alternative", label: "另类数据", description: "活动、关注、供应链与地理观测" },
    { family: "global", label: "全球市场", description: "香港、美国与全球宏观候选" },
    { family: "crypto", label: "加密资产", description: "隔离的公共只读市场数据" },
  ] : [
    { family: "market", label: "Markets", description: "Prices, trading states, and market reference" },
    { family: "fundamentals", label: "Companies", description: "Identity, disclosures, and ownership" },
    { family: "events", label: "Events", description: "Announcements, actions, and listing milestones" },
    { family: "funds", label: "Indices & funds", description: "Indices, ETFs, funds, and convertibles" },
    { family: "macro", label: "Macro & rates", description: "Releases, rates, central banks, and commodities" },
    { family: "text", label: "News & text", description: "News, policy, research, and versioned documents" },
    { family: "alternative", label: "Alternative", description: "Activity, attention, supply chain, and geospatial data" },
    { family: "global", label: "Global markets", description: "Hong Kong, US, and global macro candidates" },
    { family: "crypto", label: "Crypto", description: "Isolated public read-only market data" },
  ];
  const visibleDataProducts = productManifest.objects.datasets.filter((item) => {
    const matchesFamily = dataFamily === "all" || item.family === dataFamily;
    const matchesStage = dataStage === "all" || item.status === dataStage;
    return matchesFamily && matchesStage;
  });
  const dataStageCounts = productManifest.objects.datasets.reduce((counts, item) => ({ ...counts, [item.status]: (counts[item.status] || 0) + 1 }), { all: productManifest.objects.datasets.length });
  const showDataDirectory = dataFamily === "all" && dataStage === "all";
  const activeDataCategory = dataCategories.find((category) => category.family === dataFamily);
  const dataResultTitle = activeDataCategory?.label || (dataStage === "observed_example" ? (locale === "zh" ? "已观测" : "Observed") : dataStage === "pending_open" ? (locale === "zh" ? "待开放" : "Pending release") : (locale === "zh" ? "规划中" : "Planned"));

  return (
    <div className={`site-shell route-${primaryRoute}`} id="top">
      <header className={`global-header ${primaryRoute === "home" ? "" : "is-page-header"}`}>
        <Brand onNavigate={navigate} />
        <nav className="desktop-nav" aria-label="Primary navigation">
          {copy.nav.map((label, index) => <a key={label} href={navPaths[index]} onClick={(event) => navigate(event, navPaths[index])} aria-current={primaryRoute === sections[index] ? "page" : undefined}>{label}</a>)}
        </nav>
        {renderGlobalSearch("desktop-global-search")}
        <div className="header-actions">
          <button className="icon-button bookmark-header-button" type="button" aria-label={locale === "zh" ? `已收藏 ${bookmarks.length} 项` : `${bookmarks.length} bookmarks`} onClick={() => openAccountSection("bookmarks")}><BookmarkSimple size={23} weight={bookmarks.length ? "fill" : "regular"} />{bookmarks.length > 0 && <span>{bookmarks.length}</span>}</button>
          <div className="popover-wrap account-wrap">
            <button className="icon-button account-button" type="button" disabled={accountChecking} aria-busy={accountChecking} aria-label={accountChecking ? accountEntryLabel : accountData ? copy.account : accountViewState === "unavailable" ? copy.account : (locale === "zh" ? "登录账户" : "Sign in")} aria-expanded={accountData && !accountChecking ? accountMenuOpen : false} onClick={() => accountData ? setAccountMenuOpen((value) => !value) : goTo(accountViewState === "unavailable" ? "/account" : "/login")}><UserCircle size={30} weight="thin" /></button>
            {accountMenuOpen && accountData && !accountChecking && <div className="account-menu-popover">
              <div className="account-menu-identity"><span>{accountData ? String(accountData.tenant_id || "TD").slice(0, 2).toUpperCase() : "TD"}</span><div><strong>{accountData ? (accountData.email || accountData.tenant_id) : "TradingDatas"}</strong><small>{accountData ? (locale === "zh" ? `${accountPlanLabel} · 已登录` : `${accountPlanLabel} · signed in`) : (locale === "zh" ? "账户尚未连接" : "Account not connected")}</small></div></div>
              {accountMenuGroups.map((group) => <section key={group.label}><span>{group.label}</span>{group.items.map((item) => <button key={item.key} type="button" onClick={() => openAccountSection(item.key)}>{item.label}<ArrowRight /></button>)}</section>)}
            </div>}
          </div>
          <button className="icon-button mobile-menu-button" type="button" aria-label={copy.menu} onClick={() => setMobileOpen((value) => !value)}>{mobileOpen ? <X size={24} /> : <List size={24} />}</button>
        </div>
        {mobileOpen && <nav className="mobile-nav" aria-label="Mobile navigation">{renderGlobalSearch("mobile-global-search")}{copy.nav.map((label, index) => <a key={label} href={navPaths[index]} onClick={(event) => navigate(event, navPaths[index])}>{label}<ArrowRight /></a>)}</nav>}
      </header>

      <main>
        {primaryRoute === "home" && <section className="hero" aria-labelledby="hero-title">
          <picture className="hero-art" aria-hidden="true">
            <img src={theme === "dark" ? "/assets/data-material-dark.png" : "/assets/data-material-light.png"} alt="" />
          </picture>
          <div className="hero-copy">
            <h1 id="hero-title">{copy.title.split("\n").map((line) => <span key={line}>{line}</span>)}</h1>
            <p>{copy.subtitle}</p>
            <div className="hero-actions">
              <a className="primary-button" href="/data" onClick={(event) => navigate(event, "/data")}>{locale === "zh" ? "探索 A 股数据" : "Explore A-share data"}<ArrowRight /></a>
              <button className="secondary-action" type="button" onClick={() => setAgentOpen(true)}>{copy.connect}</button>
            </div>
          </div>
          <div className="hero-verification mono-text" aria-hidden="true">
            <span>2026-08-26T18:04:00Z</span>
            <span>batch_7f9c2a1e</span>
          </div>
          <div className="hero-hash mono-text" aria-hidden="true">
            <span>rcpt_9f3b7e21...14c8d2a7</span>
            <span>sha256:2b7e1516...a1f4c3d9</span>
          </div>
          <div className="hero-trust-teaser">
            <h2>{copy.receipts}</h2>
            <p>{copy.receiptsCopy}</p>
          </div>
        </section>}

        {primaryRoute === "data" && !routeSlug && <main className="data-catalog-page" id="data">
          <section className="data-catalog-intro">
            <h1>{locale === "zh" ? "找到你需要的数据。" : "Find the data you need."}</h1>
            <p>{locale === "zh" ? "可追溯的数据产品，为研究与生产系统准备。" : "Traceable data products, packaged for research and production."}</p>
            <div className="data-family-filters" aria-label={locale === "zh" ? "数据分类" : "Data categories"}>
              {(locale === "zh" ? [["all", "全部"], ["market", "行情"], ["fundamentals", "公司与财务"], ["events", "事件"], ["funds", "指数与基金"], ["macro", "宏观与利率"], ["text", "新闻与文本"], ["alternative", "另类数据"], ["global", "全球市场"], ["crypto", "加密资产"]] : [["all", "All"], ["market", "Markets"], ["fundamentals", "Companies"], ["events", "Events"], ["funds", "Indices & funds"], ["macro", "Macro & rates"], ["text", "News & text"], ["alternative", "Alternative"], ["global", "Global markets"], ["crypto", "Crypto"]]).map(([value, label]) => <button key={value} type="button" className={dataFamily === value ? "is-active" : ""} onClick={() => setDataFamily(value)}>{label}</button>)}
              <span>{locale === "zh" ? "先按分类发现 · 再进入具体数据产品" : "Discover by category · open individual data products"}</span>
            </div>
            <div className="data-stage-filters" aria-label={locale === "zh" ? "接入状态" : "Onboarding stage"}>
              <span>{locale === "zh" ? "状态" : "Stage"}</span>
              {(locale === "zh" ? [["all", "全部"], ["observed_example", "已观测"], ["planned", "规划中"], ["pending_open", "待开放"]] : [["all", "All"], ["observed_example", "Observed"], ["planned", "Planned"], ["pending_open", "Pending release"]]).map(([value, label]) => <button key={value} type="button" className={dataStage === value ? "is-active" : ""} onClick={() => setDataStage(value)}><span>{label}</span><small>{dataStageCounts[value] || 0}</small></button>)}
            </div>
          </section>

          {showDataDirectory ? <section className="data-category-directory" aria-label={locale === "zh" ? "数据分类目录" : "Data category directory"}>
            <div className="data-directory-summary"><span>{locale === "zh" ? "9 个分类 · 41 个数据产品" : "9 categories · 41 data products"}</span><span>{locale === "zh" ? "选择分类后查看完整产品与接入计划" : "Choose a category for complete products and onboarding plans"}</span></div>
            {dataCategories.map((category, categoryIndex) => {
              const products = productManifest.objects.datasets.filter((item) => item.family === category.family);
              return <article className="data-category-shelf" key={category.family}>
                <header>
                  <span>{String(categoryIndex + 1).padStart(2, "0")}</span>
                  <h2>{category.label}</h2>
                  <p>{category.description}</p>
                  <button type="button" onClick={() => setDataFamily(category.family)}>{locale === "zh" ? `查看全部 ${products.length} 个` : `View all ${products.length}`}<ArrowRight /></button>
                </header>
                <div className="data-shelf-products">
                  {products.slice(0, 4).map((item) => <a key={item.id} href={`/datasets/${item.id}`} onClick={(event) => navigate(event, `/datasets/${item.id}`)}>
                    <ProductMark item={item} compact />
                    <div><h3>{item.title[locale]}</h3><p>{item.description[locale]}</p><MaturityTag status={item.status} locale={locale} /></div>
                    <ArrowRight />
                  </a>)}
                </div>
              </article>;
            })}
          </section> : <>
            <div className="data-result-context">
              <div><span>{locale === "zh" ? "当前视图" : "CURRENT VIEW"}</span><h2>{dataResultTitle}</h2><p>{locale === "zh" ? `${visibleDataProducts.length} 个数据产品` : `${visibleDataProducts.length} data products`}</p></div>
              <button type="button" onClick={() => { setDataFamily("all"); setDataStage("all"); }}>{locale === "zh" ? "返回分类目录" : "Back to categories"}</button>
            </div>
            <section className="data-product-list" aria-live="polite">
              {visibleDataProducts.map((item) => {
                const hasCollectionHistory = item.stability !== "—";
                return <article className={`data-product-row ${hasCollectionHistory ? "" : "is-unobserved"}`} key={item.id}>
                <ProductMark item={item} />
                <div className="data-product-copy">
                  <div><span className="product-category-label">{item.category[locale]}</span><h2>{item.title[locale]}</h2><p>{item.description[locale]}</p></div>
                  <div className="dataset-tags">{item.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
                </div>
                {hasCollectionHistory ? <>
                  <StabilityTrack item={item} locale={locale} compact />
                  <dl className="data-product-meta">
                    <div><dt>{locale === "zh" ? "最近成功" : "Last success"}</dt><dd>{item.lastSuccess}</dd></div>
                    <div><dt>{locale === "zh" ? "频率" : "Cadence"}</dt><dd>{item.cadence}</dd></div>
                    <div><dt>{locale === "zh" ? "覆盖" : "Coverage"}</dt><dd>{item.coverage}</dd></div>
                    <div><dt>{locale === "zh" ? "接入计划" : "Onboarding plan"}</dt><dd>{item.plan}</dd></div>
                  </dl>
                </> : <div className="data-product-readiness">
                  <div className="collection-readiness"><MaturityTag status={item.status} locale={locale} /><StabilityTrack item={item} locale={locale} compact showStage={false} /></div>
                  <dl>
                    <div><dt>{locale === "zh" ? "频率" : "Cadence"}</dt><dd>{item.cadence}</dd></div>
                    <div><dt>{locale === "zh" ? "接入" : "Onboarding"}</dt><dd>{item.plan}</dd></div>
                  </dl>
                </div>}
                <a className="data-product-open" href={`/datasets/${item.id}`} onClick={(event) => navigate(event, `/datasets/${item.id}`)}>{locale === "zh" ? "打开产品" : "Open product"}<ArrowRight /></a>
              </article>})}
              {visibleDataProducts.length === 0 && <div className="data-product-empty">{locale === "zh" ? "没有匹配的数据产品。" : "No data products match this search."}</div>}
            </section>
          </>}

          <div className="data-catalog-footer">
            <p>{locale === "zh" ? "产品合同示例 · 真实状态由 Registry、receipts、认证 API 回读与账户授权共同确定。" : "Product-contract examples · live status is determined by the Registry, receipts, authenticated API readback, and account entitlement."}</p>
            <div><a href="/data/sources" onClick={(event) => navigate(event, "/data/sources")}>{locale === "zh" ? "来源与接入计划" : "Sources & roadmap"}<ArrowRight /></a><a href="/data/receipts" onClick={(event) => navigate(event, "/data/receipts")}>{locale === "zh" ? "了解采集凭证" : "How receipts work"}<ArrowRight /></a><a href="/data/alternative" onClick={(event) => navigate(event, "/data/alternative")}>{locale === "zh" ? "浏览另类数据" : "Browse alternative data"}<ArrowRight /></a></div>
          </div>
        </main>}

        {primaryRoute === "datasets" && <ProductObjectDetail type="datasets" item={selectedDataset} locale={locale} onNavigate={navigate} />}

        {primaryRoute === "data" && routeSlug === "sources" && <DataSourceLandscapePage locale={locale} onNavigate={navigate} />}

        {primaryRoute === "data" && routeSlug === "alternative" && <section className="object-detail-page"><SectionNav locale={locale} active="/data/alternative" onNavigate={navigate} items={locale === "zh" ? [{ path: "/data", label: "全部数据" }, { path: "/data/alternative", label: "另类数据" }, { path: "/data/receipts", label: "凭证与覆盖" }] : [{ path: "/data", label: "All data" }, { path: "/data/alternative", label: "Alternative data" }, { path: "/data/receipts", label: "Receipts & coverage" }]} /><div className="object-detail-hero"><div><span className="mono-kicker">ALTERNATIVE DATA / PRODUCT CATEGORY</span><h1>{locale === "zh" ? "另类数据是分类，每一种指数都是独立产品。" : "Alternative data is a category; every index is its own product."}</h1><p>{locale === "zh" ? "从 Pizza 指数到客流、招聘、应用关注、航运、卫星和消费价格，每个产品分别披露来源、许可、覆盖和接入计划。" : "From Pizza Index to foot traffic, hiring, app attention, shipping, satellite, and consumer prices, every product discloses its own source, license, coverage, and onboarding plan."}</p></div><MaturityTag status="planned" locale={locale} /></div><AlternativeProductList locale={locale} onNavigate={navigate} /><section className="object-boundary"><h2>{locale === "zh" ? "购买前必须可见" : "Visible before purchase"}</h2><p>{locale === "zh" ? "来源、许可与再分发边界、样例字段、历史覆盖、更新频率、试用期限、价格、到期与续费选择。" : "Source, license and redistribution boundary, sample fields, history, cadence, trial term, price, expiry, and renewal choice."}</p><a className="primary-button" href="/pricing/alternative" onClick={(event) => navigate(event, "/pricing/alternative")}>{locale === "zh" ? "查看加购逻辑" : "Review add-on logic"}<ArrowRight /></a></section></section>}

        {primaryRoute === "data" && routeSlug === "receipts" && <section className="object-detail-page"><SectionNav locale={locale} active="/data/receipts" onNavigate={navigate} items={locale === "zh" ? [{ path: "/data", label: "全部数据" }, { path: "/data/alternative", label: "另类数据" }, { path: "/data/receipts", label: "凭证与覆盖" }] : [{ path: "/data", label: "All data" }, { path: "/data/alternative", label: "Alternative data" }, { path: "/data/receipts", label: "Receipts & coverage" }]} /><div className="object-detail-hero"><div><span className="mono-kicker">DATA WITH RECEIPTS</span><h1>{locale === "zh" ? "每个可用性声明，都回到证据。" : "Every availability claim returns to evidence."}</h1><p>{locale === "zh" ? "Registry 定义身份，事实与 receipt 记录观测，API 只投影同一权威链。" : "Registry defines identity, facts and receipts record observations, and the API projects the same authority chain."}</p></div><MaturityTag status="observed_example" locale={locale} /></div><ReceiptProof copy={copy} /><section className="object-boundary"><h2>{locale === "zh" ? "Receipt 能证明什么，也不能证明什么" : "What a receipt proves—and what it does not"}</h2><p>{locale === "zh" ? "它证明一次来源绑定的采集、验证与落库事务；单次成功不等于连续健康、历史完整或时点一致。" : "It proves one source-bound collection, validation, and storage transaction. One success is not continuous health, complete history, or point-in-time correctness."}</p></section></section>}

        {primaryRoute === "features" && !routeSlug && <section className="object-index-page">
          <SectionNav locale={locale} active="/features" onNavigate={navigate} items={locale === "zh" ? [{ path: "/features", label: "特征目录" }, { path: "/features/methodology", label: "方法与版本" }] : [{ path: "/features", label: "Feature index" }, { path: "/features/methodology", label: "Method & versions" }]} />
          <div className="object-index-hero"><span className="mono-kicker">TRANSPARENT FEATURES / TARGET PLANE</span><h1>{locale === "zh" ? "可解释、可复现、可追溯的衍生数据。" : "Derived data that stays explainable, reproducible, and traceable."}</h1><p>{locale === "zh" ? "Feature 公开公式、输入、时点对齐、缺失与修订规则。它不是信号、排名、策略或建议。" : "Every Feature publishes its formula, inputs, as-of alignment, missingness, and revision rules. It is not a signal, ranking, strategy, or recommendation."}</p></div>
          <div className="object-list large">{productManifest.objects.features.map((item) => <a key={item.id} href={`/features/${item.id}`} onClick={(event) => navigate(event, `/features/${item.id}`)}><div><MaturityTag status={item.status} locale={locale} /><h2>{item.title[locale]}</h2><p>{item.detail}</p></div><ArrowRight /></a>)}</div>
          <p className="commercial-disclaimer">{locale === "zh" ? "Feature Plane 尚未实现；当前条目只定义未来产品合同。" : "The Feature Plane is not implemented; current entries define the future product contract only."}</p>
        </section>}
        {primaryRoute === "features" && routeSlug && routeSlug !== "methodology" && <ProductObjectDetail type="features" item={selectedFeature} locale={locale} onNavigate={navigate} />}
        {primaryRoute === "features" && routeSlug === "methodology" && <section className="object-detail-page"><SectionNav locale={locale} active="/features/methodology" onNavigate={navigate} items={locale === "zh" ? [{ path: "/features", label: "特征目录" }, { path: "/features/methodology", label: "方法与版本" }] : [{ path: "/features", label: "Feature index" }, { path: "/features/methodology", label: "Method & versions" }]} /><div className="object-detail-hero"><div><span className="mono-kicker">METHOD / VERSION / LINEAGE</span><h1>{locale === "zh" ? "看见结果之前，先看见生成规则。" : "See the production rule before the value."}</h1><p>{locale === "zh" ? "每个 Feature 必须发布公式、输入版本、对齐与缺失策略、测试夹具、变更记录和限制。" : "Every Feature must publish formula, input versions, alignment and missingness policy, fixtures, changelog, and limitations."}</p></div><MaturityTag status="planned" locale={locale} /></div><div className="object-fact-grid">{["formula + parameters", "inputs + as-of policy", "fixtures + version changelog"].map((value, index) => <article key={value}><span>0{index + 1}</span><h2>{value}</h2><p>{locale === "zh" ? "没有这些证据，就不能标成可用 Feature。" : "Without this evidence, the Feature cannot be marked available."}</p></article>)}</div></section>}

        {primaryRoute === "recipes" && !routeSlug && <section className="object-index-page">
          <SectionNav locale={locale} active="/recipes" onNavigate={navigate} items={locale === "zh" ? [{ path: "/recipes", label: "全部 Recipes" }, { path: "/recipes/adjusted-price-series", label: "价格准备" }, { path: "/recipes/pit-fundamentals-panel", label: "财务对齐" }] : [{ path: "/recipes", label: "All recipes" }, { path: "/recipes/adjusted-price-series", label: "Price preparation" }, { path: "/recipes/pit-fundamentals-panel", label: "Fundamental alignment" }]} />
          <div className="object-index-hero"><span className="mono-kicker">DATA RECIPES / EXECUTABLE METHODS</span><h1>{locale === "zh" ? "教你正确组合数据，不替你完成研究。" : "Combine data correctly without outsourcing the research."}</h1><p>{locale === "zh" ? "每个 Recipe 都声明问题、输入、时间对齐、输出结构、验证与局限；结果判断仍属于用户。" : "Every Recipe declares the task, inputs, time alignment, output schema, validation, and limits. Conclusions remain the user's."}</p></div>
          <div className="object-list large">{productManifest.objects.recipes.map((item) => <a key={item.id} href={`/recipes/${item.id}`} onClick={(event) => navigate(event, `/recipes/${item.id}`)}><div><MaturityTag status={item.status} locale={locale} /><h2>{item.title[locale]}</h2><p>{item.detail}</p></div><ArrowRight /></a>)}</div>
        </section>}
        {primaryRoute === "recipes" && routeSlug && <ProductObjectDetail type="recipes" item={selectedRecipe} locale={locale} onNavigate={navigate} />}

        {primaryRoute === "research" && !routeSlug && <ResearchAtlasPage locale={locale} theme={theme} copy={copy} atlas={researchAtlas} featuredPaper={featuredPaper} visiblePapers={visiblePapers} researchTopic={researchTopic} setResearchTopic={setResearchTopic} researchKind={researchKind} setResearchKind={setResearchKind} browseOpen={researchBrowseOpen} setBrowseOpen={setResearchBrowseOpen} libraryRef={researchLibraryRef} onShowLibrary={showResearchLibrary} onNavigate={navigate} topicLabels={topicLabels} kindLabels={kindLabels} methods={productManifest.objects.recipes} bookmarks={bookmarks} onToggleBookmark={toggleBookmark} />}

        {primaryRoute === "research" && routeSlug && <section className="object-detail-page research-record"><a className="object-back" href="/research" onClick={(event) => navigate(event, "/research")}>← {locale === "zh" ? "返回研究库" : "Back to Research"}</a><div className="object-detail-hero"><div><span className="mono-kicker">EXTERNAL RESEARCH / CURATED RECORD</span><h1>{selectedPaper?.title || (locale === "zh" ? "研究记录未找到" : "Research record not found")}</h1><p>{selectedPaper ? `${selectedPaper.authors} · ${selectedPaper.venue} · ${selectedPaper.year}` : ""}</p></div><span className="maturity-tag">{locale === "zh" ? "外部来源" : "External source"}</span></div>{selectedPaper && <><div className="research-record-grid"><article><span>01 / QUESTION</span><h2>{locale === "zh" ? "研究问题" : "Research question"}</h2><p>{selectedPaper.summary[locale]}</p></article><article><span>02 / EVIDENCE</span><h2>{locale === "zh" ? "所需数据材料" : "Required data"}</h2><p>{selectedPaper.data}</p></article><article><span>03 / LIMITS</span><h2>{locale === "zh" ? "方法与限制" : "Method & limits"}</h2><p>{locale === "zh" ? "先核对样本、时间范围、可得时点、修订、幸存者偏差与市场适用性，再决定能否复现或迁移。" : "Check sample, time range, point-in-time availability, revisions, survivorship, and market applicability before replication or transfer."}</p></article></div><section className="object-boundary"><h2>{locale === "zh" ? "从阅读进入数据准备" : "Continue from reading to data preparation"}</h2><p>{locale === "zh" ? "下一步是检查对应 Dataset、透明 Feature 与 Recipe；TradingDatas 不发表或验证论文结论。" : "Next inspect the related Dataset, transparent Feature, and Recipe. TradingDatas neither publishes nor validates the paper's conclusions."}</p><div className="detail-actions"><a className="primary-button" href="/data" onClick={(event) => navigate(event, "/data")}>{locale === "zh" ? "查看数据" : "View data"}<ArrowRight /></a><a className="text-link" href={`https://scholar.google.com/scholar?q=${encodeURIComponent(selectedPaper.title)}`} target="_blank" rel="noreferrer">{copy.sourcePaper}<ArrowRight /></a></div></section></>}</section>}

        {primaryRoute === "cookbook" && <section className="cookbook-section" id="cookbook">
          <div className="cookbook-visual" aria-hidden="true" />
          <div className="cookbook-copy">
            <span className="mono-kicker">COOKBOOK / METHODS</span>
            <h2>{copy.cookbookTitle}</h2>
            <p>{copy.cookbookCopy}</p>
            <ol>{copy.recipes.map((recipe, index) => <li key={recipe}><span>0{index + 1}</span>{recipe}<ArrowRight /></li>)}</ol>
          </div>
        </section>}

        {primaryRoute === "pricing" && !routeSlug && <section className="pricing-section pricing-page" id="pricing">
          <header className="pricing-intro">
            <span className="mono-kicker">BASE DATA / THREE PLANS</span>
            <h1>{locale === "zh" ? "三档基础套餐。" : "Three base-data plans."}</h1>
            <p>{locale === "zh" ? "相同基础数据，200 / 600 / 1,000 次每分钟。没有每日额度限制，另类数据独立加购。" : "The same base data, at 200 / 600 / 1,000 requests per minute. No daily quota. Alternative data is a separate add-on."}</p>
          </header>
          <BasePlanShowcase locale={locale} plans={packageCards} activeIndex={pricingPlanIndex} onChange={setPricingPlanIndex} onNavigate={navigate} billingPeriod={pricingBillingPeriod} setBillingPeriod={setPricingBillingPeriod} />
          <p className="commercial-disclaimer">{locale === "zh" ? "价格已确定，在线订阅与支付尚未开放。年付为月价 × 12 × 90%，按年一次支付，不代表已启用自动续费。具体数据开放范围、历史覆盖和有效权限以数据产品说明及账户读回为准。" : "Prices are set; online subscriptions and checkout are not yet available. Annual billing is monthly price × 12 × 90%, paid yearly; automatic renewal is not enabled. Available data, historical coverage, and effective access remain subject to product disclosures and authenticated account readback."}</p>
        </section>}

        {primaryRoute === "pricing" && routeSlug === "alternative" && <section className="object-detail-page"><SectionNav locale={locale} active="/pricing/alternative" onNavigate={navigate} items={locale === "zh" ? [{ path: "/pricing", label: "套餐比较" }, { path: "/pricing/alternative", label: "另类数据加购" }, { path: "/pricing/beta", label: "申请内测" }] : [{ path: "/pricing", label: "Compare plans" }, { path: "/pricing/alternative", label: "Alternative add-ons" }, { path: "/pricing/beta", label: "Request beta" }]} /><div className="object-detail-hero"><div><span className="mono-kicker">ALTERNATIVE DATA / OPTIONAL PRODUCTS</span><h1>{locale === "zh" ? "按具体产品试用，再明确选择是否加购。" : "Trial a specific product, then explicitly choose whether to add it."}</h1><p>{locale === "zh" ? "Pizza 指数、客流、招聘、应用关注等分别展示来源、授权范围和未来价格，不把整个另类数据分类打成一个模糊套餐。" : "Pizza Index, foot traffic, hiring, app attention, and other products show source, entitlement, and future price separately—not as one vague alternative-data bundle."}</p></div><MaturityTag status="planned" locale={locale} /></div><AlternativeProductList locale={locale} onNavigate={navigate} /><p className="commercial-disclaimer">{locale === "zh" ? "试用期限、价格、支付、续费和可购买范围等待 commerce backend 合同。" : "Trial term, price, payment, renewal, and purchasable scope await the commerce backend contract."}</p></section>}

        {primaryRoute === "pricing" && routeSlug === "beta" && <section className="object-detail-page">
          <SectionNav locale={locale} active="/pricing/beta" onNavigate={navigate} items={locale === "zh" ? [{ path: "/pricing", label: "基础套餐" }, { path: "/pricing/beta", label: "内测说明" }] : [{ path: "/pricing", label: "Base plans" }, { path: "/pricing/beta", label: "Beta information" }]} />
          <div className="object-detail-hero"><div><span className="mono-kicker">PRIVATE BETA / NOT OPEN</span><h1>{locale === "zh" ? "内测申请暂未开放。" : "Beta applications are not open yet."}</h1><p>{locale === "zh" ? "你可以先浏览数据、研究资料与套餐价格。目前不会收集申请信息、加入候补名单或开通数据权限。" : "Explore the data, research library, and plan prices first. We are not collecting applications, adding people to a waitlist, or granting data access here."}</p></div></div>
          <div className="detail-actions"><a className="primary-button" href="/pricing" onClick={(event) => navigate(event, "/pricing")}>{locale === "zh" ? "查看套餐与购买预览" : "View plans and purchase preview"}<ArrowRight /></a><a className="text-link" href="/data" onClick={(event) => navigate(event, "/data")}>{locale === "zh" ? "浏览数据目录" : "Browse the data catalog"}<ArrowRight /></a></div>
        </section>}

        {primaryRoute === "docs" && !routeSlug && <section className="docs-hub" id="docs">
          <SectionNav locale={locale} active="/docs" onNavigate={navigate} items={locale === "zh" ? [{ path: "/docs", label: "文档首页" }, { path: "/docs/data-1", label: "数据模型" }, { path: "/docs/api-1", label: "Catalog" }, { path: "/docs/commerce-1", label: "套餐" }] : [{ path: "/docs", label: "Docs home" }, { path: "/docs/data-1", label: "Data model" }, { path: "/docs/api-1", label: "Catalog" }, { path: "/docs/commerce-1", label: "Plans" }]} />
          <div className="docs-hub-hero">
            <span className="mono-kicker">PLATFORM GUIDE / DATA / API / ACCOUNT</span>
            <h1>{locale === "zh" ? "理解并使用 TradingDatas 的所有说明。" : "Everything needed to understand and use TradingDatas."}</h1>
            <p>{locale === "zh" ? "Docs 汇集网站各板块、数据合同、Agent 接入、套餐与账户的说明；API 只是其中一个部分。" : "Docs brings together guidance for every product area, data contract, Agent connection, package, and account workflow. API is one part—not the whole hub."}</p>
          </div>
          <div className="docs-category-tabs" aria-label={locale === "zh" ? "文档分类" : "Documentation categories"}>
            <button type="button" className={docsCategory === "all" ? "is-active" : ""} onClick={() => setDocsCategory("all")}>{locale === "zh" ? "全部" : "All"}</button>
            {docsCategories.map((category) => <button type="button" key={category.key} className={docsCategory === category.key ? "is-active" : ""} onClick={() => setDocsCategory(category.key)}>{category.label}</button>)}
          </div>
          <div className="docs-grid">{visibleDocs.length ? visibleDocs.map((entry, index) => <a className="docs-card" key={`${entry.category}-${entry.title}`} href={`/docs/${entry.slug}`} onClick={(event) => navigate(event, `/docs/${entry.slug}`)}><span>{String(index + 1).padStart(2, "0")} · {entry.categoryLabel}</span><h2>{entry.title}</h2><p>{entry.description}</p><ArrowRight /></a>) : <div className="docs-empty">{locale === "zh" ? "没有匹配的说明。换一个关键词或分类。" : "No guidance matches. Try another term or category."}</div>}</div>
          <section className="docs-quickstart">
            <div><span className="mono-kicker">API QUICKSTART / ONE PART OF DOCS</span><h2>{copy.docsTitle}</h2><p>{copy.docsCopy}</p><button className="primary-button" type="button" onClick={() => setAgentOpen(true)}>{copy.connect}</button></div>
            <div className="code-window"><div><span /><span /><span /><small>catalog request</small></div><pre><code>{`GET /v1/catalog HTTP/1.1\nHost: api.tradingdatas.com\nAuthorization: Bearer ••••••••\nAccept: application/json`}</code></pre><div className="code-status"><ShieldCheck weight="fill" /> authenticated · provider-neutral</div></div>
          </section>
        </section>}

        {primaryRoute === "docs" && routeSlug && <section className="object-detail-page docs-article"><a className="object-back" href="/docs" onClick={(event) => navigate(event, "/docs")}>← {locale === "zh" ? "返回文档" : "Back to Docs"}</a><div className="object-detail-hero"><div><span className="mono-kicker">{selectedDoc?.categoryLabel?.toUpperCase() || "DOCUMENTATION"}</span><h1>{selectedDoc?.title || (locale === "zh" ? "说明未找到" : "Guide not found")}</h1><p>{selectedDoc?.description}</p></div><span className="maturity-tag">{locale === "zh" ? "版本化说明" : "Versioned guide"}</span></div>{selectedDoc && <div className="docs-article-body"><aside><span>{locale === "zh" ? "本文回答" : "THIS GUIDE ANSWERS"}</span><p>{selectedDoc.description}</p><span>{locale === "zh" ? "权威来源" : "AUTHORITY"}</span><p>{selectedDoc.category === "api" ? "docs/API.md + authenticated runtime" : selectedDoc.category === "data" ? "registry + facts/receipts + docs/PRODUCT.md" : "docs/PRODUCT.md + backend contract"}</p></aside><article><h2>{locale === "zh" ? "说明结构" : "Guide structure"}</h2><p>{locale === "zh" ? "每篇文档会明确当前能力、目标能力、使用步骤、限制、错误状态、相关对象与下一步。它不会把产品提案写成生产事实。" : "Every guide identifies current capability, target capability, steps, limits, error states, related objects, and next action. It never turns a product proposal into a production fact."}</p><h2>{locale === "zh" ? "相关入口" : "Related entries"}</h2><div className="detail-actions"><a className="text-link" href="/data" onClick={(event) => navigate(event, "/data")}>{locale === "zh" ? "数据目录" : "Data catalog"}<ArrowRight /></a><a className="text-link" href="/recipes" onClick={(event) => navigate(event, "/recipes")}>Recipes<ArrowRight /></a></div></article></div>}</section>}

        {primaryRoute === "pricing" && routeSlug === "preview" && <PurchasePreview locale={locale} selection={readPreviewSelection(routeSearch)} accountState={accountViewState} navigate={navigate} onRetry={() => setAccountConnectionRevision((value) => value + 1)} onAccount={() => openAccountSection("subscription")} />}

        {primaryRoute === "login" && (
          <LoginPage locale={locale} theme={theme} returnPath={safeLoginDestination(routeSearch)} token={accountTokenInput} onTokenChange={(value) => { setAccountTokenInput(value); setAccountError(""); }} onSubmit={connectAccount} onEmailVerify={connectEmailAccount} loading={accountLoading} submitting={accountLoginPending} error={accountError} navigate={navigate} />
        )}

        {primaryRoute === "account" && (
          <section className="account-page">
            <div className="account-page-heading">
              <span className="mono-kicker">ACCOUNT / LIBRARY / DATA ACCESS</span>
              <h1>{locale === "zh" ? "你的 TradingDatas 工作区。" : "Your TradingDatas workspace."}</h1>
              <p>{locale === "zh" ? "在一个安静的工作区管理已收藏内容、数据访问、文档、Agent 接入、账单和个人设置。" : "A quiet workspace for saved materials, data access, documentation, Agent connections, billing, and preferences."}</p>
              <div className="account-entry-actions">
                <button className="primary-button" type="button" disabled={accountChecking} aria-busy={accountChecking} onClick={() => accountViewState === "unavailable" ? setAccountConnectionRevision((value) => value + 1) : accountData ? setAccountSection("overview") : goTo("/login")}>{accountEntryLabel}<ArrowRight /></button>
                <small>{locale === "zh" ? "登录后仅显示当前账户的订阅、授权和用量。" : "After sign-in, only the current account's plan, access, and usage are shown."}</small>
              </div>
            </div>
            <div className="account-workspace">
              <aside className="account-sidebar" aria-label={locale === "zh" ? "账户分类" : "Account sections"}>
                {accountGroups.map((group) => (
                  <div className="account-nav-group" key={group.label}>
                    <span>{group.label}</span>
                    {group.items.map((item) => <button key={item.key} type="button" className={accountSection === item.key ? "is-active" : ""} onClick={() => setAccountSection(item.key)}>{item.label}<ArrowRight /></button>)}
                  </div>
                ))}
              </aside>
              <article className="account-detail">
                <div className="account-detail-head">
                  <span className="account-surface-label">{locale === "zh" ? "账户主页" : "ACCOUNT HOME"}</span>
                  <h2>{activeAccountItem.label}</h2>
                  <p>{activeAccountItem.description}</p>
                </div>
                {(accountSignOutError || accountSignOutPending) && <div className="account-signout-feedback" role={accountSignOutError ? "alert" : "status"} aria-atomic="true">
                  <p>{accountSignOutPending ? (locale === "zh" ? "正在安全退出，请稍候…" : "Signing out securely. Please wait…") : (locale === "zh" ? "未能确认退出，会话可能仍然有效。请重试，确认退出前不要离开共享设备。" : "Sign-out could not be confirmed. Your session may still be active. Retry before leaving a shared device.")}</p>
                  {accountSignOutError && <button type="button" onClick={disconnectAccount} disabled={accountSignOutPending}>{locale === "zh" ? "重试退出" : "Retry sign-out"}<ArrowRight size={16} /></button>}
                </div>}
                {accountUsageError && accountData && <div className="account-signout-feedback" role="status"><p>{locale === "zh" ? "用量暂时无法加载，你仍然处于登录状态。" : "Usage is temporarily unavailable. You are still signed in."}</p><button type="button" onClick={() => setAccountConnectionRevision((value) => value + 1)}>{locale === "zh" ? "重新加载" : "Retry loading"}</button></div>}
                {accountViewState === "unavailable" && <div className="account-signout-feedback" role="alert"><p>{locale === "zh" ? "暂时无法验证账户连接，未显示账户数据。你可以重新加载。" : "We could not verify the account connection. Account data is hidden until you retry."}</p><button type="button" disabled={accountLoading} onClick={() => setAccountConnectionRevision((value) => value + 1)}>{locale === "zh" ? "重新加载" : "Retry loading"}</button></div>}
                {accountPrivateSection && accountChecking ? (
                  <div className="account-empty-state" role="status" aria-live="polite"><ShieldCheck size={28} /><strong>{locale === "zh" ? "正在验证账户连接" : "Checking your account connection"}</strong><p>{locale === "zh" ? "请稍候，验证完成后显示当前账户。无需重复登录。" : "Please wait while we verify this session. No need to sign in again."}</p></div>
                ) : accountPrivateSection && accountViewState === "unavailable" ? null : accountPrivateSection && isEmailAccount ? (
                  <EmailAccountPanel account={accountData} section={accountSection} locale={locale} onSignOut={disconnectAccount} signingOut={accountSignOutPending} navigate={navigate} />
                ) : accountSection === "overview" ? (
                  accountData ? (
                    <div className="account-live-overview">
                      <div className="account-live-status"><span className={accountData.enabled ? "is-active" : "is-paused"} /> <strong>{accountData.enabled ? (locale === "zh" ? "账户可用" : "Account active") : (locale === "zh" ? "账户已暂停" : "Account paused")}</strong><button type="button" onClick={disconnectAccount} disabled={accountSignOutPending}>{accountSignOutPending ? (locale === "zh" ? "正在退出…" : "Signing out…") : (locale === "zh" ? "断开连接" : "Disconnect")}</button></div>
                      <dl className="account-facts account-live-facts">
                        <div><dt>{locale === "zh" ? "当前套餐" : "Current plan"}</dt><dd>{accountPlanLabel}</dd></div>
                        <div><dt>{locale === "zh" ? "有效期" : "Expiry"}</dt><dd>{accountData.expires_at ? accountData.expires_at.slice(0, 10) : (locale === "zh" ? "长期有效" : "No expiry")}</dd></div>
                        <div><dt>{locale === "zh" ? "请求频率" : "Request frequency"}</dt><dd>{accountData.minute_request_limit ? `${accountData.minute_request_limit.toLocaleString()} / ${locale === "zh" ? "分钟" : "minute"}` : accountData.hourly_request_limit ? `${accountData.hourly_request_limit.toLocaleString()} / ${locale === "zh" ? "小时" : "hour"}` : (locale === "zh" ? "不限" : "Unlimited")}</dd></div>
                        <div><dt>{locale === "zh" ? "今日请求" : "Requests today"}</dt><dd>{(accountUsage?.today_count ?? accountData.usage?.today_count ?? 0).toLocaleString()}</dd></div>
                        <div><dt>{locale === "zh" ? "数据授权" : "Data access"}</dt><dd>{accountCategories.join(" · ") || (locale === "zh" ? "无数据授权" : "No data grants")}</dd></div>
                      </dl>
                    </div>
                  ) : (
                    <div className="account-empty-state account-signin-state"><ShieldCheck size={28} /><strong>{locale === "zh" ? "登录后查看真实账户状态" : "Sign in to see live account status"}</strong><p>{locale === "zh" ? "套餐、有效期、授权和用量只在认证后显示。" : "Plan, expiry, grants, and usage appear only after authentication."}</p><button className="primary-button" type="button" onClick={() => goTo("/login")}>{locale === "zh" ? "前往登录" : "Go to sign in"}<ArrowRight /></button></div>
                  )
                ) : accountSection === "subscription" ? (
                  accountData ? (
                    <div className="account-plan-panel">
                      <section className="account-plan-hero">
                        <div><span className="mono-kicker">CURRENT BASE-DATA PLAN</span><h3>{accountPlanLabel}</h3><p>{locale === "zh" ? "当前账户的实际套餐与数据授权由认证后的 Portal API 返回。" : "The authenticated Portal API supplies this account's effective plan and data grants."}</p></div>
                        <div><span>{accountData.enabled ? (locale === "zh" ? "账户可用" : "ACTIVE") : (locale === "zh" ? "账户暂停" : "PAUSED")}</span><strong>{accountData.minute_request_limit ? `${accountData.minute_request_limit.toLocaleString()} / ${locale === "zh" ? "分钟" : "minute"}` : accountData.hourly_request_limit ? `${accountData.hourly_request_limit.toLocaleString()} / ${locale === "zh" ? "小时" : "hour"}` : (locale === "zh" ? "不限频率" : "Unlimited")}</strong><small>{locale === "zh" ? "每日请求总量" : "Daily request volume"} · {accountData.daily_limit == null ? (locale === "zh" ? "不限" : "Unlimited") : accountData.daily_limit.toLocaleString()}</small></div>
                      </section>
                      <section className="account-access-list">
                        <div><span>{locale === "zh" ? "有效期" : "EXPIRY"}</span><strong>{accountData.expires_at ? accountData.expires_at.slice(0, 10) : (locale === "zh" ? "长期有效" : "No expiry")}</strong></div>
                        <div><span>{locale === "zh" ? "基础数据授权" : "BASE-DATA GRANTS"}</span><strong>{accountCategories.join(" · ") || (locale === "zh" ? "无数据授权" : "No data grants")}</strong></div>
                        <div><span>{locale === "zh" ? "授权模式" : "GRANT MODE"}</span><strong>{accountData.data_category_mode === "all" ? (locale === "zh" ? "全部已登记分类" : "All registered categories") : (locale === "zh" ? "按分类授权" : "Category allowlist")}</strong></div>
                      </section>
                      <div className="account-boundary-note"><ShieldCheck /> <div><strong>{locale === "zh" ? "另类数据加购尚未单独投影" : "Alternative-data add-ons are not projected separately yet"}</strong><p>{locale === "zh" ? "当前接口只返回有效数据分类授权。待加购合同上线后，这里再显示试用、单独有效期和续费状态。" : "The current contract returns effective category grants only. Trials, separate expiry, and renewal will appear after the add-on contract is live."}</p></div></div>
                      <a className="account-inline-action" href={packageCards.some((plan) => plan.id === accountData.tier) ? buildPreviewPath(accountData.tier, "monthly") : "/pricing"} onClick={(event) => navigate(event, packageCards.some((plan) => plan.id === accountData.tier) ? buildPreviewPath(accountData.tier, "monthly") : "/pricing")}>{locale === "zh" ? "预览购买与续费 · 暂未开放支付" : "Preview purchase & renewal · payment unavailable"}<ArrowRight /></a>
                    </div>
                  ) : (
                    <div className="account-empty-state"><ShieldCheck size={28} /><strong>{locale === "zh" ? "登录后查看套餐与授权" : "Sign in to view plan and access"}</strong><p>{locale === "zh" ? "这里只显示当前租户的真实套餐、有效期和分类授权。" : "Only the current tenant's live plan, expiry, and category grants appear here."}</p><button className="primary-button" type="button" onClick={() => goTo("/login")}>{locale === "zh" ? "前往登录" : "Go to sign in"}</button></div>
                  )
                ) : accountSection === "usage" ? (
                  accountData ? (
                    <div className="account-usage-panel">
                      <div className="account-usage-summary">
                        <article><span>{locale === "zh" ? "今日请求" : "TODAY"}</span><strong>{(accountUsage?.today_count ?? accountData.usage?.today_count ?? 0).toLocaleString()}</strong><small>{locale === "zh" ? "当前租户" : "current tenant"}</small></article>
                        <article><span>{locale === "zh" ? "请求频率" : "RATE LIMIT"}</span><strong>{accountData.minute_request_limit ? accountData.minute_request_limit.toLocaleString() : accountData.hourly_request_limit ? accountData.hourly_request_limit.toLocaleString() : "∞"}</strong><small>{accountData.minute_request_limit ? (locale === "zh" ? "每分钟" : "per minute") : accountData.hourly_request_limit ? (locale === "zh" ? "每小时" : "per hour") : (locale === "zh" ? "不限频率" : "unlimited")}</small></article>
                        <article><span>{locale === "zh" ? "每日总量" : "DAILY VOLUME"}</span><strong>{accountData.daily_limit == null ? "∞" : accountData.daily_limit.toLocaleString()}</strong><small>{accountData.daily_limit == null ? (locale === "zh" ? "无每日额度限制" : "no daily cap") : (locale === "zh" ? "请求上限" : "request cap")}</small></article>
                      </div>
                      <section className="account-usage-history">
                        <div><div><span className="mono-kicker">30 DAY REQUEST HISTORY</span><h3>{locale === "zh" ? "请求量保持可读，不做交易终端。" : "Readable request volume, not a trading terminal."}</h3></div><small>{locale === "zh" ? "认证后的租户汇总" : "Authenticated tenant aggregate"}</small></div>
                        {accountUsageHistory.length ? <div className="account-usage-chart" aria-label={locale === "zh" ? "最近 30 天请求量" : "Request volume for the last 30 days"}>{accountUsageHistory.map((entry) => <div key={entry.date} title={`${entry.date}: ${entry.total}`}><i style={{ height: `${Math.max(3, ((Number(entry.total) || 0) / accountUsagePeak) * 100)}%` }} /><span>{entry.date.slice(5)}</span></div>)}</div> : <div className="account-chart-empty">{locale === "zh" ? "当前周期暂无请求记录。" : "No requests in the current period."}</div>}
                      </section>
                      <div className="account-usage-grants"><span>{locale === "zh" ? "本周期生效的数据分类" : "DATA CATEGORIES IN THIS PERIOD"}</span><strong>{accountCategories.join(" · ") || (locale === "zh" ? "无数据授权" : "No data grants")}</strong></div>
                    </div>
                  ) : (
                    <div className="account-empty-state"><ShieldCheck size={28} /><strong>{locale === "zh" ? "登录后查看真实用量" : "Sign in to view live usage"}</strong><p>{locale === "zh" ? "请求历史和限制只从当前租户的 Portal API 读取。" : "Request history and limits are read only from the current tenant's Portal API."}</p><button className="primary-button" type="button" onClick={() => goTo("/login")}>{locale === "zh" ? "前往登录" : "Go to sign in"}</button></div>
                  )
                ) : accountSection === "keys" ? (
                  accountData ? (
                    <div className="account-keys-panel">
                      <form className="account-key-create" onSubmit={createAccountKey}>
                        <div><span className="mono-kicker">CUSTOMER-SCOPED CREDENTIALS</span><h3>{locale === "zh" ? "为设备或 Agent 创建独立密钥" : "Create one key per device or Agent"}</h3><p>{locale === "zh" ? "新密钥继承当前套餐、数据授权、有效期和限额，不能提升权限。" : "New keys inherit the current plan, data grants, expiry, and limits. They cannot elevate access."}</p></div>
                        <div className="account-key-create-controls"><label htmlFor="account-key-label">{locale === "zh" ? "密钥名称" : "Key name"}</label><div><input id="account-key-label" value={accountKeyLabel} maxLength={64} onChange={(event) => { setAccountKeyLabel(event.target.value); setAccountKeyError(""); }} placeholder={locale === "zh" ? "例如：MacBook 上的 Codex" : "e.g. Codex on MacBook"} /><button className="primary-button" type="submit" disabled={!accountKeyLabel.trim() || accountKeyLoading}>{locale === "zh" ? "创建密钥" : "Create key"}</button></div></div>
                      </form>
                      {accountNewKey && <div className="account-new-key" role="status"><div><span>{locale === "zh" ? "只显示一次" : "SHOWN ONCE"}</span><strong>{accountNewKey}</strong><small>{locale === "zh" ? "现在复制并保存在密码管理器中，离开此页面后无法再次查看。" : "Copy it now and store it in a password manager. It cannot be shown again."}</small></div><button type="button" onClick={() => navigator.clipboard.writeText(accountNewKey)}><Copy />{locale === "zh" ? "复制" : "Copy"}</button></div>}
                      {accountKeyError && <div className="account-key-error" role="alert">{locale === "zh" ? "密钥操作暂时无法完成，请稍后重试。" : "The key action could not be completed. Try again later."}</div>}
                      <div className="account-key-list">
                        {accountKeys.map((key) => <article key={key.key_id} className={!key.enabled ? "is-disabled" : ""}><div><span>{key.is_current ? (locale === "zh" ? "当前连接" : "CURRENT CONNECTION") : key.enabled ? (locale === "zh" ? "可用" : "ACTIVE") : (locale === "zh" ? "已停用" : "DISABLED")}</span><strong>{key.label}</strong><small>{key.fingerprint}{key.created_at ? ` · ${key.created_at.slice(0, 10)}` : ""}</small></div>{key.is_current ? <em>{locale === "zh" ? "不可在当前会话停用" : "Protected in this session"}</em> : key.enabled ? <button type="button" disabled={accountKeyLoading} onClick={() => disableAccountKey(key)}>{locale === "zh" ? "停用" : "Disable"}</button> : <em>{locale === "zh" ? "已停用" : "Disabled"}</em>}</article>)}
                        {!accountKeys.length && !accountKeyError && <div className="account-empty-state"><ShieldCheck size={28} /><strong>{accountKeysLoading ? (locale === "zh" ? "正在读取密钥" : "Loading keys") : (locale === "zh" ? "暂无 API 密钥" : "No API keys yet")}</strong></div>}
                      </div>
                    </div>
                  ) : (
                    <div className="account-empty-state"><ShieldCheck size={28} /><strong>{locale === "zh" ? "先登录账户" : "Sign in first"}</strong><p>{locale === "zh" ? "登录后才能查看和管理当前租户的 API 密钥。" : "Sign in before viewing or managing API keys for the current tenant."}</p><button className="primary-button" type="button" onClick={() => goTo("/login")}>{locale === "zh" ? "前往登录" : "Go to sign in"}</button></div>
                  )
                ) : accountSection === "bookmarks" ? (
                  <div className="account-bookmarks">
                    <div className="account-local-note"><BookmarkSimple />{locale === "zh" ? "当前收藏保存在此浏览器。登录账户同步功能尚未连接。" : "Bookmarks currently stay in this browser. Account sync is not connected yet."}</div>
                    {savedItems.length ? savedItems.map((item) => <div className="account-bookmark-row" key={item.key}><a href={item.path} onClick={(event) => openSearchItem(event, item)}><span>{item.type}</span><strong>{item.label}</strong><small>{item.description}</small></a><button type="button" onClick={() => toggleBookmark(item.key)} aria-label={locale === "zh" ? "取消收藏" : "Remove bookmark"}><BookmarkSimple weight="fill" /></button></div>) : <div className="account-empty-state"><BookmarkSimple size={28} /><strong>{locale === "zh" ? "还没有收藏内容" : "Nothing saved yet"}</strong><p>{locale === "zh" ? "可从全站搜索或研究库收藏数据产品、论文、方法和文档。" : "Save datasets, papers, methods, and docs from site search or the Research library."}</p></div>}
                  </div>
                ) : accountSection === "docs" ? (
                  <div className="account-docs-browser">
                    <aside>{docsCategories.map((category) => <section key={category.key}><span>{category.label}</span>{category.items.map(([title], index) => { const slug = `${category.key}-${index + 1}`; return <button key={slug} type="button" className={activeAccountDoc.slug === slug ? "is-active" : ""} onClick={() => setAccountDocSlug(slug)}>{title}</button>; })}</section>)}</aside>
                    <article><span className="mono-kicker">{activeAccountDoc.categoryLabel.toUpperCase()}</span><h3>{activeAccountDoc.title}</h3><p>{activeAccountDoc.description}</p><dl><div><dt>{locale === "zh" ? "说明范围" : "Guide scope"}</dt><dd>{locale === "zh" ? "当前能力、目标能力、操作步骤、限制和相关入口。" : "Current capability, target capability, steps, limits, and related entries."}</dd></div><div><dt>{locale === "zh" ? "权威来源" : "Authority"}</dt><dd>{activeAccountDoc.category === "api" ? "docs/API.md + authenticated runtime" : activeAccountDoc.category === "data" ? "registry + facts/receipts + docs/PRODUCT.md" : "docs/PRODUCT.md + backend contract"}</dd></div></dl><a className="text-link" href={`/docs/${activeAccountDoc.slug}`} onClick={(event) => navigate(event, `/docs/${activeAccountDoc.slug}`)}>{locale === "zh" ? "打开完整说明" : "Open full guide"}<ArrowRight /></a></article>
                  </div>
                ) : accountSection === "preferences" ? (
                  <div className="account-setting-panels">
                    <section>
                      <span className="popover-title">{copy.language}</span>
                      <div className="segmented">
                        <button type="button" className={locale === "zh" ? "is-active" : ""} onClick={() => chooseLocale("zh")}>中文</button>
                        <button type="button" className={locale === "en" ? "is-active" : ""} onClick={() => chooseLocale("en")}>English</button>
                      </div>
                    </section>
                    <section>
                      <span className="popover-title">{copy.appearance}</span>
                      <div className="account-theme-list">
                        <button type="button" className={themeChoice === "system" ? "is-active" : ""} onClick={() => chooseTheme("system")}><GlobeSimple />{copy.system}</button>
                        <button type="button" className={themeChoice === "light" ? "is-active" : ""} onClick={() => chooseTheme("light")}><Sun />{copy.light}</button>
                        <button type="button" className={themeChoice === "dark" ? "is-active" : ""} onClick={() => chooseTheme("dark")}><Moon />{copy.dark}</button>
                      </div>
                    </section>
                  </div>
                ) : accountSection === "agents" ? (
                  <div className="account-agent-panel">
                    <TerminalWindow size={30} weight="duotone" />
                    <div><strong>Claude · Codex · OpenClaw · Hermes</strong><p>{locale === "zh" ? "所有 Agent 共用 provider-neutral 的 catalog/query 合同。密钥不会进入提示词。" : "Every Agent uses the same provider-neutral catalog/query contract. Secrets stay out of prompts."}</p></div>
                    <button className="primary-button" type="button" onClick={() => setAgentOpen(true)}>{copy.connect}</button>
                  </div>
                ) : accountSection === "billing" ? (
                  <div className="account-billing-panel">
                    <div><span className="mono-kicker">BILLING / NOT YET AVAILABLE</span><h3>{locale === "zh" ? "支付与账单暂未开放。" : "Payments and billing are not open yet."}</h3><p>{locale === "zh" ? "购买预览不会生成订单或账单，也不会改变现有权限。正式接通后，这里会分别展示订单、支付结果和开通状态；现在不展示模拟记录。续费需主动购买，不自动扣款。" : "A purchase preview creates no order or bill and never changes existing access. Once connected, this space will distinguish orders, payment results, and activation. No simulated records are shown. Renewals require an active purchase, with no automatic debit."}</p></div>
                    {accountData && <dl><div><dt>{locale === "zh" ? "当前套餐" : "Current plan"}</dt><dd>{accountPlanLabel}</dd></div><div><dt>{locale === "zh" ? "有效期" : "Expiry"}</dt><dd>{accountData.expires_at ? accountData.expires_at.slice(0, 10) : (locale === "zh" ? "长期有效" : "No expiry")}</dd></div></dl>}
                    <a className="account-inline-action" href="/pricing" onClick={(event) => navigate(event, "/pricing")}>{locale === "zh" ? "查看公开套餐" : "View public plans"}<ArrowRight /></a>
                  </div>
                ) : accountSection === "security" ? (
                  accountData ? (
                    <div className="account-security-panel">
                      <section><ShieldCheck size={24} weight="duotone" /><div><span>{locale === "zh" ? "当前浏览器连接" : "CURRENT BROWSER CONNECTION"}</span><h3>{locale === "zh" ? "安全网页会话" : "Secure web session"}</h3><p>{locale === "zh" ? "访问密钥已封装在不可被页面脚本读取的同站会话中。" : "The access key is sealed in a same-site session that page scripts cannot read."}</p></div><button type="button" onClick={disconnectAccount} disabled={accountSignOutPending}>{accountSignOutPending ? (locale === "zh" ? "正在退出…" : "Signing out…") : (locale === "zh" ? "退出此浏览器" : "Sign out here")}</button></section>
                      <dl className="account-security-facts"><div><dt>{locale === "zh" ? "租户" : "Tenant"}</dt><dd>{accountData.tenant_id}</dd></div><div><dt>{locale === "zh" ? "认证方式" : "Authentication"}</dt><dd>{locale === "zh" ? "HttpOnly 同站会话" : "HttpOnly same-site session"}</dd></div><div><dt>{locale === "zh" ? "密钥管理" : "Key management"}</dt><dd><button type="button" onClick={() => setAccountSection("keys")}>{locale === "zh" ? "查看与轮换 API 密钥" : "View and rotate API keys"}<ArrowRight /></button></dd></div></dl>
                      <div className="account-boundary-note"><ShieldCheck /><div><strong>{locale === "zh" ? "凭证绑定与跨设备会话列表尚未开放" : "Credential linking and cross-device session lists are not available"}</strong><p>{locale === "zh" ? "访问密钥与邮箱账户不会自动绑定；短信服务暂未接入。可用登录方式以登录页的服务状态为准。" : "Access keys are not automatically linked to email accounts. SMS is not connected. Available sign-in methods are shown on the login page."}</p></div></div>
                    </div>
                  ) : (
                    <div className="account-empty-state"><ShieldCheck size={28} /><strong>{locale === "zh" ? "登录后管理当前连接" : "Sign in to manage this connection"}</strong><p>{locale === "zh" ? "前往登录页查看可用的登录方式。网页登录不会自动开通数据权限。" : "Visit sign-in to see available methods. A web login does not automatically grant data access."}</p><button className="primary-button" type="button" onClick={() => goTo("/login")}>{locale === "zh" ? "前往登录" : "Go to sign in"}</button></div>
                  )
                ) : (
                  <dl className="account-facts">
                    <div><dt>{locale === "zh" ? "权威来源" : "Authority"}</dt><dd>{accountSection === "billing" ? "Commerce / billing contract" : "Customer Portal API"}</dd></div>
                    <div><dt>{locale === "zh" ? "当前状态" : "Current state"}</dt><dd>{locale === "zh" ? "连接账户后读取当前密钥的真实授权与用量" : "Connect an account to read effective access and usage for the current key"}</dd></div>
                    <div><dt>{locale === "zh" ? "访问边界" : "Access boundary"}</dt><dd>{locale === "zh" ? "认证后仅显示当前租户数据" : "Authenticated, current-tenant data only"}</dd></div>
                  </dl>
                )}
              </article>
            </div>
          </section>
        )}
      </main>

      <footer><Brand onNavigate={navigate} /><p>Raw materials for financial research.</p><span>© 2026 TradingDatas</span></footer>
      <AgentDialog open={agentOpen} onClose={() => setAgentOpen(false)} copy={copy} locale={locale} />
    </div>
  );
}
