# ADR-0010: TradingDatas clean-slate data platform

## Status

Accepted — 2026-07-20.

## Decision

产品、GitHub 仓库、本地目录和下一代生产运行面统一命名为 TradingDatas。

TradingDatas 只保留 provider-neutral data platform：统一 Tushare transport、registry/config、provider-native SQLite facts、transaction receipts、generic scheduler、`GET /v1/catalog` 和 `POST /v1/query`。

旧交易门禁、研究关系、专用 API、Crypto、预测市场、DuckDB、邮件、旧 cron、旧 reader 和双注册表兼容不进入 TradingDatas 新架构。它们从当前代码树删除；旧生产只在新系统完成切换前作为短期回滚源。

## Reasons

旧系统同时承担数据、研究、交易门禁、运维和兼容职责，导致普通 Tushare 数据集不能通过配置快速接入。clean-slate 方案把普通接口 onboarding 恢复为 registry/config 工作，避免继续逐接口开发和无限兼容。

## Compatibility

消费者合同继续使用 `/v1/catalog` 和 `/v1/query`，因此 TradingAgent 和 MarketGraph 不需要 provider-specific 改造。产品名称和 base URL 配置改为 TradingDatas；真实 dataset IDs 由 catalog 冻结。

## Retirement

Git 历史保留旧实现。当前树不保留重复旧文档。旧生产服务只能在 TradingDatas 真实采集、API readback、消费者切换和回滚证据通过后删除。数据库和历史数据不随代码退役自动删除。
