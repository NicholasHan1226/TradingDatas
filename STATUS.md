# SharedSignals 状态

> **给所有 agent：** 读完 [AGENTS.md](AGENTS.md) 理解规则后，读本文件理解"现在在哪、要去哪、能做什么"。
>
> **⚠️ 变更后必须更新本文件。**
>
> 最后更新：2026-07-02

---

## 一、当前状态

- **行情采集**：稳定运行 — Tushare（14 接口）+ Binance（4）+ Polymarket（3）→ SQLite + CSV
- **事件采集**：RSS（883 源）+ Tavily → NDJSON staging → runtime_bridge → CSV
- **巡查自愈**：patrol.py（6 维度 10 分钟）+ heal.py（failover/backfill/checkpoint）
- **采集器架构**：BaseCollector + 6 mixins + 4 采集器实现，完整生命周期（health→plan→collect→validate→dedup→save→audit→coverage）
- **DuckDB 迁移**：SQLite 保持权威写模型 → NDJSON staging → DuckDB read model（StorageAdapter 双后端同步运行中）
- **存储**：marketdata.sqlite（~81MB，11 表），staging 6 streams 活跃
- **服务器**：杭州 `8.138.181.177`（境内采集+存储），新加坡 `47.82.153.58`（境外 RSS → rsync → 杭州）

## 二、已知问题

- DuckDB 迁移未完成：SQLite 仍为权威写模型，DuckDB shadow read-model 在并行运行
- 美国/全球宏观数据覆盖不足
- 港股财务数据采集未接入（Tushare hk_income/hk_balance/hk_cashflow 接口已可用）

## 三、下一步

1. [ ] DuckDB 作为主存储完成切换（当前 SQLite 81MB，数据量持续增长）
2. [ ] 完善美国/全球宏观数据采集覆盖
3. [ ] 接入港股财务数据采集

## 四、活跃任务

- 暂无待办，系统稳定运行

## 五、采集器架构

| 采集器 | 数据源 | 输出表 | 状态 |
|--------|--------|--------|------|
| Tushare | Tushare Pro（21 API） | market_bars_daily 等 | 已有（参考实现） |
| Binance | Binance REST API | market_bars_daily, market_bars_intraday | 新实现 |
| Polymarket | Gamma API + CLOB API | market_pm_markets, market_pm_prices | 新实现 |
| RSS | RSSCollector bridge（883 源） | market_events | 新实现 |

### 运维基础设施

| 组件 | 文件 | 说明 |
|------|------|------|
| 巡查 | `patrol.py` | 6 项健康检查：source_health, data_freshness, staging_backpressure, sqlite_health, disk_usage, field_drift |
| 自愈 | `heal.py` | 6 种策略：source failover, backfill, force bridge merge, WAL checkpoint, disk cleanup, field drift update |
| 同步 | `duckdb_merge.py` | SQLite → DuckDB 定时同步 |
| 调度 | `scheduler.py` | merge → patrol → heal 统一调度入口 |

### Tushare 采集分层

| Tier | 频次 | 内容 |
|------|------|------|
| P0 | 交易时段 5 分钟 | A 股盘中行情 |
| P1 | 盘后日频 | 日线行情 |
| P2 | 盘后日频 | 财务数据 |
| P3 | 晚间日频 | 参考数据 |
| P4 | 早间日频 | 宏观数据 |
| P5 | 收盘后日频 | 港股/美股 |
| P6 | 日频 | 期货/基金/ETF/新闻 |
| P7 | 已删除 | Crypto/PM 不属于 Tushare tier，走各自 collector |

## 六、关联系统状态

- [TradingAgent STATUS](../tradingagent/STATUS.md) — 交易执行与模拟盘状态
- [MarketGraph STATUS](../MarketGraph/STATUS.md) — 研究图谱与因果状态
- [Finance STATUS](../STATUS.md) — 根工作区总览
