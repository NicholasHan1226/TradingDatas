const sampleContract = {
  fields: 0,
  sampleRows: [["sample", "contract", "preview", "only", "not live"]],
};

const productIcons = {
  market: "/assets/data-products/market-daily.png",
  fundamentals: "/assets/data-products/fundamentals.png",
  events: "/assets/data-products/announcements.png",
  funds: "/assets/data-products/funds-v2.png",
  macro: "/assets/data-products/macro-v2.png",
  text: "/assets/data-products/text-v2.png",
  alternative: "/assets/data-products/alternative.png",
  global: "/assets/data-products/global-v2.png",
  crypto: "/assets/data-products/crypto-v2.png",
};

function plannedDataset({ id, title, description, family, category, market, detail, tags, cadence, plan, source }) {
  return {
    ...sampleContract,
    id,
    title,
    description,
    family,
    category,
    market,
    status: plan.startsWith("Wave 1") || plan.startsWith("Isolated provider slice") ? "pending_open" : "planned",
    detail,
    icon: productIcons[family],
    tags,
    cadence,
    plan,
    coverage: "planned scope · not collected",
    lastSuccess: "collection not started",
    stability: "—",
    stabilityNote: { en: "collection history not yet observed", zh: "尚未开始采集，暂无稳定性历史" },
    delayedDays: [],
    source,
    receipt: "no observed receipt",
    sampleColumns: ["observed_at", "entity_id", "value", "source", "receipt_id"],
  };
}

export const productManifest = {
  status: "design_contract",
  generatedAt: null,
  note: "Navigation and content prototype only; not runtime availability authority.",
  objects: {
    datasets: [
      {
        id: "cn-equity-daily",
        title: { en: "A-share daily bars", zh: "A 股日线行情" },
        description: { en: "Daily OHLCV, turnover, adjustment inputs, and trading-session reference for listed A-share securities.", zh: "覆盖 A 股上市证券的日线 OHLCV、成交额、复权输入与交易日参考。" },
        family: "market",
        category: { en: "Market data", zh: "行情数据" },
        market: "CN",
        status: "observed_example",
        detail: "daily prices · adjustment inputs · trading calendar",
        icon: "/assets/data-products/market-daily.png",
        tags: ["OHLCV", "adjustment inputs", "trading calendar"],
        cadence: "postclose_daily",
        plan: "Observed example · runtime readback required",
        coverage: "2010-01-04 → 2026-08-26",
        lastSuccess: "2026-08-26 18:04 CST",
        stability: "99.98%",
        stabilityNote: { en: "illustrative 30-day receipt window", zh: "示意性 30 日 receipt 窗口" },
        delayedDays: [27],
        source: "SSE · SZSE · provider-native payload",
        receipt: "rcpt_9f3b7e21…14c8d2a7",
        fields: 27,
        sampleColumns: ["trade_date", "ts_code", "open", "close", "volume"],
        sampleRows: [
          ["2026-08-26", "600519.SH", "1586.00", "1592.22", "1,245,678"],
          ["2026-08-26", "000001.SZ", "9.67", "9.71", "287,654,321"],
          ["2026-08-25", "300750.SZ", "123.45", "124.38", "6,543,210"],
        ],
      },
      plannedDataset({ id: "cn-equity-minute", title: { en: "A-share historical minutes", zh: "A 股历史分钟" }, description: { en: "Minute OHLCV prepared for bounded historical queries.", zh: "用于有界历史查询的分钟级 OHLCV 原始数据。" }, family: "market", category: { en: "Market data", zh: "行情数据" }, market: "CN", detail: "1m/5m bars · session boundaries", tags: ["minute", "OHLCV", "sessions"], cadence: "session_minute", plan: "Wave 1 · permission probe", source: "Tushare contract via QuickSync · permission unknown" }),
      plannedDataset({ id: "cn-auction-premarket", title: { en: "Auction & pre-market", zh: "集合竞价与盘前" }, description: { en: "Opening auction transactions, indicative prices, and pre-market capital reference.", zh: "集合竞价成交、指示价格与盘前股本参考。" }, family: "market", category: { en: "Market data", zh: "行情数据" }, market: "CN", detail: "auction · pre-market · opening state", tags: ["auction", "premarket", "opening"], cadence: "session_minute", plan: "Wave 1 · contract and permission", source: "Tushare contract via QuickSync · permission unknown" }),
      plannedDataset({ id: "cn-market-reference", title: { en: "Market reference & adjustments", zh: "市场基础与复权" }, description: { en: "Trading calendar, instruments, suspension states, and adjustment inputs.", zh: "交易日历、证券主数据、停复牌状态与复权输入。" }, family: "market", category: { en: "Market data", zh: "行情数据" }, market: "CN", detail: "calendar · instruments · adjustments", tags: ["reference", "calendar", "adjustments"], cadence: "daily_reference", plan: "Wave 1 · registry batch", source: "Tushare contract via QuickSync · permission unknown" }),
      plannedDataset({ id: "cn-market-realtime", title: { en: "A-share real-time snapshot", zh: "A 股实时快照" }, description: { en: "Current market snapshots for entitled downstream observation.", zh: "面向已授权下游观察场景的实时行情快照。" }, family: "market", category: { en: "Market data", zh: "行情数据" }, market: "CN", detail: "snapshot · quote · session state", tags: ["real-time", "snapshot", "quotes"], cadence: "session_minute", plan: "Wave 4 · commercial rights required", source: "licensed market-data source required" }),

      plannedDataset({ id: "cn-pit-fundamentals", title: { en: "Point-in-time fundamentals", zh: "时点一致财务数据" }, description: { en: "Statements organized around publication time, revisions, and restatements.", zh: "围绕披露时点、修订与重述组织的财务报表原料。" }, family: "fundamentals", category: { en: "Company & fundamentals", zh: "公司与财务" }, market: "CN", detail: "as-of · revisions · restatements", tags: ["financials", "as-of", "restatements"], cadence: "quarterly_reporting", plan: "Wave 2 · schema and as-of rules", source: "Tushare contract via QuickSync · permission unknown" }),
      plannedDataset({ id: "cn-company-master", title: { en: "Company master & industry", zh: "公司主数据与行业" }, description: { en: "Company identity, listing history, industry, location, and status changes.", zh: "公司身份、上市历史、行业、地域与状态变化。" }, family: "fundamentals", category: { en: "Company & fundamentals", zh: "公司与财务" }, market: "CN", detail: "identity · industry · listing history", tags: ["company", "industry", "master data"], cadence: "daily_reference", plan: "Wave 1 · registry batch", source: "Tushare contract via QuickSync · permission unknown" }),
      plannedDataset({ id: "cn-ownership-holdings", title: { en: "Ownership & holdings", zh: "股东与持仓结构" }, description: { en: "Major holders, fund holdings, pledges, and ownership changes.", zh: "主要股东、基金持仓、质押与所有权变化。" }, family: "fundamentals", category: { en: "Company & fundamentals", zh: "公司与财务" }, market: "CN", detail: "holders · pledges · fund positions", tags: ["holders", "ownership", "pledges"], cadence: "quarterly_reporting", plan: "Wave 2 · permission and PIT review", source: "Tushare contract via QuickSync · permission unknown" }),
      plannedDataset({ id: "cn-valuation-indicators", title: { en: "Valuation & financial indicators", zh: "估值与财务指标" }, description: { en: "Daily valuation ratios and reported financial indicators with source lineage.", zh: "带来源血缘的日频估值比率与披露财务指标。" }, family: "fundamentals", category: { en: "Company & fundamentals", zh: "公司与财务" }, market: "CN", detail: "valuation · ratios · reported indicators", tags: ["valuation", "ratios", "indicators"], cadence: "postclose_daily", plan: "Wave 2 · normalization contract", source: "Tushare contract via QuickSync · permission unknown" }),

      plannedDataset({ id: "cn-company-actions", title: { en: "Company actions", zh: "公司行动" }, description: { en: "Dividends, capital changes, suspensions, listings, and dated corporate events.", zh: "分红、股本变化、停复牌、上市状态与其它公司事件。" }, family: "events", category: { en: "Corporate events", zh: "公司事件" }, market: "CN", detail: "dividends · capital changes · suspensions", tags: ["dividends", "capital", "suspensions"], cadence: "event", plan: "Wave 2 · event identity contract", source: "Tushare contract via QuickSync · permission unknown" }),
      plannedDataset({ id: "cn-announcements", title: { en: "Listed-company announcements", zh: "上市公司公告" }, description: { en: "Announcement metadata, documents, publication time, and source identity.", zh: "公告元数据、文档、披露时间与来源身份。" }, family: "events", category: { en: "Corporate events", zh: "公司事件" }, market: "CN", detail: "announcement · document · publish time", tags: ["announcements", "documents", "events"], cadence: "event", plan: "Wave 3 · document rights and extraction", source: "exchange/company disclosures · redistribution review" }),
      plannedDataset({ id: "cn-secretary-qa", title: { en: "Investor Q&A", zh: "董秘互动问答" }, description: { en: "Timestamped investor questions and company responses with source links.", zh: "带时间戳和来源链接的投资者提问与公司回复。" }, family: "events", category: { en: "Corporate events", zh: "公司事件" }, market: "CN", detail: "questions · answers · timestamps", tags: ["Q&A", "interaction", "source links"], cadence: "event", plan: "Wave 3 · license review", source: "exchange interaction platforms · redistribution review" }),
      plannedDataset({ id: "cn-ipo-calendar", title: { en: "IPO & listing calendar", zh: "IPO 与上市日历" }, description: { en: "Application, issuance, subscription, allotment, and listing milestones.", zh: "申报、发行、申购、配售与上市里程碑。" }, family: "events", category: { en: "Corporate events", zh: "公司事件" }, market: "CN", detail: "IPO · issuance · listing milestones", tags: ["IPO", "calendar", "listing"], cadence: "event", plan: "Wave 2 · event normalization", source: "exchange and Tushare contracts · permission unknown" }),

      plannedDataset({ id: "cn-index-constituents", title: { en: "Index constituents & weights", zh: "指数成分与权重" }, description: { en: "Index membership, weights, adjustment dates, and reference history.", zh: "指数成分、权重、调整日期与参考历史。" }, family: "funds", category: { en: "Indices & funds", zh: "指数与基金" }, market: "CN", detail: "constituents · weights · rebalance", tags: ["index", "weights", "rebalance"], cadence: "monthly", plan: "Wave 2 · provider contract", source: "index-provider rights required" }),
      plannedDataset({ id: "cn-etf-nav-iopv", title: { en: "ETF NAV & IOPV", zh: "ETF 净值与 IOPV" }, description: { en: "ETF NAV, IOPV, creation/redemption reference, and trading metadata.", zh: "ETF 净值、IOPV、申赎参考与交易元数据。" }, family: "funds", category: { en: "Indices & funds", zh: "指数与基金" }, market: "CN", detail: "NAV · IOPV · creation/redemption", tags: ["ETF", "NAV", "IOPV"], cadence: "session_minute", plan: "Wave 3 · licensed source", source: "exchange/authorized vendor rights required" }),
      plannedDataset({ id: "cn-fund-portfolio", title: { en: "Fund portfolio disclosures", zh: "基金持仓披露" }, description: { en: "Fund identity, periodic portfolio disclosures, holdings, and changes.", zh: "基金身份、定期组合披露、持仓及其变化。" }, family: "funds", category: { en: "Indices & funds", zh: "指数与基金" }, market: "CN", detail: "funds · holdings · disclosures", tags: ["funds", "holdings", "disclosures"], cadence: "quarterly_reporting", plan: "Wave 3 · PIT and rights review", source: "fund disclosures and provider contracts" }),
      plannedDataset({ id: "cn-convertible-bonds", title: { en: "Convertible bonds", zh: "可转债数据" }, description: { en: "Instrument terms, daily observations, conversions, redemptions, and events.", zh: "可转债条款、日行情、转股、赎回与事件。" }, family: "funds", category: { en: "Indices & funds", zh: "指数与基金" }, market: "CN", detail: "terms · prices · conversion events", tags: ["convertibles", "terms", "events"], cadence: "postclose_daily", plan: "Wave 2 · registry batch", source: "Tushare contract via QuickSync · permission unknown" }),

      plannedDataset({ id: "cn-macro-calendar", title: { en: "China macro calendar", zh: "中国宏观日历" }, description: { en: "Release dates, reported values, revisions, and units for macro indicators.", zh: "宏观指标发布日期、公布值、修订值与单位。" }, family: "macro", category: { en: "Macro & rates", zh: "宏观与利率" }, market: "CN", detail: "releases · revisions · units", tags: ["macro", "calendar", "revisions"], cadence: "monthly", plan: "Wave 3 · source mapping", source: "official statistical releases and provider contracts" }),
      plannedDataset({ id: "cn-yield-curve", title: { en: "Rates & yield curves", zh: "利率与收益率曲线" }, description: { en: "Government and policy-bank yields, tenors, and curve observations.", zh: "国债与政策性金融债收益率、期限与曲线观测。" }, family: "macro", category: { en: "Macro & rates", zh: "宏观与利率" }, market: "CN", detail: "rates · tenors · yield curves", tags: ["rates", "bonds", "yield curve"], cadence: "postclose_daily", plan: "Wave 3 · source and license", source: "official/authorized fixed-income data source required" }),
      plannedDataset({ id: "cn-pboc-operations", title: { en: "Central-bank operations", zh: "央行公开市场操作" }, description: { en: "Open-market operations, policy rates, reserve changes, and release metadata.", zh: "公开市场操作、政策利率、准备金变化与发布元数据。" }, family: "macro", category: { en: "Macro & rates", zh: "宏观与利率" }, market: "CN", detail: "OMO · policy rates · releases", tags: ["PBOC", "OMO", "policy rates"], cadence: "event", plan: "Wave 3 · official-source collector", source: "PBOC public releases · redistribution review" }),
      plannedDataset({ id: "cn-futures-commodities", title: { en: "Futures & commodity reference", zh: "期货与商品参考" }, description: { en: "Contracts, settlements, open interest, warehouse receipts, and delivery reference.", zh: "合约、结算、持仓量、仓单与交割参考。" }, family: "macro", category: { en: "Macro & rates", zh: "宏观与利率" }, market: "CN", detail: "contracts · settlement · inventory", tags: ["futures", "commodities", "inventory"], cadence: "postclose_daily", plan: "Wave 4 · exchange rights", source: "domestic futures exchanges · license review" }),

      plannedDataset({ id: "cn-news-flashes", title: { en: "Financial news & flashes", zh: "财经新闻与快讯" }, description: { en: "Timestamped news items with source, entities, language, and document lineage.", zh: "带时间戳、来源、实体、语言和文档血缘的新闻条目。" }, family: "text", category: { en: "News & documents", zh: "新闻与文本" }, market: "CN", detail: "news · flashes · source lineage", tags: ["news", "documents", "timestamps"], cadence: "event", plan: "Wave 4 · content license", source: "licensed news providers required" }),
      plannedDataset({ id: "cn-policy-regulation", title: { en: "Policy & regulation library", zh: "政策法规库" }, description: { en: "Versioned policies, regulations, issuers, effective dates, and source documents.", zh: "版本化政策法规、发布主体、生效日期与来源文档。" }, family: "text", category: { en: "News & documents", zh: "新闻与文本" }, market: "CN", detail: "policies · versions · effective dates", tags: ["policy", "regulation", "documents"], cadence: "event", plan: "Wave 3 · official-source mapping", source: "government and regulator public documents" }),
      plannedDataset({ id: "cn-broker-research", title: { en: "Broker research library", zh: "券商研报库" }, description: { en: "Licensed report metadata, documents, authorship, coverage, and publication time.", zh: "经授权的研报元数据、文档、作者、覆盖对象与发布时间。" }, family: "text", category: { en: "News & documents", zh: "新闻与文本" }, market: "CN", detail: "reports · authors · coverage", tags: ["research", "documents", "authorship"], cadence: "event", plan: "Wave 5 · commercial licensing", source: "broker/publisher licenses required" }),
      plannedDataset({ id: "cn-central-bank-reports", title: { en: "Central-bank reports", zh: "央行报告库" }, description: { en: "Monetary-policy reports, release metadata, versions, and attachments.", zh: "货币政策报告、发布元数据、版本与附件。" }, family: "text", category: { en: "News & documents", zh: "新闻与文本" }, market: "CN", detail: "reports · versions · attachments", tags: ["central bank", "reports", "policy"], cadence: "quarterly_reporting", plan: "Wave 3 · official-source collector", source: "PBOC public reports" }),

      plannedDataset({ id: "global-pizza-index", title: { en: "Pizza Index", zh: "Pizza 指数" }, description: { en: "A timestamped activity proxy assembled from observable pizza-ordering signals and documented collection rules.", zh: "由可观测披萨订购活动与公开采集规则组成的时间戳活动代理数据。" }, family: "alternative", category: { en: "Alternative data", zh: "另类数据" }, market: "GLOBAL", detail: "ordering activity · timestamped proxy", tags: ["activity proxy", "orders", "time series"], cadence: "event", plan: "Alternative pilot · source-rights discovery", source: "third-party/public sources · rights review required" }),
      plannedDataset({ id: "global-foot-traffic", title: { en: "Foot Traffic Index", zh: "线下客流指数" }, description: { en: "Aggregated location activity around stores, districts, or facilities.", zh: "围绕门店、商圈或设施汇总的客流活动数据。" }, family: "alternative", category: { en: "Alternative data", zh: "另类数据" }, market: "GLOBAL", detail: "locations · visits · aggregates", tags: ["mobility", "foot traffic", "locations"], cadence: "postclose_daily", plan: "Alternative Wave 2 · vendor evaluation", source: "licensed mobility provider required" }),
      plannedDataset({ id: "global-hiring-index", title: { en: "Hiring Activity Index", zh: "招聘活动指数" }, description: { en: "Job-posting volume, role mix, location, seniority, and employer changes.", zh: "招聘数量、岗位结构、地域、职级与雇主变化。" }, family: "alternative", category: { en: "Alternative data", zh: "另类数据" }, market: "GLOBAL", detail: "job posts · role mix · employer", tags: ["jobs", "hiring", "workforce"], cadence: "weekly", plan: "Alternative Wave 1 · source and entity mapping", source: "licensed job-posting data required" }),
      plannedDataset({ id: "global-app-attention", title: { en: "App Attention Index", zh: "应用关注度指数" }, description: { en: "App ranks, reviews, release activity, and category attention signals.", zh: "应用排名、评论、版本发布与品类关注度数据。" }, family: "alternative", category: { en: "Alternative data", zh: "另类数据" }, market: "GLOBAL", detail: "rank · reviews · releases", tags: ["apps", "rankings", "reviews"], cadence: "postclose_daily", plan: "Alternative Wave 2 · platform-rights review", source: "app-store/public vendor data · rights review" }),
      plannedDataset({ id: "global-web-attention", title: { en: "Web Attention Index", zh: "网络关注度指数" }, description: { en: "Aggregated search, web-traffic, and public attention observations with source metadata.", zh: "带来源元数据的搜索、网站流量与公开关注度汇总观测。" }, family: "alternative", category: { en: "Alternative data", zh: "另类数据" }, market: "GLOBAL", detail: "search · traffic · attention", tags: ["web", "search", "attention"], cadence: "postclose_daily", plan: "Alternative Wave 2 · vendor evaluation", source: "licensed web-attention providers required" }),
      plannedDataset({ id: "global-shipping-congestion", title: { en: "Shipping Congestion Index", zh: "航运拥堵指数" }, description: { en: "Port calls, vessel queues, transit time, and route congestion aggregates.", zh: "港口靠泊、船舶排队、运输时间与航线拥堵汇总。" }, family: "alternative", category: { en: "Alternative data", zh: "另类数据" }, market: "GLOBAL", detail: "ports · vessels · congestion", tags: ["shipping", "ports", "supply chain"], cadence: "postclose_daily", plan: "Alternative Wave 3 · AIS license", source: "licensed AIS/shipping provider required" }),
      plannedDataset({ id: "global-night-lights", title: { en: "Night Lights Activity", zh: "夜间灯光活动" }, description: { en: "Geospatial night-light observations normalized by location and acquisition time.", zh: "按地点与采集时间标准化的地理夜间灯光观测。" }, family: "alternative", category: { en: "Alternative data", zh: "另类数据" }, market: "GLOBAL", detail: "satellite · geospatial · activity", tags: ["satellite", "night lights", "geospatial"], cadence: "monthly", plan: "Alternative Wave 3 · public-source feasibility", source: "official satellite products · license and processing review" }),
      plannedDataset({ id: "global-consumer-basket", title: { en: "Consumer Price Basket", zh: "消费价格篮子" }, description: { en: "Observed product prices, availability, promotions, and normalized basket history.", zh: "商品价格、可售状态、促销与标准化价格篮子历史。" }, family: "alternative", category: { en: "Alternative data", zh: "另类数据" }, market: "GLOBAL", detail: "prices · availability · promotions", tags: ["consumer", "prices", "basket"], cadence: "postclose_daily", plan: "Alternative Wave 1 · merchant/source rights", source: "licensed retail/e-commerce sources required" }),
      plannedDataset({ id: "us-notable-investor-13f", title: { en: "Notable Investor 13F Holdings", zh: "知名投资者 13F 披露持仓" }, description: { en: "Quarterly, delayed institutional holdings disclosed through SEC Form 13F, with filer identity, filing versions, security details, and source lineage.", zh: "基于 SEC Form 13F 的季度滞后机构持仓披露，保留申报主体、文件版本、证券明细与来源血缘。" }, family: "alternative", category: { en: "Alternative data", zh: "另类数据" }, market: "US", detail: "institution universe · quarterly filings · revisions", tags: ["13F", "SEC EDGAR", "institutional holdings", "notable investors"], cadence: "quarterly_reporting", plan: "Alternative future · SEC contract and universe design", source: "SEC EDGAR Form 13F structured filings · official source review" }),

      plannedDataset({ id: "hk-equity-daily", title: { en: "Hong Kong equity daily", zh: "港股日线行情" }, description: { en: "Daily OHLCV and market reference for Hong Kong listed securities.", zh: "香港上市证券的日线 OHLCV 与市场参考。" }, family: "global", category: { en: "Global markets", zh: "全球市场" }, market: "HK", detail: "daily · instruments · corporate actions", tags: ["Hong Kong", "daily", "OHLCV"], cadence: "postclose_daily", plan: "Future market · outside initial scope", source: "licensed HKEX/authorized vendor source required" }),
      plannedDataset({ id: "us-equity-daily", title: { en: "US equity daily", zh: "美股日线行情" }, description: { en: "Daily observations and reference for US listed securities.", zh: "美国上市证券的日线观测与市场参考。" }, family: "global", category: { en: "Global markets", zh: "全球市场" }, market: "US", detail: "daily · instruments · adjustments", tags: ["US", "daily", "reference"], cadence: "postclose_daily", plan: "Future market · outside initial scope", source: "licensed exchange/authorized vendor source required" }),
      plannedDataset({ id: "us-sec-filings", title: { en: "SEC filings & XBRL", zh: "SEC 文件与 XBRL" }, description: { en: "Company submissions and extracted XBRL facts with filing timestamps.", zh: "带申报时间戳的公司文件与提取后 XBRL 事实。" }, family: "global", category: { en: "Global markets", zh: "全球市场" }, market: "US", detail: "EDGAR · filings · XBRL", tags: ["SEC", "filings", "XBRL"], cadence: "event", plan: "Future Wave · official API feasibility", source: "SEC data.sec.gov public APIs" }),
      plannedDataset({ id: "global-macro-indicators", title: { en: "Global macro indicators", zh: "全球宏观指标" }, description: { en: "Country indicators, units, revisions, and release metadata.", zh: "国家级宏观指标、单位、修订与发布元数据。" }, family: "global", category: { en: "Global markets", zh: "全球市场" }, market: "GLOBAL", detail: "countries · indicators · revisions", tags: ["macro", "countries", "indicators"], cadence: "monthly", plan: "Future Wave · official API mapping", source: "World Bank and other official statistical APIs" }),

      plannedDataset({ id: "crypto-binance-spot-5m", title: { en: "Binance spot 5-minute bars", zh: "Binance 现货 5 分钟行情" }, description: { en: "A frozen high-liquidity universe of public spot market observations.", zh: "固定高流动性标的范围内的公共现货 5 分钟行情。" }, family: "crypto", category: { en: "Crypto assets", zh: "加密资产" }, market: "CRYPTO", detail: "spot · 5m bars · frozen universe", tags: ["Binance", "spot", "5m"], cadence: "session_minute", plan: "Isolated provider slice · runtime evidence required", source: "Binance public market-data API" }),
      plannedDataset({ id: "crypto-binance-derivatives", title: { en: "Binance funding & open interest", zh: "Binance 资金费率与持仓量" }, description: { en: "Public USDⓈ-M funding-rate and open-interest history for the frozen universe.", zh: "固定标的范围内的公开 USDⓈ-M 资金费率与持仓量历史。" }, family: "crypto", category: { en: "Crypto assets", zh: "加密资产" }, market: "CRYPTO", detail: "funding · open interest · futures", tags: ["Binance", "funding", "open interest"], cadence: "session_minute", plan: "Isolated provider slice · network/readback gate", source: "Binance public futures API/data dumps" }),
      plannedDataset({ id: "crypto-coinbase-spot", title: { en: "Coinbase spot market", zh: "Coinbase 现货市场" }, description: { en: "Public spot products, candles, trades, and market reference.", zh: "公开现货产品、K 线、成交与市场参考。" }, family: "crypto", category: { en: "Crypto assets", zh: "加密资产" }, market: "CRYPTO", detail: "products · candles · trades", tags: ["Coinbase", "spot", "public API"], cadence: "session_minute", plan: "Future provider candidate · outside initial scope", source: "Coinbase Exchange public market-data API" }),
    ],
    features: [
      { id: "adjusted-return", title: { en: "Adjusted return", zh: "复权收益" }, family: "prices", status: "product_definition", detail: "formula · corporate-action handling · version" },
      { id: "realized-volatility", title: { en: "Realized volatility", zh: "已实现波动率" }, family: "market", status: "planned", detail: "window · sampling · missingness" },
      { id: "liquidity-measures", title: { en: "Liquidity measures", zh: "流动性度量" }, family: "microstructure", status: "planned", detail: "turnover · spread proxies · coverage" },
    ],
    recipes: [
      { id: "adjusted-price-series", title: { en: "Build an adjusted price series", zh: "构建复权价格序列" }, status: "product_definition", detail: "daily prices + adjustment factors" },
      { id: "pit-fundamentals-panel", title: { en: "Build a point-in-time fundamentals panel", zh: "构建时点一致财务面板" }, status: "planned", detail: "reports + publication time + revisions" },
      { id: "company-event-timeline", title: { en: "Prepare a company-event timeline", zh: "准备公司事件时间线" }, status: "product_definition", detail: "actions + announcements + trading calendar" },
    ],
  },
};
