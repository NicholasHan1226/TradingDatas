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
  -> applicable cadence continuity + consumer readback
stable
```

晋级只影响内部只读数据能力和既有预算内的调度资格。provider 权限、请求预算、完整性、数据质量和资源安全仍是硬边界；单个 dataset 失败只降级该 dataset，不应阻塞其它独立数据能力。

## GitHub Actions

GitHub Actions 是可选的远端验证渠道，不是运行权威，也不是生产上线的必要条件。Actions 不可用时，发布仍可由以下证据完成：

1. 候选源码的确定性本地/服务器验证；
2. immutable release 建立与版本核对；
3. systemd/service/timer 运行读回；
4. SQLite receipt；
5. authenticated catalog/query readback；
6. 适用消费者 readback。

没有上述运行证据时，GitHub 上的 commit、PR 或绿色 CI 也不能单独证明生产已上线。

## 历史保留原则

保留三类历史：

1. **Git history**：普通代码和文档变更；
2. **ADR**：会影响未来实现的决策；
3. **机器运行证据**：SQLite receipts、运行日志、外置 evidence/backup，由运行数据面按保留策略管理。

不需要把每次开发过程、每个 commit、每次 timer 成功都复制到 `STATUS.md`。只有对未来调查有价值的异常或验收，才另外形成 `docs/reports/YYYY-MM-DD-*.md`。
