# Collectors — SharedSignals 数据采集层

> **阅读顺序：** [../AGENTS.md](../AGENTS.md) → [../STATUS.md](../STATUS.md) → 本文件

> **所有 agent 修改本目录前，必须先读 [../AGENTS.md](../AGENTS.md) 和本文件。**

## 本目录职责

本目录是 SharedSignals 的统一数据采集框架。所有外部数据源（股票、Crypto、预测市场、RSS 新闻）通过统一的 Collector 接口接入，由 Orchestrator 按调度策略并行执行。

## 核心架构

```
run_collectors.sh
  → orchestrator.py (Orchestrator)
      → registry.yaml (collector 注册表)
      → base.py (Collector 基类)
      → tushare/collector.py    (A 股行情/基本面/资金流)
      → crypto/binance.py       (Binance K线/资金费率)
      → polymarket/collector.py (Polymarket 市场数据)
      → rss/collector.py        (RSS 新闻采集, 883 源)
```

## 关键文件

| 文件 | 职责 |
|------|------|
| `orchestrator.py` | 统一调度器：读 registry → 按优先级+schedule 并行执行 collector |
| `base.py` | Collector 基类：定义 `collect()` 接口、错误处理、重试策略 |
| `models.py` | 数据模型：CollectionResult、HealthStatus 等 |
| `registry.yaml` | Collector 注册表：定义每个 collector 的 enable/priority/schedule |
| `run_collectors.sh` | 入口脚本，Orchestrator 持续循环模式 |

### 子 Collector

| 目录 | 市场 | 数据源 | 关键文件 |
|------|------|--------|----------|
| `tushare/` | A股/港股/美股/期货/汇率 | Tushare API | `collector.py`, `sync_daily.py`, `config.yaml` |
| `crypto/` | Crypto | Binance Public API | `binance.py`, `config.yaml` |
| `polymarket/` | 预测市场 | Polymarket API | `collector.py`, `parquet_loader.py`, `config.yaml` |
| `rss/` | 新闻/事件 | RSSHub + 直接 RSS（生产 deferred） | `collector.py`, `feed_health_monitor.py`, `gap_filler.py`, `rsshub_route_healer.py`, `source_failover.py` |

### RSS 自愈子系统（当前 deferred）

`rss/` 目录包含 RSS 采集健康管理代码，但当前主服务器不把 RSS/RSSHub 当作现役 collector。恢复前必须补齐生产调度、数据库归属、staging/bridge、健康检查和回滚方案：
- `feed_health_monitor.py` — 883 源健康状态追踪
- `gap_filler.py` — 采集缺口自动回补
- `rsshub_route_healer.py` — RSSHub 路由故障自动切换
- `source_failover.py` — 源失效自动降级/替换

当前主服务器 RSS/RSSHub 旧顶层资产应退出 `/opt/investment` 现役目录；`/opt/investment/MarketGraphRuntime/rss_collector.db` 仅保留历史/迁移审计价值。修改 `rss/` 前先确认 live crontab、DB 归属和回滚方案，不得从 MarketGraph 恢复旧采集。

## 修改规则

1. **新增 Collector**：
   - 继承 `base.py` 的 `Collector` 基类
   - 实现 `collect()` 方法，返回 `CollectionResult`
   - 在 `registry.yaml` 注册（enable/priority/schedule）
   - 在子目录添加 `config.yaml`（API 配置、限速参数等）
2. **输出目标**：collector 写入 `SharedSignals/data/` 下的 staging 区，不直接写正式表
3. **错误处理**：所有 collector 必须优雅处理 API 限频、超时、空返回 —— 不抛异常中断 orchestrator
4. **数据不分析**：collector 只负责采集、去重、存储，不做任何投资分析或信号生成
5. **不碰资金**：本目录代码不涉及任何交易执行、资金操作或账户管理
6. **KimiWork 已退役**：collector 调度由 SharedSignals crontab/orchestrator 管理，不引用 KimiWork

## 运行方式

```bash
# 单次运行所有 enabled collector
python3 -m collectors.orchestrator --once

# 持续循环模式（crontab 入口）
collectors/run_collectors.sh

# 环境变量
SHAREDSIGNALS_ROOT=/opt/investment/SharedSignals
COLLECTOR_INTERVAL_SEC=60  # 循环间隔
```
