# TradingDatas Roadmap

## 最终目标

TradingDatas 优先成为稳定运行的金融数据底座，并在同一事实链上逐步形成公共数据产品：属于当前产品范围、且上游能力已经通过真实调用证明可用的数据集，应尽快沿统一链路持续积累数据，并由客观证据自动提升可用等级，而不是等待采集、商业化和完整网站一次性完成。

统一数据链：

```text
provider
-> provider-level adapter
-> provider-native validation
-> SQLite facts + transaction-scoped receipt
-> runtime metadata projection
-> GET /v1/catalog + POST /v1/query
-> authenticated consumers
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
- 自动晋级只能扩大“内部只读数据可用性”和既有预算内的调度范围，不能绕过 provider 权限、资源预算、我们自己的 receipt 完整性（empty ≠ success）或安全边界。Vendor/input quality is immutable external，不得把上游 completeness 当成晋级或排期门禁。
- GitHub Actions 是可选验证渠道，不是生产上线门禁。Actions 不可用时，以本地/服务器确定性测试、候选 release 校验和生产 runtime readback 作为发布证据。
- 公共 Data/Features/Recipes/Research/Pricing/Docs/Account 可以在合同层和前端候选中独立推进，但不得在运行面、commerce、授权、再分发和 production readback 完成前伪装为 live，也不得阻断既有数据持续运行。
- **Datas PM 2026-09-05：** 对齐 Tushare 的是 dataset/coverage 菜单，不是其 ad-hoc API 交付模型。TradingDatas 仍是 agent-first catalog+query 事实层；empty ≠ success。
- 上游晚发、缺行、限频、文档≠现实、间歇 `provider_error` 是外部 blocker，单独列出；合同正确时不停止下一可接接口，也不计为进度 slip / 未完成。
- 优先最小诚实合同（request shape + cadence + empty≠success）。不得为“等源变好”新增 cadence class、VIP transport、完整性重写、worker 上调或 catalog 超时变更；双认证 catalog <15s 仍是既有部署安全门。
- 我们拥有 registry/shape、cadence/planner、fanout、activation、merge→GZ cut，以及 vendor 实际返回行时的非空 SUCCESS。我们不拥有把 vendor 数据变好、伪造非空、把 empty 写成 success，或等源“变稳定”再发下一可接接口。
- 正确合同上 GZ 后，vendor-side empty/`provider_error` 只记短外部-blocker 行并继续下一可接接口；仅内部 shape/cadence 错误才重开。盘中生产行为变更默认 WIP=1，但 vendor emptiness 不得冻结队列。完整口径见 `docs/OPERATIONS.md`「Datas PM 接入口径」。
- **Daily acceptance = actual GZ deployment, not GitHub merge alone.** Merge 而未 GZ cut = incomplete。每日汇报 / 验收 = GZ running SHA + 适用时 dual catalog <15s + proving receipts（vendor 返回行时非空 SUCCESS）。`STATUS.md` / `main` tip 单独不是验收。
- **可执行排期（vendor-external，不得因源质量滑期）：** 核心可接接口 2026-09-11 前；其余 vendor-reachable 2026-09-18 前；fund / fut / opt 另波；硬底线 2026-10-09 前全部可积已上 GZ 或已单列外部 blocker。节奏约每个交易日 2–3 个接口。

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
- 统一使用九类 cadence：`session_minute`、`postclose_daily`、`daily_reference`、`prior_open_morning`、`weekly`、`monthly`、`quarterly_reporting`、`event`、`on_demand`；
- 当前数据优先，历史回填只使用版本化、有预算上限、可中断续跑的 manifest；
- activation wave 在执行前必须能从同一 registry 生成非零且有界的计划，但不要求人工逐项批准。

退出条件不是“所有接口都 stable”，而是：每个已进入运行范围的数据集都有明确合同或明确 blocker；已证明可用的数据集能够持续采集和供内部消费者使用。vendor-side empty / `provider_error` 算明确外部 blocker，不算工程未完成，也不阻塞下一可接接口。Phase 1 的可执行日期底线见上节：2026-09-11 / 2026-09-18 / fund·fut·opt 另波 / 2026-10-09；不得因 vendor quality 滑期。GitHub merge 不是 Phase 1 完成；GZ `current` + proving receipts 才是。

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

## Phase 4 — 公共数据产品定义与内测入口

公共产品继续销售同一份 receipt-backed 原始数据，不建立研究、策略或交易旁路。

账户独立身份与购买开通的实施前合同、待确认商业选择及验收顺序见
[Customer identity and commerce draft](docs/design/customer-identity-commerce-v1.md)。
手机与邮箱双登录、99/299/499 月价及年付九折已由 owner 确认；
该草案不代表已选定验证码/支付服务，也不构成真实收费授权。

- 冻结 Data / Features / Recipes / Research / Pricing / Docs / Account 的对象、索引页、详情页和状态词；
- 完成 `zh-CN`/`en` 系统语言检测、显式切换、偏好持久化、English fallback 和技术标识不翻译合同；
- 建立 Claude、Codex、OpenClaw、Hermes 和其它 HTTP Agent 的单一 canonical prompt 编译合同、密钥隔离和连接测试状态；
- 先完成一条 A 股付费价值纵向切片：provider-native evidence -> canonical/PIT 定义 -> 可复现 Recipe -> 私测交付；广泛 provider 扩展不作为公共商业叙事的前置条件，但既有受控采集继续独立运行；
- 以 dataset-detail 页面连接 schema、覆盖、cadence、lineage、样本、限制、API 示例和相关 Feature/Recipe；
- Future Feature Plane 只承载透明、版本化衍生数据；先冻结公式、输入、as-of、缺失/修订、测试与 lineage，再讨论运行时实现；
- Recipes 只提供查询、连接、as-of 对齐、复权、缺失处理和验证方法，示例结果标明 synthetic/observed，不发布研究结论或策略绩效；
- 冻结少量完整基础套餐与另类数据 add-on 的 server-side entitlement 映射；试用到期默认停止且不自动收费的目标只有在 commerce 实现和读回后才可对外承诺；
- 第三方数据逐类完成使用/再分发权、provider contract、真实 receipt/API readback 和 account entitlement；
- 实现网站账户与 API key 分离、订单/订阅/发票/webhook 幂等和客户自助 token 管理；commerce 数据不写入金融 facts SQLite；
- 在支付和授权完成前，公共商业 CTA 固定为非支付购买预览（`/pricing/preview`），支付按钮保持禁用；不得把显示价格写成可立即购买，也不得恢复已移除的 beta 申请表作为开通路径；
- 公共前端按 `docs/product/PUBLIC_SURFACE_MAP.md` 与 `docs/design/public-data-product-system-v1.md` 完成 desktop/tablet/mobile、无障碍、错误/空/到期/试用结束状态和真实浏览器视觉验收。

退出条件分两步：先让内测客户可以从 Dataset/Feature/Recipe/Research 关系理解产品并申请匹配的 A 股数据访问；随后在 commerce 实现后，客户可以购买已获授权的数据套餐、读取真实 entitlement，并用可复现 Recipe 正确准备数据。网站、commerce、数据 runtime 与生产 readback 仍分别有可验证证据。

## 文档与历史

文档职责固定，避免重复维护同一事实：

- `README.md`：产品定位、快速入口和稳定架构概览；
- `AGENTS.md`：自动开发/修改的硬规则；
- `ROADMAP.md`：未来优先级，不记录瞬时生产状态；
- `STATUS.md`：当前状态摘要，不作为长期事件日志；
- `docs/ARCHITECTURE.md`：稳定架构；
- `docs/API.md`：接口合同；
- `docs/OPERATIONS.md`：部署、恢复、运行操作，以及 Datas PM 接入口径（外部 blocker ≠ 未完成）；
- `docs/product/PUBLIC_SURFACE_MAP.md`：公共对象、导航、分类内页与详情页合同；
- `docs/product/PRODUCT_PLANES.md`：当前 Evidence Plane 与目标 Product/Feature/Recipe planes；
- `docs/design/public-data-product-system-v1.md`：公共产品、商业页面与前端视觉开发合同；
- `docs/adr/`：影响未来实现的长期决策；
- `docs/reports/`：需要人工可读保留的日期化 readback、事故与验收报告；
- SQLite receipts、runtime logs/evidence：机器运行历史，保存在运行数据面，不复制进 Git 文档。

普通代码演进由 Git 历史保存；只有会长期约束未来实现的决定才写 ADR。详见 `docs/AUTHORITY_AND_HISTORY.md`。

## 后续评估

公网产品按 Phase 4 的独立合同推进，不改变当前数据持续运行的优先级。若新增 provider，优先复用现有 registry/receipt/query 链；只有 transport、auth、payload 或 pagination 协议确实不同，才增加最小 provider-level adapter。公共页面、套餐、Feature 或 Recipe 均不能成为新增专用 route、数据表、collector、timer 或 provider 业务分支的理由。
