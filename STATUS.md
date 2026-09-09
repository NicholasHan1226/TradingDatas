# TradingDatas 当前状态

检查日期：2026-09-09，Asia/Shanghai。当前事实入口；实际数据权威仍为 registry、SQLite facts/receipts 及读取时钟。详细证据见[本轮验收](docs/reports/2026-09-09-release-session-and-minute-readback.md)。

## PR #548：503 安全诊断发布

PR #548 已合入 `f2f5cb2a575f2981d836f9ee7790579614e8a80f`，精确 PR head CI 34331348663 与 main CI 34332481416 四分片均成功；本地主线及服务器源码干净同步。完整本地 API 测试184项、独立新增5项及 Ruff/diff 检查通过。

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
