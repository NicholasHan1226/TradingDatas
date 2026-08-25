# 2026-08-25 Catalog 投影性能与误报告警修复

## 问题

管理端数据浏览首次加载曾在 Tunnel 恢复后的冷态达到约 45 秒；链路稳定后的生产页面复测仍为
6.6–9.3 秒。生产 SQLite 有 68,262 条 `market_ingest_runs`、134 个 source；最近窗口实际返回
5,862 条 receipt。SQL 窗口查询本身约 0.18 秒，主要耗时来自把这 5,862 条 receipt 逐一提交给
192 个数据集投影，以及在页面渲染前串行等待 catalog 与采集状态。

同一有界窗口还导致 10 个大型 execution 被误报为 `receipt_execution_inconsistent`：每个数据集
只保留最近 100 条 receipt，而真实物理调用序号可达 1,160。合法的连续后缀因此从 2、7、497
或 1,061 等非零序号开始，旧校验器却要求可见集合必须从 0 开始。

## 修复

- 最近 receipt 在一次扫描后按 envelope source 与 payload dataset claim 建立相关行索引；每个
  数据集只校验与自己相关的行。
- 有界执行窗口允许非零起点的连续物理调用后缀；重复、内部缺口、重试错位、context 漂移和
  physical/non-physical 混合继续失败关闭。
- 不修改 SQLite、历史 receipt、Token、provider 配置、采集 service/timer 或公开 API 合同。

## 候选验证

- 生产只读数据基准：共享校验缓存热态投影由约 2.4 秒降至约 0.15 秒；候选冷态完整投影约
  1.9 秒。
- 生产只读数据重放：失败数据集由 14 个降至 4 个，降级由 85 个降至 75 个；消除的 10 个均为
  连续后缀误判，没有隐藏真实 provider、storage、日期或配置错误。
- `tests/test_receipt_projection.py` 与 `tests/test_catalog_service.py`：171 项全部通过。

剩余 4 个真实失败分别为 `invalid_data_through`、`storage_failed`、`provider_error` 与
`data_through_in_future`。它们需要各自的 provider/receipt 根因修复，不属于本性能修复范围。
