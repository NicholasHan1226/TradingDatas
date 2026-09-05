# Authority and History

本文件只定义“哪类事实放在哪里”，用于避免 README、STATUS、ROADMAP、运行日志和机器状态互相复制。

## 事实权威

按事实类型使用不同权威，不设一个万能状态文件。

| 事实类型 | 权威 | Git 文档的作用 |
| --- | --- | --- |
| dataset identity / schema / provider binding / query policy | versioned registry/config | 解释合同，不复制运行状态 |
| 已采集事实、receipt、lineage、watermark | SQLite + transaction-scoped receipts | 只引用验收结论 |
| 当前 API 可读状态 | 当前 release + runtime metadata + authenticated `catalog/query` readback | `STATUS.md` 做短摘要 |
| service/timer/effective release | 服务器本轮直接 readback | `STATUS.md` 可记录最近摘要 |
| 长期架构和接口 | `docs/ARCHITECTURE.md` / `docs/API.md` | 稳定说明 |
| 发布和恢复规则 | `docs/OPERATIONS.md` | 操作合同 |
| 接口接入 / 外部 blocker / 采集成功口径 | `docs/OPERATIONS.md`「Datas PM 接入口径」 | 解释我们拥有什么；不把 vendor empty 写成未完成 |
| 长期决策 | `docs/adr/` | 决策原因、约束和后果 |
| 一次性验收、事故、迁移证据 | `docs/reports/` | 日期化人工可读记录 |
| 普通代码修改历史 | Git commits | 不重复写事件日志 |

## 文档职责

### `README.md`

只回答：这是什么、当前稳定架构是什么、从哪里开始。不要长期堆生产快照。

### `AGENTS.md`

只保存自动开发与修改时必须遵守的硬规则。规则应能长期成立；瞬时 release、某次 receipt 数量或某次 timer 状态不进入这里。

### `ROADMAP.md`

只保存下一阶段方向和优先级。当前生产数字、临时 blocker、某次探测结果不进入路线图。

### `STATUS.md`

只回答“现在是什么状态”。目标是短、可覆盖更新，而不是 append-only 日志。需要长期保留的旧状态转为日期化 report，普通变化由 Git 历史追溯。

### `docs/adr/`

只保存会约束未来实现的决定，例如：固定 API、provider/transport 身份分离、deploy-first、证据自动晋级。ADR 一经采纳不重写历史；后续改变用新 ADR supersede。

### `docs/reports/`

保存值得人工审计的一次性证据：生产 readback、故障复盘、迁移验收、重大性能/容量试验。它们不是当前 authority，也不能被运行代码读取为状态。

## 自动晋级

内部数据能力不依赖人工确认。冻结合同满足后，系统根据可机器验证的证据自动前进：

```text
contract_ready
  -> real provider + SQLite receipt + authenticated API readback
observed
  -> applicable cadence continuity + authenticated platform API readback
stable
```

这些层级描述证据与稳定性，不是接入、供数、正常发布或预算内采集的统一开关；消费者 readback 只决定消费者自身的稳定声明。详见 [接入、供数与质量的边界](OPERATIONS.md#接入供数与质量的边界)。provider 权限、请求预算、我们自己的 receipt 完整性（empty ≠ success，不得伪造非空）和资源安全仍是硬边界。Vendor/input quality is immutable external：合同正确时的 empty / `provider_error` 是外部 blocker，不是晋级未完成，也不阻塞下一可接接口。单个 dataset 失败只降级该 dataset。

## GitHub Actions

GitHub Actions 不成为运行权威，也不阻止已上线采集和只读 API 按现有合同继续运行。
源码合入仍遵守根 `AGENTS.md` 的 PR 与精确候选 CI 门禁；本地测试不能替代该门禁，
不得因 Actions 不可用直推主线或发布未经接受的源码。

合并与 CI 成功后，生产交付还需分别验证：不可变 release/清单、实际服务与定时任务、
SQLite receipt、认证 catalog/query，以及适用消费者。GitHub commit、PR 或绿色 CI
均不能单独证明生产已上线或数据稳定；单数据集外部失败按运维口径单列。

## 历史保留原则

保留三类历史：

1. **Git history**：普通代码和文档变更；
2. **ADR**：会影响未来实现的决策；
3. **机器运行证据**：SQLite receipts、运行日志、外置 evidence/backup，由运行数据面按保留策略管理。

不需要把每次开发过程、每个 commit、每次 timer 成功都复制到 `STATUS.md`。只有对未来调查有价值的异常或验收，才另外形成 `docs/reports/YYYY-MM-DD-*.md`。
