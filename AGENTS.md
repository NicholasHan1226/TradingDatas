# TradingDatas project rules

## 产品定位

TradingDatas 是一个类似 Tushare 的 provider-neutral 金融数据平台。Tushare 是首个已接入上游；未来可以增加新闻、公告、研报、政策、互动和客观舆情等 provider。

当前主目标：所有属于首期境内只读范围、且当前 QuickSync 账号经真实调用确认允许访问的 Tushare 数据集，按照注册频率稳定采集到 SQLite，并通过 `GET /v1/catalog` 与 `POST /v1/query` 供内部调用。Binance 公共现货行情与同一冻结 40 个 USDT 标的的 USDⓈ-M 永续 funding rate / open interest 公共只读历史共同构成独立的第二 provider 纵向切片，必须使用独立 OS 服务账号、release、SQLite、内部 API 认证材料、loopback 端口和 timer，且继续复用同一固定 API；不得影响 A 股运行面，也不得创建或使用 Binance 账户/API key。

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
- `observed`：在受控窗口取得一次真实 provider -> SQLite receipt -> 固定 `catalog/query` 回读。它允许明确标注的内部只读试用，以及在既有 provider 预算、隔离运行面和 fail-closed 语义内持续积累观察证据；单次结果不等于连续健康或历史 PIT。
- `stable`：按该数据集适用 cadence 连续成功，且需要消费的 TA/Copilot 已完成受控 readback。它才是稳定生产能力的称谓；不要求无关消费者或尚未适用的 cadence 一并完成。

`stable` 缺失只能阻止稳定生产声明、无界扩容或相应发布切换，不能单独阻止已受控启用的隔离只读采集、后续普通数据集的 registry/config、编译、测试、候选 PR，或 TA 的受控消费开发。观察期 timer 的启用不是 `stable` 声明，仍受 provider 权限/预算、SQLite receipt、认证 API 回读和 fail-closed 完整性约束。任何层级都不得由 HTTP 200、历史记录、代码合入或任务卡伪造。

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

catalog row 携带 `coverage`（`row_count`、`earliest_observed_at`、`latest_observed_at`），来自同一 SQLite 快照对 `provider_dataset_rows` 的按 dataset 聚合；它是存储覆盖面参考，不证明历史完整性或 PIT，也不参与 cursor watermark。`/v1/query` 的 `fields` 过滤与 `max_selected_fields` 预算已内建于 query contract。

API 只读 SQLite。缺库、缺表、损坏、缺 receipt 或 metadata 不一致时 fail closed；不得现场调用 provider，不得回退文件、旧数据库、旧 route 或 provider 专用接口。

## 管理控制台

`GET /admin/` 提供内部管理界面，页面本身无需认证即可加载，API 调用需要 `admin` scope 或 `internal` tier 认证。

**前端部署**：前端代码位于 `static/index.html`，部署到 Cloudflare Pages（`tradingdatas-admin.pages.dev`），由 GitHub Actions 在 push main 且 `static/**` 变化时自动部署。后端管理服务在阿里云 ECS `/opt/td-admin`（systemd `tradingdatas-admin.service`，0.0.0.0:18084，`td-admin-autodeploy.timer` 每 5 分钟自动拉取），`/admin/` 直接读磁盘 `static/index.html`。Pages 的生产默认 API 是 `https://td-admin-api.tradingagent.cc`；该公开 HTTPS/auth 边界须由相应运行时交付分别读回，仓库不凭此客户端配置断言 Tunnel 名称、systemd unit 或凭据落点。不得把浏览器改回直连 HTTP IP，也不得将任何路由凭据写入仓库或 Pages。管理 API 的无凭据 `OPTIONS /admin/api/*` 必须返回 CORS preflight 成功；这不放宽后续实际请求的 admin/internal 认证。控制台含 Data Browser tab：按 dataset 浏览 `/v1/query` 落库数据（forward-only cursor）。控制台含 Token 管理、用量趋势、采集状态、健康告警与数据浏览器（按数据集分页预览 `/v1/query` 结果）。

管理 API 路由：

- `GET/POST /admin/api/tokens`：列出/创建 API token
- `PATCH/DELETE /admin/api/tokens/{hash}`：更新/删除 token
- `GET /admin/api/usage`：日用量、小时用量、系统统计
- `GET /admin/api/collection/status`：各数据集采集状态
- `GET /admin/api/data/overview`：数据概览（按市场/Provider/cadence 分类）

三个数据端点通过 `build_data_plane_runtime()` + `CatalogService.list_datasets` 聚合真实 catalog runtime（与 `/v1/catalog` 同一数据面），不引入旁路读法；功能测试见 `tests/test_v1_api.py::test_admin_data_endpoints_serve_real_catalog_runtime`。

**客户门户**：`GET /portal/api/me` 与 `GET /portal/api/me/usage?days=N` 让任意有效
token（read scope 即可）查看自身套餐/限额/用量，仅返回本租户数据；不计日配额、不做
scope 检查（门户自加载不烧客户配额），但完整认证、每小时频率与并发限制照常执行。
路由冻结白名单已显式登记这三个 `/portal/api*` 字面量（见
`tests/test_v1_api_clean_slate.py`）。合同详见 `docs/API.md` Customer Portal API。

**前端构建**：管理台/门户的 React 源码在 `frontend/`（Vite + TS + Tailwind），
构建产物提交在 `static/app/`（`base: '/app/'`），随 `static/**` 由同一 Pages 通道发布，
生产 URL 为 `tradingdatas-admin.pages.dev/app/`。旧单文件控制台 `static/index.html`
保留为回退入口。改前端后需在本机重新构建并一并提交 dist：
`cd frontend && npm ci && npm run build`（输出直接落到 `static/app/`）。

Token 配置（`config/api_tokens.json`）支持扩展字段：

- `enabled`（bool）：是否启用，默认 true
- `expires_at`（RFC3339/Unix 时间戳）：token 有效期
- `daily_limit`（number/null）：每日请求上限，null 或省略 = 无限

`tier` 档位与频率/并发（`auth.py` 常量，admin PATCH 可 per-token 覆盖并发）：

- 商业三档：`basic` 200 次/分钟、`standard` 600 次/分钟、`flagship` 1000 次/分钟，
  默认并发 4/8/16。按滑动 60 秒窗口计每分钟请求数，无小时窗；日配额与有效期照常。
- 存量档位不变：`free`/`starter` 60 次/小时、`research` 300 次/小时、`pro` 600 次/小时；
  `enterprise`/`internal` 不限频率。

`enforce_daily_limit` 在 `enforce_rate_limit`（商业档为每分钟窗口、存量档为每小时窗口）之后执行，超限时返回 429 `daily_limit_exceeded`。

**限流键与前置墙**（2026-08-24 起）：所有 per-IP 前置墙以**客户端真实 IP** 为键——公网流量经 Cloudflare 橙云代理回源时，TCP 对端是 CF 边缘而非客户，`api_server._effective_client_ip` 仅在 peer 属于 CF 回源网段时信任 `CF-Connecting-IP` 头（头缺失/畸形则回落共享边缘桶，防伪造）。两层前置墙必须高于最高商业档分钟限（flagship 1000），否则付费客户先被墙挡：`auth._PREAUTH_MAX_ATTEMPTS` 默认 1200/60s（env `TRADINGDATAS_PREAUTH_RATE_LIMIT`）、`api_server._AUTH_ATTEMPTS_PER_WINDOW` 默认 1200/60s（env `TRADINGDATAS_AUTH_ATTEMPT_RATE_LIMIT`），loopback 豁免仅 api 层有。

## 首期范围

- 中国境内只读数据和当前账号实际有权使用的数据集；
- Binance 公共现货冻结的 40 个高流动性 USDT 标的只读 5 分钟行情与公开 exchangeInfo 交易约束元数据，以及同一冻结 40 标的的 Binance USDⓈ-M 永续 funding rate 与 open interest 公共只读历史，仅允许在隔离 Crypto 运行面接入；标的清单由版本化 universe 合同编译，不能由运行时临时扩张；在 `fapi.binance.com` 被 SNI 级阻断期间，open interest 允许以 `https://data.binance.vision` 的 USDⓈ-M 日度 metrics dump 作为同一 dataset 的降级公共来源，premium index（funding 压力代理，非 funding rate 本身）允许以同站的日度 premiumIndexKlines dump 作为独立新 dataset 家族采集（funding rate 无 dump，仍不可得）；
- 港股、美股和其它加密资产排除；预测市场仅限 TD 的公共只读数据面：受限采集、provider-native 校验、规范化事实、transaction receipt/lineage，以及在独立合同、官方来源 hash、relay/权限证据、真实 receipt 和认证 API readback 齐备后向 A-share/Crypto 分析供数；这不构成 activation；
- 预测市场的 TA 交易/模拟、Copilot、钱包/账户/经纪、资金、订单、执行、promotion、live 与任何 provider 写/账号管理操作排除；
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

`on_demand` 数据集在 receipt 投影中永远不判 stale（success 与 empty 观测均豁免 freshness SLA）：按需查询语义没有刷新预期，`freshness_sla_seconds` 是 registry 通用字段而非刷新承诺。投影的 attempt/execution 完整性校验必须在 `data_through_in_future` 过滤之前的完整 receipt 集合上执行；否则同 execution 中被 future 过滤移除的行会造成 call_index 断档，级联误报 `receipt_execution_inconsistent` 掩盖真实根因（生产 `cn.news.flash` 曾因此误报）。

当前/最新分区优先，历史回填有界并在后台运行。调度从 registry、SQLite facts 和可信 receipts 推导缺口，不以最近一次运行时间假装数据完整。账号级、provider 级、API 级预算必须跨 dataset 生效。

QuickSync 的账号级限频、每日额度与并发上限在证据冻结前不得启用自动调度；历史回填也不能绕过同一 transport budget。

普通接口接入按同一批次推进：先批量探测并分类权限/参数/空响应，再按 data class 批量冻结 cadence 与 window，随后用同一个 runner 做有界入库和 API readback。不得为单个 API 单独创建任务流、测试栈、service、timer、route 或发布流程。

当前交付采用广度优先：valid rows 与 receipts 立即保留和积累；单个 dataset 的 empty、partial、429、provider `5xx` 或 cadence 失败只降级该 dataset 并形成后续修正，不阻断下一独立批次。locked、excluded、unknown 或 required params 未解决的 dataset 显式暂停。稳定性继续按 dataset 独立积累，不能被用作延迟全部接口接入的全局门禁。

## clean-slate 与退役

当前代码树不保留旧 SharedSignals 公共 route、双注册表、opening gate、旧 Crypto 路由/采集器、旧预测市场产品、DuckDB、邮件、旧 cron、旧 reader 或交易式控制。`collectors/prediction_markets/` 如存在，只能是当前经审查的公共只读 TD provider adapter；在官方合同 hash、双 dataset 映射、Yes/No 语义交叉核对、持久化/receipt 合同与认证 API readback 完成前，不得注册、启用 timer 或对外供数，更不得形成 TA/Copilot 交易控制。新的 Binance 公共数据切片只能通过独立 provider-level adapter 和隔离运行面接入；Git 历史承担旧实现追溯。

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
- **合入门禁：** 一切变更走 feature 分支 + PR，禁止直推 main。M0 只限可信同仓、非 draft、精确 candidate head、绿 CI、`automerge-m0` 标签及 `README.md`/`CONTRIBUTING.md`/`docs/**`/`tests/**`/`static/**` 的可逆非运行时改动；无关 main 前进不要求重写 M0 分支，且 M0 合并只补 exact-main CI，绝不触发服务器部署。M1 仍要求当前 immutable head 的 Controller `AUTODEV_RETURN_V1` + `controller-accepted` 标签；shared/workflow/contract/receipt/registry/query/schema/deploy/risk/execution/promotion 或与主线 authority 重叠时，base 前进必须重新集成并验收。自动合并必须等待 GitHub 的真实 merged SHA，再调度该 SHA 的 main CI；若本次改动含 `static/**`，同一流程显式调度该 SHA 的 Pages 发布，因为 Actions 身份合并不可靠地重新触发 push workflow。各层 CI、服务器、有效 release、runtime、receipt 和消费者 readback 独立结论：下游未完成只阻断对应发布/运行声明，不阻断已满足最小充分证据的独立 M0 或非运行时开发。自动化绝不替 owner/Controller 改写候选分支。修改 `.github/workflows/**` 的 PR 永不自动合并，需单独的受信 bootstrap 合并。CI 在 push main 后补跑不构成豁免：直推意味着坏代码可能已在 main 上并被服务器 5 分钟内拉取。本地测试通过不能替代 CI 门禁。
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
- `docs/AUTHORITY_AND_HISTORY.md`
- `docs/reports/`

架构、API、运行路径、环境变量、频率或发布边界变化时，代码与上述文档同批更新。旧计划和事故说明不保留在当前树，必要追溯使用 Git 历史。
