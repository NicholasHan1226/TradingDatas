# 2026-08-16 Crypto data-plane incident lessons

**状态：** historical record。本文保留根因和复发防线，不证明当前 release、service、timer
或 dataset 健康；这些必须由本轮服务器、receipt 与认证 API readback 判断。

## 1. Read-model snapshot 与 WAL sidecar

**现象：** 回填并发写入期间，catalog/query 偶发 `503`，并出现 receipt database sidecar
不可读或 snapshot epoch 不一致。

**最终根因：** 一次性去重脚本执行 `PRAGMA journal_mode=WAL`，将 read-model 持久切换为
WAL；并发写入时 `-wal/-shm` sidecar 的短暂状态触发了严格的 snapshot 校验。

**处置与防线：** 恢复 rollback journal、截断 WAL sidecar，并保留有界 snapshot 重试与读锁
等待。一次性修复脚本不得改变数据库的持久 journal mode；中间诊断不作为长期事实，最终根因
以可复现运行证据修正。

**追溯：** `719d81f`、`148ecaf`、`39b0d25`、`352e832`。

## 2. OI metrics dump 的逻辑重复 identity

**现象：** 认证 query 在 OI 历史上暴露 `pagination_duplicate_row_identity`。

**根因：** 日度 dump 的同一逻辑时间点被重复下载且 payload 不同；仅依赖 append-only 的
payload hash 不能保证逻辑 row identity 唯一。

**处置与防线：** 当时先备份后按确定性 row key 清理重复行。后续数据合同、去重与分页验证必须
同时覆盖 payload identity 和业务 logical identity；不要把一次 repair 当成 schema 层永久保证。

**追溯：** `ffb8e50`、`7836aec`。

## 3. Append-only 数据的瞬时 provider failure

**现象：** 每日 append-only dataset 在一次短暂 `provider_error` 后，即使最近成功数据仍满足
SLA，也会被最新 attempt 投影为不可读数小时。

**处置与防线：** 仅对 `point_in_time=append_only`、错误明确为 `provider_error` 且最近成功
数据仍在 SLA 内的情形，投影回退到最近成功 terminal receipt；结构性失败、完整性失败和过期数据
仍 fail closed。

**追溯：** `2843df7`。

## 可复用教训

1. 运行健康的权威是 receipt、受验证 SQLite snapshot 与认证 API readback，不能由日志、HTTP
   200 或旧 Markdown 推断。
2. 先保留失败 evidence，再修复；不可用删除、覆盖或一次性脚本改写历史来制造健康表象。
3. 一次性运维脚本也属于运行面变更，必须显式检查持久化副作用、回滚方式和并发读写影响。
