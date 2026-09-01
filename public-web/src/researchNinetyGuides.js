// Original bilingual commentary on explicitly bounded primary-source passages.
const bi = ([zh, en]) => ({ zh, en });
// Preparation examples only, not the historical NYSE sample or a replication.
const materials = { "Risk, Return, and Equilibrium: Empirical Tests": { recipes: ["adjusted-price-series"] } };
const guide = ([title, url, edition, evidenceScope, limits, rows]) => [title, {
  reviewedAt: "2026-08-31", evidenceUrl: url, evidenceScope, limits: bi(limits), related: materials[title] ?? {},
  sections: rows.map(([location, zh, en, bodyZh, bodyEn]) => ({
    title: { zh, en }, body: { zh: bodyZh, en: bodyEn },
    reference: { url, label: { zh: edition[0] + " · " + location, en: edition[1] + " · " + location } },
  })),
}];

export const researchNinetyGuides = Object.fromEntries([
  [
    "An Intertemporal Capital Asset Pricing Model",
    "https://breesefine7110.tulane.edu/wp-content/uploads/sites/16/2015/10/Merton-Int.-CAPM.pdf",
    [
      "1973年期刊版",
      "1973 journal article"
    ],
    "Printed pp. 867–870 visually inspected from the scanned journal copy: lifetime choice, opportunity sets, market assumptions and asset supply. Later separation results and proofs not reviewed.",
    [
      "这是连续时间均衡理论，不是当前市场的估计模型。无交易成本、相同借贷利率和可卖空等假设，不能直接当作现实账户条件。",
      "This is continuous-time equilibrium theory, not a fitted model of today's market. Frictionless trading, common borrowing rates and short selling are assumptions, not account capabilities."
    ],
    [
      [
        "pp. 867–868",
        "把一个持有期放回一生",
        "Put one holding period into lifetime choice",
        "Merton把消费与投资放进持续决策的问题。今天的资产选择不仅影响下一期财富，也影响以后能怎样消费和配置资产。因此，单期均值与方差的比较，未必完整描述一个面向长期的投资者所关心的风险。",
        "Merton embeds consumption and investment in continuing choice. Today's holdings affect both next-period wealth and later opportunities to consume and invest. A one-period mean–variance comparison need not capture every risk relevant to a lifetime decision."
      ],
      [
        "p. 869",
        "机会集本身也会变化",
        "The opportunity set can itself change",
        "未来可获得的收益分布并不一定保持不变。投资者除了关心财富涨跌，还可能在意利率或其他投资条件的变化。理解跨期风险，要把资产本身的当期收益与未来可投资机会的状态分开，而非只增加一个预测期限。",
        "Future return distributions need not stay fixed. Investors can care about changing investment conditions as well as changing wealth. Intertemporal risk therefore separates current asset returns from the state of future opportunities, rather than merely extending a forecast horizon."
      ],
      [
        "pp. 868–869",
        "共同预期仍然是一项假设",
        "Common expectations remain an assumption",
        "从单期转向跨期，并不意味着论文同时解决了所有市场摩擦。作者仍保留共同预期、价格接受者与市场出清等条件。比较模型时，应识别究竟放松了哪一项假设，不能把动态结构误读成对现实复杂性的全面覆盖。",
        "Moving to multiple periods does not resolve every friction. Common expectations, price taking and market clearing remain assumptions. Model comparisons should identify the particular restriction being relaxed; a dynamic structure is not comprehensive realism."
      ],
      [
        "p. 868",
        "融资与交易条件先于推论",
        "Financing assumptions precede conclusions",
        "模型允许连续交易、资产可分割和卖空，并采用相同的借贷利率，同时忽略税费及交易成本。这些条件帮助建立理论关系，却与有交易时段、融资额度或借券限制的账户不同，不能将理论可行组合直接视为可实施方案。",
        "Continuous trading, divisibility, short selling and common lending and borrowing rates simplify the argument. Taxes and transaction costs are absent. The feasible set differs from an account with trading hours, credit limits or restricted stock borrowing."
      ],
      [
        "p. 870",
        "资产总价值不等于每股价格",
        "Total asset value differs from a share price",
        "讨论资产供给时，论文区分资产产生消费品的能力与所有权份额的价格。新增投资、折旧或发行会改变总资产及份额数量。观察公司总价值的变化时，不能省略股数变化而直接解释成现有每股持有者的收益。",
        "The supply discussion separates productive assets from ownership shares. Investment, depreciation or issuance can alter asset totals and share counts. A change in aggregate firm value cannot be read as an existing shareholder's return without accounting for those quantities."
      ],
      [
        "pp. 867–870",
        "跨期框架提出更具体的问题",
        "The framework sharpens the question",
        "阅读这篇文章的价值，是重新问清楚什么状态对未来消费不利，以及哪些资产与这些状态共同变化。它并没有仅凭历史价格就提供答案；从理论状态到可观测变量，还需要另外建立测量、样本和经验检验之间的联系。",
        "The framework asks which states harm future consumption and which assets move with them. Historical prices alone do not answer that question. Connecting theoretical states to observations requires separate measurement choices, sample definitions and empirical tests."
      ]
    ]
  ],
  [
    "The Arbitrage Theory of Capital Asset Pricing",
    "https://jacobslevycenter.wharton.upenn.edu/wp-content/uploads/2016/10/The-Arbitrage-Theory-of-Capital-Asset-Pricing.pdf",
    [
      "1976年期刊版",
      "1976 journal article"
    ],
    "Printed pp. 341–343 inspected, including the factor representation, diversified zero-cost heuristic and the author's explicit warning about its weaknesses. Later formal proofs not reviewed.",
    [
      "APT的分散化论证依赖共同因子与剩余风险的结构。高历史拟合度不证明无套利，也不能把有限样本的估计误差当作确定利润。",
      "APT relies on common-factor and residual-risk structure. A good historical fit does not establish no-arbitrage, and finite-sample estimation errors are not certain profits."
    ],
    [
      [
        "p. 341",
        "定价约束不必从市场组合出发",
        "Pricing restrictions need not start from a market portfolio",
        "Ross寻找的是由资产收益共同结构与套利约束形成的定价关系，而不是先把某个市场指数指定为唯一风险来源。这个出发点改变了理论组织方式，但不意味着随意添加任何统计变量，都能自动得到有经济意义的定价因子。",
        "Ross seeks pricing restrictions from common return structure and arbitrage constraints, rather than privileging a market index as the only risk source. That starting point does not make every statistical predictor an economically meaningful pricing factor."
      ],
      [
        "p. 342 · equation (2)",
        "先分共同变化与剩余变化",
        "Separate common and residual variation",
        "示例把资产收益分为期望收益、对共同因子的暴露，以及资产自身的剩余项。因子暴露描述共同冲击如何传递，不是某资产全部波动的别名。剩余项之间能否充分分散，是后续论证的关键条件，而非可忽略的技术细节。",
        "The example separates expected return, common-factor exposure and an asset-specific residual. Exposure describes transmission of shared shocks, not total volatility. Whether residuals can be diversified is essential to the argument, not a disposable technical detail."
      ],
      [
        "p. 342 · steps 1–2",
        "零成本还要有足够分散",
        "Zero cost also requires diversification",
        "作者构造的启发式组合不仅净投入为零，还要求单项权重随资产数量增加而缩小。若少数头寸占据大部分规模，剩余风险未必消失。因此，多空金额相抵与足够分散是两个不同条件，不能仅凭前者宣称组合已经无风险。",
        "The heuristic uses both zero net investment and individual weights that shrink as the asset count grows. Concentrated positions can retain residual risk. Offsetting long and short expenditure is therefore distinct from adequate diversification."
      ],
      [
        "pp. 342–343 · steps 3–4",
        "消除因子暴露不等于消除一切误差",
        "Removing factor exposure does not remove every error",
        "在共同因子暴露为零且剩余风险可以分散的条件下，组合收益接近由期望收益决定的部分。这里的近似依赖资产数量和误差结构。实证中估计出来的零暴露仍有误差，也不处理融资、借券与实际执行成本。",
        "With zero common-factor exposure and diversifiable residuals, portfolio returns approach their expected component. This approximation depends on asset count and error structure. Estimated neutrality still contains uncertainty and says nothing by itself about financing or execution costs."
      ],
      [
        "p. 343",
        "暴露与风险价格是不同对象",
        "Exposure and risk price are different objects",
        "线性定价表达式将资产对因子的敏感度，与共同因子所对应的收益补偿分开。两者在概念上承担不同角色：一个描述收益如何共同变化，另一个描述这种暴露如何定价。对收益做回归，不能自动同时识别全部经济解释。",
        "A linear pricing relation separates sensitivity to a factor from compensation associated with that exposure. One describes comovement; the other prices it. A return regression does not automatically identify every economic interpretation of both quantities."
      ],
      [
        "p. 343",
        "作者也指出启发式论证的缺口",
        "The author flags weaknesses in the heuristic",
        "论文明确提醒，简单使用大数定律的直觉仍有漏洞，例如财富与风险厌恶随资产数量变化，可能影响结论。读者应把入门论证与后续正式条件区分开来，不能将几步组合代数当作适用于所有有限市场的完整无套利证明。",
        "Ross explicitly notes weaknesses in the introductory argument, including how wealth and risk aversion may change with the number of assets. The heuristic must be distinguished from later formal conditions; a few portfolio identities are not a universal finite-market proof."
      ]
    ]
  ],
  [
    "Asset Prices in an Exchange Economy",
    "https://www.economics.utoronto.ca/adamopou/lucas_ap.pdf",
    [
      "1978年期刊版",
      "1978 journal article"
    ],
    "Printed pp. 1429–1432 inspected for the exchange economy, endowment process, timing, rational expectations and equilibrium definition. Subsequent proof and quantitative implications not reviewed.",
    [
      "模型中的同质消费者、外生产出和无储存消费品是刻意简化。它研究价格如何与决策相容，不是对现实交易量或投资者学习过程的直接解释。",
      "Identical consumers, exogenous output and a perishable consumption good are deliberate simplifications. The model studies consistency between prices and choices, not actual trading volume or learning."
    ],
    [
      [
        "pp. 1429–1430",
        "用消费品的索取权理解资产",
        "Understand assets as claims on consumption goods",
        "Lucas用一个交换经济讨论资产价格：资产提供未来产出的所有权，而消费者选择何时消费、持有什么份额。这个设定把价格与真实资源联系起来，不先假设一条股票价格路径，再把消费者行为作为事后的补充解释。",
        "Assets are ownership claims on future output in an exchange economy. Consumers choose consumption and holdings. The setup links prices to real resources rather than assuming a stock-price path first and adding consumer behavior afterward."
      ],
      [
        "p. 1430",
        "产出过程是外生给定的",
        "Output is specified outside the pricing problem",
        "模型的消费品不能储存，产出按给定的随机过程变化。这里没有企业根据融资成本扩张生产的完整决策。因此，研究的是既定资源流如何被定价，不能直接用来回答新增投资、技术变化或公司发行股票的全部问题。",
        "The consumption good cannot be stored, and output follows a specified stochastic process. Firms do not solve a full investment problem here. The model prices given resource flows; it does not settle questions about investment, technology or issuance."
      ],
      [
        "p. 1430",
        "分红与交易的先后影响价格含义",
        "Dividend timing changes what a price means",
        "当期产出先分配给原有持有人，随后交易的份额对应未来所有权。由此得到的价格是与这一时间顺序一致的价格。阅读收益公式时，必须确认分红是否已经支付；把含息与除息价格混用，会改变所计算的资产收益。",
        "Current output goes to existing owners before shares are traded. Prices must be interpreted using that sequence. A return calculation needs to know whether the dividend has already been paid; mixing cum-dividend and ex-dividend prices changes the object measured."
      ],
      [
        "p. 1431",
        "理性预期是一致性条件",
        "Rational expectations impose consistency",
        "消费者根据预期价格作决定，所有人的决定又通过市场出清形成价格。论文要求这两种价格描述相互一致。这个条件并不等于解释投资者如何学习，也不能被简单翻译成每个人都能准确预测下一次实现的价格。",
        "Consumers choose using expected price behavior, while market clearing generates prices from those choices. Rational expectations require consistency between the two descriptions. They neither explain learning nor imply accurate prediction of each realized future price."
      ],
      [
        "pp. 1430–1432",
        "没有交易量仍可能有资产价格",
        "Prices can exist without equilibrium trade",
        "同质消费者在均衡中持有既定份额，并消费全部当期产出，因此不需要持续交换资产。价格仍然有意义，因为它支持每个人不愿偏离的选择。这个模型适合讨论定价一致性，却不能据此解释真实市场频繁交易的原因。",
        "Identical consumers hold the equilibrium shares and consume current output, so continuing asset exchange is unnecessary. Prices still support choices that nobody wishes to change. This is useful for pricing consistency but not an explanation of active real-world trading."
      ],
      [
        "p. 1432 · definition",
        "最优选择与市场出清缺一不可",
        "Optimal choice and market clearing are both required",
        "均衡定义同时要求给定价格下的消费与持仓最优，以及这些选择与资源和份额供给相容。只解消费者问题还没有完成整个定价问题，反过来仅找到供需相等的价格，也不能省略偏好与预算约束带来的行为条件。",
        "Equilibrium requires optimal consumption and holdings at given prices, plus compatibility with resource and share supply. Solving the consumer problem alone is incomplete; a market-clearing price also needs behavior consistent with preferences and budget constraints."
      ]
    ]
  ],
  [
    "By Force of Habit: A Consumption-Based Explanation of Aggregate Stock Market Behavior",
    "https://www.bauer.uh.edu/rsusmel/phd/campbell-cochrane_1999JPE.pdf",
    [
      "1999年期刊版",
      "1999 journal article"
    ],
    "Printed pp. 205–207 and 209–210 inspected for external habit, surplus consumption, local curvature and consumption dynamics. Simulations and later empirical fit not independently reproduced.",
    [
      "习惯水平是模型状态，不是直接可见的账户变量。参数校准和模拟匹配不等于已经识别现实中的风险厌恶，也不构成市场预测。",
      "Habit is a model state, not an observed account variable. Calibration and simulated fit do not identify actual risk aversion or provide a market forecast."
    ],
    [
      [
        "pp. 205–207",
        "相同消费增长可以伴随不同风险感受",
        "Similar consumption growth can accompany different risk sensitivity",
        "文章让风险态度取决于消费相对于习惯水平的距离。即使当期消费增长相似，一个接近习惯下限的经济与一个余量充足的经济，面对风险时也可能不同。这样，平稳的消费增长不必对应固定不变的资产风险补偿。",
        "Risk sensitivity depends on consumption relative to habit. Similar current growth can occur with little or substantial consumption surplus. Smooth consumption growth therefore need not imply a constant compensation for bearing asset risk."
      ],
      [
        "p. 209",
        "核心状态是剩余消费比例",
        "The central state is the surplus consumption ratio",
        "剩余消费比例是消费减去习惯后，占消费本身的比重。它不是消费增长率，也不是储蓄率。当消费接近习惯时，这个比例下降；理解状态变化，应先固定分子和分母的含义，避免把几个名字相近的宏观指标混在一起。",
        "Surplus consumption is consumption minus habit, divided by consumption. It is neither consumption growth nor a saving rate. The ratio falls as consumption approaches habit; its numerator and denominator must remain distinct from similarly named macroeconomic measures."
      ],
      [
        "p. 209",
        "局部风险曲率会随状态变化",
        "Local curvature varies with the state",
        "文中的局部效用曲率等于参数γ除以剩余消费比例，而不是固定等于γ。剩余比例越低，同样消费冲击的效用影响越强。因此，看到一个偏好参数的数值，不能脱离状态变量就直接解释为任何时点相同的风险厌恶。",
        "Local utility curvature is gamma divided by the surplus ratio, not gamma alone. Lower surplus makes consumption shocks more consequential for utility. A preference parameter cannot be interpreted as the same effective risk sensitivity in every state."
      ],
      [
        "p. 209",
        "外部习惯不是个人消费的简单惯性",
        "External habit differs from individual consumption inertia",
        "主要设定让习惯取决于全社会消费的历史，而非单个投资者自己的消费路径。个体在决策时面对这一外部参照。把它改成个人习惯，会改变边际消费对未来效用的影响，不能只替换数据列而保留全部推导不变。",
        "The main specification ties habit to aggregate consumption history, not an individual's own past consumption. Individuals take that external reference as given. Replacing it with personal habit changes marginal incentives, rather than merely replacing a data column."
      ],
      [
        "pp. 209–210",
        "慢变化来自习惯机制而非收益外推",
        "Persistence comes from habit dynamics",
        "剩余消费状态具有持续性，且对消费冲击的反应随状态变化。论文同时把消费增长设为独立同分布的对数正态过程。由此产生的持续风险态度，不是把近期股票涨跌直接延长到未来，而是通过消费与习惯的关系形成。",
        "The surplus state is persistent and responds nonlinearly to consumption shocks, even though consumption growth is specified as independently lognormal. Persistent risk sensitivity arises through habit, not by extrapolating recent stock returns."
      ],
      [
        "pp. 205–207, 210",
        "校准解释与经验验证要分开",
        "Separate calibration from empirical validation",
        "作者通过特定偏好和状态过程解释若干市场现象，其中函数选择承担重要作用。模型能够生成相似统计特征，是解释的一步，但并不单独证明习惯机制是唯一原因。与其他消费定价模型比较时，应同时检查假设与可区分的预测。",
        "Chosen preferences and state dynamics generate market-like features. Matching those features is one explanatory step, not proof that habit is the unique cause. Comparisons with other consumption models should examine assumptions and predictions that distinguish their mechanisms."
      ]
    ]
  ],
  [
    "Risks for the Long Run: A Potential Resolution of Asset Pricing Puzzles",
    "https://msuweb.montclair.edu/~lebelp/BansalRisksForTheLongRunJF200408.pdf",
    [
      "2004年期刊版",
      "2004 journal article"
    ],
    "Printed pp. 1481–1485 inspected for persistent growth news, recursive preferences, distinct consumption/dividend claims and Case I dynamics. Full uncertainty-case derivation and calibration not reproduced.",
    [
      "长期增长状态与消费索取权收益并非直接可见。模型对持续性和偏好的设定很重要；短样本中的拟合不能替代对机制的独立识别。",
      "Long-run growth states and consumption-claim returns are not directly observable. Persistence and preference assumptions matter; short-sample fit does not independently identify the mechanism."
    ],
    [
      [
        "pp. 1481–1483",
        "微小但持续的增长变化可能很重要",
        "Small persistent growth changes can matter",
        "Bansal与Yaron关注消费增长中很小、却持续存在的预期成分。一次短暂变化与一个延续很久的预期修正，对未来消费总路径的含义不同。长期风险的重点是冲击的持续性，不是简单把日收益换成更长时间的收益。",
        "The model emphasizes a small persistent component in expected consumption growth. A temporary change and a lasting revision imply different future consumption paths. Long-run risk concerns persistence, not simply measuring returns over a longer interval."
      ],
      [
        "pp. 1481–1484",
        "风险厌恶与跨期替代分开表达",
        "Separate risk aversion from intertemporal substitution",
        "递归偏好允许分别表达对不确定性的厌恶，以及在不同时点之间调整消费的意愿。两者并不总由同一个参数锁定。解释价格如何响应增长消息时，需要同时理解这两个维度，而不能只用风险厌恶高低概括全部结果。",
        "Recursive preferences separate aversion to uncertainty from willingness to shift consumption across time. The two need not be tied to one parameter. Price responses to growth news depend on both dimensions, not on risk aversion alone."
      ],
      [
        "p. 1484",
        "消费索取权不等于股票市场",
        "A consumption claim is not the equity market",
        "模型区分支付全部消费流的理论资产，与支付股息的股票市场资产。劳动收入等资源使两者不能直接等同。用观察到的股票指数替代消费索取权收益，会改变定价关系中的对象，需要额外论证而非仅做名称替换。",
        "A theoretical claim to aggregate consumption differs from an equity claim to dividends. Resources such as labor income prevent automatic equivalence. Substituting an observed stock index for consumption-claim returns changes the pricing object and requires justification."
      ],
      [
        "p. 1485 · equation (4)",
        "消费与股息共享状态但不共享全部冲击",
        "Consumption and dividends share a state, not every shock",
        "预期增长状态同时进入消费和股息过程，但两者可以有不同的敏感度与额外冲击。股息更剧烈的波动不意味着消费也同幅变化。比较数据时，应分别保留消费、股息及状态成分，而非用一条序列代表全部现金流风险。",
        "Expected growth enters both consumption and dividend processes, with different sensitivities and additional shocks. More volatile dividends do not imply equally volatile consumption. The separate series and shared state must remain distinct in empirical interpretation."
      ],
      [
        "pp. 1482–1483",
        "不确定性变化是另一种风险",
        "Changing uncertainty is a separate risk",
        "文章还讨论经济不确定性随时间变化，与预期增长高低是两个不同维度。对未来均值的修正和对未来波动的修正，都可能影响价格。仅观察当期增长率，不能直接判断市场正在给哪一类长期消息重新定价。",
        "Time-varying uncertainty is distinct from the level of expected growth. Revisions to future means and future variability can both affect prices. Current growth alone does not reveal which kind of long-run news the market is repricing."
      ],
      [
        "pp. 1483–1485",
        "持续状态很难从短样本中辨认",
        "Persistent states are difficult to identify in short samples",
        "原文指出，小而持续的增长成分可能难以与简单过程区分。模型使用校准和近似解展示机制，但隐含状态并非已经被准确观测。阅读时应将可生成的经济故事、参数选择和数据能否区分竞争解释这三件事分别评价。",
        "A small persistent growth component can be hard to distinguish from simpler dynamics. Calibration and approximate solutions illustrate a mechanism without making its latent state directly observed. Economic plausibility, parameter choice and empirical discrimination are separate judgments."
      ]
    ]
  ],
  [
    "Value and Momentum Everywhere",
    "https://w4.stern.nyu.edu/facdir/lpederse/papers/ValMomEverywhere.pdf",
    [
      "2013年期刊版",
      "2013 journal article"
    ],
    "Printed pp. 932–937 inspected for cross-sectional versus time-series momentum, liquid sample selection, return units and asset-specific value measures. Performance and implementation sections not replicated.",
    [
      "不同资产的价值代理并不相同，历史共同变化也不是未来收益承诺。样本选择、可交易工具、融资和成本仍需各自处理。",
      "Value proxies differ across assets, and historical comovement is not a return promise. Sample selection, instruments, financing and costs remain separate issues."
    ],
    [
      [
        "p. 932",
        "跨资产比较的是相对排名",
        "Cross-asset comparison uses relative rankings",
        "这里的动量是在同类资产之间比较过去表现，不是判断每个资产相对自身历史是否上涨。两种方法即使使用相似收益窗口，也会得到不同对象。理解跨市场一致性之前，应先固定比较组和排名基准，避免与时间序列动量混读。",
        "Momentum here ranks past performance relative to peers, rather than asking whether each asset rose against its own history. Similar return windows can therefore define different objects. Cross-market comparisons require a fixed peer group and ranking benchmark."
      ],
      [
        "pp. 933–934",
        "流动性筛选改变样本含义",
        "Liquidity selection changes the sample",
        "股票样本集中于较大、较流动的公司，并非每个市场所有上市证券。这个选择帮助讨论可交易性，却也限制了结论覆盖范围。将样本规律推广到小盘或低流动性证券时，需要新的证据，不能仅因它们同属股票就直接套用。",
        "The equity universe emphasizes larger, liquid firms rather than every listed security. This supports an implementability discussion but limits coverage. Extending its patterns to small or illiquid stocks requires evidence beyond their sharing the equity label."
      ],
      [
        "pp. 935–936",
        "先统一收益的经济单位",
        "Reconcile the economic units of returns",
        "期货收益不包含抵押资金的收益，货币收益则包含相应利差因素。直接把价格涨跌与这些收益混合，可能制造虚假的跨资产差异。比较之前，应识别合约、计价货币和现金收益口径，而不只让每条序列拥有相同日期。",
        "Futures returns exclude collateral income, while currency returns incorporate interest differentials. Mixing these with simple price changes can create artificial cross-asset differences. Contract, currency and cash-income conventions matter beyond matching dates."
      ],
      [
        "p. 936",
        "账面价值需要信息时点",
        "Book value needs an availability convention",
        "股票价值指标使用账面权益与市值的比率，并将账面值滞后六个月以处理当时可得性。滞后规则与财务报告真实公开日期不是完全相同的事实。若改用不同市场数据，应重新检查披露时点，而不能用今日修订值回看过去。",
        "The equity measure divides book equity by market equity, lagging book values six months for availability. A lag convention is not identical to an observed filing date. Other datasets require their own disclosure-time checks and protection against revised-history leakage."
      ],
      [
        "pp. 936–937",
        "统一名称不代表统一价值定义",
        "A common label does not mean one value definition",
        "股票有账面价值，但货币、商品和债券不能照搬这一分子。作者使用长期价格、购买力或收益率变化等代理构造可比较问题。它们有共同研究动机，却不是会计意义相同的估值倍数，解释时必须保留每类资产的具体定义。",
        "Stocks have book equity, whereas currencies, commodities and bonds require other proxies involving long-horizon prices, purchasing power or yields. These measures share a research motivation but are not identical accounting valuation ratios."
      ],
      [
        "pp. 932, 936–937",
        "共同变化不等于唯一共同原因",
        "Comovement does not identify a unique common cause",
        "研究同时观察价值与动量，有助于追问它们在不同资产上的共同变化。负相关或类似溢价可以约束解释，却不能单独证明某一种流动性或行为机制。还需区分原始指标、组合构造和风险解释，不能由相关性直接推出因果结论。",
        "Studying value and momentum together reveals cross-asset comovement that can discipline explanations. Negative correlation or similar premia does not uniquely establish a liquidity or behavioral cause. Measures, portfolio construction and risk interpretation remain distinct."
      ]
    ]
  ],
  [
    "Betting Against Beta",
    "https://w4.stern.nyu.edu/facdir/lpederse/papers/BettingAgainstBeta.pdf",
    [
      "2013年5月10日工作稿",
      "May 10, 2013 draft"
    ],
    "Author-hosted draft pp. 3–5 inspected for beta scaling, funding constraints, contemporaneous versus expected returns and the explicit lagged-TED inconsistency. Estimation and trading results not reproduced.",
    [
      "导读依据2013年工作稿。贝塔中性不等于没有风险，历史组合还涉及杠杆、卖空与融资条件，不能作为可直接执行的收益承诺。",
      "This guide uses the 2013 draft. Beta neutrality is not risklessness; historical portfolios involve leverage, short selling and funding conditions, not an executable return promise."
    ],
    [
      [
        "p. 3",
        "融资约束可以改变风险需求",
        "Funding constraints can change demand for risk",
        "当部分投资者不能方便地加杠杆时，高贝塔资产可能提供他们所寻求的市场暴露。模型由此讨论证券市场线为何可能更平坦。这里的解释涉及投资者约束的差异，不是说承担更多风险在任何市场都必然得到更少收益。",
        "Investors unable to lever easily may seek market exposure through high-beta assets. The model links heterogeneous funding constraints to a flatter security market line. It does not claim that greater risk always earns less in every market."
      ],
      [
        "p. 3",
        "贝塔配平与资金配平不同",
        "Beta balance differs from cash balance",
        "工作稿将低贝塔与高贝塔两侧缩放到可比较的市场暴露，再用现金头寸处理净资金。两侧金额因此不必相等。只观察买卖金额相抵，无法判断贝塔是否中性；反过来贝塔相抵，也不能说明没有资金或融资需求。",
        "The draft scales low- and high-beta sides to comparable market exposure, using cash positions to balance financing. Dollar amounts need not match. Cash neutrality does not establish beta neutrality, and beta neutrality does not remove funding needs."
      ],
      [
        "p. 3",
        "市场暴露为零仍会受融资冲击",
        "Zero market exposure can still face funding shocks",
        "模型中的融资条件收紧会迫使受约束参与者去杠杆，影响相关资产价格。组合即便按估计贝塔配平，也可能在这种状态下损失。贝塔只描述某种共同收益暴露，不能覆盖融资流动性、估计偏差或所有尾部情景。",
        "Tighter funding can force deleveraging and move asset prices. A beta-balanced portfolio may lose in that state. Beta describes one shared return exposure; it does not encompass funding liquidity, estimation uncertainty or every tail scenario."
      ],
      [
        "pp. 3–4",
        "当期损失与未来补偿可以方向相反",
        "Current losses and future compensation can differ",
        "资产价格下跌可能同时提高未来所要求的收益，因此当期实现收益与下一期预期补偿不能混为一谈。工作稿把融资收紧时的价格影响与约束下的未来收益联系起来，阅读经验结果时也必须保留这个时间顺序。",
        "A price decline can raise subsequently required returns, so realized losses and future expected compensation are different objects. The draft connects funding shocks to both. Empirical interpretation must preserve the timing instead of combining them into one effect."
      ],
      [
        "p. 5",
        "代理变量并未完全吻合理论",
        "The empirical proxy does not fully match the theory",
        "作者明确指出，滞后的TED利差结果若解释为约束紧度，会与模型预测不一致，并将另一种解释标为推测。这个细节很重要：支持部分预测不等于所有证据一致，也不能把一个融资代理当成理论状态的直接观测。",
        "The authors explicitly report that lagged TED-spread evidence conflicts with the model if interpreted as constraint tightness, and label an alternative explanation speculative. Partial support is not uniform confirmation, and a funding proxy is not the theoretical state itself."
      ],
      [
        "pp. 4–5",
        "跨资产证据仍需保留工具差异",
        "Cross-asset evidence retains instrument differences",
        "股票、国债和信用债中的低贝塔暴露由不同工具与期限形成，所需杠杆也可能差别很大。共同研究框架不消除这些差异。比较结果时，应区分单位风险补偿、资产原始收益与实际融资可行性，而不是只比较历史比率。",
        "Low-beta exposure is constructed differently in equities, Treasuries and credit, potentially requiring very different leverage. A shared framework does not remove instrument differences. Compensation per risk unit, raw returns and financing feasibility require separate comparison."
      ]
    ]
  ],
  [
    "Risk, Return, and Equilibrium: Empirical Tests",
    "https://people.hec.edu/rosu/wp-content/uploads/sites/43/2023/09/Fama-MacBeth-Risk-return-and-equilibrium-Empirical-tests-1973.pdf",
    [
      "1973年期刊版",
      "1973 journal article"
    ],
    "Printed pp. 607–609 and 613–616 inspected for testable restrictions, estimated betas, formation/estimation windows and monthly cross-sectional regressions. Full result tables not reviewed.",
    [
      "两步回归不能自动消除测量误差或证明市场有效。本文的历史NYSE样本、市场代理和模型假设，共同限定了检验对象。",
      "Two-pass regressions do not automatically eliminate measurement error or establish efficiency. The historical NYSE sample, market proxy and model assumptions jointly define the test."
    ],
    [
      [
        "pp. 607–609",
        "风险是对组合的贡献",
        "Risk concerns contribution to a portfolio",
        "论文从组合选择出发理解个股风险，而非仅用个股自身波动。一个证券如何与持有组合共同变化，决定它对组合风险的贡献。因此，高个股波动与高市场贝塔不是同一概念，经验检验必须对应理论中真正使用的风险定义。",
        "Risk is an asset's contribution to portfolio dispersion, not merely its standalone volatility. Comovement with the held portfolio matters. High individual volatility and high market beta are different concepts, and tests must match the theoretical risk definition."
      ],
      [
        "p. 613",
        "把多个定价命题分别检验",
        "Test distinct pricing restrictions separately",
        "作者区分风险收益关系的线性、非贝塔风险是否另有补偿，以及平均风险补偿是否为正等命题。某个截距限制失败，不必等于所有组合理论都失败。分开这些命题，有助于避免把一个统计结果解释成对整个模型体系的总判决。",
        "The paper separates linearity, compensation for non-beta risk and a positive average risk premium. Rejection of one intercept restriction need not reject every portfolio implication. Distinct hypotheses prevent a single statistic becoming a verdict on an entire framework."
      ],
      [
        "p. 614",
        "贝塔是估计量，不是已知常数",
        "Beta is estimated rather than known",
        "理论关系使用真实风险暴露，但研究只能从历史收益估计贝塔，因此解释变量本身带有误差。增加观测或形成组合可以帮助处理部分噪声，却不意味着问题自动消失。市场指数也只是代理，不是理论市场组合的完美直接观测。",
        "Theory uses true exposure, but empirical beta is estimated from historical returns. The regressor therefore contains error. More observations or portfolios can address some noise without eliminating the problem; the observed index is also only a market proxy."
      ],
      [
        "p. 615",
        "排序期与重新估计期分开",
        "Separate sorting from re-estimation",
        "按估计贝塔排序会把正向误差集中到高组、负向误差集中到低组。作者用一个时期形成组合，再用后续资料重新估计风险，减少这种选择造成的回归现象。若用同一窗口同时排序和验证，就改变了这项设计的含义。",
        "Sorting estimated betas groups positive errors at the top and negative errors at the bottom. The paper forms portfolios in one period and re-estimates risk using later data to mitigate that selection. Reusing one window for both changes the design."
      ],
      [
        "p. 616 · equation (10)",
        "每个月得到一次横截面比较",
        "Each month supplies a cross-sectional comparison",
        "研究逐月将组合收益与事前估计的风险变量联系，得到一系列月度回归系数，再将这些系数用于检验。它不是把所有公司月份简单堆叠成一次回归。横截面的风险差异与时间上的系数变化，在这种方法中承担不同角色。",
        "Monthly portfolio returns are related to previously estimated risk variables, yielding a time series of coefficients for testing. This is not a single regression pooling all firm-months. Cross-sectional risk differences and coefficient variation over time play different roles."
      ],
      [
        "pp. 614–616",
        "历史样本和数据处理属于检验合同",
        "Sample and return conventions belong to the test",
        "原研究使用历史NYSE普通股月度收益，包含分红与资本变动调整，并采用特定市场代理。换成另一市场、价格收益或不同组合权重，就是新的经验设计。保留方法名称并不能保证新结果与原文检验的对象完全相同。",
        "The study uses historical NYSE monthly common-stock returns with dividends and capital adjustments, plus a particular market proxy. Another market, price-only returns or different weights define a new empirical design even if the method keeps the same name."
      ]
    ]
  ],
  [
    "Differences of Opinion, Short-Sales Constraints, and Market Crashes",
    "https://www.columbia.edu/~hh2679/hong-stein-rfs.pdf",
    [
      "2003年期刊版",
      "2003 journal article"
    ],
    "Printed pp. 488–490 inspected for heterogeneous signals, constrained pessimists, endogenous revelation, asymmetry and contagion. Theoretical motivation only; later formal results not independently verified.",
    [
      "这是观点分歧与卖空约束的机制模型，不是崩盘预警器。高成交量、价格下跌或没有显眼新闻，都不能单独证明该机制已经发生。",
      "This is a mechanism model, not a crash-warning system. High volume, falling prices or absent headlines do not individually establish that its mechanism is operating."
    ],
    [
      [
        "p. 489",
        "观点分歧来自不同信息权重",
        "Disagreement comes from different information weights",
        "模型中的两位投资者各自重视自己的信号，即使另一方的信息有所显露，也不完全采纳。价格差异由这种观点分歧产生，而不是单纯假设所有人都犯同一种错误。理性套利者又是另一类参与者，不能把三者合并为一个代表投资者。",
        "Two investors emphasize their own signals rather than fully accepting the other's information. Disagreement is distinct from everyone sharing one mistake. Rational arbitrageurs form another participant class, so the roles cannot be collapsed into a representative investor."
      ],
      [
        "p. 489",
        "不交易可能隐藏悲观信息",
        "Not trading can conceal pessimistic information",
        "面对卖空限制，悲观者可能只选择不买，而无法用负头寸充分表达观点。观察者知道他不够乐观，却未必知道究竟悲观到什么程度。因此，没有成交并不等于没有信息，约束会影响信息进入价格的方式和速度。",
        "A constrained pessimist may simply abstain instead of expressing a negative position. Others infer limited optimism but not the exact severity of the signal. No trade does not mean no information; constraints affect how information reaches prices."
      ],
      [
        "p. 489",
        "下跌会揭示是否有人愿意接手",
        "A decline reveals whether others will buy",
        "当原先乐观者变得悲观并退出时，市场会观察另一方是否在更低价格买入。如果价格已跌很多仍无人接手，先前隐藏的信息可能比预想更差。这个额外推断使交易过程本身带来消息，而不只机械反映刚发布的一条新闻。",
        "As the former optimist withdraws, others observe whether another investor buys at lower prices. Failure to provide support can reveal worse previously hidden information. Trading itself produces an inference beyond the newly arriving external signal."
      ],
      [
        "p. 490",
        "坏消息可能释放更多旧信息",
        "Bad news can release additional old information",
        "上涨时，新的乐观信息可以进入价格，而悲观者的旧信号继续隐藏；下跌时，两类信息可能一起显露。这种不对称是模型解释大幅下跌的重要环节。它不是对每次市场下跌的事实认定，也不等于任何坏消息都会造成崩盘。",
        "Positive news can enter prices while pessimistic old information remains hidden; negative news may reveal both. That asymmetry is central to the mechanism. It does not identify every observed selloff or imply that all bad news causes a crash."
      ],
      [
        "p. 490",
        "信息关联可以形成跨股票传递",
        "Related information can transmit across stocks",
        "多股票扩展中，一只股票的交易可能揭示也与另一只股票有关的信息，因此后者即使没有自己的当期新闻也会变化。这个传递渠道与简单同时收到公共新闻不同，但要在数据中辨认，仍需要明确股票之间的信息联系。",
        "Trading one stock can reveal information relevant to another, moving the latter without stock-specific contemporaneous news. This differs from both receiving the same public announcement. Empirical identification still requires a specified information connection."
      ],
      [
        "pp. 488, 490",
        "偏度证据不是逐次事件预测",
        "Skewness evidence is not event-by-event prediction",
        "文章讨论收益分布的不对称及其条件变化，同时承认个股与市场整体的偏度并不总一致。分布层面的规律不提供下一次大跌的时间。阅读成交量与负偏度关系时，应保留样本层级和条件，不能把统计关联转换成确定预警。",
        "The article discusses distributional asymmetry while acknowledging differences between individual stocks and the aggregate market. A distributional pattern does not time the next crash. Volume–skewness associations retain sample and conditioning limits rather than yielding certain warnings."
      ]
    ]
  ],
  [
    "Speculative Trading and Stock Prices: Evidence from Chinese A-B Share Premia",
    "https://www.nber.org/system/files/working_papers/w11362/w11362.pdf",
    [
      "2005年NBER工作稿",
      "2005 NBER working paper"
    ],
    "Printed pp. 1–3 inspected for resale-option motivation, historical A/B segmentation, matched rights and turnover/liquidity controls. Later regressions and institutional changes not reproduced.",
    [
      "论文描述1990年代至2000年前后的历史制度，不是当前交易规则。相同股东权利不等于可自由转换或无成本套利，换手率也不直接观测投机动机。",
      "The institutional setting is historical, not a statement of current rules. Equal shareholder rights do not establish convertibility or costless arbitrage, and turnover does not directly observe motives."
    ],
    [
      [
        "p. 1",
        "价格可能包含转售机会的价值",
        "Prices may include the value of resale opportunities",
        "文章从分歧与卖空限制出发，讨论持有人未来向更乐观买家转售的机会。这个机会可能影响今天愿意支付的价格。它与仅按预期现金流折现的讨论不同，但仍是一种需要数据检验的解释，不是看到高价格就能确认存在泡沫。",
        "Under disagreement and short-sale constraints, an owner may value the chance to resell to a more optimistic buyer. This differs from cash-flow valuation alone. It remains an empirical explanation to test, not a diagnosis established by a high price."
      ],
      [
        "p. 2",
        "同一公司两类股份帮助控制基本面",
        "Two share classes help hold fundamentals comparable",
        "A股与B股的相同现金流和投票权，为比较价格提供一个较清晰的公司内参照。这样能减少跨公司基本面差异，但并不消除投资者资格、货币、流动性与风险溢价等因素。配对结构改善比较，不等于形成完全相同的可交易证券。",
        "Equal payoff and voting rights provide a within-firm comparison that reduces fundamental differences. Investor eligibility, currencies, liquidity and risk premia can still matter. Matching share classes improves comparison without making them identical tradable instruments."
      ],
      [
        "p. 2",
        "投资者分割必须放回历史时期",
        "Investor segmentation belongs to its historical period",
        "工作稿讨论的主要时期，两类股票面对不同投资者群体，卖空和发行也受到当时制度限制。正是这些条件让比较具有研究意义。将结论延伸到后来制度或其他市场前，应重新核对约束，而不能把历史描述当作今天的规则。",
        "The main historical period separates investor access across classes and constrains short selling and issuance. Those conditions give the comparison its meaning. Applying it to later regimes or other markets requires checking constraints anew."
      ],
      [
        "pp. 2–3",
        "换手率是行为结果，不是动机标签",
        "Turnover is an outcome, not a motive label",
        "作者研究A股换手率与A、B股价差的关系，用来评价投机转售解释。成交也可能来自流动性需求或其他原因，所以不能给每笔高频交易贴上投机标签。指标与机制之间，需要通过竞争解释和控制变量建立更具体的联系。",
        "The turnover–premium relation is used to assess a resale explanation. Trading can also reflect liquidity needs and other motives. High activity cannot label each trade speculative; mechanism interpretation requires comparison with competing explanations."
      ],
      [
        "p. 3",
        "流动性控制不等于全部混杂消失",
        "Liquidity controls do not remove every confounder",
        "研究使用无价格变化天数、流通规模和其他风险控制，检查价格溢价与换手关系是否仍在。不同控制变量回应不同疑问，并不能证明所有遗漏因素都已排除。固定效应也只是处理特定共同或稳定差异，不会自动建立因果识别。",
        "No-price-change days, float and risk controls probe alternative explanations. Different controls address different concerns without excluding every omitted factor. Fixed effects handle specified common or stable differences; they do not automatically establish causality."
      ],
      [
        "pp. 1–3",
        "价差不是随时可兑现的套利收益",
        "A premium is not an immediately realizable arbitrage profit",
        "两类股份价格不同可以帮助研究定价机制，但能否借券、转换、跨市场转移资金以及承担何种风险，是另一组问题。只把较贵的一侧与较便宜的一侧相减，并不能得到实际可锁定的利润；论文的比较对象不应被误读为交易指令。",
        "A share-class premium informs pricing research, while borrowing, conversion, capital movement and risk determine feasibility. Subtracting the cheaper price from the dearer one does not produce a lockable profit. The comparison is not a trading instruction."
      ]
    ]
  ]
].map(guide));
