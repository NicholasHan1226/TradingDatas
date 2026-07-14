# A 股 5 分钟供数 / Opening Gate 本地接手包

## 范围

- 基线：SharedSignals `main` 的 `ccff5c8`。
- 隔离分支：`codex/sharedsignals-ashare-5min-gate-v2`。
- 只修复 P0 5 分钟采集与 `morning_first_sample` / `afternoon_resume` / `close_check` 同分钟运行时的短暂入库竞态。
- 不改变 P0 provider、active universe、批量大小、SQLite schema、cron 时点或 API 契约。

## 行为

- Opening gate 首次读取 green 时立即返回。
- 只有 SQLite 与 `health_sla` 均为 green、当前 phase 的 A 股样本是唯一 red 检查时，才每 5 秒重读一次，窗口最多 20 秒。
- SQLite 或 `health_sla` 失败不重试，继续 fail closed。
- 每次判断使用同一个 aware UTC 决策边界；`bar_time` 结合 `trade_date` 与 `Asia/Shanghai` 转为确定瞬间，`collected_at` 必须显式带时区。bar 或 collected 时间最多允许领先决策边界 5 秒；超出上界、naive `collected_at` 或无法解析/日期冲突的时间均不计为有效样本。
- shell 总超时默认从 20 秒调整为 30 秒，为 20 秒重评窗口保留进程启动和原子落盘余量。
- JSON artifact 新增 `attempt_count` 与 `retry`，便于区分无需重试、窗口内到达、不可重试失败和窗口耗尽。

## 本地证据

```bash
/Users/nicholashan/Projects/Finance/SharedSignals/.venv/bin/python3 -m pytest -q \
  tests/test_opening_gate.py \
  tests/test_tushare_sync_daily.py \
  tests/test_health_check.py \
  tests/test_source_governance_monitor.py
```

预期：`77 passed`（原 75 项加 future `collected_at`、future `bar_time` 两个决定性负例；负例同时覆盖 naive/invalid fail-closed）。

## 未执行与接手门禁

- 未访问服务器或真实数据源。
- 未修改数据库、已安装 cron 或生产 artifact。
- 未 commit、push、deploy，也未修改 SharedSignals `main`。
- 集成方应先审计精确 diff，再在授权范围内运行完整测试；生产验证必须另行核对 runtime 文件、下一轮 P0 入库、opening-gate artifact 与 API readback，不能用本地测试替代。
