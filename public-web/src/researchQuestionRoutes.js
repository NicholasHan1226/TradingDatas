// Question-led alternatives complement, rather than replace, the core topic journeys.
const step = (title, zh, en) => ({title, reason:{zh,en}});
export const researchQuestionRoutes = [
  {
    id:"earnings-quality", topic:"corporate-fundamentals",
    question:{zh:"如何理解盈余质量？",en:"How should we assess earnings quality?"},
    steps:[
      step("Do Stock Prices Fully Reflect Information in Accruals and Cash Flows about Future Earnings?", "先分清应计与现金流，理解盈余持续性为什么可能不同。", "Separate accruals and cash flows before comparing earnings persistence."),
      step("The Quality of Accruals and Earnings: The Role of Accrual Estimation Errors", "再看应计估计如何对应现金流；注意未来现金流带来的信息时点限制。", "Connect accrual estimates with cash flows, including the timing constraint introduced by future cash flows."),
      step("Detecting Earnings Management", "最后区分质量度量与操纵识别，检查模型残差、误报和业绩混淆。", "Distinguish quality measurement from manipulation detection through residuals, false positives and performance confounding."),
    ],
  },
  {
    id:"comparing-companies", topic:"corporate-fundamentals",
    question:{zh:"比较企业时，财务指标如何衔接？",en:"How do financial measures connect when comparing firms?"},
    steps:[
      step("Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers", "从限定企业群体中的会计指标变化开始，不把评分外推为所有企业的排序。", "Begin with accounting changes in a defined firm population, not a universal company ranking."),
      step("The Other Side of Value: The Gross Profitability Premium", "聚焦盈利口径，区分毛利润相对资产与销售利润率。", "Focus on the profitability definition: gross profit over assets differs from a sales margin."),
      step("Earnings, Book Values, and Dividends in Equity Valuation", "再把盈利流量与账面权益存量放入估值框架，区分经验比较与理论假设。", "Connect earnings flows and book-equity stocks in valuation, separating empirical comparisons from theoretical assumptions."),
    ],
  },
  {
    id:"financial-distress", topic:"corporate-fundamentals",
    question:{zh:"财务困境指标能说明什么？",en:"What can financial-distress measures tell us?"},
    steps:[
      step("Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy", "先理解财务比率如何形成判别分数，以及原始制造业样本的边界。", "Start with financial-ratio classification and the limits of the original manufacturing sample."),
      step("In Search of Distress Risk", "再比较含市场变量的动态失败分析；分数、概率和事件定义不能互换。", "Compare dynamic failure analysis with market variables; scores, probabilities and event definitions are not interchangeable."),
      step("Replicating Anomalies", "最后借用复现视角检查样本与数据处理；这篇不是对前两篇破产模型的直接验证。", "Use a replication lens to examine samples and data handling; this paper does not directly validate the preceding bankruptcy models."),
    ],
  },
];

export function questionRoutesFor(paper) {
  return researchQuestionRoutes.filter(route => route.steps.some(step => step.title === paper.title));
}
