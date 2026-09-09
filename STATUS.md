# TradingDatas 当前状态

检查日期：2026-09-09，Asia/Shanghai。当前事实入口；实际数据权威仍为 registry、SQLite facts/receipts 及读取时钟。详细证据见[本轮验收](docs/reports/2026-09-09-release-session-and-minute-readback.md)。


## 23:57 更新：部署后跟进与分钟身份校验候选

当前候选仅在单次dataset projection内最多复用256个完整request_identity的成功验证结果；完整canonical JSON键保留primitive类型、cursor与全部字段，坏identity不缓存，receipt/config/cohort/时间/proof和读取预算保持。未改变API、schema、索引、worker、超时、registry或权限。

当前生产仍为1edd16fa。只读同快照ABBA对rt_min的14600条receipt投影：旧5.180/5.089秒、新4.203/4.212秒，identity验证14600次降至37次，完整projection相等、DB零修改、前后manifest通过。该局部步骤约省0.93秒，不是全HTTP延迟提升18%的证明。既有sibling合批实验仍不包含。

23:51完整认证catalog A192项17.202秒（111success/37empty/38paused/4stale/2failed），C240项6.523秒且240success；scope/runtime校验通过，仅时点证据，A延迟仍波动。23:54已验证global.news.flash最新失败receipt对应Firecrawl HTTP500，为上游provider_response；etf_mins只有9/6历史失败，尚无本轮新窗口证明。自然调度23:41/23:50两轮终态计数共35success/10empty/1failed（非唯一数据集数或行数），23:31:05的旧版本排空轮不计新部署。有限API日志窗口未见503，不声明永久修复。

候选相关完整回归343项通过（460.21秒），最终7项新增复核通过；独立审查与独立7项测试通过，无P0/P1，基础Ruff、diff和文档链接/实际渲染检查通过。正在完成缺口驱动补采与候选发布。客户仍未登录，客户授权目录与客户key端到端未验收。所有生产发布、补采和最终readback以之后的新鲜记录为准。

## 23:35 更新：双面受控部署与分钟读回完成

PR #552 已合入 `1edd16fa5860715b0e4cb0eabf16d406d307fb2c`；精确head `7343c10b73ebb176c70464661107686911313437` CI34367011391及main CI34368235152均全部成功。该版本包含此前PR550的单快照分钟查询memo修正和本轮离线目录审计工具；未包含没有可靠收益的sibling合批实验。双面各1108文件manifest、Git tree `7281632bcb16f164c4f1fe63f807116a41594516`及registry重编译一致。

23:22–23:23同目标新进程门禁全部通过：cold A8.874/C10.517秒，同面并发A4.529/4.559、C11.501/8.517秒。每次完整192/240目录及runtime字段、无cursor、真实并发重叠与时效校验通过；两临时API停止读回均inactive。此前19时失败样本保留，当前通过不构成catalog性能修复或持续稳定声明。

23:24:00进入唯一safe_release会话，在双release目录锁内暂停后续timer并等待已有collector自然排空；23:31:08/10分别切换A股/Crypto，23:32:06认证目录192项/2.266秒、240项/8.711秒，23:32:10会话complete，原状态恢复errors=[]。没有杀collector或绕过15秒门槛，回退f2f5cb2a及旧release保留。服务器会话证据为`/var/tmp/td-audit-20260909/release/1edd16fa5860715b0e4cb0eabf16d406d307fb2c-release-session.jsonl`，actor=Nicholas-Codex，task_id末尾pr552。

23:32:53独立复核双current/物理cwd均为1edd16fa，API PID580180/581057；九timer enabled/active、selector不存在、临时API inactive，源码1edd16fa干净。独立完整认证catalog A192项/4.292秒（108success/40empty/38paused/4stale/2failed）、C240项/10.606秒（240success），catalog版本及scope一致，前后各1108文件manifest验证通过。A失败为etf_mins和global.news.flash，均provider_error；Crypto仅该时点未见失败。23:33:37双面匿名401。

23:33–23:35，部署后的rt_min major2对14:35和15:00固定窗口各验收两页，普通/proof各用独立cursor，共8次200。逐行身份、event==through、proof窗口/结束/读取时钟、同cohort、分页无重复及普通/proof相同均通过；各验证2行且仍有下一页，quality degraded/freshness_sla_exceeded。首次18.177秒，其余9.739–12.577秒，不声明所有query低于15秒；本次未复现503，不声明旧间歇故障永久修复或全历史完整。前后current/物理cwd/manifest均为1edd16fa。完整本机证据为`Documents/Codex/2026-09-09/TradingDatas-catalog-release/`的canonical-release-session、staged-catalog-measurements、catalog-postdeploy、runtime-postdeploy和minute-postdeploy。

真实客户仍缺已有登录，尚未验收客户授权目录、复制请求和客户key端到端；没有创建账户/key、提升权限、开通支付或变更官网前端。本节后的各时刻记录均为历史快照，PR550“未部署”只描述23:31之前状态。后续纯文档交接只同步主线/源码，不重复切换本运行版本。

## 22:50 更新：继续采集与完整目录审计

目录与审计组合回归89项通过，最终审计工具32项复核及完整Ruff通过；独立review未发现P0/P1。README、状态及报告已检查真实渲染。当前候选仅包含离线审计工具、测试与文档，未改变API运行路径。

22:43 双面 current/API 物理 cwd 仍为 f2f5cb2a，源码 e7e8b277；九 timer enabled/active，selector 不存在。目录 sibling 查询合批实验已完成：真实同快照ABBA分别3.551/3.335/3.698/3.622秒，完整raw结果和预算相同，但无可靠收益，因此撤回候选并归档补丁。未将实验作为性能修复发布；15秒门槛、worker、读取预算和receipt权威保持。

22:48 五项20260908窗口各续取一个真实下一seed，index分别105/119/105/1/1：dc_concept_cons新增60行、etf_sz_cons 51行、fund_daily 1行、fut_wsr 14行；fut_holding为empty/0行。五项各一个receipt、0 rejected，共126新增行。配置、universe、进度及receipt-owned facts均验证；四项success各抽样1行，普通/proof共8次200、内容一致并回链本次receipt。quality均degraded，fut_wsr还保留上游缺字段，不声称全量完整。唯一collector的Invocation为f1e6289700814f98bc25950e9db1cf4a，timer已恢复，selector已消费；10000和38paused保持。

完整离线目录审计工具增加精确scope、非空目录、runtime字段、无cursor与安全原因码校验，再输出失败身份。22:49当前runtime认证快照A192项/18.457秒：108success、40empty、38paused、4stale、2failed，失败身份为cn.dataset.etf_mins、global.news.flash；C240项/6.201秒，240success。两面完整scope及catalog版本已验证，前后manifest/current/cwd保持。此时点未见Crypto失败不表示连续恢复，A耗时也未通过15秒门槛；本读取不是staged并发发布证据。客户仍缺已有登录。

## PR #550：冷查询修正已合入，发布门禁未通过

17:47–17:49，对 rt_min 的14:35和15:00固定窗口分别验收两页普通/proof，共8次HTTP200，逐行身份、窗口和receipt回链通过，仍有下一页且quality degraded。未复现503；部署后有限日志窗口没有新503诊断，不代表旧故障永久消失。首次23.087秒，后续9.817–15.497秒。

同运行版本的只读新进程profile为22.917秒，29,221次receipt解析累计16.562秒；projection和exact-slot history各自重复校验同一历史。当前候选只在单次verified snapshot内共享既有memo，保留两次完整扫描及全部cohort/config/时间/proof校验。冷请求预计少一轮解析；暖请求的解析轮数不减少，不承诺所有query低于15秒。相关完整回归336项、独立新增2项、基础Ruff及diff检查通过；完整Ruff的27条基线问题未增加。PR #550已合入7b3e401a76e51a30d265a70397d4f8d8d90da9f8；精确head CI34342482854及main CI34343386033四分片成功。本地main与服务器源码均干净同步，双面各1106文件及registry重编译通过。生产仍为下述f2f5cb2a，未执行cut。

发布后两轮自然采集合计26 success、19 empty、1 failed（新闻provider_error）；不把empty记成成功或not_due记成恢复。真实客户浏览器仍在已有账户登录页，等待客户身份；内部consumer不替代客户端到端。18:55五项有界采集已完成：dc_concept_cons新增30行；etf_sz_cons、fund_daily、fut_holding、fut_wsr各1个empty回执、0行。全部0 rejected，目标20260908，每项仅一个seed，10000预算与38paused保持。新回执config/window/进度和counts已验证；主题成分普通/proof各200、同一行并回链本次receipt，quality degraded。四项空回执不算成功供数。selector已消费、原timer恢复enabled/active。

候选真实只读profile为18.923秒，receipt解析降为14,621次；SQLite execute自耗从1.509增至6.647秒，测量环境/负载并非严格对照，不声称整体倍速或全部query低于15秒。

19:13–19:18两次独立新进程staged验证均在Crypto同面并发失败：第一次11.234/15.352秒，第二次16.434/11.493秒。两次A股及cold请求均200、目录192/240完整；未生成合格catalog-evidence，未启动safe_release会话。临时API在finally中停止；不改变15秒门槛、worker、权限或生产服务。已保留失败记录，当前不能声明PR550已部署。后续唯一一次Crypto只读catalog方法profile为12.710秒、240项，实际回执校验21,010次/5.537秒，execution兄弟查询200次/3.447秒；未发现本分钟补丁改变catalog路径，单次方法测量不能替代失败的并发门禁。

19:23:34最终运行读回：双面current/物理cwd/各1106文件manifest仍为f2f5cb2a；匿名401，认证catalog A192项/14.663秒、C240项/6.336秒，无下一页。A为106success/42empty/38paused/4stale/2failed；C为238success/2failed。19:24:53复查脚本输出空failed筛选，但未校验240项完整范围及runtime字段，不能证明实际零失败；最近20条failed回执未能唯一匹配原两项身份，原因未定位，不能概括全部持续健康或已稳定恢复。九timer enabled/active、selector不存在、临时API已停止，源码7b3e401a干净。单次运行读回不替代上述失败并发门禁。

## PR #548：503 安全诊断发布

PR #548 已合入 `f2f5cb2a575f2981d836f9ee7790579614e8a80f`，精确 PR head CI 34331348663 与 main CI 34332481416 四分片均成功；当时本地主线及服务器源码干净同步。完整本地 API 测试184项、独立新增5项及 Ruff/diff 检查通过。

现有三个 data-service 503 异常分支增加一条 WARNING：固定类别、白名单项目代码位置、有限异常链及服务端 request_id。公开响应、读取权威和预算保持，不记录密钥、请求参数、cursor、异常原文或数据 payload。该诊断能力不代表原分钟查询503根因已修复。

**17:20 受控部署完成。** 双面 current、API 物理 cwd 和各1106文件 manifest 均匹配 `f2f5cb2a`。17:19:06/07切换，17:20:05会话 complete、恢复错误为空；回退35f56e07156be97851ed85821b5955d697f2feb2保留。切换后认证catalog为192项/2.262秒及240项/8.839秒；17:20:49独立复核为4.641/7.559秒，匿名均401，九个采集timer恢复enabled/active，一次性selector不存在、临时API停止。此前新进程cold及同面并发全部低于15秒，详见验收报告。

17:21对bak_daily、dc_member、fund_manager的20260908窗口各做一次普通/proof查询：六次均200，每次1行、仍有下一页；普通/proof内容一致、proof回链各自receipt、lineage complete。quality仍为degraded。本次只读复核未重跑采集。此后的STATUS/报告纯文档PR只同步main与源码，不切换已验收runtime。

## 发布交接

已定位此前重复切换来自 Grok Bot 的 Johnny/TradingDatas。16:52:27 Johnny 实际确认关闭 `tradingdatas-gz-deploy-after-merge` 自动补发任务，没有其它发布任务或进行中切换，将 #548 交给当前任务，保留现有采集并等待明确交接。未修改 SSH 权限。旧手工脚本和早期切换不能追认为符合当前门禁；后续常规发布使用 `tools/safe_release.py`。纯文档仅走 PR/CI 和源码同步，不重复切 runtime。目录锁约束合作工具，不构成对 root 任意操作的权限墙。

## 已有数据与未完成验收

- 15:07 有界采集：bak_daily 5567行、dc_member 14行、fund_manager 18行，20260908明确窗口，各1个success receipt、0 rejected。普通/proof API读回一致；dc_member仅既有单seed，quality仍为degraded，不证明完整或新鲜。未重跑该批采集；10000预算与38个paused保持。
- 分钟查询：rt_min_daily历史09:30窗口与rt_min收盘15:00窗口已有真实分页/proof证据；盘中503尚未定位，后续首次查询曾29.578秒，不声明全部query低于15秒或长期稳定。
- 官网PR543的发布、资源字节与内部consumer API已验证；真实客户登录、授权目录和客户key端到端仍未验收。没有创建key、提升权限或开通支付。
- 合法empty、provider_error、stale、partial分别保留；fund_company超硬预算仍暂停，Crypto只在内部隔离运行。采集事实不因CI或HTTP200被改写成完整性承诺。

## 保留与入口

原脏目录、stash、数据库/WAL备份、旧release、ignored文件和归档继续保留。早期运行快照及历史发布问题见[本轮验收](docs/reports/2026-09-09-release-session-and-minute-readback.md)，上午恢复见[恢复记录](docs/reports/2026-09-09-runtime-recovery-and-collection.md)；历史SHA不替代当前runtime证据。

长期入口：[API](docs/API.md)、[架构](docs/ARCHITECTURE.md)、[运维](docs/OPERATIONS.md)。未涉及真实交易、资金、权限扩展、支付或客户开通。
