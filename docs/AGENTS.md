# SharedSignals Docs — 文档导航

> 阅读顺序：[../AGENTS.md](../AGENTS.md) → [../STATUS.md](../STATUS.md) →
> [Beta 设计规格](superpowers/specs/2026-07-15-sharedsignals-external-data-platform-beta-design.md)。
> 根层规则与设计规格冲突时先停止开发并修正文档，不允许选择更方便的旧表述继续实现。

## 权威文档

| 文档 | 权威范围 |
| --- | --- |
| [../AGENTS.md](../AGENTS.md) | 产品边界、权威层、防漂移与发布红线 |
| [../STATUS.md](../STATUS.md) | 当前候选、Git/生产分层、阻塞和下一步 |
| [Beta 设计规格](superpowers/specs/2026-07-15-sharedsignals-external-data-platform-beta-design.md) | 外部数据平台目标合同、首期范围、固定 API、Beta access |
| [Phase 1 计划](superpowers/plans/2026-07-15-sharedsignals-phase1-registry-receipts-retirement.md) | registry/receipt/退役基础实施与验收 |
| [../API_CONTRACT.md](../API_CONTRACT.md) | 目标 `/v1` 合同与 legacy compatibility surface；不能把 legacy 路径当成未来扩源模式 |
| [query_service.md](query_service.md) | Phase 2 provider-neutral catalog/query 请求、分页、状态、错误与访问限制合同 |
| [dataset_registry.md](dataset_registry.md) | registry authority、字段、provider onboarding 和兼容 alias |
| [ingest_receipts.md](ingest_receipts.md) | SQLite fact/receipt 原子性、terminal receipt、runtime projection |
| [data_source_onboarding.md](data_source_onboarding.md) | 新 provider/dataset 的端到端准入清单 |
| [sqlite_recovery_runbook.md](sqlite_recovery_runbook.md) | SQLite 权威库的 fail-closed 诊断与恢复流程 |

## 支持与历史文档

- `market_capability_matrix.md`：迁移期能力盘点；configured/allowlisted 不等于 entitled、observed、fresh 或 queryable。
- `status_history_2026-07.md`：历史生产/事故事实，只作追溯。
- `external_agent_api_prompt.md` 与机器配置：当前 legacy 接入材料；Phase 2/4 完成前不能称为最终 Beta 合同。
- `tushare_activation_backlog.md` 与 `event_lane.md`：旧调度/专用 endpoint 迁移盘点；不能作为 registry、运行状态或扩路由依据。
- DuckDB、旧 endpoint、旧 cron、opening/readiness、研究关系和交易式治理文档只可作为迁移/退役证据，不是新开发入口。

## 文档防漂移规则

- 目标公共数据面固定为 `GET /v1/catalog` 与 `POST /v1/query`；现有专用路径仅是迁移期 compatibility surface。
- 新增 provider/dataset 只能扩 registry/adapter/storage/receipt/query metadata；不得新增公共 route。
- 文档不得把 opening gate、候选、策略、资金、持仓、风险或交易决策归入 SharedSignals。
- 文档不得把 flat JSON、邮件、dashboard、HTTP 200、allowlist 数量或 DuckDB mirror 写成数据 authority。
- 目标、当前实现、GitHub、生产 runtime、external route 和真实数据必须分别标注；不得用“已实现”概括全部层级。
- 长期文档不记录临时测试数字；当前数字写 STATUS/evidence，历史数字写 history。
