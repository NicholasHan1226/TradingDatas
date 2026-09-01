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

const connection = (zh, en) => ({ zh, en });
// Each edge explains a relationship, not a ranking or an inferred citation.
export const journeyConnections = {
  "asset-pricing": [
    connection("前一篇讨论给定预期下的组合选择；后一篇转向哪些共同变量解释股票与债券收益。", "Move from choosing portfolios with given expectations to explaining shared stock and bond return variation."),
    connection("对照时间序列因子回归与横截面公司特征检验；不要把因子载荷与公司规模混为一谈。", "Compare time-series factor regressions with cross-sectional characteristics; a factor loading is not firm size."),
  ],
  "market-microstructure": [
    connection("Kyle解释信息如何进入交易价格；波动率研究进一步追问，怎样从价格变化中测量波动。", "Kyle models information entering prices; realized-volatility research asks how price changes measure variation."),
    connection("两篇都面对波动与交易噪声，但分别使用高频收益与日高低价；输入频率改变了可识别的对象。", "Both confront variation and trading noise, using high-frequency returns versus daily ranges; frequency changes what can be identified."),
  ],
  "corporate-fundamentals": [
    connection("从应计与现金流的持续性差异，转向应计估计的质量；注意后一指标需要未来现金流。", "Move from accrual/cash-flow persistence to estimation quality; the latter measure requires future cash flows."),
    connection("用复现视角重新检查会计指标：样本、权重、披露版本和统计标准都可能改变结果。", "Revisit accounting measures through replication: samples, weights, disclosure versions and inference standards can change findings."),
  ],
  "a-share-market": [
    connection("制度综述提供背景；实证研究把问题落到价格信息含量与企业投资，并区分所有权。", "The institutional overview supplies context; the empirical study measures informativeness and investment, distinguishing ownership."),
    connection("从价格中的未来盈利信息转到交易日内价格发现；两者的“效率”不是同一个度量。", "Shift from future-profit information in prices to intraday discovery: these are different definitions of efficiency."),
  ],
  "alternative-data": [
    connection("媒体语气研究使用特定语料；金融词典论文说明，一般语言词义不能直接迁移到财务披露。", "Media-tone research uses a specific corpus; the dictionary paper shows why general-language meanings need not transfer to filings."),
    connection("词典衡量文本中的语言特征，Lazy Prices衡量同一企业跨期的文件变化；两者互补而非互相验证。", "Dictionaries measure language features; Lazy Prices measures document changes over time. They complement rather than validate each other."),
  ],
  "crypto-markets": [
    connection("先区分协议与市场，再读平台采用模型；比特币机制不能直接套用到所有平台代币。", "Distinguish protocol and markets before reading a platform-adoption model; Bitcoin mechanisms do not describe every token."),
    connection("采用模型讨论价值形成，跨场所研究讨论价格分割；理论均衡不保证资金能够无摩擦转移。", "Adoption models address value formation; cross-venue evidence addresses segmentation. Equilibrium theory does not imply frictionless capital transfers."),
  ],
  "research-methods": [
    connection("先定义事件与窗口，再用方法实验检验误报率和检出能力；一次显著结果不是方法有效性的证明。", "Define events and windows, then examine false positives and power; one significant result does not validate a method."),
    connection("从日收益事件研究的误差问题，扩展到公司与时间两个维度的依赖；不能机械照搬标准误。", "Extend daily event-study error questions to dependence across firms and time; standard errors cannot be transferred mechanically."),
  ],
  "macro-finance": [
    connection("简约曲线拟合提供表示法，动态研究加入时间维度与样本外检验；拟合好不等于预测好。", "Parsimonious fitting supplies a representation; dynamics add time and out-of-sample evaluation. Good fit is not good forecasting."),
    connection("从预测收益率曲线转向持有期超额收益；描述曲线主要变化的因子未必保留全部收益预测信息。", "Move from forecasting yields to holding-period excess returns; dominant curve factors may omit information relevant to returns."),
  ],
};

export function readingJourney(paper, catalog) {
  const entry = Object.entries(researchJourneys).find(([, steps]) => steps.some((step) => step.title === paper.title));
  if (!entry) return null;
  const [topic, steps] = entry;
  const index = steps.findIndex((step) => step.title === paper.title);
  const links = [index - 1, index + 1].filter((position) => position >= 0 && position < steps.length).map((position) => ({
    paper: catalog.find((item) => item.title === steps[position].title),
    direction: position < index ? "previous" : "next",
    stage: journeyStages[position],
    reason: journeyConnections[topic][Math.min(position, index)],
  })).filter((link) => link.paper);
  return { topic, index, stage: journeyStages[index], reason: steps[index].reason, links };
}
