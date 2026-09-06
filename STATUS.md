# TradingDatas 当前状态

发布检查更新至 2026-09-06 11:10 Asia/Shanghai。源码、公开网站、数据运行面和真实商业开通分别验收；历史快照由 Git 保存。

## 当前结论与对外范围

- Crypto 仅内部使用，不计入公共产品、来源候选、套餐、供数数量或接入排期；内部采集保持隔离。Research 外部文献不构成 Crypto 供数承诺。
- 两个已 active 的 `on_demand` 接口在 live `e8a96ccc` 上完成首次有界正式采集：`cn.dataset.fut_daily`（`trade_date=20260904`）与 `cn.dataset.opt_basic`（window `{}`）。empty ≠ success。
- [PR #514](https://github.com/NicholasHan1226/TradingDatas/pull/514) 合入 `5644f6313ebb934767f7ba000a7d561d76d3dff2` 后，A 股与 Crypto 的 live `current` 均已指向该 SHA。本 follow-up **未再 cut**。精确主线 [33990330624](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33990330624) 通过；Cloudflare [33990331993](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33990331993) 已发布。
- `bse_mapping` / `sge_basic` 已在 `5644f631` 上取得非空 success receipt（248 / 13 行）。`fund_basic` 同批 `{}` 窗口 failed `resource_budget`（coverage 2884，认证 query 0 行）：同一 attempt 里 E success 2884、O 自溢 10000。本切片把 same-attempt variants 收窄为 E-only，未抬高 10000，未 restage，未 mass-unpause；GZ cut 与再采集等新 `current`。`fund_company` 与 empty 项保持暂停。
- 2026-09-06 03:27 曾把 live `current` 切到 [PR #511](https://github.com/NicholasHan1226/TradingDatas/pull/511) merge SHA `e8a96ccc0cfbf38905a34c22dfa1345d95e5f539`。该次 15 秒门未放宽：切前全新暂存进程双认证 catalog 对为 A 股 200 / **2.480s** / 192、Crypto 200 / 8.676s / 240；切后生产端口 3.576s / 11.835s。匿名两侧 401。该指针已被后续 `5644f631` 取代。
- [PR #501](https://github.com/NicholasHan1226/TradingDatas/pull/501) 合入 `49e5ca9d60a878bcf4712b7ff46975215c817c58`。精确主线 [33971674611](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33971674611) 第 2 次执行通过；首次失败为测试清理与后台 Git 锁竞争，不能写成首次成功。
- [PR #502](https://github.com/NicholasHan1226/TradingDatas/pull/502) 合入 `d1140e914a11b1303173c9e05148d86421a788ac`，修正测试隔离及网站历史文案；精确主线 [33972854145](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33972854145) 四组检查均通过。
- Cloudflare [33972855121](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33972855121) 发布成功，最新资源为 `index-BZtC9up5.js`。来源摘要从正式配置快照派生，显示 Tushare 190 项、138 active / 52 paused；加新闻共 192 项、139 active / 53 paused。这是主线配置数量，**不证明两个 immutable 采集运行面已切换**。
- 来源页日期为 2026-09-05，保留 8 月 27 日历史。新增历史记录只说明按需配置，并引导至账户认证目录查看实际 receipt、覆盖与采集状态，不把探测或配置当作落库证明。
- Data/产品介绍公开；真实状态通过 `/api/account/catalog` 使用当前用户已有 key 读取，21 个产品导航关联正式原始 dataset。38 个产品定义、接口数、非空查询结果和稳定性分别判断。上游等待 30 秒、浏览器 45 秒保持，不构成放宽数据运行发布要求。

## 运行面与性能诊断

- 2026-09-06 03:24 读回：任务开始时 A 股与内部 Crypto 的 live `current` 已是 `6d4acdf2b00d585b9f5e80aa8cc2220ea0fbcf2c`（#508 文档合入，1089 文件 `verify-current` 通过），不是更早的 `f4bb6bef` 或 `a3106d68`。03:27 按 OPERATIONS 切到 `e8a96ccc`（1090 文件，tree `b7a987eb…`，registry 逐字节 cmp 通过）。18082/18083 与两项 API 在切后恢复 active。**该次 cut 本身**没有写 facts 库、没有 mass-unpause；正式 on-demand 批次在 04:02 才执行，见上。
- 目标版本全新进程认证目录三次结果：境内 20.084 / 21.853（受控诊断）/ 17.588 秒，内部 Crypto 12.363 / 8.517 / 7.853 秒。境内持续超出既有 15 秒要求；不能以已合并、HTTP 200 或较快的 warm 查询冒充发布完成。
- `7ef6bd19` 全新暂存进程权威对：境内 20.350 秒 / 192 项，Crypto 11.406 秒 / 240 项，监听约 43.5 秒（含覆盖索引全表 fault-in）。该 fault-in 伤害监听且不足以让首个 A 股 catalog <15s。
- [PR #507](https://github.com/NicholasHan1226/TradingDatas/pull/507) 合入 merge SHA `d21278d5b60eff2ab0188331db449a961787a745`（head `f95bea2f`）。PR CI [33984284520](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33984284520) 四组 fast shard 通过。本次无 `static/**` / `public-web/**`，未调度 Cloudflare。精确主线 [33984887459](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33984887459) 写入时仍在跑，不能写成已绿。
- `d21278d5` 当时按同一 archive/manifest 通道暂存（1089 文件），全新暂存进程双认证 catalog 对：A 股 200 / **17.554s** / 192 datasets；Crypto 200 / 9.622s / 240 datasets；匿名两侧 401。监听 31.930s。该次境内高于既有 15 秒门，故当时未切 `d21278d5`。
- [PR #511](https://github.com/NicholasHan1226/TradingDatas/pull/511) 合入 merge SHA `e8a96ccc0cfbf38905a34c22dfa1345d95e5f539`。本次无 `static/**` / `public-web/**`，automerge 未调度 Cloudflare。精确主线 [33986885195](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33986885195) 写入时仍在跑，不能写成已绿。
- `e8a96ccc` 已按同一 archive/manifest 通道暂存到 A 股与 Crypto 两平面（1090 文件，tree `b7a987eb…`，registry 逐字节 cmp 通过）。全新暂存进程双认证 catalog 对：A 股 200 / **2.480s** / 192 datasets；Crypto 200 / 8.676s / 240 datasets；匿名两侧 401。监听 25.401s。两侧均低于未放宽的 15 秒门，故切 `current`。empty ≠ success。
- 切后生产端口新鲜双认证 readback：A 股 200 / 3.576s / 192；Crypto 200 / 11.835s / 240；匿名 18082/18083 均为 401。生产监听 20.779s。该次 live `current` 曾为 `e8a96ccc`，现已被 `5644f631` 取代。
- [PR #514](https://github.com/NicholasHan1226/TradingDatas/pull/514) 合入 merge SHA `5644f6313ebb934767f7ba000a7d561d76d3dff2`。精确主线 [33990330624](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33990330624) 通过；Cloudflare [33990331993](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33990331993) 已在该 SHA 发布。本 follow-up **未再 cut**。
- 读回 2026-09-06 11:00 Asia/Shanghai：两侧 `/opt/investment/releases/tradingdatas{,-crypto}/current` 均为 `5644f631`。`tradingdatas-v1-internal.service` 与 `tradingdatas-crypto-v1-internal.service` active；`127.0.0.1:18082` / `18083` 在听。错误 unit `tradingdatas-api.service` inactive，不是生产 API。
- `5644f631` 切后生产双认证 catalog：A 股 200 / **2.282s** / 192；Crypto 200 / **8.266s** / 240；匿名两侧 401。15 秒门未放宽。11:05 follow-up 认证 18082 catalog 200 / **2.512s** / 192；匿名 18082/18083 均为 401。本 follow-up 未另用其它 token 重测 18083。
- 2026-09-06 04:37–04:38 Asia/Shanghai 的有界 on-demand 三件套已落 receipt（catalog `observed_at` 为 `2026-09-05T20:37:36Z` / `20:38:00Z` / `20:38:00Z`）。先前 SSH 超时并不等于未提交。后续 timer cadence 会 skip 这三项 `on_demand`。本 follow-up 到达时 `/run/tradingdatas/` 无 `on-demand-batch.json` / `on-demand.env`，仅 `collect.lock`；因三项均已有 receipt，**未 restage、未再 start** 同一 collect unit。cadence oneshot 在 11:00 后仍占用 unit 时未强杀。timer 保持 enabled/active。
- 认证 18082 回读（API 未调 provider；匿名 catalog 401）。empty ≠ success；未抬高 `max_rows_per_attempt=10000`：
  - `cn.dataset.bse_mapping`：catalog `runtime.state=success`，`degraded=false`，`receipt_id=receipt:4f51e767451041b87d05630d99293dce0c35ef7745ce6eef7b0f19660389c49d`，coverage `row_count=248`。query 200 / 0.130s / 本页 5 行且有 next_cursor；`runtime_state=success`，`state=partial`，quality `degraded`，reason `response_completeness_unverified`。合同完整性未验证，不是失败，也不是已证明全量。
  - `cn.dataset.sge_basic`：catalog `runtime.state=success`，`degraded=false`，`receipt_id=receipt:6a5aa92116bb7f6799d215e81585ac95fd04d33d85420a0dda6777dc9d4e100e`，coverage `row_count=13`。query 200 / 0.128s / 本页 5 行且有 next_cursor；`runtime_state=success`，`state=partial`，quality `degraded`，reason `response_completeness_unverified`。
  - `cn.dataset.fund_basic`：catalog `runtime.state=failed`，`degraded=true`，reasons `resource_budget`，`receipt_id=receipt:79f0791fd81e391ed3e769e65a66c50fa4305656cbc7fee6ab9914fcf112071a`，coverage `row_count=2884`。query 200 / 0.076s / **0 行**（失败回执页被排除）；`runtime_state=failed`。2884 与探测 `market=E` 行数相同，但不能写成 success；`{}` 窗口含 `market=E`/`O` 两个 variant。下一步是收窄请求，不得抬高硬预算、不得 restage 同一 `{}` selector。
- 2026-09-06 04:02 Asia/Shanghai 在同一 `tradingdatas-provider-native-collect.service` 上执行有界 on-demand batch（无新 unit/timer）。同 release no-write plan：2 项 planned，`will_call_provider=false`，`will_write_database=false`，dummy db-path 未创建。当时 cadence oneshot 连续占用 unit；selector 在确认运行中 PID **没有** `TRADINGDATAS_ON_DEMAND_BATCH_FILE` 后写入 `/run/tradingdatas/`（`tradingdatas`、`0600`、nlink=1）。下一轮同一 unit 于 04:02:00 消费 selector，04:02:10 结束，exit 0，CPU 9.568s。selector 已被 dispatcher 删除，不可重放。timer 保持 enabled/active。
- 批次执行（empty ≠ success；本批两项均为非空 success，不是 empty 观察）：
  - `cn.dataset.fut_daily`：`state=success`，returned/validated/committed/inserted **1072**，receipt_count 1。
  - `cn.dataset.opt_basic`：`state=success`，returned/validated/committed/inserted **6000**，receipt_count 1。未抬高 `max_rows_per_attempt=10000`。`response_completeness=null`，不得写成完整宇宙。
- 认证 18082 回读（API 未调 provider；匿名 catalog 401 / `unauthenticated`）：
  - `fut_daily` catalog：`runtime.state=success`，`degraded=false`，`receipt_id=receipt:137db0bbacceb26995e033e5408c25ccdbfcbcf8fb06e1d936ea1055661ec228`，coverage `row_count=1072`。query 200 / 0.125s / 本页 5 行且有 next_cursor；`runtime_state=success`，`state=ready`，quality `valid`，lineage `complete`。
  - `opt_basic` catalog：`runtime.state=success`，`degraded=false`，`receipt_id=receipt:25a8682cc3b2ce0d58431e8665b258b4ab3e4fc850610ce323bb025ada24ecf4`，coverage `row_count=6000`。query 200 / 0.117s / 本页 5 行且有 next_cursor；`runtime_state=success`，`state=partial`，quality `degraded`，reason `response_completeness_unverified`。这是合同上的未验证完整性，不是失败，也不是已证明全量。
  - 采集后第一次认证 catalog 18.043s / 第二次 2.999s / 192 项。18s 是写库后的单次读回，不是新的 release gate，也不回写已过的 15s 切门。
- 服务器证据（gitignored）：`/opt/investment-data/tradingdatas/evidence/20260906-ondemand-fut-daily-opt-basic/`。未提交 DB、token、receipt blob 或密钥。
- 合入前本地新进程 profile 曾记 16.857 秒（coverage 9.927 秒）；那是本机证据，已被本次 GZ 暂存对 2.480s / 8.676s 取代，不能回写成未过门。繁忙时段目录性能仍是内部观察项，不归为 vendor 问题。
- 公网管理服务此前已随 source 更新至 `d1140e914a11b1303173c9e05148d86421a788ac`。live 不可变采集/API `current` 现为 `5644f631`，不能再写成 `e8a96ccc`、`f4bb6bef` 或 a3106d68。较早公网目录的 `fut_daily`、`opt_basic` unobserved/0 行记录已被 `e8a96ccc` 上回执取代；`bse_mapping` / `sge_basic` 的旧 unobserved 记录已被本次 receipt 取代。`stk_nineturn` 仍 paused。公网页面本身不是本次 receipt 权威。
- 同次公网采集状态为 success 93、paused 53、empty 39、unobserved 4、stale 2、failed 1，合计 192。这是瞬时状态，不是稳定或可售数量。
- 当前生产继续使用此前已验证的 a3106d68 查询修复：失败 execution 的成功前缀一次排除，`pledge_stat` 小页不再逐项耗尽排除循环。该修复不放行失败 cohort。
- 本轮来源页受影响 7 项测试与生成构建通过，公开合同快照检查通过。22:49 新公网回读使用既有内部验收权限：会话 200；目录 200 / 24.939 秒 / 192 项，192 项均带 runtime/coverage，Crypto 0；退出 200 确认。该链路不是普通客户商业购买证明。

## 接入证据与下一批

计划唯一入口：[运维：可执行排期](docs/OPERATIONS.md#可执行排期不得因源质量滑期)。主线 49 个 Tushare 暂停中：29 个已有权限、14 locked、5 excluded、1 unknown；另有 25 个 current 未注册候选与 7 个 retired，后者排除当前队列。编译 registry（含新闻补充合同）为 142 active / 50 paused。

- 21:56 在既有 immutable a3106d68 上执行 3 次冻结的串行 HTTPS 探测：`fut_daily` valid_empty；`opt_basic` success / 6000 行（仅 ts_code 字段）；`stk_nineturn` valid_empty。这些是上游权限/请求观察，不是全字段落库 receipt、生产供数或连续稳定证明。
- `fut_daily`、`opt_basic` 已是 active / `on_demand`。2026-09-06 04:02 在 `e8a96ccc` 上完成首次有界正式采集与认证 catalog/query 回读，见上文 receipt。单次非空 success 是 observed 证据，不是 `stable`，也不是历史完整性或 PIT。
- `bse_mapping`、`fund_basic`、`sge_basic` 已是 active / `on_demand`。2026-09-06 04:37 在 `5644f631` 上完成首次有界正式采集：`bse_mapping` / `sge_basic` 非空 success 为 observed；`fund_basic` 为诚实 `resource_budget` failed，不是 empty，也不是 success。不得抬高 10000。
- 服务器证据位于 `evidence/20260905-ready3/`；冻结计划 SHA-256 为 `e80370da25b922ebe99ea3edbbf7620f733ae31c5ee62b9dee70290cb6d0ac45`。evidence refs 为 `server-evidence/20260905-ready3-fut_daily` 与 `server-evidence/20260905-ready3-opt_basic`；旧探测仍绑定原 immutable，不随新配置回写。
- `stk_nineturn` 保持 paused：datetime 窗口与发布时段合同待补齐，probe/ingest ready 不等于 activation-ready。源 empty 不阻挡其它接口。
- [PR #505](https://github.com/NicholasHan1226/TradingDatas/pull/505) 已合入 merge SHA `7ef6bd19eae0c0e3874b5e85cd4158a412d8c465`。精确主线 [33982793546](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33982793546) 通过；Cloudflare Pages [33982793531](https://github.com/NicholasHan1226/TradingDatas/actions/runs/33982793531) 已在该 SHA 发布。**未做 GZ cut**。
- 该 SHA 的全新暂存进程双认证 catalog 对未过既有 15 秒门：A 股 200 / **20.350s** / 192 datasets；Crypto 200 / 11.406s / 240 datasets；匿名 401 两侧成立。监听约 43.5s（含覆盖索引全表 fault-in）。本次 fault-in **没有**把 A 股首请求压到 15s 以下。
- `d21278d5` follow-up 只改只读 I/O：监听前不再对覆盖索引做全表 `COUNT(*)`，改为同一最近收据窗口 + 逐数据集 `COUNT`/`MIN`/`MAX` 并丢弃结果；快照打开的收据可读性探测改为 `LIMIT 1`。权威、认证、receipt 与 15s 门不变。当时实测境内 17.554s，未过门。`e8a96ccc` 在该基础上切掉 leftover snapshot 工作后，暂存对 2.480s / 8.676s，已切 `current`。empty ≠ success。
- 2026-09-06 对 `5f0f8f78` / 合入后主线的有界 HTTPS 探测：`fund_company` 返回 **15371 行**，超过硬预算 `max_rows_per_attempt` 10000，属过大非空，不是 empty≠success。**未激活、未 unpause、未抬高硬预算**。
- 同批探测中 `bse_mapping` / `fund_basic` / `sge_basic` 为 nonempty success（248 / 2884 / 13），已具备 ingest-ready 合同。#514 只把这三项写入 `active_evidence`（`server-evidence/20260906-preflight6-*`），Tushare 正式编译为 **141 active / 49 paused**；cadence 仍是 `on_demand`，窗口/variants/预算未改。`5644f631` 已切 `current` 并完成有界采集回读，见上文；该行旧文案「未做 GZ cut，未采集」作废。仓外 sidecar 仍在 `/opt/investment-data/tradingdatas/evidence/20260906-preflight6-paused-probe/`，探测 JSON 不进 git。`fund_company`、`stk_nineturn`（valid_empty）、`stock_hsgt`（valid_empty）及其余 paused 项均未动。empty ≠ success。
- `fund_company` 已按既有 `row_limit_observation` 合同记 `observed_count=15371`、`reject_at_limit=true`，ingest 改为 blocked（`response_completeness_unresolved_at_observed_limit`），activation 仍 paused。官方输入段仍是 documented empty-all，文档快照没有可钉住的收窄滤镜，不得猜公司名或抬高硬预算。preflight ready 现为 2 且全部 paused（`stk_nineturn`、`stock_hsgt`）。
- 本地 `codex/cursor-finite-coverage` 已把官方 `index_basic` 市场表与 `stock_hsgt` 类型表写入文档快照（doc 94 / 398）。`stock_hsgt` 按官方 `HK_SZ`/`SZ_HK`/`HK_SH`/`SH_HK` 映射，ingest 原因已空，仍 paused，未激活。`stock_company` 输入表表头是「必须」不是「必选」，且没有输入后交易所说明表，保持 `official_requiredness_unknown` + `request_anchor_unresolved`。`hm_list` / `mkt_idx_bmk` / `ths_index` / `ths_member` 仍无文档 empty-all 或默认值。`index_basic` / `opt_daily` ingest 仍因 6000 / 15000 行完整性未决保持阻断。
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
