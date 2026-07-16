# SharedSignals

> **阅读顺序：** 本文件 → [STATUS.md](STATUS.md) → [README.md](README.md) →
> [外部 Beta 设计规格](docs/superpowers/specs/2026-07-15-sharedsignals-external-data-platform-beta-design.md)。
> 跨仓协作前再读上层 `Finance/AGENTS.md`。运行事实、一次性测试数字和事故记录不得写回本文件。

## 产品定位（不可漂移）

SharedSignals 是**独立外部多源金融数据平台**。Tushare 是首个主要上游和能力基准，不是 SharedSignals 的公共合同；未来可横向增加公告、新闻、研报、政策、互动和客观舆情等 provider。

SharedSignals 只负责：

- provider-neutral dataset catalog、provider adapter 和 canonical schema；
- 采集、校验、标准化、去重和数据质量；
- SQLite facts 与同事务的 SQLite ingest receipt；
- 客观 `freshness`、`quality`、`lineage`、`degraded`、`data_through` 和 runtime state；
- DB-first 只读 HTTP API/SDK，以及受邀外部账户的数据访问治理。

SharedSignals **不承载 opening gate**、候选选择、预测、策略评分、alpha、资金、持仓、风险、订单、成交、执行回执或交易建议；不读取 TradingAgent/MarketGraph 的业务状态决定采集，不共享数据库，不做跨系统事务、callback 或直接 import 它们的业务代码。事实型资金流或持仓排名可以作为 provider 原始数据存储，但不得被解释成交易判断。

## 权威层

权威顺序固定如下，后层不得反向覆盖前层：

1. provider-neutral dataset registry：dataset identity、schema、provider binding、entitlement、cadence、SLA、query policy 与 Beta policy；
2. SQLite facts + transaction-scoped ingest receipts：每次真实写事务的数据和成功 receipt 必须同事务提交；empty/failed 使用独立 terminal receipt；
3. registry + SQLite receipts + 当前读取时钟生成的 runtime/API metadata；
4. 可重建 JSON、监控摘要、日志和兼容响应，仅是缓存或观察材料，永远不是 authority。

HTTP 200、配置存在、allowlist、静态接口数量、旧数据行或消费者可解析都不等于数据健康。`success`、`empty`、`unobserved`、`paused`、`failed`、`stale` 必须保持可区分；provider error 不能伪装为 empty，缺 receipt 不能伪装为 success。

## 固定公共接口

- 目标数据面固定为 `GET /v1/catalog` 与 `POST /v1/query`。
- **新增数据源不得新增公共 API 路由**；新增 provider/dataset 通过 registry、adapter、storage mapping、receipt、query contract 和 metadata 扩展。
- `/tushare` 与现有专用端点是迁移期 legacy compatibility surface，最终必须调用同一个 query service，不能保留独立 SQL、provider live fallback 或文件 fallback。
- 外部消费者只能通过受控 HTTP API 访问；不得直连 SQLite、DuckDB、CSV/NDJSON、旧目录或 provider。
- 横向扩源完成定义是“能发现、能采、能同事务入库、能查询、能返回真实 metadata、能限流/降级、能回滚”，不是“配置里有名字”。

## 首期范围

- 首期只覆盖中国境内市场与已获权的 Tushare 能力；预测市场、加密货币、港股、美股不进入首期采集和公开目录。
- SQLite 是首期权威存储。DuckDB 不属于 Beta 关键读路径，保持停用直至独立设计和验收。
- CSV、NDJSON、Parquet、旧 staging、旧 bridge 和其它系统内部文件不得成为生产成功路径或 API fallback。
- 当前代码中仍存在的 opening gate、Green Gate 邮件、交易式 blocking、研究关系、旧专用 endpoint、旧 cron/patrol/heal 属于待迁移债务；必须按“替代接口 → 迁移消费者 → deprecate → safe-delete”处理，不能继续扩展，也不能在未知消费者仍存在时直接删除。

## 开发防漂移门禁

每个任务开始前必须写清并冻结：

1. 它是否直接推进“外部数据平台 Beta”目标；
2. 权威输入、输出接口、允许写域和明确非目标；
3. 威胁模型和运行假设；当前 Beta 只承诺协作进程与意外 race，不承诺抵御恶意 same-UID 进程；
4. 可复现的 P0/P1 验收项、停止条件和回滚方式；
5. 本地候选、Git 主线、GitHub、生产文件、生产 runtime、外部 route 和真实数据分别如何证明。

实现顺序固定为：

```text
批准的产品/接口规格
→ 一个 provider 到 API 的纵向切片
→ 冻结 acceptance contract
→ TDD 实现
→ 候选冻结
→ fresh clean-overlay review
→ 精确集成
→ 安全发布与生产回读
```

### Acceptance Freeze

- 候选冻结后，reviewer 只能按已批准合同验收；不得临时把新的架构偏好、未来商业能力或合同外安全加固升级为阻断项。
- 新发现只有同时满足“当前范围内、确定性可复现、真实影响数据正确性/隔离/可用性、达到 P0/P1”才允许 FAIL；其它发现记录为 P2/backlog。
- 一个 P0/P1 修复后重放原 acceptance matrix；不得因为修复顺手扩大写域。
- 同一方向连续两轮出现新的结构性 P1 时暂停补丁叠加，回到规格/架构裁决；不得无限追加 validation、锁或恢复协议。
- full suite、静态检查、manifest 和 reviewer PASS 只证明候选层；不能替代 GitHub、生产、外部路由或真实采集证据。

## 并行协作

- registry/ingest、query/API、scheduler、Beta access、文档可在接口冻结后用隔离 worktree 并行；写域不得交叉。
- 同一个公共合同、schema 或权威路径只能有一个 owner；其他 agent 默认只读审计。
- agent 不得自行 commit、push、deploy、改 cron、迁移数据库、写生产或清理数据/证据。主集成者独立审计 exact diff 后才可接手。
- 评审结论必须包含 base、worktree、精确文件、指纹、测试、未验证项和禁止动作；只说“完成”视为未完成。

## 数据与发布安全

- 禁止提交或删除生产数据库、Journal、ledger、outbox、history、evidence、缓存、日志、密钥、`.codegraphcontext` 或含独有成果的 worktree。
- 未经 Nicholas 明确授权禁止 schema migration、不可逆动作、生产 cron/systemd/nginx、真实邮件或外部写回。
- reader/API 只读 SQLite；缺库、缺表、损坏、无 mapping、无 receipt 或 metadata 不一致时 fail closed，不创建空库、不现场调用 provider、不回退文件。
- 发布必须使用 fresh safe-release preflight，分别验证 local/origin/GitHub、production checkout、runtime、外部 route、真实采集和 rollback；任何一层不能替代其它层。

## 文档与当前状态

- 稳定边界写本文件；目标架构写设计规格；任务步骤写 implementation plan；当前进度和生产事实写 [STATUS.md](STATUS.md)；历史运行记录写 `docs/status_history_2026-07.md`。
- 修改 registry、receipt、query contract、auth、scheduler、数据分类或发布边界时，代码、测试和对应核心文档必须同批审计。
- 仓库、默认分支和远端以当前 `git status -sb`、`git remote -v` 和最近提交为准；不得用旧摘要覆盖新事实。
