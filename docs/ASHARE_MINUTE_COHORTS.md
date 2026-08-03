# A 股 5 分钟 cohort：事实源与扩容门

本文件只说明 `cn.dataset.rt_min` 的消费覆盖与扩容证据。它不定义交易 Universe、下单、仓位或自动化投资建议。

## 事实源优先级

1. 生产状态：immutable release、systemd、SQLite receipt、受认证 catalog/query 读回；
2. 当前合同：`config/provider_native_dataset_registry.yaml`；
3. 冻结候选：外部、reviewed security-master snapshot + receipt，经本仓库离线工具生成的 artifact；
4. 交付记录：`STATUS.md`；它只能链接上述证据，不能替代它们。

因此，代码合并、HTTP 200、旧样本或候选 hash 都不能单独称为 `live` 或 `stable`。

## 三层覆盖状态

| 层级 | 允许的状态 | 当前含义 |
| --- | --- | --- |
| 30 只回滚 canary | 生产合同 | 30 个冻结代码、单个 5MIN 请求；仍需下一交易日 fresh receipt 与消费者读回才成为 live/stable。 |
| 100 只 shard | candidate → ready → live → stable | 离线编译器仅产生 `paused` candidate。启用前需要独立 activation evidence；启用后还需完整同快照 receipt、catalog/query、TA、Copilot 的顺序读回。 |
| 500 只 cohort | candidate → ready → live → stable | 五个冻结 100 shard 必须在同一窗口完整返回、无重复、恰好覆盖 500 且 `time` 相同；不以五次互不关联的成功拼接为 500 live。 |

`ready` 表示合同、配置和测试均通过；`live` 需要真实有界 receipt 与 catalog/query 回读；`stable` 需要跨适用 cadence 的连续成功，并已有需要它的消费者回读。

## 受控推进路径

1. 用 receipt-bound security-master snapshot 生成 500 immutable universe；无此输入时不猜测 symbol 列表。
2. 使用 `compile_cn_minute_capacity_registry.py` 编译其中一个 100 shard 的暂停候选和 promotion reference。
3. 在独立、可回退的 release preflight 中复核 target、rollback、预算、已有 service/timer、完整同快照 receipt 与受认证 API；不新增 collector、route、timer 或 service。
4. 只在自然交易窗口做受控试采和 readback；任一缺码、重复、row-limit、snapshot 时间不一致、上游限流或 consumer 失败即 fail closed 并保留 30 回滚面。
5. 100 稳定后按同一 immutable universe 顺序扩到剩余 shard；500 的最终声明仍需同一轮五 shard 的完整性证明。

Copilot 只能展示来自 TA 的 receipt-bound projection。没有同标的 fresh formal projection 时，界面必须显示“等待正式覆盖”，不能显示买卖建议、目标价或概率。
