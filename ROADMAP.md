# TradingDatas Roadmap

## 最终目标

TradingDatas 优先成为稳定运行的内部金融数据底座：属于当前产品范围、且上游能力已经通过真实调用证明可用的数据集，应尽快沿统一链路持续积累数据，并由客观证据自动提升可用等级，而不是等待整个平台一次性完成。

统一数据链：

```text
provider
-> provider-level adapter
-> provider-native validation
-> SQLite facts + transaction-scoped receipt
-> runtime metadata projection
-> GET /v1/catalog + POST /v1/query
-> internal consumers
```

每个数据集都应：

1. 从明确的 provider / transport 合同获取；
2. 按注册 cadence 或有界 on-demand 请求运行；
3. 无损写入通用 SQLite facts；
4. 在同一事务形成 receipt 与 lineage；
5. 通过固定 `catalog/query` API 供内部系统只读消费；
6. 如实暴露 `success`、`empty`、`unobserved`、`paused`、`failed`、`stale`；
7. 支持失败后的有界自愈、缺口恢复和版本化 manifest 控制的历史回填。

当前中国境内只读数据以 Tushare provider、QuickSync transport 为主要范围。Crypto 使用隔离运行面覆盖冻结的 40 个 USDT 标的；现货和 USDⓈ-M 公共只读能力共用同一 provider-neutral 数据模型，但保持独立 release、SQLite、内部认证、端口和 timer。精确 active/paused 能力、release 与生产状态不得固化在本路线图，以 `STATUS.md` 和本轮 runtime/catalog/query readback 为准。

## 执行原则：先运行，再持续优化

当前阶段的第一优先级是让安全、可验证的采集/API/消费者链尽早上线并持续积累真实数据。工程重构、目录美化、通用框架升级和非必要性能优化不得成为已有能力上线的前置条件。

- 数据集独立沿 `contract_ready -> observed -> stable` 前进，不设置全局完成门槛。
- `contract_ready` 允许继续开发、集成和候选发布；一个数据集失败不阻断其它独立数据集。
- `observed` 由真实 provider -> SQLite receipt -> authenticated API readback 的客观证据自动形成。
- `stable` 由适用 cadence 的连续成功和消费者 readback 自动形成；满足冻结规则即可自动晋级，不需要人工确认。
- 自动晋级只能扩大“内部只读数据可用性”和既有预算内的调度范围，不能绕过 provider 权限、资源预算、数据完整性或安全边界。
- GitHub Actions 是可选验证渠道，不是生产上线门禁。Actions 不可用时，以本地/服务器确定性测试、候选 release 校验和生产 runtime readback 作为发布证据。
- 不为未来公网 SaaS、多租户、计费、复杂 RBAC 或理论扩展提前建设系统。

## Phase 0 — clean-slate 基础

- 产品和仓库统一命名为 TradingDatas；
- 新运行面只保留 provider-native SQLite、receipt/lineage 和固定 catalog/query API；
- 旧 SharedSignals、旧 route、旧专项 Tushare collector 和旧数据库接口不再成为运行依赖；
- 生产数据与代码 release 分离，回滚代码不得覆盖 SQLite 数据。

退出条件：当前运行链没有旧公共 route、旧业务系统 import 或 dataset-specific Tushare 运行入口。

## Phase 1 — 数据合同与持续采集

“全量”只是滚动 backlog，不是上线门禁。每个 dataset 独立获得合同、权限证据、真实 receipt 和 API readback。

主要工作：

- 固定官方能力目录及来源哈希；
- 区分产品 scope、正式合同、transport 可见性、真实 entitlement 和 runtime activation；
- 普通 Tushare dataset 只通过 registry/config 接入；
- 统一支持四类 request shape：`snapshot_or_date_range`、`entity_fanout`、`dimension_fanout`、`event_or_intraday_window`；
- 统一处理 pagination、variants、fanout、rate budget、retry、freshness 和 completeness；
- 统一使用八类 cadence：`session_minute`、`postclose_daily`、`daily_reference`、`weekly`、`monthly`、`quarterly_reporting`、`event`、`on_demand`；
- 当前数据优先，历史回填只使用版本化、有预算上限、可中断续跑的 manifest；
- activation wave 在执行前必须能从同一 registry 生成非零且有界的计划，但不要求人工逐项批准。

退出条件不是“所有接口都 stable”，而是：每个已进入运行范围的数据集都有明确合同或明确 blocker；已证明可用的数据集能够持续采集和供内部消费者使用。

## Phase 2 — 内部服务与自动恢复

- 优先保证最新/当前数据持续积累；
- API 始终只读 SQLite，不现场调用 provider；
- TradingAgent 与其它内部研究工具只通过固定 API 消费；
- same-as-of 查询在已有证据范围内可复现；
- 失败按 dataset 隔离，能够在预算内自动重试、恢复缺口并如实降级；
- 运行状态由 receipts、runtime metadata 和 readback 自动计算，不依赖人工状态填写。

退出条件：内部主要消费者不再访问旧数据库、旧 route 或 provider，且真实 provider -> SQLite -> receipt -> API -> consumer 闭环持续可读。

## Phase 3 — 稳定生产与轻量发布

生产保持现有不可变 release 模式：

```text
/opt/investment/releases/tradingdatas/<immutable-release>
                         ^
                         |
                      current

mutable data -> /opt/investment-data/tradingdatas/
```

发布原则：

- target release 与 rollback release 均可确定性识别；
- `current` 只做代码版本选择，SQLite 不随代码回滚；
- systemd service/timer 在既有资源和网络边界内运行；
- 发布后以 service/timer、receipt、catalog/query 和消费者 readback 验证实际运行；
- GitHub、服务器 source、effective release、runtime 和数据证据分别陈述，不能互相替代；
- CI 不可用时不阻断发布，但发布脚本/服务器验证失败必须 fail closed；
- 已稳定替代的旧运行入口按引用归零后删除，不长期维持双轨。

## 文档与历史

文档职责固定，避免重复维护同一事实：

- `README.md`：产品定位、快速入口和稳定架构概览；
- `AGENTS.md`：自动开发/修改的硬规则；
- `ROADMAP.md`：未来优先级，不记录瞬时生产状态；
- `STATUS.md`：当前状态摘要，不作为长期事件日志；
- `docs/ARCHITECTURE.md`：稳定架构；
- `docs/API.md`：接口合同；
- `docs/OPERATIONS.md`：部署、恢复和运行操作；
- `docs/adr/`：影响未来实现的长期决策；
- `docs/reports/`：需要人工可读保留的日期化 readback、事故与验收报告；
- SQLite receipts、runtime logs/evidence：机器运行历史，保存在运行数据面，不复制进 Git 文档。

普通代码演进由 Git 历史保存；只有会长期约束未来实现的决定才写 ADR。详见 `docs/AUTHORITY_AND_HISTORY.md`。

## 后续评估

当前不开发公网数据产品。若未来新增 provider，优先复用现有 registry/receipt/query 链；只有 transport、auth、payload 或 pagination 协议确实不同，才增加最小 provider-level adapter。任何未来扩展都不能阻断当前数据持续运行和积累。
