# TradingDatas 当前状态

检查日期：2026-09-09，Asia/Shanghai。当前入口只记录本次可核对结果；数据来源质量、代码合并、运行发布与查询供数分别验收。

## 代码与运行

- 运行代码为 `f543f7eb71fb4234a62dbead42524069aa6793ce`，包含 PR #538–#541 的四项修复。精确 merged-main CI [34305906019](https://github.com/NicholasHan1226/TradingDatas/actions/runs/34305906019) 四组通过；主线后续仅有本次交付文档收尾。
- 双 immutable current、API 进程物理 cwd 与 1098 文件 manifest 均匹配该 SHA。11:24 独立认证 catalog 回读：A股 200/2.457秒/192项，Crypto 200/5.463秒/240项；匿名均401。
- 最终版本的独立新进程冷启动为3.089/9.891秒，同平面并发为A股4.742/4.749秒、Crypto6.845/9.375秒，均低于15秒。最终版本已由并行发布过程先行切换，本任务完成的是切换后的独立验证；不补写成由本任务完成了切换前排空与门禁。
- 九个既有采集timer均恢复原enabled/active状态，一次性selector/manifest均清除，临时验收API已停止。源码副本已从干净12fd4097同步到当前运行代码并验证Git备份；运行权威仍为current/manifest。源码及本地主线的最终文档同步另由交付时Git读回记录。
- 中间2cac切换经系统审计定位到独立root SSH会话126926；具体操作者/本地任务未归因，且切换早于该main CI完成。最终结果已独立验证，这不豁免或追认原切换流程。过程与验收见[运行恢复及采集记录](docs/reports/2026-09-09-runtime-recovery-and-collection.md)。

## 已修复的内部问题

- 合法SQLite部分checkpoint被mtime规则误拒绝，导致A股API503与collector快速失败：仅移除错误mtime推断，保留身份、侧车集合、salt、帧/回填、schema与epoch检查。独占锁下已保全18.46GB主库与WAL/SHM一致副本，SHA-256匹配；quick_check=ok、checkpoint=(0,0,0)，恢复前后135028条receipt及最新时间不变。
- 分钟选择先读取全部192项状态：改为所选active数据集及日历/递归fanout依赖，仍使用完整registry验证receipt。真实只读计划77.47秒；11:00自动轮次73.018秒，rt_min success、无失败。不同负载下的耗时不作严格提速倍数。
- fund_basic成功重采但旧事实仍指向失败execution前缀：仅真实同payload重观测允许事务内重绑，payload/revision及健康首观测保持。
- 合法空日期窗口不能附带逐行proof：仅修正该空窗口拒绝条件，required-window、foreign-provider、非空历史、分钟及单一cohort限制保持。

## 已执行采集与查询

同release no-write plan通过后，使用唯一collector执行一个七项有界batch，未提高10000预算或批量解暂停：

| 数据集 | 真实结果 | returned | inserted |
|---|---|---:|---:|
| cb_rate | success | 3 | 0 |
| cb_rating | empty | 0 | 0 |
| ci_index_member | success | 2 | 2 |
| fund_adj（20260908） | success | 1 | 1 |
| index_member_all | success | 2 | 2 |
| stk_rewards | success | 6000 | 24 |
| top10_holders | success | 2897 | 61 |

合计6项success、1项empty，8905行returned、90行inserted。七项均有当前配置receipt，unobserved清零；六项默认认证查询非空，单行逐行proof均200；cb_rating默认/proof均如实为空。单行proof用于避免跨历史采集序列的整页限制，不放宽该限制。

fund_basic另行真实E-only重采2887行：2880 unchanged、7 inserted，2880旧事实重绑新成功receipt；原2884事实的identity/payload hash/schema major/revision均保持，未重观测的4条旧失败前缀保留并排除。物理coverage2891不等于当前可供数2887。六页认证查询核对全部2887个不同row identity，逐行proof均绑定新成功receipt `123660cc0231325bfc336d5f511b707bdde9de83ab1aed84354d1f943ffadeba`，无重复/缺页；上游完整性仍未证明。

## 当前限制与本地收尾

- 11:24 A股catalog快照：106 success、43 empty、38 paused、3 stale、2 failed；Crypto内部240 success。单次快照不证明连续稳定、全部历史完整或全部查询性能；15秒门槛仅为catalog，rt_min精确时间槽的本次查询约26–28秒。
- rt_min_daily schema3默认filters={}且关闭proof时可读，本次为stale；其snapshot_field=null，不满足既有分钟proof/精确槽位要求，相关调用仍503。该能力未交付，不属于本次空窗口修复回归，不能靠移除分钟校验放行。
- fund_company返回15371行超10000硬预算，继续暂停；已有vendor empty/provider_error与其它暂停项保持诚实状态，不伪造非空或完整性。Crypto仅内部独立运行，不纳入公开菜单/套餐/供数数量。
- 原主目录8文件改动有stash/patch/tar/哈希备份；32个已合并工作树正常移除，ignored原件与证据保留；三个原脏工作树整体归档且哈希一致，旧patch已被主线覆盖，不重复合并。本轮实现工作树也归档，分支和14个旧release暂存目录保留。
- 本轮未改变真实交易、资金、账号/Token/权限、支付或客户开通；公共站/Cloudflare及消费者业务链不由内部API验收推导为完成。

长期入口：[API](docs/API.md)、[架构](docs/ARCHITECTURE.md)、[运维](docs/OPERATIONS.md)。历史快照由Git保留，本页不作为数据权威。
