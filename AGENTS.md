# TradingDatas project rules

## 产品定位

TradingDatas 是一个类似 Tushare 的 provider-neutral 金融数据平台。Tushare 是首个已接入上游；未来可以增加新闻、公告、研报、政策、互动和客观舆情等 provider。

当前主目标：所有属于首期境内只读范围、且当前 QuickSync 账号经真实调用确认允许访问的 Tushare 数据集，按照注册频率稳定采集到 SQLite，并通过 `GET /v1/catalog` 与 `POST /v1/query` 供内部调用。Binance 公共现货行情是独立的第二 provider 纵向切片，必须使用独立 OS 服务账号、release、SQLite、内部 API 认证材料、loopback 端口和 timer，且继续复用同一固定 API；不得影响 A 股运行面，也不得创建或使用 Binance 账户/API key。

在 Finance 产品架构中，TradingDatas 只负责跨市场数据接口接入、稳定采集、规范化落库、持续积累、lineage/receipt 和固定 API 供应。TradingAgent/Quant Core 是终局个人自动量化交易系统；TradingCopilot 只是过渡性的 A 股实盘辅助与观察工具。TradingDatas 不把消费者串成 `TD -> TA -> Copilot`，也不因某个消费者、某个数据集的稳定性或未来市场计划冻结其它独立数据接口接入。

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

## 能力分层与轻量门禁

数据质量不降级，但开发、内部试用与稳定生产不得再共用一扇门：

- `contract_ready`：registry/config、字段/主键、cadence、consumer applicability、编译与失败测试均通过。它允许进入 capability manifest、TA 的受控兼容测试和候选发布准备；不声称上游权限、receipt、API 或生产可用。
- `observed`：在受控窗口取得一次真实 provider -> SQLite receipt -> 固定 `catalog/query` 回读。它允许明确标注为一次性、内部只读试用；单次结果不等于连续健康、历史 PIT 或自动调度。
- `stable`：按该数据集适用 cadence 连续成功，且需要消费的 TA/Copilot 已完成受控 readback。它才是稳定生产能力的称谓；不要求无关消费者或尚未适用的 cadence 一并完成。

`stable` 缺失只能阻止稳定生产声明、自动调度或相应发布切换，不能阻止后续普通数据集的 registry/config、编译、测试、候选 PR，或 TA 的受控消费开发。任何层级都不得由 HTTP 200、历史记录、代码合入或任务卡伪造。

## Tushare 复用

- 普通接口复用统一 `api_name + params + fields -> fields/items` transport。
- `provider=tushare` 表示数据合同与上游能力，`transport_service=quicksync` 表示当前账号实际使用的兼容传输服务；两者不得混为同一个身份，也不得把 QuickSync 写成新的 dataset provider。
- Tushare 官方接口清单、输入字段、输出字段和更新说明只作为 dataset/schema/cadence 参考，从固定官方目录与批量官方文档快照生成；禁止逐接口复制文档或手写同构合同。生成结果必须记录来源 URL、内容哈希和未解析项。
- QuickSync 的实际 endpoint、认证方式、权限返回、限频、并发、错误码和连接约束才是当前 runtime transport 的事实源。官方 Tushare 积分、频次或直接 endpoint 不能替代 QuickSync 的运行证据。
- 新增普通 dataset 只能修改 registry/config，不得增加 dataset-specific collector、业务表、scheduler 分支、query 分支、fixture 分支或公共 route。
- 请求差异只通过四种通用 request shape、variants、fanout、pagination 和 budgets 声明。
- 只有 transport/auth/pagination 协议真实不同，才增加 provider-level adapter。
- provider payload 必须无损保留；未知字段标记 schema drift，不能静默删除或改写。
- **复杂度止损：** 新一批普通 Tushare dataset 先用批量 matrix + registry/config 完成；只有证明现有四种 request shape、八种 cadence class 和通用 SQLite adapter 无法表达时，才允许讨论 Python 改动，并须先记录可复现的配置表达缺口。
- **采集前门禁：** `activation=active` 不是采集成功，也不能替代 planner 验证。每个自动采集候选必须先从同一 registry 做 dry-run，证明选中 dataset、窗口和频率会生成非零计划；`on_demand` 只能保持按需查询语义，不能被 wave、timer 或文档误称为自动采集。

## 固定接口

- `GET /v1/catalog`
- `POST /v1/query`

API 只读 SQLite。缺库、缺表、损坏、缺 receipt 或 metadata 不一致时 fail closed；不得现场调用 provider，不得回退文件、旧数据库、旧 route 或 provider 专用接口。

## 首期范围

- 中国境内只读数据和当前账号实际有权使用的数据集；
- Binance 公共现货冻结的 10 个高流动性 USDT 标的只读 5 分钟行情与公开 exchangeInfo 交易约束元数据，仅允许在隔离 Crypto 运行面接入；标的清单由版本化 universe 合同编译，不能由运行时临时扩张；
- 港股、美股、其它加密资产、预测市场和 provider 写/账号管理操作排除；
- `in_scope` 只是产品分类，不等于 entitlement 或 activation；
- `activation`/稳定生产的每个数据集必须有合同、权限证据、真实 receipt、API readback 和 observed cadence；`contract_ready` 候选只需保留上述缺口，不得被误标为已激活。

## QuickSync 权限与流控口径

- 当前凭证只标识 QuickSync 访问账号，不证明某个 Tushare dataset 可用、调用额度或并发能力。
- 项目中的 `entitlement` 是 provider-neutral 技术字段，含义固定为“经当前 QuickSync transport 真实调用观测到的账号权限状态”，不是购买、计费或订阅状态。
- activation 只能来自受控真实探测与人工审核；scheduler 的账号级/API 级调用预算必须服从 QuickSync 当前账号说明和真实返回中更保守的一侧，不能从凭证存在、官方 Tushare 积分、静态目录或单次成功推断。
- QuickSync 频率或并发未知时固定为 unknown，并保持串行、人工有界 canary 和 production timer disabled；禁止填入猜测值或沿用官方直连预算。
- Tushare 官方入口仍用于理解 dataset 与更新周期：[平台介绍与接口文档](https://tushare.pro/document/1)；当前 transport 权限与流控必须由 QuickSync 文档或真实有界观测另行证明。

## 频率与回填

只允许八种通用 cadence class：`session_minute`、`postclose_daily`、`daily_reference`、`weekly`、`monthly`、`quarterly_reporting`、`event`、`on_demand`。

当前/最新分区优先，历史回填有界并在后台运行。调度从 registry、SQLite facts 和可信 receipts 推导缺口，不以最近一次运行时间假装数据完整。账号级、provider 级、API 级预算必须跨 dataset 生效。

QuickSync 的账号级限频、每日额度与并发上限在证据冻结前不得启用自动调度；历史回填也不能绕过同一 transport budget。

普通接口接入按同一批次推进：先批量探测并分类权限/参数/空响应，再按 data class 批量冻结 cadence 与 window，随后用同一个 runner 做有界入库和 API readback。不得为单个 API 单独创建任务流、测试栈、service、timer、route 或发布流程。

当前交付采用广度优先：valid rows 与 receipts 立即保留和积累；单个 dataset 的 empty、partial、429、provider `5xx` 或 cadence 失败只降级该 dataset 并形成后续修正，不阻断下一独立批次。locked、excluded、unknown 或 required params 未解决的 dataset 显式暂停。稳定性继续按 dataset 独立积累，不能被用作延迟全部接口接入的全局门禁。

## clean-slate 与退役

当前代码树不保留旧 SharedSignals 公共 route、双注册表、opening gate、旧 Crypto 路由/采集器、预测市场、DuckDB、邮件、旧 cron、旧 reader 或交易式控制。新的 Binance 公共数据切片只能通过独立 provider-level adapter 和隔离运行面接入；Git 历史承担旧实现追溯。

旧生产系统只在 TradingDatas 真实采集、API readback、消费者切换和回滚证明完成前作为短期回滚源；不得把其接口或数据结构带回新架构。数据库和历史数据删除需要单独保留策略。

基于官方 `api.tushare.pro` 直连假设形成的旧生产 transport 证据已经失效，只能证明 registry、SQLite、receipt 与 API 代码层，不得作为 QuickSync runtime、权限、频率或生产可用证明。

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
- GitHub 传输优先使用 Nicholas 已登录的 `gh` HTTPS 凭据链：先核对 `gh auth status`，仓库 `origin` 固定为 `https://github.com/NicholasHan1226/TradingDatas.git`。若 `git@github.com` 的 SSH/22 端口失败一次，不重复重试或上报为长期 blocker；立即验证 HTTPS `git ls-remote`，切换现有 remote 后 fetch。不得输出 token，也不得另建凭据或绕过 host-key 校验。
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
