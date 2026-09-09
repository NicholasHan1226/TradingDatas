# 2026-09-09 发布会话、分钟查询与限量采集验收

事实入口：STATUS.md；长期合同以API.md和OPERATIONS.md为准。本报告不把代码合并、实际切换、生产读取、客户账户或上游完整性合并成一个完成状态。时间均按Asia/Shanghai解释。

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
