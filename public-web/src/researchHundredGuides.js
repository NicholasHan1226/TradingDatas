// Original bilingual commentary; edition and page scope are retained for review.
const bi = ([zh, en]) => ({ zh, en });
// Version-preservation examples only; neither tutorial supplies the original corpus.
const materials = {
  "More Than Words: Quantifying Language to Measure Firms' Fundamentals": { recipes: ["document-version-ledger"] },
  "Annual Report Readability, Current Earnings, and Earnings Persistence": { recipes: ["document-version-ledger"] },
  "CSI 300 Index Methodology": { datasets: ["cn-index-constituents"] },
};
const guide = ([title, url, edition, evidenceScope, limits, rows]) => [title, {
  reviewedAt: "2026-08-31", evidenceUrl: url, evidenceScope, limits: bi(limits), related: materials[title] ?? {},
  sections: rows.map(([location, zh, en, bodyZh, bodyEn]) => ({
    title: { zh, en }, body: { zh: bodyZh, en: bodyEn },
    reference: { url, label: { zh: edition[0] + " · " + location, en: edition[1] + " · " + location } },
  })),
}];

export const researchHundredGuides = Object.fromEntries([
  [
    "Stock Market Liberalization, Economic Reform, and Emerging Market Equity Prices",
    "https://www.underpricing.de/files/Henry_Stock-Market.pdf",
    [
      "1999年7月工作稿",
      "July 1999 draft"
    ],
    "Manuscript cover and printed pp. 1–4 inspected for liberalization definitions, equity revaluation, event windows, timing selection and concurrent reforms. Journal-version estimates not substituted.",
    [
      "导读依据1999年7月稿的跨国历史比较，不是当前开放政策评估。政策时点与其他改革可能共同变化，价格重估也不等于持续高收益。",
      "This uses the July 1999 cross-country draft, not current policy evaluation. Policy timing and reforms can coincide; a valuation jump does not mean persistently higher returns."
    ],
    [
      [
        "p. 1",
        "开放首先是投资者准入变化",
        "Liberalization first changes investor access",
        "Henry将股票市场开放定义为允许外国投资者购买本国市场股票的政策变化。它不是所有资本项目限制同时取消，也不等于所有外国资金立即流入。清楚界定处理事件，才能区分制度准入、实际参与程度与之后的市场表现。",
        "Henry defines liberalization as allowing foreigners to buy domestic equities. It is not the removal of every capital-account restriction or immediate foreign inflows. The event definition separates legal access, actual participation and subsequent market outcomes."
      ],
      [
        "pp. 1–2",
        "价格上涨与要求收益下降可以并存",
        "Higher prices can accompany lower required returns",
        "风险分担改善可能降低股权资本成本；在预期现金流不变时，更低的折现率会提高当前价格。因此，开放附近的价格上涨与未来要求收益下降并不矛盾。把事件期涨幅理解为以后每年都会重复的额外收益，会颠倒这条机制。",
        "Improved risk sharing can lower the cost of equity and raise current prices if expected cash flows are unchanged. An event-period gain can therefore coexist with lower future required returns. It is not a recurring annual performance bonus."
      ],
      [
        "pp. 2–3",
        "消息到达未必等于正式实施",
        "Information arrival need not equal implementation",
        "市场可能在政策正式实施前就获知变化，所以事件窗口不仅包含实施当月。窗口越长，也越容易纳入其他消息或预先上涨。研究不同窗口，是在信息提前反映与混杂事件之间做比较，而不是机械寻找最显著的一组日期。",
        "Markets may learn of reform before implementation, motivating a wider event window. Longer windows also admit other news and prior runups. Comparing windows addresses anticipation and confounding, rather than simply searching for the most significant dates."
      ],
      [
        "p. 3",
        "政策时点本身可能有选择",
        "Policy timing can be selected",
        "作者提醒，政府可能选择市场已经上涨的时候开放，类似发行人选择融资时点。这会让长窗口的价格变化高估开放效应。缩短窗口与检查其他日期可以提供稳健性证据，却不等于政策时点已经成为完全随机的外生事件。",
        "Governments may liberalize after a market runup, creating timing selection. Long-window gains could then overstate the effect. Shorter windows and alternative dates provide robustness checks without making policy timing a randomized event."
      ],
      [
        "pp. 3–4",
        "同时发生的改革需要单独处理",
        "Concurrent reforms require separate treatment",
        "开放往往与宏观稳定、经济改革或全球市场变化一起发生。工作稿构建政策变化资料，并控制相关因素，以区分股票准入与其他变化。仅用开放前后平均价格做比较，会把这些共同发生的影响全部塞进同一个解释。",
        "Liberalization can coincide with stabilization, economic reform and global market movements. The draft uses policy histories and controls to distinguish them. A simple before–after price comparison would bundle these overlapping influences into one explanation."
      ],
      [
        "pp. 1, 4",
        "估值、投资与增长是不同结果",
        "Valuation, investment and growth are different outcomes",
        "这篇文章重点检验股票价格重估，投资与产出增长是理论链条中的后续问题。价格变化与机制一致，并不独立证明新增投资已经发生。与经济增长研究并读时，应保留事件期金融结果与多年实体结果之间的时间和证据距离。",
        "The paper focuses on equity revaluation; investment and output growth are later links in the proposed chain. Consistent price evidence does not independently establish new investment. Financial event outcomes and multi-year real outcomes require separate evidence."
      ]
    ]
  ],
  [
    "Does Financial Liberalization Spur Growth?",
    "https://people.duke.edu/~charvey/Research/Working_Papers/W56_Does_financial_liberalization.pdf",
    [
      "作者存档稿",
      "Author-hosted manuscript"
    ],
    "Author-hosted manuscript cover and printed pp. 1–3 inspected for real per-capita growth, official/first-sign/intensity measures, selection and simultaneous reforms. Cover has no revision date; no final-version numerical estimate adopted.",
    [
      "所读作者稿封面未标修订日期。跨国开放与增长关系受改革组合、制度和时点选择影响，不能直接当作某一国家政策的确定因果效果。",
      "The consulted manuscript has no cover revision date. Reform packages, institutions and timing selection affect cross-country associations, which do not establish a particular country's policy effect."
    ],
    [
      [
        "pp. 1–2",
        "结果变量是实体增长，不是股票收益",
        "The outcome is real growth, not stock returns",
        "研究将股权市场开放与随后实际人均GDP增长联系起来。这个结果与股价在开放消息附近的跳升不同，也不等同于居民投资收益。比较两类文献时，应先区分金融价格、资本成本与实体产出，避免把它们当成同一个指标。",
        "The study relates equity-market liberalization to subsequent real per-capita GDP growth. This differs from stock-price jumps around reform news and from household investment returns. Financial prices, capital costs and real output are distinct outcomes."
      ],
      [
        "p. 3",
        "正式准入与首次间接通道可能不同",
        "Official access can differ from first indirect access",
        "作者除了正式开放日期，还使用国家基金、存托凭证或正式开放三者中最早出现的迹象。间接投资渠道可能早于本地市场允许外国人直接交易。一个国家因此可以有多个合理事件日期，它们回答的并不是完全相同的准入问题。",
        "Alongside official dates, the study considers the first country fund, depositary receipt or official opening. Indirect access can precede direct local trading. Multiple dates can be defensible because they describe different forms of access."
      ],
      [
        "p. 3",
        "开放程度不是只有零和一",
        "Openness is not only a binary state",
        "投资者可投资市值与总体市值的比率，被用作连续的开放强度指标。它与是否出现正式政策的二元变量含义不同，也受证券覆盖和权重影响。比较指标之前，应固定可投资的定义，而不是将法律开放直接解释为市场已完全整合。",
        "Investable capitalization relative to total capitalization measures openness continuously. It differs from an official-policy indicator and depends on coverage and weights. Legal opening should not be equated automatically with complete market integration."
      ],
      [
        "pp. 1–2",
        "资本账户开放与股票开放分开",
        "Separate capital-account and equity-market opening",
        "文章将股权市场准入与更广泛的资本账户限制分别衡量，以解释不同研究为何可能得到不同结果。两个政策标签并不覆盖同一类跨境交易。把指标合并或互换，会改变研究处理变量，不能只认为它们是同一概念的不同名称。",
        "Equity access and broader capital-account restrictions are measured separately. They cover different cross-border transactions and can produce different findings. Combining or interchanging the indicators changes the treatment rather than merely renaming it."
      ],
      [
        "p. 2",
        "改革与增长机会可能同时变化",
        "Reforms and growth opportunities may coincide",
        "作者承认开放可能是对增长机会的主动选择，也可能与法律、金融或宏观改革同步。这些竞争解释需要分别检验。增加控制变量能提高比较的针对性，但并不能保证全部未观测的改革动机与国家差异都已经被排除。",
        "Liberalization may respond to growth opportunities or coincide with legal, financial and macroeconomic reforms. These alternatives need separate examination. Controls sharpen the comparison but cannot guarantee removal of all unobserved policy motives and country differences."
      ],
      [
        "p. 2",
        "平均效果不能代替制度差异",
        "An average effect does not replace institutional differences",
        "文章进一步追问为什么不同国家的增长反应不同，并考虑制度质量与金融发展条件。跨国平均关系只是一个汇总，不能直接套用于任何具体改革。评价政策适用性时，还需要了解原有约束、实施内容和其他同期变化。",
        "The paper asks why growth responses vary with institutions and financial development. A cross-country average is an aggregate, not a transferable effect for every reform. Applicability requires understanding prior constraints, implementation and concurrent changes."
      ]
    ]
  ],
  [
    "Politically Connected CEOs, Corporate Governance, and Post-IPO Performance of China's Newly Partially Privatized Firms",
    "https://cuhk.edu.hk/ief/josephfan/doc/research_published_paper/11.pdf",
    [
      "2007年期刊版",
      "2007 journal article"
    ],
    "Journal pp. 330–332 and 335 inspected for CEO definition, 1993–2001 IPO scope, ownership context and coverage differences. This is the JFE article, not its 2014 practitioner abridgment.",
    [
      "样本是1993—2001年部分私有化上市企业，政治联系按作者履历定义。历史关联不能直接证明因果，也不能用于评价当前某位高管或企业。",
      "The sample covers partially privatized IPO firms in 1993–2001, with connections defined through career histories. Historical associations neither prove causality nor assess a current executive or firm."
    ],
    [
      [
        "p. 331",
        "先看政治联系如何定义",
        "Start with the definition of political connection",
        "作者按CEO是否曾经或正在中央、地方政府或军队任职构造代理变量。这个定义不是泛指所有社会关系，也不等于每一次经营决策都受到直接干预。理解回归结果，必须保留履历分类与理论上政府影响之间的区别。",
        "The proxy records current or former central-government, local-government or military service. It does not mean every social connection or direct intervention in each decision. Career classification must remain distinct from the theoretical concept of government influence."
      ],
      [
        "pp. 331–332",
        "部分私有化保留了控制权背景",
        "Partial privatization retains a control context",
        "研究讨论通过发行少数股份引入公众股东、同时保留政府控制的历史安排。它与出售全部控制权的私有化不同。不同制度下的治理激励和股东权利可能差异很大，因此不能仅凭共同使用私有化一词，就合并所有国家经验。",
        "The historical arrangement introduces public minority shareholders while retaining government control. It differs from transferring full control. Governance incentives and shareholder rights can vary substantially across settings that share the privatization label."
      ],
      [
        "p. 331",
        "股价与经营表现分别观察",
        "Observe market and operating outcomes separately",
        "论文同时讨论上市后的股票收益、盈利和销售等经营表现，以及上市首日的价格反应。这些变量的基准和时间范围不同。股价表现较弱不直接等于经营现金流减少，也不能用一项首日结果替代多年企业表现的证据。",
        "The paper considers post-IPO returns, earnings and sales outcomes, and first-day pricing. Their benchmarks and horizons differ. Weak stock performance is not identical to lower operating cash flow, and a first-day result cannot substitute for multi-year evidence."
      ],
      [
        "pp. 332, 335",
        "董事会结构提供另一条观察线",
        "Board composition provides another observation channel",
        "CEO联系与董事会成员背景之间的关系，让研究不只停留在收益比较，也追问组织如何构成。履历和专业背景是可分类资料，但仍不能完整代表董事独立性、实际监督力度或每次投票行为，组织标签与治理质量需要区分。",
        "Connections and directors' backgrounds add an organizational channel beyond return comparisons. Career and professional categories are observable classifications, not complete measures of independence, monitoring or voting behavior. Organizational labels and governance quality remain distinct."
      ],
      [
        "p. 335 · table 1",
        "披露覆盖影响谁进入样本",
        "Disclosure coverage affects sample inclusion",
        "样本覆盖随年份改善，不同行业也有差异，金融与房地产的覆盖尤其低于其他大类。这样的缺失不是简单增加公司数量就能忽略。将样本比例解释为全国或全部上市企业比例时，必须先考虑可获得履历资料所带来的选择。",
        "Coverage improves over time and varies by industry, with finance and real estate less represented. Missingness cannot be ignored because the sample is large. Available career disclosures select firms before any sample percentage is generalized."
      ],
      [
        "pp. 331–335",
        "历史条件与因果解释不能省略",
        "Retain historical and causal limits",
        "高管任命、企业类型和政府持股可能共同决定观察到的表现。控制可见特征有助于比较，但不是随机分配高管背景。原研究提供特定转型时期的治理证据，不应转化成对今天某类履历的机械评级或自动投资筛选。",
        "Appointments, firm type and state ownership may jointly shape outcomes. Controlling observable features is not random assignment of executive backgrounds. The historical governance evidence should not become a mechanical rating of current careers or an automatic investment screen."
      ]
    ]
  ],
  [
    "Retail and Institutional Investor Trading Behaviors: Evidence from China",
    "https://www.pbcsf.tsinghua.edu.cn/PDF/yifabiao7.pdf",
    [
      "2024年综述",
      "2024 review"
    ],
    "Review pp. 460–462 inspected for investor classifications, account-level aggregation, volume versus holdings, US proxy differences and historical efficiency measures. This is a review; underlying proprietary data not accessed.",
    [
      "这是综合既有研究的综述，并非可直接下载的账户数据库。中美比较使用不同识别方法，文中历史比例也不代表当前全市场的实时状态。",
      "This reviews existing studies rather than providing an account database. China–US comparisons use different identification methods, and historical proportions are not current real-time market measures."
    ],
    [
      [
        "p. 460",
        "散户、机构与大股东不是一条轴",
        "Retail, institutions and blockholders are different roles",
        "综述将个人账户、机构账户和持有战略性大额股份的大股东区分开。大股东既可能是个人，也可能是公司或政府。分类同时涉及账户性质和持有角色，因此不能只按法律主体名称，就推断一个参与者属于哪一种交易行为群体。",
        "The review distinguishes personal accounts, institutional accounts and strategic blockholders. A blockholder can be an individual, corporation or government. Account identity and holding role are separate dimensions, so legal form alone does not determine trading behavior."
      ],
      [
        "p. 460 · figure 1",
        "交易占比与持股占比不同",
        "Trading shares differ from ownership shares",
        "频繁交易的群体未必持有最多股份，长期大股东也可能很少成交。综述并列展示交易与持有结构，帮助解释这种差异。用成交占比描述所有权集中度，或用持股占比解释短期订单流，都会把两种不同经济对象混在一起。",
        "A group trading frequently need not own the most shares, while large long-term holders may trade little. Trading and holding compositions are shown separately. Volume shares do not measure ownership concentration, and ownership shares do not directly describe short-term order flow."
      ],
      [
        "p. 460",
        "账户资料先聚合，再得到市场图像",
        "Account data are aggregated into a market picture",
        "所引用中国交易所资料先按股票和日期聚合账户交易与持仓，再对股票和日期平均。这种统计方式与按全市场市值直接加权并不一样。理解图中比例时，要保留样本交易所、历史窗口和聚合顺序，不能把它当作所有年份统一的常数。",
        "The cited exchange data aggregate accounts by stock and day before averaging across stocks and dates. This differs from directly weighting the entire market by capitalization. Exchange coverage, historical window and aggregation order belong to the interpretation."
      ],
      [
        "pp. 460–461",
        "美国散户交易是识别代理",
        "US retail trades are identified through a proxy",
        "美国比较使用成交价格特征识别部分主动散户交易，而不是与中国账户标签完全同源的资料；对其他订单还要作假设。由两种方法得到的比例可以提供背景，但不能把差额全部解释成投资者真实行为的跨国差异。",
        "The US comparison uses trade-price features to identify some aggressive retail activity, rather than equivalent account labels. Other orders require assumptions. Differences between these estimates cannot all be attributed to genuine cross-country behavior."
      ],
      [
        "p. 461",
        "13F之外不只有个人投资者",
        "Holdings outside 13F are not only households",
        "机构申报数据覆盖特定门槛与证券范围，未被该集合覆盖的持仓还包含其他机构。综述将剩余部分与家庭合并描述，并不把它全部识别为散户。因此，公开持仓文件中的缺席，不能直接证明所有权属于某一种账户类型。",
        "Institutional filings cover particular thresholds and securities. Holdings outside that set include other institutions as well as households. Absence from public filing coverage therefore does not identify the owner as a retail investor."
      ],
      [
        "p. 462",
        "效率指标是一个有限视角",
        "An efficiency measure offers a limited view",
        "综述使用周收益之间的相关关系讨论历史信息效率变化。这样的指标反映特定形式的价格依赖，不等于测量所有定价偏差或证明市场完全有效。比较年代时，还需考虑交易制度、样本组成和数据质量的共同变化。",
        "Weekly-return dependence offers one view of historical information efficiency, not a measure of every pricing error or proof of complete efficiency. Comparisons over time also face changing institutions, sample composition and data quality."
      ]
    ]
  ],
  [
    "CSI 300 Index Methodology",
    "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/en/000300_Index_Methodology_en.pdf",
    [
      "2023年9月方法文件",
      "September 2023 methodology"
    ],
    "Official PDF cover and printed pp. 1–2 and 6–7 inspected for selection, adjusted capitalization, divisor, periodic review and buffers. Historical edition only; current rules and constituent files not verified.",
    [
      "这里解释2023年9月版本，不声称它仍是最新规则。编制方法、历史成分名单和具体日期权重是不同资料，当前名单不能替代历史样本。",
      "This explains the September 2023 edition without claiming it is current. Methodology, historical membership and dated weights are distinct materials; current constituents cannot replace historical samples."
    ],
    [
      [
        "p. 1 · §§1–3",
        "指数不是全部A股的等比例缩影",
        "The index is not a proportional miniature of all A-shares",
        "方法文件通过上市条件、交易活跃度与市值选择成分，目标集中于较大且流动的证券。这个筛选结构决定指数覆盖范围。用指数研究市场时，应承认它不是全部上市公司的随机样本，也不代表每个行业或规模组具有相同权重。",
        "Eligibility, trading activity and capitalization select larger, liquid securities. This structure defines coverage. The index is not a random sample of every listed firm and does not give equal representation to each industry or size group."
      ],
      [
        "p. 1 · §3",
        "交易筛选先于市值排名",
        "Trading-activity screening precedes size ranking",
        "该版本先按过去一段时间的日均成交金额筛选，再对剩余证券按日均总市值排序。两个步骤不是同一个流动性指标。只取某天市值最大的300只证券，不能重建这一规则，也会遗漏上市条件和其他资格要求。",
        "This edition screens average daily trading value before ranking remaining securities by average total capitalization. The two steps are distinct. Taking the largest 300 stocks on one date does not reconstruct the process or its eligibility conditions."
      ],
      [
        "p. 2 · §4.2",
        "权重使用调整后的流通份额",
        "Weights use adjusted free-float shares",
        "计算使用证券价格与调整后的自由流通股数，而不是直接采用公司总股本。战略持有或受限制股份会影响自由流通定义，档位调整又影响最终计入份额。公司总市值、实际自由流通市值与指数权重之间不能简单画等号。",
        "Calculation uses prices and adjusted free-float shares, not total issued shares. Strategic or restricted holdings affect float, and category weighting affects included shares. Total capitalization, raw free-float capitalization and index weights are not interchangeable."
      ],
      [
        "p. 2 · §4.2",
        "除数维持非交易变化前后的可比性",
        "The divisor preserves comparability across non-trading changes",
        "成分或股本结构变化可能改变总市值，却不是投资者在市场交易中获得的收益。文件通过除数调整维持指数的连续可比。重建历史指数时，仅汇总价格乘股数不够，还需处理对应生效时间的调整，否则会产生人为跳变。",
        "Membership or share-structure changes can alter capitalization without representing a market return. Divisor adjustment preserves comparability. Historical reconstruction needs dated adjustments as well as price-times-share totals, or artificial jumps may appear."
      ],
      [
        "p. 6 · §§6.1–6.2",
        "审核期、数据期和生效日分开",
        "Separate review, data and effective dates",
        "该版本分别规定审核所用资料窗口、审核时间与调整实施时间。知道将来要纳入的名单，不等于它在更早日期已属于指数。历史研究需要按生效日期保存成分，而不能把审核结果或今天的名单回填到全部过去日期。",
        "The edition distinguishes the data window, review timing and effective adjustment date. A future addition is not an earlier constituent. Historical research needs effective-dated membership instead of backfilling review outcomes or today's list into the past."
      ],
      [
        "p. 6 · §§6.3–6.5",
        "缓冲规则意味着名单不会简单重排",
        "Buffers prevent simple repeated reranking",
        "为降低换手，规则对原有成分与新候选设置不同保留和优先区间，并限制通常调整规模。因此，成分会依赖上一期名单，而不只是当期排名。理解指数稳定性，要把这些路径依赖规则与市场自然稳定的现象区分开。",
        "Retention and entry buffers, alongside normal adjustment limits, reduce turnover. Membership depends partly on the prior list rather than current ranks alone. Rule-driven persistence must be distinguished from stability arising naturally in the market."
      ]
    ]
  ],
  [
    "More Than Words: Quantifying Language to Measure Firms' Fundamentals",
    "https://www.uts.edu.au/globalassets/sites/default/files/adg_cons2015_tetlock-saar-tsechansky-macskassy-jf-2008.pdf",
    [
      "2008年期刊版",
      "2008 journal article"
    ],
    "Printed pp. 1438–1441 inspected for firm-news coverage, dictionary weights, earnings versus returns, timing/cost limitations and entity matching. Original news corpus and regressions not reproduced.",
    [
      "词典负面词比例不是完整语义或真实情绪的直接观测。原研究的英文新闻、公司覆盖与发布时间，不能直接移植为中文文本模型。",
      "Dictionary negativity is not full meaning or directly observed sentiment. English news coverage, firm matching and publication timing do not automatically transfer to a Chinese-language model."
    ],
    [
      [
        "p. 1438",
        "从市场语气走向公司基本面",
        "Move from market tone to firm fundamentals",
        "研究关注公司新闻的语言是否提供超出分析师预测与会计资料的额外信息。它不只问市场今天乐观还是悲观，还问文本能否帮助理解未来盈利。媒体语气、企业基本面和股票回报因此是相关但不同的研究对象。",
        "The study asks whether firm-news language adds information beyond analyst forecasts and accounting data. It examines future earnings as well as market tone. Media language, company fundamentals and stock returns are related but distinct objects."
      ],
      [
        "p. 1440",
        "词袋方法放弃了部分语境",
        "Bag-of-words measurement discards some context",
        "作者以词频表示文章，并把预先定义的负面词视为同等有信息。这个方法透明、便于复查，却不保留完整词序或复杂上下文。相同词汇可能出现在不同叙述中，因此测量的可重复性不能直接当作语义理解已经完整。",
        "The method represents articles through word frequencies and gives predefined negative words equal informational weight. It is transparent but does not retain full word order or context. Reproducibility therefore should not be confused with complete semantic understanding."
      ],
      [
        "pp. 1438, 1440",
        "负面比例需要固定分母",
        "Negativity requires a fixed denominator",
        "文章用负面词相对于文本词数的频率，而不是简单统计负面词总量。长文章天然更可能含有更多相关词，分母会影响比较。更换分词、去重或文本截取规则，也可能改变比例，不能认为沿用同一本词典就得到同一指标。",
        "Negativity is a relative frequency, not a raw count. Longer articles naturally contain more opportunities for matching words. Tokenization, deduplication and document boundaries can change the ratio even when the dictionary stays unchanged."
      ],
      [
        "p. 1441",
        "公司匹配连接文本与财务资料",
        "Entity matching connects text to financial records",
        "新闻使用公司常用名称，金融数据库则使用不同标识。作者需要处理名称到证券和会计标识的匹配，完美字符串一致并不常见。若关联到同名企业、错误证券或错误时期，再精细的语气指标也会被接到错误的结果变量上。",
        "News uses common company names while financial databases use identifiers. Matching links the two, and exact name agreement is uncommon. Wrong entities, securities or periods attach even a carefully measured tone variable to the wrong outcome."
      ],
      [
        "p. 1439",
        "发布时间决定预测的可用边界",
        "Publication timing defines the forecasting boundary",
        "连续新闻服务与较低频更新的报纸，在投资者能看到文本的时间上不同。原文讨论的收益结果也随信息来源而异。研究文本与随后价格时，必须先对齐真正公开时间，不能把当天较晚发布的材料用于解释更早可实施的决定。",
        "Continuous news services and less frequently updated newspapers differ in availability. Return findings vary with the source. Text–price studies must align actual publication timing rather than using late-day material as if it informed an earlier decision."
      ],
      [
        "p. 1439",
        "增量信息不等于可获利能力",
        "Incremental information is not profitability",
        "作者并不声称词频替代传统会计指标，还指出合理交易成本可能消除短期策略利润。文本能增加解释信息，与投资者能够稳定兑现收益是两个门槛。理解研究价值，应保留信息测量、价格反应与成本约束这几个层次。",
        "The authors do not claim that word counts replace accounting measures and note that plausible costs may eliminate short-horizon profits. Incremental information and realizable performance are separate thresholds involving measurement, price response and implementation frictions."
      ]
    ]
  ],
  [
    "The Sum of All FEARS Investor Sentiment and Asset Prices",
    "https://rady.ucsd.edu/faculty/directory/engelberg/pub/portfolios/FEARS.pdf",
    [
      "2013年10月7日工作稿",
      "October 7, 2013 draft"
    ],
    "Author-hosted draft cover and printed pp. 1–2 and 5–7 inspected for term selection, US search scope, quarterly normalization, preprocessing and expanding selection. Later result tables and live Google behavior not verified.",
    [
      "搜索是家庭关注与态度的代理，不是持仓或真实交易。所读稿使用历史Google数据和特定处理流程，不能把今天下载的同名指数视为完全相同样本。",
      "Search proxies household attention and attitudes, not holdings or trades. Historical Google data and processing choices define the draft's sample; a current download is not automatically the same dataset."
    ],
    [
      [
        "pp. 1–2",
        "搜索行为提供另一种情绪观察",
        "Search behavior offers another sentiment proxy",
        "作者用经济相关搜索词观察家庭关注，试图区别于直接从价格、成交或资金流构造的市场结果型代理。搜索仍不是人的内心状态，也无法确认每位搜索者都持有股票。指标的对象是聚合行为，而非逐个投资者的真实交易动机。",
        "Economic search queries offer a proxy distinct from market-outcome measures built from prices or flows. Search is not an internal mental state, and users need not own stocks. The observed object is aggregate behavior, not individual trading motives."
      ],
      [
        "pp. 5–6",
        "词表经过多层筛选",
        "The term list passes through several filters",
        "工作稿先用词典中的经济与情绪分类，再扩展相关搜索并去重，最后排除数据不足或语义不属于经济金融的词。最终集合不是任意挑几个悲观词。每一层筛选都会影响覆盖与解释，也需要避免将医疗等同名含义误算成经济担忧。",
        "Dictionary categories are expanded through related searches, deduplicated and filtered for data availability and economic meaning. The final set is not a few arbitrarily chosen pessimistic words. Each filter affects coverage and avoids unrelated meanings such as medical uses."
      ],
      [
        "p. 6",
        "归一化窗口会产生边界问题",
        "Normalization windows create boundary problems",
        "当时的日度搜索量按季度分段下载，每段都用自身最大值缩放。季度内部变化可以比较，但跨季度第一天不能直接相减，因为分母已经变化。这个细节说明，平台给出的相同指标名称，不保证不同请求窗口具有同一尺度。",
        "Daily search data were downloaded by quarter, each scaled to its own maximum. Within-quarter changes are comparable, but the first cross-quarter difference lacks a common denominator. Identical platform labels do not ensure identical scales across request windows."
      ],
      [
        "p. 7",
        "季节性和波动尺度先处理",
        "Address seasonality and scale before aggregation",
        "作者对极端变化截尾，处理星期与月份效应，再将不同词的变化标准化。否则，天然更波动或有固定工作日规律的词可能主导指数。这样的处理定义了指标本身，并非无关清洗步骤；改变它们需要重新评价可比性。",
        "The draft winsorizes changes, removes weekday and month effects, then standardizes term series. Otherwise volatile or seasonal terms could dominate. These transformations define the measure rather than serving as inconsequential cleaning choices."
      ],
      [
        "p. 7",
        "选词依据只向后看仍需完整流程审计",
        "Backward-looking selection is one part of the timing audit",
        "工作稿每半年用此前扩展样本评估词与市场收益的关系，并选取负向关系更强的一组。这个时序有别于用全样本挑词后回测，但不自动保证词表扩展、缩放和预处理也都满足严格实时可得性，整个流程仍需分别核对。",
        "Semiannual expanding regressions select terms using prior observations, unlike selecting once on the full sample. That timing choice does not automatically make vocabulary expansion, scaling and preprocessing fully real-time; each stage needs its own availability audit."
      ],
      [
        "pp. 1–2, 6",
        "美国历史搜索不能代表所有投资者",
        "Historical US searches do not represent every investor",
        "稿中将地域限定为美国，并研究特定历史窗口中的市场、波动与基金流。不同语言、搜索平台或国家的用户构成可能变化。将方法用于中文数据时，需要重新定义词义、覆盖和时间粒度，不能直接翻译词表后继承原文结论。",
        "The draft restricts searches to the United States in a historical window. Languages, platforms and countries can have different users. A Chinese-language application needs new definitions of meaning, coverage and timing rather than inheriting conclusions through word translation."
      ]
    ]
  ],
  [
    "Investor Sentiment in the Stock Market",
    "https://pages.stern.nyu.edu/~jwurgler/papers/wurgler_baker_investor_sentiment.pdf",
    [
      "2007年综述",
      "2007 review"
    ],
    "Printed pp. 130–132 and 134–136 inspected for top-down versus bottom-up approaches, hard-to-value/arbitrage stocks and proxy confounding. Composite-index construction and later result tables not reviewed.",
    [
      "情绪是通过不完美代理衡量的概念，不是价格变动的万能解释。市场共振可能同时反映基本面、风险补偿和资金约束，需要竞争解释。",
      "Sentiment is measured through imperfect proxies, not a universal explanation for price changes. Comovement can also reflect fundamentals, risk compensation and funding constraints."
    ],
    [
      [
        "p. 130",
        "从个体偏差与整体情绪两端研究",
        "Study individual biases and aggregate sentiment separately",
        "综述区分从心理偏差推导市场结果的自下而上研究，以及先衡量整体情绪再观察资产差异的自上而下方法。两者互相补充，但识别对象不同。一个整体指数与收益相关，并不能直接证明某一种个人心理偏差就是背后唯一原因。",
        "The review distinguishes deriving market outcomes from individual biases from measuring aggregate sentiment and tracing asset differences. The approaches complement each other but identify different objects. An aggregate correlation does not uniquely establish a particular psychological bias."
      ],
      [
        "pp. 131–132",
        "情绪与套利限制共同起作用",
        "Sentiment interacts with limits to arbitrage",
        "观点偏离基本面并不自动保证价格长期偏离，还要考虑其他参与者是否有能力承担纠偏交易的成本和风险。综述把需求变化与套利约束一起讨论。因此，看到乐观情绪后，不能省略融资期限、卖空成本等条件就直接推断价格结果。",
        "Beliefs alone do not determine persistent mispricing; corrective traders face costs and risks. The review combines demand shifts with arbitrage limits. Optimism cannot be translated directly into price outcomes without considering horizons, financing and short-sale costs."
      ],
      [
        "p. 132",
        "难估值与难套利往往集中出现",
        "Valuation difficulty and arbitrage difficulty can overlap",
        "年轻、盈利不稳定或未来空间高度不确定的公司，可能同时难以估值和难以进行纠偏交易。这使其成为研究情绪差异的对象。但这些特征并不证明任何具体公司被错误定价，也不能把分组层面的关系当作逐只股票的确定判断。",
        "Young or uncertain firms may be both difficult to value and costly to arbitrage, motivating cross-sectional tests. Such characteristics do not prove mispricing in a particular firm. Group-level associations are not deterministic judgments about individual stocks."
      ],
      [
        "p. 134",
        "同步变化与后续收益分别提问",
        "Separate contemporaneous movement from later returns",
        "情绪变化与当期收益共同变化，可能同时受到基本面消息影响；当前情绪水平与之后收益的关系则是另一项问题。两个检验的时间对象不同。讨论它们时，应避免把同日相关直接说成可提前利用的预测能力或已经成立的因果机制。",
        "Sentiment changes and current returns can share fundamental news, while current sentiment levels and later returns form another test. Their timing differs. Same-day correlation is not automatically advance predictability or an established causal mechanism."
      ],
      [
        "pp. 135–136",
        "代理变量分布在不同因果环节",
        "Proxies sit at different points in a causal chain",
        "问卷观察表达的态度，交易记录观察行为，价格反映市场均衡，发行则还包含企业的融资选择。它们都可能与情绪有关，却不是相同概念的直接重复测量。将几个代理合在一起前，应该先理解各自混入哪些其他经济力量。",
        "Surveys observe stated attitudes, trades observe behavior, prices reflect equilibrium and issuance includes corporate financing choices. These are not repeated direct measurements of one object. Each proxy mixes sentiment with other economic influences."
      ],
      [
        "p. 135",
        "多代理不能自动消除混杂",
        "Multiple proxies do not automatically remove confounding",
        "使用多个不完美代理可以减少依赖单一指标，但它们也可能共享基本面或制度变化。共同成分因此不天然就是纯粹情绪。对综合指标的解释，需要与风险、现金流及样本构成相对照，而不能仅凭几条曲线一起变动就确定标签。",
        "Combining imperfect proxies reduces reliance on one measure, yet shared fundamentals or institutional changes can remain. A common component is not inherently pure sentiment. Interpretation needs comparison with risk, cash flows and sample composition."
      ]
    ]
  ],
  [
    "What Moves Stock Prices?",
    "https://www.nber.org/system/files/working_papers/w2538/w2538.pdf",
    [
      "1988年NBER工作稿",
      "1988 NBER working paper"
    ],
    "Scanned printed pp. 1–4 visually inspected for news-explanation motivation, VAR innovations, historical windows and omitted-information caveats. Later event tables and numerical decompositions not independently reviewed.",
    [
      "可观测新闻未解释的部分，不等于已证明非理性或没有信息。宏观代理、新闻记录和历史频率都有边界，这篇工作稿不是实时价格归因工具。",
      "Variation unexplained by observed news does not prove irrationality or absence of information. Macro proxies, news records and historical frequency limit the analysis; it is not a real-time attribution tool."
    ],
    [
      [
        "p. 1",
        "新闻影响价格与只有新闻影响价格不同",
        "News matters is different from only news matters",
        "作者从一个更强的问题出发：即使公告能够影响股价，是否足以说明全部大幅变化都由可识别新闻解释？这两个命题并不相同。事件研究发现某类消息重要，不能直接推出其他日期的价格变化已经得到完整归因。",
        "Announcements can move prices without explaining every large movement. The paper asks about that stronger claim. Showing that one event type matters does not provide complete attribution for price changes on other dates."
      ],
      [
        "pp. 2–3",
        "宏观消息被定义为未预期部分",
        "Macroeconomic news is an unexpected component",
        "工作稿用向量自回归中的创新项表示宏观变量的未预期变化，而不是简单使用变量当期水平。什么属于意外，取决于预测信息集和模型。因此，测得的新闻是有条件的统计代理，不是研究者已经观察到市场所有新信息。",
        "VAR innovations proxy unexpected macroeconomic changes rather than current levels. Surprise depends on the forecasting model and information set. Measured news is therefore a conditional statistical proxy, not the market's entire new information set."
      ],
      [
        "pp. 3–4",
        "不同频率对应不同信息问题",
        "Different frequencies ask different information questions",
        "文中月度与年度分析使用不同长度的历史窗口，研究宏观变化能够解释多少收益波动。它们不能直接等同于分钟级消息发布后的价格反应。频率决定哪些时序可以被辨认，也限制了对某一天或某次交易的因果解释。",
        "Monthly and annual analyses use different historical windows to study explained return variation. They are not minute-level announcement studies. Frequency determines which timing relationships are observable and limits attribution to a particular day or trade."
      ],
      [
        "p. 4",
        "新闻集合包含金融与实体变量",
        "The news set spans real and financial variables",
        "所选宏观指标涉及股息、生产、货币、利率、通胀与市场波动等不同维度。这样的集合比单一经济新闻更广，但仍然有限。指标覆盖广不代表已经穷尽所有信息，也不能把模型残差简单命名为某一种未测量的心理因素。",
        "The selected variables span dividends, production, money, rates, inflation and volatility. Broader coverage remains finite. Model residuals cannot simply be renamed as a particular unmeasured psychological force because several macro series were included."
      ],
      [
        "p. 2",
        "重大新闻与重大行情是两种筛选",
        "Selecting major news differs from selecting major moves",
        "作者除了宏观模型，还讨论重大世界新闻附近的收益以及大幅行情当天的消息。这是从事件到收益、从收益到事件的两种观察方向。第二种尤其需要警惕事后解释，不能因为容易找到一个故事，就断言已经识别造成行情的原因。",
        "The paper considers returns around major news and news around large moves. These reverse the direction of selection. Searching backward from a price move especially invites retrospective stories; a plausible narrative is not identified causation."
      ],
      [
        "pp. 2–3",
        "解释不足是一项研究问题",
        "Incomplete explanation is a research question",
        "论文指出，可见消息可能无法充分解释所有价格变化，并提出研究信息如何被共同理解以及冲击如何传播。这里的缺口值得继续调查，而不是用没有新闻四个字结束分析。未进入模型或新闻记录的信息，仍可能影响观察到的价格。",
        "The paper motivates work on changing interpretations and shock propagation when visible news explains too little. That gap invites investigation rather than a conclusion of no information. Information outside the model or news record may still affect prices."
      ]
    ]
  ],
  [
    "Annual Report Readability, Current Earnings, and Earnings Persistence",
    "https://www.cis.upenn.edu/~mkearns/finread/readability.pdf",
    [
      "2006年9月15日工作稿",
      "September 15, 2006 draft"
    ],
    "Draft cover and printed pp. 2–4 and 8–11 inspected for readability/length definitions, text filtering, sample dates and obfuscation alternatives. This predates the 2008 article; final-version counts not substituted.",
    [
      "导读依据2006年工作稿。英文可读性指标只覆盖部分阅读负担，不能直接评价中文，也不能仅凭文档难读就判定管理层故意隐瞒。",
      "This uses the 2006 draft. English readability measures capture only part of reading difficulty, do not directly score Chinese, and do not prove intentional concealment."
    ],
    [
      [
        "pp. 2–3",
        "可读性与披露多少是不同维度",
        "Readability differs from the amount disclosed",
        "Li研究的是年报表达方式与当前、未来盈利的关系，不只是公司是否披露更多文字。更长的文件既可能带来更高处理成本，也可能包含更多必要资料。因此，信息数量、表达难度和信息质量不能仅用一个简单长度排序全部代替。",
        "Li studies expression and its relation to current and future earnings, not only disclosure quantity. Longer reports may impose processing costs while adding necessary information. Length alone cannot rank quantity, difficulty and quality together."
      ],
      [
        "p. 10 · equation (1)",
        "Fog衡量句长与复杂词比例",
        "Fog combines sentence length and complex-word share",
        "工作稿的Fog指标将每句词数与复杂词百分比相加再乘系数，复杂词按音节数定义。它衡量英语文本的一些表面特征，而不是全面测试读者理解。金融术语、句子逻辑和版式影响，不能由这个数值单独完整表达。",
        "Fog combines words per sentence and the percentage of complex words, defined through syllables. It measures surface features of English text, not comprehensive reader understanding. Terminology, logical structure and layout are not fully represented by the score."
      ],
      [
        "p. 11 · equation (2)",
        "长度采用词数的对数",
        "Length uses the logarithm of word count",
        "文档长度使用词数的自然对数，以处理不同公司之间偏斜和极端长度。这个指标与Fog并非同一量纲，也更容易混入披露内容多少的影响。若改用页数或原始字符数，需要重新定义可比性，不能直接沿用原来的解释。",
        "Length is the natural logarithm of word count, reducing skewness and extremes across firms. It differs from Fog and can mix difficulty with disclosure quantity. Pages or raw characters would require a new measurement interpretation."
      ],
      [
        "pp. 9–10",
        "清除表格后才测量正文",
        "Measure prose after excluding tables",
        "作者先匹配公司和申报标识，再删除表格、标题等不适合文本公式的内容，并对过短材料筛选。这个处理会决定最终进入计算的文本。直接对整份PDF提取结果评分，可能把数字、断行或表格错误当成语言复杂性。",
        "Company identifiers are matched before tables, headings and unsuitable fragments are removed and short texts filtered. Those decisions define the measured prose. Scoring an unprocessed PDF extraction can mistake numbers, broken lines or tables for linguistic complexity."
      ],
      [
        "pp. 8–9",
        "隐瞒动机是一项解释而非直接观测",
        "Obfuscation is an interpretation, not a direct observation",
        "管理层可能通过提高理解成本延迟坏消息被吸收，但经营复杂性也可能让年报更难读。工作稿围绕当前盈利与未来持续性提出可检验关系。发现相关性后，仍要区分行为动机与文本特征，不能直接给企业贴上隐瞒标签。",
        "Managers might raise processing costs to delay adverse information, while business complexity can also make reports difficult. Earnings relations test implications without directly observing motives. Correlation cannot by itself label a firm intentionally opaque."
      ],
      [
        "pp. 3–4, 10",
        "盈利与亏损、年度与申报日期分开",
        "Separate profit from loss and fiscal from filing dates",
        "文章分别讨论盈利和亏损持续性，样本又受电子申报可得年份限制。财年结束与文件公开日期并不相同，因此未来盈利的对齐必须保留披露时点。英语样本得到的关系，也不能未经语言和制度检验直接移植到中文年报。",
        "Profit and loss persistence are considered separately, and electronic availability bounds the sample. Fiscal year-end differs from filing time, which matters for aligning future outcomes. English-sample findings do not transfer to Chinese reports without language and institutional checks."
      ]
    ]
  ]
].map(guide));
