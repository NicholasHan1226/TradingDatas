# TradingDatas 当前状态

观察时间：2026-09-05 21:24 Asia/Shanghai。源码、公开网站、数据运行面、真实商业开通分别验收；历史快照由 Git 保存。

## 对外范围与前后端整合

- Nicholas 确认 Crypto 仅内部使用，不计入公共产品、来源候选、套餐、供数数量或接入排期；独立内部采集继续。Research 可保留外部加密资产文献，不映射为对外供数承诺。
- [PR #498](https://github.com/NicholasHan1226/TradingDatas/pull/498) 合入 `a3106d68b19d528c31be775b808665833ed8c4e3`；候选 [33967381204](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33967381204)、精确主线 [33967864444](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33967864444) 四组检查全部通过。
- 公开 Data/产品介绍无需登录；真实状态通过账户 `/api/account/catalog` 使用当前用户已有 key 读取，展示全部授权境内/新闻接口的 state、coverage、receipt/reasons 和读取时间。21 个产品导航绑定正式原始 dataset；38 个产品定义不等于 38 个已完成加工产品，也不等于可返回非空数据的接口数。
- `pledge_stat` 小页 503 已修复：一次排除同一已验证失败 execution 的全部成功前缀，避免逐项耗尽排除循环；不放宽失败批次、lineage 或查询预算。
- [PR #499](https://github.com/NicholasHan1226/TradingDatas/pull/499) 合入 `e251ae7be29981646fb8bb2223da9e64fa255aa4`，仅调整公共账户目录传输等待并更新构建/API 文档。候选 [33968276279](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33968276279) 通过；发布后精确主线 [33968738191](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33968738191) 待最终确认。
- Cloudflare [33968739190](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33968739190) 两项发布成功；正式 `/data` 资源 `index-CoboUdjE.js` 一致。账户目录上游等待与已有公共网关统一为 30 秒，浏览器为 45 秒，仍 no-store、身份隔离、失败可重试；不增加采集预算或修改数据面性能目标。
- 21:24 正式公网使用既有内部验收权限：会话 200，目录 200 / 12.410 秒 / 192 项，192 项均有 runtime 与 coverage，Crypto 0；质押统计查询 200 / 3.516 秒 / 1 行、partial、lineage complete；退出确认 200。此为既有权限链路，不是普通客户商业购买证明。

## 数据运行、质量与性能

- A 股与内部 Crypto `current` 均为 `a3106d68b19d528c31be775b808665833ed8c4e3`，各 1086 文件清单验证通过。发布等待在途采集自然结束，未强杀 collector；两项 API 启动与原有 timer 状态恢复均通过。回滚 release `a093d407d23fe6cf7f82c1fb2a27359c82b7d803` 保留；恢复写入后的回滚必须重新自然 drain。
- 隔离候选全新进程认证目录：境内 200 / 14.346 秒 / 192 项，内部 Crypto 200 / 8.510 秒 / 240 项。正式切换后 21:22 回读：境内 200 / 6.080 秒，内部 Crypto 200 / 7.915 秒；质押统计 200 / 0.912 秒 / 1 行，partial/degraded、lineage complete；两个 current 在回读前后不变。
- 境内/新闻目录状态快照为 success 92、paused 55、empty 39、stale 3、unobserved 2、failed 1。它们是当前采集状态，不是 192 项都能返回非空，也不是连续稳定或商业可售数量。内部 Crypto 240 项不纳入对外统计。
- 先前 27 项默认空查询复核为 26 项 provider_returned_no_rows 与 1 项 provider_error，不伪造非空、不把它们算作 27 项工程未完成。源 empty/partial/stale/provider_error 按合同展示，不冻结其它接入、开发或发布。
- 性能仍需优化：本轮早期隔离境内目录出现 19.739 秒，公开账户目录出现 503/504；独立 profile 未重现固定慢函数，现场有 I/O 等待与采集竞争，相关性不是完整因果结论。后续成功读回不抹去繁忙时段超时，不宣称已持续稳定。
- 一次诊断在旧 A 股 release 留下 15 个 Python 缓存；已保存到库外、验证全部 1056 个正式文件未变并仅清除该批缓存，恢复不可变目录验证后才发布。未改业务数据或凭据。另一次 Crypto 启动检查因探针等待短于原有初始化窗口而提前终止；已修正诊断等待并以真实启动/认证回读通过验收，没有放宽服务性能门禁。
- 本地验证：346 项相关 Python 测试、321 项公共站测试、最终 29 项账户桥接/目录测试通过，生成构建通过。独立规则发现/代码审查，以及合成桌面、390/768px、中英/明暗、加载、身份切换、失败重试、空结果与查询示例检查完成；实际公网访客页面与授权 HTTP 链路另行验证。

## 接入计划与下一批

计划唯一入口：[运维：可执行排期](docs/OPERATIONS.md#可执行排期不得因源质量滑期)。当前 190 个 Tushare 注册接口为 136 active、54 paused；另有 2 个新闻接口。54 个 Tushare 暂停中：34 个已有权限、14 locked、5 excluded、1 unknown。另有 25 个 current 未注册候选与 7 个 retired；后者不列入当前交付队列。

- 先推进同时满足实际 probe executable 与 ingest ready 的 3 项：`fut_daily`、`opt_basic`、`stk_nineturn`。
- 紧接着复核 12 个仅被数量边界完整性疑虑暂停的合同：`bc_otcqt`、`dc_concept_cons`、`dc_member`、`etf_sz_cons`、`fund_daily`、`fund_nav`、`fut_holding`、`fut_wsr`、`index_basic`、`index_weekly`、`kpl_concept_cons`、`opt_daily`。真实有限覆盖可以如实 partial/unverified，不要求先证明全量。
- `bak_daily`、`fund_adj`、`fund_manager` 目前只是 limit=1/offset=0 探测合同，先补实际分页或窗口。其余 seed、请求锚点与必要参数按依赖推进。12+3 属于待复核/修正，不是本轮已激活。
- compiler 仍存在把整千数量边界直接升级为 activation blocker 的行为，尚未在本轮修改；其与有限覆盖政策的差距列为下一批优先通用合同修正。不能直接清空 blocker、批量 unpause，或把失败 receipt 改成成功。
- 9 月 11 日、18 日、10 月 9 日是检查节点，不是全量上线保证，也不是已就绪接口必须等待的发布日期。每交易日 2–3 项仅容量参考，不是限额；非交易日照常开发、复核、回填和发布，采集按 cadence。

## 账户、订阅与未完成项

- Docs 保留 13 个公开地址及双语内容，入口仅在账户菜单/工作区，顶栏为 Data、Research、Pricing。订阅/订单账本与既有数据权限分开；账本不可用不阻断登录、已有 key 连接、有效期和用量。
- 生产未绑定 commerce 数据库或测试模式，不能创建订单、收款或发放新权限。本地持久化模拟器覆盖幂等、重复事件、开通失败重试与重启读回，但不是支付服务商 sandbox 或正式交易。
- 待指定真实验收邮箱、普通客户数据权限及既有商户/支付渠道，完成验证码送达、购买/续费/开通验收；尚未代发真实邮件、创建客户 key 或执行付款。
- Python-urllib 默认标识曾遭边缘 403；requests/Node/curl 的结果不同，具体边缘规则仍待具备查看权限的会话核对。不能将它冒充数据源故障或已修复。
- `api.tradingdatas.com` DNS 未配置不阻断官网同域接口；#395 settlement identity/迁移草稿不在本轮范围。后续工程优先项为有限覆盖合同修正、下一批就绪接口，以及繁忙时段目录与公网转发耗时。

长期合同：[API](docs/API.md)、[架构](docs/ARCHITECTURE.md)、[运维](docs/OPERATIONS.md)、[账户与订阅](docs/design/customer-identity-commerce-v1.md)。当前页记录本轮证据，旧状态由 Git 历史追溯。
