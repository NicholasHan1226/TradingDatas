# TradingDatas 当前状态

最后更新：2026-08-22 17:47 CST。本文只保留当前可验证摘要；历史决策见
[`docs/adr/`](docs/adr/)，事故与验收复盘见
[`docs/reports/`](docs/reports/)。当前运行事实仍以本轮服务器、SQLite receipt 和认证
`catalog/query` readback 为准。

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

## 能力和边界

- 数据集独立沿 `contract_ready -> observed -> stable` 推进。隔离观察 timer 可以持续收集
  证据；它既不等于 `stable`，也不允许无界扩容。
- TradingDatas 仅提供数据接入、采集、SQLite 事实、receipt/lineage 和固定
  `GET /v1/catalog` / `POST /v1/query`。它不拥有策略、资金、订单、成交、执行或任何
  TradingAgent authority。

## 下一步

1. 按各 dataset 自己的 cadence、receipt、freshness 和认证 consumer readback 累积观察证据。
2. 发生值得长期追溯的异常、生产验收或迁移时，在 `docs/reports/YYYY-MM-DD-*.md` 新建日期化
   报告；普通变更由 Git history 追溯。
