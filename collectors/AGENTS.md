# Collectors — SharedSignals 数据采集层

> **阅读顺序：** [../AGENTS.md](../AGENTS.md) → [../STATUS.md](../STATUS.md) → 本文件

> **所有 agent 修改本目录前，必须先读 [../AGENTS.md](../AGENTS.md) 和本文件。**

## 本目录职责

本目录是 SharedSignals 的统一数据采集层。所有现役外部数据源由 cron wrapper 调用对应 collector/脚本，采集成功必须直接写入 SQLite read model。

## 核心架构

```
cron/collectors.sh          → tushare/sync_daily.py
cron/tushare_low_frequency_collect.sh → tushare/sync_daily.py --tier P7_low_frequency
cron/crypto_collect.sh      → crypto/binance_collect.py
cron/pm_collect.sh          → polymarket_collect.py
cron/cn_futures_5min.sh     → tools/collect_cn_futures_5min.py
```

## 关键文件

| 文件 | 职责 |
|------|------|
| `base.py` | Collector 基类：定义 `collect()` 接口、错误处理、重试策略 |
| `models.py` | 数据模型：CollectionResult、HealthStatus 等 |

### 子 Collector

| 目录 | 市场 | 数据源 | 关键文件 |
|------|------|--------|----------|
| `tushare/` | A股/港股/美股/期货/汇率 | Tushare API | `collector.py`, `sync_daily.py`, `config.yaml` |
| `crypto/` | Crypto | Binance Public API | `binance.py`, `binance_collect.py`, `config.yaml` |
| 根层 `polymarket_collect.py` | 预测市场 | Polymarket Gamma API | `polymarket_collect.py` |

### RSS/RSSHub 退役状态

RSS/RSSHub 旧 collector 代码已删除。当前主服务器不把 RSS/RSSHub 当作现役 collector。恢复事件采集前必须作为新的 SharedSignals collector 重新设计调度、数据库归属、直接入库、健康检查和回滚方案，不得从 MarketGraph 或旧 RSSCollector 恢复旧采集。

## 修改规则

1. **新增 Collector**：
   - 继承 `base.py` 的 `Collector` 基类
   - 实现 `collect()` 方法，返回 `CollectionResult`
   - 在子目录添加 `config.yaml`（API 配置、限速参数等）
   - 在 `cron/` 添加受 flock 保护的 wrapper，并补 `tests/test_capability_coverage.py`
2. **输出目标**：collector 必须直接写 SQLite read model；非空采集写入 0 行必须失败并进入 watchdog/health_sla
3. **错误处理**：所有 collector 必须优雅处理 API 限频、超时、空返回，并把失败写入 `market_ingest_runs` / cron log
4. **数据不分析**：collector 只负责采集、去重、存储，不做任何投资分析或信号生成
5. **不碰资金**：本目录代码不涉及任何交易执行、资金操作或账户管理
6. **旧调度已退役**：通用调度器、文件注册表、文件 staging bridge、parquet loader 均已删除；不得恢复为生产入口
7. **输出给外部 agent**：collector 只负责增量写库；外部 agent 必须经 HTTP API/reader 读取数据库结果，不得直接调用 collector、provider SDK 或 staging 文件。

## 运行方式

```bash
# A股/期货/Tushare tiers
cron/collectors.sh --tier P0_trading_5min
cron/tushare_low_frequency_collect.sh

# Crypto / PM
cron/crypto_collect.sh
cron/pm_collect.sh

# 环境变量
SHAREDSIGNALS_ROOT=/opt/investment/SharedSignals
COLLECTOR_INTERVAL_SEC=60  # 循环间隔
```
