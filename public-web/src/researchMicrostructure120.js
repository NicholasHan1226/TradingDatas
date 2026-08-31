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

export const researchMicrostructure120 = Object.fromEntries([
  [
    "Bid, Ask and Transaction Prices in a Specialist Market with Heterogeneously Informed Traders",
    "https://web.stanford.edu/~milgrom/publishedarticles/Bid%20Ask%20and%20Transaction%20Prices.pdf",
    [
      "1985年论文作者存档扫描",
      "Author-hosted 1985 paper scan"
    ],
    "Author-hosted scan, PDF pages 1–3 visually read for introduction, competitive zero-profit specialist, adverse selection, conditional quotes and return interpretation. Later propositions and empirical identification not reviewed.",
    [
      "这是信息不对称的理论模型，并未估计当前市场各种价差成本的占比。风险中性、竞争与库存约束等假设，不能未经检验直接套用真实订单簿。",
      "This information model does not estimate today's spread components. Risk neutrality, competition and inventory assumptions must be examined before applying it to an actual order book."
    ],
    [
      [
        "PDF pp. 1–2",
        "没有库存成本，也可能有价差",
        "A spread without inventory costs",
        "Glosten与Milgrom将买卖价差解释为信息不对称的结果。即使做市商风险中性、没有交易成本且预期利润为零，仍可能报出不同的买价与卖价。因此，看到价差不能只寻找手续费或库存成本，也要考虑交易对手的信息优势。",
        "Glosten and Milgrom isolate an informational source of spreads. A risk-neutral, zero-cost specialist can quote different buying and selling prices while earning zero expected profit. Fees and inventory costs are therefore not the only possible explanations."
      ],
      [
        "PDF p. 2",
        "交易意愿本身会带来信息",
        "Willingness to trade carries information",
        "接受卖价买入的人，可能知道做市商尚不知道的好消息；接受买价卖出的人也可能有相反的信息。报价必须考虑这种选择，而不是把交易到来当成与资产价值无关的随机抽样。这正是模型中逆向选择的含义。",
        "A customer accepting an ask may know favorable information unavailable to the specialist; a seller may know the opposite. Quotes account for this selection. Order arrival is not treated as a random sample independent of asset value."
      ],
      [
        "PDF pp. 2–3",
        "零利润不是每笔交易都不亏",
        "Zero expected profit is not zero loss on every trade",
        "模型中的竞争条件约束的是给定信息下的预期利润。做市商与知情者成交可能亏损，与其他交易者成交的收入则补偿这部分损失。将预期约束理解成逐笔无损，会抹去价差在该模型中存在的原因，也混淆事前与事后结果。",
        "Competition constrains expected profit conditional on information. Losses to informed traders are offset by gains from other transactions. This is not a promise of zero loss on each trade; confusing expectation with realization removes the model's rationale for a spread."
      ],
      [
        "PDF p. 3",
        "买价与卖价对应不同条件",
        "Bid and ask condition on different events",
        "做市商不是给资产设置一个与下一笔交易无关的单一价格。卖价已经考虑下一位客户是买方所透露的信息，买价则对应卖方到来的情形。因此，比较报价、中间价与成交价时，需要保留交易方向和报价所依据的信息时点。",
        "The ask incorporates information inferred if the next customer buys, while the bid conditions on a sale. Quotes, midpoints and transaction prices therefore represent different objects. An empirical comparison needs direction and the timing of the information behind each quote."
      ],
      [
        "PDF pp. 1–2",
        "价格序列收益不等于可实现收益",
        "Recorded returns differ from attainable returns",
        "论文提醒，带有价差的价格序列可能使非知情交易者能够实现的收益被高估。具体偏差取决于收益的测量方式，而非所有价格变化都需机械扣同一个数。阅读时应先确认采用成交价、报价还是其他基准，再讨论其经济含义。",
        "With spreads, recorded price returns can overstate what an uninformed trader can realize. The discrepancy depends on the return convention rather than a universal deduction. Identify whether the series uses transactions, quotes or another benchmark before interpreting it."
      ],
      [
        "PDF pp. 2–3",
        "理论来源与经验分解分开",
        "Separate theoretical origin from empirical decomposition",
        "该模型展示信息差足以产生价差，并不说明真实市场的全部价差都来自信息差。与Roll等低频估计研究并读时，应区分“机制为何存在”和“怎样从数据识别成分”。理论假设为测量提出问题，不会自动把不可观测的信息状态变成数据字段。",
        "Showing that information asymmetry can generate spreads does not assign all observed spreads to it. Read alongside empirical spread estimators to distinguish a mechanism from its measurement. A theoretical information state is not automatically an observed data field."
      ]
    ]
  ],
  [
    "Optimal Execution of Portfolio Transactions",
    "https://quantitativebrokers.com/s/Optimal-Execution-of-Portfolio-Transaction-_-AlmgrenChriss-1999.pdf",
    [
      "1999年4月8日作者稿",
      "April 8, 1999 manuscript"
    ],
    "April 8, 1999 manuscript hosted by Almgren's firm; PDF pp. 1–4 and 7–9 read for cost/risk trade-off, static benchmark, remaining inventory and permanent/temporary impact. No implementation or later numerical results reproduced.",
    [
      "导读依据1999年作者稿，引用身份仍为2001年期刊论文。这里解释成本度量和模型假设，不提供下单程序；静态最优性依赖独立增量等条件。",
      "This guide uses the 1999 manuscript while retaining the 2001 journal identity. It explains cost measurement, not an order program. Static optimality depends on assumptions including independent increments."
    ],
    [
      [
        "pp. 3–4",
        "研究的是成本与不确定性的权衡",
        "Cost and uncertainty are separate objectives",
        "Almgren与Chriss将预期交易成本和成本的不确定性放在同一框架内。立即完成与分段完成可能面对不同的冲击和价格风险，因而只比较平均成交价格不足以定义“最优”。这里的最优是相对于目标函数与假设，不是普遍适用的执行承诺。",
        "The framework combines expected trading cost with its uncertainty. Immediate and staged completion face different impact and price exposure, so average price alone cannot define optimality. The term is relative to an objective and assumptions, not a universal execution guarantee."
      ],
      [
        "p. 7",
        "剩余数量与本期交易数量不同",
        "Remaining inventory differs from interval volume",
        "稿件用每个时点剩余的数量描述路径，再用相邻剩余数量之差描述该区间的交易量。初始数量和结束时剩余为零构成边界。理解这种记账关系，有助于检查是否遗漏或重复计算数量，而不是从一条行情曲线推断真实完成情况。",
        "The path records units remaining at each time; consecutive differences give interval volume. Initial holdings and zero final holdings impose boundaries. This accounting helps detect missing or duplicated quantity, but a price series does not establish actual completion."
      ],
      [
        "pp. 8–9",
        "永久冲击与临时冲击分开",
        "Permanent and temporary impact are distinct",
        "永久冲击改变模型中的后续市场价格，临时冲击则影响当前一批的平均成交价格，并假设在下一阶段恢复。这里的“永久”是针对执行期间而言，不等于无限期存在。把两者都塞进同一个固定费率，会失去对影响时间范围的区分。",
        "Permanent impact changes subsequent modeled prices; temporary impact affects the current batch's average execution price and is assumed to recover. Permanent refers to the execution horizon, not eternity. A single flat fee obscures these distinct time effects."
      ],
      [
        "pp. 3–4",
        "静态路径来自强假设",
        "A static path follows from strong assumptions",
        "作者指出，在价格独立增量和对称风险惩罚等条件下，可以在事前求出静态路径。这不是说新信息永远没有价值；稿件将这种路径作为与动态处理比较的基准。若价格相关性、信息或风险偏好发生变化，需要重新判断原结论的适用性。",
        "Independent price increments and a symmetric risk penalty support a path chosen in advance. The authors treat this as a benchmark for dynamic approaches, not a claim that information never matters. Dependence, news and different preferences can change the conclusion."
      ],
      [
        "pp. 8–9",
        "市场价格与实际成交价格分别记录",
        "Market and execution prices need separate records",
        "模型将市场参考价格与包含临时冲击的成交价格分开，并据此计算整段收入与成本。用于检验时，不能用日收盘价同时冒充参考价和逐笔执行价。数量、价格单位、时点与基准需对应，才能判断差额描述的是市场移动还是执行成本。",
        "The model separates a market reference price from an execution price affected by temporary impact. Daily closes cannot stand in for both. Quantity, units, timestamps and benchmark definitions must align to distinguish market movement from execution cost."
      ],
      [
        "pp. 3–4, 7–9",
        "先理解度量，再考虑模型迁移",
        "Understand measurement before transferring the model",
        "线性或简化的冲击假设帮助建立可解释的基准，但不同场所的深度、交易规则和费用并未因此相同。阅读这篇论文的起点，是识别所需的数量和成本资料及模型边界。本文没有提供真实订单或成交样本，也不代表任何数据接口具备交易能力。",
        "Simplified impact assumptions produce an interpretable benchmark without equating venues' depth, rules or fees. The reading task is to identify quantity and cost inputs and their limits. No actual order sample or trading capability follows from this guide."
      ]
    ]
  ],
  [
    "Limit Order Book as a Market for Liquidity",
    "https://www.edegan.com/pdfs/Foucault%20Kadan%20Kandel%20(2005)%20-%20Limit%20Order%20Book%20as%20a%20Market%20for%20Liquidity.pdf",
    [
      "2005年期刊扫描版",
      "2005 journal scan"
    ],
    "Original RFS 2005 article scan hosted by academic Ed Egan; PDF cover and pp. 1171–1173 read for patience, order choice, waiting costs, resiliency and tick-size implications. No later proofs or numerical replication reviewed.",
    [
      "模型以等待成本不同的流动性交易者解释订单簿，不能把其中的交易选择直接当成知情交易识别。韧性采用特定概率定义，也不是所有市场恢复速度指标的同义词。",
      "The model explains liquidity trading through waiting costs, not identification of informed orders. Resiliency has a particular probability definition and is not interchangeable with every recovery-speed measure."
    ],
    [
      [
        "pp. 1171–1172",
        "订单类型也是时间选择",
        "Order type is also a timing choice",
        "Foucault、Kadan与Kandel将限价单和市价单理解为对即时成交的不同需求。限价单可能改善价格，但需要等待且未必成交；市价单换取即时性。订单类型因而不能只用价格好坏判断，还应看到未成交和等待所带来的成本。",
        "Limit and market orders express different demands for immediacy. A limit order may improve price but must wait and may remain unfilled. Order choice therefore involves waiting and nonexecution, not just a comparison of quoted prices."
      ],
      [
        "p. 1172",
        "耐心是模型中的等待成本",
        "Patience means a cost of waiting",
        "模型中的参与者都想完成单位交易，但等待成本不同。所谓有耐心与无耐心，是对这种成本的建模，不是对现实投资者性格或信息水平的标签。若用数据研究对应机制，应先说明怎样观察等待和订单选择，而不是直接猜测个人动机。",
        "Traders seek unit transactions but differ in waiting costs. Patient and impatient label these modeled costs, not personality or information quality. An empirical application must explain how waiting and order choices are observed rather than infer motives directly."
      ],
      [
        "p. 1173",
        "韧性有明确的事件边界",
        "Resiliency has an explicit event boundary",
        "文章将韧性定义为流动性冲击后、下一笔成交前，价差恢复到原水平的概率。这与恢复所需秒数或价格反弹幅度不是同一个量。测量时若改变冲击、恢复目标或终止事件，就已经改变了指标，不能只保留相同名称。",
        "Resiliency is the probability that the spread returns to its former level before the next trade after a liquidity shock. It is not elapsed recovery time or a price rebound. Changing the shock, target or ending event changes the measure."
      ],
      [
        "p. 1173",
        "更多耐心交易者可能改变报价竞争",
        "Patient traders alter quote competition",
        "在模型中，耐心交易者比例增加会改变流动性供需，并延长限价单的预期等待。提供流动性的人于是可能用更积极的报价缩短等待。这条机制将人群组成、订单选择与价差恢复连在一起，不能简化为交易数量越多市场就越好。",
        "A larger patient population changes liquidity demand and can lengthen expected waiting for limit orders. More aggressive quotes then help reduce waiting. The mechanism connects participant composition with recovery rather than equating more transactions with better markets."
      ],
      [
        "p. 1173",
        "到达更快不一定恢复更快",
        "Faster arrivals need not improve resiliency",
        "更高的到达率缩短等待，可能让报价不必那么积极，因此价差恢复前需要更多订单。这里的结论对应论文的事件概率定义，不应改写成所有时间单位下恢复都更慢。阅读时必须同时保留模型机制和度量使用的时钟。",
        "Higher arrival rates shorten waiting and can reduce incentives for aggressive quotes, requiring more orders before recovery. This concerns the paper's event-probability definition, not every clock-time recovery measure. Preserve the mechanism and the measurement clock."
      ],
      [
        "p. 1173",
        "更小的报价单位并非单向改善",
        "A smaller tick is not a one-way improvement",
        "文章说明，在某些以急于成交者为主的环境中，缩小最小报价单位可能削弱积极改善报价的动力，影响恢复并提高平均价差。这是均衡模型下的条件性结果，不是对某个交易所当前规则的结论，也不能单独支持一次具体制度变更。",
        "In some impatient-trader environments, a smaller tick weakens incentives to improve quotes, affecting recovery and average spreads. This is a conditional equilibrium result, not a diagnosis of a current exchange or sufficient support for a specific rule change."
      ]
    ]
  ],
  [
    "Hawkes Processes in Finance",
    "https://arxiv.org/pdf/1502.04592v2",
    [
      "2015年5月17日arXiv v2",
      "May 17, 2015 arXiv v2"
    ],
    "Frozen arXiv 1502.04592v2, PDF pp. 1–3 read for scope, counting processes, conditional intensity, causal nonnegative kernels and typed event times. Later estimation appendices and empirical applications not reproduced.",
    [
      "这是事件模型综述，而非统一适用于所有金融序列的拟合方案。所读线性定义采用非负、因果核；聚集与交叉激发本身不证明经济因果或交易优势。",
      "This event-model survey is not a universal fitting recipe. The consulted linear definition uses causal nonnegative kernels; clustering and cross-excitation do not themselves establish economic causality or a trading edge."
    ],
    [
      [
        "pp. 1–2",
        "先把事件与等间隔观测分开",
        "Separate events from grid observations",
        "综述关注交易、报价变化等发生时点，而不只是把数据聚合为每分钟一行。等间隔统计保留区间总量，却可能丢失到达顺序和间隔。选择事件模型之前，应确认原数据确实记录所研究的事件，而不是只有聚合后的价格与成交量。",
        "The survey models times of trades and quote changes rather than only regular bars. Aggregation preserves totals but can discard ordering and gaps between events. An event model requires observations of the events of interest, not merely interval prices and volume."
      ],
      [
        "p. 3",
        "强度描述条件到达速度",
        "Intensity describes conditional arrival rate",
        "强度利用当前时点之前的信息描述紧接下来事件到达的速度。它不是单位时间内已经发生的计数，也不是未来必然发生几次的承诺。将估计强度与实现计数比较时，要保持时间单位与预测区间一致，否则数值大小没有可比性。",
        "Intensity uses information before the current time to describe the immediate arrival rate. It is neither an already realized count nor a guaranteed number of future events. Comparing intensity with counts requires consistent time units and observation intervals."
      ],
      [
        "p. 3",
        "基线与过去事件贡献相加",
        "Baseline and past-event contributions add",
        "线性Hawkes定义将外生基线与过去事件经核函数加权的贡献相加。某次事件对后续的影响随时间距离变化，而不是给所有未来时点增加固定计数。这个分解提供模型解释，但基线和核能否从样本中可靠估计仍是另一问题。",
        "The linear definition adds a baseline to kernel-weighted contributions from past events. Influence depends on elapsed time rather than adding a fixed future count. This decomposition is interpretable, but reliable estimation of its components remains a separate problem."
      ],
      [
        "p. 3",
        "不同事件类型之间也能联动",
        "Different event types can interact",
        "多变量模型为每类事件设置计数过程，并用核矩阵描述一类事件对另一类强度的影响。例如成交与报价变化必须先有明确分类，才能解释交叉项。分类或时间戳错误会改变估计关系，不能把模型矩阵直接当成市场参与者的真实作用网络。",
        "A multivariate model assigns a counting process to each event type and a kernel matrix to cross-effects on intensity. Trades and quote changes need clear labels. Misclassification or timestamp errors alter the fitted relation; the matrix is not a directly observed causal network."
      ],
      [
        "p. 3",
        "核函数的约束是定义的一部分",
        "Kernel restrictions are part of the definition",
        "所读定义要求核具有因果性、非负性和相应可积条件。因果性在这里意味着未来事件不进入当前强度，非负性意味着这一线性形式描述激发而非抑制。不能在保留原模型名称的同时忽略这些条件，再任意解释负系数或未来信息。",
        "The consulted definition requires causal, nonnegative, integrable kernels. Causality here excludes future events from current intensity; nonnegativity makes this form excitatory. Ignoring these conditions while retaining the model label changes what its parameters mean."
      ],
      [
        "pp. 1–3",
        "应用清单不是共同验证结果",
        "An application map is not joint validation",
        "综述将价格、订单流、冲击及系统联系分为不同应用方向，各自的数据和识别条件并不相同。阅读时可沿主题找到进一步的原论文，但不能因为同属Hawkes模型就合并验证结论。事件强度可解释活动聚集，也不自动产生价格方向判断。",
        "The survey organizes prices, order flow, impact and systemic links into applications with different data and assumptions. Use it to locate original studies, not to pool their validation. Explaining event clustering does not automatically determine price direction."
      ]
    ]
  ],
  [
    "The Long Memory of the Efficient Market",
    "https://arxiv.org/pdf/cond-mat/0311053v2",
    [
      "arXiv cond-mat/0311053 第2版",
      "arXiv cond-mat/0311053 v2"
    ],
    "arXiv v2 header dated July 26, 2004; PDF pp. 1–3 read for event signs, effective order classification, SETS sample and liquidity compensation. Body auto-date says November 26, 2024; not treated as a new empirical sample or publication.",
    [
      "导读使用arXiv v2，文件头版本为2004年，正文另有2024年排版日期；后者不表示样本更新。订单方向的持续性不等于价格收益同样可预测，样本仅含特定历史电子市场。",
      "The arXiv v2 header is from 2004, while the body shows a 2024 typesetting date, not a refreshed sample. Persistent order signs do not imply equally predictable returns; the evidence concerns a historical electronic market."
    ],
    [
      [
        "pp. 1–2",
        "长记忆首先指订单方向",
        "Long memory first concerns order signs",
        "Lillo与Farmer研究买卖方向序列的相关性为何能持续到较远的事件间隔。这一对象不同于价格水平、收益或波动率。若把“订单具有长记忆”直接改写成“价格容易预测”，就跳过了订单流到价格形成之间最关键的一层机制。",
        "The paper studies persistent dependence in buy/sell signs across event lags. Signs differ from prices, returns and volatility. Translating long memory in orders directly into easy price prediction skips the central price-formation mechanism."
      ],
      [
        "p. 3",
        "按实际效果拆分订单",
        "Classify orders by their effects",
        "数据处理中，立即成交的部分记作有效市价单，留在簿中的部分记作有效限价单。一张可成交限价单可能同时贡献两类事件。因此，直接使用交易所原始订单名称不一定复现论文分类，拆分数量和成交状态需要能够追溯。",
        "Immediate execution counts as an effective market order; a resting remainder counts as an effective limit order. One submitted order can generate both. Exchange order names alone may not reproduce this classification, so quantities and execution states must remain traceable."
      ],
      [
        "pp. 2–3",
        "事件时间不等于钟表时间",
        "Event time differs from clock time",
        "研究通常按某类事件的发生次数推进时间，而不是按固定秒数采样。一个活跃时段和一个安静时段可以贡献相同数量的事件却持续不同长度。比较长记忆结果时，应确认使用哪一类事件、是否包含撤单，以及是否混入开盘集合竞价。",
        "Time usually advances by counts of a chosen event type rather than seconds. Equal event counts can span unequal durations. Comparing persistence requires specifying the event type, cancellations and session treatment, including the exclusion of the opening auction."
      ],
      [
        "p. 1",
        "数量与深度可能抵消方向持续性",
        "Size and depth can offset sign persistence",
        "作者指出，当买入方向更可能持续时，买单数量相对于卖方最优报价处深度可能减小，从而降低推动价格变化的概率。这个补偿机制说明，方向、数量与可用流动性要一起看。只保留买卖标签，会丢失解释价格为何没有同样持续变化的信息。",
        "When buys become more likely, buy size relative to depth at the best ask can decline, reducing the chance of moving price. This compensation motivates examining signs, size and liquidity together. Signs alone omit information needed to explain weaker return persistence."
      ],
      [
        "p. 3",
        "电子市场样本不是整个交易系统",
        "The electronic sample is not the whole market",
        "样本研究1999—2002年持续交易的20只伦敦股票，并只分析电子市场连续交易部分。场外或楼上市场并不因此被覆盖。历史样本的完整事件记录也不同于整个市场的完整覆盖，不能把两种“完整”混为一谈。",
        "The sample follows twenty continuously traded London stocks in 1999–2002 and uses electronic continuous trading. Upstairs activity is outside it. Complete events within a selected venue are not complete coverage of the entire market."
      ],
      [
        "pp. 1–3",
        "持续性检验不等于识别拆单动机",
        "Persistence does not identify a splitting motive",
        "作者讨论不同机构的方向序列，但并未据此解决长记忆来源的全部问题。机构代码能够帮助分组，不等于观察最终投资者或完整母单。应用时需保留这种身份粒度，避免把相关性直接解释成某个参与者有意实施的单一行为。",
        "Institution-level sequences offer clues without fully resolving the source of persistence. An institutional code need not identify an ultimate investor or parent order. Preserve that identity granularity rather than turning dependence into a specific behavioral motive."
      ]
    ]
  ],
  [
    "The High-Frequency Trading Arms Race: Frequent Batch Auctions as a Market Design Response",
    "https://ericbudish.org/files/high_frequency_trading_arms_race.pdf",
    [
      "2015年期刊版",
      "2015 journal edition"
    ],
    "Author-hosted QJE article, printed pp. 1547–1549 read for serial processing, public-information races and discrete-time uniform-price proposal. Later proofs, data tables and policy implementation not reproduced.",
    [
      "文章提出机制设计方案，而非证明任何市场当前都应采用同一批次长度。本文区分公共信息下的速度竞争与信息优势，不提供实盘执行或制度实施结论。",
      "The paper proposes a market design, not a universally validated batch interval. This guide distinguishes speed competition under public information from private information and makes no live execution or implementation claim."
    ],
    [
      [
        "pp. 1548–1549",
        "问题不只是电脑有多快",
        "The question is not merely computer speed",
        "Budish、Cramton与Shim把竞争的根源放在连续时间下逐条处理订单的机制中。即使大家都看见同一公共消息，更新与接受旧报价之间仍可能发生竞赛。因此，研究关注信息到达后的处理规则，而不只是比较参与者拥有多少硬件。",
        "The authors locate the problem in serial processing under continuous-time trading. Even shared public news can trigger a race between updating and accepting stale quotes. The focus is the processing rule after information arrives, not merely hardware ownership."
      ],
      [
        "p. 1548",
        "同步可见的信息也可能产生租金",
        "Shared information can still create rents",
        "论文将公共消息出现后的机械性套利机会与私人信息区分开。信息相同不意味着每个人都能在相同时间完成撤单或成交；串行处理会放大极小的速度差。这个机制也提醒读者，不要把所有短时优势都归结为更准确的基本面判断。",
        "The mechanism separates public-news arbitrage from private information. Seeing the same news does not ensure equal ability to cancel or execute before others. Serial processing magnifies tiny speed differences, which need not represent better fundamental judgment."
      ],
      [
        "p. 1549",
        "同一时间窗的请求一起处理",
        "Process a time window as one batch",
        "方案把交易日划成很短但离散的时间窗，在同一窗口到达的请求按同一批处理，再用统一价格拍卖撮合。文中的100毫秒用于说明设想，不是无需验证即可采用的固定配置。理解这个区别，才能把机制研究与工程参数选择分开。",
        "The proposal groups requests arriving within a short interval and clears them in a uniform-price auction. The example of 100 milliseconds illustrates the design; it is not a universally validated setting. Mechanism and implementation parameters are separate decisions."
      ],
      [
        "pp. 1548–1549",
        "价格竞争与速度竞争不同",
        "Price and speed competition differ",
        "作者认为，批量处理可以降低极小速度优势的价值，让竞争更多体现在价格上。这个结论属于其模型和论证，不代表现实中所有延迟价值或套利机会都消失。判断某项机制是否适合具体市场，还需要规则、参与者和交易需求的证据。",
        "Batching is argued to reduce the value of tiny speed advantages and shift competition toward price. That is a model-based claim, not the disappearance of all latency value or arbitrage. Application requires evidence about rules, participants and trading needs."
      ],
      [
        "p. 1549",
        "跨市场时钟决定能否观察竞赛",
        "Cross-market clocks govern what can be observed",
        "论文使用交易所直接行情的毫秒级资料讨论两个跟踪同一指数的工具。把这种机制放到分钟线中检验，可能将不同先后顺序聚合成相同区间。资料准备首先需要确认场所、时间戳含义和时钟对齐，不能仅靠提高图表刷新频率。",
        "The argument draws on millisecond direct-feed observations of instruments tracking the same index. Minute bars can collapse different event orders into one interval. Venue identity, timestamp semantics and clock alignment matter more than a faster chart refresh."
      ],
      [
        "pp. 1547–1549",
        "研究提案与已实施效果分开",
        "Separate a proposal from observed implementation",
        "论文将经验事实、理论机制和替代设计连在一起，但三者并不是同一种证据。阅读时应分别问现象在哪里被观察、机制依赖什么假设，以及方案是否经过真实环境测试。提出一种设计不等于已证明部署之后的所有市场质量结果。",
        "Observed facts, a theoretical mechanism and a proposed design provide different evidence. Ask where the facts were observed, which assumptions support the mechanism and whether implementation was tested. A proposal does not certify all post-deployment market-quality outcomes."
      ]
    ]
  ],
  [
    "High-Frequency Trading and Price Discovery",
    "https://faculty.haas.berkeley.edu/hender/hft-pd.pdf",
    [
      "2014年期刊版",
      "2014 journal edition"
    ],
    "Author-hosted RFS 2014 article, printed pp. 2267–2270 read for NASDAQ HFT labels, permanent/transitory state-space interpretation, supply/demand split and unavailable no-HFT counterfactual. Later tables not replicated.",
    [
      "样本识别的是NASDAQ资料中的一部分高频交易者，不是所有自动化交易。观察到的均衡关系不能独立证明移除高频交易后的结果，价格发现也不等于公平或社会福利的完整评价。",
      "The data identify a subset of NASDAQ HFTs, not all automated trading. Observed equilibrium relations do not establish outcomes without HFT, and price discovery is not a complete fairness or welfare assessment."
    ],
    [
      [
        "pp. 2267–2268",
        "先确认谁被标作高频交易者",
        "Identify who receives the HFT label",
        "研究使用带参与者分类的NASDAQ逐笔资料，而不是凭一段交易很快就自行认定高频交易。分类覆盖的是可识别的子集，且资料分别标记供给与需求两侧。因此，只有价格与成交量的数据不能直接重建论文中的参与者比较。",
        "The study uses NASDAQ transaction data with participant classification, not speed alone as an HFT label. A subset is identified on both liquidity sides. Price and volume without those classifications cannot reproduce its participant comparisons."
      ],
      [
        "p. 2268",
        "永久与暂时成分来自模型分解",
        "Permanent and transitory components are modeled",
        "作者采用状态空间模型，将价格移动分成永久和暂时部分，通常分别解释为信息与定价误差。这些成分不是交易所直接发布的真值。衡量价格效率之前，需要理解分解假设、估计区间与误差，而不是给任一价格上涨贴上“信息”标签。",
        "A state-space model separates permanent and transitory price components, interpreted as information and pricing error. These are not exchange-published truths. Efficiency assessment requires understanding decomposition assumptions and estimation uncertainty, not labeling every price rise as information."
      ],
      [
        "pp. 2268–2269",
        "提供与消耗流动性要分开",
        "Separate liquidity supply from demand",
        "研究发现的总体关系主要通过高频交易者主动消耗流动性的订单体现，而其被动提供流动性的订单会受到逆向选择。将两类活动合并，可能隐藏相反的作用。读取同一参与者的资料时，也应区分这一笔在交易中的具体角色。",
        "The overall relationship is associated with HFT liquidity-demanding orders, while their supplying orders face adverse selection. Aggregating the two can hide opposing effects. Participant identity alone does not replace the role played in a particular transaction."
      ],
      [
        "p. 2269",
        "没有高频交易的反事实未被观察",
        "The no-HFT counterfactual is unobserved",
        "作者明确指出，数据记录的是高频交易者存在时的均衡结果，无法直接看到没有这些参与者时其他人会怎样调整。因而，样本中的价格效率关系不是简单的移除实验，不能把相关证据直接写成政策变化必然带来的效果。",
        "The authors explicitly note that their data are equilibrium outcomes with HFT present. The counterfactual response of other traders without HFT is unknown. Observed efficiency relations are not a removal experiment and cannot directly determine a policy effect."
      ],
      [
        "pp. 2269–2270",
        "价格发现不等于所有维度都改善",
        "Price discovery is not improvement in every dimension",
        "更快反映信息与其他交易者面临的逆向选择成本可以同时存在。论文研究价格发现及效率，但公平性、基础设施成本与整体福利是不同问题。读者应保留这种并存关系，而不是把文章归纳成对全部高频交易的单向赞成或反对。",
        "Faster information incorporation can coexist with adverse-selection costs for others. Price discovery, fairness, infrastructure cost and welfare are distinct questions. Preserve that coexistence rather than treating the paper as blanket approval or rejection of HFT."
      ],
      [
        "pp. 2268–2270",
        "历史交易样本不能替代当前诊断",
        "A historical sample is not a current diagnosis",
        "资料涉及2008—2009年的特定股票样本，并将公共消息、盘口变化与短时价格关系联系起来。市场规则、数据分发与参与者可能已经改变。复用概念时应先核对样本和时钟，不能把历史关系直接称为当下市场的已验证状态。",
        "The 2008–2009 stock sample connects public news, book conditions and short-horizon prices. Rules, feeds and participants may subsequently change. Reusing the concepts requires renewed sample and clock checks, not relabeling historical findings as current market health."
      ]
    ]
  ]
].map(guide));
