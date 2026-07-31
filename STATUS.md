# TradingDatas 当前状态

最后更新：2026-07-31 13:25 CST。

## 当前运行面

- 正式 A 股 API：`tradingdatas-v1-internal.service` 为 active，固定只读接口仍是
  `GET /v1/catalog` 与 `POST /v1/query`（loopback `18082`）。
- 正式 immutable `current`：`5ac3925c3931a81132ea02abb16f9745033fb6dc`；18082 API
  active，通用 provider-native timer 为 `enabled/active`。`71b7890928a9cc8c6345f41b0cd87a60f46158f8`
  仍保留为已验证的 500-symbol 候选/rollback 对象，但不再挂载到正式 18082。
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

## 第二批非开盘接口（已合入并预构建，当前未挂载）

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
