// Additional source-backed guides; the eight three-stage core journeys stay fixed.
const section = (url, pages, zh, en, bodyZh, bodyEn) => ({
  title: { zh, en }, body: { zh: bodyZh, en: bodyEn },
  reference: { url, label: { zh: `原文定位：${pages.zh}`, en: `Source: ${pages.en}` } },
});
const amihud = "https://www.cis.upenn.edu/~mkearns/finread/amihud.pdf";
const novyMarx = "https://mysimon.rochester.edu/novy-marx/research/OSoV.pdf";
const a = (zhPages, enPages, ...text) => section(amihud, { zh: `2002年期刊版，第${zhPages}页`, en: `2002 journal article, pp. ${enPages}` }, ...text);
const n = (zhPages, enPages, ...text) => section(novyMarx, { zh: `2012年6月作者稿，第${zhPages}页`, en: `June 2012 author draft, pp. ${enPages}` }, ...text);

export const researchAdditionalGuides = {
  "Illiquidity and Stock Returns: Cross-Section and Time-Series Effects": {
    reviewedAt: "2026-08-30",
    evidenceUrl: amihud,
    evidenceScope: "2002 journal article hosted by the University of Pennsylvania: opening argument and sections 2.1–2.3.1, printed pp. 31–37. Definition and sample pages 34, 36–37 visually checked; no table replication or complete time-series review.",
    sections: [
      a("31–34", "31–34", "流动性为什么需要代理量？", "Why use a liquidity proxy?",
        "Amihud关注流动性与股票收益之间的关系，但日频历史数据通常没有完整报价和订单流。论文因此构造容易从日收益与成交金额得到的粗略代理量。它牺牲了微观结构细节，换取较长的历史覆盖；这不是把成交金额本身当作流动性，也不是直接测量买卖价差。",
        "Amihud studies the relation between liquidity and stock returns when long histories of quotes and order flow are unavailable. A coarse proxy built from daily returns and traded value trades microstructure detail for historical coverage. It is neither trading value by itself nor a directly observed bid–ask spread."),
      a("34", "34", "先算每日比值，再取平均", "Average the daily ratios",
        "ILLIQ先用每日收益的绝对值除以当日成交金额，再在观察期内对这些比值取平均。分母是金额，不是股数；“每日比值的平均”也不同于把全年绝对收益之和除以全年成交金额之和。单位、日频边界与有效观测天数都应随结果保留，否则不同序列的数值无法直接比较。",
        "ILLIQ is the mean of daily ratios: absolute return divided by that day's dollar trading volume. The denominator is traded value, not shares. This differs from dividing summed absolute returns by summed volume. Retain currency, return units, daily boundaries and the number of valid observations when comparing series."),
      a("36–37", "36–37", "样本规则也是方法的一部分", "The sample is part of the method",
        "横截面检验限制在纽约证券交易所股票，并使用上一年的特征解释之后的月收益。样本要求上一年有超过200天的收益及成交量数据、年末仍挂牌且价格高于5美元，还需要市值资料并剔除ILLIQ两端各1%的极端值。这些是原研究的历史设定，不是所有市场都应沿用的清洗规则。",
        "The cross-sectional tests use NYSE stocks and prior-year characteristics for subsequent monthly returns. Admission requires more than 200 prior-year return/volume observations, year-end listing, a price above $5 and capitalization data; the outer 1% tails of ILLIQ are excluded. These historical design choices are not universal cleaning defaults."),
      a("36–37", "36–37", "不要把原始指标与回归变量混用", "Raw and normalized measures differ",
        "论文不仅计算单只股票的ILLIQ，也计算年度市场平均值，再用个股指标除以该平均值形成均值调整后的变量。展示时还使用数值缩放。因此，看到名为“Amihud非流动性”的字段时，要先问它是原始日比值、期间平均、缩放值还是市场标准化值，不能只按名称连接数据。",
        "The paper also averages stock-level ILLIQ across the yearly sample and divides individual measures by that market average. Numerical scaling is used in presentation. A field called Amihud illiquidity could therefore contain daily ratios, period means, scaled values or market-normalized values; the name alone does not establish comparability."),
      a("31–32", "31–32", "预期补偿与当期冲击并不矛盾", "Expected compensation and contemporaneous shocks",
        "论文区分预期非流动性与未预期的当期变化：前者与预期超额收益正相关，后者与当期股票收益负相关。这分别对应持有不易交易资产的补偿，以及流动性意外恶化时的价格调整。阅读中应保留变量的时间位置，不能把历史上的正向关系简化为“流动性变差就会涨”。",
        "The opening argument separates expected illiquidity, positively related to expected excess returns, from unexpected contemporaneous illiquidity, negatively related to current returns. Compensation for holding less liquid assets and repricing after a liquidity shock address different time positions. Neither implies that worsening liquidity must produce a price rise."),
      a("34–37", "34–37", "把口径检查放在计算之前", "Check conventions before calculation",
        "用于新数据时，应先核对收益定义、币种、成交金额单位和市场日历。零成交金额使比值无定义，缺失也不能当作零流动性；应单独标记并披露处理规则。保留退市证券与样本剔除原因，再比较不同市场。上述准备原则帮助说明输入边界，并不等于已经复现论文的回归。",
        "For a new dataset, verify return definitions, currency, traded-value units and sessions first. A zero denominator prevents calculation; missing observations are not zero illiquidity. Mark these cases explicitly, retain delisted securities and record exclusions. These preparation principles clarify inputs without claiming to reproduce the paper's regressions."),
    ],
    limits: {
      zh: "日收益／成交金额只是粗略代理量，不能替代报价、订单方向或实际执行成本。历史纽约证券交易所样本的关系不保证跨市场成立；这里没有复现回归或检验当前收益。",
      en: "Daily return-to-value ratios are coarse proxies, not quotes, signed order flow or execution costs. Historical NYSE relationships need not transfer across markets; no regression replication or current-return test is claimed here.",
    },
  },
  "The Other Side of Value: The Gross Profitability Premium": {
    reviewedAt: "2026-08-30",
    evidenceUrl: novyMarx,
    evidenceScope: "June 2012 author draft hosted by University of Rochester: introduction and sections 2–2.1, printed pp. 1–7, with PDF pages 6–8 visually checked for definition, information lag and comparison design. The 2013 journal identity is retained; tables and appendices not independently replicated.",
    sections: [
      n("1、5–7", "1, 5–7", "毛利能力，不是通常所说的毛利率", "Gross profitability is not gross margin",
        "Novy-Marx用毛利除以账面总资产来衡量毛利能力，其中毛利由收入减去销售成本得到。它不是毛利除以收入的毛利率，也不是净利润除以权益的ROE。分母从收入换成资产后，问题从每单位销售留下多少毛利，变成每单位资产支持多少毛利，经济含义随之改变。",
        "The measure divides gross profits, revenue less cost of goods sold, by book assets. It is not gross margin, which divides gross profits by sales, or ROE, which uses earnings and equity. Changing the denominator changes the question from profit per unit of sales to gross profits supported by the asset base."),
      n("4–5", "4–5", "为什么不只看净利润？", "Why look above bottom-line earnings?",
        "作者认为，广告、研发及组织能力建设等当期费用，可能压低净利润，却不一定表示经营生产力更弱。因此论文考察更靠近生产活动的毛利口径。这个解释不是说所有被扣除的费用都无关紧要，而是要求在比较盈利指标之前，先理解它们包含或排除了哪些经营投入。",
        "The author argues that current spending on advertising, R&D or organizational capability can depress earnings without implying weaker productivity. Gross profits offer a different view of operations. This does not make excluded expenses irrelevant; comparisons should identify which operating investments each profitability measure includes or leaves out."),
      n("6", "6", "财务年份不等于可用日期", "Fiscal year is not availability time",
        "作者稿把某财政年度的会计数据从下一日历年6月底开始用于研究，资产定价检验覆盖1963年7月至2010年12月，并排除金融企业。这个时滞是原样本设计，不证明别的市场在同一天已经全部披露。迁移时仍要核对真实公告日期、修订版本与行业定义，不能把报告期末直接当成可用日期。",
        "The draft uses a fiscal year's accounting data from the end of June in the next calendar year; tests span July 1963–December 2010 and exclude financial firms. That lag is a sample convention, not proof of publication elsewhere. Transfer requires actual publication dates, filing versions and industry definitions rather than period-end availability."),
      n("6–7", "6–7", "与估值一起比较，而非单独排序", "Compare profitability alongside valuation",
        "横截面回归同时考虑账面市值比、规模与过去收益，再比较毛利／资产、净利润／权益和自由现金流／权益。作者还检查行业调整后的口径。这样的问题是毛利能力是否带来额外信息，而不是只展示高毛利组合的表现；控制变量、分母与样本需要一并阅读。",
        "Cross-sectional regressions control for book-to-market, size and past returns while comparing gross profits/assets with earnings/equity and free cash flow/equity. Industry-adjusted versions are also examined. The question is incremental information, not merely the performance of a high-profitability portfolio; controls, denominators and the sample matter together."),
      n("7", "7", "先分清统计结果与经营解释", "Separate the result from its interpretation",
        "在作者稿所报告的比较中，毛利能力保留了较强的横截面解释信息，加入其他盈利指标后也不完全消失。这是一组设定与历史样本下的结果，不是毛利率、资产周转率或所有“质量”指标都等价的证明。论文还分别讨论毛利率和资产周转，说明相似名称不能替代变量定义。",
        "In the draft's reported comparisons, gross profitability retains substantial cross-sectional information alongside other earnings measures. This is conditional historical evidence, not proof that gross margin, asset turnover or every quality metric is interchangeable. The paper examines those components separately, reinforcing the importance of exact variable definitions."),
      n("5–7", "5–7", "建立可解释的财务输入表", "Build an interpretable accounting input table",
        "准备对应研究时，可以分别保存收入、销售成本、毛利、总资产、财政期间与披露版本，再记录缩放和行业处理。毛利缺失不能自动用净利润替代；不同会计准则的成本归类也需核对。保留这些差异，才能判断结果来自企业经营特征，还是来自数据口径与样本选择。",
        "Retain revenue, cost of goods sold, gross profits, assets, fiscal periods and filing versions separately, alongside scaling and industry treatment. Missing gross profits must not silently become net income. Cost classifications can differ across accounting regimes; preserving them helps distinguish economic variation from input and sample choices."),
    ],
    limits: {
      zh: "导读采用2012年6月作者稿，保留2013年期刊题录；具体最终设定请核对期刊原文。指标是毛利／资产而非毛利率，不是统一的质量评分，也不保证当前或A股市场的收益。",
      en: "This guide uses the June 2012 author draft while retaining the 2013 journal citation; consult the final article for definitive specifications. Gross profits/assets is not gross margin or a universal quality score, and does not guarantee current or A-share returns.",
    },
  },
};
