# TradingDatas 当前状态

最后更新：2026-08-16 11:50 CST。

> **2026-08-16 OI dump 生产评审修正：有界回看 + 历史回填（代码层事实，无生产
> 变更）：** 评审发现两点并已在同一 candidate 上修正。(1) 发布滞后永久跳日：
> 实测 UTC 03:05–03:45 时 2026-08-15 的 metrics zip 仍 404（2026-08-14 可用），
> 原"最近完整日"窗口在每日一发的 timer 下失败即跳日。runner 改为 7 天有界回看：
> 缺口从 SQLite facts + 经验证 success receipt 推导（不看运行历史），每个 symbol
> 采集"已发布且尚未入库"的最新一日，已覆盖窗口的 symbol 标 `unchanged` 不调
> provider；文件缺失仍是诚实失败，但缺口留在库里，后续 tick 自愈，不再永久跳日。
> timer 相应调为每 2 小时一发（`*-*-* 00/2:37:00`，与 5 分钟 timer 错峰）。
> (2) owner 批准 OI 历史回填对齐 bar 历史：新增有界 `--backfill-days 198`（其它值
> 拒绝；以最近完整 UTC 日 2026-08-15 计 198 个窗口起于 2026-01-30），逐日一批
> （10 币）持锁、批间放锁并以等待方式重新取锁，5 分钟采集链只在批边界看到已有的
> 锁忙自愈噪声而不会被长时间饿死；已入库日按同一 receipt 校验推导跳过，中断重跑
> 自动续跑；回填为一次性手工操作，不进任何 timer。真实端到端证据：404 诚实失败
> （2 张 failed receipt、0 行）、真实下载 2026-08-14/08-13 两日各 2880 行成功
> 入库、2 日真实回填 20 张 receipt 且重跑 collected=0。timer 仍 disabled，
> 生产启用门禁不变。
> **2026-08-16 Tushare `news`（快讯）合同冻结为 contract_ready
> 候选（代码层事实，无生产变更）：** `cn.dataset.news` 从
> `ingest_contract_state: blocked`（`required_enum_unresolved`）转为
> reviewed contract：主键 `[datetime, title]`（响应无显式 id、无 source
> 列，datetime/title 声明非空），`event_or_intraday_window` 请求形状
> （start/end `local_datetime_seconds` 窗口 + 官方文档唯一命名的
> `src: sina` literal），cadence `event`，无分页参数。因四种通用
> completeness 策略均要求响应侧 fanout/分区字段而 news 响应不具备，
> `response_completeness` 保持 `null`（同形状 `npr`/`stk_nineturn`
> 先例），`as_of/range/partition` 同样为 `null`（`as_of_format` 不支持
> local datetime，同 `major_news` 先例）。activation 维持 `paused`、不加
> wave、不做自动调度：2026-08-16 有界探测（1 小时窗口 114 行）只证明合同
> 可编译，激活需另行新鲜 HTTPS 证据与人工审核。`cn.dataset.major_news`
> 此前已按 `dimension_fanout` 合同激活，本次不改动。
> **2026-08-16 Binance USDⓈ-M open interest metrics-dump 降级采集
> contract_ready 候选（代码层事实，无生产变更）：** 针对上一条记录的
> `fapi.binance.com` SNI 级阻断，owner 批准 dump 降级方案：open interest 改用
> 已实测可达的 `https://data.binance.vision` 日度 metrics zip
>（`futures/um/daily/metrics/<SYMBOL>/<SYMBOL>-metrics-YYYY-MM-DD.zip`，单 CSV、
> 8 列、288 个 5m 行、行序乱序、UTC 日结后发布）日更积累；funding rate 无
> dump（404）仍不可得。dataset 复用决策：喂同一批
> `crypto.perp.binance.<symbol>.open_interest` dataset（schema、主键
> [symbol, timestamp]、append_only + payload_hash 幂等均不变），新增第二个
> provider binding `binance_usdm_dump`（active），原 fapi binding 置
> `activation_state: paused` 以满足 ingest 恰好一个 active binding 的约束，
> 不产生新 dataset 家族。新 provider-level adapter
> `collectors/binance/oi_dump_collector.py`（transport 为批量文件下载而非 REST
> JSON API，符合新增 adapter 条件；拒 redirect、校验 zip 成员名/表头/完整 288
> 行 5m 网格/symbol，行映射到既有 OI schema；dump 独有的 long/short ratio 列只
> 做形状校验不入本 dataset）。新 candidate runner
> `tools/run_binance_oi_dump_canary.py`（无 provider/symbol 输入、共享
> `/run/tradingdatas-crypto/collect.lock`、plan/execute、窗口=最近已完整 UTC
> 日、一次 provider 重试）与
> `tradingdatas-crypto-binance-oi-dump-collect.{service,timer}` unit 对（每日
> UTC 00:37，与 5 分钟 timer 错峰共享锁）。本条只声明 **contract_ready**：
> dump timer 必须保持 disabled，直到隔离生产评审完成真实 provider → SQLite
> receipt → authenticated catalog/query readback（observed）与连续 cadence
> 证据（stable）后才可启用。fapi binding 暂停期间，已 disabled 的
> `run_binance_usdm_canary.py` 的 open interest 半侧不再可执行（funding rate
> 半侧不变）。本次没有 release、service/timer 启用、数据库或交易权限变更。

> **2026-08-16 USDM 切片生产评审：网络层阻断，timer 维持 disabled
>（`observed_at≈2026-08-15T17:30Z`）：** release `63c2632` 已切换，受控真实采集
> 首轮失败。逐层诊断确认根因在网络而非代码：服务器解析 `fapi.binance.com` 仅得
> IPv6（无可用路由）；用真实 IPv4 实测 TCP 443 可连通但 TLS 握手被 RST——
> SNI 级阻断，现货 `data-api.binance.vision` 不受影响的唯一区别是 SNI 名称。
> 旁证：公共 dump 站 `data.binance.vision` 可达（HTTP 200），futures `metrics`
> 日度 zip（含 5m OI）可下载，`fundingRate` 无 dump（404，仅 API 提供）。
> 结论：在 owner 决定网络路线（代理/中继，涉及治理与合规）或接受 dump 降级方案
> （OI 日更、无 funding rate）之前，USDM 切片保持 contract_ready、timer disabled；
> 现货 bars/rules/book-ticker 采集与 API 未受影响。

> **2026-08-16 Crypto book-ticker timer 定时不确定性消除：** 首小时生产观测发现
> 两类拒收（TradingAgent 侧 `crypto_spread_watermark_invalid`，fail-closed 按设计
> 生效、bar 链无损）：(1) `*:0/5:20`+10s 抖动与 bars 采集（`:00`+10s 抖动起跑、
> 最慢 25s）窗口重叠撞 collect 锁，整轮失败；(2) Binance 公共端点偶发慢响应
> （首笔 7.6s、整轮 39s）使 9 个 symbol 的 receipt 完成时刻越过消费者 `:55`
> cutoff。timer 改为 `*:0/5:40`、`RandomizedDelaySec=0`：bars 最坏 `:10+:25s`
> 结束，确定性错开；正常采集 `:45-:50` 完成仍留 cutoff 余量。上游慢响应造成的
> 偶发缺槽接受为可见噪声，下一槽自愈。采集语义与隔离合同不变。

> **2026-08-15 Binance USDⓈ-M 永续公共只读切片 contract_ready 候选
>（代码层事实，无生产变更）：** 根合同首期范围已扩展加入同一冻结 10 个
> USDT 标的的 Binance USDⓈ-M 永续 funding rate 与 open interest 公共只读历史。
> 新 provider adapter `binance_usdm`（`https://fapi.binance.com`，无 key、无账户、
> 拒 redirect）接入 `fundingRate` 与 `openInterestHist` 两个公共历史 endpoint；
> 冻结 universe 合同不变，单一 pinned canary registry（原
> `crypto_binance_spot_canary_registry.v1.yaml` 更名为
> `crypto_binance_canary_registry.v1.yaml`，因 18083 隔离 API 只能服务一份
> pinned registry）由同一确定性编译器扩为 50 个 dataset（30 现货 + 20 永续候选），
> schema_major=1、append_only + payload_hash 幂等积累。新增 candidate runner
> `tools/run_binance_usdm_canary.py`（无 provider/symbol 输入、共享
> `/run/tradingdatas-crypto/collect.lock`、一次 provider 重试）与
> `tradingdatas-crypto-binance-usdm-collect.{service,timer}` unit 对（与现货
> 采集错峰两分钟）。本条只声明 **contract_ready**：没有真实 provider receipt、
> catalog/query readback 或连续 cadence 证据，不是 observed/stable；USDM timer
> 必须保持 disabled，直到生产评审完成真实采集与 authenticated readback 后才可启用。
> 本次没有 release、service/timer 拓扑、数据库或交易权限变更。

> **2026-08-15 Crypto book-ticker timer cadence 对齐消费者 cutoff：** timer 从
> `*:2/5:30` 前移到 `*:0/5:20`。TradingAgent 观测槽的 watermark 要求证据
> `observed_at ≤ bar 收盘 +55s`；原对齐下最新快照（`:02:30`）晚于 cutoff，会被
> 消费者按 PIT 纪律逐槽拒收。bars 采集于 `:00` 起跑约 5 秒结束，`:00:20`（+10s
> 抖动）无锁冲突，快照 `observed_at ≤ :00:40` 落在 cutoff 内。采集语义、unit
> 隔离与 readback 证据不变。

> **2026-08-15 Crypto book-ticker 5 分钟采集源码候选
>（候选证据 `observed_at=2026-08-15T14:29Z`）：** Kimi 候选记录十个
> `.book_ticker` 数据集完成一次隔离 provider-to-API review：service-identity
> 按需采集写入十张独立 success receipt，随后以 `tradingagent` 身份做认证
> 18083 query readback，每个数据集返回 `ready/fresh/valid`、`degraded=false`。
> 源码候选新增专用 `tradingdatas-crypto-binance-book-ticker.service/.timer`
>（`*:2/5:30`，与 bars、rules timer 错开，共用同一把 collect 锁）。本记录不表示
> unit 已安装、启用或 runtime-effective；这些层仍需 Controller 的 immutable release、
> unit readback 和自然运行证据。每次采集只保留每个 symbol 最新一张 receipt-bound
> 快照，不积累历史序列；bar/rules timer、A股 18082、交易权限均未改变。

> **2026-08-15 SharedSignals 物理清理核验与 source 纠偏
>（`observed_at=2026-08-15T13:24:51Z`）：** 当前服务器上
> `/opt/investment/sharedsignals-runtime`、`releases/sharedsignals-v1`、
> `_archive/SharedSignalsV1Source-retired-20260801`、
> `_archive/SharedSignals-retired-active-path-20260801` 均不存在；顶层没有
> `SharedSignals-release-candidate-*`，systemd 搜索路径和 unit-file 列表也没有
> SharedSignals 条目。历史 Tushare 数据归档
> `_archive/sharedsignals_retired_data_tushare_20260709T044641Z` 仍存在，未获单独数据删除
> 授权；删除前清单 `/tmp/sharedsignals-delete-inventory-20260815T130057.txt` 仍存在，
> SHA-256 为 `be469407bdf42992ba62317ef0fdb11af6844e176e213277faf5ed0226a1ff0e`，
> 共 9,477 行。`tradingdatas-v1-internal.service` 为 active/success/exit0，collector timer
> 为 enabled/active；这只证明当前服务层未因旧运行面清理而中断，不代表所有 dataset
> stable，也不授权删除历史数据。
>
> 本地 canonical checkout 继续在受保护的 KimiCode 候选分支 `release-full-universe`
> `18f1c9f`，不作为 source/release authority。GitHub `main` 与 ordinary server source
> 已分别读回 `68398f00c0beb404cc3c0f5a7be93bac8568c3bd`；服务器候选分支仍保留
> `18f1c9f`。immutable effective release 仍为
> `e6dc519101174ba6158ce3e8d180eefee385c9ff`，本次没有 provider、数据库、release、
> service/timer 拓扑或交易权限变更。原始未合并文档提交 `dc0e361` 已保存在
> `archive/td-sharedsignals-delete-record-20260815T2125CST`；其中带日期的数量和删除现场
> 未复制进长期 `docs/OPERATIONS.md`，只前向保留已验证的稳定退役行为与本条运行记录。

> **2026-08-15 当前分层事实（`observed_at=2026-08-15T02:48+08:00`）：** GitHub
> `main` 与普通服务器源码均为
> `dabe0dc081d3a06e811939abeb6525a8148fb8d9`；immutable effective release 仍为
> `e6dc519101174ba6158ce3e8d180eefee385c9ff`。本地 canonical checkout 正由外部协作者
> 使用且存在未交接改动，不参与本次验收，协作者交还前不声称本地与其他层已同步。
>
> 同一次有界读回 `observed_at=2026-08-14T18:23:44Z`：自然 collector 于
> 02:20:11—02:21:04 CST 以 `Result=success/ExecMainStatus=0` 结束，`terminal=11`、
> `success=3`、`valid_empty=8`、`failed=0`、`pending=false`、`planned=0`、
> `committed=943`、`receipt_count=11`；数据库共 6,891,918 行，最新采集时间为
> `2026-08-14T18:20:13Z`。`tradingdatas-v1-internal.service` 为 active，匿名
> catalog 返回 401；collector 当时 inactive/success，timer 为 enabled/active。该证据只证明
> `e6dc519` 这一运行层的本轮健康采集，不代表所有 dataset 已达 `stable`，
> 也没有手工重放 provider。PR #152 只修正 source compiler 的可重现投影；生成的
> runtime 字节未变，因此未切换 release。

> 以下 2026-08-03 等条目是带日期的历史运行记录，不得覆盖上面的当前摘要，也不得替代
> 本轮 receipt/API/consumer readback。当前 release、服务和 timer 事实每轮仍需重新核验。

> **2026-08-03 A 股分钟 cohort 扩容准备：** 当前生产 `cn.dataset.rt_min` 的正式
> registry 仍为冻结 30 标的 rollback canary；本轮没有修改其 runtime、release、service、timer、
> SQLite 或外部路由。新增的离线 capacity compiler 只能从 receipt-bound、immutable 的 500
> universe 编译一个恰好 100 标的 `activation_state=paused` candidate，并输出包含来源 receipt、
> universe hash、shard hash 与 consumer readback 门的 reference。若 base registry 的 30 标的
> canary 漂移、universe/hash 不合法或 shard 越界，编译/回归会 fail closed。该能力目前仅为
> **contract-ready**：尚无本轮 reviewed security-master snapshot、真实 100 标的 receipt、
> catalog/query、TradingAgent 或 TradingCopilot consumer readback，故不是 live/stable，也未扩大
> A 股采集范围。权威边界和下一步见 `docs/ASHARE_MINUTE_COHORTS.md`。

> **2026-08-03 Crypto catalog runtime projection release：** 已合入的 PR #89
> `107483e8ca1e8cf86b81a456f931da6fcb9df2ca` 以本地 clean commit 的受控 Git archive
> 和 manifest 经 `marketgraph-root` staged；服务器 GitHub checkout 没有被当作发布前置。
> 18083 的 immutable `current` 已由 `557a2967bc9582ffef26bc412d702767e0ef5c17` 原子切至
> `107483e…`，target 141 文件和 rollback 134 文件均经 trusted manifest verifier 逐字节
> 验证。18083 API restart 后为 `active`，以 TradingAgent 身份认证的 `/v1/catalog` 读回
> 30 个 datasets，耗时 4.62 秒；这修复了旧 catalog 在双重 runtime projection 下约 8.6 秒、
> 超出消费者 8 秒读取界限的直接原因。
>
> 同一 release 上手工执行了一次 G5 closed-5m round-trip **模拟**：服务在 54 秒后以
> `status=completed`、exit status 0 结束，记录 `market_data_access_attempt_count=1` 与新的
> `fresh_query_catalog_version`；`REAL_TRADING_ENABLED=false`、无 broker、无资金执行权限。
> 18083 service 与 G5 timer 均为 active。该证据证明一次真实 loopback
> `TradingAgent -> TradingDatas -> receipt/query -> TradingAgent` 已越过原 catalog timeout，
> 但不是多周期连续稳定性或真实交易证明；后续自然 timer receipt 仍须单独观察。

> **2026-08-03 发布获取修复与接口窗口复核：** 服务器 source 已使用独立、root-only、
> GitHub read-only deploy key 完成 `fetch`，并 fast-forward 到本次发布目标
> `83573f617341f75c978b944f203938bbc53cf1ae`；生产 `current` 已从 `e6b3123` 原子切到
> 同一 commit。当前内部 API 的实际 unit 是
> `tradingdatas-v1-internal.service`，状态 `active/running/enabled`，18082 仅监听
> `127.0.0.1`；匿名 `/v1/catalog` 返回 401 是认证合同，不是服务故障。通用 collector
> timer 也为 `active/waiting/enabled`。
>
> 先前 source 停在 `983c5f6` 且 GitHub SSH 返回 `Permission denied (publickey)` 的阻塞
> 已解除。新 preflight 必须先读取 source 的受限 SSH 命令、执行 `fetch origin main` 并读回
> target commit；read-only key、严格 host verification、source checkout 与 immutable
> release 分离。API restart 后必须以有界等待取得预期 401，再宣布 release 成功；单次立即
> connect failure 会自动回滚，不能误判为 target 故障。
>
> 数据集层面，`anns_d`、`cctv_news`、`irm_qa_sh`、`irm_qa_sz`、`research_report`、
> `moneyflow`、`moneyflow_ths` 和 `rt_min` 在当前 release 都是
> `active/executable/ready`；最近 collector 记录显示它们按各自 cadence 为 `not_due`，或在
> 当前分区返回合法 `empty`，而非 provider/validation error。历史已完成分区超过 86400 秒
> freshness SLA 时会正确投影为 `stale/degraded`，不能据此阻塞其它合同/config 开发，也不能
> 声称当前 observed/stable。`cn.dataset.news` 仍有明确合同缺口：必填 `src` 未冻结可用
> enum/默认值，故 `paused/blocked`；需以小批、受控真实 probe 固化该参数后才可激活。

> **2026-08-03 冻结 30 标的 `rt_min` production release：** GitHub `main`
> 的 `e6b3123da027399826a17e1c25152f0d793c14c4` 已从已验证 rollback
> `2cd289db369ffebdb7b475ce71d45c9d5993eb48` 原子切为 18082 的 immutable
> `current`。target 和 rollback manifest 均由 trusted verifier 逐字节验证；首次
> health probe 在 API listener 绑定前立即触发自动 rollback，未留下半切换状态；第二次在
> 有界等待至第 4 秒取得预期匿名 `401` 后完成切换，并恢复既有
> `tradingdatas-v1-internal.service` 与 generic collector timer 为 active/enabled。
>
> target physical registry 的 `cn.dataset.rt_min` 为 `freq=5MIN`、
> `request_shape=snapshot_or_date_range`、`fanout.strategy=none`，含 30 个唯一
> `ts_code`。这证明 production 代码与 30 标的静态合同已一致；匿名 `401` 只证明 API
> 认证边界，尚不是数据 readback。下一自然交易日仍必须取得新的 30 标的 complete receipt、
> freshness、精确 `as_of` catalog/query 全分页 readback，以及 TradingAgent 和
> TradingCopilot 的受认证消费者读回；这些证据完成前不得称为 live/stable，也不得扩容。
> A股真实交易、资金、订单、Crypto 与其它数据集均未改变。

> **2026-08-02 `dc_daily` complete-response v3 已正式部署：** PR #75
> 的 schema 2 selectable-field release 曾在正式 `trade_date=20260731` 读回时暴露
> append-only 历史混读：1,031 个逻辑 identity 对应 2,062 行，旧 payload 不含
> `category`，API 正确降级。该 target 已回滚；旧 facts、receipts 与证据均未删除。
>
> 随后 PR #77 将完整响应合同升为 `cn.dataset.dc_daily schema_major=3`，而非修改所有
> append-only dataset 的 global current-query 语义。旧 schema 2 保持历史审计可读；v3 用
> 独立物理 storage cohort 收集含 `category` 的 payload。isolated immutable
> `5a1aeebd907f717aafa3b5ff88abeda0f985ce68` 的 target 与生产 rollback manifest 均验证通过；
> 独立 SQLite 的一次 generic on-demand collection 为 `1031/1031` success，所有 v3
> `[trade_date, ts_code]` identity 唯一且 `category` 无缺失、`quick_check=ok`。临时 18084
> 以 UID987/现有只读 scope 回读三页 1,031 行、terminal cursor、payload replay 一致、receipt
> 与 lineage 完整；因为 20260731 已跨日级 SLA，metadata 诚实为 `stale/degraded`，不是质量或
> 分页失败。18084 已停止。
>
> 随后从 verified rollback `983c5f63fee1c166db40859420f817b04cc639d9` 原子切至 immutable
> `current=2cd289db369ffebdb7b475ce71d45c9d5993eb48`；target 与 rollback manifest、target
> physical registry byte-equality 均通过，18082 API 与既有 generic timer 已恢复 active/enabled。
> 对同一 completed partition 的 formal generic on-demand collection 先通过 no-write plan，后写入
> 一张 v3 success receipt。UID987 经正式 18082 catalog/query 全页双读得到三页 1,031 行、1,031 个
> 唯一 `[trade_date,ts_code]`、零缺 `category`、terminal cursor、payload replay 一致，receipt 与
> lineage 完整。周末读时钟使 envelope 继续如实为 `stale/degraded`，而非质量失败；下一可用日的新鲜
> receipt/readback 才能使 v3 进入 fresh/valid 内部可消费集合。A股分钟、Crypto、TradingAgent 与真实交易均未改变。

> **2026-08-02 Crypto 有界瞬态重试发布：** 独立 Crypto immutable
> `current=557a2967bc9582ffef26bc412d702767e0ef5c17` 已从已验证 rollback
> `a60e5425c9119bf9fe24c1b08a070907db58febd` 原子切换；两份 manifest 均通过验证。
> 变更只影响 18083 的已关闭 5 分钟 Binance bar collector：某一 dataset/window 写入
> terminal `provider_error` receipt 后，最多立即重试一次；配置、校验与合法 empty 永不
> 重试，二次失败仍保持失败，不存在替代 provider、替代 bar 或交易 fallback。
>
> 切换后既有 18083 API、closed-5m timer 与 rules timer 均恢复。20:40 和 20:45 CST 两轮
> 自然自动采集各为十标的 success；日志表明已执行新 release（每项 `retry_count=0`）。
> UID987 对 BTCUSDT 的固定 13 根 terminal window 做同一 `as_of` 双读，结果均为
> `ready/success/fresh/valid/non-degraded`、receipt/lineage 完整且 canonical replay 一致。
> 本两轮没有触发真实 `provider_error`，因此这只证明新运行面、自然采集和回放正常；
> 有界重试对短暂上游失败的在线恢复仍待未来真实 receipt 证据验证。A股 18082、其 timer、
> TradingAgent 资金/订单与 `REAL_TRADING_ENABLED=false` 均未改变。

> **2026-08-02 daily-reference wave 受控采集：** 对 `trade_date=20260731` 的
> `cn.dataset.adj_factor`、`cn.dataset.margin`、`cn.dataset.margin_detail` 与
> `cn.dataset.stk_limit` 先做同一 generic batch plan，再由现有 service 执行一次。结果为
> `adj_factor=5548`、`stk_limit=7716` 的 success receipt，以及 `margin`、`margin_detail`
> 各一张合法 empty receipt；没有 validation/provider error、专用 collector 或新的 timer。
>
> UID987 的 formal 18082 有界读回显示：前两项各首页 500 行且存在 next cursor，receipt 与
> lineage 完整；它们在周末按 86400 秒 SLA 如实为 `stale/degraded`。后两项为 0 行、terminal
> cursor、`state=empty`、`quality=valid`、`degraded=false`，receipt/lineage 完整，明确表示
> provider 当前分区合法返回空，而不是采集失败。本轮没有执行两项大分区的全页重放，所以不能把
> 这条有界 readback 表述为完整分页 API 验收；历史数据也不得作为实时或执行证据。

> **2026-08-02 event wave 正式历史分区闭环：** 复用同一个 generic on-demand batch，
> 对已完成的 `20260731` 分区依次采集 `cn.dataset.anns_d`、`cn.dataset.cctv_news`、
> `cn.dataset.irm_qa_sh` 与 `cn.dataset.irm_qa_sz`。无写入 plan 先通过；随后单个 service
> batch 成功，四项各自写入一张 success receipt，返回/校验/提交分别为
> `1514/1514/1514`、`15/15/15`、`326/326/326` 与 `6/6/6`。没有新增 route、collector、
> timer、表或 provider 专用逻辑。
>
> UID987 经 formal 18082 对四项顺序全分页后再重放：`anns_d` 为四页 1514 个唯一
> `[ann_date,ts_code,title,url]`，其余三项为一页、分别 15/326/6 个唯一 identity；全部
> terminal cursor、重放 identity digest 一致、receipt/lineage/`data_through`/`observed_at`
> 完整。读取发生在周末，四项都按 86400 秒 SLA 如实投影为
> `stale/degraded/quality invalid`，唯一原因 `freshness_sla_exceeded`；这是历史分区的读时钟
> 状态，不是 provider、校验、身份、分页或 receipt 失败。它们可作为 receipt-bound 历史观察，
> 不能作为实时、PIT、策略或执行证据。

> **2026-08-02 `research_report` nullable-author 合同修正已发布：** 不可变
> production `current` 为发布代码
> `983c5f63fee1c166db40859420f817b04cc639d9`；原
> `4acfb6b8f57678c18261bf0d28a4517683ababbb` 已通过 manifest 验证并保留为回滚。
> 本次只将 `cn.dataset.research_report` 升为 schema major `2`，其稳定 identity 改为
> `[trade_date, title, url]`，并将上游可合法缺失的 `author` 声明为 nullable；未新增
> route、collector、timer、表或交易语义。目标 release 与回滚 release 均逐字节验证，目标
> registry 由其物理 release 重编译后与 checked-in registry 一致；随后在短暂受控窗口内原子
> 切换并恢复 18082 API 与既有 generic collector timer。
>
> 随后以现有唯一 generic collector 对 `trade_date=20260731` 做一次受控 on-demand
> collection，得到 `returned=validated=committed=66` 和一张 success receipt；没有重试、
> 专用 collector 或新增 timer。UID987 的正式 18082 两次同请求读回均为 HTTP 200、66 个
> 非空唯一 `[trade_date,title,url]`、terminal cursor、相同 identity digest，且 receipt、
> lineage、`data_through` 与 `observed_at` 完整。catalog 为 190 datasets、
> `catalog_version=v1-e23dc83446ca082f`，该 dataset 公开 `schema_major=2` 与
> `identity_fields=[trade_date,title,url]`。因为该历史分区在周末已超过 86400 秒 SLA，两个
> envelope 都如实为 `stale/degraded/quality invalid`，唯一 evidence 是
> `freshness_sla_exceeded`；这不是采集、identity、receipt 或分页失败，仍不能用作实时、PIT、
> 策略或执行证据。A股分钟、Crypto、TradingAgent、凭证与真实交易均未改变。

> **2026-08-02 `major_news` 正式按需闭环：** GitHub `main/origin` 与
> 18082 immutable `current` 均为 `4acfb6b8f57678c18261bf0d28a4517683ababbb`；已验证
> rollback `bad65a77bd95b0ca0db0abfbe8626e160533acdc` 保留。该 release 让既有唯一
> `tradingdatas-provider-native-collect.service` 在没有 selector 时保持原 cadence planner，
> 在受控 selector 存在时以同一 `tradingdatas` 身份与 `/run/tradingdatas/collect.lock` 执行
> 一次有界 on-demand batch；它不新增 timer、route 或数据集专用 collector。selector 与
> batch 在结束时被消费，避免 timer 重放；合法 empty 仍被 systemd 视为完成，provider/
> validation 失败则保持失败。
>
> 对 `cn.dataset.major_news` 的正式一分钟窗口 `2026-08-02 17:25:00..17:26:00 +08:00`，
> service-identity generic collection 写入真实 receipt。UID987 经 formal 18082 两次相同
> `POST /v1/query` 均返回 1 行、terminal cursor、相同 rows/metadata digest，
> `ready/success/fresh/valid/non-degraded`，receipt
> `receipt:53f2e49778690cdf0959bb8c7cd1a2fbb10aa26639c68d6d797904226fa61327` 与完整
> Tushare/QuickSync lineage；`data_through=2026-08-02T17:26:00+08:00`，
> `observed_at=2026-08-02T10:00:28.654706+00:00`。这是新闻/公告事件的只读、receipt-bound
> observation evidence，可供 TradingAgent event shadow 使用；不等同历史 PIT、策略信号、
> 订单、仓位或任何交易 authority。A股分钟、Crypto、TA timer、broker 与
> `REAL_TRADING_ENABLED=false` 均未改变。

> **2026-08-02 Crypto current best-bid/ask readback:** GitHub `main/origin`
> `a60e5425c9119bf9fe24c1b08a070907db58febd` was built as the dedicated
> Crypto immutable release and atomically became
> `/opt/investment/releases/tradingdatas-crypto/current`. The verified rollback
> is `9bbf270fa91342b2ce3519de0c007d6f14d2525b`. The rollback verifier first
> rejected two manifest-external Python cache files; their exact removal left
> code, facts and receipts untouched, and the rollback release then verified.
> Target and rollback manifests both verified before the switch. Existing 18083,
> the closed-5m timer and the rules timer were restored; the next automatic
> 13:20 CST closed-bar run returned `success`.
>
> The formal 18083 catalog now exposes ten frozen `.book_ticker` datasets.
> One service-identity, on-demand collection wrote ten valid rows and ten
> distinct success receipts through the ordinary provider-native transaction
> path. A serial authenticated 18083 catalog/query check as `tradingagent`
> asserted one row per dataset, `ready/success/fresh/valid/non-degraded`
> metadata and complete receipt/lineage. This data is only a receipt-bound
> current Binance best-bid/ask snapshot: the upstream response has no event
> timestamp, so it is not historical L1, depth, replayable market-time series
> or execution evidence. No book-ticker timer was added; existing 5m bars and
> public-rule timers remain the only automatic Crypto collectors. A-share 18082,
> TradingAgent execution, accounts and real trading were not changed.

> **2026-08-02 Crypto historical-coverage verification:** The frozen
> ten-symbol 5m cohort already has 52,957 non-duplicate, continuous bar
> identities per symbol from 2026-01-30 through 2026-08-02 04:35 UTC. A
> bounded, authenticated formal 18083 query over 2026-02-03 returned 12/12
> unique bars for each symbol, terminal pagination, non-degraded
> `ready/success/valid` metadata and complete receipt/lineage. The approved
> 180-day backfill is therefore already satisfied; it is historical
> observation/research coverage, not historical PIT or live-execution proof.
> A redundant manual re-run was stopped after its shared collector lock caused
> the 12:35 live cycle to fail closed. No facts were overwritten; the 12:40
> timer cycle automatically recovered with a complete ten-symbol current
> receipt. Do not repeat the full backfill while the live collector is active.

> **2026-08-02 Crypto 10-symbol continuous readback:** Crypto remains a
> separate internal runtime on formal 18083, with its own release, SQLite,
> service identity and timers; A-share 18082 was not touched. Authenticated
> bounded queries verified two adjacent completed 5m windows for the frozen
> BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, DOGEUSDT, ADAUSDT, TRXUSDT,
> LINKUSDT and AVAXUSDT cohort. Each dataset returned a terminal page with 12
> unique bar identities, `ready/success/fresh/valid/non-degraded` metadata and
> complete receipt/lineage. The two most recent bar open times were 04:10 and
> 04:15 UTC. This closes the earlier 10-symbol live-readback gap; it is
> data-service evidence only, not an order, account or execution authority.

> **2026-08-02 `tdx_daily` 正式历史分区回读：** 生产代码基线
> `main/origin=37742e09d62cc545369e77ee61d5ec04169a3466` 已构建并切为 immutable
> `current=37742e09d62cc545369e77ee61d5ec04169a3466`；回退 release
> `908092d47945948b473b958209acfd9c79bc9c80` 的 manifest 在精确清理其 manifest 外
> Python 缓存后重新验证通过。一次 service-identity 的通用 `tdx_daily` 采集对
> `trade_date=20260731` 得到 `returned=validated=committed=616`、一张 success receipt、
> 无错误码。UID987 经正式 18082 对同一分区连续完成两次完整分页：各为两页、616 行、616 个
> 非空唯一 `[trade_date, ts_code]`、terminal cursor，重放 identity digest 一致，且
> receipt、完整 lineage、`data_through` 与 `observed_at` 均存在。该已完成历史日分区在
> 周末读取时超过 86400 秒 freshness SLA，故 envelope 如实为
> `stale/degraded/quality invalid`，唯一原因 `freshness_sla_exceeded`；这不是采集、
> identity、receipt 或分页失败。18082 API 和既有 generic collector timer 均
> `active/enabled`。TradingAgent 只能将本事实用作历史/观察证据，不得当作实时或执行证据。

> **2026-08-01 Tradings 退役路径复核：** 旧 `/opt/investment/SharedSignals` 已从活跃路径
> 移至 root-only `/opt/investment/_archive/SharedSignals-retired-active-path-20260801/`，
> 8082 继续关闭且无 SharedSignals unit/process。95GB 历史数据与 Git/receipt 证据未销毁，
> 不得成为 TradingDatas fallback。MarketGraph API/cron 已单独暂停；18082、18083 与
> TradingDatas collector timers 保持运行，registry/catalog/query 合同未改变。
> 旧源码入口 `/opt/investment/SharedSignalsV1Source` 也已在零 systemd/process/cron 引用
> 后移入 root-only `/opt/investment/_archive/SharedSignalsV1Source-retired-20260801/`；新的
> `/opt/investment/TradingDatasSource` 为干净的 GitHub `main` 源码入口；本轮 code baseline
> 为 `5d054d09…`，后续状态文档提交不改变运行代码。
> 生产 `current=908092d…` 未随源码入口迁移切换。

## 当前运行面

- **8 月 2 日生产基线窄候选：** 为避免把最新 main 中尚未逐项正式验收的多批合同整体
  推入生产，已从正式 `908092d…` 基线构建独立候选
  `0ddfedb7167ec14819eb54a3c1e7eec43c4125fc`；其 runtime contract 与 registry
  的语义差异精确只有 `cn.dataset.shibor`、`cn.dataset.shibor_quote` 和
  `cn.dataset.tdx_daily`。两个 compiler 的仓外重建结果与 checked-in 产物逐字节一致，
  294 项 runtime/registry/observation/schedule 回归通过，Ruff check 与 diff-check 通过；
  当前 Ruff formatter 对三个既有文件仍会提出历史格式重排，本轮未夹带全文件机械重排。
  Tradings 上的 129 文件 immutable release/manifest 验证通过；使用独立 SQLite、现有
  generic batch collector 和临时 18084 完成真实 provider→receipt→catalog/query：
  三项分别为 `1/17/616` 行、身份全非空唯一、页数 `1/1/2`、terminal cursor、双跑 rows
  一致且 receipt/lineage 完整。因为读取发生在周末，`data_through=20260731` 已超过
  86400 秒 SLA，三项均诚实为 `stale/degraded`；所以没有切换正式 18082。临时 18084
  已停止、隔离 DB 已删除；root-only 非敏感证据保存在
  `/opt/investment/release-evidence/tradingdatas/20260802T0142-reference-contracts-0ddfedb…/`。
  正式 `current=908092d…`、18082 API、30 股 timer 均保持 active/enabled，候选分支
  `origin/agent/production-reference-contracts-v1` 仅供下一个有效分区的 fresh 验收。

- **8 月 2 日 `tdx_daily` 通用合同收口：** PR
  [#48](https://github.com/NicholasHan1226/TradingDatas/pull/48) 已普通合并，权威
  `main=e4589a3277d7d1c9128eb1454ec978e2324a1ad1`。变更只冻结 provider-native
  38 字段、`[trade_date, ts_code]` identity、`trade_date` 单分区完整性和
  `on_demand` cadence；没有新增 route、collector、table、timer 或交易语义。
  隔离的 20260731 generic collector 写入 616 行 success receipt；基于 production
  SQLite online backup 的候选 18085 由 UID987 双遍分页读回 `[500,116]`，616 个身份
  全部非空唯一、terminal cursor、rows digest 重放一致，receipt 存在且 lineage complete。
  当前是周末，86400 秒 SLA 将该旧分区诚实投影为 `stale/degraded/quality invalid`，因此
  合同虽已入 main，但 production `current` 不切换，不能称为 formal ready。候选 release
  `d832c3484cae5e2914924d3fab3d69ffb314277c` 的 132 文件 manifest、registry 物理重编译
  均已验证；候选 18085 已关闭。仓外证据位于
  `/opt/investment-data/tradingdatas/evidence/20260801T002149Z-tdx-daily-overlay/` 与
  `/opt/investment/release-evidence/tradingagent/20260801T003000Z-tdx-daily-candidate/`。
  同批 `stk_factor` 的 5528 行仅在窄字段探测成功，完整 35 字段请求失败，故保持
  NO-GO，未混入 PR #48。

- **8 月 1 日七项 completed-partition 通用 probe：** 使用服务器 service identity、
  concurrency=1、零重试、零 SQLite 写入，对 20260731 依次验证：`shibor=1`、
  `shibor_lpr=合法空`、`shibor_quote=17`、`stk_alert=合法空`、`stk_factor=5528`
  （窄字段）、`stk_high_shock=合法空`、`tdx_daily=616`（窄字段），均未命中响应上限。
  随后的完整字段审计只确认 `tdx_daily` 616 行覆盖全部 38 字段；`stk_factor` 因完整字段
  请求失败而拒绝升级。权威 evidence root 为
  `/opt/investment-data/tradingdatas/evidence/20260801T154829Z-completed-partition-probe/`；
  早期 `identity-audit.json` 曾把 `mappingproxy` 误当 `dict` 而产生假空值，已由使用
  `collections.abc.Mapping` 的 `identity-audit-v2.json` 明确取代，不得引用旧结论。

- **8 月 1 日周末利率数据隔离验收：** 使用服务器 `tradingdatas` 身份、干净源码
  `main=5d054d09…`、现有 generic batch collector 和独立 SQLite root，对最近完成分区
  `date=20260731` 采集 `cn.dataset.shibor` 与 `cn.dataset.shibor_quote`。首次分别写入
  `1/17` 行，主键 `[date]` 与 `[date, bank]` 均全量非空唯一；相同 batch 重放分别为
  `1/17 unchanged`，没有重复事实。以 UID987 和既有只读凭据通过临时 loopback
  `GET /v1/catalog` / `POST /v1/query` 双跑时，两项分别返回 `1/17` 行、terminal cursor、
  same-observation replay 一致、receipt 存在且 lineage complete。由于读取发生在周六，
  元数据按日级 SLA 如实为 `stale/degraded`，所以本轮只证明 provider→receipt→API 的
  通用链路和幂等性，不把它们升级为 formal ready，也不切 production。首次临时 API 的
  HTTP 503 已定位为隔离启动命令漏写 `read_model/` 的数据库路径，并非数据或合同失败；
  正确路径复验通过，临时 18085 已关闭。root-only 证据位于
  `/opt/investment/release-evidence/tradingdatas/20260801T152522Z-weekend-rate-5d054d0/`。
  正式 `current=908092d…`、18082 API、production SQLite 和通用 timer 全程未改变。

- **8 月 1 日隔离 probe 与周末运行快照：** 该轮 probe 开始时生产 `current` 为
  `d5b278…`（之后仅 catalog `identity_fields` 投影发布到 `908092d…`），formal
  catalog 为 `v1-a057e9b7b5f1456d`，18082 API active、通用 collector timer
  enabled/active；production registry 有 `101` 项 `active/active`、`69` 项
  `paused/active`、`14` 项 `paused/locked`、`5` 项 `paused/excluded` 和 `1` 项
  `paused/unknown`。以服务器 `tradingdatas` 服务身份、现役 immutable release 的同一通用
  HTTPS probe 对 `trade_date=20260801` 的 `dc_concept_cons` 与 `fund_daily` 分别得到
  provider `ok` 但 `valid_empty`（均 0 行）；二者仍不能证明非空 identity 或 response
  completeness，保持 paused/NO-GO，未写 SQLite receipt、未改 registry、API、timer 或
  current。`stk_nineturn` 已从该 YYYYMMDD 日频 wave 拆出；其权威请求值为
  `YYYY-MM-DD HH:MM:SS`，独立、正确格式 probe 同样为 provider `ok`/`valid_empty`，没有
  发出错误日期格式调用。三份无 payload evidence 的 SHA-256 分别为
  `71a0eaf…577de2`、`d46b42d…2edf3d` 和 `97e8b73…a36ff`。
- **分钟与跨市场读回口径：** 2026-08-01 是周六，当前 rt_min envelope 的
  `stale/degraded` 是读时钟对 300 秒 SLA 的诚实投影，不得写成当日采集故障或实时可用。
  最近交易日 2026-07-31 的 13:25、13:30、13:35、13:40 通过 UID987/formal 18082
  精确读回均为 30 行、30 个唯一 `ts_code` 和单一 bar time；13:20 有 100 行，不能代替
  冻结 30-symbol cohort。500 扩容仍 NO-GO。CNFutures 继续 NO-GO：`fut_basic` 当前
  stale/degraded，`ft_mins` 与 `rt_fut_min` 未形成可消费 formal dataset；Crypto 18083
  属于独立运行面，本轮没有触碰。

- **只读 onboarding 报告运行验收：** `main=93b8c23` 的报告代码已被构建为不切流的
  immutable report-only release（131 个受 manifest 约束文件）；它没有成为 `current`。
  报告运行时显式绑定正式 `d5b278…` 物理 registry 原始字节（SHA-256
  `20f278e4…a6e082c7`）与同一 formal catalog version `v1-a057e9b7b5f1456d`，而没有
  使用 93b 自带的较新 registry。以 `tradingagent` 身份串行抓取一次 catalog 和 99 个
  query envelope（91 个读侧拒绝如实保留为未绑定），随后以 `tradingdatas` 身份只读打开
  verified SQLite snapshot 生成 schema-v1 报告；没有 provider 调用、SQLite 写入、API/timer
  或 current 切换。报告的 readiness 计数为 `contract_missing=65`、`stale=63`、
  `observed_isolated_only=36`、`paused=21`、`locked=3`、`failed=2`，`formal_ready=0`、
  `legal_empty=0`。这说明当前 snapshot 没有满足 receipt/time/provider/API 逐项绑定的正式
  可消费项，不能将 HTTP 200 或 catalog 可见性误报为 ready。仓外、无 payload 的 report、
  snapshot、acceptance summary 和 SHA-256 清单已保存为 release evidence；production
  `d5b278…`、18082 API 与 30-symbol timer 均经 verifier/readback 保持不变。
- 机器可读 onboarding 状态报告已正常合入 main/origin（`ad9dd31`）。它只读取 verified SQLite
  snapshot、registry 和可选的脱敏 formal API snapshot，
  不调用 provider、不写 DB、不触碰 18082、timer 或分钟运行面。报告把 `formal_ready` 与
  `observed_isolated_only`、`legal_empty`、`stale`、`failed`、`paused`、`locked`、
  `contract_missing`、`seed_missing`、`unobserved` 明确区分；正式可用必须满足
  `api_version=v1`、当前 registry catalog version/SHA-256、envelope dataset 与
  `degraded=false`，且 receipt、data-through、observed-at、provider lineage 与 SQLite 权威投影
  精确一致。独立 review P0/P1=0，11 项回归、Ruff 与 diff-check 通过。当前本机没有可绑定的
  production SQLite snapshot，因此未生成或伪造运行报告；服务器只读生成和 formal snapshot
  readback 是下一项运行验收，不构成部署动作。
- `cb_daily`、`dc_daily`、`dc_index`、`ft_limit`、`repo_daily`、`sge_daily` 与
  `tdx_index` 的七项同形单日分区合同已正常合入 main/origin（`753587a`）。变更严格限于
  六个 registry/config 及其生成物：不新增 route、collector、table、timer 或交易语义。
  隔离的 `trade_date=20260731` 真实 QuickSync 预检分别得到
  `308/1031/496/868/45/41/612` 行 success receipt；`[trade_date, ts_code]` 均非空、唯一且
  未达到 10,000 行上限，`dc_index` 固定 `idx_type=行业板块`。独立 clean-overlay review
  P0/P1=0，249 项编译、registry、request-observation、schedule 与 QuickSync 回归通过。
  这仍只是候选/隔离证明：七项保持 `on_demand`，尚未切换 formal 18082/current；必须等待下一个
  可用分区的正式 success receipt 和认证 API fresh readback，不能把 20260731 的旧分区写成
  内部生产可消费数据。
- `bak_basic`、`limit_list_d`、`ci_daily` 与 `ths_daily` 的四项同类单日分区合同已正常
  合入 main（PR #43，`ecf336b`）。修正后的候选只含 registry/config 及其生成物，不新增
  route、collector、table、timer 或交易语义。真实 QuickSync 隔离采集对
  `trade_date=20260731` 分别完成 `5543/206/444/1880 inserted`，同窗口重放分别为
  `5543/206/444/1880 unchanged`；认证候选 18091 query 的终止分页、首分页重放以及
  receipt/lineage 都已验证。`limit_list_d.last_time` 的 107/206 合法空值现明确为非主键可空，
  `[trade_date, ts_code]` 仍全量非空唯一。独立 clean-overlay review P0/P1=0，131 项
  compiler/registry/observations 回归通过。该固定 20260731 分区已超过 86400 秒 SLA，
  所有候选 envelope 因而如实为 `stale/degraded`；候选 18091 已停止，尚未切换 formal 18082。
  下一可用交易日的新分区 receipt 与正式 18082 fresh readback 才是部署门槛。
- `limit_cpt_list`、`limit_step` 与 `sz_daily_info` 的同类、单日分区合同已正常合入
  main（`0d2b2ea`）：三项均复用既有 generic registry/transport/SQLite receipt/catalog-query
  路径，不新增 route、collector、table、timer 或交易语义。隔离 immutable candidate
  `f6f92ea90e54bac8ab20a74552c7c387f8c6fc10` 已经真实 QuickSync 验证：首次分别
  `20/10/14 inserted`，同窗口重放分别 `20/10/14 unchanged`；以
  `tradingagent` 身份的候选 18091 query 行数、终止 cursor、receipt/lineage 与规范化重放
  均通过，独立 review P0/P1=0。查询时 `20260731` 已超过 86400 秒 SLA，三项如实投影为
  `stale/degraded`，所以尚未切换 formal 18082；下一个可用日分区的 production receipt
  和 fresh readback 才是部署门槛。候选 18091 已停止，正式 18082 与 30-symbol timer
  本轮未改动。
- 正式 A 股 API：`tradingdatas-v1-internal.service` 为 active，固定只读接口仍是
  `GET /v1/catalog` 与 `POST /v1/query`（loopback `18082`）。
- 正式 immutable `current`：`908092d47945948b473b958209acfd9c79bc9c80`；18082 API
  active，通用 provider-native timer 为 `enabled/active`。908 相对直接回退点
  `d5b2788208d55e9f7052783caf8447233cf01dfa` 只新增 catalog `identity_fields` 的通用
  registry primary-key 投影，未改 registry、provider、SQLite、timer、公共 route 或
  TradingAgent；二者均由 trusted manifest verifier 验证。`moneyflow` 的日分区、
  `[trade_date, ts_code]` identity、`postclose_daily` 与单分区完整性合同来自 d5 基线，
  不是 908 新增的数据合同。更早的回退链仍保留：
  `04fcf3a6af8cfe1c18b0420af11f4ccec6b21a86`、
  `cb89620b7e20356a00c7ff3f06c357b401565113`、
  `0935b70aafca4f3bd269381aa2ee6bba8ac73f61`、`1f17708730172bc31fba3f849fa938da6e8a73fa`
  与经过验证的
  `5ac3925c3931a81132ea02abb16f9745033fb6dc` 继续保留为分钟运行面的后续 rollback
  链；`71b7890928a9cc8c6345f41b0cd87a60f46158f8` 仍只作为已验证的 500-symbol 候选，
  不挂载到正式 18082。
  13:05/13:10 的 500 live 门禁失败后，发布侧按停止线先停 API/timer、以 trusted manifest
  原子回切 5ac、再恢复 API/timer；切换没有写入、覆盖或补造任何 SQLite facts/receipts。
- 71b 的事件/公告合同与严格 provider-local minute timestamp 投影仍保留在 immutable
  release 中。此前以 `tradingagent` 身份对候选 18082 的 `cn.dataset.anns_d` 带 `as_of`
  分页 readback 通过；该候选证据不等于当前 5ac 正式可用性，也不增加任何新闻分析或交易逻辑。
- 切换前后均以 trusted manifest verifier 验证 current/release。以 `tradingagent` 身份的正式
  18082 catalog readback 为 HTTP 200；闭市 planner 在 `tradingdatas` 身份下对
  `cn.dataset.rt_min` 返回 `not_due`，因此未在闭市窗口伪采分钟 bar。
- **500-symbol live 门禁失败：** 正式 18082 以 `tradingagent` 身份对
  `time=2026-07-31 13:05:00` 与 `13:10:00` 的精确 query 均返回 0 行；两者均投影为
  `failed/degraded/quality=degraded`，原因 `validation_failed`，且指向完整 lineage 的 failed
  receipt `receipt:b0810c7b7667e6fedc5208f7ebc41a23bba9155c7bd6b38bacfc1b52cd4238ac`。
  因而未达到 500 unique、单一 time、5 个 success shard receipt、分页终止/重放与
  `ready/fresh/valid` 条件；没有尝试第三轮，也没有把旧 30 或旧 bar 伪装为通过。当前保持
  5ac/30 production，500 仅作为隔离候选，真实交易继续关闭。
- `stock_st` production readback：正式 generic one-shot 对 `trade_date=20260731`
  返回 208 行并留下 success receipt；随后以 `tradingagent` 身份通过 formal 18082
  分页读取为 208 行、208 个 `[trade_date, ts_code]` 唯一 identity、3 页且 terminal cursor
  为 null，receipt/lineage 完整。该分区的 `data_through=2026-07-31` 已跨读取时钟的
  86400 秒 SLA，envelope 因而如实为 `stale/degraded`；它证明稳定按需入库/API 合同，
  不把昨日 ST 标记数据伪装为当前新鲜或可交易事实。
- `moneyflow_ths` production readback：正式 generic one-shot 对 `trade_date=20260731`
  返回 5,199 行并留下 success receipt；随后以 `tradingagent` 身份通过 formal 18082
  分页读取为 5,199 行、5,199 个 `[trade_date, ts_code]` 非空唯一 identity、11 页且 terminal
  cursor 为 null。相同请求第二次读取的行数、identity digest 与 cursor 语义一致；metadata
  为 `ready/success/fresh/valid/non-degraded`，receipt
  `receipt:73b27d0be181cb17f75fc4aa7cf03629c0d6e9e55ce189884d0c88f573539af9` 与 lineage
  完整。这证明该日分区可经内部 API 稳定按日读取；不代表策略、交易或其他未验收数据集已可用。
- `moneyflow` production readback：在候选真实 receipt 与第二次 unchanged 重放均通过独立
  review 后，正式 generic one-shot 对 `trade_date=20260731` 返回 5,197 行。以
  `tradingagent` 身份通过 formal 18082 分页读取为 5,197 行、5,197 个 `[trade_date, ts_code]`
  非空唯一 identity、11 页且 terminal cursor 为 null；相同请求第二次读取的行数、identity
  digest 与 cursor 语义一致。metadata 为 `ready/success/fresh/valid/non-degraded`，receipt
  `receipt:09823b511506ab7295233384eba702c692c0a75a6a2027add1f3b77aa9043987` 与 lineage
  完整。该项是客观的日级资金流数据事实，不是交易信号或执行 authority。
- `moneyflow_cnt_ths` 已正常合入 main（`bdd9bf6`），但尚未部署到正式 current：隔离 candidate
  对 `trade_date=20260731` 的通用采集为 386 行 inserted，第二次为 386 行 unchanged；
  `[trade_date, ts_code]` 均非空且唯一、未触顶，candidate loopback 分页为 `100/100/100/86`、
  terminal cursor 与 lineage 完整。独立 review 为 P0/P1/P2=0，且 activation-wave 的 registry
  hash 已同步。由于此时已跨 86400 秒 SLA，candidate envelope 如实为 `stale/degraded`；因此
  未切换正式 current，也不把该 yesterday partition 写成 fresh production 通过。下一可用日分区
  的 receipt 与正式 18082 readback 是该项部署门槛。
- `moneyflow_hsgt` 已正常合入 main（`8f29bdc`）：候选用冻结 release 对 `trade_date=20260731`
  留下 1 行 inserted、随后 1 行 unchanged 的两个 success receipt，`[trade_date]` 非空唯一，
  loopback query 的 terminal cursor、payload replay 与 lineage 均完整。独立 review 为 P0/P1/P2=0，
  但该分区已经跨 SLA，metadata 如实为 `stale/degraded`；它尚未部署到正式 current。必须由下一个
  可用日分区的 production receipt 与 formal 18082 fresh readback 才能进入内部可消费集合。
- `daily_info` 已正常合入 main（`15f4871`）：隔离 immutable candidate 的两次通用采集对
  `trade_date=20260731` 依次得到 11 条 inserted、11 条 unchanged；`[trade_date, ts_code]`
  全部非空且唯一，认证 loopback query 为 schema 1、11 行、终止 cursor、重放一致且
  receipt/lineage 完整。独立 review 为 P0/P1/P2=0。该分区已跨 86400 秒 SLA，envelope
  因而诚实为 `stale/degraded`；尚未切入正式 current。下一可用日分区的正式 receipt 与
  18082 fresh readback 是部署门槛，不能用这一昨日证据宣称内部生产可消费。
- `index_dailybasic` 已正常合入 main（`da55d55`）：隔离 immutable candidate 的两次通用采集对
  `trade_date=20260731` 依次得到 12 条 inserted、12 条 unchanged；`[trade_date, ts_code]`
  全部非空且唯一，认证 loopback query 为 schema 1、12 行、终止 cursor、重放一致且
  receipt/lineage 完整。独立 review 为 P0/P1/P2=0。该日分区也已跨 86400 秒 SLA，故尚未
  切换正式 current；只有下一个可用日分区的 production receipt 与 formal 18082 fresh readback
  能把它加入内部可消费集合。
- 对失败 receipt `b0810c7b...` 的 16:01 CST 只读审计进一步确认：同一 13:20
  attempt 的 5 个非空 100-symbol 分片均为 `returned=validated=committed=0`、
  `terminal_no_data_transaction`、`validation_failed`，没有部分 500 facts 写入。因此该次
  NO-GO 的唯一根因是当时 QuickSync/Tushare 没有返回任何分钟行，不是分页、SQLite 投影或
  分片原子性故障。隔离 DB 在 15:08 以同一通用 5×100 runner 对 15:00 bar 取得 5 个 success
  receipt、500 个唯一 symbol、同一 provider time；临时 loopback catalog/query 可分页终止并
  重放一致。16:00 读取时该 bar 已按 300 秒 SLA 诚实为 stale，且没有在同一 clean isolate
  中取得第二根相邻的 fresh bar，故不能以此替代下一交易时段的双轮 live 门禁，也不得据此切换
  正式 current。
- 回滚后的自然 30-symbol 链路已恢复：正式 18082、`tradingagent` 身份对 `13:25`、`13:30`、
  `13:35`、`13:40` 的精确 query 均为 30 行/30 个唯一 symbol、单一 time、
  `ready/success/fresh/valid/non-degraded` 且 receipt/lineage 完整；本页复核的 `13:45`
  也满足同一合同。`13:20` 的多于 30 行结果不作为恢复起点。该证据仅恢复既有 30-symbol
  数据链，不重启 500，也不赋予真实交易 authority。
- 13:05 CST 的 a42 首轮 live 验证未通过：collector 日志显示 `rt_min` success，但正式
  18082 精确查询 `time=2026-07-30 13:00:00` 返回 0 行，不能将旧 11:30 数据伪装为
  最新 500 分钟 bar。按 fail-closed 停止线，已先停 API/timer、用已验证 manifest 原子回切
  `5ac3925`，再恢复 API/timer；SQLite facts 和 receipts 均未覆盖或删除。
- 回滚后以 `tradingagent` 身份对正式 18082 查询
  `cn.dataset.rt_min(time=2026-07-30 11:30:00)` 得到 30 个唯一 symbol、单一 time，
  但 metadata 诚实为 `stale/degraded`；这仅证明回滚可读，**不**证明实时分钟链已恢复。
- 13:16 CST 的后续 UID987 受控 readback 已确认回滚后的 30 只链路重新出现两根相邻
  completed bar：`13:05` 与 `13:10` 各 30 个唯一 symbol。正式 envelope 为
  `ready/success/fresh/valid/non-degraded`，receipt 存在且 lineage 完整；这是 30 只回滚链
  恢复的证据，不解除 500 候选的 NO-GO。
- 15:05 和 15:10 的 `rt_min` 上游调用各留下一个 `provider_error` 的 failed receipt（均为
  0 行）；没有手工重试、插库或删除失败证据。现有通用 session-minute timer 在下一合资格
  15:20 轮自然恢复，取得实际 `time=2026-07-30 15:00:00` 的 30 个唯一 symbol；15:25 轮
  同样成功。以 `tradingagent` 身份对正式 18082 精确查询该 time 为
  `ready/success/fresh/valid/non-degraded`，receipt 与 lineage 完整。这只证明最终 bar 的
  合法恢复，不填补 15:05/15:10 的失败尝试，也不解除 500 的 NO-GO。
- 2026-07-31 09:35 的 500 live 门禁失败后，TA 已停止并禁用 scale500 session/paper
  timers，恢复旧 30 session/paper timers；两个状态根均保留且
  `REAL_TRADING_ENABLED=false`。回切后正式 18082 精确查询 `09:35` 得到 30 个唯一
  symbol、单一 time，metadata 为 `ready/success/fresh/valid/non-degraded`，receipt 与
  lineage 完整。`09:30` 分区仍可见此前 500 候选写入的事实，因此读取方必须继续使用冻结
  Universe，不能把全分区行数当作当前 30-symbol cohort 完整性证明。
- 后续正式读回确认 `09:35`、`09:40`、`09:45` 三根相邻 completed bar 各为 30 个唯一
  symbol、无游标且 metadata/receipt/lineage 全部通过。TA 于 09:57 重新初始化冻结的 30-symbol
  日内状态，并于 09:58 通过显式 incident-recovery late-start 消费 `09:45` 一根：30 行、
  资金/执行 authority 均为 false、无候选、无持仓、四个影子袖套对账通过。被跳过的 `09:35`
  与 `09:40` 被记录为 gap，因此当天 `full_session_complete=false`、
  `learning_eligible=false`，没有伪造历史 PIT 或补做交易。
- `REAL_TRADING_ENABLED=false`。TradingDatas 不管理策略、资金、订单、broker 或交易。

## 已验证的内部数据事实

- 2026-07-29 23:04 CST 的正式 18082、以 `tradingagent` 身份 readback 得到
  `catalog_version=v1-1e4560099e58a89e`。catalog 的数量只表示合同与可发现性；消费者必须
  每次根据 query envelope 的 `state`、`degraded`、`freshness`、`quality`、receipt 与 lineage
  决定是否消费。
- 同次 readback 已验证：
  `cn.market.trade_calendar(SSE, 20260730)`、`cn.equity.daily(20260729)`、
  `cn.dataset.stk_limit(20260729)`、`cn.dataset.adj_factor(20260729)` 当时均为
  `ready/success/fresh/valid/non-degraded`，且 receipt/lineage 完整。
- `cn.dataset.suspend_d(20260729)` 的较早 `provider_error` 已由本页所述 23:24 CST
  的成功 receipt 覆盖；当前读取状态以最新可信 receipt 为准，不能把较早错误或空行混作
  当前结果。

## 夜间预采集快照

- 2026-07-29 23:24–23:25 CST 通过正式、受控的 provider-native oneshot（timer 仍关闭）
  串行完成了当前已到窗口的六项通用 registry 采集。它没有增加 route、专用 collector、
  交易语义或新的自动调度。
- `cn.dataset.broker_recommend`、`cn.dataset.limit_list_ths`、
  `cn.dataset.moneyflow_ths`、`cn.dataset.stk_holdernumber` 已取得 success receipt，
  `cn.dataset.fund_portfolio` 取得合法 empty receipt；五项均可从正式 18082 查询到数据或
  空结果，且 lineage 完整，但由于当前 registry 尚未声明 response completeness 和可信业务
  watermark，API 如实返回 `state=partial`、`degraded=true`，不能被消费者作为新鲜完整事实。
- `cn.dataset.suspend_d(20260729)` 已通过同一正式 18082 以 TradingAgent 只读身份回读：
  `state=ready`、`runtime_state=success`、`freshness=fresh`、`quality=valid`、
  `degraded=false`，receipt 与 lineage 均完整。
- 此轮证明的是“通用入库与内部 API 读回”而非六项都已稳定自动化。明早仍只按既有门禁复核
  30 只分钟链路；其余数据集需要先补齐 registry 的完整性/水位合同，才可能从 partial 晋级为
  可消费的 ready。

## 明日批量准备

- 对 2026-07-30 16:35 CST 的 registry-driven 计划进行了只读模拟：24 项会被选中，
  `failed=0`。其中包括日线、复权因子、涨跌停、融资融券、申万日线、北向与资金流；
  68 项按需数据和 89 项 paused 数据继续被排除。这是明日盘后受控 one-shot 的准备证据，
  不是预先启用 timer 或宣称 24 项已经采集成功。
- 当前 5 项 partial 的合同不会被凭空改为 ready。只有补齐各自的 primary identity、请求窗口
  完整性和业务 watermark 后，才允许以新合同重新采集、receipt 验证和正式 API 读回。

## 新闻、公告与互动数据（历史生产证据已保留，当前未挂载）

- 主线与 immutable release `56ab09aaa758943485890717fa2b5e29254d281a`
  已冻结五项事件证据数据的通用 registry
  合同：`cn.dataset.anns_d`、`cn.dataset.cctv_news`、`cn.dataset.irm_qa_sh`、
  `cn.dataset.irm_qa_sz` 与 `cn.dataset.research_report`。它们复用既有 QuickSync
  transport、SQLite receipt、catalog/query 数据面与通用 `event` cadence；现有通用
  scheduler 约每 15 分钟检查一次，日期分区的 freshness SLA 为 86400 秒。没有新增公共
  route、专用 collector、业务表或新闻专用 timer。该 release 当前不再是正式 `current`；
  下列 readback 是回滚前保留的真实生产证据，不是当前 18082 可用性声明。
- 隔离 SQLite 的 `20260730` provider 采集成功且身份数与行数一致：公告 1119、央视新闻
  11、上证互动 282、深证互动 2、研报 13。相同窗口第二次真实上游重放均为 `unchanged`
  success receipt；公告历史窗口经有界 `as_of` 分页为 3 页、1119 个唯一身份，首分页重放一致。
- `20260731` 首次受控日期窗口检查返回五个合法 empty receipt；候选 API 以 TradingAgent 只读身份
  返回 `empty/valid/non-degraded` 与完整 receipt/lineage，未把空结果伪装为成功数据。
  昨日分区在当前读取时钟下按 86400 秒 SLA 诚实为 stale；历史重放必须带明确 `as_of`，不能将
  昨日数据称为当前新鲜事实。
- 早期按需候选的 immutable manifest SHA-256 为
  `08ddf79a5f338e171a9f806c9f6836a942d9162427092f035010609a96592450`，其编译/registry/
  schedule 回归分别为 37/37、48/48、95/95 通过。最终 event cadence 版本另有 134 项
  compiler/scheduler 回归、生成文件逐字节相等和 activation hash 校验；production
  catalog_version=`v1-1a25a650e12bdc4d`。2026-07-31 02:15 CST 首个自动周期
  `Result=success`，五项 formal 18082 readback 均为合法
  `empty/valid/non-degraded`，receipt 与 lineage 完整；这表示当天当时上游无返回行，
  不是已有新闻内容或交易信号。`major_news`/`news` 仍维持 paused/404，不伪装为已接入。
- 2026-07-31 早盘的后续自动采集已取得真实公告内容：正式 18082 对
  `cn.dataset.anns_d(ann_date=20260731)` 有界分页返回 1209 行、1209 个唯一身份，metadata
  为 `ready/success/fresh/valid/non-degraded`，receipt/lineage 完整，首分页再次读回一致。
  同期 `cctv_news`、`irm_qa_sh`、`irm_qa_sz`、`research_report` 均为合法
  `empty/valid/non-degraded`，只表示当前 provider 返回 0 行，不表示接口失效。
- 10:12–10:18 CST 使用 server immutable `7de9ed58` 在临时 loopback `18086` 完成一次
  只读候选 parity 后立即停止，端口已关闭，正式 18082/current/timer 未变。候选 catalog
  `v1-54838b10dd9c696d` 下，`anns_d(20260731)` 为
  `ready/success/fresh/valid/non-degraded`；`cctv_news`、两项 `irm_qa` 与
  `research_report` 均为带完整 receipt/lineage 的合法 empty。该 parity 只证明发布代码可按
  现有 SQLite 事实投影，不构成正式 current 或持久候选服务。

## 第二批非开盘接口（已合入并正式挂载）

- 2026-07-31 17:xx CST 已在闭市受控窗口把本批的 main `1f17708` 挂载到正式 18082，随后
  用 `0935b70` 修复唯一 P1：通用 query 层此前把 registry 声明为 `yyyymm` 的月分区错误按
  `yyyymmdd` 校验。修复只涉及 `query_service.py` 与回归测试；PR #26 已普通合入、目标 release
  已由 manifest verifier 验证。正式 readback（`tradingagent` 身份）结果是：
  `disclosure_date(20260731)` 为 2 行、`ready/success/fresh/valid/non-degraded`；
  `share_float(20260731)` 为 44 行且同状态；`top_list(20260730)` 为 113 行、receipt/lineage
  完整但因日分区已超过 SLA 诚实为 `stale/degraded`；`broker_recommend(202607)` 的上游当前
  返回 0 行并留下 failed validation receipt，带 `month` 的正式 query 已不再 HTTP 400，而是
  因没有可用 success receipt 诚实 503 fail-closed。没有伪造月度 data_through、没有手工 SQLite，
  也没有把 broker_recommend 标为可消费。

- 同一切换后的只读候选审计不新增采集或配置：`report_rc` 当前窗口是合法 empty，历史行中
  `quarter` 有 11 个空值，不能作为稳定修订身份；`repurchase` 最近成功 receipt 的 49 行均缺
  `end_date`/`exp_date`，不能用伪主键；`top_inst` 最近成功 receipt 的 909 行按
  `[trade_date,ts_code,exalter,side,reason]` 仍有 132 个重复 excess。三项均维持 NO-GO。
  `stk_managers` 的最近 4 行样本暂时唯一且非空，但样本量不足，只可进入后续隔离真实 receipt
  评估，不进入本次 production。事件侧 `anns_d` 的有界 as-of query 为 ready；
  `research_report` 虽有行和 lineage，但 response completeness 未冻结，仍 degraded；
  `cctv_news` 与两项 `irm_qa` 的 as-of query 没有匹配 success receipt 而诚实 503，
  `major_news`/`news` 继续 paused。没有为任何一项新增 route、专用 collector 或数据表。

- `stk_managers` 的下一独立隔离 slice 已在独立 SQLite 中通过同一 generic collector 对
  `ann_date=20260728` 与 `20260731` 得到两个真实 success receipt（分别 57 与 8 行）。候选
  业务身份 `[ann_date,ts_code,name,title,begin_date]` 在 20260731 的 8 行样本中非空且唯一，
  但 20260728 的 57 行有 11 个 `begin_date` 空值，并存在一组重复；重复行只在可空 `lev`
  字段不同。因而没有可证明的非空稳定业务主键，不能以 payload hash、可空字段拼接或丢弃字段
  伪造身份。此项为 P1/NO-GO：不生成 registry/config 候选、不建 PR、不发布，隔离 DB/receipt
  仅保留审计证据，正式 18082 与 30-symbol 分钟链未受影响。

- 随后的只读排序只选择了一个下一候选：`cn.dataset.fund_share`。隔离 SQLite 对
  `trade_date=20260728` 的真实 provider 调用得到 1,703 行，
  `[trade_date,ts_code]` 为 1,703/1,703 非空唯一、未触顶，重放为 1,703 `unchanged` 行。
  该证据已用于冻结纯 registry/config 合同：schema `2.0.0`、日分区、
  `[trade_date,ts_code]` 主键、默认排序和
  `single_partition_unique_primary_key` response completeness；cadence 仍为 `on_demand`，
  没有新增 collector、route、timer 或业务表。PR #27 已普通合并为 `cb89620`，target release
  manifest、离线 registry 重编译、clean-overlay P0/P1 审查和 13 项 compiler/query/scheduler/
  receipt 回归均通过。
- 2026-07-31 23:14 CST 的正式单项 generic one-shot（`tradingdatas` 身份）对
  `trade_date=20260731` plan 与 execute 均成功。随后以 `tradingagent` 身份从 formal 18082
  分页 readback：791 行、791 个非空唯一身份、两页终止；metadata 为
  `ready/success/fresh/valid/non-degraded`，receipt
  `receipt:14d8e037c2798d02cdb7b193fb7dede3cdd290a05e0caedcd2c5bcceeee95db0` 与 lineage
  完整。第二次相同查询的行数、身份 digest 和 receipt 完全一致。该项现在是可按需内部读取的
  数据事实，不代表自动调度、研究结论或交易 authority。
- `fund_share` 闭环后的下一独立候选是 `cn.dataset.limit_list_ths`。候选
  `9a45f577c650946348b46a17865eb53f9087da91` 已经 PR #28 普通合并为
  `6299d6239c717f579e734a86e94fa1505ecac6ec`，只冻结真实返回的 18 个字段、
  `schema_major=2`、日分区 `[trade_date,ts_code]` 身份和既有通用
  `single_partition_unique_primary_key` 合同；上游这次未返回的 6 个文档可选字段不再被伪装为
  已有字段，原始 provider payload 仍无损保存。候选没有增加 Python、route、collector、timer
  或表。
- 2026-07-31 23:45 CST 在独立 release/SQLite 中以 `tradingdatas` 身份两次真实采集
  `trade_date=20260731`：第一次 100/100 写入，第二次 100/100 unchanged，两个 receipt 的
  payload 指纹一致。随后临时 loopback（18084，已停止）以 `tradingagent` 身份按固定
  catalog/query 合同读取到两页 100/100 非空唯一身份、终页 cursor 和重放一致；metadata 为
  `ready/success/fresh/valid/non-degraded`，receipt/lineage 完整。随后受控原子切换正式 current，
  以 `tradingdatas` 身份对同一日期完成 plan+execute，并以 `tradingagent` 身份从 formal 18082
  得到两页 100/100、终页 cursor、重放一致与
  `ready/success/fresh/valid/non-degraded`；正式 receipt 为
  `receipt:85ed2ad22d0f1882bd0889039b90a3723f76c84b016c26eac173f20c42244785`，lineage 完整。
  该数据集现在可按日分区从内部 API 只读消费，不代表自动交易或策略 authority。
- `cn.dataset.fund_div` 以 PR #31 普通合并为
  `013623aed01cc2b6400f6ce1341d64b39db09bf0`，仅新增通用 registry/config 与回归：
  schema `2.0.0`、`ann_date` 单日窗口、
  `[ts_code,ann_date,imp_anndate,base_date,div_proc]` identity 和
  `single_partition_unique_primary_key` 完整性合同。独立 clean-overlay 审查为 P0/P1/P2=0；
  不新增 Python、route、collector、timer 或业务表。受控发布后，正式 18082 以
  `tradingagent` 身份对 `ann_date=20260801` 返回合法
  `empty/valid/non-degraded`（receipt
  `receipt:76915b398ca1278be35652f228b3dd6901f0f08c1ffdf08811b55c3f29b345c6`，lineage 完整）。
  这是上游当前窗口无记录的真实状态，不伪装为有内容或自动调度；当有真实公告日数据时，再以同一
  on-demand 合同做有界 readback。
- `stk_holdernumber` 有一条业务身份重复，继续 NO-GO；此前的 `report_rc`、`repurchase`、
  `top_inst`、`stk_managers` 结论不变。此前 `moneyflow_ths` 的历史 receipt 审计包含一个
  14,593 行、30,150 duplicate-excess 的不合格窗口；它没有被删除或覆盖。后续隔离真实采集
  使用冻结的单日窗口得到 5,199/5,199 非空唯一事实后，才以新的完整 success receipt 进入本次
  production readback。此候选与筛选没有触及分钟 timer。

- 生产 receipt 审计表明，`cn.dataset.disclosure_date` 的三个真实分区均可使用
  `[ann_date,end_date,ts_code]` 作为分区内非空唯一身份。main/GitHub 的
  `7ee1396a5bf84ae6f393605450fbd193cc8093ea` 已通过 registry/config
  将它冻结为 `on_demand`、`ann_date` 单日分区和
  `single_partition_unique_primary_key` 完整性合同；QuickSync 未返回的 `modify_date`
  继续由既有响应观测显式移除。相同 SHA 的 immutable server release 已预构建并通过
  manifest/registry 字节一致性验证，但正式 current 已因分钟 live 门禁回到 `5ac3925`；
  本项尚未在正式 18082 重新采集和读回，不能提前称为 ready。
- `broker_recommend` 的月份字段是 `YYYYMM`，当前通用日分区 watermark 不能科学投影月度
  完整性；`report_rc` 与 `repurchase` 的可区分修订字段存在空值；`stk_surv` 尚无真实行级
  样本。因此四项继续保持 partial/stale 或 empty 的现状，不通过新增专用代码、伪主键或
  人工插库强行升级。
- 本次扩展继续选择可由现有通用 `yyyymmdd` 分区合同表达、且生产 SQLite 已有真实
  行级样本的接口：`share_float` 的 65 行在两个公告日分区内以
  `[ann_date,float_date,ts_code,holder_name,share_type]` 全部非空且唯一；
  `top_list` 的 164 行在两个交易日分区内以 `[trade_date,ts_code,reason]` 全部非空且唯一。
  两项只增加 reviewed registry/completeness 合同，不增加 Python、route、collector 或
  timer；在新的 immutable release、真实 receipt 和 formal 18082 readback 完成前仍不是当前
  可消费数据。`block_trade` 虽当前 131 行可区分，但上游没有稳定业务流水号，重复成交碰撞
  仍可能发生，未纳入本批。
- 同一 10:12–10:18 候选 parity 对 `disclosure_date`、`share_float` 与 `top_list`
  均得到 `unobserved/degraded/no_recognized_receipt`，与“新合同尚未形成新 authority
  receipt”的停止线一致；没有复用旧合同 receipt、人工插库或把已有 rows 升级为 ready。

## 500 只分钟数据候选（已回滚，live 验证失败）

- 2026-07-30 主线已普通合入 500 分片合同，并补齐已审的次日交易日历、开市分钟窗口与
  session-minute 优先级。候选 immutable release 为
  `a42e66277aa7bbfa284fb7afdef980a4ba95386d`；午间虽完成原子切换，但首轮 live
  500/500 证明失败，现已安全回滚到 `5ac3925`。该候选在重新取得两根相邻 live 500/500
  receipt/API readback 前不得再次切入 production。

- 原始候选 commit：`4329307352d9138186cd2e3fca994ca5cdc96083`；审计分支：
  `codex/rtmin-500-atomic-v3`。其 4 份配置改动已正常合入 main 的
  `3b4ecc35531091d6356604f8bf156acffa28b2b8`。该记录是早期候选的审计来源；当前
  production 指针、timer 状态和可用性以上文 13:08 CST readback 为准。
- 只修改同一通用数据面需要的 4 份 registry/contract/hash 配置：
  `cn.dataset.rt_min` 使用 `entity_fanout`、5 片 × 100、`identity=[ts_code,time]`，并要求
  每轮同一 bar_end 的 500 个唯一身份齐全；没有新增 route、专用 collector、TA 改动或交易语义。
- 隔离候选对 2026-07-29 15:00 的真实 QuickSync 压测已得到 500/500、5 个成功 receipt、
  3.117 秒总耗时；候选 query 以 `time eq`、`limit=100` 得到 5 页、终止 cursor，重放的
  data/cursor/metadata 一致。候选证据：
  `/opt/investment-data/tradingdatas/candidate-evidence/rtmin500-4329307352d9138186cd2e3fca994ca5cdc96083/rtmin500-history-1500-evidence.json`
  （SHA-256 `21b66b0d7e7dcfe7137e19865c856ff44d4877b997909288d0980b46d7a90be8`）。
- 该候选的 fresh clean-overlay 关键门禁为 7/7 PASS；合入后同一关键回归为 10/10 PASS。
  它仍不能替代下一交易时段的真实证明：先确认现役 30/30 第一根，再要求预构建 release
  连续两根相邻 live bar 均为 500/500、5/5 分片、同一 bar_end、总耗时小于 300 秒。任一
  失败则保持 30 只 production rollback，不切换。
- 13:00 生产失败的隔离根因已复现：五个 100-symbol 上游分片实际合计只有 498 个唯一
  symbol（缺 `002294.SZ`、`000333.SZ`），且全部是旧的 11:30 bar；因此正式查询 13:00
  返回 0 行是正确的，不是 API 投影故障。编译器曾静默丢失 registry 声明的
  `fanout_field=ts_code`，并把采集开始时间当作 snapshot `data_through`，使缺码旧 bar
  错记为 success/fresh。
- 该问题最初在隔离候选 `8d18b5cffa06fd7af979d1962cb7b94c01f61794` 中修正：保留
  `fanout_field` 并要求每个请求值恰好一次，同时以 provider 的真实 bar time
  生成 snapshot watermark。候选在独立 SQLite 上完成一次收盘后 5×100 的 500/500 同一 15:00
  bar、5 个 success receipt、8.5 秒采集；候选 API 对已过 SLA 的历史 bar 诚实返回 stale，
  没有宣称 live-ready。仍欠下一交易时段两根相邻的真实 500/500 证明，之前禁止再切换生产。
- 该通用修正已在主线普通合入为 `ad4bc00`，并作为上述盘后 production release 切换；这只是
  代码/配置发布，不等于 500 分钟数据已经被 live 证明。明早首两根已完成 bar 必须各自满足
  500 个唯一 symbol、同一实际 provider time、5/5 分片 success receipt、完整 lineage、
  `ready/success/fresh/valid/non-degraded` 的正式 18082 envelope 与一致重放。任一轮失败即
  受控回切 `5ac3925`，保留失败 receipt，不手工补库。

## 旧系统退役与保留

- SharedSignals 运行态已退役并 permanent-mask：7 个历史 service/timer 均为
  `inactive/masked`；旧 `8082` 无监听；root 的 5 条和 `marketgraph` 的 22 条活动旧 cron
  已移除。原 unit 文件已复制并移入受限退役证据目录，回滚需先显式 `unmask` 后恢复该副本。
  退役证据：
  `/opt/investment/release-evidence/tradingdatas/20260729T124623Z-sharedsignals-runtime-retirement/unit-mask-20260729T211900Z`
  （`SHA256SUMS` 摘要：`832b938f21638deea95dd16ed565684dfbe9b72642090cdf1f74d4d2e28a9629`）。
- 2026-07-29 已按逐目录审计和明确授权退役本地 SharedSignals 源码：16 个历史 worktree、
  26 个本地候选分支及其旧 Python 环境、缓存和源码残留均已移除，且没有候选需要合并进
  TradingDatas。旧仓仅保留本地 Git 历史、`RETIRED.md`、`data/`、`logs/` 和
  `.codegraphcontext/`；SQLite、receipt、evidence 和 rollback 材料不在删除范围。
- 旧 SharedSignals 仓原先错误指向 TradingDatas GitHub remote 的 `origin` 已移除，防止它再向
  活跃 TradingDatas 主线推送。该退役提交只留在旧仓本地历史；TradingDatas main/origin 不受影响。
- 2026-07-29 已清除 12 条指向已不存在 `/private/tmp` 目录的 Git worktree 元数据；这不会删除
  任何文件或数据。

## 下一步与停止线

1. 保持 30-symbol 回滚链与 TA 冻结 Universe，继续记录真实分钟 receipt；不得把同一 SQLite
   中的历史 500 facts 当作当前 cohort，且不得通过放宽 SLA 掩盖 QuickSync 分钟数据延迟。
2. 为分钟模拟盘补充可证明满足决策延迟门禁的上游或受控延迟语义；在此之前不再次放行 500。
3. 在不影响分钟运行面的独立安全窗口，将事件合同和 `disclosure_date` 合同纳入一个经过
   manifest、真实 receipt、正式 18082 readback 验证的 production release；发布前不得把
   已保留 server release 称为当前可消费。
4. 当前不扩公共 API、不新增专用采集器，不把已 active、paused 或单次成功说成“全部接口已稳定采集”。

历史候选、事故、旧端口和早期探测结论以 Git 历史与服务器 evidence 为准，不再保留在当前状态页。
