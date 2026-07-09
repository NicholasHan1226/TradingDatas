# SharedSignals

> **阅读顺序：** 进入 SharedSignals 后，先读 [AGENTS.md](AGENTS.md) → [STATUS.md](STATUS.md) 了解规则和当前状态。本文件提供系统概述和架构总览。

共享数据采集与存储层。一次采集，研究线和交易线共享读取。SharedSignals 支撑的是分钟级/5 分钟级交易数据供给，不是毫秒级 HFT、撮合、下单或资金执行系统。

## 目标
统一所有数据源的采集、去重、存储，消除重复采集，确保两线读到同一份数据。

## 价值
- 消除重复采集（节省API成本+避免数据不一致）
- 统一存储格式（SQLite read model + DuckDB 分析镜像）
- 单一数据出口（两线不直接调外部API，只读SharedSignals）
- API 读侧有限行、短超时和大表索引保护；慢查询返回 degraded，不阻塞交易/研究调用方

## 架构
```
采集层 → 校验/去重 → SQLite read model → DuckDB 分析镜像
  Tushare(P0-P7分层接口) → marketdata.sqlite
  Binance(9 symbols, ticker 30min + 6h klines) → marketdata.sqlite
  Polymarket(markets/prices) → marketdata.sqlite
  RSS/RSSHub      → retired/deferred（恢复前需重建直接入库 collector）
  Tavily/DeepSeek → disabled（不属于当前生产采集）
  基本面           → 预计算落库后只读
```

## 存储
- 行情: `/opt/investment/SharedSignals/runtime/read_model/marketdata.sqlite` + `/opt/investment/SharedSignals/data/marketdata.duckdb` — 对外 HTTP API 只读此处
- 事件: SQLite (URL去重) — 原始事件, 不做分类
- 参考: SQLite `market_assets` / `market_factors` / `market_events`；旧 reference CSV 不作为生产 API 兜底

## 边界
- 做: 采集、去重、存储、健康监控、自愈
- 不做: 不分析、不分类、不做交易决策；不做毫秒级 HFT、订单簿撮合、下单或资金执行
- 不做: 不直接调外部API给消费者（通过存储层间接）

## 与其他层的关系
- → MarketGraph: 只读行情+事件+基本面（研究用）
- → TradingAgent: 只读行情+事件+基本面+资金（交易用）
- ← 不接收: 不接收研究结论或交易结果（单向输出）

## 采集频率
- 行情: A股与期货盘中 5min / Crypto 与 Polymarket 30min / 日级（盘后）
- 事件: RSS/RSSHub/Tavily 当前不作为现役生产采集；恢复前必须走 SharedSignals collector 直接入库契约
- 基本面: 日级预计算
- 宏观: 日级
- 低频参考: 周/月线通过 P7 低频 lane 每周独立刷新，不混入每日 P6

## API 输出保护
- `/events`、`/fundamentals`、`/macro`、`/tushare` 等大表接口必须把 `limit` 下推到数据库查询。
- SQLite read model 只读查询设置短 busy timeout 和查询超时；超时返回 degraded 元数据，不回退旧 CSV/旧目录。
- 外部应用通过 SharedSignals HTTP API 读取数据；TradingAgent、MarketGraph 和外部 agent 不直接调用 provider 或旧目录。
- 外部 agent 接入先读 `/health` 与 `/agent_config`；复制用 prompt 见 `docs/external_agent_api_prompt.md`，机器配置见 `config/external_agent_api_config.json`。

## 服务器
- 主服务器 8.138.181.177: 境内采集 + 存储 + 只读 API
- 新加坡 47.82.153.58: 境外代理 relay；RSS/RSSHub 已停止，历史路径仅作审计参考

## 仓库
https://github.com/NicholasHan1226/SharedSignals.git
