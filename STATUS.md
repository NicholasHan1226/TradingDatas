# TradingDatas 当前状态

最后更新：2026-08-22 18:32:42 CST。本文只保留当前可替换摘要；历史决策见
[`docs/adr/`](docs/adr/)，事故与验收复盘见
[`docs/reports/`](docs/reports/)。当前运行事实仍以本轮服务器、SQLite receipt 和认证
`catalog/query` readback 为准。

## 分层交付状态

| 层 | 本轮事实 | 声明边界 |
|---|---|---|
| GitHub `main` | `b15c0718ee5d02150d2e603a5a196bdd49dcfb62` | 已验收源码；文档合并不等于发布 |
| 本地 canonical | `cbde095b4080264e71e037ff95d60f024c2a7d4a`，ahead 1 / behind 8 | 已保留的非权威分叉；owner 交接前不 reset/清理 |
| 普通服务器源码 | 标准 `/opt/investment` 源码路径下未发现 canonical checkout | 不声明同步；也不是 immutable release 的必要条件 |
| A 股有效 release | `f085075e98f5de9199482e8aac0281d4f1ec529e` | immutable 运行源码 |
| Crypto 有效 release | `d711414bec41356724dd2bdbeaf4601459ff2778` | 隔离 immutable 运行源码 |

上述各层必须分别读回；源码、service 或 timer 单层健康都不能写成“三端同步”、
消费者闭环或模拟交易结果。

## 当前运行面

- **A 股 / Tushare 数据面：** 有效 immutable release 为 `f085075e`；18082 API service
  active/running、通用 collector timer enabled。非交易时段的认证 query 可诚实投影为 stale，
  这不等于数据面故障；有效 release、service/timer、receipt 与 API freshness 仍由本轮
  readback 分别判断。
- **Crypto 隔离数据面：** immutable `current` 为
  `d711414bec41356724dd2bdbeaf4601459ff2778`；18083 API service 为
  `active/running`，匿名 `GET /v1/catalog` 返回 `401`。Spot、rules、book-ticker、USDM、
  OI dump 和 premium-index dump 六个 timer 均 enabled，只在隔离、预算受控、fail-closed 的
  数据运行面累积 receipt。
- **Crypto 最新 readback：** 17:40 CST 的自然 Spot 5 分钟窗口对冻结 40/40 标的成功，
  零 retry、同一 window；TradingAgent 专用 read token 在 18083 返回 240 个 dataset，
  `crypto.spot.binance.btcusdt.5m` 为 `ready/success/fresh/valid`、
  `degraded=false`，receipt 与 lineage 完整。

## 同批 A 股 collector 结果

18:32:42 CST 的同一次 readback 为 `Result=success`、exit status 0、`failed=0`、
`planned=0`、`skipped=187`、`terminal=5`。`cn_schedule`、`cyq_chips`、
`cyq_perf` 与 `global.news.flash` 成功，`daily_basic` 为合法 empty；这些值不得与
其它时点或批次混搭。`cn.news.flash` 因 `data_through_in_future` 被局部跳过，
只阻断该 capability，不反向否定五个终态结果或其它独立数据集。

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

1. 对最新有效 A 股 receipt 补同一身份与观测时间的认证 `catalog/query` 及 TA consumer
   readback；健康 service/timer 不能替代它。
2. 按各 dataset 自己的 cadence、receipt、freshness 和认证 consumer readback 累积观察证据。
3. 发生值得长期追溯的异常、生产验收或迁移时，在 `docs/reports/YYYY-MM-DD-*.md` 新建日期化
   报告；普通变更由 Git history 追溯。
4. 下一次 material observation 直接替换本页，不追加事故年表，也不把这里的 SHA、count 或
   timer 状态复制进长期 API/Operations 合同。
