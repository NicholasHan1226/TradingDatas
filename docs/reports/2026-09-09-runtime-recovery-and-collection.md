# 2026-09-09 运行恢复与有界采集验收

本记录是日期化验收快照；当前入口为 [STATUS](../../STATUS.md)，长期合同为
[OPERATIONS](../OPERATIONS.md) 与 [API](../API.md)。时间采用 Asia/Shanghai，明确标注UTC的审计除外。

## 冻结范围与版本

本轮覆盖本地遗留工作、A股运行故障、分钟状态读取成本、失败前缀重观测、合法空窗口proof，
以及七项既有active/on-demand绑定的有界采集。未提高10000硬预算、批量解暂停、增加公共路由，
未触碰真实交易、Token/权限、支付或客户开通。

| PR | 问题与验证 |
|---|---|
| #538 | 合法部分checkpoint被mtime误拒绝；240项projection回归通过，salt篡改仍拒绝。 |
| #539 | 按所选active dataset与依赖加载状态；175项完整schedule测试及9项最终针对性回归通过。 |
| #540 | 显式失败execution前缀经真实相同payload重采后原子重绑；63项针对性回归及独立12项测试通过。 |
| #541 | 仅允许binding合同合法的空窗口proof；99项组合回归、1项非空历史兼容回归及独立10项测试通过。 |

各候选Ruff/diff检查和独立审查通过。最终运行代码为
`f543f7eb71fb4234a62dbead42524069aa6793ce`；PR CI与精确merged-main
[CI 34305906019](https://github.com/NicholasHan1226/TradingDatas/actions/runs/34305906019)分别通过。
本记录与STATUS是纯文档收尾，不要求再次切运行版本。

## 数据库与本地原件保全

A股原先认证catalog503、collector约2秒失败，定位为mtime误拒绝合法SQLite WAL状态。
在停止A股API/timer、collector空闲并持有独占authority lock后，保全主库18,464,755,712字节
及WAL/SHM一致副本，逐项SHA-256匹配。`quick_check(10)=ok`；受控
`wal_checkpoint(TRUNCATE)=(0,0,0)`，journal mode仍为WAL。恢复前后135028条receipt与最新
finished_at不变。声明代码无字节漂移，25个额外pyc/7个缓存目录按精确路径与哈希保留后移出。

原库和收据证据在服务器私有 `/var/tmp/td-audit-20260909/`，不得作为新数据权威或直接覆盖
当前数据库。回滚保留旧release，不反向恢复数据库以抹掉本轮新事实。

本地原主目录8文件改动有stash、patch、tar、哈希清单和独立Git bundle；4份dirty patch均在
原HEAD的独立index通过apply check。32个已合入worktree正常移除，ignored原件/evidence保留。
三个旧脏worktree经792 passed/1 skipped及语义审计确认已被主线覆盖，整体归档后哈希一致，
没有重放旧patch或重复合并。本轮实现worktree亦归档，分支及14个旧release暂存worktree保留。

## 切换过程与独立运行读回

本任务完成9da的排空、切换与timer恢复；随后发现并行root SSH会话126926执行2cac切换：
UTC 02:51:18.526988与02:51:21.021883分别调用双面switch-current，02:51:23.617513重启双API。
审计login uid=0，非marketgraph嵌套提权；td-admin-autodeploy可排除。该中间切换早于main CI完成，
且A股前轮collector尚在运行，不能补写成已通过本任务preflight。具体操作者/本地任务未归因。

最终f543也在本任务准备阶段由并行过程创建并切换；本任务没有重复切回或覆盖。此时精确main CI
已经通过。完整上传后的tar SHA-256为
`d2463671681fb0daea8d3cbe2f1ee37a318af17c50e2f46790423042a5904725`，与本地一致。
两面1098文件manifest、Git tree `68f6b21c3b59a67fe1e137cd7faa76c9f28b5380`及API物理cwd均匹配。

最终新进程验证是在实际切换后执行，不冒充由本任务完成的切换前门禁：

- dual authenticated cold catalog：A股3.089秒、Crypto9.891秒。
- 同平面并发：A股4.742/4.749秒，Crypto6.845/9.375秒。
- 11:24实际运行API双认证回读：A股2.457秒/192项，Crypto5.463秒/240项，均HTTP200；匿名均401。
- 九个既有采集timer恢复原enabled/active状态；一次性selector/manifest均不存在，临时验收API已停止。
- 源码副本由干净12fd4097同步至f543，原refs Git bundle验证通过；当时无ignored文件。源码与最终
  文档主线的后续同步由Git读回单独记录，不把source HEAD当运行权威。

## 采集、查询与停止线

同release no-write plan后，唯一collector执行7项batch：cb_rate 3、ci_index_member 2、fund_adj 1、
index_member_all 2、stk_rewards 6000、top10_holders 2897行success；cb_rating为0行empty。
合计8905 returned、90 inserted、8815 unchanged。fund_adj的20260908窗口由真实交易日历确认开市。
使用原registry fanout源和max_batches_per_run=1，不固定探测seed或抬预算。

最终六项默认认证查询均非空，单行proof均200且证明数量与行数一致；cb_rating默认/proof均200空页。
单行页用于遵守既有单一execution/window/config/data_through限制，不意味着跨cohort整页proof被放宽。

fund_basic真实E-only重采2887行，其中2880 unchanged、7 inserted、0 rejected/updated。
原2884事实的identity、schema major、payload hash与revision均保持；2880条旧失败前缀重绑到新
成功receipt `123660cc0231325bfc336d5f511b707bdde9de83ab1aed84354d1f943ffadeba`。
未重观测到的4条旧前缀保留并排除，物理coverage2891不同于当前可供数2887。
六页认证query（500×5+387）核对2887个不同row identity，全部proof绑定上述新receipt，
无重复、无缺页、lineage complete。此验证只覆盖本地当前事实，不证明上游完整性或历史PIT。

新规划器对生产DB的只读计划耗时77.47秒，两个非零分钟计划，未调用provider/写业务DB。
11:00真实timer轮次73.018秒，rt_min success、无失败。不同负载不计算严格提速倍数。
rt_min精确已验证时间槽默认/proof均200，默认5行、单行proof完整；本次请求耗时约26–28秒，
不能把catalog的15秒门槛扩写为所有query的性能保证。

rt_min_daily的schema3使用windowed_unique_primary_key且snapshot_field=null，不满足既有分钟
proof/精确槽位要求的snapshot_field=time。默认filters={}、关闭proof可读（本次stale），
相关proof/精确time请求仍503。只读复核定位到原minute入口guard，非本次empty-window修复回归；
本轮不移除该guard或宣称此能力已交付。

11:24目录快照为A股106 success、43 empty、38 paused、3 stale、2 failed，Crypto内部240 success。
保持empty、partial、stale和vendor错误的真实标签。fund_company 15371行超10000预算继续暂停；
其它暂停项不批量恢复。不存在从HTTP200、目录数量或一次成功推导全量/持续稳定的结论。
