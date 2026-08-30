// Source-backed editorial notes, separate from internal preparation/QA profiles.
export const researchReaderNotes = {
  "Tokenomics: Dynamic Adoption and Valuation": {
    reviewedAt: "2026-08-30",
    evidenceUrl: "https://nengwang-economics.com/publications/papers/Cong_Li_Wang_RFS_2020_authorcopy.pdf",
    evidenceScope: "Author copy, abstract and introduction; not a full-paper review.",
    sections: [
      {
        title: { zh: "从平台使用理解代币价值", en: "Value through platform use" },
        body: {
          zh: "作者研究的是用于平台交易的代币，而不是把所有加密资产视为同一种资产。模型把用户的交易需求、平台功能和网络效应联系起来：用户是否加入平台、持有多少代币，与代币价格共同决定。阅读时可以先抓住这种双向关系。",
          en: "The authors examine tokens used for platform transactions. Their model connects transaction demand, platform productivity, and network effects: participation, token holdings, and price are jointly determined. This offers a way to think about platform use rather than treating every cryptoasset as the same instrument.",
        },
      },
      {
        title: { zh: "关注采用过程，而不只是价格", en: "Follow adoption, not price alone" },
        body: {
          zh: "在模型中，用户采用经历由慢到快、再趋缓的过程；预期价格变化也会影响参与成本。因此，理解这篇论文需要观察平台活动与用户参与，单独查看交易所行情并不能回答它讨论的问题。",
          en: "Adoption follows an S-shaped path in the model, while expected price changes affect the cost of participation. Understanding this mechanism requires attention to platform activity and users, not exchange prices alone.",
        },
      },
    ],
    limits: {
      zh: "这是依赖特定假设的理论模型，包括固定代币供给；它不是对某个代币价格或实际采用速度的预测。",
      en: "This is a theoretical model with specific assumptions, including fixed token supply, not a forecast for a particular token or its adoption rate.",
    },
  },
};

export const sourceSpecificReaderLimits = {
  "Modeling and Forecasting Realized Volatility": { en: "Sampling frequency, trading sessions, and microstructure noise affect realized-volatility measurement.", zh: "采样频率、交易时段与微观结构噪声会影响已实现波动率的测量。" },
  "Intraday Information Efficiency on the Chinese Equity Market": { en: "The study uses tick trades and quotes. Minute OHLCV alone cannot reproduce its spread and price-discovery tests.", zh: "研究使用逐笔成交与报价；仅有分钟OHLCV无法复现其中的价差和价格发现检验。" },
  "Giving Content to Investor Sentiment: The Role of Media in the Stock Market": { en: "News timing, text selection, and company identification affect how media tone is interpreted.", zh: "新闻发布时间、文本选择与公司识别方式，会影响对媒体语气的解释。" },
  "Trading and Arbitrage in Cryptocurrency Markets": { en: "The analysis compares exchanges. A single venue's prices cannot describe cross-exchange deviations or transfer constraints.", zh: "研究比较不同交易所；单一场所的价格不能描述跨交易所偏离或转移约束。" },
  "Why DeFi Lending? Evidence from Aave V2": { en: "The evidence concerns Aave V2 lending. Exchange perpetual funding rates and open interest describe different activity.", zh: "研究证据涉及Aave V2借贷；交易所永续资金费率与持仓量描述的是不同活动。" },
  "Form 13F: Official Filing Guidance and EDGAR Data Access": { en: "13F disclosures are quarterly, delayed, and subject to amendments and reporting-scope limits; they are not real-time portfolios.", zh: "13F按季度披露，存在时滞、修订和申报范围限制，不是实时持仓。" },
  "Binance USDⓈ-M Futures Market Data: Funding Rate and Open Interest": { en: "Funding rates, premium indices, and open interest are distinct measures with different units and observation times.", zh: "资金费率、溢价指数与持仓量是不同指标，单位与观测时点也不同。" },
};
