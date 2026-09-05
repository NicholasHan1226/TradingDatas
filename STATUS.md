# TradingDatas 当前状态

观察时间：2026-09-05 18:39 Asia/Shanghai。本页是可替换的运行快照；源码、运行版本、数据状态和外部入口分别核验。

## Doc 入口调整

- 2026-09-05 后续用户确认：顶栏仅保留数据、研究、套餐；原“帮助与接入”入口改名为 `Doc`，放在账户菜单和账户工作区，桌面与移动端主导航均不显示。`/docs` 与接入教程仍可免登录访问。对应产品、设计与前端规则同批更新；本节描述变更范围，发布证据以下方既有记录及本次 PR/CI 为准。

## 公开导航与登录流程（18:39 发布记录，导航标签以上节为准）

- #490 已合入 `0a3753128ff54024305c16ea45a5d6eb8ca06f3c`，最终候选 `ddc43562` 四组 CI 与 Cloudflare 发布 [33961142751](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33961142751) 通过；精确主线 CI 见 [33961142792](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33961142792)。
- 顶栏为数据、研究、套餐、帮助与接入；`/docs`、文档详情、`/connect`、`/bookmarks` 公开，语言/外观直接在右上菜单切换。账户只保留个人概览、订阅、用量、密钥、账单与安全。
- 18:39 正式浏览器资源 `index-BJ4iKG44.js` 匹配发布。未登录 `/account` → `/login?next=%2Faccount`；`/account/subscription` → 保留该分区的登录页。公开帮助、接入、收藏直接访问通过。没有发送真实验证码或执行客户操作。
- 私有路由先验证未知会话，仅确认 guest 后跳转；不可用显示重试。本机收藏独立于身份状态，不自动上传或切换云库。云收藏 adapter/后端仍保留为未启用候选，当前 UI 不提供云导入。
- 289 项 public-web 测试、构建、diff 与相关文档渲染通过；合成邮箱登录回原密钥分区、退出、身份 503 时公开收藏和刷新保留、中英明暗、390px 手机菜单/768px 平板布局、菜单互斥及 Esc 焦点回归均已验证。新上下文规则发现通过。本轮只改公共网站与文档，没有数据库迁移或采集运行切换。

## 账户与对外接口

- 账户整合 #487 已合入 `122208dd37ce97fdd45ae6230ddffd8e48a3cbba` 并由 Cloudflare 发布。Account 的「订阅与数据访问」连接已有密钥，读取后端有效套餐、有效期、数据分类、用量和密钥管理；邮箱身份不因数据权限不可读而退出。未读取到权限不表示取消订阅或零用量。
- 身份 D1 应用既有账户 schema：两表、两触发器与外键检查通过；用户/会话前后均为零。connection/email/retention 已启用，library/admin 保持禁用；原秘密配置名称保留。回退可关闭 connection 并恢复前版 Worker，保留追加 schema 与账户禁用撤销触发器，不回滚金融数据或已发密钥。
- 同域数据入口 #488 合入 `d2e8d30b02621c0b5f16c0cddc8c0cf136b9c89a` 并发布：`https://tradingdatas.com/v1/catalog` 与 `/v1/query`。默认 Agent 地址同步，独立 api 子域名不再是此入口的前置条件。当前仅转发既有 A股数据面，未聚合隔离 Crypto 数据面。
- 网关只转发调用者 Bearer；不使用邮箱 Cookie、已连接的账户密钥或内部凭据代替调用者。JSON/receipt/错误语义与 no-store 保留，查询体固定原字节与 Content-Length，最多 64 KiB，传输截止 30 秒；这不修改既有目录性能目标。
- 17:56 官网实测：guest catalog/query 为 JSON 401、未知路径 JSON 404、OPTIONS 204、无效测试密钥 401，均 no-store。实际浏览器资源 `index-BAaUY0e4.js` 与发布版本匹配；这证明路由和认证拒绝，不是普通客户成功查询。
- 最终候选本地 287 项 public-web 测试与构建通过；真实 workerd 验证原查询字节、Content-Length 与 Cookie 隔离；文件配置和环境覆盖通过。实际浏览器覆盖 synthetic 邮箱/已有密钥连接、中英明暗账户及 390px 页面。账户 #487 候选与精确主线 CI 均通过；网关 #488 候选四组 CI 与 Cloudflare 发布均通过，精确主线 CI 记录为 [33959241069](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33959241069)，状态以该运行读回为准。
- 真实用户的验证码送达、本人连接密钥和普通客户 catalog/query 成功读回仍待验证；未代发真实邮件、创建真实客户凭据或执行付款。在线支付继续暂停；这里交付的是已有权限管理，不是新购、续费或正式订阅账本。

## 不可变数据运行与质量

- #485 运行基线 `a093d407d23fe6cf7f82c1fb2a27359c82b7d803`。16:44 发布轮 A股/Crypto current、1056 文件清单及实际进程已核验，11 个定时器恢复。此轮账户/Worker 不切换这两个运行面。回退代码 `3ad50fc4ca325dea25b49914d5d6189e860cf033` 保留，不回滚数据。
- 前轮目录 A股 192 项、Crypto 240 项身份摘要一致；A股首次 15.591 秒、后续 4.332 秒，Crypto 7.793 秒。此轮 17:35 既有账户上游 A股目录认证 200/17.998 秒/192 项，数据库路径与目录身份一致；财务查询继续 partial/degraded 且 lineage 完整。
- 冷读仍未满足 15 秒性能目标，有限读回不是持续 SLA。当前服务输出既有质量事实，不通过清除质量条件制造成功；新闻 provider_error、周末时效、未观测和暂停独立展示。
- 源 empty/partial/stale/provider_error 不要求全量 stable 才接入、开发、发布或按合同供数；授权、合同和存储身份校验继续保留。接入口径唯一正文见 [OPERATIONS](docs/OPERATIONS.md)。

## 当前入口与下一步

[API](docs/API.md)、[架构](docs/ARCHITECTURE.md)、[运维](docs/OPERATIONS.md) 保存长期合同；本页记录发布状态，历史由 Git 与 [reports](docs/reports/README.md) 追溯。源码 HEAD 与 immutable runtime 分别读取，不为仅文档提交重启服务。

下一步优先完成真实客户连接及查询验收、缩短目录冷读；支付恢复需明确商户/结算与订阅合同。`api.tradingdatas.com` DNS 尚未配置，控制台登录仍待完成，但既有官网同域入口独立交付。#395 settlement identity/迁移草稿不在本轮范围。
