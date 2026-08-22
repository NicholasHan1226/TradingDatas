# TradingDatas 当前状态

最后更新：2026-08-23 00:45 CST。本文只保留当前可替换摘要；历史决策见
[`docs/adr/`](docs/adr/)，事故与验收复盘见
[`docs/reports/`](docs/reports/)。当前运行事实仍以本轮服务器、SQLite receipt 和认证
`catalog/query` readback 为准。

## 分层交付状态

| 层 | 本轮事实 | 声明边界 |
|---|---|---|
| GitHub `main` | `300182f935c7f9f35b01d08ef049d4ed911df652` | 已验收源码；文档合并不等于发布 |
| 本地 canonical | `cbde095b4080264e71e037ff95d60f024c2a7d4a`，ahead 1 / behind 8 | 已保留的非权威分叉；owner 交接前不 reset/清理；其 rt-min fanout 子集保留逻辑已被 main 等价覆盖 |
| A 股有效 release | `300182f935c7f9f35b01d08ef049d4ed911df652`（回滚点 `f085075e98f5de9199482e8aac0281d4f1ec529e`） | immutable 运行源码，2026-08-23 00:22 CST 切换 |
| Crypto 有效 release | `300182f935c7f9f35b01d08ef049d4ed911df652`（回滚点 `d711414bec41356724dd2bdbeaf4601459ff2778`） | 隔离 immutable 运行源码，2026-08-23 00:25 CST 切换 |

上述各层必须分别读回；源码、service 或 timer 单层健康都不能写成"三端同步"、
消费者闭环或模拟交易结果。

## 2026-08-23 发布记录

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
- **已知残留：** crypto 共享存储锁下，长时 USDM/OI-dump 批次仍会让 5 分钟级
  spot/book-ticker 批次以 lock-held 快速失败（本轮切换后已观察到 2 次）；
  该行为是既有设计（非阻塞抢锁 + 失败即退出），不是本轮发布引入。修复方向
  （阻塞等待或错峰调度）需单独走 PR。

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
2. 观察 crypto spot/book-ticker 的 lock-held 失败频率，决定是否提 PR 改为
   有界阻塞等待或错峰调度。
3. 发生值得长期追溯的异常、生产验收或迁移时，在 `docs/reports/YYYY-MM-DD-*.md` 新建日期化
   报告；普通变更由 Git history 追溯。
4. 下一次 material observation 直接替换本页，不追加事故年表，也不把这里的 SHA、count 或
   timer 状态复制进长期 API/Operations 合同。
