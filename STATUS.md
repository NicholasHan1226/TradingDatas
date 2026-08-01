# TradingDatas 当前状态

最后更新：2026-08-01 16:40 CST。

> **2026-08-01 Tradings 退役路径复核：** 旧 `/opt/investment/SharedSignals` 已从活跃路径
> 移至 root-only `/opt/investment/_archive/SharedSignals-retired-active-path-20260801/`，
> 8082 继续关闭且无 SharedSignals unit/process。95GB 历史数据与 Git/receipt 证据未销毁，
> 不得成为 TradingDatas fallback。MarketGraph API/cron 已单独暂停；18082、18083 与
> TradingDatas collector timers 保持运行，registry/catalog/query 合同未改变。

## 当前运行面

- **8 月 1 日隔离 probe 与周末运行快照：** 生产 `current` 仍为 `d5b278…`，formal
  catalog 为 `v1-a057e9b7b5f1456d`，18082 API active、通用 collector timer
  enabled/active；production registry 有 `101` 项 `active/active`、`69` 项
  `paused/active`、`14` 项 `paused/locked`、`5` 项 `paused/excluded` 和 `1` 项
  `paused/unknown`。以服务器 `tradingdatas` 服务身份、现役 immutable release 的同一通用
  HTTPS probe 对 `trade_date=20260801` 的 `dc_concept_cons` 与 `fund_daily` 分别得到
  provider `ok` 但 `valid_empty`（均 0 行）；二者仍不能证明非空 identity 或 response
  completeness，保持 paused/NO-GO，未写 SQLite receipt、未改 registry、API、timer 或
  current。`stk_nineturn` 已从该 YYYYMMDD 日频 wave 拆出；其权威请求值为
  `YYYY-MM-DD HH:MM:SS`，独立、正确格式 probe 同样为 provider `ok`/`valid_empty`，没有
  发出错误日期格式调用。三份无 payload evidence 的 SHA-256 分别为
  `71a0eaf…577de2`、`d46b42d…2edf3d` 和 `97e8b73…a36ff`。
- **分钟与跨市场读回口径：** 2026-08-01 是周六，当前 rt_min envelope 的
  `stale/degraded` 是读时钟对 300 秒 SLA 的诚实投影，不得写成当日采集故障或实时可用。
  最近交易日 2026-07-31 的 13:25、13:30、13:35、13:40 通过 UID987/formal 18082
  精确读回均为 30 行、30 个唯一 `ts_code` 和单一 bar time；13:20 有 100 行，不能代替
  冻结 30-symbol cohort。500 扩容仍 NO-GO。CNFutures 继续 NO-GO：`fut_basic` 当前
  stale/degraded，`ft_mins` 与 `rt_fut_min` 未形成可消费 formal dataset；Crypto 18083
  属于独立运行面，本轮没有触碰。

- **只读 onboarding 报告运行验收：** `main=93b8c23` 的报告代码已被构建为不切流的
  immutable report-only release（131 个受 manifest 约束文件）；它没有成为 `current`。
  报告运行时显式绑定正式 `d5b278…` 物理 registry 原始字节（SHA-256
  `20f278e4…a6e082c7`）与同一 formal catalog version `v1-a057e9b7b5f1456d`，而没有
  使用 93b 自带的较新 registry。以 `tradingagent` 身份串行抓取一次 catalog 和 99 个
  query envelope（91 个读侧拒绝如实保留为未绑定），随后以 `tradingdatas` 身份只读打开
  verified SQLite snapshot 生成 schema-v1 报告；没有 provider 调用、SQLite 写入、API/timer
  或 current 切换。报告的 readiness 计数为 `contract_missing=65`、`stale=63`、
  `observed_isolated_only=36`、`paused=21`、`locked=3`、`failed=2`，`formal_ready=0`、
  `legal_empty=0`。这说明当前 snapshot 没有满足 receipt/time/provider/API 逐项绑定的正式
  可消费项，不能将 HTTP 200 或 catalog 可见性误报为 ready。仓外、无 payload 的 report、
  snapshot、acceptance summary 和 SHA-256 清单已保存为 release evidence；production
  `d5b278…`、18082 API 与 30-symbol timer 均经 verifier/readback 保持不变。
- 机器可读 onboarding 状态报告已正常合入 main/origin（`ad9dd31`）。它只读取 verified SQLite
  snapshot、registry 和可选的脱敏 formal API snapshot，
  不调用 provider、不写 DB、不触碰 18082、timer 或分钟运行面。报告把 `formal_ready` 与
  `observed_isolated_only`、`legal_empty`、`stale`、`failed`、`paused`、`locked`、
  `contract_missing`、`seed_missing`、`unobserved` 明确区分；正式可用必须满足
  `api_version=v1`、当前 registry catalog version/SHA-256、envelope dataset 与
  `degraded=false`，且 receipt、data-through、observed-at、provider lineage 与 SQLite 权威投影
  精确一致。独立 review P0/P1=0，11 项回归、Ruff 与 diff-check 通过。当前本机没有可绑定的
  production SQLite snapshot，因此未生成或伪造运行报告；服务器只读生成和 formal snapshot
  readback 是下一项运行验收，不构成部署动作。
- `cb_daily`、`dc_daily`、`dc_index`、`ft_limit`、`repo_daily`、`sge_daily` 与
  `tdx_index` 的七项同形单日分区合同已正常合入 main/origin（`753587a`）。变更严格限于
  六个 registry/config 及其生成物：不新增 route、collector、table、timer 或交易语义。
  隔离的 `trade_date=20260731` 真实 QuickSync 预检分别得到
  `308/1031/496/868/45/41/612` 行 success receipt；`[trade_date, ts_code]` 均非空、唯一且
  未达到 10,000 行上限，`dc_index` 固定 `idx_type=行业板块`。独立 clean-overlay review
  P0/P1=0，249 项编译、registry、request-observation、schedule 与 QuickSync 回归通过。
  这仍只是候选/隔离证明：七项保持 `on_demand`，尚未切换 formal 18082/current；必须等待下一个
  可用分区的正式 success receipt 和认证 API fresh readback，不能把 20260731 的旧分区写成
  内部生产可消费数据。
- `bak_basic`、`limit_list_d`、`ci_daily` 与 `ths_daily` 的四项同类单日分区合同已正常
  合入 main（PR #43，`ecf336b`）。修正后的候选只含 registry/config 及其生成物，不新增
  route、collector、table、timer 或交易语义。真实 QuickSync 隔离采集对
  `trade_date=20260731` 分别完成 `5543/206/444/1880 inserted`，同窗口重放分别为
  `5543/206/444/1880 unchanged`；认证候选 18091 query 的终止分页、首分页重放以及
  receipt/lineage 都已验证。`limit_list_d.last_time` 的 107/206 合法空值现明确为非主键可空，
  `[trade_date, ts_code]` 仍全量非空唯一。独立 clean-overlay review P0/P1=0，131 项
  compiler/registry/observations 回归通过。该固定 20260731 分区已超过 86400 秒 SLA，
  所有候选 envelope 因而如实为 `stale/degraded`；候选 18091 已停止，尚未切换 formal 18082。
  下一可用交易日的新分区 receipt 与正式 18082 fresh readback 才是部署门槛。
- `limit_cpt_list`、`limit_step` 与 `sz_daily_info` 的同类、单日分区合同已正常合入
  main（`0d2b2ea`）：三项均复用既有 generic registry/transport/SQLite receipt/catalog-query
  路径，不新增 route、collector、table、timer 或交易语义。隔离 immutable candidate
  `f6f92ea90e54bac8ab20a74552c7c387f8c6fc10` 已经真实 QuickSync 验证：首次分别
  `20/10/14 inserted`，同窗口重放分别 `20/10/14 unchanged`；以
  `tradingagent` 身份的候选 18091 query 行数、终止 cursor、receipt/lineage 与规范化重放
  均通过，独立 review P0/P1=0。查询时 `20260731` 已超过 86400 秒 SLA，三项如实投影为
  `stale/degraded`，所以尚未切换 formal 18082；下一个可用日分区的 production receipt
  和 fresh readback 才是部署门槛。候选 18091 已停止，正式 18082 与 30-symbol timer
  本轮未改动。
- 正式 A 股 API：`tradingdatas-v1-internal.service` 为 active，固定只读接口仍是
  `GET /v1/catalog` 与 `POST /v1/query`（loopback `18082`）。
- 正式 immutable `current`：`d5b2788208d55e9f7052783caf8447233cf01dfa`；18082 API
  active，通用 provider-native timer 为 `enabled/active`。本次闭市切换仅将
  `cn.dataset.moneyflow` 冻结为 `trade_date` 日分区、`[trade_date, ts_code]` identity、
  `postclose_daily` 与单分区完整性合同；官方 source schema 仍为 v1，既有 QuickSync
  response override 继续生成 runtime schema v2。没有修改分钟 collector、公共 API route 或
  TradingAgent。target、直接回退点 `04fcf3a6af8cfe1c18b0420af11f4ccec6b21a86` 与 current
  均已由 trusted manifest verifier
  验证，目标 registry 也从冻结输入逐字节重编译。更早的回退链仍保留：
  `cb89620b7e20356a00c7ff3f06c357b401565113`、
  `0935b70aafca4f3bd269381aa2ee6bba8ac73f61`、`1f17708730172bc31fba3f849fa938da6e8a73fa`
  与经过验证的
  `5ac3925c3931a81132ea02abb16f9745033fb6dc` 继续保留为分钟运行面的后续 rollback
  链；`71b7890928a9cc8c6345f41b0cd87a60f46158f8` 仍只作为已验证的 500-symbol 候选，
  不挂载到正式 18082。
  13:05/13:10 的 500 live 门禁失败后，发布侧按停止线先停 API/timer、以 trusted manifest
  原子回切 5ac、再恢复 API/timer；切换没有写入、覆盖或补造任何 SQLite facts/receipts。
- 71b 的事件/公告合同与严格 provider-local minute timestamp 投影仍保留在 immutable
  release 中。此前以 `tradingagent` 身份对候选 18082 的 `cn.dataset.anns_d` 带 `as_of`
  分页 readback 通过；该候选证据不等于当前 5ac 正式可用性，也不增加任何新闻分析或交易逻辑。
- 切换前后均以 trusted manifest verifier 验证 current/release。以 `tradingagent` 身份的正式
  18082 catalog readback 为 HTTP 200；闭市 planner 在 `tradingdatas` 身份下对
  `cn.dataset.rt_min` 返回 `not_due`，因此未在闭市窗口伪采分钟 bar。
- **500-symbol live 门禁失败：** 正式 18082 以 `tradingagent` 身份对
  `time=2026-07-31 13:05:00` 与 `13:10:00` 的精确 query 均返回 0 行；两者均投影为
  `failed/degraded/quality=degraded`，原因 `validation_failed`，且指向完整 lineage 的 failed
  receipt `receipt:b0810c7b7667e6fedc5208f7ebc41a23bba9155c7bd6b38bacfc1b52cd4238ac`。
  因而未达到 500 unique、单一 time、5 个 success shard receipt、分页终止/重放与
  `ready/fresh/valid` 条件；没有尝试第三轮，也没有把旧 30 或旧 bar 伪装为通过。当前保持
  5ac/30 production，500 仅作为隔离候选，真实交易继续关闭。
- `stock_st` production readback：正式 generic one-shot 对 `trade_date=20260731`
  返回 208 行并留下 success receipt；随后以 `tradingagent` 身份通过 formal 18082
  分页读取为 208 行、208 个 `[trade_date, ts_code]` 唯一 identity、3 页且 terminal cursor
  为 null，receipt/lineage 完整。该分区的 `data_through=2026-07-31` 已跨读取时钟的
  86400 秒 SLA，envelope 因而如实为 `stale/degraded`；它证明稳定按需入库/API 合同，
  不把昨日 ST 标记数据伪装为当前新鲜或可交易事实。
- `moneyflow_ths` production readback：正式 generic one-shot 对 `trade_date=20260731`
  返回 5,199 行并留下 success receipt；随后以 `tradingagent` 身份通过 formal 18082
  分页读取为 5,199 行、5,199 个 `[trade_date, ts_code]` 非空唯一 identity、11 页且 terminal
  cursor 为 null。相同请求第二次读取的行数、identity digest 与 cursor 语义一致；metadata
  为 `ready/success/fresh/valid/non-degraded`，receipt
  `receipt:73b27d0be181cb17f75fc4aa7cf03629c0d6e9e55ce189884d0c88f573539af9` 与 lineage
  完整。这证明该日分区可经内部 API 稳定按日读取；不代表策略、交易或其他未验收数据集已可用。
- `moneyflow` production readback：在候选真实 receipt 与第二次 unchanged 重放均通过独立
  review 后，正式 generic one-shot 对 `trade_date=20260731` 返回 5,197 行。以
  `tradingagent` 身份通过 formal 18082 分页读取为 5,197 行、5,197 个 `[trade_date, ts_code]`
  非空唯一 identity、11 页且 terminal cursor 为 null；相同请求第二次读取的行数、identity
  digest 与 cursor 语义一致。metadata 为 `ready/success/fresh/valid/non-degraded`，receipt
  `receipt:09823b511506ab7295233384eba702c692c0a75a6a2027add1f3b77aa9043987` 与 lineage
  完整。该项是客观的日级资金流数据事实，不是交易信号或执行 authority。
- `moneyflow_cnt_ths` 已正常合入 main（`bdd9bf6`），但尚未部署到正式 current：隔离 candidate
  对 `trade_date=20260731` 的通用采集为 386 行 inserted，第二次为 386 行 unchanged；
  `[trade_date, ts_code]` 均非空且唯一、未触顶，candidate loopback 分页为 `100/100/100/86`、
  terminal cursor 与 lineage 完整。独立 review 为 P0/P1/P2=0，且 activation-wave 的 registry
  hash 已同步。由于此时已跨 86400 秒 SLA，candidate envelope 如实为 `stale/degraded`；因此
  未切换正式 current，也不把该 yesterday partition 写成 fresh production 通过。下一可用日分区
  的 receipt 与正式 18082 readback 是该项部署门槛。
- `moneyflow_hsgt` 已正常合入 main（`8f29bdc`）：候选用冻结 release 对 `trade_date=20260731`
  留下 1 行 inserted、随后 1 行 unchanged 的两个 success receipt，`[trade_date]` 非空唯一，
  loopback query 的 terminal cursor、payload replay 与 lineage 均完整。独立 review 为 P0/P1/P2=0，
  但该分区已经跨 SLA，metadata 如实为 `stale/degraded`；它尚未部署到正式 current。必须由下一个
  可用日分区的 production receipt 与 formal 18082 fresh readback 才能进入内部可消费集合。
- `daily_info` 已正常合入 main（`15f4871`）：隔离 immutable candidate 的两次通用采集对
  `trade_date=20260731` 依次得到 11 条 inserted、11 条 unchanged；`[trade_date, ts_code]`
  全部非空且唯一，认证 loopback query 为 schema 1、11 行、终止 cursor、重放一致且
  receipt/lineage 完整。独立 review 为 P0/P1/P2=0。该分区已跨 86400 秒 SLA，envelope
  因而诚实为 `stale/degraded`；尚未切入正式 current。下一可用日分区的正式 receipt 与
  18082 fresh readback 是部署门槛，不能用这一昨日证据宣称内部生产可消费。
- `index_dailybasic` 已正常合入 main（`da55d55`）：隔离 immutable candidate 的两次通用采集对
  `trade_date=20260731` 依次得到 12 条 inserted、12 条 unchanged；`[trade_date, ts_code]`
  全部非空且唯一，认证 loopback query 为 schema 1、12 行、终止 cursor、重放一致且
  receipt/lineage 完整。独立 review 为 P0/P1/P2=0。该日分区也已跨 86400 秒 SLA，故尚未
  切换正式 current；只有下一个可用日分区的 production receipt 与 formal 18082 fresh readback
  能把它加入内部可消费集合。
- 对失败 receipt `b0810c7b...` 的 16:01 CST 只读审计进一步确认：同一 13:20
  attempt 的 5 个非空 100-symbol 分片均为 `returned=validated=committed=0`、
  `terminal_no_data_transaction`、`validation_failed`，没有部分 500 facts 写入。因此该次
  NO-GO 的唯一根因是当时 QuickSync/Tushare 没有返回任何分钟行，不是分页、SQLite 投影或
  分片原子性故障。隔离 DB 在 15:08 以同一通用 5×100 runner 对 15:00 bar 取得 5 个 success
  receipt、500 个唯一 symbol、同一 provider time；临时 loopback catalog/query 可分页终止并
  重放一致。16:00 读取时该 bar 已按 300 秒 SLA 诚实为 stale，且没有在同一 clean isolate
  中取得第二根相邻的 fresh bar，故不能以此替代下一交易时段的双轮 live 门禁，也不得据此切换
  正式 current。
- 回滚后的自然 30-symbol 链路已恢复：正式 18082、`tradingagent` 身份对 `13:25`、`13:30`、
  `13:35`、`13:40` 的精确 query 均为 30 行/30 个唯一 symbol、单一 time、
  `ready/success/fresh/valid/non-degraded` 且 receipt/lineage 完整；本页复核的 `13:45`
  也满足同一合同。`13:20` 的多于 30 行结果不作为恢复起点。该证据仅恢复既有 30-symbol
  数据链，不重启 500，也不赋予真实交易 authority。
- 13:05 CST 的 a42 首轮 live 验证未通过：collector 日志显示 `rt_min` success，但正式
  18082 精确查询 `time=2026-07-30 13:00:00` 返回 0 行，不能将旧 11:30 数据伪装为
  最新 500 分钟 bar。按 fail-closed 停止线，已先停 API/timer、用已验证 manifest 原子回切
  `5ac3925`，再恢复 API/timer；SQLite facts 和 receipts 均未覆盖或删除。
- 回滚后以 `tradingagent` 身份对正式 18082 查询
  `cn.dataset.rt_min(time=2026-07-30 11:30:00)` 得到 30 个唯一 symbol、单一 time，
  但 metadata 诚实为 `stale/degraded`；这仅证明回滚可读，**不**证明实时分钟链已恢复。
- 13:16 CST 的后续 UID987 受控 readback 已确认回滚后的 30 只链路重新出现两根相邻
  completed bar：`13:05` 与 `13:10` 各 30 个唯一 symbol。正式 envelope 为
  `ready/success/fresh/valid/non-degraded`，receipt 存在且 lineage 完整；这是 30 只回滚链
  恢复的证据，不解除 500 候选的 NO-GO。
- 15:05 和 15:10 的 `rt_min` 上游调用各留下一个 `provider_error` 的 failed receipt（均为
  0 行）；没有手工重试、插库或删除失败证据。现有通用 session-minute timer 在下一合资格
  15:20 轮自然恢复，取得实际 `time=2026-07-30 15:00:00` 的 30 个唯一 symbol；15:25 轮
  同样成功。以 `tradingagent` 身份对正式 18082 精确查询该 time 为
  `ready/success/fresh/valid/non-degraded`，receipt 与 lineage 完整。这只证明最终 bar 的
  合法恢复，不填补 15:05/15:10 的失败尝试，也不解除 500 的 NO-GO。
- 2026-07-31 09:35 的 500 live 门禁失败后，TA 已停止并禁用 scale500 session/paper
  timers，恢复旧 30 session/paper timers；两个状态根均保留且
  `REAL_TRADING_ENABLED=false`。回切后正式 18082 精确查询 `09:35` 得到 30 个唯一
  symbol、单一 time，metadata 为 `ready/success/fresh/valid/non-degraded`，receipt 与
  lineage 完整。`09:30` 分区仍可见此前 500 候选写入的事实，因此读取方必须继续使用冻结
  Universe，不能把全分区行数当作当前 30-symbol cohort 完整性证明。
- 后续正式读回确认 `09:35`、`09:40`、`09:45` 三根相邻 completed bar 各为 30 个唯一
  symbol、无游标且 metadata/receipt/lineage 全部通过。TA 于 09:57 重新初始化冻结的 30-symbol
  日内状态，并于 09:58 通过显式 incident-recovery late-start 消费 `09:45` 一根：30 行、
  资金/执行 authority 均为 false、无候选、无持仓、四个影子袖套对账通过。被跳过的 `09:35`
  与 `09:40` 被记录为 gap，因此当天 `full_session_complete=false`、
  `learning_eligible=false`，没有伪造历史 PIT 或补做交易。
- `REAL_TRADING_ENABLED=false`。TradingDatas 不管理策略、资金、订单、broker 或交易。

## 已验证的内部数据事实

- 2026-07-29 23:04 CST 的正式 18082、以 `tradingagent` 身份 readback 得到
  `catalog_version=v1-1e4560099e58a89e`。catalog 的数量只表示合同与可发现性；消费者必须
  每次根据 query envelope 的 `state`、`degraded`、`freshness`、`quality`、receipt 与 lineage
  决定是否消费。
- 同次 readback 已验证：
  `cn.market.trade_calendar(SSE, 20260730)`、`cn.equity.daily(20260729)`、
  `cn.dataset.stk_limit(20260729)`、`cn.dataset.adj_factor(20260729)` 当时均为
  `ready/success/fresh/valid/non-degraded`，且 receipt/lineage 完整。
- `cn.dataset.suspend_d(20260729)` 的较早 `provider_error` 已由本页所述 23:24 CST
  的成功 receipt 覆盖；当前读取状态以最新可信 receipt 为准，不能把较早错误或空行混作
  当前结果。

## 夜间预采集快照

- 2026-07-29 23:24–23:25 CST 通过正式、受控的 provider-native oneshot（timer 仍关闭）
  串行完成了当前已到窗口的六项通用 registry 采集。它没有增加 route、专用 collector、
  交易语义或新的自动调度。
- `cn.dataset.broker_recommend`、`cn.dataset.limit_list_ths`、
  `cn.dataset.moneyflow_ths`、`cn.dataset.stk_holdernumber` 已取得 success receipt，
  `cn.dataset.fund_portfolio` 取得合法 empty receipt；五项均可从正式 18082 查询到数据或
  空结果，且 lineage 完整，但由于当前 registry 尚未声明 response completeness 和可信业务
  watermark，API 如实返回 `state=partial`、`degraded=true`，不能被消费者作为新鲜完整事实。
- `cn.dataset.suspend_d(20260729)` 已通过同一正式 18082 以 TradingAgent 只读身份回读：
  `state=ready`、`runtime_state=success`、`freshness=fresh`、`quality=valid`、
  `degraded=false`，receipt 与 lineage 均完整。
- 此轮证明的是“通用入库与内部 API 读回”而非六项都已稳定自动化。明早仍只按既有门禁复核
  30 只分钟链路；其余数据集需要先补齐 registry 的完整性/水位合同，才可能从 partial 晋级为
  可消费的 ready。

## 明日批量准备

- 对 2026-07-30 16:35 CST 的 registry-driven 计划进行了只读模拟：24 项会被选中，
  `failed=0`。其中包括日线、复权因子、涨跌停、融资融券、申万日线、北向与资金流；
  68 项按需数据和 89 项 paused 数据继续被排除。这是明日盘后受控 one-shot 的准备证据，
  不是预先启用 timer 或宣称 24 项已经采集成功。
- 当前 5 项 partial 的合同不会被凭空改为 ready。只有补齐各自的 primary identity、请求窗口
  完整性和业务 watermark 后，才允许以新合同重新采集、receipt 验证和正式 API 读回。

## 新闻、公告与互动数据（历史生产证据已保留，当前未挂载）

- 主线与 immutable release `56ab09aaa758943485890717fa2b5e29254d281a`
  已冻结五项事件证据数据的通用 registry
  合同：`cn.dataset.anns_d`、`cn.dataset.cctv_news`、`cn.dataset.irm_qa_sh`、
  `cn.dataset.irm_qa_sz` 与 `cn.dataset.research_report`。它们复用既有 QuickSync
  transport、SQLite receipt、catalog/query 数据面与通用 `event` cadence；现有通用
  scheduler 约每 15 分钟检查一次，日期分区的 freshness SLA 为 86400 秒。没有新增公共
  route、专用 collector、业务表或新闻专用 timer。该 release 当前不再是正式 `current`；
  下列 readback 是回滚前保留的真实生产证据，不是当前 18082 可用性声明。
- 隔离 SQLite 的 `20260730` provider 采集成功且身份数与行数一致：公告 1119、央视新闻
  11、上证互动 282、深证互动 2、研报 13。相同窗口第二次真实上游重放均为 `unchanged`
  success receipt；公告历史窗口经有界 `as_of` 分页为 3 页、1119 个唯一身份，首分页重放一致。
- `20260731` 首次受控日期窗口检查返回五个合法 empty receipt；候选 API 以 TradingAgent 只读身份
  返回 `empty/valid/non-degraded` 与完整 receipt/lineage，未把空结果伪装为成功数据。
  昨日分区在当前读取时钟下按 86400 秒 SLA 诚实为 stale；历史重放必须带明确 `as_of`，不能将
  昨日数据称为当前新鲜事实。
- 早期按需候选的 immutable manifest SHA-256 为
  `08ddf79a5f338e171a9f806c9f6836a942d9162427092f035010609a96592450`，其编译/registry/
  schedule 回归分别为 37/37、48/48、95/95 通过。最终 event cadence 版本另有 134 项
  compiler/scheduler 回归、生成文件逐字节相等和 activation hash 校验；production
  catalog_version=`v1-1a25a650e12bdc4d`。2026-07-31 02:15 CST 首个自动周期
  `Result=success`，五项 formal 18082 readback 均为合法
  `empty/valid/non-degraded`，receipt 与 lineage 完整；这表示当天当时上游无返回行，
  不是已有新闻内容或交易信号。`major_news`/`news` 仍维持 paused/404，不伪装为已接入。
- 2026-07-31 早盘的后续自动采集已取得真实公告内容：正式 18082 对
  `cn.dataset.anns_d(ann_date=20260731)` 有界分页返回 1209 行、1209 个唯一身份，metadata
  为 `ready/success/fresh/valid/non-degraded`，receipt/lineage 完整，首分页再次读回一致。
  同期 `cctv_news`、`irm_qa_sh`、`irm_qa_sz`、`research_report` 均为合法
  `empty/valid/non-degraded`，只表示当前 provider 返回 0 行，不表示接口失效。
- 10:12–10:18 CST 使用 server immutable `7de9ed58` 在临时 loopback `18086` 完成一次
  只读候选 parity 后立即停止，端口已关闭，正式 18082/current/timer 未变。候选 catalog
  `v1-54838b10dd9c696d` 下，`anns_d(20260731)` 为
  `ready/success/fresh/valid/non-degraded`；`cctv_news`、两项 `irm_qa` 与
  `research_report` 均为带完整 receipt/lineage 的合法 empty。该 parity 只证明发布代码可按
  现有 SQLite 事实投影，不构成正式 current 或持久候选服务。

## 第二批非开盘接口（已合入并正式挂载）

- 2026-07-31 17:xx CST 已在闭市受控窗口把本批的 main `1f17708` 挂载到正式 18082，随后
  用 `0935b70` 修复唯一 P1：通用 query 层此前把 registry 声明为 `yyyymm` 的月分区错误按
  `yyyymmdd` 校验。修复只涉及 `query_service.py` 与回归测试；PR #26 已普通合入、目标 release
  已由 manifest verifier 验证。正式 readback（`tradingagent` 身份）结果是：
  `disclosure_date(20260731)` 为 2 行、`ready/success/fresh/valid/non-degraded`；
  `share_float(20260731)` 为 44 行且同状态；`top_list(20260730)` 为 113 行、receipt/lineage
  完整但因日分区已超过 SLA 诚实为 `stale/degraded`；`broker_recommend(202607)` 的上游当前
  返回 0 行并留下 failed validation receipt，带 `month` 的正式 query 已不再 HTTP 400，而是
  因没有可用 success receipt 诚实 503 fail-closed。没有伪造月度 data_through、没有手工 SQLite，
  也没有把 broker_recommend 标为可消费。

- 同一切换后的只读候选审计不新增采集或配置：`report_rc` 当前窗口是合法 empty，历史行中
  `quarter` 有 11 个空值，不能作为稳定修订身份；`repurchase` 最近成功 receipt 的 49 行均缺
  `end_date`/`exp_date`，不能用伪主键；`top_inst` 最近成功 receipt 的 909 行按
  `[trade_date,ts_code,exalter,side,reason]` 仍有 132 个重复 excess。三项均维持 NO-GO。
  `stk_managers` 的最近 4 行样本暂时唯一且非空，但样本量不足，只可进入后续隔离真实 receipt
  评估，不进入本次 production。事件侧 `anns_d` 的有界 as-of query 为 ready；
  `research_report` 虽有行和 lineage，但 response completeness 未冻结，仍 degraded；
  `cctv_news` 与两项 `irm_qa` 的 as-of query 没有匹配 success receipt 而诚实 503，
  `major_news`/`news` 继续 paused。没有为任何一项新增 route、专用 collector 或数据表。

- `stk_managers` 的下一独立隔离 slice 已在独立 SQLite 中通过同一 generic collector 对
  `ann_date=20260728` 与 `20260731` 得到两个真实 success receipt（分别 57 与 8 行）。候选
  业务身份 `[ann_date,ts_code,name,title,begin_date]` 在 20260731 的 8 行样本中非空且唯一，
  但 20260728 的 57 行有 11 个 `begin_date` 空值，并存在一组重复；重复行只在可空 `lev`
  字段不同。因而没有可证明的非空稳定业务主键，不能以 payload hash、可空字段拼接或丢弃字段
  伪造身份。此项为 P1/NO-GO：不生成 registry/config 候选、不建 PR、不发布，隔离 DB/receipt
  仅保留审计证据，正式 18082 与 30-symbol 分钟链未受影响。

- 随后的只读排序只选择了一个下一候选：`cn.dataset.fund_share`。隔离 SQLite 对
  `trade_date=20260728` 的真实 provider 调用得到 1,703 行，
  `[trade_date,ts_code]` 为 1,703/1,703 非空唯一、未触顶，重放为 1,703 `unchanged` 行。
  该证据已用于冻结纯 registry/config 合同：schema `2.0.0`、日分区、
  `[trade_date,ts_code]` 主键、默认排序和
  `single_partition_unique_primary_key` response completeness；cadence 仍为 `on_demand`，
  没有新增 collector、route、timer 或业务表。PR #27 已普通合并为 `cb89620`，target release
  manifest、离线 registry 重编译、clean-overlay P0/P1 审查和 13 项 compiler/query/scheduler/
  receipt 回归均通过。
- 2026-07-31 23:14 CST 的正式单项 generic one-shot（`tradingdatas` 身份）对
  `trade_date=20260731` plan 与 execute 均成功。随后以 `tradingagent` 身份从 formal 18082
  分页 readback：791 行、791 个非空唯一身份、两页终止；metadata 为
  `ready/success/fresh/valid/non-degraded`，receipt
  `receipt:14d8e037c2798d02cdb7b193fb7dede3cdd290a05e0caedcd2c5bcceeee95db0` 与 lineage
  完整。第二次相同查询的行数、身份 digest 和 receipt 完全一致。该项现在是可按需内部读取的
  数据事实，不代表自动调度、研究结论或交易 authority。
- `fund_share` 闭环后的下一独立候选是 `cn.dataset.limit_list_ths`。候选
  `9a45f577c650946348b46a17865eb53f9087da91` 已经 PR #28 普通合并为
  `6299d6239c717f579e734a86e94fa1505ecac6ec`，只冻结真实返回的 18 个字段、
  `schema_major=2`、日分区 `[trade_date,ts_code]` 身份和既有通用
  `single_partition_unique_primary_key` 合同；上游这次未返回的 6 个文档可选字段不再被伪装为
  已有字段，原始 provider payload 仍无损保存。候选没有增加 Python、route、collector、timer
  或表。
- 2026-07-31 23:45 CST 在独立 release/SQLite 中以 `tradingdatas` 身份两次真实采集
  `trade_date=20260731`：第一次 100/100 写入，第二次 100/100 unchanged，两个 receipt 的
  payload 指纹一致。随后临时 loopback（18084，已停止）以 `tradingagent` 身份按固定
  catalog/query 合同读取到两页 100/100 非空唯一身份、终页 cursor 和重放一致；metadata 为
  `ready/success/fresh/valid/non-degraded`，receipt/lineage 完整。随后受控原子切换正式 current，
  以 `tradingdatas` 身份对同一日期完成 plan+execute，并以 `tradingagent` 身份从 formal 18082
  得到两页 100/100、终页 cursor、重放一致与
  `ready/success/fresh/valid/non-degraded`；正式 receipt 为
  `receipt:85ed2ad22d0f1882bd0889039b90a3723f76c84b016c26eac173f20c42244785`，lineage 完整。
  该数据集现在可按日分区从内部 API 只读消费，不代表自动交易或策略 authority。
- `cn.dataset.fund_div` 以 PR #31 普通合并为
  `013623aed01cc2b6400f6ce1341d64b39db09bf0`，仅新增通用 registry/config 与回归：
  schema `2.0.0`、`ann_date` 单日窗口、
  `[ts_code,ann_date,imp_anndate,base_date,div_proc]` identity 和
  `single_partition_unique_primary_key` 完整性合同。独立 clean-overlay 审查为 P0/P1/P2=0；
  不新增 Python、route、collector、timer 或业务表。受控发布后，正式 18082 以
  `tradingagent` 身份对 `ann_date=20260801` 返回合法
  `empty/valid/non-degraded`（receipt
  `receipt:76915b398ca1278be35652f228b3dd6901f0f08c1ffdf08811b55c3f29b345c6`，lineage 完整）。
  这是上游当前窗口无记录的真实状态，不伪装为有内容或自动调度；当有真实公告日数据时，再以同一
  on-demand 合同做有界 readback。
- `stk_holdernumber` 有一条业务身份重复，继续 NO-GO；此前的 `report_rc`、`repurchase`、
  `top_inst`、`stk_managers` 结论不变。此前 `moneyflow_ths` 的历史 receipt 审计包含一个
  14,593 行、30,150 duplicate-excess 的不合格窗口；它没有被删除或覆盖。后续隔离真实采集
  使用冻结的单日窗口得到 5,199/5,199 非空唯一事实后，才以新的完整 success receipt 进入本次
  production readback。此候选与筛选没有触及分钟 timer。

- 生产 receipt 审计表明，`cn.dataset.disclosure_date` 的三个真实分区均可使用
  `[ann_date,end_date,ts_code]` 作为分区内非空唯一身份。main/GitHub 的
  `7ee1396a5bf84ae6f393605450fbd193cc8093ea` 已通过 registry/config
  将它冻结为 `on_demand`、`ann_date` 单日分区和
  `single_partition_unique_primary_key` 完整性合同；QuickSync 未返回的 `modify_date`
  继续由既有响应观测显式移除。相同 SHA 的 immutable server release 已预构建并通过
  manifest/registry 字节一致性验证，但正式 current 已因分钟 live 门禁回到 `5ac3925`；
  本项尚未在正式 18082 重新采集和读回，不能提前称为 ready。
- `broker_recommend` 的月份字段是 `YYYYMM`，当前通用日分区 watermark 不能科学投影月度
  完整性；`report_rc` 与 `repurchase` 的可区分修订字段存在空值；`stk_surv` 尚无真实行级
  样本。因此四项继续保持 partial/stale 或 empty 的现状，不通过新增专用代码、伪主键或
  人工插库强行升级。
- 本次扩展继续选择可由现有通用 `yyyymmdd` 分区合同表达、且生产 SQLite 已有真实
  行级样本的接口：`share_float` 的 65 行在两个公告日分区内以
  `[ann_date,float_date,ts_code,holder_name,share_type]` 全部非空且唯一；
  `top_list` 的 164 行在两个交易日分区内以 `[trade_date,ts_code,reason]` 全部非空且唯一。
  两项只增加 reviewed registry/completeness 合同，不增加 Python、route、collector 或
  timer；在新的 immutable release、真实 receipt 和 formal 18082 readback 完成前仍不是当前
  可消费数据。`block_trade` 虽当前 131 行可区分，但上游没有稳定业务流水号，重复成交碰撞
  仍可能发生，未纳入本批。
- 同一 10:12–10:18 候选 parity 对 `disclosure_date`、`share_float` 与 `top_list`
  均得到 `unobserved/degraded/no_recognized_receipt`，与“新合同尚未形成新 authority
  receipt”的停止线一致；没有复用旧合同 receipt、人工插库或把已有 rows 升级为 ready。

## 500 只分钟数据候选（已回滚，live 验证失败）

- 2026-07-30 主线已普通合入 500 分片合同，并补齐已审的次日交易日历、开市分钟窗口与
  session-minute 优先级。候选 immutable release 为
  `a42e66277aa7bbfa284fb7afdef980a4ba95386d`；午间虽完成原子切换，但首轮 live
  500/500 证明失败，现已安全回滚到 `5ac3925`。该候选在重新取得两根相邻 live 500/500
  receipt/API readback 前不得再次切入 production。

- 原始候选 commit：`4329307352d9138186cd2e3fca994ca5cdc96083`；审计分支：
  `codex/rtmin-500-atomic-v3`。其 4 份配置改动已正常合入 main 的
  `3b4ecc35531091d6356604f8bf156acffa28b2b8`。该记录是早期候选的审计来源；当前
  production 指针、timer 状态和可用性以上文 13:08 CST readback 为准。
- 只修改同一通用数据面需要的 4 份 registry/contract/hash 配置：
  `cn.dataset.rt_min` 使用 `entity_fanout`、5 片 × 100、`identity=[ts_code,time]`，并要求
  每轮同一 bar_end 的 500 个唯一身份齐全；没有新增 route、专用 collector、TA 改动或交易语义。
- 隔离候选对 2026-07-29 15:00 的真实 QuickSync 压测已得到 500/500、5 个成功 receipt、
  3.117 秒总耗时；候选 query 以 `time eq`、`limit=100` 得到 5 页、终止 cursor，重放的
  data/cursor/metadata 一致。候选证据：
  `/opt/investment-data/tradingdatas/candidate-evidence/rtmin500-4329307352d9138186cd2e3fca994ca5cdc96083/rtmin500-history-1500-evidence.json`
  （SHA-256 `21b66b0d7e7dcfe7137e19865c856ff44d4877b997909288d0980b46d7a90be8`）。
- 该候选的 fresh clean-overlay 关键门禁为 7/7 PASS；合入后同一关键回归为 10/10 PASS。
  它仍不能替代下一交易时段的真实证明：先确认现役 30/30 第一根，再要求预构建 release
  连续两根相邻 live bar 均为 500/500、5/5 分片、同一 bar_end、总耗时小于 300 秒。任一
  失败则保持 30 只 production rollback，不切换。
- 13:00 生产失败的隔离根因已复现：五个 100-symbol 上游分片实际合计只有 498 个唯一
  symbol（缺 `002294.SZ`、`000333.SZ`），且全部是旧的 11:30 bar；因此正式查询 13:00
  返回 0 行是正确的，不是 API 投影故障。编译器曾静默丢失 registry 声明的
  `fanout_field=ts_code`，并把采集开始时间当作 snapshot `data_through`，使缺码旧 bar
  错记为 success/fresh。
- 该问题最初在隔离候选 `8d18b5cffa06fd7af979d1962cb7b94c01f61794` 中修正：保留
  `fanout_field` 并要求每个请求值恰好一次，同时以 provider 的真实 bar time
  生成 snapshot watermark。候选在独立 SQLite 上完成一次收盘后 5×100 的 500/500 同一 15:00
  bar、5 个 success receipt、8.5 秒采集；候选 API 对已过 SLA 的历史 bar 诚实返回 stale，
  没有宣称 live-ready。仍欠下一交易时段两根相邻的真实 500/500 证明，之前禁止再切换生产。
- 该通用修正已在主线普通合入为 `ad4bc00`，并作为上述盘后 production release 切换；这只是
  代码/配置发布，不等于 500 分钟数据已经被 live 证明。明早首两根已完成 bar 必须各自满足
  500 个唯一 symbol、同一实际 provider time、5/5 分片 success receipt、完整 lineage、
  `ready/success/fresh/valid/non-degraded` 的正式 18082 envelope 与一致重放。任一轮失败即
  受控回切 `5ac3925`，保留失败 receipt，不手工补库。

## 旧系统退役与保留

- SharedSignals 运行态已退役并 permanent-mask：7 个历史 service/timer 均为
  `inactive/masked`；旧 `8082` 无监听；root 的 5 条和 `marketgraph` 的 22 条活动旧 cron
  已移除。原 unit 文件已复制并移入受限退役证据目录，回滚需先显式 `unmask` 后恢复该副本。
  退役证据：
  `/opt/investment/release-evidence/tradingdatas/20260729T124623Z-sharedsignals-runtime-retirement/unit-mask-20260729T211900Z`
  （`SHA256SUMS` 摘要：`832b938f21638deea95dd16ed565684dfbe9b72642090cdf1f74d4d2e28a9629`）。
- 2026-07-29 已按逐目录审计和明确授权退役本地 SharedSignals 源码：16 个历史 worktree、
  26 个本地候选分支及其旧 Python 环境、缓存和源码残留均已移除，且没有候选需要合并进
  TradingDatas。旧仓仅保留本地 Git 历史、`RETIRED.md`、`data/`、`logs/` 和
  `.codegraphcontext/`；SQLite、receipt、evidence 和 rollback 材料不在删除范围。
- 旧 SharedSignals 仓原先错误指向 TradingDatas GitHub remote 的 `origin` 已移除，防止它再向
  活跃 TradingDatas 主线推送。该退役提交只留在旧仓本地历史；TradingDatas main/origin 不受影响。
- 2026-07-29 已清除 12 条指向已不存在 `/private/tmp` 目录的 Git worktree 元数据；这不会删除
  任何文件或数据。

## 下一步与停止线

1. 保持 30-symbol 回滚链与 TA 冻结 Universe，继续记录真实分钟 receipt；不得把同一 SQLite
   中的历史 500 facts 当作当前 cohort，且不得通过放宽 SLA 掩盖 QuickSync 分钟数据延迟。
2. 为分钟模拟盘补充可证明满足决策延迟门禁的上游或受控延迟语义；在此之前不再次放行 500。
3. 在不影响分钟运行面的独立安全窗口，将事件合同和 `disclosure_date` 合同纳入一个经过
   manifest、真实 receipt、正式 18082 readback 验证的 production release；发布前不得把
   已保留 server release 称为当前可消费。
4. 当前不扩公共 API、不新增专用采集器，不把已 active、paused 或单次成功说成“全部接口已稳定采集”。

历史候选、事故、旧端口和早期探测结论以 Git 历史与服务器 evidence 为准，不再保留在当前状态页。
