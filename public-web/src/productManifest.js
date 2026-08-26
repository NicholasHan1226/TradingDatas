export const productManifest = {
  status: "design_contract",
  generatedAt: null,
  note: "Navigation and content prototype only; not runtime availability authority.",
  objects: {
    datasets: [
      { id: "cn-equity-daily", title: { en: "A-share daily prices", zh: "A 股日线行情" }, family: "market", status: "observed_example", detail: "daily prices · adjustment inputs · trading calendar" },
      { id: "cn-company-actions", title: { en: "Company actions", zh: "公司行动" }, family: "fundamentals", status: "product_definition", detail: "dividends · capital changes · suspensions" },
      { id: "cn-pit-fundamentals", title: { en: "Point-in-time fundamentals", zh: "时点一致财务数据" }, family: "fundamentals", status: "planned", detail: "as-of availability · revisions · restatements" },
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
