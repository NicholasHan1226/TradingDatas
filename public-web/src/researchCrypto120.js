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

export const researchCrypto120 = Object.fromEntries([
  [
    "Common Risk Factors in Cryptocurrency",
    "https://www.nber.org/system/files/working_papers/w25882/w25882.pdf",
    [
      "2019年5月NBER工作稿",
      "May 2019 NBER draft"
    ],
    "NBER w25882 cover, abstract and printed pp. 1–2 inspected for 2014–2018 sample selection, weekly sorts, market/size/momentum factors and the scope of tested characteristics. No claim extends beyond the abstract and inspected pages; later regression tables not independently reproduced.",
    [
      "导读依据2019年工作稿，不以2022年期刊版的结果替换。历史样本中的因子解释力不证明当前风险补偿、可交易收益或跨交易所执行可行性。",
      "This guide uses the 2019 draft, without substituting results from the 2022 journal version. Historical factor fit establishes neither current compensation nor attainable cross-venue returns."
    ],
    [
      [
        "pp. 1–2",
        "研究的是币种之间的收益差异",
        "Explaining differences across coins",
        "这篇研究关注不同加密资产为何表现不同，而不只是比特币涨跌与宏观变量的关系。横截面比较需要在同一观察时点定义可选资产集合。单独一条币价序列即使很长，也不能替代多资产样本中的共同波动与特征差异。",
        "The question concerns differences across cryptocurrencies, not just Bitcoin's time-series relation to macro variables. Cross-sectional analysis requires a contemporaneous investment universe; a long series for one coin cannot substitute for multiple assets and their characteristics."
      ],
      [
        "p. 1",
        "样本集合随时间改变",
        "The universe changes over time",
        "工作稿使用2014至2018年的历史数据，并设定市值门槛，样本中的币种数量随市场发展明显增加。因此，研究对象不是从今天仍然存在的币种倒推出来的固定清单。市值筛选、进入时间与退出记录都会影响如何理解结果。",
        "The draft studies 2014–2018 with a market-capitalization threshold and an expanding set of coins. This is not a fixed list reconstructed from today's survivors. Entry, exit and capitalization filters matter when interpreting its historical evidence."
      ],
      [
        "pp. 1–2",
        "同名特征不等于同一种经济含义",
        "Similar labels need not imply similar economics",
        "作者选择可以从价格和市场活动构造的特征，并与股票研究中的指标联系起来。规模、成交量和动量可以寻找对应物，公司账面权益却不能直接移植到代币。使用股票文献的名称，不会自动赋予加密资产相同的现金流或所有权基础。",
        "The selected characteristics can be constructed from prices and market activity. Size, volume and momentum have market-based counterparts, whereas corporate book equity does not transfer directly to tokens. Shared terminology does not establish common cash-flow or ownership foundations."
      ],
      [
        "p. 2",
        "先排序，再观察下一期",
        "Sort first, observe the following period",
        "工作稿按特征形成分组，再观察下一周收益。这里最重要的是信息先后顺序：用于分组的市值和价格信息必须属于形成时点，而不是结果期结束后回填的值。周度排序的证据也不能直接解释为日内交易信号。",
        "The draft forms characteristic-sorted groups and examines returns over the following week. Inputs must be available at formation, not revised using end-of-outcome information. Evidence from weekly sorts also does not directly establish an intraday trading signal."
      ],
      [
        "pp. 1–2",
        "三个因子是一种解释框架",
        "Three factors form an explanatory framework",
        "市场、规模和动量构成工作稿提出的简洁因子框架，用来解释所检验组合之间的收益差异。因子可以共同变动，其统计解释力与“找到了三种独立经济风险”不是同一回事。对照股票因子模型时，应把可观测组合与经济机制分开。",
        "Market, size and momentum provide a parsimonious framework for the tested portfolios. Factors may covary. Statistical explanatory power is different from identifying three independent economic risks; observable factor portfolios and their proposed mechanisms remain distinct."
      ],
      [
        "pp. 1–2",
        "解释历史组合，不等于可直接投资",
        "Explaining portfolios is not an implementation result",
        "研究将大量候选特征放在同一框架中比较，价值在于梳理哪些差异可以被共同因子吸收。实际使用还需要额外核对交易费用、流动性、币种消失和数据修订。论文中的历史组合不是平台已提供或已经验证的投资产品。",
        "Comparing characteristics within one framework shows which differences can be absorbed by common factors. Costs, liquidity, disappearing coins and revisions require separate implementation evidence. Historical research portfolios are not validated investment products supplied by this platform."
      ]
    ]
  ],
  [
    "The Economics of Cryptocurrencies—Bitcoin and Beyond",
    "https://www.bankofcanada.ca/wp-content/uploads/2019/09/swp2019-40.pdf",
    [
      "2019年9月加拿大央行工作稿",
      "September 2019 Bank of Canada paper"
    ],
    "Bank of Canada Staff Working Paper 2019-40 cover and printed pp. 1–3 inspected for monetary-exchange model, double-spending incentives, confirmation delay, mining finance and calibration boundaries. No current network parameters inferred.",
    [
      "采用2019年加拿大央行版本，保留书目中较早的工作稿身份。模型假设和历史校准不能代表当前网络安全、能源消耗或任何资产的合理价格。",
      "The 2019 Bank of Canada version is used while the earlier bibliographic identity is retained. Model assumptions and historical calibration do not establish current network security, energy use or fair asset values."
    ],
    [
      [
        "pp. 1–2",
        "先把加密货币看作支付工具",
        "Start with a payment instrument",
        "作者把加密货币放入货币交换模型，研究没有可信中介时怎样支持交易。核心问题是支付能否成立，以及维持支付所消耗的资源，而不是预测代币下一期价格。讨论货币价值时，需要同时考虑使用需求与运行机制。",
        "The authors place cryptocurrency inside a monetary-exchange model to study payments without a trusted intermediary. The central questions concern feasible exchange and its resource costs, not a forecast of the next token price. Use demand and operating incentives enter together."
      ],
      [
        "pp. 1–2",
        "双花约束是一条激励条件",
        "Double-spending prevention is an incentive condition",
        "记录写入账本不意味着付款人必然没有动机撤回支付。模型比较诚实交易与双花的收益，让安全支付依赖足够强的激励约束。因此，安全不能只用账本副本数量或某个加密技术名称来替代，必须看参与者付出的成本与可能获得的利益。",
        "A ledger entry does not by itself remove an incentive to reverse payment. The model compares honest exchange with double spending and requires an incentive constraint. Security therefore depends on costs and gains, not merely the number of ledger copies or a cryptographic label."
      ],
      [
        "pp. 2–3",
        "等待确认也属于支付成本",
        "Confirmation delay is part of payment cost",
        "工作稿将挖矿资源与确认等待一起纳入分析。等待会影响交易的便利性，同时可能提高改变支付结果的难度。较大的支付需要怎样的保护，取决于模型中的激励条件；不能把某个固定确认次数当作所有金额和网络都适用的保证。",
        "Mining resources and confirmation delay jointly enter the analysis. Waiting affects convenience while changing the difficulty of reversing a payment. Appropriate protection depends on incentives and payment size; a fixed confirmation count is not a universal guarantee across networks."
      ],
      [
        "pp. 2–3",
        "矿工报酬与货币价值相互关联",
        "Mining compensation and monetary value interact",
        "运行系统需要给矿工提供报酬，但报酬本身依赖货币在交换中的价值。使用需求、安全投入和支付可接受程度因而形成相互依赖，而不是先给出一个不变的价格再单独计算安全。阅读校准时，应保留这种一般均衡关系。",
        "Miners need compensation, whose value depends on the currency's role in exchange. Demand, security expenditure and payment acceptance are interdependent. The calibration is not simply a security calculation at an externally fixed coin price; it reflects a general-equilibrium structure."
      ],
      [
        "pp. 2–3",
        "发行收入与手续费并不等价",
        "Issuance revenue and fees are not equivalent",
        "作者比较发行收入和交易手续费如何支持挖矿，并指出它们在模型中的激励和征收基础不同。这是特定设定下的机制比较，不是手续费没有任何用途的结论。手续费还可能承担防止滥用或表达支付紧急程度等不同功能。",
        "The paper compares issuance revenue with transaction fees as funding mechanisms with different incentive and tax-base properties. This model comparison does not imply that fees have no purpose: deterring spam and expressing payment urgency concern different functions."
      ],
      [
        "pp. 1–3",
        "福利评价不是币价目标",
        "Welfare analysis is not a price target",
        "模型用历史背景下的参数讨论支付效率与资源耗费，结果依赖需求、等待成本和安全条件。福利损失、网络费用与持币收益是不同对象。将这些分析用于理解制度取舍有帮助，但不能把其数值直接当作今天的币价估值或投资建议。",
        "Historical calibration examines payment efficiency and resource use under demand, delay and security assumptions. Welfare, network fees and holding returns are different objects. The analysis informs institutional trade-offs without supplying a current valuation target or investment recommendation."
      ]
    ]
  ],
  [
    "Blockchain Economics",
    "https://www.philadelphiafed.org/-/media/frbp/assets/working-papers/2022/wp22-15.pdf",
    [
      "2022年费城联储工作稿22-15",
      "2022 Philadelphia Fed WP 22-15"
    ],
    "Federal Reserve Bank of Philadelphia May 2022 working-paper cover, January 2022 author title page and printed pp. 1–2 inspected for fault tolerance, resource efficiency, full transferability and framework assumptions. No protocol audit undertaken.",
    [
      "本导读对应2022年工作稿中的理论框架，不是实际链的性能测试。其三难关系不同于常见的安全、去中心化与扩容口号，结论受参与者和转移条件约束。",
      "This concerns the 2022 theoretical framework, not a live-chain benchmark. Its trilemma differs from the familiar security/decentralization/scalability slogan and depends on participant and transfer assumptions."
    ],
    [
      [
        "p. 1",
        "先分清是哪一种三难关系",
        "Identify the particular trilemma",
        "本文讨论容错、资源效率与完全可转移性之间的关系。这里的第三项关注符合条件的转移能否完成，不是常见宣传中的扩容速度。若把三个概念换成另一组流行术语，就会改变论文的命题，而不只是换一种表达。",
        "The trilemma concerns fault tolerance, resource efficiency and full transferability. The third property concerns completing qualifying transfers, not the throughput used in familiar scalability slogans. Replacing these terms with another trio would change the proposition itself."
      ],
      [
        "pp. 1–2",
        "账本需要在参与者故障时继续协调",
        "A ledger must coordinate despite participant faults",
        "支付系统需要让参与者对转移达成一致，但部分参与者可能离线、出错或不能被信任。容错针对的是这种协调条件，不等同于所有恶意行为都已被经济激励消除。阅读时应区分故障模型、信息条件与蓄意偏离的动机。",
        "Participants must agree on transfers even when some are unavailable, faulty or untrustworthy. Tolerance of such faults is not equivalent to eliminating every malicious incentive. The fault model, information assumptions and motives for deliberate deviation remain separate questions."
      ],
      [
        "pp. 1–2",
        "完全可转移性约束支付能否完成",
        "Full transferability concerns feasible completion",
        "框架不仅要求账本不出错，还关心对参与者而言可接受的转移是否能够实现。一个从不处理交易的系统可能避免许多冲突，却显然不能满足支付用途。理解完全可转移性，有助于看清安全、资源使用与交易完成之间为何需要同时比较。",
        "The framework asks whether acceptable transfers can actually be achieved, alongside ledger consistency. A system that processes nothing avoids many conflicts but fails its payment purpose. Full transferability makes completion a separate requirement from safety and resource expenditure."
      ],
      [
        "p. 2",
        "资源效率不是单次手续费高低",
        "Resource efficiency is not a fee quotation",
        "资源效率是理论比较的一项系统属性，不能仅凭用户支付的手续费判断。费用可能在参与者之间转移，而计算、等待或其他真实投入具有不同含义。研究不同共识安排时，应先明确哪些成本属于资源耗费，哪些只是收入分配。",
        "Resource efficiency is a system property rather than a quoted transaction fee. A fee can transfer income between participants, unlike real computation or other resource use. Comparing consensus arrangements requires distinguishing expenditure of resources from their financial allocation."
      ],
      [
        "pp. 1–2",
        "中心化与不同共识机制放在同一框架",
        "Compare organizational forms within one framework",
        "作者用统一经济框架讨论中心化安排以及工作量证明、权益证明等机制，重点是它们怎样取舍目标。一个机制在某项属性上占优，不代表它在所有环境下都更好。比较必须保留可信参与者、故障和转移需求的共同前提。",
        "Centralized arrangements and proof-of-work or proof-of-stake mechanisms are considered within a common framework. An advantage in one property does not establish universal superiority. Comparisons retain assumptions about trusted participants, faults and transfer requirements."
      ],
      [
        "pp. 1–2",
        "理论不可能性不是漏洞认证",
        "An impossibility argument is not a vulnerability certificate",
        "在模型条件下无法同时满足全部属性，是对机制设计约束的判断。它不能替代对真实协议代码、治理权力或网络行为的检查，也不证明某条链一定会在某一天失败。将论文作为概念地图时，应保留理论命题与实证安全审计的距离。",
        "A constraint on jointly satisfying properties under model assumptions is a mechanism-design result. It does not replace inspection of protocol code, governance powers or network behavior, nor predict a specific failure date. Theoretical limits and empirical security audits provide different evidence."
      ]
    ]
  ],
  [
    "SoK: Research Perspectives and Challenges for Bitcoin and Cryptocurrencies",
    "https://jbonneau.com/doc/BMCNKF15-IEEESP-bitcoin.pdf",
    [
      "2015年作者存档论文",
      "Author-hosted 2015 paper"
    ],
    "Author-hosted 2015 systematization PDF pp. 1–3 inspected for transaction scripts, ledger consensus, communication, UTXO references and historical security assumptions. Later attack taxonomies and current implementations not independently assessed.",
    [
      "材料梳理的是早期比特币技术与研究问题，不是当前客户端或协议的安全认证。账本上的脚本条件、现实身份与法律所有权不能相互替代。",
      "This surveys early Bitcoin technology and research questions, not the security of current clients or protocols. Script conditions, real-world identity and legal ownership are not interchangeable."
    ],
    [
      [
        "PDF pp. 1–2",
        "把系统拆成三层再阅读",
        "Read the system through three components",
        "综述把交易与脚本、共识以及通信网络分开讲解。有效签名回答谁满足了花费条件，共识回答大家接受哪一份历史，网络则负责信息传播。这些机制相互依赖，但任何一层正常都不能单独证明整个支付系统已经安全。",
        "The survey separates transactions and scripts, consensus, and communication. A valid signature helps satisfy spending conditions; consensus selects an accepted history; the network propagates information. Success at one layer does not establish security of the complete payment system."
      ],
      [
        "PDF pp. 2–3",
        "交易连接的是未花费输出",
        "Transactions connect unspent outputs",
        "早期比特币交易通过输入引用已有输出，并产生新的输出及其花费条件。分析对象因此不是银行账户余额的直接复制。将链上记录整理成用户资产时，还需要额外解决地址归属和输出关联，不能把一个地址自然等同于一个人。",
        "Inputs reference existing outputs and create new outputs with spending conditions. This is not a direct replica of bank-account balances. Constructing user-level holdings requires additional address attribution and output linkage; one address cannot simply be equated with one person."
      ],
      [
        "PDF p. 3",
        "签名不能单独解决双花",
        "Signatures alone do not prevent double spending",
        "同一花费者可以对相互冲突的交易作出有效签名，所以密码学上的授权不等于全局历史没有冲突。系统还需要共识规则决定哪一次花费被接受。只检查签名或交易格式，会遗漏账本排序与重复花费之间的关键联系。",
        "A spender can sign conflicting transactions, so cryptographic authorization does not ensure a conflict-free history. Consensus is needed to determine which spend is accepted. Signature or format validation alone misses the role of global ordering in preventing duplicate spending."
      ],
      [
        "PDF pp. 2–3",
        "脚本规定条件，而非现实权利",
        "Scripts specify conditions, not real-world rights",
        "输出中的脚本限制后续花费需要满足什么条件，常见条件涉及密钥与签名。掌握密钥能够影响协议层面的控制，却不自动说明现实中的合法所有人是谁。托管、失窃和代理关系等问题，需要账本之外的证据才能区分。",
        "Output scripts impose conditions on subsequent spending, often involving keys and signatures. Key possession affects protocol control without independently identifying lawful ownership. Custody, theft and agency relationships require evidence outside the ledger."
      ],
      [
        "PDF p. 3",
        "价值守恒需要识别发行例外",
        "Conservation checks must recognize issuance",
        "普通交易的输入与输出受到价值约束，但创造区块奖励的特殊交易不具有相同的输入结构。比较交易总额或生成资金流时，如果把发行和普通转移混为一谈，就可能重复计算。协议对象的类型，应先于汇总统计被识别出来。",
        "Ordinary transactions face input-output value constraints, whereas reward-creating transactions have a different input structure. Mixing issuance with ordinary transfers can distort aggregate flows or double-count value. Protocol object types must be identified before statistical aggregation."
      ],
      [
        "PDF pp. 1–2",
        "历史运行经验不等于未来保证",
        "Historical operation is not a future guarantee",
        "综述总结早期系统的运行经验，同时把开放的研究问题放在中心位置。历史上能够运行，不能证明所有攻击条件、治理变化和网络规模都已覆盖。阅读这类系统化综述的价值，是形成问题清单与概念边界，而不是获得永久有效的安全结论。",
        "The survey combines early operating experience with open research questions. Past operation does not cover every attack condition, governance change or network scale. Its value lies in organizing questions and conceptual boundaries, not in offering a permanent security guarantee."
      ]
    ]
  ],
  [
    "Taming Wildcat Stablecoins",
    "https://lawreview.uchicago.edu/sites/default/files/2023-04/03_Zhang%20%26%20Gorton_ART_Final.pdf",
    [
      "2023年《芝加哥大学法律评论》",
      "2023 University of Chicago Law Review"
    ],
    "Published 2023 University of Chicago Law Review 90:3, printed pp. 909–912 inspected for private-money analogy, no-questions-asked acceptance, convenience yield and historical policy framing. Detailed later legal analysis not reviewed.",
    [
      "本导读采用2023年发表版，书目仍保留2021年工作稿身份。历史类比和作者政策主张不是当前法律说明，也不能证明某个稳定币的储备安全。",
      "This guide uses the 2023 published article while retaining the 2021 working-paper identity. Historical analogies and policy proposals are not current legal guidance or proof of any stablecoin's reserve safety."
    ],
    [
      [
        "pp. 909–910",
        "稳定币也是私人货币问题",
        "Stablecoins raise a private-money question",
        "作者借私人银行券的历史讨论稳定币，关注公众为何愿意按面值接受私人发行的支付工具。这种类比不是说两种技术或法律结构完全一样，而是帮助识别信誉、兑付和普遍可接受性这些共同问题。链上转移只是其中一层。",
        "The authors use the history of private banknotes to ask why people accept privately issued payment claims at par. The analogy does not equate their technologies or legal structures. It highlights confidence, redemption and broad acceptability beyond the mechanics of on-chain transfer."
      ],
      [
        "pp. 910–912",
        "无需逐笔质疑是一种货币属性",
        "No-questions-asked acceptance is a monetary property",
        "文中强调，日常支付工具应尽量不要求收款人每次重新调查发行者。所谓无需质疑，描述的是在交易中按面值接受的便利，不是数学意义上的零风险。若每次收款都必须给储备重新估值，支付工具就承担了额外的信息负担。",
        "No-questions-asked acceptance means recipients need not reassess an issuer for every payment. It describes convenient acceptance at par, not mathematical absence of risk. Revaluing reserves on each receipt adds an information burden that can undermine monetary usefulness."
      ],
      [
        "pp. 910–912",
        "便利收益不同于利息收入",
        "Convenience yield differs from interest income",
        "货币持有者可能因为支付方便、普遍接受或节省核查而愿意持有某种工具。这类便利收益与账户上实际收到的利息不同，也不能直接填进收益率比较表。分析稳定币需求时，应区分支付服务价值与金融回报承诺。",
        "Holders may value payment convenience, acceptance and reduced verification effort. Such convenience yield is distinct from interest credited to an account and cannot simply be inserted into a return comparison. Payment-service value and promised financial compensation are different sources of demand."
      ],
      [
        "pp. 909–912",
        "价格稳定不代表兑付数量没有压力",
        "A stable price does not rule out redemption pressure",
        "稳定币的目标是维持接近面值，但市场担忧可能首先表现为大量赎回或流通数量下降。只看价格是否偏离，会遗漏支付承诺另一端的数量变化。储备是否能及时变现、赎回能否完成，需要与二级市场报价分别观察。",
        "Maintaining a near-par price does not preclude heavy redemptions or contraction in circulation. Price-only observation can miss quantity pressure on the payment promise. Reserve liquidity, successful redemption and secondary-market quotations need separate evidence."
      ],
      [
        "pp. 909–911",
        "储备可信度与转账技术分开",
        "Separate reserve credibility from transfer technology",
        "账本可以记录稳定币在地址之间转移，但不能仅靠记录证明支持兑付的资产真实存在、价值稳定或可随时取用。作者的私人货币视角提示，应把发行安排和储备可信度单独分析，而不是让技术可验证性代替资产负债关系。",
        "A ledger records token transfers without proving that redemption assets exist, retain value or remain accessible. The private-money perspective directs attention to issuance arrangements and reserve credibility. Technical verifiability cannot substitute for the underlying balance-sheet relationship."
      ],
      [
        "pp. 909–910",
        "政策方案属于作者的制度比较",
        "Policy proposals are institutional comparisons",
        "文章提出并比较若干制度方向，包括对私人发行的约束与公共数字货币等安排。这里应读作作者在当时语境下对货币制度的讨论，不是平台对现行监管的摘要。判断实际产品是否合法或安全，仍需另行核对适用规则和发行者证据。",
        "The article discusses institutional directions including constraints on private issuance and public digital money. These are the authors' proposals in their historical context, not a platform summary of current regulation. Actual legality or safety requires applicable rules and issuer-specific evidence."
      ]
    ]
  ],
  [
    "An Empirical Study of DeFi Liquidations: Incentives, Risks, and Instabilities",
    "https://arxiv.org/pdf/2106.06389v2",
    [
      "2021年10月arXiv第2版",
      "October 2021 arXiv v2"
    ],
    "arXiv 2106.06389v2, PDF pp. 1–3 inspected for historical protocol sample, fixed-spread versus auction liquidation, collateral/debt definitions, oracle dependence and participant incentives. No current protocol parameter or exploit execution assessed.",
    [
      "研究对象是历史版本的借贷协议。清算条件、预言机与网络费用会变化；链上地址不等于唯一用户，也不能用交易所永续数据替代借贷仓位。",
      "The study concerns historical lending-protocol versions. Thresholds, oracles and network fees change; addresses are not unique users, and exchange perpetual data cannot substitute for lending positions."
    ],
    [
      [
        "PDF pp. 1–2",
        "清算研究从仓位负债开始",
        "Start liquidation analysis with position debt",
        "文章研究抵押借贷仓位在不再满足协议条件时怎样被处理，涉及抵押品、债务和触发规则。这与交易所合约的持仓量或资金费率不同。识别协议、仓位及其资产组成，是理解清算事件的起点，而不是先寻找某条通用价格线。",
        "The study examines collateralized debt positions that breach protocol conditions, involving collateral, debt and trigger rules. This differs from exchange open interest or funding rates. Protocol identity and position composition precede any attempt to define a common liquidation price."
      ],
      [
        "PDF pp. 2–3",
        "几个比率不能混着使用",
        "Keep collateral ratios and thresholds distinct",
        "抵押价值与债务价值之比，和协议设置的清算阈值、抵押因子并非同一个变量。仓位可能仍有超过债务的抵押价值，却已满足清算条件。只按资产是否大于负债分类，会把偿付能力、借款约束与清算触发混在一起。",
        "Collateral-to-debt value, liquidation thresholds and collateral factors are different quantities. A position can have collateral worth more than its debt and still be liquidatable. Asset coverage alone conflates solvency, borrowing constraints and the protocol's trigger."
      ],
      [
        "PDF pp. 2–3",
        "拍卖和固定折价是不同机制",
        "Auctions and fixed spreads are different mechanisms",
        "样本中的协议并不采用完全相同的清算流程。工作稿区分拍卖与固定折价机制，它们对价格形成、参与和等待有不同要求。因此，跨协议统计不能只把所有清算金额合并，而应先保留机制类型与对应的历史版本。",
        "The sampled protocols use different procedures, including auctions and fixed-spread mechanisms. Their price formation, participation and timing differ. Cross-protocol aggregates should retain mechanism type and historical version instead of pooling all liquidation amounts as identical events."
      ],
      [
        "PDF pp. 1–3",
        "清算者激励与借款人损失要同时看",
        "Consider liquidator incentives and borrower losses",
        "协议需要吸引外部参与者处理风险仓位，这通常意味着清算者可以获得补偿，但同一安排也会影响借款人的损失。研究把两端放在一起观察。更多清算活动不自动意味着系统更有效率，也不能只凭参与者盈利判断规则优劣。",
        "Protocols need external participants to process risky positions, commonly offering compensation that also affects borrower losses. The study considers both sides. More liquidation activity does not automatically imply efficiency, and liquidator profitability alone cannot rank mechanism quality."
      ],
      [
        "PDF pp. 2–3",
        "触发价格是协议收到的价格",
        "The relevant price is the protocol's oracle input",
        "清算条件由协议采用的价格信息决定，不是任意交易所屏幕上的最新成交价。价格更新、交易提交和区块确认还有各自的时间。将这些事件压成一个时间点，会误读仓位何时可清算以及清算为什么没有立即发生。",
        "Liquidatability depends on the protocol's price input, not an arbitrary venue's latest trade. Oracle updates, transaction submission and confirmation have different times. Collapsing them obscures when a position becomes eligible and why liquidation need not occur immediately."
      ],
      [
        "PDF pp. 1–3",
        "链上可见不等于经济主体已识别",
        "On-chain visibility does not identify economic actors",
        "链上事件提供可核对的转移记录，但地址可能属于同一主体，主体也可能使用多个地址。网络费用、拥堵和协议参数进一步影响参与条件。历史事件比较因此需要保留地址层级与版本边界，不能据此直接给出当前借贷操作建议。",
        "Events provide observable transfers, while addresses need not correspond one-to-one with economic actors. Fees, congestion and protocol parameters affect participation. Historical comparisons retain address-level and version boundaries rather than yielding current borrowing instructions."
      ]
    ]
  ],
  [
    "SoK: Decentralized Finance (DeFi)",
    "https://arxiv.org/pdf/2101.08778v6",
    [
      "2022年9月arXiv第6版",
      "September 2022 arXiv v6"
    ],
    "arXiv 2101.08778v6 PDF pp. 1–3 inspected for DeFi ideals, ledger/contract/keeper/oracle/governance primitives, atomic execution and technical/economic risk framing. No later implementation or live protocol audit asserted.",
    [
      "采用2022年综述版本。非托管、开放和可组合是分析维度，不表示每个产品都具备这些属性；代码公开也不等于已经接受安全审计。",
      "This uses the 2022 survey. Non-custody, openness and composability are analytical dimensions, not properties guaranteed for every product; public code is not evidence of a completed security audit."
    ],
    [
      [
        "PDF pp. 1–2",
        "理想属性需要逐项核对",
        "Verify the ideal properties individually",
        "综述用非托管、无需许可、可审计和可组合等属性解释DeFi，但这些并不是给所有产品自动盖上的标签。一个协议可以在访问上开放，同时保留集中的升级权力。理解具体产品，需要把每个属性对应到实际控制与依赖。",
        "The survey describes DeFi through ideals such as non-custody, permissionless access, auditability and composability. These are not automatic labels for every product. Open access can coexist with concentrated upgrade powers, requiring each property to be checked against actual control and dependencies."
      ],
      [
        "PDF p. 2",
        "智能合约不会凭空自行醒来",
        "Contracts do not wake themselves up",
        "合约定义状态变化规则，但执行通常仍需要交易触发。综述因此把维护者等外部参与者作为重要组成部分。某项操作可以由合约自动计算，不等于无需任何人提交交易或承担费用；忽略触发依赖，会高估系统的自主运行能力。",
        "Contracts specify state transitions, but execution still requires triggering transactions. External keepers therefore matter. Automatic computation does not remove the need for someone to submit a transaction and pay its costs; ignoring triggers overstates operational autonomy."
      ],
      [
        "PDF pp. 2–3",
        "链上执行依赖链外信息时要看预言机",
        "Inspect oracles when execution depends on outside facts",
        "价格或现实事件进入合约，通常需要预言机提供信息。账本能够验证某条输入被使用，却不能单独证明其对应的链外事实真实无误。数据提供者、更新方式和异常处理，应与合约代码一起成为理解协议风险的对象。",
        "Prices and external events generally enter contracts through oracles. A ledger can verify that an input was used without independently verifying the outside fact. Providers, update procedures and failure handling belong alongside contract code in the risk assessment."
      ],
      [
        "PDF p. 2",
        "原子执行不代表经济上无风险",
        "Atomic execution is not economic risklessness",
        "原子性使一组操作按规则整体成功或整体回滚，但并不保证成功执行后用户一定盈利。价格变化、输入信息和交易排序仍然影响经济结果。因此，“不会留下半套状态”与“不会遭受损失”是两种完全不同的承诺。",
        "Atomicity allows a group of operations to succeed together or revert together. It does not guarantee a profitable successful transaction. Prices, inputs and ordering still shape outcomes, so avoiding partially completed state is different from avoiding economic loss."
      ],
      [
        "PDF p. 3",
        "治理权力也是系统依赖",
        "Governance powers are system dependencies",
        "参数调整和合约升级可能受管理员、持币投票或其他治理安排控制。形式上存在投票，并不证明控制权已经充分分散。阅读协议时，需要识别谁能改变规则、改变哪些规则，以及这些权力如何影响原本看似固定的合约承诺。",
        "Parameters and upgrades can be controlled by administrators, token voting or other governance arrangements. The existence of voting does not establish dispersed control. Identify who can change which rules and how those powers alter apparently fixed contractual commitments."
      ],
      [
        "PDF pp. 1–3",
        "组合之后要重新看风险边界",
        "Reassess risk after composition",
        "把多个协议连接起来可以产生新的用途，也会将预言机、流动性、治理和底层账本的依赖叠加。单个组件公开可检查，不代表组合之后的经济行为已经被验证。综述的技术与经济风险视角，帮助把代码正确性和系统稳定性分开提问。",
        "Connecting protocols creates new uses while combining oracle, liquidity, governance and ledger dependencies. Inspectable individual components do not validate the economics of their composition. Technical and economic perspectives distinguish code correctness from system stability."
      ]
    ]
  ]
].map(guide));
