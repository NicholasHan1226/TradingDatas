# TradingDatas project rules

## 产品定位

TradingDatas 是一个类似 Tushare 的 provider-neutral 金融数据平台。Tushare 是首个已接入上游；未来可以增加新闻、公告、研报、政策、互动和客观舆情等 provider。

唯一当前目标：所有属于首期境内只读范围、且当前 Tushare 账号由积分或单独权限实际允许调用的数据集，按照注册频率稳定采集到 SQLite，并通过 `GET /v1/catalog` 与 `POST /v1/query` 供内部调用。

TradingDatas 不承担 opening gate、候选、预测、策略、alpha、资金、持仓、风控、订单、成交、执行回执或交易建议；不直接 import TradingAgent/MarketGraph 业务代码，不共享数据库，不做跨系统事务或 callback。

## 不可漂移的数据链

```text
provider registry
-> provider adapter
-> provider-native validation
-> SQLite facts + transaction-scoped receipt
-> read-clock metadata projection
-> /v1/catalog + /v1/query
```

权威顺序固定为 registry、SQLite facts/receipts、runtime metadata、HTTP projection。HTTP 200、配置数量、JSON 缓存、日志、旧数据库和消费者状态都不是数据健康权威。

## Tushare 复用

- 普通接口复用统一 `api_name + params + fields -> fields/items` transport。
- 接口清单、输入字段、输出字段和更新说明从固定官方目录与批量官方文档快照生成；禁止逐接口复制文档或手写同构合同。生成结果必须记录来源 URL、内容哈希和未解析项。
- 新增普通 dataset 只能修改 registry/config，不得增加 dataset-specific collector、业务表、scheduler 分支、query 分支、fixture 分支或公共 route。
- 请求差异只通过四种通用 request shape、variants、fanout、pagination 和 budgets 声明。
- 只有 transport/auth/pagination 协议真实不同，才增加 provider-level adapter。
- provider payload 必须无损保留；未知字段标记 schema drift，不能静默删除或改写。

## 固定接口

- `GET /v1/catalog`
- `POST /v1/query`

API 只读 SQLite。缺库、缺表、损坏、缺 receipt 或 metadata 不一致时 fail closed；不得现场调用 provider，不得回退文件、旧数据库、旧 route 或 provider 专用接口。

## 首期范围

- 中国境内只读数据和当前账号实际有权使用的数据集；
- 港股、美股、加密货币、预测市场和 provider 写/账号管理操作排除；
- `in_scope` 只是产品分类，不等于 entitlement 或 activation；
- 每个激活数据集必须有合同、权限证据、真实 receipt、API readback 和 observed cadence。

## Tushare 权限与流控口径

- Token 只标识账号，不证明接口可用、调用额度或并发能力。
- 普通接口通常由账号积分门槛及对应的分钟/每日频控决定；部分接口需要单独开通权限，可能与积分无关。
- 项目中的 `entitlement` 是兼容 provider-neutral registry 的技术字段，含义固定为“经真实调用观测到的账号权限状态”，不是购买、计费或订阅状态。
- activation 只能来自受控真实探测与人工审核；scheduler 的账号级/API 级调用预算必须服从官方说明和真实返回中观测到的频控，不能从 Token 存在、静态积分或接口目录推断。
- 官方入口：[平台介绍与积分频次](https://tushare.pro/document/1)；[权限中心](https://tushare.pro/weborder/#/permission)。

## 频率与回填

只允许八种通用 cadence class：`session_minute`、`postclose_daily`、`daily_reference`、`weekly`、`monthly`、`quarterly_reporting`、`event`、`on_demand`。

当前/最新分区优先，历史回填有界并在后台运行。调度从 registry、SQLite facts 和可信 receipts 推导缺口，不以最近一次运行时间假装数据完整。账号级、provider 级、API 级预算必须跨 dataset 生效。

## clean-slate 与退役

当前代码树不保留旧 SharedSignals 公共 route、双注册表、opening gate、Crypto、预测市场、DuckDB、邮件、旧 cron、旧 reader 或交易式控制。Git 历史承担追溯。

旧生产系统只在 TradingDatas 真实采集、API readback、消费者切换和回滚证明完成前作为短期回滚源；不得把其接口或数据结构带回新架构。数据库和历史数据删除需要单独保留策略。

## 开发顺序

```text
冻结产品/接口/验收
-> 一个通用能力实现
-> TDD
-> 候选冻结
-> fresh independent review
-> 精确集成
-> safe release
-> production readback
```

reviewer 只能按冻结合同阻断 P0/P1，不得在候选冻结后扩大范围。普通 dataset onboarding 若需要修改 Python，直接判定架构失败。

## 并行协作

registry/ingest、query/API、scheduler、deploy/docs 可在接口冻结后并行，但写域不得交叉。同一 schema、公共合同或 authority 只能有一个 owner。协作者不得自行 commit、push、deploy、改 production 或删除数据。

## Git、发布与删除

- 开工先检查 branch、status、remote、HEAD 与并行 worktree。
- 不覆盖他人改动，不使用 `git add .`、force push、历史重写或破坏性 reset。
- local、GitHub、production files、runtime、真实 provider receipt、API readback 和消费者调用分别验证。
- 删除旧代码/文档必须确认它不属于新运行面；删除生产 service/cron 必须先完成新系统切换与回滚证明。
- 不提交或删除数据库、token、日志、receipt、history、evidence、rollback artifact 或 `.codegraphcontext`。

## 文档入口

- `README.md`
- `ROADMAP.md`
- `STATUS.md`
- `docs/ARCHITECTURE.md`
- `docs/API.md`
- `docs/OPERATIONS.md`
- `docs/adr/ADR-0010-tradingdatas-clean-slate.md`

架构、API、运行路径、环境变量、频率或发布边界变化时，代码与上述文档同批更新。旧计划和事故说明不保留在当前树，必要追溯使用 Git 历史。
