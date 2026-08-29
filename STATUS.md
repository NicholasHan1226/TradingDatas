# TradingDatas 当前状态

最后更新：2026-08-26 23:5x CST（第十一轮记录；cf988f9 已于 23:07 CST 切换）。本文只保留当前可替换摘要；历史决策见
[`docs/adr/`](docs/adr/)，事故与验收复盘见
[`docs/reports/`](docs/reports/)。当前运行事实仍以本轮服务器、SQLite receipt 和认证
`catalog/query` readback 为准。

## 分层交付状态

| 层 | 本轮事实 | 声明边界 |
|---|---|---|
| GitHub `main` | `2d88158`（含 #354 诊断修复与 public-web 数据源面，Controller 持续推进中） | 已验收源码；文档合并不等于发布 |
| 本地 canonical | `cbde095b4080264e71e037ff95d60f024c2a7d4a`，behind 更多 | 已保留的非权威分叉；owner 交接前不 reset/清理；其 rt-min fanout 子集保留逻辑已被 main 等价覆盖 |
| A 股有效 release | `cf988f93e6dbe379f82fd0a530e081af6aab8965`（回滚点 `21d03183355d7de6578ab5761d83aa91a1925c1f`） | immutable 运行源码，2026-08-26 23:07 CST 由 Controller 切换；verify true + catalog 200 复核通过 |
| Crypto 有效 release | `f5388759cec0fb3f8f78af97c6f900587eb74b62`（回滚点 `7d04a1f6fe273d81e7ea20bef29c7c7701091df2`） | 隔离 immutable 运行源码，2026-08-23 15:26 CST 切换 |

上述各层必须分别读回；源码、service 或 timer 单层健康都不能写成"三端同步"、
消费者闭环或模拟交易结果。

## 2026-08-26 发布记录

第十一轮（23:07 CST 切换 `cf988f9`，PR #354；自愈验收与三项诊断同轮收口）：

- **#352 自愈验收（21:55 定时检查 + 查询面回读）**：`cn.news.flash` 的
  `invalid_receipt_authority` 跳过消失、窗口内 `data_through_in_future` 零命中；
  认证查询回读 state=success、首页 500 行、内容新鲜至当日且**零未来时间戳行**。
  恢复期一例 provider_error 与两例 ingest validation_failed 属采集面常态波动；
  发现缺口：validation_failed 的 `validation_reasons:[]` 为空，失败细节同样不可判读，
  排入后续改进。消费契约实证：快照型数据集 `as_of_field=null`，带 `as_of` 的
  `/v1/query` 一律 invalid_request——正确形状不含 as_of。
- **PR #354 firecrawl 信封诊断修复**：根因链——SEC 页抓取常态耗时 18-22s 贴近
  timeout_ms=30000 上限（复现 >30s 客户端超时），但生产主导失败形态是
  `success:false` 信封且 firecrawl 错误文本被适配器整体丢弃（今日两 news 数据集
  82 failed / 51 success 全为不可判读 provider_error）。修复按白名单标记把信封错误
  归类为固定罐头诊断（timed-out / refused-by-target / generic），经专用内部异常
  `_FirecrawlUpstreamFailure` 直达 outcome error_message，原文永不入日志/receipts；
  error_code、fail-closed 语义与契约哈希零变化。+4 单测含防泄漏断言，文件级
  35 passed、相邻套件 177 passed、CI 4/4。合并后由 Controller 于 23:07 标准流程
  部署并切换 current → `cf988f9`；本侧复核 verify true + catalog 200。
  待自然失败样本回报三类分布后再议 timeout_ms 上调或换源。
- **#309 关闭（带生产证据）**：share_float 断供已由 #344 解决（ann_date=20260826
  实测 73 行、data_through=当日）；float_date 四算子过滤实测正确生效、目录广告一致；
  "当日公告解禁日在次日"属正确时点语义；08-24 的 503 恶化归 #327 存储病。
- **cb_basic 停更=纯调度缺失（已回填 #350）**：cadence_policy 自 07-23 即 on_demand；
  journal 全窗零次调度成功（08-11 前 paused、08-12 起 on_demand skip）；上游探针
  空参快照 success 1162 行。建议归入 daily_reference 或常规 on-demand batch。
- **fina_mainbz 探针定案（已回填 #349）**：QuickSync 端点无任何公告日暴露，唯一日期
  杠杆是报告期 end_date；多码+start/end（现模板形态）静默空实锤；单码全史 ~150 行/码
  （4 报告期 ×~37）；type=P 硬编码会静默丢弃地区(D)/行业(I)构成。提案：单码低频全史
  快照扇出 + 去掉 type 过滤，实施前需解 dependency_seed_receipt_unresolved。

第十轮（19:28 CST，A 股面 → `21d0318`，PR #352）：Controller 侧修复 cls.cn 电报条目
携带 ~12h 未来时间戳毒化 `cn.news.flash` 收据水印、导致数据集被 planner 以
`invalid_receipt_authority` 持续跳过（09:50 起）的事故。修复为写时钳制：
`_clamp_future_watermark` 用与投影侧 `_data_through_in_utc` 完全一致的解析阶梯
（%Y%m/%Y%m%d/ISO，naive 按 dataset 时区），把严格晚于写入时刻的候选 data_through
钳到 `written_at`；trade_calendar 豁免与投影层镜像。审计通过后本地全量复跑
2322 passed / 1 skipped（25m54s），标准流程发布：build→scp→staging（manifest 驱动
chmod 0444/0555、目录 0555、root:root）→verify→停 timer 排空在途周期（90s）→
switch-current→恢复服务，认证 catalog readback 200/192 datasets。运维注记：本轮
回滚点 `252eb9b` 的顶层 manifest 缺失，按确定性重建（同 commit 同树 ⇒ 字节一致）
并先对已安装树 verify 通过后才切链；manifest 归位 `manifests/<sha>.json` 约定。
事故语义：修复只阻断新增毒化，存量未来水印需等墙钟越过该时间戳（约当日 21:45 CST）
后由 `state.invalid_reasons` 自然恢复干净，采集自动续跑——已排一次性验收检查。
另：`global.news.flash` 周期 state=failed 为 firecrawl `provider_error`（既有独立
问题，与本修复无关）。回滚点 `252eb9b2`。

第九轮（10:33 CST，A 股面 → `c5e8499`，PR #348）：#319 收尾——#347 把六个财报源
换到 ann_date 窗后，实弹探针（复刻 collector 传输 `tushare_rows_outcome`）证明
QuickSync 端点行为：income 族逗号多码 ts_code 携带任意第二参数静默返回空（单码+
同一 ann_date 返回 2 行；ann_date 单独被拒 20002 必填 ts_code）；pledge_stat 每
请求静默截断在 1000 行（三长历史码恰返回 1000，单码最大观测 641）。据此七源
（income/balancesheet/cashflow/express/fina_indicator/fina_audit/pledge_stat）
`batch_size` 10→1，U=`1eee7462…`、registry=`7f99b8f1…` 重生成重钉，新增生成态
registry 回归钉测并把七源移出 `TEN_CODE_FANOUT_APIS`（含原因注释）。流程同标准
发布：build→staging root:root→verify→停 timer 排空→switch-current→恢复。排障
记录：切链时 switch-current 报 "release directory mode must be 0555"，根因是此前
服务器端探针以 venv python 直接从发布树 import 且未设 PYTHONDONTWRITEBYTECODE，
在不可变树里留下 __pycache__（755）；清除并复验回滚树后切换成功。教训：对发布树
的任何一次性 python 调用必须带 `PYTHONDONTWRITEBYTECODE=1`。后续 issue：#349
（fina_mainbz 无 ann_date 字段需 period-window 设计）、#350（七个数据集
cadence=on_demand 从未被调度——生产零行的直接原因是调度缺失而非采集失败；
cb_basic 自 2026-08-14 停更待诊断）。回滚点 `9f2f19c8`。
实弹验收（当日两次 on_demand 单窗触发）：修复形态在生产路径真实出数——income
ann_date=20260826 落 389 行 valid（约 190 个真实公告码，半年报季）；pledge_stat
落 399,315 行单码全史、无 1000 行截断；重跑去重语义验证通过（62,520 行全部
unchanged）。两次扇出均在 ~1-2k 请求后遭上游同端点持续突发停滞（客户端传输超时
fail-fast 中止；同期混合定时周期正常，属 #350 已量化的上游行为）。数据集最新周期
state=failed 期间查询面按设计 fail-closed 返回空（`allow_rows=False`），干净周期
完成后恢复；全宇宙覆盖需 #350 的 resumable_fanout/排期决策。

第八轮（08:51 CST，A 股面 → `9f2f19c`，PR #347）：#319 第一轮——六个财报源
（income/balancesheet/cashflow/express/fina_indicator/fina_audit）请求模板从
run_clock 推导的 end_date/start_date 窗改为 ann_date 单日窗（公告日语义，窗口机制
全通用无需改调度 lane），pledge_stat 去掉 end_date 改纯 ts_code 扇出（stk_rewards
先例形态）；观察文件 registered pin → U=`8b372d0d…`、registry=`776a23a5…` 重生成
重钉。部署后实弹验收发现多码+过滤组合静默空（见第九轮），故本轮为"必要但不充分"，
由 #348 完成修复。回滚锚 `9f99800`。

第七轮（02:47 CST，A 股面 → `9f99800`，PR #344）：#339 修复——share_float 上游单次
响应静默截断在 ~6000 行而声明 pagination strategy=none，高流量 ann_date 六个分区
（20260801/03/05/06/10/19）以成功 receipt 入库了截断数据且无失败信号。声明层改为
offset 分页（page_size=6000、max_pages=8、budgets 48000→编译安全上限 42466，
满页 fail-closed 语义保留）。为表达多页分页，运行时契约编译器新增可选观察键
`pagination_max_pages`（正整数、默认 1，替代投影中硬编码的 max_pages=1，要求伴随
limit/offset literal，阻断 probe 禁用）；share_float 官方文档节补登 limit/offset 输入
（bak_daily 先例），下游全部哈希钉更新：runtime+cadence policy canonical SHA、
request-profiles 文档 SHA、观察 provenance 四项、upstream contracts 与
provider-native registry 重生成、activation wave registry 哈希重钉；双编译器字节级
幂等复现。回归测试断言编译产物分页参数与预算覆盖最大观测日（20411 行）。
流程：本地 build manifest（255 files）→ staging root:root 按 manifest 定模式 →
verify 通过 → 停 timer 排空采集（02:40 一轮 firecrawl 双源 provider_error 致 exit 1
为遗留问题非回归）→ switch-current → 服务恢复，catalog 认证回读正常。
重补验证：六分区 on_demand 单窗重采全部 success，唯一行数
6000→8068/17805/20411/11290/11277/10562（合计找回 43413 行），证明上游真实支持
offset 翻页；API query 回读 `ann_date=20260805` 数据可消费。回滚点 `423a9f49`。

## 2026-08-25 发布记录

第六轮（23:40 CST，A 股面 → `423a9f4`，PR #340 + #338）：#340 为 #283 修复——
dataset_field fanout 源读取从非阻塞抢锁改为有界共享锁等待
（`_FANOUT_SOURCE_LOCK_WAIT_SECONDS=180`），并发写入方（backfill/重叠采集）到来时
延迟读而非 fail-closed；#338 为 console 工作区统一与数据状态文案（静态资源随版）。
流程：本地 build manifest（255 files）→ staging 只读 root:root → verify 通过 →
safe-release preflight（timer disabled、collector 排空、API inactive）→ switch-current
→ verify-current verified=true → 认证 readback：catalog 192 datasets、
`cn.equity.daily` query 200（TA 消费者 token）。切换后新代码采集运行 Tushare 面
全部成功；`global.news.flash`（firecrawl）provider_error 致 exit 1 为部署前后一致的
遗留问题，非本次回归。回滚点 `4f7f894`。

后续（00:30 CST，#342，test-only）：修复 firecrawl 裸时间锚测试
`test_bare_wall_clock_time_is_anchored_to_source_day` 的日期边界缺陷——测试用真实
时钟推期望日，而生产代码在本地 00:00–08:09:28 窗口会正确回退一天避免未来时间戳，
故该窗口内 CI 必挂；注入固定 `observed_at` 后确定性通过。生产行为不变，无需重新发布；
旧分支 `fix/firecrawl-bare-time-anchor`（210c02e）的生产改动已由 main 等价承载，
归档候选。

## 2026-08-23 发布记录

第五轮（15:26 CST，crypto 面 → `f538875`，PR #271）：oi-dump 共享锁等待上限由
120s 提升至 480s（unit TimeoutStartSec=600s 内）。生产实弹验证 `systemctl start`
后 ExecMainStatus=0，数据集按设计报 unchanged/unpublished 软缺口，unit 不再标红。
回滚点 `7d04a1f`。

第四轮（15:07 CST，crypto 面 → `7d04a1f`，PR #270）：oi-dump 入口锁从非阻塞
flock 改为有界等待 `_timed_lock`，消除与 book-ticker/funding 批次的瞬时碰撞。
首次实弹暴露 120s 不足，引出第五轮。

第三轮（14:33 CST，A 股面 → `7f6ba42`，PR #269）：`daily_limit_exceeded` 补入
`_V1_ERROR_DETAILS`（对齐冻结合同的 429 语义）；`GET /admin/api/usage/history`
NameError 修复；调度器预算耗尽改 skipped 语义并新增错误码静态守卫测试。
匿名 401 readback 通过；消费者级认证 readback 待 owner 执行。

第二轮（02:20/02:23 CST，两面 → `5ca8e3e`，PR #267）：scheduled crypto 采集器
（spot bars / book-ticker / USDM）从非阻塞抢锁改为有界 120s 等待
（`_bounded_lock`），失败输出带具体错误与 `lock_wait_seconds`；`_private_lock`
保留给快路径调用方。同一 trusted verifier（SHA256 复核一致）、registry 重编译逐字节
一致；两面 switch-current、verify-current（含 manifest）、认证 readback 均通过。
回滚点统一为 `300182f`。

第一轮（00:22/00:25 CST，两面 → `300182f`）：

发布通道：本地 clean worktree（origin/main HEAD）→ `release_manifest.py build`
→ `marketgraph-root` 写入新 commit 目录 → trusted verifier 校验 → registry 重编译
逐字节一致 → safe-release preflight（API inactive、timers disabled、collector 排空）
→ `switch-current` → verify-current → service/timer 恢复 → 认证 readback。

- A 股面：匿名 catalog `401`、TradingAgent token catalog `200`（6.4s/874KB）；
  `tradingdatas-v1-internal.service` active、provider-native timer enabled。
- Crypto 面：切换前先按 OPERATIONS normalize-current 规程把遗留绝对 `current`
  指针改为相对形式（trusted verifier SHA256 与已验证 release 内副本一致）；
  匿名 `401`、crypto read token catalog `200`；API active、六个 binance timer enabled。
- Crypto 回滚 manifest 缺失已在切换前从同一 Git commit 重建并验证补齐
  （`manifests/d711414b….json`，与线上现存 release 字节一致）。
- 手动触发一轮 A 股模拟盘：`status=noop`、`reason=outside_delayed_session_window`、
  `selected_mode=rolling_eligible`、安全门全部关闭。对比 8 月 21 日的
  `fail_closed/minute_tradingdatas_request_failed`，数据面请求路径已恢复；
  最终结论以下一个交易日（周一）自然轮次为准。

## 当前运行面

- **A 股 / Tushare 数据面：** 有效 immutable release 为 `cf988f9`（2026-08-26 23:07 CST
  由 Controller 切换，回滚点 `21d0318`）；18082 API service active、通用 collector timer
  enabled。#350 调度合同已在源码完成、尚未 exact-main 发布：`cb_basic` 改为
  `daily_reference`（每轮 1 个空参快照）；income/balancesheet/cashflow/express/
  fina_indicator/fina_audit/pledge_stat 与 `cb_share` 离开 `on_demand`，改为
  `event`（与 `stk_holdernumber`/`disclosure_date` 的 ann_date 窗一致）并复用
  `cyq_chips` 的 `resumable_fanout.max_batches_per_run=1`。`top10_floatholders`
  仍 parked。生产触发/验收是发布后的运维步骤，本状态不声称已排期出数。
  `cn.news.flash` 已按预期墙钟自愈（查询面 success、零未来行），两 news 数据集的
  firecrawl 间歇失败等待 #354 新诊断字段回报类别分布。快照型数据集查询不带 as_of。
- **Crypto 隔离数据面：** immutable `current` 为 `300182f`；18083 API service 为
  `active/running`，匿名 `GET /v1/catalog` 返回 `401`。Spot、rules、book-ticker、USDM、
  OI dump 和 premium-index dump 六个 timer 均 enabled。切换后首轮 spot 采集
  40/40 数据集成功、零 retry。
- **已知残留：** crypto 共享存储锁冲突已在 `5ca8e3e` 改为有界等待（120s）+ 失败
  带错误详情；后续观察 journal 中 `lock_wait_seconds` 的出现频率与数值，确认
  长批次重叠不再造成整轮失败。若仍有等待超时，再评估错峰调度。
- **#327 WAL：** 可写采集连接请求 WAL、catalog/query 在 sidecar 存在时不用
  `immutable=1` 的代码已完成；广州生产库 journal mode 尚未在 write-pause /
  exact-main 发布路径切换，本状态不声称已释放。

## 能力和边界

- 数据集独立沿 `contract_ready -> observed -> stable` 推进。隔离观察 timer 可以持续收集
  证据；它既不等于 `stable`，也不允许无界扩容。
- TradingDatas 仅提供数据接入、采集、SQLite 事实、receipt/lineage 和固定
  `GET /v1/catalog` / `POST /v1/query`。它不拥有策略、资金、订单、成交、执行或任何
  TradingAgent authority。
- exact500 与 Crypto full-40 只约束各自命名覆盖声明，不阻止 PIT 安全的
  per-symbol/per-shard 模拟消费者。
- Prediction markets 与 CNFutures 保持暂停；本状态不产生真实交易、资金、订单或
  execution authority。

## 下一步

1. #350 排期决策：为 income 族/pledge_stat/top10_floatholders/cb_share/cb_basic
   选定 cadence 与 resumable_fanout 策略（全宇宙覆盖需跨周期收敛；cb_basic 停更
   已定案为调度缺失）；干净整轮完成后补查询面回读验收。
2. 依 #354 新诊断字段观察 firecrawl 失败类别分布（timeout / refused / other），
   决定 timeout_ms 上调或换源；顺手改进 validation_failed 的空
   `validation_reasons` 缺口。
3. #349：fina_mainbz 按探针提案落地（单码全史快照扇出 + 去 type 过滤），
   先解 dependency_seed_receipt_unresolved。
4. #327 WAL 代码已落地（可写 open 请求 WAL；生产 journal 切换仍待 write-pause +
   exact-main，本仓不自动部署 GZ）。
5. 归档候选交 Controller 收口（rt-min-daily-scan-budget 分支、rolling-simulation
   残留、ta-365/366、fix/firecrawl-bare-time-anchor 210c02e、约 60 陈旧分支）。
6. 发生值得长期追溯的异常、生产验收或迁移时，在 `docs/reports/YYYY-MM-DD-*.md` 新建日期化
   报告；普通变更由 Git history 追溯。
7. 下一次 material observation 直接替换本页，不追加事故年表，也不把这里的 SHA、count 或
   timer 状态复制进长期 API/Operations 合同。
