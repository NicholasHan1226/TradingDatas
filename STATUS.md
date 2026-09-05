# TradingDatas 当前状态

观察时间：2026-09-05 20:25 Asia/Shanghai。本页记录当前发布与运行事实；源码、公开网站、数据运行面和真实商业开通分别验收。

## 账户、订阅与 Docs

- [PR #495](https://github.com/NicholasHan1226/TradingDatas/pull/495) 已合入 `e5e374a24b341fd27bb5b31fc2f98cef20d2d9d4`。候选 [33964732178](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33964732178) 四组检查通过；已发布源的精确主线检查 [33965230844](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33965230844) 补跑四组全部通过；原轮被后续文档合并取消，未将取消写成成功。
- Cloudflare [33965231922](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33965231922) 成功。20:10 正式资源 `index-qtd5VsfW.js` 与发布一致，Docs 公共页面/账户菜单及 `/account/billing` → `/login?next=%2Faccount%2Fbilling` 通过。auth-methods 为 email=true/phone=false；guest commerce/offers/orders 为 JSON 404，明确无效邮箱 session 的 commerce 为 401，guest `/v1/catalog` 为 401，均 no-store；未创建订单。
- 订阅/订单账本与现有数据权限分开显示，账本不可用不阻断邮箱登录、已有密钥连接、有效期和用量。
- 生产未绑定 commerce 数据库或测试模式，不能创建订单、收款或发放新的数据权限。账本未接通明确显示不可确认记录，不将它显示成“从未购买”。
- 独立本地持久化模拟器覆盖订单、价格/条款版本快照、所有权、幂等、重复事件、开通失败重试及重启读回。这不是支付服务商 sandbox，也不是正式购买或续费。
- Docs 保留 13 个公开地址和原有双语目录、正文、搜索内容源。入口仅在账户菜单/工作区，顶栏继续数据、研究、套餐。
- 313 项网站测试、构建/打包及独立审核通过；实际浏览器验证合成邮箱登录返回账单、订单/模拟结算、重启持久化、连接已有密钥、刷新/分区切换、中英/明暗与 390/768px。最终修复重复 React key，实际交互后始终只有一个订阅面板，无控制台错误。
- 补充程序客户端检查：Python requests、Node undici、curl 的标识均得到预期 JSON 401；Python-urllib/3.9 默认标识得到 Cloudflare plain-text 403，具体边缘规则尚未核实。现有 Cloudflare 登录可读取该域名，但规则查询返回 403/10000；浏览器控制台尚未登录。此兼容性问题待具备规则查看权限的控制台会话继续排查，不冒充数据源故障或已修复。
- 真实验证码送达、普通客户本人连接和成功 catalog/query 尚待指定验收邮箱/账户。尚未代发真实邮件、创建客户密钥或执行付款。

## 数据运行与性能

- PR #494 已合入 `3a2e534091079e28d1955ee0a2fca8c1bb1c2590`，精确主线 CI [33964421197](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33964421197) 通过。改动复用同一回执绑定的校验结果，不改存储模式、索引、HTTP 超时或 worker 数。
- 两个候选目录各 1071 文件验证通过。A 股隔离候选实际首次认证目录为 200 / 16.251 秒 / 192 项；Crypto 正常初始化后为 200 / 11.576 秒 / 240 项。A 股尚未达既有 15 秒目标，本轮未切换数据运行版本。
- A 股和 Crypto current 仍为 `a093d407d23fe6cf7f82c1fb2a27359c82b7d803`，各 1056 文件清单验证通过，现有服务 active。本轮只启动并回收独立诊断进程，未更改线上服务、timer、数据库内容或凭据。
- 20:08 现有运行认证读回：A 股 200 / 16.433 秒 / 192 项，Crypto 200 / 6.973 秒 / 240 项；`cn.dataset.fina_mainbz` 查询 200 / 0.286 秒 / 1 行，partial/degraded、lineage complete，两个 current 在读回前后相同。该读回是内部凭据验收，不是普通客户或冷启动验收。
- 源 empty/partial/stale/provider_error 继续分别按合同展示；不以全量 stable 阻断接入、开发、发布或供数。商户配置与消费者验收也不是已有数据服务的统一开关。

## 当前入口与未完成项

长期合同：[API](docs/API.md)、[架构](docs/ARCHITECTURE.md)、[运维](docs/OPERATIONS.md)、[账户与订阅](docs/design/customer-identity-commerce-v1.md)。本轮证据：[账户整合](docs/reports/2026-09-05-account-commerce-integration.md)、[目录优化](docs/reports/2026-09-05-catalog-binding-memo.md)。历史快照由 Git 保存，不再在当前页累积旧导航和发布段落。

剩余：指定真实验收邮箱及普通客户数据权限；明确既有支付渠道/商户、结算币种后接入服务商测试并验收；继续降低 A 股首次目录延迟并完成双并发与实际运行切换；核对并修正 urllib 默认标识的边缘拦截。`api.tradingdatas.com` DNS 未配置不阻断现有官网同域入口。#395 settlement identity/迁移草稿不在本轮范围。
