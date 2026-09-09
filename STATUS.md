# TradingDatas 当前状态

检查日期：2026-09-09，Asia/Shanghai。当前事实入口；实际数据权威仍为registry、SQLite facts/receipts及读取时钟。完整证据见[本轮验收](docs/reports/2026-09-09-release-session-and-minute-readback.md)。

## 代码、发布与官网

- PR543–545已合并，运行实现版本为`8612c625eea98262aaa0c127345e2650836c2c8f`；精确main CI [34318423833](https://github.com/NicholasHan1226/TradingDatas/actions/runs/34318423833)四组成功。新增/相关检查：site323项、分钟组合94项、发布/manifest独立67项通过。
- 新`safe_release.py`统一合作发布的目录锁、精确CI与真实catalog采样、排空、actor/task审计、失败回滚及原状态恢复，已current/保守纯文档变更跳过。项目入口、CLI和运维文档已在新agent上下文核对，不代表桌面新任务实际加载。
- **外部发布入口尚未收口。** 双pointer在14:27:47/49由其它过程切换，早于main CI完成。本任务14:32使用新入口时只执行了verified skip；不能追认原切换的CI/排空门禁。SSH会话129385与时段相关，但没有命令审计可确定具体工具/操作者；已排除当前td-admin-autodeploy。root任意手工调用不受合作目录锁约束。
- 切换后的独立检查：1105文件manifest、双current和API物理cwd匹配8612；新进程cold3.039/9.701秒，同面并发最慢11.100秒，均200、192/240项且无下一页，低于内部catalog15秒门槛。源码副本由本任务从干净684同步到8612并保留Git bundle。最终运行读回见下方15:10快照。
- 官网PR543经Cloudflare [34317462732](https://github.com/NicholasHan1226/TradingDatas/actions/runs/34317462732)发布，五个公开路由及新JS字节匹配。账户权限暂不可确认时可正确重试；empty/degraded保留真实含义。既有内部read consumer经公网catalog/query已200（目录17.435秒，日历1行查询1.303秒），不替代真实客户账户端到端验收；客户已有登录身份仍待用户选择，未创建key或提升权限。

## 分钟查询与观察边界

- rt_min_daily major3按既有有限窗口支持精确time/proof；真实2026-09-01 09:30 slot早于receipt through，plain/proof内容一致，三页共3行的自有receipt、行身份与时间约束通过，仍有下一页，不证明全历史完整。
- rt_min major2保留同质snapshot约束；真实14:35首行plain/proof通过。盘中分页出现503；同槽一次独立新进程诊断首/二页均可读，尚不能确定原503原因。收盘后API复核：真实15:00 slot连续三页普通/proof请求均200，3行内容、身份和回执校验通过，无重复且仍有下一页；原503原因仍未定位。
- 同口径新进程cProfile观察26.303→12.773秒，均rt_min/major2/limit5/no-proof；full receipt/binding权威仍完整校验。缓存、SQLite耗时和数据量不同，不声明严格提速倍数或全部query低于15秒。
- 10:51–13:56有效receipt观察：rt_min19success、rt_min_daily10success、global.news.flash3failed/provider_error。午休、交替not_due与minute reservation有日志解释；11:20有SIGTERM中断。部分旧巡检失败仍未查清，不能把单次成功或journal当作全天/长期稳定证明。

## 本轮有界采集与最终读回

三项使用20260908明确窗口、同release无写计划、无同窗receipt与有效seed验证；10000预算不变，38个paused不动，由唯一collector在分钟预留结束后执行。

15:07批次实际完成：bak_daily新增5567行、dc_member新增14行、fund_manager新增18行；均1个success receipt、0 rejected，回执窗口和当前config校验通过。dc_member仅使用既有单seed，不证明全板块覆盖。唯一collector退出0，一次性selector和manifest已消费，timer恢复enabled/active。15:09对应窗口plain/proof各一次认证query均200，行内容一致、回链本次receipt且lineage complete；每次limit1并仍有下一页。quality均如实为degraded（freshness_watermark_unverified、response_completeness_unverified），不声称完整或新鲜。

15:10双current、API物理cwd和1105文件manifest仍匹配8612；匿名均401，认证catalog为192项/4.220秒和240项/8.854秒。A股状态107success、41empty、38paused、4stale、2failed；Crypto240success。九个timer均enabled/active，selector不存在、临时API停止；源码副本8612干净。此后纯文档交付按PR/CI及主线源码同步验收，不创建新runtime release。

fund_company已观察15371行超硬预算，继续暂停；合法empty、provider_error、stale与partial分别保留，不为得到success追采或伪造完整性。Crypto保持内部独立运行，不纳入公开菜单与套餐。

## 本地与历史保留

本轮三个已合并实现工作树已通过git worktree move归档，分支与ignored文件保留；本地synthetic QA服务已停止。先前原脏目录、stash、数据库/WAL备份、旧release和证据继续保留，未重复合并历史patch。上午四项修复和七项batch/基金重观测见[上午恢复记录](docs/reports/2026-09-09-runtime-recovery-and-collection.md)，不以旧快照代替本轮读回。

长期入口：[API](docs/API.md)、[架构](docs/ARCHITECTURE.md)、[运维](docs/OPERATIONS.md)。未涉及真实交易、资金、权限扩展、支付或客户开通。
