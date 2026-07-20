# TradingDatas Roadmap

## 最终目标

所有属于首期境内只读范围、且当前 Tushare 账号由积分或单独权限实际允许调用的数据集，都能：

1. 从统一 provider transport 获取；
2. 按注册频率与修订窗口自动运行；
3. 无损写入通用 SQLite facts；
4. 在同一事务提交 success receipt；
5. 通过 `/v1/catalog` 和 `/v1/query` 供内部调用；
6. 如实暴露 success、empty、unobserved、paused、failed、stale；
7. 支持当前数据优先、历史数据后台回填和失败后有界重试。

首期不包含港股、美股、加密货币、预测市场和 provider 写操作。

## Phase 0 — clean-slate 基础

- 产品和仓库统一命名为 TradingDatas；
- 删除旧路由、旧 cron、旧交易门禁、旧专项 collector、DuckDB 和旧文档；
- 新运行面只保留 provider-native SQLite 与固定 catalog/query API；
- 旧生产系统只作为短期回滚源，不进入新代码依赖。

退出条件：新代码树不存在旧公共 route、旧业务系统 import、dataset-specific Tushare collector 或旧 scheduler 分支。

## Phase 1 — 全量 Tushare 合同与采集

- 固定官方能力目录版本；
- 批量读取官方接口文档的输入/输出表，生成字段与请求合同；禁止逐接口手写 Python；
- 对每个 API 标记 scope、entitlement、activation 和 successor；
- 对每个 API 记录积分门槛或单独权限口径，以及官方/实测的分钟、每日和并发预算；Token 存在本身不得视为权限证明；
- 批量生成 provider-neutral dataset registry；
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

退出条件：所有首期 API 均有明确分类；所有已授权 in-scope API 都有可执行合同或明确 blocked 原因；普通 dataset onboarding 不修改 Python。

## Phase 2 — 内部服务

- 优先采集最新/当前数据；
- 启动后台历史回填；
- 完成 catalog/query、metadata、认证和监控；
- TradingAgent、MarketGraph 与内部研究工具只通过 API 消费；
- same-as-of 查询可复现。

退出条件：内部消费者不再访问旧数据库、旧 route 或 provider；真实 Tushare -> SQLite -> receipt -> API readback 通过。

## Phase 3 — 生产稳定与旧系统删除

- 在 `/opt/investment/releases/tradingdatas/<immutable-release>` 发布不可变代码，使用
  `/opt/investment/releases/tradingdatas/current` 原子指向当前版本，并把 SQLite 放在独立的
  `/opt/investment-data/tradingdatas/` 数据目录；
- systemd service/timer 观察至少一个完整运行周期；
- 验证频率、积压、失败重试、资源预算、备份和回滚；
- 切换消费者；
- 停止并删除旧 SharedSignals 服务、cron、代码、文档和依赖。

数据库和历史数据只有在单独批准的数据保留清单中才可删除。

## Phase 4 — 后续扩源与外部 Beta

内部稳定后才增加外部账户治理。新增 provider 继续复用固定 API；只有 transport/auth/pagination 不同才增加 provider adapter。
