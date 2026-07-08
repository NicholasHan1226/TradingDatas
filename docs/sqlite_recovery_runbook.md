# SharedSignals SQLite 主库损坏恢复 Runbook

> **范围**：`/opt/investment/SharedSignals/runtime/read_model/marketdata.sqlite`
> **边界**：只恢复数据采集/存储层，不分析、不生成交易信号、不触发模拟/实盘执行。

## 1. 触发条件

`patrol.py` 的 `sqlite_health` 检查会先做一次只读损坏探测：

- 主库文件不存在 → `missing`
- 主库文件为空或无法打开 → `corrupt`
- `PRAGMA quick_check` 返回非 `ok` → `corrupt`
- 正常可读 → 继续检查 WAL、锁、完整性

当 `sqlite_health` 返回 `corrupt` / `missing` 时，`heal.py` 会自动进入恢复分支（默认仍受 `--dry-run` 控制，生产 cron 请按需决定是否传入 `--apply`）。

## 2. 恢复源优先级（auto）

`tools/sqlite_recovery.py` 按以下顺序选择恢复源：

1. **最近有效 SQLite 备份**
   - 搜索目录（按顺序）：
     - `{db_path.parent}/backups`（即 `/opt/investment/SharedSignals/runtime/read_model/backups`）
     - `$SHAREDSIGNALS_ROOT/backups`（即 `/opt/investment/SharedSignals/backups`）
   - 只接受满足以下条件的 `*.sqlite`：
     - 非空
     - 可正常打开
     - `PRAGMA quick_check == ok`
     - `market_assets`、`market_bars_daily` 等关键表存在且非空
2. **DuckDB mirror**
   - 默认路径：`/opt/investment/SharedSignals/data/marketdata.duckdb`
   - 如果 mirror 可用且关键表有数据，则从 DuckDB 重建 SQLite 主库
3. **无可用源**
   - 返回 `blocked_no_valid_recovery_source`，需要人工介入

## 3. 命令参考

```bash
# 默认 dry-run：预览会对默认主库做什么
python3 tools/sqlite_recovery.py

# 真正执行恢复（auto 选择源）
python3 tools/sqlite_recovery.py --apply

# 强制从 DuckDB 重建
python3 tools/sqlite_recovery.py --source duckdb --apply

# 指定自定义路径
python3 tools/sqlite_recovery.py \
  --db /tmp/bad_marketdata.sqlite \
  --duckdb /tmp/marketdata.duckdb \
  --backup-dir /tmp/backups \
  --apply

# 输出 JSON，便于被脚本/监控解析
python3 tools/sqlite_recovery.py --apply --json
```

## 4. apply 执行流程（fail-safe）

1. **只读探测**：确认主库确实 `corrupt` / `missing`（除非加 `--force`）。
2. **选择源**：按 2. 中的优先级挑选验证过的源。
3. **隔离坏库**：把原坏库及 `-wal`/`-shm` sidecar 移动到 quarantine 目录，命名为 `marketdata_corrupt_<UTC时间>.sqlite`。
4. **恢复/重建**：
   - 备份源：原子复制到主库路径。
   - DuckDB：创建临时 SQLite，写入 schema，按表从 DuckDB 批量导入，再原子替换。
5. **收尾**：对恢复后的库执行 `PRAGMA quick_check`、`PRAGMA wal_checkpoint(TRUNCATE)`，清理残留 sidecar。
6. **记录**：返回结果包含 `quarantine_path`、`source_type`、`source_path`、`recovered`、`reason`。

## 5. 与 patrol / heal 集成

- `patrol.py --check sqlite_health` 现在会返回 `corrupt` / `missing` 字段。
- `heal.py` 收到 `corrupt=True` 或 `missing=True` 时，调用 `tools/sqlite_recovery.recover(...)`。
- `heal.py` 内部有 `sqlite_recovery` 冷却窗口（默认 10 分钟窗口 + 每天最多 5 次），避免反复恢复。
- 如果恢复失败，`heal.py` 会按 `critical` 级别写入 `logs/emergency_alerts.log` 并尝试发送系统邮件。

## 6. 无源可恢复时的处理

当工具返回 `blocked_no_valid_recovery_source` 时：

1. 检查备份目录是否真的有有效 `*.sqlite`。
2. 检查 DuckDB mirror 是否存在且有数据：`duckdb /opt/investment/SharedSignals/data/marketdata.duckdb "SELECT COUNT(*) FROM market_bars_daily;"`
3. 如果两者都不可用，从离线/对象存储手工取回最近备份，放入 `$SHAREDSIGNALS_ROOT/backups/` 后重新执行 `--apply`。
4. 在修复完成前，对外 HTTP API 会按既有降级逻辑返回 `degraded`，不会现场调用外部数据源，也不会产生交易判断。

## 7. 验证清单

恢复后建议执行：

```bash
# 1. 完整性检查
python3 - <<'PY'
import sqlite3
p = "/opt/investment/SharedSignals/runtime/read_model/marketdata.sqlite"
c = sqlite3.connect(p)
print("quick_check:", c.execute("PRAGMA quick_check").fetchone()[0])
for t in ["market_assets", "market_bars_daily", "market_bars_intraday",
          "market_events", "market_factors", "market_pm_markets"]:
    print(t, c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
c.close()
PY

# 2. patrol 验证
python3 patrol.py --check sqlite_health --json

# 3. API 健康检查
curl -s http://127.0.0.1:8082/health | python3 -m json.tool
```

## 8. 限制与风险

- 从 DuckDB 重建只恢复已同步到 mirror 的数据；若同步也滞后，重建后的库可能比权威源旧。
- 备份文件本身可能也损坏；工具会跳过无法通过 `quick_check` 的备份。
- 恢复动作会替换主库文件，运行中的 API 进程可能短暂读到旧缓存；建议恢复后调用 `/cache/invalidate` 或等待缓存失效（WAL/sidecar 监听 + TTL）。
- 本工具只处理 SQLite read model，不修复上游采集器或 DuckDB 同步链路；若损坏反复出现，需排查磁盘/并发写入/部署脚本。
