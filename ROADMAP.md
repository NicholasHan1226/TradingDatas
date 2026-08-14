# TradingDatas Roadmap

## 最终目标

所有属于首期境内只读范围、且当前 QuickSync 账号经真实调用确认允许访问的 Tushare 数据集，都能：

1. 从 `provider=tushare`、`transport_service=quicksync` 的统一 provider-level adapter 获取；
2. 按注册频率与修订窗口自动运行；
3. 无损写入通用 SQLite facts；
4. 在同一事务提交 success receipt；
5. 通过 `/v1/catalog` 和 `/v1/query` 供内部调用；
6. 如实暴露 success、empty、unobserved、paused、failed、stale；
7. 支持当前数据优先、失败后有界重试，以及经独立批准的历史回填。

首期境内数据范围不包含港股、美股、其它加密资产、预测市场和 provider 写操作。另设隔离的 Binance 公共现货纵向切片，仅覆盖 BTCUSDT/ETHUSDT 5 分钟行情与公开 exchangeInfo 交易约束元数据；它不得共享 A 股 release、SQLite、内部 API 认证材料、端口或 timer，且无需并禁止 Binance 账户/API key。实际部署状态以 `STATUS.md` 为准。

### 当前执行停止线

本路线图当前只推进个人内部量化所需的数据闭环：provider → SQLite facts/receipts → 固定内部 `GET /v1/catalog` 与 `POST /v1/query` → 内部只读消费者。优先完成已有通用数据面上的稳定采集、真实 readback 和可回滚发布；不为了未来对外服务提前建设公网网关、多租户、计费、使用量账本、复杂权限层、专用 API、专用 collector 或按接口增加 timer。新增数据源必须沿用现有 registry/adapter/receipt/query 链路；只有已验证的通用协议缺口才允许最小修复。

## Phase 0 — clean-slate 基础

- 产品和仓库统一命名为 TradingDatas；
- 删除旧路由、旧 cron、旧交易门禁、旧专项 collector、DuckDB 和旧文档；
- 新运行面只保留 provider-native SQLite 与固定 catalog/query API；
- 旧生产系统只作为短期回滚源，不进入新代码依赖。

退出条件：新代码树不存在旧公共 route、旧业务系统 import、dataset-specific Tushare collector 或旧 scheduler 分支。

## Phase 1 — 全量 Tushare 合同与采集

这里的“全量”是产品分母与滚动 backlog，不是一次性上线门禁。每个 dataset 独立沿
`contract_ready → observed → stable` 前进；已安全落库的行、receipt 和可消费查询立即保留，
单项 empty/partial/429/5xx、权限或稳定性缺口只限制该 dataset/capability。Phase 1 未覆盖完
不能阻断下一独立接口、已覆盖子集的消费者或各市场 Factor/Strategy MVP；全分母完成只用于
宣称该阶段覆盖完成。

- 固定官方能力目录版本；
- 合并官方目录与当前 transport/tool 能力快照，冻结首期境内只读产品分母；当前
  scope v2 为 222 个 dataset，其中已有合同子集 190 个、新增待合同/权限证明 32 个；
- 能力可见性、正式合同、账号 entitlement 和 runtime activation 分开记录；新增项先
  `unobserved/paused`，不得为了凑“全量”伪造文档、请求参数或 success；
- 批量读取官方接口文档的输入/输出表，生成字段与请求合同；禁止逐接口手写 Python；
- 把 Tushare 官方文档限定为 dataset/schema/cadence 参考，把 QuickSync 文档与有界真实观测限定为 endpoint/auth/permission/error/rate/concurrency 事实源；
- 对每个 API 标记 scope、entitlement、activation 和 successor；
- 对每个 API 记录 QuickSync 真实观测的权限状态；账号级/API 级分钟、每日和并发预算未知时保持 unknown，不能用官方直连积分频次替代；凭证存在本身不得视为权限证明；
- 批量生成 provider-neutral dataset registry；
- 先按数据类型批量冻结 cadence/window，再验证每个 activation wave 会生成非零通用采集计划；
  `on_demand` 保持按需查询，不得借由 active 状态伪装为自动采集；
- 一次实现四种 request shape：
  - `snapshot_or_date_range`
  - `entity_fanout`
  - `dimension_fanout`
  - `event_or_intraday_window`
- 一次实现通用 pagination、request variants、rate budgets 和 retries；
- 使用八种 cadence class：
  - `session_minute`
  - `postclose_daily`
  - `daily_reference`
  - `weekly`
  - `monthly`
  - `quarterly_reporting`
  - `event`
  - `on_demand`

退出条件：222 个首期 dataset 均有明确分类；所有已授权项都有可执行合同或明确
blocked 原因；190 个历史合同子集与新增 32 项的证据层不混淆；普通 dataset
onboarding 不修改 Python；QuickSync transport profile、权限码和有界 budget 证据已
冻结，并经 target release/server readback 验证后，production timer 才可由受控发布流程显式启用。新增普通接口不得增加专用 collector、
路由、timer、service 或发布流程。

## Phase 2 — 内部服务

- 优先采集最新/当前数据；
- 按批准的有界 manifest 运行历史回填（不占用 production latest-window timer）；
- 完成 catalog/query、metadata、认证和监控；
- TradingAgent、MarketGraph 与内部研究工具只通过 API 消费；
- same-as-of 查询可复现。

退出条件：内部消费者不再访问旧数据库、旧 route 或 provider；真实 Tushare -> SQLite -> receipt -> API readback 通过。

## Phase 3 — 生产稳定与旧系统删除

- 在 `/opt/investment/releases/tradingdatas/<immutable-release>` 发布不可变代码，使用
  `/opt/investment/releases/tradingdatas/current` 原子指向当前版本，并把 SQLite 放在独立的
  `/opt/investment-data/tradingdatas/` 数据目录；
- 每个 target 与 rollback release 都必须有外置、确定性的 Git tree/file manifest，
  `current` 只在两端 release 均通过验证、采集执行已 quiesce 且 timer 已停止或被安全隔离
  时原子切换；release 回滚不得覆盖 SQLite；
- systemd service/timer 观察至少一个完整运行周期；
- 验证频率、积压、失败重试、资源预算、备份和回滚；
- 切换消费者；
- 停止并删除旧 SharedSignals 服务、cron、代码、文档和依赖。

数据库和历史数据只有在单独批准的数据保留清单中才可删除。

## 后续评估（不属于当前开发）

当前不开发外部账户或公网数据服务。若未来重新立项，新增 provider 仍须复用固定 API；只有 transport/auth/pagination 协议确有差异才增加 provider adapter。QuickSync/Tushare 的缓存、再分发和对外服务条款必须先完成书面核验，不能复用内部凭证或把内部 API 直接暴露为外部数据面。
