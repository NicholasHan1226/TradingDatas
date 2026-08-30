import { researchEditorial } from "./researchEditorial.js";
import { researchDeepReads } from "./researchDeepReads.js";
import { researchGuideDepthExpansion } from "./researchGuideDepthExpansion.js";
import { researchAdditionalGuides } from "./researchAdditionalGuides.js";
// Source-backed editorial notes, separate from internal preparation/QA profiles.
export const researchReaderNotes = { ...researchEditorial, ...researchDeepReads, ...researchGuideDepthExpansion, ...researchAdditionalGuides };

export const sourceSpecificReaderLimits = {
  "Modeling and Forecasting Realized Volatility": { en: "Sampling frequency, trading sessions, and microstructure noise affect realized-volatility measurement.", zh: "采样频率、交易时段与微观结构噪声会影响已实现波动率的测量。" },
  "Intraday Information Efficiency on the Chinese Equity Market": { en: "The study uses tick trades and quotes. Minute OHLCV alone cannot reproduce its spread and price-discovery tests.", zh: "研究使用逐笔成交与报价；仅有分钟OHLCV无法复现其中的价差和价格发现检验。" },
  "Giving Content to Investor Sentiment: The Role of Media in the Stock Market": { en: "News timing, text selection, and company identification affect how media tone is interpreted.", zh: "新闻发布时间、文本选择与公司识别方式，会影响对媒体语气的解释。" },
  "Trading and Arbitrage in Cryptocurrency Markets": { en: "The analysis compares exchanges. A single venue's prices cannot describe cross-exchange deviations or transfer constraints.", zh: "研究比较不同交易所；单一场所的价格不能描述跨交易所偏离或转移约束。" },
  "Why DeFi Lending? Evidence from Aave V2": { en: "The evidence concerns Aave V2 lending. Exchange perpetual funding rates and open interest describe different activity.", zh: "研究证据涉及Aave V2借贷；交易所永续资金费率与持仓量描述的是不同活动。" },
  "Form 13F: Official Filing Guidance and EDGAR Data Access": { en: "13F disclosures are quarterly, delayed, and subject to amendments and reporting-scope limits; they are not real-time portfolios.", zh: "13F按季度披露，存在时滞、修订和申报范围限制，不是实时持仓。" },
  "Binance USDⓈ-M Futures Market Data: Funding Rate and Open Interest": { en: "Funding rates, premium indices, and open interest are distinct measures with different units and observation times.", zh: "资金费率、溢价指数与持仓量是不同指标，单位与观测时点也不同。" },
};
