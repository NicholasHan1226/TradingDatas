# SharedSignals

> **阅读顺序：** 进入 SharedSignals 后，先读 [AGENTS.md](AGENTS.md) → [STATUS.md](STATUS.md) 了解规则和当前状态。本文件提供系统概述和架构总览。

共享数据采集与存储层。一次采集，研究线和交易线共享读取。

## 目标
统一所有数据源的采集、去重、存储，消除重复采集，确保两线读到同一份数据。

## 价值
- 消除重复采集（节省API成本+避免数据不一致）
- 统一存储格式（DuckDB行情 + SQLite事件 + CSV参考）
- 单一数据出口（两线不直接调外部API，只读SharedSignals）

## 架构
```
采集层 → staging NDJSON (无锁缓冲) → bridge归并 → 存储
  Tushare(14接口) → marketdata.sqlite
  Binance(4接口)  → marketdata.sqlite
  Polymarket(3接口) → marketdata.sqlite
  RSS(883源)      → staging → sentiment_signals.csv
  Tavily/agents   → staging → event_candidates.csv
  基本面           → 按需实时调
```

## 存储
- 行情: marketdata.sqlite (75MB, 11表) — MCP工具读此处
- 事件: SQLite (URL去重) — 原始事件, 不做分类
- 参考: CSV (stock_master, source_registry, entity_map, market_calendar)

## 边界
- 做: 采集、去重、存储、健康监控、自愈
- 不做: 不分析、不分类、不做交易决策
- 不做: 不直接调外部API给消费者（通过存储层间接）

## 与其他层的关系
- → MarketGraph: 只读行情+事件+基本面（研究用）
- → TradingAgent: 只读行情+事件+基本面+资金（交易用）
- ← 不接收: 不接收研究结论或交易结果（单向输出）

## 采集频率
- 行情: 5min全市场（盘中）/ 日级（盘后）
- 事件: 10-15min（RSS/agents）
- 基本面: 日级预计算
- 宏观: 日级

## 服务器
- 杭州 8.138.181.177: 境内采集 + 存储
- 新加坡 47.82.153.58: 境外RSS采集 → rsync → 杭州

## 仓库
https://github.com/NicholasHan1226/SharedSignals.git
