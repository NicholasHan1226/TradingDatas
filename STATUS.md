# TradingDatas 当前状态

发布检查更新至 2026-09-06 02:45 Asia/Shanghai。源码、公开网站、数据运行面和真实商业开通分别验收；历史快照由 Git 保存。

## 当前结论与对外范围

- Crypto 仅内部使用，不计入公共产品、来源候选、套餐、供数数量或接入排期；内部采集保持隔离。Research 外部文献不构成 Crypto 供数承诺。
- 两个新接口的按需配置已经合入主线，公开网站已更新；**正式采集批次仍未执行**。live GZ `current` 已是 `f4bb6bef`（#506 文档合入门，基于 `7ef6bd19`），不是 `a3106d68`。catalog I/O follow-up `d21278d5` 只暂存未切，因为新的双认证冷启动对境内仍 **17.554s**，未过既有 15 秒门。empty ≠ success。
- [PR #501](https://github.com/NicholasHan1226/TradingDatas/pull/501) 合入 `49e5ca9d60a878bcf4712b7ff46975215c817c58`。精确主线 [33971674611](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33971674611) 第 2 次执行通过；首次失败为测试清理与后台 Git 锁竞争，不能写成首次成功。
- [PR #502](https://github.com/NicholasHan1226/TradingDatas/pull/502) 合入 `d1140e914a11b1303173c9e05148d86421a788ac`，修正测试隔离及网站历史文案；精确主线 [33972854145](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33972854145) 四组检查均通过。
- Cloudflare [33972855121](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33972855121) 发布成功，最新资源为 `index-BZtC9up5.js`。来源摘要从正式配置快照派生，显示 Tushare 190 项、138 active / 52 paused；加新闻共 192 项、139 active / 53 paused。这是主线配置数量，**不证明两个 immutable 采集运行面已切换**。
- 来源页日期为 2026-09-05，保留 8 月 27 日历史。新增历史记录只说明按需配置，并引导至账户认证目录查看实际 receipt、覆盖与采集状态，不把探测或配置当作落库证明。
- Data/产品介绍公开；真实状态通过 `/api/account/catalog` 使用当前用户已有 key 读取，21 个产品导航关联正式原始 dataset。38 个产品定义、接口数、非空查询结果和稳定性分别判断。上游等待 30 秒、浏览器 45 秒保持，不构成放宽数据运行发布要求。

## 未切换的运行面与性能诊断

- 2026-09-06 02:42 读回：A 股与内部 Crypto 的 live `current` 均为 `f4bb6befa58a40a91ce734065f15ce3ec59f9d5a`（1089 文件清单 `verify-current` 通过）。这是本任务开始前已存在的指针，不是本次 cut。`a3106d68` 仍在磁盘上，但已不是 current。18082/18083 与两项 API 仍 active。没有强杀采集、执行新接口正式批次、写 facts 库或修改生产权限。
- 目标版本全新进程认证目录三次结果：境内 20.084 / 21.853（受控诊断）/ 17.588 秒，内部 Crypto 12.363 / 8.517 / 7.853 秒。境内持续超出既有 15 秒要求；不能以已合并、HTTP 200 或较快的 warm 查询冒充发布完成。
- `7ef6bd19` 全新暂存进程权威对：境内 20.350 秒 / 192 项，Crypto 11.406 秒 / 240 项，监听约 43.5 秒（含覆盖索引全表 fault-in）。该 fault-in 伤害监听且不足以让首个 A 股 catalog <15s。
- [PR #507](https://github.com/NicholasHan1226/TradingDatas/pull/507) 合入 merge SHA `d21278d5b60eff2ab0188331db449a961787a745`（head `f95bea2f`）。PR CI [33984284520](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33984284520) 四组 fast shard 通过。本次无 `static/**` / `public-web/**`，未调度 Cloudflare。精确主线 [33984887459](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33984887459) 写入时仍在跑，不能写成已绿。
- `d21278d5` 已按同一 archive/manifest 通道暂存到 A 股与 Crypto 两平面（1089 文件，tree `97f1ff4d…`，registry 逐字节 cmp 通过），**未**切 `current`。全新暂存进程双认证 catalog 对：A 股 200 / **17.554s** / 192 datasets；Crypto 200 / 9.622s / 240 datasets；匿名两侧 401。监听 31.930s（低于 `7ef6bd19` 的 43.5s）。境内仍高于既有 15 秒门，故停在暂存层。**15s 仍未证明**。empty ≠ success。
- 新进程 profile 总计 16.857 秒，其中 coverage 9.927 秒。对同样的 15,196,606 行，计数冷读 10.7114 秒、warm 0.5138 秒；分组 warm 0.7666 秒未证明优于现有方案。冷缓存/I/O 是调查方向，尚无完整因果或已解决结论。
- 本次冷启动诊断未新增 SQL、schema、缓存、timeout 或 worker 调整。下一步只做有证据的局部性能修正，保留 receipt/lineage、权限与发布回退边界；繁忙时段目录性能是内部未完成项，不归为 vendor 问题。
- 公网管理服务此前已随 source 更新至 `d1140e914a11b1303173c9e05148d86421a788ac`。live 不可变采集/API `current` 现为 `f4bb6bef`，不能再写成 a3106d68。同次较早公网目录的 `fut_daily`、`opt_basic` 均为 unobserved、存量 0、`no_recognized_receipt`；查询分别 200 / 1.230 秒 / 0 行、200 / 1.512 秒 / 0 行，lineage incomplete。`stk_nineturn` 仍 paused。公网新配置不证明已完成采集；回读文件中的 release 字段只是本机 current 指针，不是 HTTP 服务版本证明。
- 同次公网采集状态为 success 93、paused 53、empty 39、unobserved 4、stale 2、failed 1，合计 192。这是瞬时状态，不是稳定或可售数量。
- 当前生产继续使用此前已验证的 a3106d68 查询修复：失败 execution 的成功前缀一次排除，`pledge_stat` 小页不再逐项耗尽排除循环。该修复不放行失败 cohort。
- 本轮来源页受影响 7 项测试与生成构建通过，公开合同快照检查通过。22:49 新公网回读使用既有内部验收权限：会话 200；目录 200 / 24.939 秒 / 192 项，192 项均带 runtime/coverage，Crypto 0；退出 200 确认。该链路不是普通客户商业购买证明。

## 接入证据与下一批

计划唯一入口：[运维：可执行排期](docs/OPERATIONS.md#可执行排期不得因源质量滑期)。主线 52 个 Tushare 暂停中：32 个已有权限、14 locked、5 excluded、1 unknown；另有 25 个 current 未注册候选与 7 个 retired，后者排除当前队列。

- 21:56 在既有 immutable a3106d68 上执行 3 次冻结的串行 HTTPS 探测：`fut_daily` valid_empty；`opt_basic` success / 6000 行（仅 ts_code 字段）；`stk_nineturn` valid_empty。这些是上游权限/请求观察，不是全字段落库 receipt、生产供数或连续稳定证明。
- `fut_daily`、`opt_basic` 通过逐项 preactivation 编译，主线正式配置改为 active、cadence 仍为 on_demand。正式有界采集、落库 receipt、采集后的认证查询与公网回读仍待完成，不声称已在生产观测。`d21278d5` 未切 current，本轮也未开采集。
- 服务器证据位于 `evidence/20260905-ready3/`；冻结计划 SHA-256 为 `e80370da25b922ebe99ea3edbbf7620f733ae31c5ee62b9dee70290cb6d0ac45`。evidence refs 为 `server-evidence/20260905-ready3-fut_daily` 与 `server-evidence/20260905-ready3-opt_basic`；旧探测仍绑定原 immutable，不随新配置回写。
- `stk_nineturn` 保持 paused：datetime 窗口与发布时段合同待补齐，probe/ingest ready 不等于 activation-ready。源 empty 不阻挡其它接口。
- [PR #505](https://github.com/NicholasHan1226/TradingDatas/pull/505) 已合入 merge SHA `7ef6bd19eae0c0e3874b5e85cd4158a412d8c465`。精确主线 [33982793546](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33982793546) 通过；Cloudflare Pages [33982793531](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33982793531) 已在该 SHA 发布。**未做 GZ cut**。
- 该 SHA 的全新暂存进程双认证 catalog 对未过既有 15 秒门：A 股 200 / **20.350s** / 192 datasets；Crypto 200 / 11.406s / 240 datasets；匿名 401 两侧成立。监听约 43.5s（含覆盖索引全表 fault-in）。本次 fault-in **没有**把 A 股首请求压到 15s 以下。
- `d21278d5` follow-up 只改只读 I/O：监听前不再对覆盖索引做全表 `COUNT(*)`，改为同一最近收据窗口 + 逐数据集 `COUNT`/`MIN`/`MAX` 并丢弃结果；快照打开的收据可读性探测改为 `LIMIT 1`。权威、认证、receipt 与 15s 门不变。实测境内 17.554s，仍未过门，**未切 `d21278d5`**。live `current` 保持任务开始时读回的 `f4bb6bef`。empty ≠ success。
- 2026-09-06 对 `5f0f8f78` / 合入后主线的有界 HTTPS 探测：`fund_company` 返回 **15371 行**，超过硬预算 `max_rows_per_attempt` 10000，属过大非空，不是 empty≠success。**未激活、未 unpause、未抬高硬预算**。`fut_daily` / `opt_basic` 仍无生产采集。
- 本地 `codex/cursor-finite-coverage` 已把官方 `index_basic` 市场表与 `stock_hsgt` 类型表写入文档快照（doc 94 / 398）。`stock_hsgt` 按官方 `HK_SZ`/`SZ_HK`/`HK_SH`/`SH_HK` 映射，ingest 原因已空，仍 paused，未激活。`fund_company` 官方输入段「无，可提取全部」已按 documented empty-all 冻结为空 snapshot，不再误读输出表；probe executable / ingest ready，仍 paused，未激活。`stock_company` 输入表表头是「必须」不是「必选」，且没有输入后交易所说明表，保持 `official_requiredness_unknown` + `request_anchor_unresolved`。`hm_list` / `mkt_idx_bmk` / `ths_index` / `ths_member` 仍无文档 empty-all 或默认值。`index_basic` / `opt_daily` ingest 仍因 6000 / 15000 行完整性未决保持阻断。preflight ready 现为 6 且全部 paused。
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
