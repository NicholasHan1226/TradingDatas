# TradingDatas 当前状态

最后更新：2026-07-27。

## 结论

- **2026-07-27 生产 current 已切换至 `c647d65a3df6e4598ae7017ccddd528d3e3bfc17`。**
  该 release 的 immutable manifest 已按 commit/tree/blob/owner/mode 验证；18082
  API 已恢复为 active，collector inactive、timer disabled。没有启用 cron、没有删除
  旧数据或回滚 release。
- **production 的 92 项扩容已完成首轮有界纵向读回。** 2026-07-27 的通用 QuickSync reprobe 以五个
  有界证据分片覆盖 139 个可执行合同，无重复：19 `success`、113 `valid_empty`、3
  `permission_denied`、4 `provider_failed_unclassified`。原 29 项加 63 个满足既有
  contract-match 与预算门禁的接口与原 29 项形成 92 active / 98 paused。63 个新增项已
  通过两个 generic batch 写入 49 条非空 success receipt 与 14 条合法 empty receipt，且以
  TradingAgent 专用只读身份逐项经 `POST /v1/query` 回读为 HTTP 200、保留 receipt metadata；
  当前均按真实完整性状态返回 partial/degraded，不等同于 ready 或自动调度就绪。随后
  `forecast` 与 `pledge_detail` 的同窗口实测均被上游以“须提供 `ts_code`”拒绝，因此没有
  新增专用 fanout 或 collector，两项保持 paused 并保留 failed receipt；`stk_factor_pro` 等
  不满足同一安全窗口或预算的接口也继续 paused。
- **当前 26 个 active dataset 已完成一次真实受控 latest batch。** 同一通用
  `collect_provider_dataset.py --batch-file` runner 在 `tradingdatas` identity 与全局
  collect lock 下调用 QuickSync，并在 2026-07-26T14:41--14:42Z 为 25 项写入
  `success` receipt；`security_master` 本轮是合法 `empty`，既有完整 snapshot 保留。
  所有 26 项均已以 TradingAgent 专用只读身份经 `POST /v1/query` 回读为 HTTP 200：5 项
  `ready`，21 项为 `partial/degraded`。后者表示 response-completeness/覆盖口径尚未
  冻结，不能表述为完整或自动调度就绪；它们的 provider receipt 仍为 `success`。
  token 仅在服务器受控进程内用于认证，未输出、传输或记录到证据。
- **当前 29 个 active dataset 已完成一次真实受控 latest batch。** 初始 26 项之后，
  `anns_d`、`etf_basic`、`fut_basic` 又在 2026-07-27 由同一 batch runner 成功写入
  1,140、3,366、11,119 行及 transaction-scoped success receipt；`fut_basic` 的 6 个
  provider variants 均有 receipt。三项均已以 TradingAgent 专用只读身份经
  `POST /v1/query` 回读到数据；它们仍是 `partial/degraded`，不得冒充完整覆盖。
- **这不是全部 Tushare 接口已经稳定采集。** 当前 runtime contract 仍为 190 项，其中
  29 active、161 paused；首期产品 catalog 的另 32 项尚缺正式 runtime contract 或
  QuickSync 运行证据。后续只允许按现有 registry/adapter/batch runner 分批完成真实
  provider -> SQLite receipt -> catalog/query readback，不得新增 dataset-specific
  collector、route、cron 或 timer。
- **下一批不能按响应非空强推。** `broker_recommend` 为月度窗口，`cb_basic`、
  `cn_schedule`、`opt_basic` 为 schema-subset；它们仍保持 paused，直到用相同通用合同
  解决窗口或字段完整性，而不是绕过 registry 检查。
- **最新生产事实优先。** 2026-07-26 续费后的服务器受控复测，使用正式 QuickSync
  transport、同一冻结计划的 139 个安全可执行请求，全部完成且无重复：17 `success`
  （非空响应）、115 `valid_empty`、3 `permission_denied`（`npr`、`stk_premarket`、
  `yc_cb`）和 4 `provider_failed_unclassified`；另有 51 项因安全参数或依赖未解而未调用。
  脱敏证据位于服务器受限目录
  `quicksync-renewal-matrix-20260726T123931Z/result.json`，绑定 release
  `0472be2f52338b64b0c2561afe2d1baaf19586b6` 与冻结 request-plan
  `7e8c5e8e14c936fdaf3089bea43c1cb7d62b04a645f8c598917a52f19dc2a879`。
  这证明续费已改变当前账号的接口权限；但 `success` 只表示本次受控请求得到非空
  provider 响应，`valid_empty` 只表示请求合法，二者都**不等于**已稳定入库、已完成历史
  回填、已通过 catalog/query readback 或已启用自动调度。不得把 HTTP、catalog 数量或
  官方积分说明表述成当前可采集能力。
- **历史候选已被后续正式验证取代。** 早期 `0472...` release 与 `4ceeb47` 对
  `anns_d`、`etf_basic`、`fut_basic` 的 on-demand planner 回退仅保留追溯价值；三项现在已
  由 `807853...` 正式 release 完成 provider → SQLite receipt → catalog/query 验证。其余
  `valid_empty` 仍须在各自正确 session/window 下验证，不能直接激活。
- 历史段落仅作事故和候选追溯；若与本页 2026-07-26 的 QuickSync matrix 冲突，以本条为准。
- 2026-07-20 transport 假设已纠正：当前真实上游通道不是官方 `api.tushare.pro` 直连，而是 Tushare-compatible QuickSync。身份固定为 `provider=tushare`、`transport_service=quicksync`；官方 Tushare 文档继续作为 dataset/schema/cadence 参考，QuickSync 文档与有界真实观测才是 endpoint/auth/permission/error/rate/concurrency 的运行事实源。
- 因此，现有 registry、通用 executor、SQLite facts/receipts 与固定 catalog/query API 可以继续复用，不需要迁库或逐接口重写。旧 official-direct release 与服务器 transport readback 对生产采集结论作废，该旧证据只证明代码层、发布布局和 fail-closed impaired 投影。2026-07-23 新链路的正式内部 API 已发布 9 个激活数据集，其中 5 项为 `ready/success`，新增 4 项如实为 `partial/empty/degraded`；全接口自动 cadence、现役 TA front 切换与旧链退役仍为 NO-GO，不得合并成一个“整体已完成”。
- 2026-07-22 已修正能力分母：官方固定目录 239 个名称与当前 MCP 258 个工具的
  并集为 268；首期境内只读产品 catalog 为 222。旧 190 只代表已有官方文档合同与
  历史 transport observation 的子集；新增 32 项在合同或 HTTPS 权限证据缺失时均为
  `unobserved/paused`。scope v2 已以 commit `d274090509d9ed290eb5bb3d50ee5206df7c6d94`
  同步 local/origin/GitHub，不能据 MCP visibility 自动激活接口。
- 安全 HTTPS 探测器已以 commit `07b297449286a5e2f6da86d2a0e97641225d80eb`
  同步 local/origin/GitHub。它采用账号级 200 次/滚动 60 秒、并发 4、零重试和每次
  provider call 前的持久 start 授权；fresh review 为 P0/P1/P2=0，主线组合回归
  484 passed / 1 skipped。该工具尚未在正式服务器执行，不是 entitlement 或生产证明。
- 2026-07-22 已把 catalog 可发现性与 query/runtime eligibility 分离：当前 190 项
  runtime registry 可全 cursor 发现 190/190；222 项产品能力发现 artifact 已独立冻结，
  并以 commit `84d8ad4` 进入 main，其中新增 32 项不伪造成 runtime contract，尚未进入
  API。query 门禁的 current-main 审计同时发现旧实现错误放行 185 项进入 SQLite；
  commit `7d25cc8` 已把资格收紧为同一 binding `entitlement=active` 且
  `activation=active`。该提交当时的 fresh review 为 P0/P1=0：仅 3 项可进入 SQLite，
  其余 187 项在 SQLite/provider 前 fail closed；main 组合回归 94 passed / 1 skipped。
- 2026-07-22 请求合同 R5 已通过 fresh clean-overlay review 并以 commit `3b74b45`
  进入 main：runtime compiler 对 official/request/transport/reviewed 四类原始输入做
  内容与冻结 SHA 双重绑定，HTTPS probe plan 对 official/request/transport/registered
  做同等绑定；36 个声明覆盖 7 个唯一 authority。dataset-field seed 还要求 fresh
  success receipt 与 producer schema 精确匹配，旧版或未来 schema 均在生成请求前
  fail closed。独立验收 P0/P1/P2=0；主线定向回归 171 passed，组合回归
  146 passed / 1 skipped。该提交没有执行 provider、改写 SQLite 或接触服务器。
- 2026-07-21 CST（证据时间 2026-07-20Z）已通过文档指定的 HTTP compatibility endpoint 对首期 190/190 个 API 做真实有界调用并形成唯一接口矩阵，缺失 0、额外 0：167 `success`、3 `empty`、14 `permission_denied`、1 `credential_rejected`、5 `unsupported_api`。该矩阵确认 145 个通过 contract-match 候选门禁；通用数字字段修复又在代码层补回 4 个接口的 29 个字段，形成 149 个候选，但它们都不因此自动 activation：新增 4 个仍待 fresh HTTPS provider -> SQLite -> receipt -> API 纵向 readback。17 个 schema drift、1 个质量异常和其余 impaired 接口继续 paused。矩阵 SHA-256 为 `ea102cd7b189e1c7d8d0c208c303b308ebf3a07bd4c9b682c8b10ada9ccfb1e1`，明确 `production_ready=false`；它不是正式 HTTPS server readback。
- 频率实测只证明健康单一 HTTPS 节点的小响应 request-start 能力至少 200 次/分钟：并发 4 下 210/210 成功，全部 request start 在 59.714 秒内，零限频、零 transport error、零重试；脱敏证据 SHA-256 为 `660c5ef6f1567b9be4673822f891d7ca3b388a6aad37224b2e62fdaa0b1cb935`。当前 `main` 代码设置保护门禁 200 次/60 秒、并发 4，但这不是 QuickSync 合同额度或已部署 production 配置；混合大响应、每日额度与 DNS failover 仍待验收。
- observations 代码提交 `c4fc5a1872b2fcae76b9e20a82911bdc88615b67` 已经 local main、origin/main 与 live GitHub 三方读回一致；其基线 `7ce02ea` 包含通用 transport commit `7bf7f71`、数字字段 commit `c92b001` 与证据文档 commit `7ce02ea`。通用 transport 在一个共享 monotonic deadline 内完成 DNS snapshot direct-connect、TLS 1.3、仅 pre-send 节点切换、send 后零 replay及 `rate_limited` 诚实分类；数字字段修复一次扩展 provider output field grammar，并保留 API/参数/window 的严格 grammar。observations 精确 17 路径经双路 fresh review 确认 P0/P1=0，主线定向回归 58 项通过，Ruff/compile/diff-check 通过；服务器、production 与真实 HTTPS 全接口 readback 仍尚未完成。
- QuickSync transport 修正已形成 commit `a7e2e59aae877f9cbe0345ce80cbe0dae1e1fff8`：receipt 的 `config_hash` 现在同时绑定 provider-neutral ingest 合同和代码固定的 QuickSync transport profile；query 只有在 receipt hash 与当前 registry/profile 精确匹配时才输出 `transport_service=quicksync`，旧或不明 transport receipt 会 fail closed。最终定向矩阵为 70 项与 72 项通过，fresh reviewer 判定 P0=0、P1=0。
- 服务器 immutable canary release `a7e2e59aae877f9cbe0345ce80cbe0dae1e1fff8` 已在独立 SQLite 与 `127.0.0.1:18084` transient API 上完成真实纵向切片：`trade_cal` 8 行、`stock_basic` 5,607 行、`daily` 5,524 行，共 11,139 facts；成功数据均有 transaction receipt。catalog 返回 190 个 dataset，`daily` 与 `security_master` query 为 ready/non-degraded、lineage 完整且 transport 为 QuickSync；无认证请求为 401，同一 as-of 两次响应哈希一致；含未来上界的 `trade_cal` 负例返回 `data=[]`、failed/degraded、transport null。
- 当前 QuickSync DNS 有两个 IPv4 节点，2026-07-20 服务器 fresh TLS 复核中 `111.229.23.244` 的 TLS 1.3 与证书验证正常，而 `101.35.23.219` 对同一 SNI 持续返回 TLS internal error。首次真实采集因此写入一条 failed receipt，系统 resolver 轮换到健康节点后纵向切片成功。这个上游节点不一致在修复或获得稳定 endpoint 前阻断 production timer，不允许通过硬编码 IP、关闭证书校验或伪造 success 绕过。
- 2026-07-22 05:47-06:02 CST 已完成新的 code-only safe-release staging：GitHub
  `main=0d98d8076ed96074fa3b9f513cda42950be87dd2`，服务器新增同名不可变 release；
  target 与 rollback `9fa5838451c07fc8a328e37dd70db33976a733d2` 均由独立 trusted verifier
  重新核对 commit/tree/blob、SHA-256、owner 和 mode，外置 manifest 也已原子安装。
  `current` 仍指向 rollback，正式 API/collector/timer 仍为 inactive，timer 仍 disabled，
  旧 8082/18082/18084、root 5 条与 marketgraph 24 条 SharedSignals cron 及 TA override
  均未改动。正式 QuickSync Token 仅在服务器内部从已验证 canary 凭证复制到
  `/etc/tradingdatas/quicksync.token`，内容未读取或输出，最终为单链接普通文件、
  `tradingdatas:tradingdatas`、`0600`；源凭证继续保留作回滚。该阶段没有切换 release、
  启动服务、调用 provider 或读写 SQLite，整体仍为 PAUSE/NO-GO。已安装 collector unit
  仍是旧内容，正式 18082 仍被旧服务占用。
- 2026-07-22 05:47-07:09 CST 的本地检查把旧全仓 `18 failed` 全部归因为测试夹具漂移，而非当前 Tushare
  生产路径缺陷：5 项为固定 20260720 与真实时钟产生 stale，13 项为 synthetic provider
  未声明 transport profile。提交 `6bbb232` 修正确定性夹具；提交 `182fb75` 修正 HTTPS
  probe 从 immutable release 绝对路径启动的 import bootstrap，并保留 symlink identity
  fail-closed。两项均已各自 fresh PASS，随后组合全仓回归为 `1569 passed / 1 skipped`。
  发布/探测预审又发现 immutable release 内原地重编译 registry 以及 probe 错误/empty
  证据分类两个 P1；本地提交 `8fc5e7a` 已改为仓外私有输出后逐字节 `cmp`，本地提交
  `e4708d1` 已保留安全错误枚举与 provider `response_fields`，对应 fresh review 均为
  P0/P1=0，定向回归分别为 33 项与 529 项通过。这些结果只证明各自候选；最终 release
  必须另有 exact-byte 全仓测试、clean commit、GitHub readback 与服务器 trusted-verifier
  证据，不得由本条自动推断。上述证据截点内没有 provider 调用。
- 2026-07-22 10:19 CST 已在服务器隔离目录完成 `index_classify` 与 `sw_daily` 的
  provider-native 纵向采集证明：前者以 `src=SW2021` 返回并提交 511 行，后者以
  `trade_date=20260721` 返回并提交 439 行；950 行质量均为 valid，两个 success receipt
  的 returned/validated/inserted/committed 数量守恒，SQLite `quick_check=ok`。隔离结果位于
  `/opt/investment-data/tradingdatas-preactivation/815cbcfba99f555023b170d7a3cc5a86e3c4172b/run-20260722T021932Z`，
  结果 SHA-256 为 `e1e49b500429b72d9cfe340d7c9ee7fd43888d90b8bdd972745331d1eaf56695`，
  SQLite SHA-256 为 `fb6c0c742dfb70aa619e142d8ad2b7a4e495433a0ebb22a1e5f788229be9e4b1`。
  该证明没有写正式 registry、没有启动 scheduler、没有切换 `current`，也尚未完成固定
  `catalog/query` API 回读；因此只支持把本地候选编译为 5 active / 185 paused，不等于生产 ready。
- 2026-07-22 11:03-11:20 CST，激活提交
  `77e81816149cf614f0f2e6f42d340b5fbd23447b` 已经 local main、origin/main 与
  live GitHub 三方一致，fresh code review 为 P0/P1/P2=0，全仓回归为
  `1590 passed / 1 skipped`。服务器同名 immutable release 经 trusted verifier
  验证 109 files 与 Git tree/blob/owner/mode 全部一致；从物理 release 仓外重编
  registry 与 checked-in 文件逐字节一致，为 190 total / 5 active / 185 paused。
  新隔离 SQLite 各执行一次 QuickSync HTTPS 采集：`index_classify` 511 行、
  `sw_daily` 439 行，950 行均 valid，2 条 success receipt 的计数守恒，
  `quick_check=ok`。随后临时 `127.0.0.1:18085` API 返回 catalog 190 项，前者分页
  500+11 行、后者 439 行，均为 `ready/success/non-degraded/fresh/valid`，lineage
  完整且绑定 `provider=tushare`、`transport_service=quicksync` 和对应 SQLite receipt；
  同一 `as_of` 两次响应除随机 `request_id` 外稳定。未认证 catalog 为 401，paused
  dataset、`/tushare` 与 `/source_status` 均为 404。隔离证据位于
  `/opt/investment-data/tradingdatas-preactivation/77e81816149cf614f0f2e6f42d340b5fbd23447b/run-20260722T030335Z`，
  evidence manifest SHA-256 为
  `c780d518d1c1e8279cbc6b41e578ca50be8e3c3fc937f5fd295b86b71425d450`；fresh
  server review 为 P0/P1/P2=0。临时 API 已停止且 18085 无监听；正式 `current`、
  18082、正式 SQLite、collector/timer、旧 8082 与旧回滚面均未改变。因此该证据
  完成两个新增 dataset 的隔离 provider -> SQLite -> receipt -> API 停止线，但不等于
  正式 runtime、消费者切换或 production ready。
- 2026-07-22 11:22-11:49 CST，文档同步提交
  `d9d480a37700e6936180cea19f276dfed2cf9c22` 已建立同名 immutable release；target
  与 rollback `9fa5838451c07fc8a328e37dd70db33976a733d2` 均由 trusted verifier
  fresh 验证通过。组合 canary 的首轮窗口错误包含未来日期 `20260727`，API 正确以
  `data_through_in_future` 返回 failed/degraded；失败 run 保留且没有作为成功证据复用。
  修正 run 仅复用 `77e8181...` 已验证且 registry 字节一致的 `index_classify`/
  `sw_daily` 隔离 SQLite，再对 `trade_calendar`、`security_master`、`daily` 各执行
  一次 fresh QuickSync HTTPS 采集，因此不表述为五项均重新调用 provider。最终隔离库
  分别包含 8、5,948、5,525、511、439 行 valid facts，7 条 receipt 为 6 success +
  1 honest empty；`security_master` 的 L=5,608、D=340、P=0 三 variant 保持完整。
  `GET /v1/catalog` 返回 190 项；五项 `POST /v1/query` 全分页回读为
  `ready/success/non-degraded/fresh/valid`，SQLite、receipt 与 API 行数/主键/lineage
  守恒，same-as-of 哈希稳定；401、paused 404 及旧 `/tushare`、`/source_status` 404
  负例通过。证据位于
  `/opt/investment-data/tradingdatas-preactivation/d9d480a37700e6936180cea19f276dfed2cf9c22/run-20260722T033023Z`，
  80 项 evidence manifest SHA-256 为
  `0260a96a95b4b1b54fda9b0f4bb66f25df0599e0ce0bc8ab66f0327263161bcf`；fresh reviewer
  判定 P0/P1/P2=0。临时 18085 已停止。正式 `current` 仍是 `9fa5838...`，18082
  仍由旧 SharedSignals 占用；已安装 collector unit 仍是 official-direct 旧内容，正式
  TradingDatas API/timer inactive，消费者 parity 未证明。因此该结论仍只是隔离五数据集
  链路 PASS，不是内部稳定服务上线或 production ready。

- 2026-07-22 19:03-19:39 CST 已进入正式数据面的受控预激活：`current` 先由 trusted
  verifier 把遗留绝对指针规范为相对 commit，再切到
  `b395b9017643c61a7f076f02985e9c457cc8d069`；local/origin/GitHub 与服务器 immutable
  release 均为同一提交。安装中的 collector unit 已替换为 QuickSync 通用 runner，正式
  timer 继续 `disabled/inactive`。两轮人工 one-shot 后正式 SQLite `quick_check=ok`，共有
  23 条 transaction receipt（21 `success`、1 既有 `empty`、1 既有 future-window
  `failed`）；失败证据没有重写为成功。facts 为 `trade_calendar=731`、
  `security_master=5,949`、`daily=38,593`（7 个交易日分区）、
  `index_classify=511`、`sw_daily=3,073`（7 个交易日分区），所有事实都能追溯到 success
  receipt，且不存在 2026-07-22 之后的 calendar fact。
- 同一正式 SQLite 已由 b395 影子 API 在 `127.0.0.1:18085` 完成 authenticated readback：
  catalog 为 190 项（5 active / 185 paused）；`trade_calendar=731`、
  `security_master=5,949`、`index_classify=511` 全分页成功，`daily` 与 `sw_daily` 以
  `trade_date=20260722` 分别完整返回 5,526 与 439 行。五项均为
  `ready/success/non-degraded/fresh/valid`，lineage 绑定 SQLite receipt、
  `provider=tushare` 与 `transport_service=quicksync`；same-as-of 重放一致。无/错 Bearer
  为 401，paused dataset、`/tushare`、`/source_status` 为 404。证据目录为
  `/opt/investment-data/tradingdatas-preactivation/28a502980b03e98857707769b84b6b6b8b14b33e/cutover-20260722T110305Z/api-shadow-b395-bounded-20260722T113846Z`，
  原始 `SHA256SUMS` 摘要为
  `46a5b555df4e46b0b8bf1d9a03658ceefcb02da5068375396acd2d39df04e30d`，但该清单错误
  包含自身的空文件摘要，已原样保留为事故证据，不能作为通过清单。修正版位于相邻目录
  `api-shadow-b395-bounded-20260722T113846Z-manifest-fix-20260722T115009Z`；仅列 9 个
  payload 的 `PAYLOADS.sha256` 摘要为
  `9e5837b988befbcad3e42c6e1759b7f54d2084ff15aa33917445875dc2dda6b5`，9/9 payload
  与独立 root sidecar 均已通过 `sha256sum -c`。
- 2026-07-22 20:20-20:25 CST，TradingAgent Bearer/no-fallback 消费候选已通过独立复核、
  GitHub CI 并以 merge commit `303176e9658d72351e991db1fcc0a2c96d8311a9` 同步其
  local/origin/GitHub `main`。发布侧随后在服务器生成独立 `tradingagent` read token：
  API registry 只保存 PBKDF2 hash，明文仅保存在 root-owned `0600` 持久源和
  `marketgraph:marketgraph`、`0600`、单链接的
  `/run/secrets/tradingagent/tradingdatas-read.token`；`systemd-tmpfiles` 负责重启后从
  持久源重建，不复用 bootstrap token。b395 shadow 重启后，直接 API 与上述 TA 客户端均对
  5 个冻结 dataset 做了有界 catalog/query readback，全部为
  `ready/non-degraded/fresh/valid`、receipt/lineage 完整且无 cursor；same-as-of 一致，错 token
  为 401，旧 `/tushare`、`/source_status` 为 404。
- 同轮按已冻结回滚顺序停止并禁用了旧 `sharedsignals-v1-internal.service`，在 18082 释放后
  启动新 `tradingdatas-v1-internal.service`；正式 18082 重跑直接 API 与真实 TA 客户端均
  通过后，新服务已 `active/enabled`，旧服务保持 `inactive/disabled`，18085 shadow 已停止。
  active runtime 以 `tradingdatas:tradingdatas` 运行，读取 b395 `current` 与同一正式 SQLite；
  release verifier 为 109 files verified，SQLite `quick_check=ok`，facts/receipt 数量未漂移。
  因此固定内部 catalog/query 数据面已达到 formal GO；采集 timer、全接口 cadence、TA 研究
  snapshot 以及旧 8082/cron 退役仍是彼此独立的未完成层。
- 当前已知查询预算边界也被保留：`daily` 无筛选跨 7 个分区读取时第一页成功、第二页因
  SQLite 100 万 VM-step 预算 fail closed 为 503；按单个 `trade_date` 查询可完整读取
  5,526 行 / 12 页。它不影响已验证的 latest/current 内部切片，但意味着消费者必须使用
  registry 允许的有界日期过滤，不能把无界全历史导出当作当前稳定合同。
- 两个无反向依赖、无配置引用、无当前连接的旧 TradingDatas transient canary
  （18083/18084）已在冻结 unit 与全目录文件哈希后停止；确认目录不含数据库或真实凭证后，
  对应的两个旧代码目录已物理删除，停用/重建证据与 `/etc` 凭证回滚面继续保留。旧
  SharedSignals 18082 已停止并禁用；旧 8082、relay、root 5 条与 `marketgraph` 22 条 active
  cron 及 TA 8082 override 仍在真实使用，不能删除。正式 18082 与 TA Bearer 有界消费 parity
  已完成，但它不证明现役 TA front 已从 8082 切换，也不授权删除旧 writer 或历史数据。
  停用证据的原 `SHA256SUMS` 同样因包含自身而不可作为通过清单，已原样保留；相邻
  `legacy-canaries-stop-20260722T113932Z-manifest-fix-20260722T115450Z` 中的 9-payload
  清单摘要为 `23e2e4f05889aa5ed69a6dea8afc67c7981404873277b134bb40c6aafc4b13ab`，
  9/9 payload 与独立 root sidecar 均已通过校验。

- GitHub 仓库已从 `NicholasHan1226/SharedSignals` 重命名为 `NicholasHan1226/TradingDatas`。
- 本地新目录为 `/Users/nicholashan/Projects/Finance/TradingDatas`。
- 历史提交 `9fa5838451c07fc8a328e37dd70db33976a733d2` 曾实现 request-profile 解析器。当前 profile/resolver 仅以 deprecated migration-only 形式保留官方输入映射，不是 activation authority，也不得进入 collector、scheduler 或生产命令；待映射迁入 provider-native runtime contracts 后删除。
- GitHub 集成和生产文件预置不等于生产 runtime；正式 18082 API 与有界 TA 客户端 readback
  已完成，但全接口自动 cadence、现役 TA front 的 8082 退役和完整调度周期仍未完成。
- 历史隔离 pilot 已证明 `trade_cal`、`stock_basic`、`daily` 三个数据集的真实 Tushare -> SQLite -> receipt -> catalog/query 纵向切片；它不能替代当前服务器新 runtime 的 fresh 真实采集验收。
- 官方固定能力快照包含 239 个唯一 API 名称；scope v2 的首期境内只读产品目录为
  222 个 dataset。其 190 个已有官方文档合同子集与新增 32 个待合同/权限项必须分层
  报告；`in_scope`、MCP visible、entitled 和 active 互不等价。
- registry 中的 `entitlement` 只表示经 QuickSync transport 真实受控调用观测到的 Tushare dataset 权限状态，不表示购买、按接口计费或订阅。官方积分说明不能替代 QuickSync 的账号权限、频率或并发证据。
- 2026-07-20 已对 190 个 in-scope 官方文档做一次批量读取验证：首轮 184 个成功，6 个瞬时网络失败在有界重试后均返回 200；190 个文档都包含可解析的输入参数与输出参数表。合同字段可以批量生成，不需要逐接口手写采集器。
- clean-slate capability catalog 已移除旧 114 接口计划、`legacy_coverage` 和 `in_legacy_inventory`，现在只由固定官方索引与范围分类生成；catalog SHA-256 为 `5bb4a2aae746e31b72ae610bdfe6a3feec469d6f4b8de769ce7e5395c20d3ea1`。
- `tools/snapshot_tushare_contracts.py` 已重新生成 `config/tushare_document_contracts.v1.yaml`：190 个合同、0 个解析错误，文件 SHA-256 为 `2cbc2b0012c8920b5cdcc89e9587a46bc4001d510c04990c00d39f502cff73da`，且绑定上述 catalog SHA。合同只证明文档解析完整，不代表账号 entitlement、activation 或真实采集已通过。
- `config/quicksync_interface_observations.v1.yaml` 已取代旧 manual entitlement probe/policy，成为唯一 QuickSync 权限、兼容性观测与 activation 输入。它绑定矩阵 SHA `ea102cd7b189e1c7d8d0c208c303b308ebf3a07bd4c9b682c8b10ada9ccfb1e1` 与 190 API 集合 SHA，并互斥分类为 145 contract match、4 个数字字段修复、17 schema subset、1 quality anomaly、3 empty、14 permission denied、1 credential rejected、5 unsupported。deprecated request-profile/resolver 只保留官方输入映射迁移信息，不参与上述权威链。
- **历史 2026-07-26 快照：** `8bdc43b...` 当时为 26 active / 164 paused、production 为 12 / 178；该快照已被本页顶部的 `807853...` 29 / 161 正式事实取代。HTTP compatibility 矩阵继续明确 `production_ready=false`，不得用候选分类自动启用 scheduler。
- 通用 executor 已实现 typed variants、fanout、offset pagination、资源预算、受限重试和进程级调用预算。每个真实 provider call 都有独立 transaction receipt；数据行与 success receipt 同 SQLite 事务提交；失败调用不会被后续 empty 终止页洗白，后续独立执行可以恢复状态。
- clean-slate 候选已删除 204 个旧系统路径并保留 86 个目标路径。旧 probe 测试数量只作为历史提交证据；request-profile 测试只证明迁移资料与官方文档/registry/observations 自洽，均不代表 runtime activation。当前候选必须以 observations -> compiled registry 的 fresh 回归重新验收。
- 服务器已从 GitHub commit `b4a6aac9a346519b9e6d744fe6521f0a9510c381` 建立隔离 18083 transient canary：独立 `tradingdatas` 用户、新 SQLite 与新认证材料；未认证 catalog 为 401，认证 catalog/query 为 200，catalog 投影 190 个数据集（3 active / 187 paused），旧 `/tushare` 与 `/source_status` 均为 404。首次空库查询如实返回 `unobserved`；随后把 QuickSync 凭证错误发送到官方 Tushare endpoint 得到 provider code `40101`。这个结果证明旧 transport 假设错误和 API impaired 投影可用，不是 QuickSync 权限或数据采集证据。
- 本机保留的 2026-07-16 QuickSync capability report 记录 258 个工具，并在 20 个受控读调用中观测到 15 个 success/data-or-empty 与 5 个 permission denied `40203`。它证明 QuickSync 具备 Tushare-compatible 能力及独立权限语义，但不证明服务器正式凭证、全量 entitlement、正确 cadence、频率或并发。
- 2026-07-23 04:55 CST，正式 `current` 已由 trusted verifier 原子切换到
  `486e42a655481bbe0df359a97b8167f4611e6bcd`。正式 18082 readback 返回 catalog
  190 项（9 active / 181 paused），9 个 active dataset 的 query 均为 HTTP 200、带
  SQLite receipt 与 `transport_service=quicksync` lineage；其中 5 项为
  `ready/success`，4 项为诚实的 `partial/empty/degraded`。重复读取一致，未认证 catalog
  为 401，旧 `/tushare` 与 `/source_status` 均为 404。API unit 为 `active/enabled`，
  collector 与 timer 仍为 `inactive`，timer 仍 `disabled`。证据目录为
  `/opt/investment-data/tradingdatas-preactivation/486e42a655481bbe0df359a97b8167f4611e6bcd/production-cutover-final-20260722T205516Z`；
  `PAYLOADS.sha256` 已在目录内通过。正式 SQLite 不随 release 回滚覆盖。
- 2026-07-23，`direct_wave_2` 经 fresh clean-overlay review（P0/P1/P2=0）后由
  commit `c3232d0422aa09b83b8d8e9ed6cd87067bcb47cc` 发布到正式 `current`。
  发布前 SQLite online backup 与前后 `quick_check=ok`，schema hash 和
  `user_version=0` 保持不变；受 systemd 隔离的单次采集仅新增
  `hsgt_top10=80`、`limit_list_ths=366`、`moneyflow_ind_ths=360` 行，并分别新增
  4 条 success receipt，未改写其它 facts/receipts。正式 catalog 为 190 项
  （12 active / 178 paused），新增三项连续两次 authenticated query 行数和数据哈希一致，
  均保留 receipt、完整 lineage 与 `transport_service=quicksync`，并因
  response completeness 未冻结而诚实返回 `partial/degraded`。未认证 catalog 为 401，
  旧 `/tushare`、`/source_status` 为 404；API active/enabled，collector 与 timer 仍
  inactive/disabled。`suspend_d` 因 timer 禁用且其 15 分钟 SLA 已如实返回 stale/degraded，
  不是本次发布回归。证据目录为
  `/opt/investment-data/tradingdatas-preactivation/c3232d0422aa09b83b8d8e9ed6cd87067bcb47cc/wave2-production-20260722T214643Z`，
  `PAYLOADS.sha256` 已通过。
- 旧生产 `8082`、旧数据库、旧 cron 和旧文档不属于 TradingDatas 目标架构；在新生产与消费者切换前仅作为短期回滚源。
- 2026-07-21 只读复核确认旧生产依赖仍在运行：root crontab 仍有 4 条 `SharedSignals/cron/opening_gate.sh` 和 1 条 `external_api_probe.sh`；`marketgraph` crontab 仍有旧 collectors、CNFutures、Crypto、事件、patrol/watchdog/health 等 SharedSignals 任务；`tradingagent-front-api.service.d/sharedsignals.conf` 仍指向 `http://127.0.0.1:8082`，现役 TradingAgent front service 仍为 active。这些项目已进入精确退役清单，但在 TradingDatas 真实采集、`catalog/query` API、消费者 parity、数据连续性和回滚证明通过前不得停用或删除。
- 2026-07-22 fresh HTTPS gap probe 形成新的 **preactivation candidate**，不是生产
  activation：190 个 runtime contract 中 158 个实际执行，结果为 97 `success`、
  50 `valid_empty`、10 `provider_failed_unclassified`、1 `field_contract_mismatch`，另有
  32 个在请求计划阶段 blocked。fresh result 与 plan ingest-ready 的交集为 132；其中
  12 个合同使用 codec 已支持、但尚未通过 activation gate 的 `yyyymm`、`yyyy_qn`、
  `yyyyww` 或 `local_datetime_seconds` window，继续 paused；`cn_schedule` 的月窗重复仅记为
  激活前门禁，本轮不实现去重或新结构。因此只有显式 `preactivation_candidate` 模式加
  `--activation-evidence /outside/repository/path`，才能从仓外 hash-bound sidecar 生成
  120 active / 70 paused 的 loader-readable canary registry；当前 sidecar artifact
  SHA-256 为 `cebbff13971b4d6465b986089a152feb056dc8e56e0bc0d4992a63175d20268c`，
  不在 Git/CI 内。该模式拒绝覆盖 checked canonical registry。checked 与
  production registry 当时均继续保持 **5 active / 185 paused**，且证据明确
  `production_ready=false`。没有 `response_completeness` 策略的数据集只能作为降级 canary，
  不能表述为 exact-complete。每个 dataset 的正式 promotion 仍需独立 SQLite 中真实
  receipt、transient catalog/query readback、same-as-of 与失败负例，且 timer 保持 disabled。
- 2026-07-23 使用干净候选提交 `1def337683d809d431b624d4fd2ab62888e52ad3`
  与仓外 candidate registry SHA-256
  `44a3f28df5b469c67576092c8f64fa7be3a40ea11e155b8082d66a5e3e8738e1`
  完成首个新增数据集隔离 canary。五项 dry-plan 均未调用 provider 或创建数据库；初始化独立
  SQLite 后，`adj_factor`、`block_trade`、`cctv_news`、`etf_basic` 分别写入
  5,543、112、13、3,363 行，并各有一条 success receipt。`daily_basic` 因空隔离库缺少其
  registry 声明的 `security_master` fanout authority，写入一条 failed receipt、零事实行，
  继续 paused，不增加专用 collector 或绕过依赖。临时 `127.0.0.1:18085` catalog 为
  190 total / 120 preactivation active / 70 paused；四项成功数据集均可完整分页，连续两次
  读取的行数与数据哈希一致，但因 `response_completeness` 尚未冻结而如实返回
  `partial/degraded`，不是 ready。无认证请求为 401，`/tushare` 与 `/source_status` 为
  404。隔离库 `quick_check=ok`，临时 API 已停止；正式 `current=b395b901...`、18082、
  正式 SQLite 与 disabled timer 均未改变。证据目录为
  `/opt/investment-data/tradingdatas-preactivation/1def337683d809d431b624d4fd2ab62888e52ad3/run-20260722TQkgWsk`。
- 2026-07-23 在同一隔离 release、同一通用 `collect_provider_dataset.py` 和同一 SQLite 上继续完成
  Wave 2-7；没有新增 dataset-specific Python、route、表或 scheduler 分支。120 个
  preactivation active 合同现在形成互斥矩阵：5 个 formal ready、96 个隔离 canary 终态、
  19 个仍阻塞。96 个 canary 终态为 70 `success`、26 `empty`，共 99,051 行 facts；所有
  96 项均完成 authenticated catalog/query 分页读回和重复读取哈希一致性检查，并保留 receipt、
  完整 lineage 与 `transport_service=quicksync`。由于这些新增合同尚无
  `response_completeness`，API 仍正确返回 `partial/degraded`，没有借 canary 提升为 ready。
  剩余 19 项为 15 个 `dataset_field` fanout 和 4 个无 fanout 宽表扫描预算阻塞；其中
  `daily_basic` 的最新 receipt 仍为 failed。隔离库 `quick_check=ok`、当前 SHA-256 为
  `cc2faf9eb8805e0e9cfbf3e889c3b02093a2715d0bf4ff6c471d6aecda2f10c0`；正式 SQLite
  SHA-256 仍为 `e0d567d5a04546fd8fa0e2117f1a2e3ff8e7ffcaa6bbff0d23fbc77b1b5e4b20`。
  所有临时 18085 API 均已停止，production timer 未启用；失败与误配置 receipt 均保留，
  没有删除或改写历史证据。
- 2026-07-23 07:11 CST 的 production no-write cadence plan 证明当时的 permanent collector
  不能直接启用：全 active 会产生 29 个计划（5 current、23 backfill、1 correction），
  `pilot_existing` 也仍含 6 backfill 与 1 correction；七个 completeness 未冻结的数据集还会
  重复规划已有 success 窗口。GitHub `main` 随后新增了显式
  `--activation-wave pilot_existing --current-only` 门禁：只接受这个 pilot wave，且计划与
  执行前均拒绝 backfill/correction/非 current 项，形成 0 backfill / 0 correction 的受审入口。
  该代码已于 2026-07-26 发布到 production，并完成一次受控 latest/current one-shot 与 API
  readback；timer 继续 disabled，Wave 1/2 继续 manual-only，直到跨 cadence fresh evidence 通过。

## 当前停止线

TradingDatas 的 formal 18082 固定内部 API 已上线；当前停止线已收窄为自动 cadence、TA
研究 snapshot 与旧 8082/cron 退役：

1. scope v2 与离线 artifact 已冻结 222 个产品能力；仓库与 production formal runtime
   registry 均有 190 个合同项，GitHub `main` 与 production 均为 29 active / 161 paused；active
   仅代表可发现/可计划，新增 32 项保持
   discovery-only。不得把静态目录或历史 HTTP 矩阵误报为全量采集；
2. `3896969...` 正式 SQLite 与正式 18082 API 已完成 pilot current-only one-shot：
   `trade_cal`、`stock_basic`、`index_classify` 为 `ready`，`daily`、`sw_daily` 为
   `stale/degraded`。daily 仍必须按日期/范围有界查询；消费者不得把 HTTP 200 当成可用性；
3. TradingAgent 专用 read token 与 18082 catalog 已完成以 `tradingagent` 身份的 200 readback，
   未认证为 401；TA 仍须按当前 29-row catalog 动态完成 fail-closed parity，不得要求
   TradingDatas 伪造行证据或新增交易语义；
4. QuickSync 双 DNS 节点仍有一个 TLS 不一致节点，混合大响应和每日额度未知；timer 必须
   保持 disabled，历史回填只能继续人工 bounded one-shot，不能自动恢复；
5. 旧 shadow 18085 已停用；旧 8082、relay、27 条 active SharedSignals cron 及 90GB 代码/数据面仍有真实
   runtime 依赖。两个旧 TD canary 的无依赖代码目录已经删除，但广义旧系统必须等现役消费者切换与
   回滚门禁后分批禁用、观察、删除，数据保留另行批准。

## 当前执行顺序

1. 保持 production timer disabled；TradingAgent 专用只读 token 的 owner/UID handoff 已完成，
   由 TradingAgent 在自身仓按 catalog 动态完成当前 29 个 active dataset 的正式消费 parity；
2. TradingAgent 在自身仓完成 provider-native row/envelope 的 fail-closed parity 与 sim-only
   integration probe；TradingDatas 不新增 TA 专用字段、route 或表；
3. 部署现役 TA consumer，移除 8082 override 后先禁用并观察旧 8082、relay 与 SharedSignals
   writer/cron；跨完整调度周期无旧
   调用且数据窗口守恒后，才分批删除 unit、cron、代码和旧文档。历史 DB/90GB 数据不随
   代码退役删除；
4. 另行解决 DNS/每日额度并做一次有界 cadence pilot；pilot 通过后才启用 timer，再后台 bounded backfill，
   其余 dataset 继续按 entitlement、schema 和真实 readback 分批激活。

## 已验证与未验证

已验证：

- GitHub repository rename；
- 本轮最终候选的本地、`origin/main` / GitHub 与 production 状态必须按上文具体
  commit 和 `pending` / `verified` 证据分别判断，不再用“本地 clone 与远端 main
  一致”把未提交候选、本地主线、远端主线或生产 release 合并成一个事实；
- 三个 pilot dataset 的历史隔离纵向切片；
- capability snapshot 与 generic cadence planner 的本地/GitHub 代码层。
- scope v2（222 产品 dataset）与安全 HTTPS 探测器的 local/origin/GitHub readback，
  以及 484 passed / 1 skipped 的主线组合回归；
- 本地 clean-slate 候选的 190 个 provider-neutral 合同、通用采集与 SQLite transaction receipt；
- 本地候选的独立 clean-overlay 完整回归、静态门禁及 86 PRESENT / 204 DELETED 精确范围。
- clean-slate commit `ea33fabfbac82c6e55ada31d32613ed8c73dac20` 的 local main、origin/main 与 GitHub main readback。
- commit `b4a6aac9a346519b9e6d744fe6521f0a9510c381` 的独立 Token-owner review、服务器隔离 API canary 与 impaired-state readback。
- commit `3fe693f345b19e203842b8e3b1ea80fbe050c283` 的独立 scheduler review、完整本地回归和 installed-but-inactive systemd readback；
- 历史证据：commit `718fed57544c70232fe8b0f55a688bc5f60011b9`、`72876e42f0b14c77476d5732d9f3b474b4193272` 与 `9fa5838451c07fc8a328e37dd70db33976a733d2` 曾完成 manual entitlement probe/request-profile/resolver 的独立 review 与服务器定向回归。probe/policy 已退役；profile/resolver 仅作迁移资料。它们都不定义当前 runtime、activation 或请求合同。
- commit `a7e2e59aae877f9cbe0345ce80cbe0dae1e1fff8` 的 fresh config-hash/lineage review、服务器 immutable release、独立 SQLite 真实 QuickSync 采集、authenticated catalog/query、impaired fail-closed、401 和 same-as-of readback；未切换正式 `current`、18082 或 timer。
- commit `77e81816149cf614f0f2e6f42d340b5fbd23447b` 的 local/origin/live GitHub
  readback、fresh code review、1590/1 全仓回归、服务器 immutable release、
  `index_classify`/`sw_daily` 独立 SQLite 真实 QuickSync 采集、authenticated
  catalog/query、401/404、paused/legacy fail-closed 和 same-as-of readback；临时
  18085 已停止，正式 `current`、18082、timer 与正式 SQLite 未改变。
- commit `d9d480a37700e6936180cea19f276dfed2cf9c22` 的 immutable target/rollback
  verifier，以及单一隔离 SQLite 中 5 active dataset 的 facts/receipts 与全分页
  catalog/query 组合回读；80 项证据 fresh review 为 P0/P1/P2=0。该验证没有切换
  正式 `current`、18082、正式 SQLite、timer 或消费者。
- commit `b395b9017643c61a7f076f02985e9c457cc8d069` 的 local/origin/GitHub、服务器
  immutable release 与相对 `current` readback；正式 SQLite 的两轮 one-shot、23 条
  receipts、48,857 行五数据集 facts 的数据库守恒，以及同库 18085 authenticated
  catalog/query/same-as-of/401/404 证据；该次影子验收当时 timer 未启用、formal 18082 未切换。
- 2026-07-22 正式 18082 切换后的 fresh production readback：
  `tradingdatas-v1-internal.service=active/enabled`、
  `sharedsignals-v1-internal.service=inactive/disabled`、18085 无影子服务，b395
  `verify-current` 为 109 files verified，SQLite `quick_check=ok`、23 条 receipt 与
  48,857 行 facts 未漂移。独立 TradingAgent read token 下，catalog 为 190 项，
  5 个冻结 dataset 的有界 query 均为
  `ready/non-degraded/fresh/valid/lineage-complete`且无 cursor；错 token 为 401，
  旧 route 为 404。
- commit `c3232d0422aa09b83b8d8e9ed6cd87067bcb47cc` 的 local/origin/live GitHub、
  immutable release、trusted verifier、SQLite online backup、systemd-contained Wave 2
  one-shot、三项 facts/receipts 增量守恒和 12 项 authenticated catalog/query readback；
  permanent collector/timer 文件未改变，timer 保持 disabled。
- commit `52d199e8b1c1ce02f9204d0b6bd1c42b4f78e82f` 的 local/origin/live GitHub、
  exact 8-file Wave 3 配置与测试、fresh clean-overlay review（P0/P1/P2=0）、145 项组合
  和 8 项关键门禁；`repurchase`、`research_report`、`top_list` 均保持 `on_demand`，
  不进入自动 scheduler。该提交尚未部署，production catalog 与 TA 当前 handoff 继续为
  12 active。
- commit `8bdc43b84d37d29cba317ac9823877ab3b8ad769` 的 local/origin/live GitHub、
  exact 8-file Wave 4 配置与测试、fresh clean-overlay review（P0/P1=0）、真实 main
  关键 25 项和全量 `1700 passed / 1 skipped / 0 failed`；11 项均保持 `on_demand`，
  显式或默认 scheduler 都是 `0 planned / 11 skipped`，成功 receipt 的 query 仍诚实为
  `partial/degraded`。该提交尚未部署，production catalog 与 TA 当前 handoff 继续为
  12 active。
- TradingAgent 专用 credential 已完成阶段 A dual registration：non-secret reference 为
  `ta-read-20260722T223457Z-0907cd`，旧/新 credential 均在服务器 loopback 对 catalog
  `v1-fcc1aaa39c20743e` 返回 200。2026-07-26 在 TradingAgent 安装并 readback
  `root:tradingagent 0710` parent、确认 schedule/process/runtime holder 均为 0、旧 front
  inactive/runtime-masked、8787 closed 后，发布侧原子替换为 leaf-only tmpfiles 规则并安装新
  runtime leaf。leaf 为 `tradingagent:tradingagent 0600`、regular、nlink=1；以该身份读取
  18082 catalog 返回 200，未认证返回 401。随后 2026-07-26 的 `3896969...` current-only
  release 将 catalog 更新为 190 项：3 `success`、9 `stale`、14 `unobserved`、164 `paused`，
  如实反映 26 active 不等于 26 ready，且 collector timer 仍 inactive/disabled。freeze marker 已记录
  `runtime_cutover_complete_unfrozen`；8082、timer、真实交易和旧 front 均未改变。token 与 token
  hash 从未进入消息、日志或 evidence。
- 2026-07-26，commit `3896969983585ccd1e448f4a1eefb83c6c596255` 的本地、origin 与 GitHub
  main 一致；immutable release 经 trusted verifier 读回为 112 files verified。正式 current
  已原子切换到该 release，`tradingdatas-v1-internal.service` active，18082 未认证为 401，
  `tradingagent` scoped token catalog 为 200。一次 `pilot_existing --current-only --execute`
  service run exit 0：仅完成 `trade_cal` 与 `stock_basic` 的 current success，`daily` 与
  `sw_daily` 因历史 data-through 如实为 stale/degraded；`index_classify` 保持已有 ready receipt。
  SQLite `quick_check=ok`，且 timer 继续 disabled。此条是内部服务基线证据，不是全量接口采集、
  自动 cadence 或 TradingAgent production parity 的完成证明。
- 2026-07-26，production `current` 已按 immutable manifest 原子切换到
  `42c89e3ed2cb5867d79a8ce235d75dd2c27e59d1`；18082 API 重新启动为 active，collector
  仍 inactive、timer 仍 disabled。以该 release、同一 `tradingdatas` runtime identity 和
  QuickSync transport 对冻结的 190 合同执行 `executable` HTTPS probe：139 项具有安全请求
  形状并实际执行，结果为 4 `success`、11 `valid_empty`、124
  `provider_failed_unclassified`；另有 51 项因冻结计划缺少安全参数或依赖而未调用。证据为
  `/opt/investment-data/tradingdatas/evidence/https-probe-42c89e3ed2cb5867d79a8ce235d75dd2c27e59d1-20260726T101410Z/probe-evidence.json`，
  `request_authorizations=139`、总响应字节 95,417。4 项 success 是 `stock_basic`、`trade_cal`、
  `fut_basic`、`fut_trade_cal`；11 项 valid-empty 不能替代有数据或完整性证据。4 个失败响应
  含敏感回显，evidence 仅记录 `response_redacted=true` 与空 SHA，不保存正文。该结果推翻
  “已全量稳定采集”的说法：只有经后续 SQLite receipt 与 catalog/query readback 验证的成功项
  才能 promotion，失败/blocked 项继续 paused，不能自动启用 timer。
- 2026-07-26，对最新已知开市日 `20260724` 的只读定向 QuickSync 探测确认：`daily` 返回
  5,526 行，而 `sw_daily` 返回 provider code `40101`（权限不足）、零行；两次探测均未写 SQLite。
  生产 read-only SQLite 同时显示日线事实只到 `20260722`，而交易日历只有 `20260726` 的休市行
  并携带权威 `pretrade_date=20260724`。因此日线阻塞是通用计划器未利用已验证前一开市日字段，
  不是日线 entitlement 缺失；下一候选只在通用 calendar policy 中声明该字段并以 TDD 修复，
  不增加日线专用 collector、route 或 consumer 逻辑。`sw_daily` 仍保持 provider-impaired，
  TradingAgent 必须继续 fail closed，直到获得真实 provider 成功 receipt 与 API readback。
- 随后以现役、通用 `collect_provider_dataset.py` 对 `daily@20260724` 执行一次受控 one-shot：
  5,526 行 returned/validated/committed/inserted，rejected 为 0，新增 1 条 success receipt；执行前
  SQLite online backup 保存在受限 evidence 目录，执行后 `quick_check=ok`，日线分区上界为
  `20260724`。以 `tradingagent` scoped credential 通过 18082 `POST /v1/query` 回读为
  `ready/success/fresh/valid/lineage-complete`，水位 `2026-07-24T00:00:00+08:00`；没有启用 timer、
  改动 8082 或输出 token。该 one-shot 只恢复日线内部可读性，不代表 `sw_daily` 或 190 个合同已可用。
- 为防止已知 `40101` 在后续 current-only 计划中被反复调用，候选将 `cn.dataset.sw_daily` 从
  `pilot_existing` 自动执行波次移出；它仍留在 catalog 中如实投影为受损，只有取得新的真实 provider
  成功 receipt 与 API readback 后才可重新进入自动波次。该变更不新增专用 collector、路由或交易语义。
- 同一受控波次的 `stock_basic` 成功返回并校验 5,950 行，全部为已有事实的幂等 unchanged，仍写入
  success receipts；`index_classify` 实测返回 QuickSync `40101` 与“您的权限不足”。候选把该标准
  权限措辞纳入通用、code-gated 的 `permission_denied` 分类，并将 `cn.dataset.index_classify` 与
  `sw_daily` 一并排除出自动波次。它们继续保留在 catalog，等待将来新的真实 provider 成功证据，
  不会被当成可用或无限自动重试。

未验证：

- 190 个已有合同接口在正式 HTTPS transport 与服务器 release 上的逐项 readback；
- 新增 32 个产品 dataset 的正式合同/安全请求映射及 222 项 runtime catalog/API 投影；
- QuickSync 每日额度及双 DNS 节点 failover 的 production runtime 证明；
- 所有首期接口的真实采集与正确频率；
- 后续激活项在正式 production SQLite 的 Tushare facts/receipts/catalog/query readback；
- 现役 TradingAgent front 从旧 8082 override 切到 18082 的完整运行验收；
- 旧生产系统删除。

任何后续“完成”必须分别给出 local、GitHub、production files、production runtime、真实 receipts、API readback 和消费者证据。

外部受邀账户 Beta 的上游缓存、再分发和对外服务条款尚未书面核验；当前只推进内部只读服务，不把 QuickSync 可调用误报为可对外再分发。
