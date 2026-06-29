# SharedSignals Status

## 迁移进度 (2026-06-29)
- [x] 文件夹结构 (collectors/storage/bridge/reference/memory/logs)
- [x] bridge/ — 软链 MarketGraph runtime_bridge + marketdata_db
- [x] reference/ — 软链 Tushare wrapper (a_share_tushare_api.py)
- [x] reference/ — 软链 RSSCollector (bridge/filter/feed_store/collector/config.yaml)
- [x] reference/market_calendar.py — 交易日历 (基于 Tushare trade_cal API)
- [ ] collectors/ — 各数据源采集器 (待提取, 统一接口)
- [ ] storage/ — DuckDB schema (当前 SQLite marketdata.sqlite 75MB, 11表)

## 当前接入 (软链方式, 零拷贝)
| 模块 | 软链目标 | 用途 |
|------|----------|------|
| bridge/marketgraph_runtime_bridge.py | MarketGraph/tools/ | staging→CSV 归并桥 |
| bridge/marketgraph_marketdata_db.py | MarketGraph/08-Market-Interfaces/tools/ | marketdata.sqlite 读写 |
| reference/a_share_tushare_api.py | Ashare/tools/ | Tushare 14接口统一封装 (LRU缓存) |
| reference/rss_bridge.py | RSSCollector/bridge.py | RSS 采集桥 |
| reference/filter.py | RSSCollector/ | RSS 过滤 |
| reference/feed_store.py | RSSCollector/ | RSS 存储 |
| reference/collector.py | RSSCollector/ | RSS 采集器 |
| reference/config.yaml | RSSCollector/ | RSS 配置 |
| reference/market_calendar.py | 本仓原生 | A股交易日历 |

## 数据现状
- 行情: Tushare(14接口)/Binance(4)/PM(3) → SQLite + CSV缓存
- 事件: RSS(883源)+Tavily+agents → staging NDJSON → runtime_bridge → CSV
- 基本面: Tushare财务接口 (按需实时调)
- marketdata.sqlite: 75MB, 11表, 正常运行
- staging: 6 streams, 活跃

## 交易日历 API (reference/market_calendar.py)
- is_trading_day(date=None) — 默认今天; 返回 bool
- get_next_trading_day(date=None, include_today=False) — 下一个交易日; 无则 None
- get_trading_days(start, end) — 闭区间 [start, end] 内所有交易日 (list[date])
- 日期参数接受 date/datetime/str (YYYY-MM-DD / YYYY/MM/DD / YYYYMMDD)
- 内置 (start,end) 范围缓存 + 复用 Tushare wrapper 的 LRU 缓存
- 已通过实盘 Tushare API 验证 (2026-06-29: today=True, next=2026-06-30)

## 待办
- 提取现有采集器到 collectors/, 统一采集接口
- 引入 DuckDB (当前 SQLite, 计划迁移)
- patrol.py / heal.py 巡查自愈
