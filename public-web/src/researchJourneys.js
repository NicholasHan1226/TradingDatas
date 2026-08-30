// Reading order is editorial guidance, not a ranking of evidence or investment merit.
export const journeyStages = [
  { zh: "入门", en: "Start here" },
  { zh: "经典", en: "Core reading" },
  { zh: "进阶", en: "Go deeper" },
];
const step = (title, zh, en) => ({ title, reason: { zh, en } });
export const researchJourneys = {
  "asset-pricing": [
    step("Portfolio Selection", "先理解组合、风险与分散化的基本问题。", "Begin with portfolios, risk, and diversification."),
    step("Common risk factors in the returns on stocks and bonds", "再看风险因子如何连接不同资产的收益。", "Explore how common factors connect asset returns."),
    step("The Cross-Section of Expected Stock Returns", "区分横截面解释与时间序列检验。", "Distinguish cross-sectional explanation from time-series tests."),
  ],
  "market-microstructure": [
    step("Continuous Auctions and Insider Trading", "从参与者与信息结构理解价格形成。", "Start with participants, information, and price formation."),
    step("Modeling and Forecasting Realized Volatility", "把交易时钟与采样选择带入波动率度量。", "Connect market clocks and sampling to volatility measurement."),
    step("A Simple Way to Estimate Bid-Ask Spreads from Daily High and Low Prices", "比较日频代理量与直接报价信息的边界。", "Compare daily proxies with directly observed quotes."),
  ],
  "corporate-fundamentals": [
    step("Do Stock Prices Fully Reflect Information in Accruals and Cash Flows about Future Earnings?", "先区分盈余中的应计与现金流。", "First separate accruals from cash flows within earnings."),
    step("The Quality of Accruals and Earnings: The Role of Accrual Estimation Errors", "继续理解应计估计误差与盈余质量。", "Continue with estimation errors and earnings quality."),
    step("Replicating Anomalies", "最后用复现视角检查样本与变量定义。", "Use replication to question samples and variable definitions."),
  ],
  "a-share-market": [
    step("The Development of China's Stock Market and Stakes for the Global Economy", "先建立制度、所有权与市场发展的背景。", "Build context on institutions, ownership, and market development."),
    step("The Real Value of China's Stock Market", "将制度背景带入价格信息含量的研究。", "Carry that context into research on price informativeness."),
    step("Intraday Information Efficiency on the Chinese Equity Market", "进一步观察日内数据与交易机制的约束。", "Move into intraday evidence and trading-mechanism constraints."),
  ],
  "alternative-data": [
    step("Giving Content to Investor Sentiment: The Role of Media in the Stock Market", "从媒体文本如何变成研究变量开始。", "Start with how media text becomes a research variable."),
    step("When Is a Liability Not a Liability? Textual Analysis, Dictionaries, and 10-Ks", "理解金融语境为什么影响词典选择。", "Understand why financial context changes dictionary choice."),
    step("Lazy Prices", "继续研究文本版本变化与信息处理。", "Explore document changes and information processing."),
  ],
  "crypto-markets": [
    step("Bitcoin: Economics, Technology, and Governance", "先建立技术、经济与治理的共同背景。", "Begin with shared context on technology, economics, and governance."),
    step("Tokenomics: Dynamic Adoption and Valuation", "再理解代币采用与价值模型的假设。", "Examine assumptions linking token adoption and valuation."),
    step("Trading and Arbitrage in Cryptocurrency Markets", "最后回到跨场所数据与市场分割的证据。", "Return to cross-venue evidence and market segmentation."),
  ],
  "research-methods": [
    step("Event Studies in Economics and Finance", "先掌握事件、窗口与正常收益的定义。", "Define events, windows, and normal returns."),
    step("Using Daily Stock Returns: The Case of Event Studies", "进一步检查日频事件研究的设计选择。", "Examine design choices in daily-return event studies."),
    step("Estimating Standard Errors in Finance Panel Data Sets: Comparing Approaches", "再处理面板依赖与统计推断。", "Move on to panel dependence and statistical inference."),
  ],
  "macro-finance": [
    step("Parsimonious Modeling of Yield Curves", "从收益率曲线的简约表达开始。", "Start with a parsimonious representation of the yield curve."),
    step("Forecasting the Term Structure of Government Bond Yields", "区分曲线拟合与样本外预测。", "Distinguish curve fitting from out-of-sample forecasting."),
    step("Bond Risk Premia", "继续阅读期限结构与债券风险溢价。", "Continue with the term structure and bond risk premia."),
  ],
};
