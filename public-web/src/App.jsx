import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  Copy,
  Database,
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

const agents = ["Claude", "Codex", "OpenClaw", "Hermes", "Other Agent"];
const productRoutes = ["home", "data", "datasets", "features", "recipes", "research", "pricing", "docs", "status", "changelog", "account"];

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

const messages = {
  en: {
    nav: ["Data", "Features", "Recipes", "Research", "Pricing", "Docs"],
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
    nav: ["数据", "特征", "Recipes", "研究", "套餐", "文档"],
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
    observed_example: locale === "zh" ? "观测示例" : "Observed example",
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

function ProductObjectDetail({ type, item, locale, onNavigate }) {
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

export function App() {
  const [locale, setLocale] = useState(() => localStorage.getItem("td-locale") || getSystemLocale());
  const [themeChoice, setThemeChoice] = useState(() => localStorage.getItem("td-theme") || "system");
  const [theme, setTheme] = useState(() => themeChoice === "system" ? getSystemTheme() : themeChoice);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);
  const [route, setRoute] = useState(getRouteFromPath);
  const [accountSection, setAccountSection] = useState("overview");
  const [researchQuery, setResearchQuery] = useState("");
  const [researchTopic, setResearchTopic] = useState("all");
  const [researchKind, setResearchKind] = useState("all");
  const [docsQuery, setDocsQuery] = useState("");
  const [docsCategory, setDocsCategory] = useState("all");
  const copy = messages[locale];

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
    const syncRoute = () => setRoute(getRouteFromPath());
    window.addEventListener("popstate", syncRoute);
    return () => window.removeEventListener("popstate", syncRoute);
  }, []);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [route]);

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
  const sections = ["data", "features", "recipes", "research", "pricing", "docs"];
  const navPaths = sections.map((section) => `/${section}`);
  function navigate(event, path) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    window.history.pushState({}, "", path);
    const pathname = new URL(path, window.location.origin).pathname;
    setRoute(pathname === "/" ? "home" : pathname.replace(/^\/+|\/+$/g, ""));
    setMobileOpen(false);
  }
  const topicLabels = Object.fromEntries(copy.researchTopics);
  const kindLabels = Object.fromEntries(copy.researchKinds);
  const visiblePapers = papers.filter((paper) => {
    const matchesTopic = researchTopic === "all" || paper.topic === researchTopic;
    const matchesKind = researchKind === "all" || paper.kind === researchKind;
    const haystack = `${paper.title} ${paper.authors} ${paper.venue} ${paper.data} ${paper.summary.en} ${paper.summary.zh}`.toLowerCase();
    return matchesTopic && matchesKind && haystack.includes(researchQuery.trim().toLowerCase());
  });
  const accountGroups = locale === "zh" ? [
    { label: "账户", items: [{ key: "overview", label: "账户概览", description: "查看订阅、用量、密钥和另类数据状态的统一摘要。" }] },
    { label: "数据访问", items: [
      { key: "subscription", label: "订阅与加购", description: "管理基础套餐、另类数据试用、有效期和续费选择。" },
      { key: "usage", label: "用量与限制", description: "查看分钟频率、并发、每日查询和分类授权。" },
      { key: "keys", label: "API 密钥", description: "创建、停用和轮换用于 catalog/query 的访问密钥。" },
    ] },
    { label: "集成", items: [{ key: "agents", label: "Agent 与 MCP", description: "为 Claude、Codex、OpenClaw、Hermes 和其它 Agent 生成安全接入说明。" }] },
    { label: "账单", items: [{ key: "billing", label: "账单与发票", description: "查看订单、续费、支付记录和发票资料。" }] },
    { label: "设置", items: [
      { key: "preferences", label: "语言与外观", description: "设置网站语言以及跟随系统、明亮或暗色外观。" },
      { key: "security", label: "安全", description: "管理登录会话、账户安全和访问审计。" },
    ] },
  ] : [
    { label: "Account", items: [{ key: "overview", label: "Overview", description: "A single summary of subscription, usage, keys, and alternative-data access." }] },
    { label: "Data access", items: [
      { key: "subscription", label: "Subscription & add-ons", description: "Manage base packages, alternative-data trials, expiry, and renewal choices." },
      { key: "usage", label: "Usage & limits", description: "Review minute rate, concurrency, daily queries, and category access." },
      { key: "keys", label: "API keys", description: "Create, disable, and rotate credentials for catalog and query." },
    ] },
    { label: "Integrations", items: [{ key: "agents", label: "Agents & MCP", description: "Generate safe setup guidance for Claude, Codex, OpenClaw, Hermes, and other Agents." }] },
    { label: "Billing", items: [{ key: "billing", label: "Billing & invoices", description: "Review orders, renewals, payment records, and invoice details." }] },
    { label: "Settings", items: [
      { key: "preferences", label: "Language & appearance", description: "Choose the site language and system, light, or dark appearance." },
      { key: "security", label: "Security", description: "Manage sign-in sessions, account security, and access audit." },
    ] },
  ];
  const dataGroups = locale === "zh" ? [
    { id: "market-reference", title: "行情与基础参考", description: "A 股日线、复权因子、停复牌、交易日历、证券与市场基础信息。", examples: "daily · adj_factor · suspend · trade_cal" },
    { id: "intraday", title: "日内与微观结构", description: "历史分钟、集合竞价、盘前股本以及 ETF、指数相关分钟观测。", examples: "minute · auction · premarket · etf/index" },
    { id: "fundamentals", title: "财务与公司行动", description: "财务报表、业绩、分红、股本、股东与公司行动等研究原料。", examples: "financials · dividend · share_float · holders" },
    { id: "indices", title: "指数与基金", description: "指数成分、权重、日线、ETF 参考与申赎相关数据。", examples: "index · constituent · weight · etf" },
  ] : [
    { id: "market-reference", title: "Market & reference", description: "A-share daily prices, adjustment factors, suspensions, calendars, instruments, and market reference.", examples: "daily · adj_factor · suspend · trade_cal" },
    { id: "intraday", title: "Intraday & microstructure", description: "Historical minutes, auctions, pre-market share capital, and ETF/index minute observations.", examples: "minute · auction · premarket · etf/index" },
    { id: "fundamentals", title: "Fundamentals & corporate actions", description: "Financial statements, earnings, dividends, capital structure, holders, and company actions.", examples: "financials · dividend · share_float · holders" },
    { id: "indices", title: "Indices & funds", description: "Index constituents, weights, daily observations, ETF reference, and creation/redemption material.", examples: "index · constituent · weight · etf" },
  ];
  const alternativeGroups = locale === "zh" ? [
    { title: "公司与监管信息", description: "公告、董秘问答、券商研报及公司事件文本。", examples: "announcements · Q&A · broker research" },
    { title: "新闻与政策", description: "新闻快讯、政策法规、央行报告与宏观发布。", examples: "news · policy · central bank reports" },
    { title: "市场关注与互动", description: "客观覆盖度、互动和来源标记，不生成情绪信号或交易建议。", examples: "coverage · interaction · source metadata" },
  ] : [
    { title: "Company & regulatory intelligence", description: "Announcements, secretary Q&A, broker research, and company-event text.", examples: "announcements · Q&A · broker research" },
    { title: "News & policy", description: "News flashes, regulations, central-bank reports, and macro releases.", examples: "news · policy · central bank reports" },
    { title: "Attention & interaction", description: "Objective coverage and interaction metadata—never sentiment signals or trading advice.", examples: "coverage · interaction · source metadata" },
  ];
  const packageCards = locale === "zh" ? [
    { name: "A 股研究包", audience: "基本面、行业与事件研究", includes: ["日线与复权", "财务与公司行动", "指数与基础参考", "标准 Catalog / Query 访问"] },
    { name: "量化系统包", audience: "因子、横截面与历史回测准备", includes: ["包含研究包全部数据", "历史分钟与集合竞价", "ETF / 指数分钟", "更高运行限额（以后端为准）"] },
    { name: "交易数据包", audience: "盘中观察与交易系统数据准备", includes: ["包含量化系统包全部数据", "A 股 / ETF / 指数实时数据候选", "分钟级实时数据候选", "最高运行限额（以后端为准）"] },
  ] : [
    { name: "A-share Research", audience: "Fundamental, industry, and event research", includes: ["Daily & adjusted prices", "Financials & corporate actions", "Indices & reference", "Standard Catalog / Query access"] },
    { name: "Systematic Research", audience: "Factor, cross-sectional, and historical-test preparation", includes: ["Everything in A-share Research", "Historical minutes & auctions", "ETF / index minutes", "Higher runtime limits (backend-defined)"] },
    { name: "Trading Data", audience: "Intraday observation and trading-system data preparation", includes: ["Everything in Systematic Research", "Candidate A-share / ETF / index real-time data", "Candidate real-time minute data", "Highest runtime limits (backend-defined)"] },
  ];
  const readingSteps = locale === "zh" ? [
    ["01", "先看研究问题", "这篇内容试图解释、测量或重建什么。"],
    ["02", "再看证据与数据", "需要哪些市场、财务、另类数据和时间窗口。"],
    ["03", "理解方法与限制", "识别对齐、样本、假设以及不能外推的部分。"],
    ["04", "进入 Data 与 Cookbook", "找到对应数据材料和可复现的数据准备方法。"],
  ] : [
    ["01", "Start with the question", "What is the work trying to explain, measure, or reconstruct?"],
    ["02", "Inspect evidence and data", "Which market, fundamental, alternative datasets, and time windows are required?"],
    ["03", "Understand method and limits", "Identify alignment, samples, assumptions, and what cannot be generalized."],
    ["04", "Continue in Data and Cookbook", "Find the matching raw materials and reproducible preparation method."],
  ];
  const docsCategories = locale === "zh" ? [
    { key: "start", label: "开始使用", items: [["平台概览", "了解 Data、Research、Cookbook、Pricing、Docs 与 Account 的关系。"], ["首次接入", "创建账户、选择套餐、生成密钥并完成第一条 Catalog 查询。"]] },
    { key: "data", label: "数据说明", items: [["数据分类与模板", "市场、domain、字段、覆盖、更新时间与 receipt 的统一结构。"], ["另类数据", "来源、再分发边界、试用、加购和授权读回。"], ["数据凭证", "如何阅读 source、quality、freshness、coverage 与 receipt。"]] },
    { key: "api", label: "API 与 Agent", items: [["Catalog", "发现已授权数据集及其结构、覆盖与限制。"], ["Query", "字段、游标、预算、错误和 fail-closed 行为。"], ["Agent 与 MCP", "Claude、Codex、OpenClaw、Hermes 的安全接入说明。"]] },
    { key: "learn", label: "学习与方法", items: [["Research 阅读指南", "如何阅读外部论文、行业研究和案例。"], ["Cookbook 方法", "查询、连接、时点对齐、复权、缺失与验证。"]] },
    { key: "commerce", label: "套餐与账户", items: [["套餐比较", "A 股研究、量化系统与交易数据包的范围。"], ["订阅与账单", "有效期、试用、加购、续费、账单和发票。"], ["账户与安全", "用量、密钥、会话、语言、主题与访问审计。"]] },
  ] : [
    { key: "start", label: "Get started", items: [["Platform overview", "How Data, Research, Cookbook, Pricing, Docs, and Account fit together."], ["First connection", "Create an account, choose a package, generate a key, and make the first Catalog request."]] },
    { key: "data", label: "Data guide", items: [["Classification & template", "The shared market, domain, field, coverage, update, and receipt structure."], ["Alternative data", "Source, redistribution boundary, trial, add-on, and entitlement readback."], ["Data receipts", "How to read source, quality, freshness, coverage, and receipt evidence."]] },
    { key: "api", label: "API & Agents", items: [["Catalog", "Discover authorized datasets, schemas, coverage, and limitations."], ["Query", "Fields, cursors, budgets, errors, and fail-closed behavior."], ["Agents & MCP", "Safe setup for Claude, Codex, OpenClaw, Hermes, and other Agents."]] },
    { key: "learn", label: "Learning & methods", items: [["Research reading guide", "How to read external papers, industry research, and cases."], ["Cookbook methods", "Querying, joins, point-in-time alignment, adjustment, missingness, and validation."]] },
    { key: "commerce", label: "Plans & account", items: [["Compare packages", "Scope of A-share Research, Systematic Research, and Trading Data."], ["Subscription & billing", "Expiry, trials, add-ons, renewal, billing, and invoices."], ["Account & security", "Usage, keys, sessions, language, appearance, and access audit."]] },
  ];
  const allDocs = docsCategories.flatMap((category) => category.items.map(([title, description], index) => ({ category: category.key, categoryLabel: category.label, title, description, slug: `${category.key}-${index + 1}` })));
  const visibleDocs = allDocs.filter((entry) => {
    const matchesCategory = docsCategory === "all" || entry.category === docsCategory;
    return matchesCategory && `${entry.title} ${entry.description} ${entry.categoryLabel}`.toLowerCase().includes(docsQuery.trim().toLowerCase());
  });
  const selectedDoc = allDocs.find((entry) => entry.slug === routeSlug);
  const activeAccountItem = accountGroups.flatMap((group) => group.items).find((item) => item.key === accountSection) || accountGroups[0].items[0];

  const selectedDataset = productManifest.objects.datasets.find((item) => item.id === routeSlug);
  const selectedFeature = productManifest.objects.features.find((item) => item.id === routeSlug);
  const selectedRecipe = productManifest.objects.recipes.find((item) => item.id === routeSlug);
  const selectedPaper = routeSlug ? papers.find((paper) => paper.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") === routeSlug) : null;

  return (
    <div className={`site-shell route-${primaryRoute}`} id="top">
      <header className={`global-header ${primaryRoute === "home" ? "" : "is-page-header"}`}>
        <Brand onNavigate={navigate} />
        <nav className="desktop-nav" aria-label="Primary navigation">
          {copy.nav.map((label, index) => <a key={label} href={navPaths[index]} onClick={(event) => navigate(event, navPaths[index])} aria-current={primaryRoute === sections[index] ? "page" : undefined}>{label}</a>)}
        </nav>
        <div className="header-actions">
          <div className="popover-wrap account-wrap">
            <a className="icon-button account-button" href="/account" aria-label={copy.account} aria-current={primaryRoute === "account" ? "page" : undefined} onClick={(event) => navigate(event, "/account")}><UserCircle size={30} weight="thin" /></a>
          </div>
          <button className="icon-button mobile-menu-button" type="button" aria-label={copy.menu} onClick={() => setMobileOpen((value) => !value)}>{mobileOpen ? <X size={24} /> : <List size={24} />}</button>
        </div>
        {mobileOpen && <nav className="mobile-nav" aria-label="Mobile navigation">{copy.nav.map((label, index) => <a key={label} href={navPaths[index]} onClick={(event) => navigate(event, navPaths[index])}>{label}<ArrowRight /></a>)}</nav>}
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

        {primaryRoute === "data" && !routeSlug && <div className="data-page" id="data">
          <SectionNav locale={locale} active="/data" onNavigate={navigate} items={locale === "zh" ? [
            { path: "/data", label: "全部数据" }, { path: "/data/alternative", label: "另类数据" }, { path: "/data/receipts", label: "凭证与覆盖" },
          ] : [
            { path: "/data", label: "All data" }, { path: "/data/alternative", label: "Alternative data" }, { path: "/data/receipts", label: "Receipts & coverage" },
          ]} />
          <section className="page-hero data-page-hero">
            <span className="mono-kicker">DATA CATALOG / A-SHARE FIRST</span>
            <h1>{locale === "zh" ? "先理解数据，再决定如何使用。" : "Know the material before you query it."}</h1>
            <p>{locale === "zh" ? "TradingDatas 把 A 股原始数据按研究与交易工作所需的材料分类，并为每个数据集说明结构、覆盖、更新与来源凭证。" : "TradingDatas organizes raw A-share data around the materials research and trading work actually needs—with schema, coverage, updates, and source receipts made explicit."}</p>
          </section>

          <section className="data-taxonomy">
            <div className="section-heading compact-heading">
              <span className="mono-kicker">01 / CORE MATERIALS</span>
              <h2>{locale === "zh" ? "我们有哪些数据？" : "What data do we provide?"}</h2>
              <p>{locale === "zh" ? "分类面向用户任务；底层 Catalog 仍保留 market 与 domain 等标准合同。" : "Categories are designed for user tasks; the underlying Catalog retains standard market and domain contracts."}</p>
            </div>
            <div className="data-category-grid">
              {dataGroups.map((group, index) => <article className="data-category-card" key={group.id}>
                <span>0{index + 1}</span><h3>{group.title}</h3><p>{group.description}</p><code>{group.examples}</code>
              </article>)}
            </div>
          </section>

          <section className="data-template-section">
            <div className="section-intro">
              <span className="mono-kicker">02 / SHARED DATA TEMPLATE</span>
              <h2>{locale === "zh" ? "每种数据，都有可读的统一说明。" : "Every dataset follows a readable contract."}</h2>
              <p>{locale === "zh" ? "用户无需先理解不同上游接口。每个 Catalog 条目说明数据身份、所属市场、内容领域、时间覆盖、更新时间、字段与可验证 receipt。" : "Users do not need to decode upstream APIs first. Every Catalog entry describes identity, market, domain, time coverage, update cadence, fields, and a verifiable receipt."}</p>
            </div>
            <div className="template-contract" aria-label={locale === "zh" ? "数据模板示例" : "Dataset template example"}>
              {[
                ["dataset_id", "cn.equity.daily"], ["market / domain", "CN / a_share"], ["coverage", "2010-01-04 → 2026-08-26"],
                ["cadence", "postclose_daily"], ["fields", "symbol · trade_date · open · close …"], ["receipt_id", "rcpt_9f3b7e21…"],
              ].map(([label, value]) => <div key={label}><span>{label}</span><code>{value}</code></div>)}
            </div>
          </section>

          <section className="object-index-section">
            <div className="section-heading compact-heading"><span className="mono-kicker">DATASET OBJECTS / EXAMPLE CONTRACTS</span><h2>{locale === "zh" ? "从数据族进入可验证的数据集对象。" : "Move from a family into a verifiable dataset object."}</h2><p>{locale === "zh" ? "这些条目用于演示内页结构；状态标签不会替代真实 Catalog 与 receipt。" : "These entries demonstrate detail-page structure; status labels never replace the live Catalog and receipts."}</p></div>
            <div className="object-list">{productManifest.objects.datasets.map((item) => <a key={item.id} href={`/datasets/${item.id}`} onClick={(event) => navigate(event, `/datasets/${item.id}`)}><div><MaturityTag status={item.status} locale={locale} /><h3>{item.title[locale]}</h3><p>{item.detail}</p></div><ArrowRight /></a>)}</div>
          </section>

          <section className="receipt-section data-receipt-section">
            <div className="section-intro">
              <span className="mono-kicker">03 / PROVENANCE / QUALITY / COVERAGE</span>
              <h2>{copy.receipts}</h2><p>{copy.receiptsCopy}</p>
              <a href="/docs" className="text-link" onClick={(event) => navigate(event, "/docs")}>{copy.receiptAction}<ArrowRight /></a>
            </div>
            <ReceiptProof copy={copy} />
          </section>

          <section className="alternative-data-section">
            <div className="section-heading compact-heading">
              <span className="mono-kicker">04 / ALTERNATIVE DATA ADD-ONS</span>
              <h2>{locale === "zh" ? "另类数据独立选择，独立授权。" : "Alternative data stays separately chosen and entitled."}</h2>
              <p>{locale === "zh" ? "基础套餐用户可获得限定试用；试用结束后，由用户选择是否加购。来源与再分发边界会在下单前展示。" : "Package users may receive a limited trial. After it ends, add-on access is an explicit choice, with source and redistribution boundaries shown before ordering."}</p>
            </div>
            <div className="alternative-grid">{alternativeGroups.map((group) => <article key={group.title}><h3>{group.title}</h3><p>{group.description}</p><code>{group.examples}</code></article>)}</div>
            <div className="order-flow">
              {(locale === "zh" ? [["01", "选择加购", "查看包含的数据集与来源"], ["02", "确认试用与有效期", "核对开始、结束与续费选择"], ["03", "登录并下单", "价格与支付以后端合同为准"], ["04", "读取授权", "账户中确认数据分类与到期日"]] : [["01", "Choose an add-on", "Review included datasets and sources"], ["02", "Confirm trial & term", "Check start, expiry, and renewal choice"], ["03", "Sign in & order", "Price and payment are backend-defined"], ["04", "Read back access", "Confirm categories and expiry in Account"]]).map(([index, title, text]) => <div key={index}><span>{index}</span><strong>{title}</strong><small>{text}</small></div>)}
              <a className="primary-button" href="/pricing" onClick={(event) => navigate(event, "/pricing")}>{locale === "zh" ? "查看套餐与加购" : "View packages & add-ons"}<ArrowRight /></a>
            </div>
            <p className="commercial-disclaimer">{locale === "zh" ? "商业界面提案 · 真实价格、试用期与可购买范围尚待 commerce backend 合同确认。" : "Commercial surface proposal · Live prices, trial periods, and purchasable scope remain subject to the commerce backend contract."}</p>
          </section>
        </div>}

        {primaryRoute === "datasets" && <ProductObjectDetail type="datasets" item={selectedDataset} locale={locale} onNavigate={navigate} />}

        {primaryRoute === "data" && routeSlug === "alternative" && <section className="object-detail-page"><SectionNav locale={locale} active="/data/alternative" onNavigate={navigate} items={locale === "zh" ? [{ path: "/data", label: "全部数据" }, { path: "/data/alternative", label: "另类数据" }, { path: "/data/receipts", label: "凭证与覆盖" }] : [{ path: "/data", label: "All data" }, { path: "/data/alternative", label: "Alternative data" }, { path: "/data/receipts", label: "Receipts & coverage" }]} /><div className="object-detail-hero"><div><span className="mono-kicker">ALTERNATIVE DATA / SEPARATE ADD-ONS</span><h1>{locale === "zh" ? "第三方来源，清洗交付，单独授权。" : "Third-party sourced, cleanly delivered, separately entitled."}</h1><p>{locale === "zh" ? "按来源、许可、覆盖和更新方式理解每一种另类数据；套餐试用与后续加购保持显式。" : "Understand every alternative dataset by source, license, coverage, and update model; package trials and later add-ons stay explicit."}</p></div><MaturityTag status="product_definition" locale={locale} /></div><div className="alternative-grid">{alternativeGroups.map((group) => <article key={group.title}><h3>{group.title}</h3><p>{group.description}</p><code>{group.examples}</code></article>)}</div><section className="object-boundary"><h2>{locale === "zh" ? "购买前必须可见" : "Visible before purchase"}</h2><p>{locale === "zh" ? "来源、许可与再分发边界、样例字段、历史覆盖、更新频率、试用期限、价格、到期与续费选择。" : "Source, license and redistribution boundary, sample fields, history, cadence, trial term, price, expiry, and renewal choice."}</p><a className="primary-button" href="/pricing/alternative" onClick={(event) => navigate(event, "/pricing/alternative")}>{locale === "zh" ? "查看加购逻辑" : "Review add-on logic"}<ArrowRight /></a></section></section>}

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

        {primaryRoute === "research" && !routeSlug && <div className="research-page" id="research"><section className="research-section">
          <SectionNav locale={locale} active="/research" onNavigate={navigate} items={locale === "zh" ? [{ path: "/research", label: "全部研究" }, { path: "/research?topic=a-share", label: "A 股" }, { path: "/research?format=paper", label: "论文" }, { path: "/research?format=case", label: "案例" }] : [{ path: "/research", label: "All research" }, { path: "/research?topic=a-share", label: "A-share" }, { path: "/research?format=paper", label: "Papers" }, { path: "/research?format=case", label: "Cases" }]} />
          <div className="research-intro">
            <span className="mono-kicker">RESEARCH LIBRARY / EXTERNAL LITERATURE</span>
            <h2>{copy.researchTitle}</h2>
            <p>{copy.researchCopy}</p>
            <div className="research-notice"><GraduationCap weight="duotone" />{copy.researchNotice}</div>
            <div className="reading-guide">
              <span className="filter-label">{locale === "zh" ? "如何阅读" : "HOW TO READ"}</span>
              {readingSteps.map(([index, title, description]) => <div className="reading-step" key={index}><span>{index}</span><div><strong>{title}</strong><p>{description}</p></div></div>)}
            </div>
          </div>
          <div className="research-library">
            <label className="research-search">
              <MagnifyingGlass size={19} />
              <span className="sr-only">{copy.researchSearch}</span>
              <input value={researchQuery} onChange={(event) => setResearchQuery(event.target.value)} placeholder={copy.researchSearch} />
            </label>
            <span className="filter-label">{locale === "zh" ? "内容形式" : "FORMAT"}</span>
            <div className="research-topics research-kinds" aria-label="Research formats">
              {copy.researchKinds.map(([kind, label]) => <button key={kind} type="button" className={researchKind === kind ? "is-active" : ""} onClick={() => setResearchKind(kind)}>{label}</button>)}
            </div>
            <span className="filter-label">{locale === "zh" ? "研究主题" : "TOPIC"}</span>
            <div className="research-topics" aria-label="Research topics">
              {copy.researchTopics.map(([topic, label]) => (
                <button key={topic} type="button" className={researchTopic === topic ? "is-active" : ""} onClick={() => setResearchTopic(topic)}>{label}</button>
              ))}
            </div>
            <div className="research-count"><span>{String(visiblePapers.length).padStart(2, "0")}</span>{copy.researchResults}</div>
            <div className="paper-list">
              {visiblePapers.length ? visiblePapers.map((paper, index) => (
                <article className="paper-row" key={paper.title}>
                  <span className="paper-index">{String(index + 1).padStart(2, "0")}</span>
                  <div className="paper-main">
                    <div className="paper-meta"><span>{kindLabels[paper.kind]}</span><span>{topicLabels[paper.topic]}</span><span>{paper.year}</span><span>{paper.venue}</span></div>
                    <h3>{paper.title}</h3>
                    <p>{paper.authors}</p>
                    <p className="paper-summary">{paper.summary[locale]}</p>
                    <div className="paper-data"><span>{copy.requiredData}</span><code>{paper.data}</code></div>
                  </div>
                  <a href={`/research/${paper.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")}`} onClick={(event) => navigate(event, `/research/${paper.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")}`)} aria-label={`${locale === "zh" ? "阅读 TradingDatas 整理页" : "Read TradingDatas record"}: ${paper.title}`}><ArrowRight /></a>
                </article>
              )) : <div className="research-empty">{copy.researchEmpty}</div>}
            </div>
          </div>
        </section></div>}

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
          <SectionNav locale={locale} active="/pricing" onNavigate={navigate} items={locale === "zh" ? [{ path: "/pricing", label: "套餐比较" }, { path: "/pricing/alternative", label: "另类数据加购" }, { path: "/pricing/beta", label: "申请内测" }] : [{ path: "/pricing", label: "Compare plans" }, { path: "/pricing/alternative", label: "Alternative add-ons" }, { path: "/pricing/beta", label: "Request beta" }]} />
          <div className="section-heading">
            <span className="mono-kicker">PACKAGES / A-SHARE FIRST</span>
            <h2>{copy.pricingTitle}</h2>
            <p>{copy.pricingCopy}</p>
          </div>
          <div className="package-grid">
            {packageCards.map((plan, index) => <article className="package-card" key={plan.name}>
              <div className="package-card-head"><span>0{index + 1}</span><small>{locale === "zh" ? "A 股场景套餐" : "A-SHARE WORKFLOW"}</small></div>
              <h3>{plan.name}</h3><p>{plan.audience}</p>
              <ul>{plan.includes.map((item) => <li key={item}><Check weight="bold" />{item}</li>)}</ul>
              <div className="package-status"><strong>{locale === "zh" ? "套餐定义中" : "Package definition"}</strong><span>{locale === "zh" ? "价格与最终权限待后端确认" : "Price and final entitlements pending"}</span></div>
              <a href="/pricing/beta" onClick={(event) => navigate(event, "/pricing/beta")}>{locale === "zh" ? "申请内测" : "Request private beta"}<ArrowRight /></a>
            </article>)}
          </div>
          <section className="pricing-addons">
            <div><span className="mono-kicker">ALTERNATIVE DATA / OPTIONAL</span><h2>{locale === "zh" ? "另类数据不塞进套餐。" : "Alternative data is never forced into a package."}</h2><p>{locale === "zh" ? "基础套餐保持清晰。你可以试用指定另类数据，到期后再决定是否按类别加购。" : "Base packages stay clear. Trial selected alternative data, then decide by category whether to add it after expiry."}</p></div>
            <div className="addon-list">{alternativeGroups.map((group) => <article key={group.title}><h3>{group.title}</h3><p>{group.description}</p><span>{locale === "zh" ? "试用与单独加购 · 待后端合同" : "Trial & separate add-on · backend contract pending"}</span></article>)}</div>
          </section>
          <p className="commercial-disclaimer">{locale === "zh" ? "本页是产品套餐结构提案，不代表已上线价格、实时权限或完成支付。" : "This page is a product-package proposal, not evidence of live pricing, real-time entitlement, or completed payment."}</p>
        </section>}

        {primaryRoute === "pricing" && routeSlug === "alternative" && <section className="object-detail-page"><SectionNav locale={locale} active="/pricing/alternative" onNavigate={navigate} items={locale === "zh" ? [{ path: "/pricing", label: "套餐比较" }, { path: "/pricing/alternative", label: "另类数据加购" }, { path: "/pricing/beta", label: "申请内测" }] : [{ path: "/pricing", label: "Compare plans" }, { path: "/pricing/alternative", label: "Alternative add-ons" }, { path: "/pricing/beta", label: "Request beta" }]} /><div className="object-detail-hero"><div><span className="mono-kicker">ALTERNATIVE DATA / OPTIONAL</span><h1>{locale === "zh" ? "先试用，再明确选择是否加购。" : "Trial first, then explicitly choose whether to add it."}</h1><p>{locale === "zh" ? "另类数据按类别、来源和授权范围单独展示，不用复杂的逐接口自选。" : "Alternative data is presented by category, source, and entitlement—not as a maze of per-endpoint choices."}</p></div><MaturityTag status="product_definition" locale={locale} /></div><div className="alternative-grid">{alternativeGroups.map((group) => <article key={group.title}><h2>{group.title}</h2><p>{group.description}</p><code>{group.examples}</code></article>)}</div><p className="commercial-disclaimer">{locale === "zh" ? "试用期限、价格、支付、续费和可购买范围等待 commerce backend 合同。" : "Trial term, price, payment, renewal, and purchasable scope await the commerce backend contract."}</p></section>}

        {primaryRoute === "pricing" && routeSlug === "beta" && <section className="object-detail-page"><SectionNav locale={locale} active="/pricing/beta" onNavigate={navigate} items={locale === "zh" ? [{ path: "/pricing", label: "套餐比较" }, { path: "/pricing/alternative", label: "另类数据加购" }, { path: "/pricing/beta", label: "申请内测" }] : [{ path: "/pricing", label: "Compare plans" }, { path: "/pricing/alternative", label: "Alternative add-ons" }, { path: "/pricing/beta", label: "Request beta" }]} /><div className="object-detail-hero"><div><span className="mono-kicker">PRIVATE BETA / HONEST CONVERSION</span><h1>{locale === "zh" ? "告诉我们你的数据工作流。" : "Tell us about your data workflow."}</h1><p>{locale === "zh" ? "在价格、支付和自动授权完成前，申请内测是唯一真实的商业入口。" : "Before pricing, payment, and automatic entitlement are implemented, private-beta access is the only honest commercial entry."}</p></div><MaturityTag status="product_definition" locale={locale} /></div><div className="beta-intake"><label>{locale === "zh" ? "主要用途" : "Primary use"}<select><option>{locale === "zh" ? "基本面与行业研究" : "Fundamental and industry research"}</option><option>{locale === "zh" ? "量化数据准备" : "Systematic data preparation"}</option><option>{locale === "zh" ? "交易系统数据" : "Trading-system data"}</option></select></label><label>{locale === "zh" ? "最需要的数据" : "Most-needed data"}<input placeholder={locale === "zh" ? "例如：时点一致财务、分钟、公告" : "e.g. PIT fundamentals, minutes, announcements"} /></label><button className="primary-button" type="button" disabled>{locale === "zh" ? "提交功能待接后端" : "Submission awaits backend"}</button></div></section>}

        {primaryRoute === "docs" && !routeSlug && <section className="docs-hub" id="docs">
          <SectionNav locale={locale} active="/docs" onNavigate={navigate} items={locale === "zh" ? [{ path: "/docs", label: "文档首页" }, { path: "/docs/data-1", label: "数据模型" }, { path: "/docs/api-1", label: "Catalog" }, { path: "/docs/commerce-1", label: "套餐" }] : [{ path: "/docs", label: "Docs home" }, { path: "/docs/data-1", label: "Data model" }, { path: "/docs/api-1", label: "Catalog" }, { path: "/docs/commerce-1", label: "Plans" }]} />
          <div className="docs-hub-hero">
            <span className="mono-kicker">PLATFORM GUIDE / DATA / API / ACCOUNT</span>
            <h1>{locale === "zh" ? "理解并使用 TradingDatas 的所有说明。" : "Everything needed to understand and use TradingDatas."}</h1>
            <p>{locale === "zh" ? "Docs 汇集网站各板块、数据合同、Agent 接入、套餐与账户的说明；API 只是其中一个部分。" : "Docs brings together guidance for every product area, data contract, Agent connection, package, and account workflow. API is one part—not the whole hub."}</p>
            <label className="docs-search"><MagnifyingGlass size={20} /><span className="sr-only">{locale === "zh" ? "搜索文档" : "Search documentation"}</span><input value={docsQuery} onChange={(event) => setDocsQuery(event.target.value)} placeholder={locale === "zh" ? "搜索数据、API、套餐或账户说明" : "Search data, API, plans, or account guidance"} /></label>
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

        {primaryRoute === "account" && (
          <section className="account-page">
            <div className="account-page-heading">
              <span className="mono-kicker">ACCOUNT / DATA ACCESS / INTEGRATIONS</span>
              <h1>{locale === "zh" ? "你的 TradingDatas 工作区。" : "Your TradingDatas workspace."}</h1>
              <p>{locale === "zh" ? "账户只负责管理数据访问、Agent 接入、账单和个人设置；研究内容与数据目录保持独立。" : "Account is for data access, Agent connections, billing, and personal settings. Research content and the data catalog stay separate."}</p>
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
                  <span className="account-surface-label">{locale === "zh" ? "产品界面 · 待接后端" : "PRODUCT SURFACE · BACKEND PENDING"}</span>
                  <h2>{activeAccountItem.label}</h2>
                  <p>{activeAccountItem.description}</p>
                </div>
                {accountSection === "preferences" ? (
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
                ) : (
                  <dl className="account-facts">
                    <div><dt>{locale === "zh" ? "权威来源" : "Authority"}</dt><dd>{accountSection === "billing" ? "Commerce / billing contract" : "Customer Portal API"}</dd></div>
                    <div><dt>{locale === "zh" ? "当前状态" : "Current state"}</dt><dd>{locale === "zh" ? "原型界面，尚未连接真实账户数据" : "Prototype surface; live account data is not connected"}</dd></div>
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
