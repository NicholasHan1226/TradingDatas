# TradingDatas 当前状态

最后更新：2026-07-30 15:30 CST。

## 当前运行面

- 正式 A 股 API：`tradingdatas-v1-internal.service` 为 active，固定只读接口仍是
  `GET /v1/catalog` 与 `POST /v1/query`（loopback `18082`）。
- 正式 immutable `current`：`5ac3925c3931a81132ea02abb16f9745033fb6dc`；18082 API
  active，通用 provider-native timer 为 `enabled/active`。`a42e66277aa7bbfa284fb7afdef980a4ba95386d`
  仍完整保留为 500 候选 release，不再是 production current。
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
- 该问题的隔离修正候选为 `8d18b5cffa06fd7af979d1962cb7b94c01f61794`（仅候选分支，未合入、
  未部署）：保留 `fanout_field` 并要求每个请求值恰好一次，同时以 provider 的真实 bar time
  生成 snapshot watermark。候选在独立 SQLite 上完成一次收盘后 5×100 的 500/500 同一 15:00
  bar、5 个 success receipt、8.5 秒采集；候选 API 对已过 SLA 的历史 bar 诚实返回 stale，
  没有宣称 live-ready。仍欠下一交易时段两根相邻的真实 500/500 证明，之前禁止再切换生产。

- 2026-07-31 10:15 与 10:20 CST 已在**隔离** 500 candidate SQLite/loopback API 完成新的
  两根相邻 live 验证：每根均为 5 页 × 100、500 个唯一 `ts_code`、单一 provider bar time、
  5 个 success receipt，且以 `tradingagent` 身份精确 `time eq` 查询得到
  `ready/success/fresh/valid/non-degraded`、完整 receipt/lineage 与一致重放。候选读侧另以
  `10e0bbb3` 修复 provider 本地分钟 watermark 的严格时区规范化；10:20 前的一次上游 0 行
  `validation_failed` 已保留在隔离 evidence，未影响 30-symbol production。此结果仅解除
  candidate 数据门禁；formal 18082 仍为 `5ac3925`/30，须在 TradingAgent 500 consumer 会话
  门禁确认后才可受控切换。

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

1. 先确认现行 30 只分钟链重新出现真实 completed bar；若继续缺失或 metadata degraded，
   保持 fail-closed，不手工补分钟事实。
2. 仅在确定上游实际可提供当前 completed bar 后，重新在隔离 500 候选取得两根相邻完整
   500/500 readback；两轮均通过后才重新申请 production 切换。其它 Tushare dataset 仍按各自
   registry 合同和 receipt/metadata 验收，不因本次切换自动晋级。
3. 当前不扩公共 API、不新增专用采集器，不把已 active、paused 或单次成功说成“全部接口已稳定采集”。

历史候选、事故、旧端口和早期探测结论以 Git 历史与服务器 evidence 为准，不再保留在当前状态页。
