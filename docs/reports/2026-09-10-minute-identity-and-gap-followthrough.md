# 2026-09-10 分钟 identity 校验与缺口跟进

时间统一为 Asia/Shanghai；9月9日晚的观察不写作9月10日运行。当前事实入口为 STATUS.md，长期合同以 OPERATIONS.md、API.md 为准；数据权威仍为 registry、SQLite facts/transaction receipts 与读取时钟。

## 范围与当前边界

本轮包含自然采集及有限日志审计、两个失败数据集的证据调查、分钟查询最小性能候选、有界缺口采集和已有客户登录验收。保持固定 catalog/query、10000预算、38 paused；未授权扩展 schema/index、worker、timeout、权限、凭据、activation、cadence 或自动化。开场双面 runtime 为 `1edd16fa5860715b0e4cb0eabf16d406d307fb2c`；源码/主线与 runtime 分开记录。

## 已取得的运行证据

9月9日23:41和23:50两轮日志合计35 success、10 empty、1 failed。这是两轮终态 dataset-attempt 数，不是唯一数据集数或行数；23:31:05的10 success/6 empty早于cut，不计入新版本自然轮。使用完整 MESSAGE 的 `runtime-diagnosis-complete.jsonl` 替代首次不完整日志提取；有限API日志未见新异常，不能证明间歇503永久消失。

新闻 `global.news.flash` 最新receipt `93e124dc15ca0dfdd194a2f58fb915186f160d324b245882947545757373cbea` 对应23:32:11–23:41:12，journal明确记录 Firecrawl HTTP500，receipt为 `provider_response/provider_error`，returned/validated/rejected/committed均0。只能定位至该上游响应层，不能断言新闻网站根因或认证错误。23:50无失败摘要不表示新闻恢复；同一历史execution中的部分success receipt也不把failed cohort变成成功。未主动重采新闻或修改重试/凭据。

23:51完整catalog快照：A股192项，111 success/37 empty/38 paused/4 stale/2 failed，耗时17.202秒；Crypto240项均success，耗时6.523秒。A股该次读取超过15秒，不是重新执行当前release gate，也不推翻此前已取得的cut证据；Crypto只是该时点未见失败。两面均 `recovery_verified=false`，不能宣称持续稳定。

## 历史失败与下一seed调查

初查时，`etf_mins`仅有9月6日两个历史failed receipt，目标9月4日、index0；不能写作本次发布新增失败。当前参数形状与官方文档一致不证明QuickSync权限。经source receipt验证，同一 `158003.SZ` 存在P与L两条来源记录；这属于来源状态冲突，不能凭单条P断言当前未上市，也不能凭L保证分钟数据可用。排空后9月8日新窗口index0已真实执行，仍为failed；同一Invocation日志给出QuickSync provider_code20002，表示该代码不被分钟接口接受。未额外重试请求、改码或变更universe。

`fut_holding`在9月8日窗口的index0/1均为empty。source receipt证明index0 `A` 生命周期未知，index1 `A0001` 于2000-01-18到期，下一index2 `A0003` 于2000-03-14到期。下一seed为历史到期合约，本轮停止继续该项请求，仅保留诊断；不跳选seed、不修改universe或伪造非空。这个结论仅覆盖已核对seed，不能宣布整个数据集无有效标的。

预检查另列9月8日窗口 dc_concept_cons index106/638、etf_sz_cons120/3073、fund_daily106/3073、fut_wsr2/98。index为零基；排空后再次核对完全相同，已各执行一个seed；零基index不是已完成次数或全量覆盖证明。

## 分钟 identity 候选

候选只在单次projection pass内缓存最多256个成功request_identity验证结果，以完整canonical JSON为键，保留primitive类型、cursor及所有字段；不跨快照，不跳过receipt/cohort/config/时钟/proof/预算校验。

同一verified snapshot的ABBA使用14,600条receipt，完整projection结果一致。baseline为5.179769/5.088669秒、各14,600次identity验证；candidate为4.202519/4.212493秒、各37次。该测量证明局部projection收益，不代表完整扫描或HTTP请求等比例提速。内存exec后共享globals，但旧projection不传identity cache，基线仍逐次验证。ABBA测量候选hash为 `08ffaee06e5bfbd98106d51d45082be1e606a8f23f0cdfa07ab6d1c4223318c3`。

最终代码仅另补类型注解，不改变测量行为。本地相关回归343项通过，独立7项测试通过；不替代GitHub CI或生产验收。PR #554 head95be435ad943660b809e45bd295aae5c82a62222 CI34374127156通过，合入150d8c9fc16209ea0163b8cd2e9d07064e90ef1a，精确main CI34375282630通过。本地/服务器源码均干净同步；现有只读deploy key fetch成功，无需bundle回退。

## 执行与验收结果

- **有界采集**：9月10日00:16:27–32，Invocation0f6d3ec9ad9e4e2aa08e287342d211ba；dc_concept_cons success，新增60行；fut_wsr success，新增4行；etf_sz_cons/fund_daily两项empty，各0行；etf_mins一项failed/provider_error，0行，共64新增行、5新回执、0rejected。collector退出4且batch impaired，控制会话完成不等于全批成功。原timer已恢复enabled/active，selector及batch文件已消费，前后manifest保持1edd16fa。
- **新数据读回**：五项config/window/index/count/universe/values_hash与排空后preflight匹配，每项仅匹配一个新execution；两项success各抽1行，4次普通/proof查询200、内容相同并回链本次receipt/config/window。其余只记空/失败回执。所有样本degraded，fut_wsr缺字段如实保留；不是64行全量API验收。
- **发布**：双面各1109文件manifest、Git tree8059f29bd4dd3c566a25e7672b79d1705e0fad40与registry重编译一致。00:25新进程门禁cold A6.434/C11.777秒，同面并发A6.095/6.134、C12.654/8.563秒，完整192/240 scope及runtime字段、真实时间重叠、无cursor均验证；临时API停止且inactive。00:25:55进入唯一safe_release会话；自然排空后00:28切换双current，00:28:50认证catalog192/240项，分别2.228/8.818秒；00:28:53恢复errors=[]，00:28:54complete。没有杀collector，rollback1edd16fa保留。00:29独立运行检查双current/cwd为150d8c9f，九timer enabled/active、selector不存在、两临时API inactive。
- **分钟读回**：00:29–00:31，对9月9日14:35与15:00固定窗口各两页、普通/proof独立cursor，8/8 HTTP200。耗时17.039、10.183、9.821、9.182、9.001、8.816、9.481、9.124秒；完整分页/身份/cohort/proof时钟通过，每窗2行且仍有下一页。首次仍超过15秒，不声明永久无503或全HTTP SLA。跨日读取这两个历史窗口时API quality=valid，非新增历史数据或性能代码改变新鲜度的证明。
- **完整目录**：00:32，A192项21.869秒，102success/47empty/38paused/3stale/2failed；C240项6.492秒、240success，精确scope/runtime字段与catalog版本通过、前后manifest/current/cwd一致。A仍有延迟波动；发布门禁与之后负载下时点读回分别报告，不能声称持续达标。两个failed是etf_mins/global.news.flash。
- **major_news观察**：staged时出现failed，00:32目录已变empty；验证的最新execution4483a6dd-e759-4e00-8772-9e125222a73d:schedule-plan:000000000016开始00:16:40、结束00:25:53，目标9月10日，最新receipt90dccc57e68a1e2a048934a681fcc47b8df9e322afa7538993b77fc1bd655945为empty0行。没有匹配的独立major_news错误日志，未进一步断言旧失败根因；新空回执不算恢复非空供数。
- **客户**：浏览器仍为guest，缺已有客户登录；客户授权目录、复制请求及客户key端到端未验收。没有新建账户/key、提权或开通支付。

本机证据目录：`Documents/Codex/2026-09-09/TradingDatas-postrelease-followthrough/`，主要文件为 `runtime-diagnosis-complete.jsonl`、`receipt-investigation.jsonl`、`catalog-opening.json`、`next-seed-preflight.jsonl`、`identity-abba.jsonl`、`identity-tests.log` 和后续执行读回记录。本报告为日期化证据，后续运行事实回到STATUS和实际runtime核对。纯文档交接只同步主线/源码，不重复部署。
