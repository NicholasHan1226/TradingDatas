# TradingDatas 当前状态

发布检查更新至 2026-09-05 22:58 Asia/Shanghai。源码、公开网站、数据运行面和真实商业开通分别验收；历史快照由 Git 保存。

## 当前结论与对外范围

- Crypto 仅内部使用，不计入公共产品、来源候选、套餐、供数数量或接入排期；内部采集保持隔离。Research 外部文献不构成 Crypto 供数承诺。
- 两个新接口的按需配置已经合入主线，公开网站已更新；**数据运行版本尚未切换，正式采集批次未执行**。阻碍是本平台目录冷启动耗时超过既有 15 秒发布要求，不是上游 empty 或稳定性不足。
- [PR #501](https://github.com/NicholasHan1226/TradingDatas/pull/501) 合入 `49e5ca9d60a878bcf4712b7ff46975215c817c58`。精确主线 [33971674611](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33971674611) 第 2 次执行通过；首次失败为测试清理与后台 Git 锁竞争，不能写成首次成功。
- [PR #502](https://github.com/NicholasHan1226/TradingDatas/pull/502) 合入 `d1140e914a11b1303173c9e05148d86421a788ac`，修正测试隔离及网站历史文案；精确主线 [33972854145](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33972854145) 四组检查均通过。
- Cloudflare [33972855121](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33972855121) 发布成功，最新资源为 `index-BZtC9up5.js`。来源摘要从正式配置快照派生，显示 Tushare 190 项、138 active / 52 paused；加新闻共 192 项、139 active / 53 paused。这是主线配置数量，**不证明两个 immutable 采集运行面已切换**。
- 来源页日期为 2026-09-05，保留 8 月 27 日历史。新增历史记录只说明按需配置，并引导至账户认证目录查看实际 receipt、覆盖与采集状态，不把探测或配置当作落库证明。
- Data/产品介绍公开；真实状态通过 `/api/account/catalog` 使用当前用户已有 key 读取，21 个产品导航关联正式原始 dataset。38 个产品定义、接口数、非空查询结果和稳定性分别判断。上游等待 30 秒、浏览器 45 秒保持，不构成放宽数据运行发布要求。

## 未切换的运行面与性能诊断

- A 股与内部 Crypto 的 `current` 均仍为 `a3106d68b19d528c31be775b808665833ed8c4e3`。目标 `49e5ca9d` 的暂存 release 已通过 1087 文件清单验证，但未成为 current；两份现行 a310 清单均通过 1086 文件验证，两项 API 与原有 5 个采集 timer 均为 active；未出现新增 on-demand selector 或 batch-result。没有强杀采集、执行新接口正式批次或修改生产权限。
- 目标版本全新进程认证目录三次结果：境内 20.084 / 21.853（受控诊断）/ 17.588 秒，内部 Crypto 12.363 / 8.517 / 7.853 秒。境内持续超出既有 15 秒要求，故停在暂存层；不能以已合并、HTTP 200 或较快的 warm 查询冒充发布完成。
- 新进程 profile 总计 16.857 秒，其中 coverage 9.927 秒。对同样的 15,196,606 行，计数冷读 10.7114 秒、warm 0.5138 秒；分组 warm 0.7666 秒未证明优于现有方案。冷缓存/I/O 是调查方向，尚无完整因果或已解决结论。
- 本次冷启动诊断未新增 SQL、schema、缓存、timeout 或 worker 调整。下一步只做有证据的局部性能修正，保留 receipt/lineage、权限与发布回退边界；繁忙时段目录性能是内部未完成项，不归为 vendor 问题。
- 公网管理服务已随 source 更新至 `d1140e914a11b1303173c9e05148d86421a788ac`，服务于 22:49:58 启动；不可变采集/API current 仍为 a3106d68，不能笼统称所有生产配置仍旧。同次公网目录的 `fut_daily`、`opt_basic` 均为 unobserved、存量 0、`no_recognized_receipt`；查询分别 200 / 1.230 秒 / 0 行、200 / 1.512 秒 / 0 行，lineage incomplete。`stk_nineturn` 仍 paused。管理进程 cwd 为 `/opt/td-admin`，不可变 API cwd 为 a310 release；均无 registry override，两者读取同一 facts SQLite，因此公网读模型使用新 registry、采集/loopback 使用旧 registry。公网新配置不证明已完成采集；回读文件中的 release 字段只是本机 current 指针，不是 HTTP 服务版本证明。
- 同次公网采集状态为 success 93、paused 53、empty 39、unobserved 4、stale 2、failed 1，合计 192。这是瞬时状态，不是稳定或可售数量。
- 当前生产继续使用此前已验证的 a3106d68 查询修复：失败 execution 的成功前缀一次排除，`pledge_stat` 小页不再逐项耗尽排除循环。该修复不放行失败 cohort。
- 本轮来源页受影响 7 项测试与生成构建通过，公开合同快照检查通过。22:49 新公网回读使用既有内部验收权限：会话 200；目录 200 / 24.939 秒 / 192 项，192 项均带 runtime/coverage，Crypto 0；退出 200 确认。该链路不是普通客户商业购买证明。

## 接入证据与下一批

计划唯一入口：[运维：可执行排期](docs/OPERATIONS.md#可执行排期不得因源质量滑期)。主线 52 个 Tushare 暂停中：32 个已有权限、14 locked、5 excluded、1 unknown；另有 25 个 current 未注册候选与 7 个 retired，后者排除当前队列。

- 21:56 在既有 immutable a3106d68 上执行 3 次冻结的串行 HTTPS 探测：`fut_daily` valid_empty；`opt_basic` success / 6000 行（仅 ts_code 字段）；`stk_nineturn` valid_empty。这些是上游权限/请求观察，不是全字段落库 receipt、生产供数或连续稳定证明。
- `fut_daily`、`opt_basic` 通过逐项 preactivation 编译，主线正式配置改为 active、cadence 仍为 on_demand。由于运行版本未切换，正式有界采集、落库 receipt、采集后的认证查询与公网回读仍待完成，不声称已在生产观测。
- 服务器证据位于 `evidence/20260905-ready3/`；冻结计划 SHA-256 为 `e80370da25b922ebe99ea3edbbf7620f733ae31c5ee62b9dee70290cb6d0ac45`。evidence refs 为 `server-evidence/20260905-ready3-fut_daily` 与 `server-evidence/20260905-ready3-opt_basic`；旧探测仍绑定原 immutable，不随新配置回写。
- `stk_nineturn` 保持 paused：datetime 窗口与发布时段合同待补齐，probe/ingest ready 不等于 activation-ready。源 empty 不阻挡其它接口。
- 本地 `codex/cursor-finite-coverage` 已把官方 `index_basic` 市场表写入文档快照（doc 94，`d61a1551…`），并按官方 market / `opt_daily` exchange 收窄请求映射；两者 ingest 仍因 6000 / 15000 行完整性未决保持阻断，未激活。preflight ready 仍为 4 且 paused。**15s 未证明**。**GZ current 仍为 `a3106d68`**。`fut_daily` / `opt_basic` 无生产采集。empty ≠ success。
- 有限覆盖合同下一批优先 `fund_daily`、`dc_concept_cons`：复核真实请求、字段、主键、时间与预算，有限覆盖如实 partial/unverified，不要求先证明全量。`stk_nineturn` 的 datetime/cadence 单独处理。
- compiler 把数量边界直接升级为 activation blocker 的行为仍待通用合同修正；不得直接清空 blocker、批量 unpause 或将失败 receipt 改为成功。`bak_daily`、`fund_adj`、`fund_manager` 的 limit=1/offset=0 探测合同仍须补实际分页或窗口；其余 seed、锚点与必填参数按依赖推进。
- 9 月 11 日、18 日、10 月 9 日为检查节点，不是全量上线保证或已就绪接口最早发布日期。每交易日 2–3 项仅容量参考，不是限额；非交易日继续开发、复核、回填和发布。源 empty/partial/stale/provider_error 如实展示，不冻结独立接入。

## 账户、订阅与未完成项

- Docs 保留 13 个公开地址及双语内容，入口仅在账户菜单/工作区，顶栏为 Data、Research、Pricing。订阅/订单账本与既有数据权限分开；账本不可用不阻断登录、已有 key 连接、有效期和用量。
- 生产未绑定 commerce 数据库或测试模式，不能创建订单、收款或发放新权限。本地持久化模拟器覆盖幂等、重复事件、开通失败重试与重启读回，但不是支付服务商 sandbox 或正式交易。
- 待指定真实验收邮箱、普通客户数据权限及既有商户/支付渠道，完成验证码送达、购买/续费/开通验收；尚未代发真实邮件、创建客户 key 或执行付款。
- Python-urllib 默认标识曾遭边缘 403；requests/Node/curl 的结果不同，具体边缘规则仍待具备查看权限的会话核对。不能将它冒充数据源故障或已修复。
- `api.tradingdatas.com` DNS 未配置不阻断官网同域接口；#395 settlement identity/迁移草稿不在本轮范围。后续工程优先项为有限覆盖合同修正、下一批就绪接口，以及繁忙时段目录与公网转发耗时。

长期合同：[API](docs/API.md)、[架构](docs/ARCHITECTURE.md)、[运维](docs/OPERATIONS.md)、[账户与订阅](docs/design/customer-identity-commerce-v1.md)。当前页记录本轮证据，旧状态由 Git 历史追溯。
