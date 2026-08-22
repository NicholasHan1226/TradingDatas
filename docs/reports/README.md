# Historical decisions and reports

本目录只保存值得人工追溯的一次性事故、生产验收和迁移复盘；它们不是当前运行权威，也不能
替代服务器 readback、SQLite receipt 或认证 `catalog/query`。

长期、会约束未来实现的决定放在 [`../adr/`](../adr/)：

- [`ADR-0010`](../adr/ADR-0010-tradingdatas-clean-slate.md)：clean-slate 数据平台边界；
- [`ADR-0011`](../adr/ADR-0011-quicksync-observed-response-contracts.md)：QuickSync
  已观测响应差异的最小合同；
- [`ADR-0012`](../adr/ADR-0012-deploy-first-evidence-promotion.md)：deploy-first 与
  evidence-driven promotion。

当前已归档的经验复盘：

- [`2026-08-16-crypto-data-plane-incidents.md`](2026-08-16-crypto-data-plane-incidents.md)：
  read-model snapshot、WAL/sidecar、逻辑重复 identity 和 append-only 失败投影的根因与防线。

普通代码或文档变化不再复制到本目录，直接以 Git history 追溯。
