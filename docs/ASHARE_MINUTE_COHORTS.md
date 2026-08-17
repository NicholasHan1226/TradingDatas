# A 股 5 分钟 cohort：事实源与扩容门

本文件只说明 `cn.dataset.rt_min` 的消费覆盖与扩容证据。它不定义交易 Universe、下单、仓位或自动化投资建议。

当前 registry authority 是冻结的 5,963 个 `ts_code`，以每批 300 拆成 20 个 batch；cursor
contract v2 每轮最多选择 20 个 batch，并以 bar_time 窗口在每根 5 分钟 bar 重置游标，一个 bar
完整扫完整个 universe。本文件中的 500/100 分片和 30 只 canary 仅保留为历史回滚与诊断证据，不替代
当前 full-universe 配置。

## 事实源优先级

1. 生产状态：immutable release、systemd、SQLite receipt、受认证 catalog/query 读回；
2. 当前合同：`config/provider_native_dataset_registry.yaml`；
3. 冻结候选：外部、reviewed security-master snapshot + receipt，经本仓库离线工具生成的 artifact；
4. 交付记录：`STATUS.md`；它只能链接上述证据，不能替代它们。

因此，代码合并、HTTP 200、旧样本或候选 hash 都不能单独称为 `live` 或 `stable`。

## 三层覆盖状态

| 层级 | 允许的状态 | 当前含义 |
| --- | --- | --- |
| 5,963 只 full universe | candidate → ready → live → stable | 20 个冻结 batch 必须按 cursor v2 receipt-bound 续接；成功批次保留，失败批次只在该 dataset 内重试，不跨 universe/config 复用。 |
| 500 只历史 cohort | rollback/diagnostic | 五个冻结 100 shard 的旧证据，仅用于回滚与审计，不声明当前 full-universe 覆盖。 |
| 30 只历史 canary | rollback/diagnostic | 旧 30 个代码的独立回滚面，不改变当前 5,963 代码 authority。 |

`ready` 表示合同、配置和测试均通过；`live` 需要真实有界 receipt 与 catalog/query 回读；`stable` 需要跨适用 cadence 的连续成功，并已有需要它的消费者回读。

## 受控推进路径

1. 用 receipt-bound security-master snapshot 生成 500 immutable universe；无此输入时不猜测 symbol 列表。
2. 使用 `compile_cn_minute_capacity_registry.py` 编译其中一个 100 shard 的暂停候选和 promotion reference。
3. 在独立、可回退的 release preflight 中复核 target、rollback、预算、已有 service/timer、完整同快照 receipt 与受认证 API；不新增 collector、route、timer 或 service。
4. 只在自然交易窗口做受控试采和 readback；任一缺码、重复、row-limit、snapshot 时间不一致、上游限流或 consumer 失败即 fail closed 并保留 30 回滚面。
5. 100 稳定后按同一 immutable universe 顺序扩到剩余 shard；500 的最终声明仍需同一轮五 shard 的完整性证明。

Copilot 只能展示来自 TA 的 receipt-bound projection。没有同标的 fresh formal projection 时，界面必须显示“等待正式覆盖”，不能显示买卖建议、目标价或概率。
