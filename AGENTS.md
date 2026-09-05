# TradingDatas project rules

## 产品定位

TradingDatas 是一个类似 Tushare 的、面向公共用户但所有数据请求均需认证的 provider-neutral 金融数据平台。它是 `Finance/TradingDatas` 下的独立仓库，不是 TradingAgent 模块。Tushare 是首个已接入上游；未来可以增加新闻、公告、研报、政策、互动和客观舆情等 provider。产品背景、Agent-first 消费模型、数据分类和账户权限目标以 `docs/PRODUCT.md` 为核心事实源。

产品主要服务 Claude、Codex、OpenClaw、Hermes 等可调用 HTTP 工具的 Agent。用户侧按 A 股、加密资产、新闻等产品分类发现数据；技术 registry 仍以 `market` 与 `domain` 分开表达，公共 API 永远保持 catalog/query 两个 provider-neutral 端点。

商业权限模型是 endpoint scope、数据分类 allowlist 与每分钟请求上限三者取交集。商业套餐按 200/600/1000 次每分钟区分，不设每日查询额度，也不设置商业档并发上限。`data_categories` 只允许 `a_share`、`crypto`、`news`，由后端根据 immutable registry 推导 dataset grants，并在 catalog/query 同时强制执行；缺字段的存量 Token 保持兼容全量，显式空列表无数据授权，未知值 fail closed。当前代码已让 `basic`/`standard`/`flagship` 使用滚动 60 秒窗口、忽略旧配置残留的 `daily_limit`/`max_concurrent`，并在管理写入时拒绝商业档这两个非空字段；生产是否生效仍须 exact-main 发布及认证 readback。

当前主目标：所有属于首期境内只读范围、且当前 QuickSync 账号经真实调用确认允许访问的 Tushare 数据集，按照注册频率稳定采集到 SQLite，并通过 `GET /v1/catalog` 与 `POST /v1/query` 供内部调用。Binance 公共现货行情与同一冻结 40 个 USDT 标的的 USDⓈ-M 永续 funding rate / open interest 公共只读历史共同构成独立的第二 provider 纵向切片，必须使用独立 OS 服务账号、release、SQLite、内部 API 认证材料、loopback 端口和 timer，且继续复用同一固定 API；不得影响 A 股运行面，也不得创建或使用 Binance 账户/API key。

在 Finance 产品架构中，TradingDatas 只负责跨市场数据接口接入、稳定采集、规范化落库、持续积累、lineage/receipt 和固定 API 供应。TradingAgent/Quant Core 是终局个人自动量化交易系统；TradingCopilot 只是过渡性的 A 股实盘辅助与观察工具。TradingDatas 不把消费者串成 `TD -> TA -> Copilot`，也不因某个消费者、某个数据集的稳定性或未来市场计划冻结其它独立数据接口接入。

TradingDatas 不承担 opening gate、候选、预测、策略、alpha、资金、持仓、风控、订单、成交、执行回执或交易建议；不直接 import TradingAgent/MarketGraph 业务代码，不共享数据库，不做跨系统事务或 callback。

## 公共产品与教学内容边界

TradingDatas 对外销售的是可信、可追溯、可复现的金融数据原料。公共网站的信息架构固定分为 `Data`、`Features`、`Recipes`、`Research`、`Pricing`、`Docs` 与账户入口；`Research` 按 TradingDatas 自有分类体系整理外部论文，`Recipes` 回答“如何正确准备和组合数据”。它们是发现、购买、学习和管理同一个数据产品的界面，不是新的研究或交易 authority。Agent/MCP 是 Account/Docs 下的交付方式，不是首要购买理由。

- `Data` 只展示 registry 与 catalog/query 可证明的数据身份、字段、覆盖、更新、lineage、样本和限制。静态文案不能把 paused/unobserved/degraded 数据写成可用，也不能从 provider 文档或一次 HTTP 200 推断历史完整性。
- `Research` 只整理、分类和展示外部行业论文或研究，保留作者、年份、期刊/来源和外部链接，并可映射所需原始数据材料；不得改写成 TradingDatas 自有结论、推荐、绩效或数据产品 benchmark。论文元数据与摘要须标明外部来源，静态示例不得冒充已上线数据库。
- `Features` 只允许透明、版本化的衍生数据，必须公开公式、输入、时间/as-of 对齐、缺失/修订策略、测试与限制；它不是因子排名、信号、策略或建议。当前 Feature Plane 未实现，相关页面只能标记为 `product definition` 或 `planned`。
- `Recipes` 只教授查询、连接、时间/as-of 对齐、复权、缺失处理、去重和验证；示例必须列 dataset IDs、窗口、方法、输出 schema、限制及 synthetic/observed 身份。
- Agent 接入提示词只允许由 `docs/AGENT_INTEGRATIONS.md` 的单一 canonical template 派生；不得在提示词、URL、fixture、日志或静态 bundle 中嵌入真实 key。Claude、Codex、OpenClaw、Hermes 与其它 Agent 共用固定 catalog/query 和同一 metadata/receipt 验证语义。
- 公共站支持 `zh-CN`/`en`，首次跟随系统语言，显式选择可持久化；dataset ID、字段名、API route、schema、receipt ID、reason code 和 provider-native payload 永不翻译。MCP/Agent、语言与外观设置只放在独立 Account 工作区，全局导航右侧只保留账户头像，不重复放 Connect/Console/语言/主题文本操作。
- Data、Features、Recipes、Research、Pricing、Docs 与 Account 是可复制、可回退、可直接访问的独立公共页面，并继续进入 dataset/feature/recipe/research/docs 详情页；它们不是首页锚点或承载完整任务的大下拉菜单。Account 按账户概览、数据访问、集成、账单、设置分组，前端显示不替代 portal/commerce/auth 后端事实。
- 允许描述的“效果”仅限覆盖增加、匹配率、时间对齐、重复减少、输出形态、延迟与查询成本。禁止收益、Alpha、胜率、预测准确率、因子排名、推荐、信号或策略绩效。
- 套餐、另类数据试用、加购、续费和价格只有在 commerce/account 后端合同实现并可读回后才可声明 live。前端标签、Feature/Recipe 或营销内容不授予数据权限。
- 第三方和另类数据必须先完成上游使用/再分发权、provider 合同、transport entitlement、真实 receipt/API readback 和账户 entitlement 映射，继续复用固定 catalog/query API；不得因商业页面新增 provider 专用公共 route。

当前 `/v1` 仍是 provider-native Evidence Plane。未来 canonical/PIT Product Plane、Feature Plane 与 Recipe Plane 必须独立版本化并保持回链 receipt；不得原地改写当前事实链，也不得在新 API 合同、迁移、测试、授权和生产读回完成前声明 live。产品层级与页面合同见 `docs/product/PRODUCT_PLANES.md` 和 `docs/product/PUBLIC_SURFACE_MAP.md`。

公共产品、内容与前端合同以 `docs/PRODUCT.md`、`docs/product/` 和 `docs/design/public-data-product-system-v1.md` 为事实源。变更导航、内容语义、套餐/加购、示例 API、用户可见授权或视觉系统时，同批更新这些文档；没有对应 backend 合同时必须显式标记为 proposal，不能伪装为已实现。

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

`stable` 缺失只能阻止稳定生产声明、无界扩容或相应发布切换，不能单独阻止已受控启用的隔离只读采集、后续普通数据集的 registry/config、编译、测试、候选 PR，或 TA 的受控消费开发。观察期 timer 的启用不是 `stable` 声明，仍受 provider 权限/预算、SQLite receipt、认证 API 回读和 fail-closed 完整性约束。任何层级都不得由 HTTP 200、历史记录、代码合入或任务卡伪造。Vendor/input quality is immutable external：合同正确时的 empty / `provider_error` 是外部 blocker，不是该层未完成，也不得冻结下一可接接口或发明额外 release gate。

## Tushare 复用

- 普通接口复用统一 `api_name + params + fields -> fields/items` transport。
- `provider=tushare` 表示数据合同与上游能力，`transport_service=quicksync` 表示当前账号实际使用的兼容传输服务；两者不得混为同一个身份，也不得把 QuickSync 写成新的 dataset provider。
- Tushare 官方接口清单、输入字段、输出字段和更新说明只作为 dataset/schema/cadence 参考，从固定官方目录与批量官方文档快照生成；禁止逐接口复制文档或手写同构合同。生成结果必须记录来源 URL、内容哈希和未解析项。
- QuickSync 的实际 endpoint、认证方式、权限返回、限频、并发、错误码和连接约束才是当前 runtime transport 的事实源。官方 Tushare 积分、频次或直接 endpoint 不能替代 QuickSync 的运行证据。
- 新增普通 dataset 只能修改 registry/config，不得增加 dataset-specific collector、业务表、scheduler 分支、query 分支、fixture 分支或公共 route。
- 请求差异只通过四种通用 request shape、variants、fanout、pagination 和 budgets 声明。
- 只有 transport/auth/pagination 协议真实不同，才增加 provider-level adapter。
- provider payload 必须无损保留；未知字段标记 schema drift，不能静默删除或改写。
- **复杂度止损：** 新一批普通 Tushare dataset 先用批量 matrix + registry/config 完成；只有证明现有四种 request shape、九种 cadence class 和通用 SQLite adapter 无法表达时，才允许讨论 Python 改动，并须先记录可复现的配置表达缺口。
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

**客户门户**：`GET /portal/api/me`、`GET /portal/api/me/usage?days=N` 与
`GET/POST/PATCH /portal/api/me/keys*` 让任意有效 token 查看自身套餐/限额/用量，
并让 token-hash credential 查看、创建和停用同租户非当前 API key；仅返回本租户数据，
新 key 继承当前有效权限且原始值只显示一次；不计日配额、不做
scope 检查（门户自加载不烧客户配额），但完整认证与该档位适用的分钟/小时频率限制
照常执行；并发限制只适用于存量档位。
路由冻结白名单已显式登记这些 `/portal/api*` 字面量（见
`tests/test_v1_api_clean_slate.py`）。合同详见 `docs/API.md` Customer Portal API。

**前端角色合同**：公共网站的既有 `Account` 是唯一客户账户界面，客户 token 在这里
读取自身套餐、有效期、授权与用量；`static/app/` 只保留管理员工作台，客户 token 必须
被拒绝并引导回官网 Account。带 `admin` scope 或 `internal` tier 的 token 才能进入管理
工作台；管理员不在该应用内切换或冒充客户视角。产品与设计合同见 `docs/PRODUCT.md`
、`docs/design/console-product-system-v4.md` 和
`docs/design/console-productivity-v5.md`、`docs/design/console-resilience-v6.md`、`docs/design/console-workspace-v7.md`。前端页面定位使用 hash route，避免 Pages
刷新依赖 SPA fallback；排序、筛选、列布局和控制台体验计数只保存在当前浏览器，禁止
写入 Token、tenant、dataset、请求体、响应内容或设备标识，也不得发送到服务端。

**前端构建**：管理台/门户的 React 源码在 `frontend/`（Vite + TS + Tailwind），
构建产物提交在 `static/app/`（`base: '/app/'`），随 `static/**` 由同一 Pages 通道发布，
生产 URL 为 `tradingdatas-admin.pages.dev/app/`。旧单文件控制台 `static/index.html`
保留为回退入口。改前端后需在本机重新构建并一并提交 dist：
`cd frontend && npm ci && npm run build`（输出直接落到 `static/app/`）。
千级采集目录的本地响应式/虚拟滚动验收使用 `cd frontend && npm run mock-api:stress`，
它只生成内存中的 mock collection rows，不得作为生产数据规模或运行健康证据。

**公共前端开发规范**：当前 `frontend/` 是已认证 console；公共 Data/Features/Recipes/Research/Pricing/Docs/Account 不得未经路由与部署合同直接塞进 operator workspace。公共页面可以复用 design tokens、排版、按钮、输入、代码块、图表和无障碍原语，但 acquisition、数据发现、外部文献整理、教学内容、Agent 接入、checkout 与 authenticated operations 必须保持任务边界。所有新页面至少验证 desktop/tablet/mobile、键盘焦点、reduced motion、loading/empty/error/expired/trial-ended、长中文/英文/代码溢出、语言切换与 synthetic/observed/product-definition/planned 标识。不得在 fixture、截图、localStorage、analytics 或静态 bundle 中放真实 token、客户响应、provider payload、生产状态或未经实现的价格/授权。

Token 配置（`config/api_tokens.json`）支持扩展字段：

- `enabled`（bool）：是否启用，默认 true
- `expires_at`（RFC3339/Unix 时间戳）：token 有效期
- `daily_limit`（number/null）：仅供存量档位使用的每日请求上限；商业三档不接受非空值

`tier` 档位与请求频率（`auth.py` 常量）：

- 商业三档：`basic`/`standard`/`flagship` 分别为 200/600/1000 次/分钟，采用滚动 60 秒窗口；不设每日额度或商业档并发上限。
- 存量档位不变：`free`/`starter` 60 次/小时、`research` 300 次/小时、`pro` 600 次/小时；
  `enterprise`/`internal` 不限频率。

`enforce_rate_limit` 对商业档执行分钟窗口、对存量档执行小时窗口；`enforce_daily_limit` 只对存量档形成每日额度拒绝，商业三档仍记录逐日请求趋势。

**限流键与前置墙**（2026-08-24 起）：所有 per-IP 前置墙以**客户端真实 IP** 为键——公网流量经 Cloudflare 橙云代理回源时，TCP 对端是 CF 边缘而非客户，`api_server._effective_client_ip` 仅在 peer 属于 CF 回源网段时信任 `CF-Connecting-IP` 头（头缺失/畸形则回落共享边缘桶，防伪造）。前置墙是独立的安全防刷边界，不是商业套餐额度，默认 1200/60s 并高于最高商业档 1000/60s：`auth._PREAUTH_MAX_ATTEMPTS`（env `TRADINGDATAS_PREAUTH_RATE_LIMIT`）、`api_server._AUTH_ATTEMPTS_PER_WINDOW`（env `TRADINGDATAS_AUTH_ATTEMPT_RATE_LIMIT`），loopback 豁免仅 api 层有。

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

只允许九种通用 cadence class：`session_minute`、`postclose_daily`、`daily_reference`、`prior_open_morning`、`weekly`、`monthly`、`quarterly_reporting`、`event`、`on_demand`。`prior_open_morning` 在本地 08:30 之后请求上一开市日；它表达交易所次日早晨发布的 T+1 日频窗口，不是 dataset 专用分支。

`on_demand` 数据集在 receipt 投影中永远不判 stale（success 与 empty 观测均豁免 freshness SLA）：按需查询语义没有刷新预期，`freshness_sla_seconds` 是 registry 通用字段而非刷新承诺。投影的 attempt/execution 完整性校验必须在 `data_through_in_future` 过滤之前的完整 receipt 集合上执行；否则同 execution 中被 future 过滤移除的行会造成 call_index 断档，级联误报 `receipt_execution_inconsistent` 掩盖真实根因（生产 `cn.news.flash` 曾因此误报）。

当前/最新分区优先，历史回填有界并在后台运行。调度从 registry、SQLite facts 和可信 receipts 推导缺口，不以最近一次运行时间假装数据完整。账号级、provider 级、API 级预算必须跨 dataset 生效。

`resumable_fanout` 默认为 `complete_window`。显式 `session_day_rotation` 必须校验完整本地日、非空业务身份及真实 provider 时间；`partition_continuation` 只能在原预算内轮换当前日期与匹配合同回执证明已开始的旧日期，并保留有限续采期限外的债务。新 config/universe 不能借用旧进度；不得将轮换、空回执或过期停止续采声明为完整覆盖。具体合同见 `docs/OPERATIONS.md`。

QuickSync 的账号级限频、每日额度与并发上限在证据冻结前不得启用自动调度；历史回填也不能绕过同一 transport budget。

普通接口接入按同一批次推进：先批量探测并分类权限/参数/空响应，再按 data class 批量冻结 cadence 与 window，随后用同一个 runner 做有界入库和 API readback。不得为单个 API 单独创建任务流、测试栈、service、timer、route 或发布流程。

当前交付采用广度优先：valid rows 与 receipts 立即保留和积累；单个 dataset 的 empty、partial、429、provider `5xx` 或 cadence 失败只降级该 dataset。合同正确时记外部 blocker 后 MOVE ON，不把源质量当成工程未完成，也不为等源变好冻结队列。locked、excluded、unknown 或 required params 未解决的 dataset 显式暂停。稳定性继续按 dataset 独立积累，不能被用作延迟全部接口接入的全局门禁。

**Datas PM 接入口径（2026-09-05 Asia/Shanghai）：** 上游晚发、缺行、限频、文档≠现实、间歇 `provider_error` 是外部 blocker，不是工程未完成；合同正确时必须单独列出，不得停止下一可接接口，也不得计为进度 slip / 未完成。优先最小诚实合同（request shape + cadence + empty≠success）；除非否则无法得到 SUCCESS，否则不得新增 cadence class、VIP transport、完整性重写、worker 上调或 catalog 超时变更。双认证 catalog <15s 仍是既有部署安全门，不发明额外 release gate。盘中生产行为变更默认 WIP=1，但 vendor emptiness 不得冻结队列。我们拥有 registry/shape、cadence/planner、fanout、activation、merge→GZ cut，以及 vendor 实际返回行时的非空 SUCCESS；不拥有把 vendor 数据变好、伪造非空、把 empty 写成 success，或等源“变稳定”再发。对齐 Tushare 的是 dataset/coverage 菜单，不是其 ad-hoc API 交付模型；empty receipt 不是 success，但合同正确时的 empty/`provider_error` 是外部事实，不是重设计理由。正确合同上 GZ 后，vendor-side empty/`provider_error` 只记短外部-blocker 行并继续下一可接接口；仅内部 shape/cadence 错误才重开。**Daily acceptance = actual GZ deployment, not GitHub merge alone**（merge 而未 GZ cut = incomplete；每日验收 = GZ running SHA + 适用时 dual catalog <15s + proving receipts；`STATUS.md` / `main` tip 不是验收）。排期：核心可接 2026-09-11、其余 vendor-reachable 2026-09-18、fund/fut/opt 另波、硬底线 2026-10-09 或已列外部 blocker；约每个交易日 2–3 个接口，不得因源质量滑期。本口径不是 mass-unpause。完整运维正文见 `docs/OPERATIONS.md`「Datas PM 接入口径」。

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

## 运维与诊断纪律

- 读模型 SQLite 的权威表只有 `provider_dataset_rows` 与 `market_ingest_runs`；允许的表结构与索引以 `storage/schema_contract.py` 为唯一合同源，包含其显式登记的事实/收据读取索引。未登记的表、索引或视图及不兼容定义仍 fail closed；不得因旧文档的“两个对象”表述删除合法索引。运维备份、统计和诊断一律用库外 ATTACH 临时文件完成，不在业务库内创建中转对象。
- 比较任何时间戳前先统一时区与格式：数据行内的本地时间是 naive 墙钟，采集回执时间是 RFC3339 UTC（含 `T`/`Z`）；必须先换算到同一时钟再比较，禁止直接字符串比较。SQLite 中 RFC3339 字符串与 `datetime('now')` 的空格格式不可互比。

## 并行协作

registry/ingest、query/API、scheduler、deploy/docs 可在接口冻结后并行，但写域不得交叉。同一 schema、公共合同或 authority 只能有一个 owner。协作者不得自行 commit、push、deploy、改 production 或删除数据。

## Git、发布与删除

- 开工先检查 branch、status、remote、HEAD 与并行 worktree。
- **合入门禁：** 一切变更走 feature 分支 + PR，禁止直推 main。自动合并仅在作者为可信同仓 `NicholasHan1226`、非 fork、非 draft、base 为 `main`、精确当前 head 的 TradingDatas CI 成功、且 Datas PM 已打上 `pm-merge` 标签时发生。`controller-accepted`、`AUTODEV_RETURN_V1` 评论、`automerge-m0` 与 `change_class=M0` 文书已退役。自动合并必须等待 GitHub 的真实 merged SHA，再调度该 SHA 的 main CI；若本次改动含 `static/**` 或 `public-web/**`，同一流程显式调度该 SHA 的 Cloudflare 发布，因为 Actions 身份合并不可靠地重新触发 push workflow。各层 CI、服务器、有效 release、runtime、receipt 和消费者 readback 独立结论：下游未完成只阻断对应发布/运行声明。自动化绝不替 owner/PM 改写候选分支。修改 `.github/workflows/**` 的 PR 永不自动合并，需 Datas PM 在 CI 通过后经 GitHub 单独合并。CI 在 push main 后补跑不构成豁免：直推意味着坏代码可能已在 main 上并被服务器 5 分钟内拉取。本地测试通过不能替代 CI 门禁。GZ/immutable runtime 不会因 GitHub 合并而自动部署。
- GitHub 传输优先使用 Nicholas 已登录的 `gh` HTTPS 凭据链：先核对 `gh auth status`，仓库 `origin` 固定为 `https://github.com/NicholasHan1226/TradingDatas.git`。若 `git@github.com` 的 SSH/22 端口失败一次，不重复重试或上报为长期 blocker；立即验证 HTTPS `git ls-remote`，切换现有 remote 后 fetch。不得输出 token，也不得另建凭据或绕过 host-key 校验。
- 不覆盖他人改动，不使用 `git add .`、force push、历史重写或破坏性 reset。
- local、GitHub、production files、runtime、真实 provider receipt、API readback 和消费者调用分别验证。
- 删除旧代码/文档必须确认它不属于新运行面；删除生产 service/cron 必须先完成新系统切换与回滚证明。
- 不提交或删除数据库、token、日志、receipt、history、evidence、rollback artifact 或 `.codegraphcontext`。

## 文档入口

- `README.md`
- `docs/PRODUCT.md`
- `ROADMAP.md`
- `STATUS.md`
- `docs/ARCHITECTURE.md`
- `docs/API.md`
- `docs/OPERATIONS.md`
- `docs/adr/ADR-0010-tradingdatas-clean-slate.md`
- `docs/AUTHORITY_AND_HISTORY.md`
- `docs/reports/`

架构、API、运行路径、环境变量、频率或发布边界变化时，代码与上述文档同批更新。旧计划和事故说明不保留在当前树，必要追溯使用 Git 历史。
