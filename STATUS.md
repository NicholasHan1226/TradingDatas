# TradingDatas 当前状态

最后更新：2026-08-26 03:15 CST。本文只保留当前可替换摘要；历史决策见
[`docs/adr/`](docs/adr/)，事故与验收复盘见
[`docs/reports/`](docs/reports/)。当前运行事实仍以本轮服务器、SQLite receipt 和认证
`catalog/query` readback 为准。

## 分层交付状态

| 层 | 本轮事实 | 声明边界 |
|---|---|---|
| GitHub `main` | `9f99800bcfc7a7ce4550add9199d2eef55354ca8`（PR #344，含 #340/#338/#342） | 已验收源码；文档合并不等于发布 |
| 本地 canonical | `cbde095b4080264e71e037ff95d60f024c2a7d4a`，behind 更多 | 已保留的非权威分叉；owner 交接前不 reset/清理；其 rt-min fanout 子集保留逻辑已被 main 等价覆盖 |
| A 股有效 release | `9f99800bcfc7a7ce4550add9199d2eef55354ca8`（回滚点 `423a9f49aee26ac41c476cdf39292e680e150066`） | immutable 运行源码，2026-08-26 02:47 CST 切换 |
| Crypto 有效 release | `f5388759cec0fb3f8f78af97c6f900587eb74b62`（回滚点 `7d04a1f6fe273d81e7ea20bef29c7c7701091df2`） | 隔离 immutable 运行源码，2026-08-23 15:26 CST 切换 |

上述各层必须分别读回；源码、service 或 timer 单层健康都不能写成"三端同步"、
消费者闭环或模拟交易结果。

## 2026-08-26 发布记录

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

- **A 股 / Tushare 数据面：** 有效 immutable release 为 `300182f`；18082 API service
  active/running、通用 collector timer enabled。
- **Crypto 隔离数据面：** immutable `current` 为 `300182f`；18083 API service 为
  `active/running`，匿名 `GET /v1/catalog` 返回 `401`。Spot、rules、book-ticker、USDM、
  OI dump 和 premium-index dump 六个 timer 均 enabled。切换后首轮 spot 采集
  40/40 数据集成功、零 retry。
- **已知残留：** crypto 共享存储锁冲突已在 `5ca8e3e` 改为有界等待（120s）+ 失败
  带错误详情；后续观察 journal 中 `lock_wait_seconds` 的出现频率与数值，确认
  长批次重叠不再造成整轮失败。若仍有等待超时，再评估错峰调度。

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

1. 周一开盘后核对 A 股模拟盘自然轮次的 receipt 与决策结果，确认 rt-min 请求
   在预算内完成且无新增 fail-closed。
2. 观察 crypto journal 中 `lock_wait_seconds` 的频率与数值，确认锁冲突不再
   造成整轮采集失败；异常时再评估错峰调度。
3. 发生值得长期追溯的异常、生产验收或迁移时，在 `docs/reports/YYYY-MM-DD-*.md` 新建日期化
   报告；普通变更由 Git history 追溯。
4. 下一次 material observation 直接替换本页，不追加事故年表，也不把这里的 SHA、count 或
   timer 状态复制进长期 API/Operations 合同。
