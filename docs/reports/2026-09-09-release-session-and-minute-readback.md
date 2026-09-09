# 2026-09-09 发布会话、分钟查询与限量采集验收

事实入口：STATUS.md；长期合同以API.md和OPERATIONS.md为准。本报告不把代码合并、实际切换、生产读取、客户账户或上游完整性合并成一个完成状态。时间均按Asia/Shanghai解释。


## 17:21更新：PR #548 已受控部署

本节是最新运行证据，优先于下文15:10及此前的历史快照；下文“发布者未定位”等描述仅保留当时调查状态，不能视为当前结论。

- 发布协调：已通过Grok Bot的Johnny消息与服务器指针时间、旧手工脚本对应，定位14:27的8612、15:34的44247及15:54的35f56重复发布。用户授权后，16:51:50发送暂停自动补发和接管#548通知；16:52:27 Johnny确认`tradingdatas-gz-deploy-after-merge`已禁用，没有其它发布任务或进行中的切换，保留采集timer及在运行采集，等待明确交接。未修改SSH权限；不追认早期切换为符合新门禁。
- 代码：PR #548精确head `d7732a8e62e7ef03846b1d2f27b6cf67ddc08518`，PR CI [34331348663](https://github.com/NicholasHan1226/TradingDatas/actions/runs/34331348663)四分片成功；实际merged `f2f5cb2a575f2981d836f9ee7790579614e8a80f`，精确main CI [34332481416](https://github.com/NicholasHan1226/TradingDatas/actions/runs/34332481416)四分片成功。完整本地API测试184项、独立新增5项、Ruff/diff及最终差异复核通过。
- 诊断范围：仅现有CursorConfigurationError、QueryServiceUnavailable、RuntimeProjectionError转换为503时增加安全WARNING，记录服务端request_id、固定类别、白名单项目代码行和有限异常链。公开响应和authority保持；不记录异常原文、locals、请求、cursor、密钥或payload。未在生产注入故障；本轮没有复现原503，不能宣称根因修复。
- 发布包：双面各1106文件以已信任物理verifier引导验证，commit/tree/manifest绑定一致，registry重编译一致。manifest SHA256为`617acc752d84bce704dfd9087693cacd44b17f5349a648d5b27d29fbb3ee4b01`。源码从干净35f56同步至f2f5cb2a并保留Git bundle。
- 切换前实测：17:09:43起新进程A股cold3.939秒、Crypto cold12.059秒；同面并发A股4.342/4.341秒、Crypto11.540/8.205秒，全部认证200、192/240目录、无next_cursor。PID/物理cwd/registry绑定和实际采样时间均记录于root0600证据文件；临时API随后停止。
- 会话：17:15:50取得双release目录锁，17:15:57验证精确CI与staged evidence；暂停后续timer，等待在运行collector自然排空，没有杀collector。17:19:06.710/07.165分别切换A股/Crypto。actor=`Nicholas-Codex`，task_id=`01a083d1-5dfa-7743-afa2-c66a83dff756-pr548`。17:20:02认证catalog192项/2.262秒、240项/8.839秒，17:20:05恢复原units且errors为空，会话complete。回退版本35f56e07156be97851ed85821b5955d697f2feb2及manifest保留，没有覆盖SQLite。
- 独立运行复核：17:20:49双current/API物理cwd/各1106文件均为f2f5cb2a；A股PID4118293、Crypto PID4118908；匿名均401、认证200，无next_cursor，192项/4.641秒及240项/7.559秒。A股105success、43empty、38paused、4stale、2failed；Crypto240success。九个采集timer恢复enabled/active，on-demand selector不存在，临时API停止，源码f2f5cb2a干净。这是时点观察，不是完整性或长期稳定证明。
- 真实query复核：17:21:17–18，bak_daily/dc_member/fund_manager的20260908窗口，各一次plain与proof共6次请求均200、每次1行且仍有下一页，约0.121–0.151秒；普通/proof行内容一致、各一个proof并回链15:07已记录的各自receipt，lineage complete。quality仍为degraded，freshness_watermark与response_completeness未验证；不声称完整或新鲜，未再次执行provider采集。

完整安全证据保存在本机`Documents/Codex/2026-09-09/TradingDatas-followup/`，包括publisher-pause-ack、精确CI JSON、staged-manifests、staged-catalog-measurements、`f2f5cb2a575f2981d836f9ee7790579614e8a80f-diagnostics-session.jsonl`、final-runtime及query-readback。服务器会话审计为`/var/tmp/td-audit-20260909/release/f2f5cb2a575f2981d836f9ee7790579614e8a80f-diagnostics-session.jsonl`。

后续本报告和STATUS纯文档变更只做PR/CI与主线/源码同步，不重复GZ cut；运行验收版本固定为f2f5cb2a。真实客户登录/授权目录/key端到端与原503根因仍未验收，官网无本轮前端变更且未重新部署。

以下各节为15:10及此前历史证据，不代表最新pointer或当前发布交接状态。

## 已合入实现与检查

- PR543，head 2f1051ae，merged 7bfa1911：账户权限暂时无法确认时显示可重试错误；重试先重新验证现有账户，再读取授权目录。323项site测试、构建、中文/英文及键盘重试、桌面/390px手机实际浏览器检查通过。
- PR544，head ace2992a，merged 7ca51471：按既有有限分钟窗口校验rt_min_daily精确时间与逐行proof；保留行自有receipt、当前provider/config、完整cohort及单页约束。每次投影只计算一次完整binding内容指纹，仍以完整raw receipt和binding内容构造memo key。94项组合测试、26项memo测试及独立16项新增测试通过。
- PR545，head b5f85ceb，merged 8612c625：双release-root目录锁覆盖完整受控发布会话，真实采样/CI时效、actor/task审计、失败回滚与原服务状态恢复。独立67项release/manifest测试通过；复核发现并修复了新envelope可包装过旧采样的P1。
- 精确main 8612c625eea98262aaa0c127345e2650836c2c8f的CI34318423833四组成功。各项Ruff或构建、diff检查通过。新agent上下文完成四层规则发现及CLI/docs一致性检查；不代表桌面新任务实际加载。

## 实际发布与来源限制

目标两面均1105文件，Git tree/commit、manifest及registry重新生成核对通过。但本任务14:32:49进入safe_release后发现目标已经current，实际路径是skip_already_current，没有执行重复cut。

两面pointer实际在14:27:47/49改变，API14:27:49启动，早于该main CI完成及本任务的新进程测量。root SSH会话129385（sshd PID3803834）从14:27:40至14:28:13覆盖该时段，使用既有已知密钥；仅有时间关联，缺少命令审计，不能确定具体工具、子进程、操作者或本地任务。A股前轮已正常完成；当时Crypto USDM已有运行轮次，未证明全部collector排空。当前td-admin-autodeploy仅操作/opt/td-admin，已排除该入口。

本机Codex可见任务中仅本任务活跃，未找到TradingDatas Codex automation、LaunchAgent或hook。不能把这些有限排查当作已排除所有外部发布过程。新工具已提供合作发布互斥、显式证据与审计，但不约束root手工改链、旧工具调用或伪造证据；外部发布入口尚未完成归因/收口。已向用户询问其它持续发布任务，不修改SSH权限或任意停止未知任务。

14:31–14:32的独立新进程测量发生在实际cut之后：冷catalog A股3.039秒、Crypto9.701秒；同面并发A股6.953/6.928秒、Crypto6.535/11.100秒。均200、完整192/240目录、无next_cursor、低于既有15秒门槛。这是切换后独立检查，不能追认为原发布的切换前门禁。

14:35独立运行回读：current、API物理cwd及1105文件manifest均为8612c625；匿名401，认证catalog A股3.623秒/192项、Crypto7.405秒/240项。九个既有采集timer均enabled/active，一次性selector与临时API已清除。源码副本随后由本任务从干净684c9480同步到8612c625，保留可验证Git bundle；无ignored原件变化。

## 真实分钟读取及性能边界

rt_min_daily major3已在真实历史slot 2026-09-01 09:30:00通过plain/proof行内容一致、append-only身份与窗口/through/finished/read-clock校验；slot严格早于receipt.data_through。独立cursor的三页共3行均通过、无重复、仍有next_cursor，不能声称全历史完整。回链包括3de22e9734c0d496d62fc92fa69483741308da3900ffabfa382bb35db6a44500与cd132ed741faa52ae6b18ca5d02458c5f686d9612a2a15bc8dd38db963d16efa。

首轮出现一个未定位原因的503，后续选定窗口通过不证明所有历史行都具备proof。验收脚本还曾错误地对append_only使用primary-key身份，导致断言失败；已按真实存储合同改用canonical payload hash，未修改生产校验。原失败记录保留；早期日志candidate_slots_tested误记为可选slot数，实际请求数以逐条HTTP记录为准，脚本已修正计数。

rt_min major2的14:35实际slot首行plain/proof通过，保持event==through；盘中后续cursor返回503，不能冒称分页已验收。独立新进程、真实服务用户同一14:35 slot的单次诊断首/二页均通过（17.138/10.368秒），没有复现503；不能据此归因数据库忙、receipt变化或authority失败。收盘后再次通过真实HTTP校验15:00 slot：首行与后续两页的plain/proof共6个请求全部200，约9.736–11.004秒；三行内容一致、无重复，row identity及event==through通过，仍有next_cursor。回链0c29e4d3d9bd22b07c9f0206128c3627319a7ce6d15d4160cae66f4fec20f5ba，前后1105文件manifest/current/API物理cwd仍匹配。该次分页通过不解释或抹去盘中503，也不证明全市场或全部历史分页完整。

相同rt_min major2、limit5、关闭proof、服务用户、新进程cProfile：684基线26.303秒，8612候选12.773秒，均5行且有下一页。receipt memo累计15.363→7.727秒；实际验证调用14250→14510，未减少authority扫描。SQLite execute自耗8.348→2.362秒也发生变化，因此不能把全部改善归因于代码或声称严格提速倍数。另一次真实HTTP默认查询15.380秒，精确首行约9.5秒；15秒发布门槛针对catalog，不是所有query的性能保证。

## 官网与实际客户端

Cloudflare发布34317462732成功（官网版本7bfa1911，后续Python变更不改官网bundle）。五条公开页面读回新资源；JavaScript SHA256 4f1673e3e341e978e79a2e15031614eca1c5acb572edb86f3d46f3db8da83256与本地构建逐字节一致。实际浏览器生产详情页仍为未登录状态，未显示授权目录。

通过现有内部read consumer访问公开固定API：匿名catalog401；认证catalog200/192项/17.435秒；明确日历窗口query200/1行/1.303秒，quality valid、lineage complete、回链4518fc98d29c074990fc93df3fcc553e28a9fa92c32e1a667a90148666da59da。公网17.435秒不能被内部双面<15秒读回掩盖。该身份不是客户账户，不替代客户登录、授权目录、复制请求及其已有key的端到端验收；相关身份选择仍待用户答复。没有新建账户/key、提升权限或写入客户数据。

## 有界采集与连续观察

三项候选为bak_daily/dc_member的trade_date=20260908及fund_manager的ann_date=20260908。已验证交易日历上一开市日、同release无写计划、无同窗receipt和既有dc_index单seed authority；预算10000不变，38个paused不动。15:05窗口结束后暂停后续timer，等现有15:05轮自然完成；在8612同一release目录共享锁下，由唯一collector使用一次性selector执行。Invocation e42f7fbe52a74e298ef9e57fdac76558于15:07完成，退出0；bak_daily返回/新增5567行，dc_member返回/新增14行，fund_manager返回/新增18行，均0 rejected、1个success receipt。实际回执分别为7a24f14919adf2bdfebb165da22e3740469c2fdf901bcdd4852c27da0ea8ffb3、03db511644e12e9215a5b5ee36a46154f244e591737e17e7a585716f1ee7abf4、4ca0d586b54260777d3c15dfc5bad050dde3fad4966e951b1927028403b6ef32；通过同窗口/current config完整校验。dc_member仅是既有单seed的观察，不证明全板块覆盖。一次性selector/manifest已消费，timer恢复enabled/active。15:09对应窗口plain/proof各一次认证query均200，行内容一致、回链本次receipt且lineage complete；每次limit1并仍有下一页。quality均如实为degraded（freshness_watermark_unverified、response_completeness_unverified），不声称完整或新鲜。

连续运行只读观察10:51–13:56 receipt：rt_min19次success，rt_min_daily10次success，global.news.flash3次failed/provider_error，cn_schedule/stk_holdernumber各2次success；etf_mins是on_demand，0次不代表漏跑。13:05–13:55已完成11轮journal均成功，但最后一轮晚于receipt截止，未混算。午休、交替not_due和提前50分钟minute reservation均有调度解释。

11:20轮实际被SIGTERM终止，无有效分钟receipt；10:51边界有SIGTERM，11:50–11:54轮有SIGKILL，未归因操作者。新闻失败轮耗时约8–11分钟，不能把跨过的每个唤醒时刻简单算成漏调。独立collector-watch仍保留09:07的exit1旧记录，具体原因未核实；未据此推断当前API失败。观察不是全天、全市场完整或长期稳定证明。

## 最终运行回读

15:10双current、API物理cwd与1105文件manifest仍为8612c625。匿名均401，认证catalog A股192项/4.220秒、Crypto240项/8.854秒，无next_cursor；A股107success、41empty、38paused、4stale、2failed，Crypto240success。九个timer均enabled/active，一次性selector不存在，临时API停止。源码8612干净。此后本报告与STATUS的纯文档交付只走PR/CI及主线源码同步，不创建新immutable release；运行实现仍以8612为验收对象。

## 证据与保留

本轮外部证据目录为Nicholas工作目录Documents/Codex/2026-09-09/TradingDatas-next-execution：CI/manifest、release-session审计、release-attribution、catalog测量、分钟查询/profile、公网资源/API读回和continuity报告。输出仅保存安全元数据；真实token、客户响应及provider payload不进入仓库或静态产物。旧原件、stash、数据库备份、历史release与归档均保留。本轮三个已合并实现工作树通过git worktree move移入既有Finance-worktrees归档，ignored文件保留；本地synthetic QA服务已停止。
