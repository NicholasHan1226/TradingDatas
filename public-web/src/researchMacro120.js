// Original bilingual commentary, bounded to the cited edition and passages.
import { researchSummaryMaterials } from "./researchSummaryMaterials.js";
const bi = ([zh, en]) => ({ zh, en });
const guide = ([title, url, edition, evidenceScope, limits, rows]) => [title, {
  reviewedAt: "2026-08-31", evidenceUrl: url, evidenceScope, limits: bi(limits), related: researchSummaryMaterials[title] ?? {},
  sections: rows.map(([location, zh, en, bodyZh, bodyEn]) => ({
    title: { zh, en }, body: { zh: bodyZh, en: bodyEn },
    reference: { url, label: { zh: edition[0] + " · " + location, en: edition[1] + " · " + location } },
  })),
}];

export const researchMacro120 = Object.fromEntries([
  [
    "The Stock Market's Reaction to Unemployment News: Why Bad News Is Usually Good for Stocks",
    "https://www.nber.org/system/files/working_papers/w8092/w8092.pdf",
    [
      "2001年1月NBER工作稿8092",
      "January 2001 NBER WP 8092"
    ],
    "NBER cover visually inspected; printed pp. 3–6 read for expansion/contraction conditioning, announcement responses, rate/growth/risk channels and bond/utility comparisons. No later table estimate or 2005 final-version substitution made.",
    [
      "导读使用2001年工作稿，而非2005年发表版的完整检验。历史公告反应依赖经济状态和信息预期，标题不能直接变成今天的买卖规则。",
      "This uses the 2001 draft rather than the complete tests in the 2005 publication. Historical responses depend on economic state and expectations; the title is not a current trading rule."
    ],
    [
      [
        "pp. 3–4",
        "同一条失业消息可能有不同含义",
        "The same unemployment news can mean different things",
        "作者把失业消息与股价反应放在经济扩张和收缩两种背景中比较。消息不仅涉及就业本身，还可能改变市场对利率和企业未来收入的判断。因此，不能只根据失业率上升或下降，就给股票反应指定一个固定方向。",
        "The authors compare stock responses to unemployment news across expansions and contractions. Employment information can change both interest-rate and earnings expectations. A rise or fall in unemployment alone therefore does not determine a fixed direction for equity prices."
      ],
      [
        "pp. 3–4",
        "折现率与现金流渠道可能相反",
        "Discount-rate and cash-flow channels can oppose each other",
        "就业恶化可能意味着未来现金流变弱，也可能伴随对较低利率的预期。两条渠道对估值的影响可能相反，风险补偿还会增加另一层变化。文章的问题正是这些力量在不同状态下怎样合成，而不是坏消息本身能创造价值。",
        "Weaker employment can signal weaker cash flows while also shifting expectations toward lower rates. These channels can pull valuations in opposite directions, with risk compensation adding another component. The question is their state-dependent combination, not whether bad news intrinsically creates value."
      ],
      [
        "pp. 4–5",
        "股债比较提供渠道线索",
        "Stock–bond comparisons offer channel evidence",
        "债券与股票对利率变化的敏感度不同，对企业现金流的依赖也不同。工作稿利用这种差异帮助解释公告反应，但两类资产的共同变化并不能自动排除风险溢价等因素。渠道线索仍需要识别假设，不能只看相关方向。",
        "Bonds and equities differ in sensitivity to rates and corporate cash flows. The draft uses these differences to interpret announcements. Their comovement does not automatically rule out risk-premium changes; channel evidence still relies on identifying assumptions rather than correlation alone."
      ],
      [
        "pp. 4–6",
        "预期增长不能被直接看见",
        "Expected growth is not directly observed",
        "研究需要用可观察指标帮助判断增长渠道，但未来实现的经济活动并不等于公告当时投资者的预期。代理变量可以提供间接证据，也引入测量误差与解释空间。阅读结果时，应保留真实预期、代理指标和后续实现值之间的区别。",
        "Observable measures help investigate the growth channel, but subsequently realized activity is not identical to investors' announcement-time expectations. Proxies provide indirect evidence with measurement error. Expectations, proxy variables and later realizations should remain distinct."
      ],
      [
        "pp. 5–6",
        "不同行业可帮助检验机制",
        "Industry differences help probe the mechanism",
        "工作稿比较盈利对经济周期敏感程度不同的股票，包括公用事业类公司。若现金流渠道重要，行业差异应当有解释价值，但行业同时还可能有杠杆、监管或久期差异。因此，这种比较是机制检验的一部分，不是无条件的行业轮动规则。",
        "The draft compares equities with different cyclical earnings sensitivity, including utilities. Such contrasts can inform the cash-flow mechanism, while leverage, regulation and duration may also differ. The comparison is a mechanism check, not an unconditional sector-rotation rule."
      ],
      [
        "pp. 3–6",
        "标题不能替代状态与信息时点",
        "The title cannot replace state and timing",
        "文章讨论的是历史公告窗口中的信息反应，不是失业率水平与股票长期收益的简单关系。使用这类文献时，必须先界定消息相对预期的变化、经济状态及观测窗口。直接把标题改写成“数据越差越该买”，会丢掉研究的核心条件。",
        "The paper studies historical announcement responses, not a simple relation between unemployment levels and long-run stock returns. News relative to expectations, economic state and the observation window come first. Turning the title into 'buy worse data' discards those central conditions."
      ]
    ]
  ],
  [
    "The Macroeconomy and the Yield Curve: A Dynamic Latent Factor Approach",
    "https://glennrudebusch.com/wp-content/uploads/2006_JoE_Diebold-Rudebusch-Aruoba_The-Macroeconomy-and-the-Yield-Curve-A-Dynamic-Latent-Factor-Approach.pdf",
    [
      "2006年期刊版，309–338页",
      "2006 journal version, pp. 309–338"
    ],
    "Journal-version PDF printed pp. 309–312 inspected for latent level/slope/curvature, macro observables, short-minus-long slope convention, joint state-space estimation and absence of explicit no-arbitrage restrictions. Later estimates not reproduced.",
    [
      "采用期刊分页版本的模型说明。潜在因子与宏观变量之间的动态关联不自动识别因果冲击；曲线拟合良好，也不等于已经满足无套利约束。",
      "This uses the journal-paginated model description. Dynamic associations do not automatically identify causal shocks, and a good curve fit does not establish satisfaction of no-arbitrage restrictions."
    ],
    [
      [
        "pp. 309–310",
        "把收益率曲线与宏观变量放在一起",
        "Bring the curve and macro variables together",
        "作者将不同期限收益率的共同变化，与经济活动、通胀和政策利率等可观察变量联合建模。目标不只是单独拟合一条曲线，也关注曲线与宏观经济之间的信息联系。模型输入有不同经济含义，不能把每个因子都命名为政策冲击。",
        "The model combines common yield movements with observable activity, inflation and policy-rate variables. It goes beyond fitting an isolated curve to examine macro-financial information links. These inputs have different meanings; latent factors cannot all be relabelled policy shocks."
      ],
      [
        "pp. 310–312",
        "水平、斜率和曲率是压缩方式",
        "Level, slope and curvature compress the curve",
        "大量期限的收益率被少数潜在因子概括，因子通过不同期限载荷形成整条曲线。这样能降低维度，却不表示三个因子解释了所有经济机制。它们首先是描述曲线形状的统计结构，经济解释还需要额外证据。",
        "A few latent factors summarize yields through maturity-specific loadings. This reduces dimension without identifying every economic mechanism. Level, slope and curvature first provide a statistical description of shape; their economic interpretation requires additional evidence."
      ],
      [
        "pp. 311–312",
        "斜率的正负要先核对定义",
        "Check the slope sign convention first",
        "本文的斜率因子采用与短端减长端相联系的方向，不能直接套用常见的长端减短端利差。两者可能只有一个符号差异，却会把关联方向完全翻转。比较图表或其他论文时，应同时核对期限、单位和斜率定义。",
        "The slope convention corresponds to short minus long, unlike the familiar long-minus-short term spread. A sign reversal can invert an interpreted association. Cross-paper comparisons must align maturities, units and the precise slope definition before comparing coefficients or charts."
      ],
      [
        "pp. 311–312",
        "联合估计保留因子测量的不确定性",
        "Joint estimation retains the measurement structure",
        "状态空间方法把曲线的观测关系与因子的动态关系放在同一模型中估计。它与先逐期拟合因子、再把估计值当作已知变量做回归不同。理解这种安排，有助于区分实际观察到的收益率与由模型推断出来的状态。",
        "State-space estimation combines the observation relation for yields with factor dynamics. This differs from fitting factors period by period and then treating their estimates as known regressors. Observed yields and model-inferred states therefore remain distinct objects."
      ],
      [
        "pp. 309–310",
        "双向动态不等于双向因果",
        "Bidirectional dynamics are not automatic causality",
        "模型允许宏观变量影响之后的曲线，也允许曲线携带关于后续宏观变化的信息。这种动态联系可以帮助理解预测与反馈，但结构性政策解释仍依赖识别条件。发现先后相关，不足以证明主动改变某个因子就会产生同样结果。",
        "The model permits macro variables to influence subsequent yields and yields to contain information about later macro developments. Such dynamics inform prediction and feedback. Structural policy interpretation still needs identification; temporal association does not establish intervention effects."
      ],
      [
        "pp. 310–312",
        "拟合与无套利是两项不同要求",
        "Fit and no-arbitrage are separate requirements",
        "作者的框架没有在此显式施加无套利限制，而是强调简洁的曲线与宏观动态描述。良好的历史拟合不能独立证明不存在套利，也不意味着能够准确预测未来债券收益。使用模型前，应明确目标是描述、预测还是定价约束检验。",
        "The framework does not impose explicit no-arbitrage restrictions here, emphasizing a parsimonious curve–macro description. Historical fit proves neither absence of arbitrage nor accurate future bond-return forecasts. Description, forecasting and pricing-restriction tests are different objectives."
      ]
    ]
  ],
  [
    "Carry",
    "https://www.nber.org/system/files/working_papers/w19325/w19325.pdf",
    [
      "2013年8月NBER工作稿19325",
      "August 2013 NBER WP 19325"
    ],
    "NBER w19325 cover, abstract and printed pp. 1–3 inspected for ex-ante carry definition, price-change decomposition, cross-asset construction and static/dynamic distinction. Later asset-specific formulas and performance tables not reconstructed.",
    [
      "所读为2013年工作稿，不替代2018年发表版的全部结果。Carry不是保证收益；跨资产的融资、展期、价格变化和尾部风险不能被一个同名指标抹平。",
      "This uses the 2013 draft, not all results of the 2018 publication. Carry is not guaranteed return; financing, rolling, price changes and tail risk differ across asset classes despite the shared label."
    ],
    [
      [
        "pp. 1–2",
        "Carry先问价格不变时会怎样",
        "Carry starts with an unchanged-price scenario",
        "论文把carry定义为在相关价格不变的条件下，持有资产可以预先衡量的收益组成部分。它与之后真正发生的价格涨跌分开。因此，观察到正carry只说明这个条件情景下的持有回报为正，并没有预测全部实际收益。",
        "Carry is the ex-ante measurable return component under an unchanged-price scenario. It is separated from subsequent price movements. Positive carry therefore describes a conditional holding-return component, not a forecast or guarantee of the complete realized return."
      ],
      [
        "pp. 1–2",
        "总收益还包含价格变化",
        "Total return also includes price changes",
        "实际回报可以分成carry以及预期和意外的价格变化。价格变化可能抵消甚至超过carry，所以高carry与高实际收益并非同义词。分析时保留这种分解，有助于避免把可提前计算的部分误当成未来已经锁定的结果。",
        "Realized return also contains expected and unexpected price changes. These may offset or exceed carry, so high carry is not synonymous with high realized performance. The decomposition separates what can be measured beforehand from what remains uncertain."
      ],
      [
        "pp. 1–3",
        "跨资产统一概念，不是统一数据列",
        "Unify the concept, not the data column",
        "外汇、债券、商品和股票都可以讨论carry，但其经济来源与构造输入不同。利差、曲线形状、便利收益或股息相关信息不能简单放进同一列后直接比较。统一框架的价值，是对齐条件回报概念，而不是省略资产特有的定义。",
        "Currencies, bonds, commodities and equities admit carry measures with different sources and inputs. Rate differentials, curve shape, convenience yield and dividend-related information are not interchangeable columns. The framework aligns a conditional-return concept while preserving asset-specific definitions."
      ],
      [
        "pp. 2–3",
        "长期平均与随时间变化分开",
        "Separate long-run averages from time variation",
        "一种资产长期平均carry较高，和同一资产的carry在某个时期升高，是不同问题。工作稿区分静态与动态成分，帮助理解跨资产差异和时间变化分别提供什么信息。不能把横截面关系直接解释成每次指标上升都有效。",
        "An asset's high long-run average carry differs from a temporary rise in its own carry. Static and dynamic components separate cross-asset differences from time variation. A cross-sectional association does not imply that every within-asset increase has the same consequence."
      ],
      [
        "pp. 1–3",
        "条件价格假设必须写清楚",
        "Make the price convention explicit",
        "价格不变的情景需要对应到具体资产和合约定义；期限推进、结算和展期都可能影响衡量方式。若不同研究使用不同价格基准，同名carry也未必可直接拼接。比较之前，应先核对持有期、计价方式与价格变化部分如何划分。",
        "An unchanged-price scenario depends on the asset and contract convention, including horizon and rolling treatment. Measures with different price benchmarks need not be directly pooled. Compare holding periods, quotation conventions and the separation of price changes before combining carry series."
      ],
      [
        "abstract; pp. 1–3",
        "平常分散不代表压力时独立",
        "Ordinary diversification is not stress independence",
        "工作稿还关注carry在压力时期共同受损的可能性。平常相关性较低，不意味着极端阶段也能相互抵消；跨资产名称不同，也不保证风险来源独立。因此，解释carry时应同时讨论条件收益和共同尾部风险，而不是只排列平均回报。",
        "The draft also considers common losses in stressful periods. Low ordinary correlation does not guarantee offsetting outcomes in extremes, and different asset labels do not imply independent risks. Conditional return components and shared tail exposure belong in the same discussion."
      ]
    ]
  ],
  [
    "SRISK: A Conditional Capital Shortfall Measure of Systemic Risk",
    "https://www.esrb.europa.eu/pub/pdf/wp/esrbwp37.en.pdf",
    [
      "2017年3月ESRB工作稿37",
      "March 2017 ESRB WP 37"
    ],
    "ESRB Working Paper 37 printed pp. 2–5 and 7–8 inspected for conditional capital shortfall, book debt/market equity, LRMES, positive-part aggregation and the edition-specific h=22, C=-10% stress scenario. No current institution estimate reproduced.",
    [
      "导读依据ESRB工作稿的具体情景，不是当前机构风险排名。资本比率、压力窗口与市场跌幅均需注明版本，不能把论文设定写成通用监管要求。",
      "This uses the ESRB paper's specific scenario, not a current institution ranking. Capital ratios, stress horizons and market declines are versioned assumptions rather than universal regulatory requirements."
    ],
    [
      [
        "pp. 2–3",
        "SRISK衡量条件下的资本缺口",
        "SRISK measures a conditional capital shortfall",
        "SRISK问的是：如果整个市场进入指定压力情景，一家机构预期会缺少多少资本。它不是市场危机发生的概率，也不是机构必然需要得到的救助金额。条件情景与情景发生概率是两层信息，不能合并成一个看似确定的风险数字。",
        "SRISK asks how much capital an institution is expected to lack conditional on a specified market stress. It is not the probability of that stress or a certain bailout bill. A conditional shortfall and the probability of its conditioning event are separate quantities."
      ],
      [
        "pp. 3–5",
        "账面债务与市场权益承担不同角色",
        "Book debt and market equity play different roles",
        "指标结合账面债务、市场权益和压力下的权益损失预期。债务与股价数据来自不同计量体系和时点，不能简单拿两个最新数字相除就声称复现。工作稿还在压力窗口内对债务作出假设，这也是计算边界的一部分。",
        "The measure combines book debt, market equity and expected equity losses in stress. Accounting and market quantities have different measurement conventions and dates. Combining two latest values does not reproduce the method, which also makes an assumption about debt over the stress horizon."
      ],
      [
        "pp. 7–8",
        "压力窗口属于版本定义",
        "The stress window is edition-specific",
        "这份ESRB工作稿的实现使用22个交易期，并以市场跌幅超过10%定义相应压力事件。其他资料可能采用不同窗口和阈值，不能因为都称为SRISK就互换。每一个结果都应同时保留窗口、市场基准及阈值方向。",
        "This ESRB implementation uses 22 trading periods and a market decline exceeding 10% for its stress event. Other implementations may use different horizons or thresholds. A shared SRISK label does not make these settings interchangeable; horizon, market benchmark and threshold direction travel with the result."
      ],
      [
        "pp. 3–5",
        "规模、杠杆与尾部损失共同作用",
        "Size, leverage and tail losses work jointly",
        "机构资本缺口既可能因为规模大，也可能因为杠杆高或在市场压力下权益损失更严重。只用股价波动排序，会遗漏资产负债结构；只看杠杆也会遗漏与市场下跌共同发生的损失。指标的组合结构正是为了保留这些区别。",
        "A large shortfall can reflect size, leverage or severe equity losses during market stress. Ranking volatility alone omits balance-sheet structure; leverage alone omits stress dependence. The combined measure retains these distinct contributors rather than treating them as equivalent."
      ],
      [
        "pp. 4–5",
        "系统汇总只累计正缺口",
        "System aggregation uses positive shortfalls",
        "汇总系统风险时，作者累计存在正资本缺口的机构，而不直接让另一家机构的资本盈余抵消。原因是不能假定压力时资本可以无摩擦地跨机构转移。因此，系统指标不是所有机构带符号缺口的简单净和。",
        "The aggregate includes positive institutional shortfalls rather than automatically offsetting them with capital surpluses elsewhere. Capital cannot simply be assumed to transfer frictionlessly between firms in stress. System SRISK is therefore not the net signed sum of all institutional values."
      ],
      [
        "pp. 2–5, 7–8",
        "压力度量不能替代完整监管判断",
        "A stress measure is not a complete supervisory judgment",
        "估计结果依赖市场信息、损失模型和资本要求假设，并存在不确定性。工作稿中的比例不应被写成对所有地区和机构都有效的规则。把SRISK作为对照指标有帮助，但判断真实资本充足、流动性和处置需要更完整的机构资料。",
        "Estimates depend on market information, a loss model and assumed capital requirements, with uncertainty. A paper's ratio is not a universal rule for all jurisdictions or firms. SRISK can inform comparison without replacing evidence on actual capital adequacy, liquidity and resolution."
      ]
    ]
  ],
  [
    "The Leverage Cycle",
    "https://cowles.yale.edu/sites/default/files/2022-08/d1715.pdf",
    [
      "2009年Cowles讨论稿1715",
      "2009 Cowles Discussion Paper 1715"
    ],
    "Cowles July 2009 cover and June 24, 2009 author manuscript printed pp. 1–3 inspected for collateral equilibrium, haircut/LTV/leverage definitions, heterogeneous valuations and historical margin evidence. Later model proofs and 2010 version not substituted.",
    [
      "导读采用2009年讨论稿。抵押要求与价格反馈是理论机制，少数历史融资例子不代表所有市场；文中的制度建议也不是当前政策或交易建议。",
      "This uses the 2009 discussion paper. Collateral–price feedback is a theoretical mechanism; selected historical financing examples do not represent all markets, and policy proposals are not current advice."
    ],
    [
      [
        "pp. 1–2",
        "信贷条件不只有利率",
        "Credit conditions include more than interest rates",
        "Geanakoplos强调，借款合约除了利率，还规定需要多少抵押品或自有资金。两笔名义利率相同的贷款，可能因为抵押要求不同而提供完全不同的购买能力。因此，只追踪融资价格，会遗漏融资数量的重要约束。",
        "Geanakoplos emphasizes collateral and own-funds requirements alongside interest rates. Loans at the same quoted rate can provide very different purchasing power when margins differ. Monitoring the price of credit alone therefore misses a major constraint on its quantity."
      ],
      [
        "pp. 1–2",
        "保证金、贷款价值比和杠杆不是同一个数",
        "Margin, loan-to-value and leverage are different ratios",
        "这些指标从不同分母描述同一融资安排：自有资金占资产价值的比例、借款占资产价值的比例，以及资产相对自有资金的倍数。比例方向不同，紧缩时变化方向也可能相反。跨数据源比较前，应明确各自的分子与分母。",
        "These ratios use different denominators: own funds relative to asset value, borrowing relative to value, and assets relative to own funds. Their directions can differ during tightening. Cross-source comparison requires explicit numerators and denominators rather than a shared 'leverage' label."
      ],
      [
        "pp. 2–3",
        "谁能借到钱会影响边际价格",
        "Borrowing capacity can influence marginal pricing",
        "当参与者对资产的评价不同，最看好资产的人能投入多少资金，会影响谁成为边际买方。更宽松的抵押要求可能扩大这些买方的购买能力。价格因此不仅反映平均看法，也与财富分布和可获得融资相联系。",
        "With heterogeneous valuations, the funding available to optimistic buyers affects who prices the marginal unit. Looser collateral requirements can expand their purchasing capacity. Prices consequently depend on wealth and financing access, not only an average assessment of asset value."
      ],
      [
        "pp. 1–3",
        "抵押收紧与价格下跌可能相互强化",
        "Tighter collateral and falling prices can reinforce each other",
        "价格下降会影响抵押品价值，而要求更多自有资金又可能压缩购买能力并加重卖出压力。论文用杠杆周期理解这种反馈。它不要求把所有行为解释为非理性恐慌，也不意味着每次价格下跌都能仅由融资条件解释。",
        "Falling prices affect collateral value, while higher own-funds requirements can reduce buying capacity and intensify selling pressure. The leverage cycle examines this feedback without reducing all behavior to irrational panic or attributing every price decline solely to funding conditions."
      ],
      [
        "pp. 1–3",
        "降息未必恢复同样的购买能力",
        "Lower rates need not restore purchasing capacity",
        "如果约束来自所需自有资金上升，降低贷款利率未必能让买方恢复原来的持仓规模。融资成本和融资上限是不同维度。理解这点，有助于比较利率政策与抵押条件变化，但不能据此自动推出某项政策必然有效。",
        "When required own funds rise, cutting loan rates need not restore the previous position size. Financing cost and financing capacity are different dimensions. This helps compare rate policy with collateral changes without establishing that a particular intervention must succeed."
      ],
      [
        "pp. 2–3",
        "历史保证金例子不是全市场统计",
        "Historical margin examples are not market-wide estimates",
        "工作稿借历史融资安排说明抵押条件能够剧烈变化。这些例子有具体资产、机构和时间背景，不能直接外推成整个金融系统的平均杠杆。用论文指导数据收集时，应该保留合约类型、抵押资产和融资主体的层级。",
        "Historical financing examples illustrate that collateral terms can change sharply. They have particular assets, institutions and dates and cannot be extrapolated into system-wide average leverage. Contract type, collateral identity and borrower level should remain visible in any resulting data collection."
      ]
    ]
  ],
  [
    "Monetary Policy Shocks: What Have We Learned and to What End?",
    "https://www.nber.org/system/files/working_papers/w6400/w6400.pdf",
    [
      "1998年2月NBER工作稿6400",
      "February 1998 NBER WP 6400"
    ],
    "NBER w6400 cover and printed introduction pp. 1–2 visually read for identification of policy innovations, the three-step model-evaluation exercise, feedback-rule assumptions and recursive linear residual interpretation. Later VAR specifications not reviewed.",
    [
      "导读限于1998年工作稿的识别框架与研究动机。未把后文模型结果作为已重估证据，也不将当时的政策工具或假设视为今天所有央行的实际做法。",
      "This is bounded to the 1998 draft's identification framework and motivation. Later model results are not presented as re-estimated evidence, and historical instruments or assumptions are not universal current central-bank practice."
    ],
    [
      [
        "pp. 1–2",
        "政策动作不等于政策冲击",
        "A policy action is not a policy shock",
        "央行会根据经济情况改变政策，所以观察到利率上升，并不能直接把之后的经济变化归因于一次外生冲击。研究首先要分开对已有信息的系统性反应与意外变化。若不做区分，经济恶化促成的政策调整就可能被误当成恶化原因。",
        "Central banks respond to economic conditions, so an observed rate increase is not automatically an exogenous shock. The first distinction is between a systematic response to information and an innovation. Otherwise a policy response to deterioration can be mistaken for its cause."
      ],
      [
        "p. 1",
        "先定义实验，再比较经济与模型",
        "Define the experiment before comparing data and models",
        "作者描述的研究路径包括识别一个外生政策实验、估计经济对它的反应，再让理论模型接受同样的实验。关键是保持实验对象一致。若数据中的意外利率变化与模型中的永久规则切换不是同一件事，比较就会失去含义。",
        "The proposed exercise identifies an exogenous policy experiment, estimates the economy's response, and subjects a theoretical model to the same experiment. The object must stay consistent: an unexpected rate innovation is not interchangeable with a permanent change in the policy rule."
      ],
      [
        "pp. 1–2",
        "反应规则依赖央行的信息集合",
        "A feedback rule depends on the information set",
        "识别政策意外变化，需要假设决策者根据哪些信息作出反应，以及采用什么政策工具和函数形式。遗漏决策者已经看到的变量，可能让正常反应落入所谓冲击之中。因此，信息集合是研究设计的一部分，而不是可随意省略的背景。",
        "Identifying innovations requires assumptions about the policymaker's information, instrument and response function. Omitting variables already observed by policymakers can put systematic responses into the estimated shock. The information set is therefore part of identification, not optional background."
      ],
      [
        "p. 2",
        "回归残差并不天然外生",
        "A regression residual is not inherently exogenous",
        "在线性设定下，研究者可以用回归残差表示未被规则解释的部分，但残差只是相对于所选变量而言。把它称为外生政策冲击，还需要额外的正交性或递归识别假设。统计上的拟合剩余，不会自动变成经济学上的自然实验。",
        "In a linear setup, a residual represents what the selected rule does not explain. Calling it an exogenous policy shock additionally requires orthogonality or recursive identification assumptions. A statistical remainder does not automatically become an economic natural experiment."
      ],
      [
        "pp. 1–2",
        "冲击响应检验模型的一部分",
        "Shock responses test part of a model",
        "如果一个模型不能解释识别出的政策意外变化所带来的动态反应，它的结构可能需要重新考虑。但成功匹配这一类响应，也不证明所有机制或其他政策实验都正确。研究把冲击作为约束模型的证据，而不是一次性验证整个模型的印章。",
        "Failure to match responses to identified policy innovations can challenge a model's structure. Success does not validate every mechanism or every other policy experiment. Shock responses constrain a model without providing a one-time certificate of complete correctness."
      ],
      [
        "p. 1",
        "更换政策规则是另一个反事实",
        "Changing the policy rule is another counterfactual",
        "理解经济怎样回应一次意外政策变化，有助于建模，却不能直接回答长期采用另一套政策规则会怎样。后者改变的是系统性行为和预期形成环境。阅读政策冲击文献时，应保留局部实验与制度性反事实之间的差别。",
        "Learning how the economy responds to one policy innovation helps model evaluation without directly answering the consequences of a different enduring rule. That counterfactual changes systematic behavior and expectations. Local shock experiments and institutional rule changes remain different questions."
      ]
    ]
  ]
].map(guide));
