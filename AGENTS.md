# SharedSignals

## 目标
统一数据采集与存储, 供研究线和交易线共享读取。

## 边界
- 做什么: 采集行情/事件/基本面/资金/宏观, 去重入库
- 不做什么: 不分析, 不分类, 不做交易决策
- 存储: SQLite (marketdata.sqlite 81MB) + CSV + NDJSON staging

## 现状
- 行情: Tushare(14接口)/Binance(4)/PM(3) → SQLite + CSV缓存
- 事件: RSS(883源)+Tavily+agents → staging NDJSON → runtime_bridge → CSV
- 基本面: Tushare财务接口 (按需实时调)
- staging: 8 streams (collection_runs/sentiment_signals/event_candidates/...)

## 依赖
- 读取: 外部API (Tushare/Binance/PM/RSS/Tavily/DeepSeek)
- 输出: SQLite + CSV → MarketGraph和Tradings读取

## 巡查自愈系统 (patrol + heal)

### patrol.py — 10min巡检
检查6个维度:
- source_health: 每个source最近采集时间, 超时→stale (只标记已采集过的源)
- data_freshness: marketdata.sqlite最新trade_date, 超过1天→stale
- staging_backpressure: pending NDJSON文件数, >100→backpressure
- sqlite_health: WAL文件大小(>100MB→checkpoint), 锁等待→告警, 完整性检查
- disk_usage: >80%告警, >90%停止采集
- field_drift: 实际CSV字段 vs expected_fields不匹配→告警

输出: JSON {checks: [{name, status, value, threshold, alert}], overall_score}

### heal.py — 自愈动作
- source down → 切换备用源(source_failover.py)
- 数据缺失 → 触发补采(重跑marketdata_db --ingest)
- staging积压 → 强制运行runtime_bridge --apply
- SQLite锁 → 等待5s重试, 清理WAL(PRAGMA wal_checkpoint)
- 磁盘满 → 清理旧archive(>30天Parquet), >90%发出停止采集信号
- 字段漂变 → 更新expected_fields.json + 告警
- 自愈失败 → 紧急告警(emergency_alerts.log) → 人工介入

### memory/ — 闭环记录
- patrol_history.jsonl: 每次巡查结果
- heal_actions.jsonl: 每次自愈动作
- patterns.jsonl: 发现的模式(周复盘迭代规则)
- failover_history.jsonl: 源切换历史

### source_failover.py — 源故障切换
预配置FAILOVER_MAP: 主源↔备用源映射, 覆盖A股/港股/美股/Crypto/PM/全球新闻/宏观等源。

## 文件结构
- collectors/ — 各数据源采集器(软链)
- storage/ — schema文档 (当前SQLite, 计划DuckDB)
- bridge/ — staging→CSV归并桥(软链)
- reference/ — 参考数据 + expected_fields.json
- memory/ — 采集层记忆 + 巡查/自愈历史
- staging/ — 本层staging缓冲
- patrol.py — 10min巡查 (6维度健康检查)
- heal.py — 自愈引擎 (failover/backfill/merge/checkpoint/cleanup/drift)
- source_failover.py — 源故障切换映射
- logs/ — 紧急告警 (emergency_alerts.log)
