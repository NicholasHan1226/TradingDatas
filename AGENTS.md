# SharedSignals

## 目标
统一数据采集与存储, 供研究线和交易线共享读取。

## 边界
- 做什么: 采集行情/事件/基本面/资金/宏观, 去重入库
- 不做什么: 不分析, 不分类, 不做交易决策
- 存储: SQLite (marketdata.sqlite 75MB) + CSV + NDJSON staging

## 现状
- 行情: Tushare(14接口)/Binance(4)/PM(3) → SQLite + CSV缓存
- 事件: RSS(883源)+Tavily+agents → staging NDJSON → runtime_bridge → CSV
- 基本面: Tushare财务接口 (按需实时调)
- staging: 6 streams (event_candidates/sentiment_signals/collection_runs/...)

## 依赖
- 读取: 外部API (Tushare/Binance/PM/RSS/Tavily/DeepSeek)
- 输出: SQLite + CSV → MarketGraph和Tradings读取

## 文件结构
- collectors/ — 各数据源采集器
- storage/ — DuckDB/SQLite schema和管理 (未来DuckDB, 当前SQLite)
- bridge/ — staging→DB归并桥
- reference/ — 参考数据 (stock_master/source_registry/entity_map/market_calendar)
- memory/ — 采集层记忆
- patrol.py — 巡查 (来源健康/数据新鲜度)
- heal.py — 自愈 (切换备用源/补采)
