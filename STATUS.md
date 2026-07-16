# SharedSignals 状态

> 先读 [AGENTS.md](AGENTS.md)。本文件只保存当前可执行状态、证据分层、阻塞和下一步；历史生产与事故细节保留在 `docs/status_history_2026-07.md` 和外部 evidence 中。
>
> 最后更新：2026-07-16。当前所有结果仍是**本地候选**；GitHub、生产 checkout、生产 runtime、外部 route 和真实采集尚未完成对应发布验收，**生产未改变**。

## 当前结论

- SharedSignals 的批准定位是**独立外部多源金融数据平台**，以 Tushare 为首个主要上游，未来横向扩展公告、新闻、研报、政策、互动和客观舆情等事实数据。
- SharedSignals 不承载 opening gate、候选、策略评分、资金决策、持仓、风险、订单、成交或交易建议；不与 TradingAgent/MarketGraph 共享数据库、跨系统事务或 callback。
- 权威层已固定为 provider-neutral registry → SQLite facts + transaction-scoped **SQLite ingest receipt** → runtime/API metadata。flat JSON 只能是可重建缓存。
- 目标公共数据面固定为 `GET /v1/catalog` 与 `POST /v1/query`；新增数据源不得新增 route。`/tushare` 和现有专用 endpoint 只是待迁移兼容层。
- 首期只覆盖中国境内市场与当前账户真实有权使用的 Tushare dataset；预测市场、加密货币、港股和美股不进入首期激活/默认调度。
- REAL_TRADING、broker、真实邮件、自动扩权、生产 cron/systemd/nginx、DB migration 和不可逆删除均不在当前授权内。

## 代码与 Git 分层

- SharedSignals `origin/main` 最后核对为 `d913d32c`。
- 本地 `main` 为 `c127599`，比 `origin/main` 领先 3 个已审计设计/退役计划文档提交；tracked/index clean，`.codegraphcontext/` 保持 untracked、unstaged。
- Phase 1 主候选 worktree：`.worktrees/sharedsignals-external-data-phase1`。
- Phase 1 主候选已包含代码 checkpoint `09927f1`，并吸收 provider-neutral registry、provider outcome、atomic receipt、Task 9 Tushare authoritative receipt、Task 10 SQLite runtime projection、anti-drift 文档和 unmapped receipt 隔离修复；当前 doc-only descendant HEAD 以 `git rev-parse HEAD` 为准，未 push、未 deploy。
- 结构性作废的 flat-file authority worktree `sharedsignals-source-runtime-ledger-p0` 从未进入主线；在替代方案完成集成且 rollback evidence 齐全前只保留审计证据，不继续修补、不提前删除。

## Phase 1 当前进度

### 已完成候选

- 仓库第一批安全退役：5 份已证明无消费者的旧文档和一个未使用 impact helper 已从 Phase 1 候选删除，Git 历史可回滚。
- 目标 cron template 已收窄到境内 Beta；这只表示仓库目标模板，生产 live crontab 未修改、未验证。
- provider-neutral dataset registry、Tushare provider outcomes、versioned ingest receipts、数据+success receipt 同 SQLite transaction、terminal empty/failed receipts 和 Task 9 registry-backed sync 已进入 Phase 1 主候选。
- Task 9 精确提交：`341fd5a feat: make Tushare receipts authoritative`。

### Task 10：SQLite runtime projection

- 候选已冻结为精确 14 文件，base `a100ef4`；Task 9 精确 4 文件未被修改。冻结根指纹为 `86db6493…8317`。
- 两路 fresh clean-overlay reviewer 均 PASS，P0/P1/P2=0；独立 Python 3.12 全仓分别为 `1545/1545`，Task 9+10 overlay 为 `1577/1577`。
- 独立 10 万 receipt 实测：单次 projection 约 `1.428s`、完整 verified load 约 `1.442s`；maintenance snapshot 与 writer lock 边界通过并发实证。
- 当前合同：同一 SQLite read transaction 返回 data + receipt；只做一次完整 projection；maintenance lock 覆盖 snapshot，writer open lock 只覆盖绑定/open/BEGIN/schema read；不让持续读饿死采集 writer。
- 精确 14 文件已逐字节吸收到 Phase 1 主候选，并形成本地提交 `e73c06d refactor: project source runtime from SQLite receipts`；与本轮 anti-drift 文档/测试合并后的 Python 3.12 全仓为 `1581 passed`，Ruff、compileall、`git diff --check` 通过。它仍未 push 或生产发布。

### Task 12 交叉层修复

- 最终独立验收发现一个确定性 P1：Task 9 合法 `unmapped.tushare.<digest>` terminal receipt 被 Task 10 当作全局 rogue unknown，污染所有 dataset/interface 状态；原冻结 `435acee` 因此作废。
- 本地提交 `09927f1 fix: isolate unmapped ingest receipts` 已按 TDD 收口：只有真实 registry alias miss 可生成 synthetic tombstone；已知 dataset 的 binding/adapter/table 故障保留 owner identity 并 fail closed；合法 tombstone 精确绑定 provider/API/digest/adapter/status/error/count/window/UUID/time/envelope/receipt ID，分类不依赖当前 dataset 或未来 onboarding；所有形似但不完整的 unknown receipt 继续 fail closed。
- 当前候选定向 `244 passed`、Python 3.12 全仓 `1593 passed`，精确 Ruff、collector 既有 E701 例外、`git diff --check` 全绿；fresh 独立 reviewer PASS（P0/P1=0）。这仍只授权 local main fast-forward，不能代替 GitHub 或生产验收。
- Phase 1 不新增全局 unmapped audit API 字段。SQLite tombstone 继续保留为 durable evidence；未来若公开全局 audit bucket，必须另行定义 latest/resolution 语义，避免历史事件永久把整体状态置红。

### Task 11：核心文档与防漂移门禁

- `AGENTS.md`、`README.md`、`STATUS.md`、目标 API 合同、registry/receipt/onboarding/recovery 文档和 Phase 1 规格已统一到外部数据平台边界。
- 三个会把旧 `P0-P7`、5 分钟交易口径、`stock_master` 专用公共路由和旧扩源文件重新写回核心文档的测试已改为新 authority/fixed-API/legacy-compatibility 契约。
- 旧 external-agent prompt、Tushare activation backlog 与 event lane 已明确标注为 migration inventory/compatibility，而不是目标 API、runtime authority 或生产可用证明。
- 文档定向门禁、Task 9+10+文档 union 全仓 `1581/1581`；fresh 独立 anti-drift 文档审阅 PASS（P0/P1/P2=0），对应本地提交为 `afa7f3b` 与 `435acee`。

### 未完成

- Phase 1 候选到 local main 的精确 fast-forward/readback。
- Phase 2 固定 `GET /v1/catalog`、`POST /v1/query`、signed keyset cursor、同 snapshot metadata/query 和 `/tushare` compatibility adapter。
- Phase 3 境内 Tushare entitlement probing、registry-driven cadence scheduler、throttled backfill 与频率实证。
- Phase 4 受邀账户 tenant credential、dataset/field/lookback policy、rate/concurrency、persistent quota、usage ledger、revocation 和 runbook。
- Phase 5 GitHub readback、安全生产发布、外部 route、真实采集、回滚和稳定性观察。

## Acceptance Freeze

- 候选冻结后只能按已批准合同验收；不得临时扩大产品范围、威胁模型或商业能力。
- 只有当前范围内、确定性可复现、真实影响数据正确性/隔离/可用性的 P0/P1 才能阻断；其它发现进入 P2/backlog。
- same-UID malicious process 不属于当前受邀 Beta 合同；协作进程的意外 race、锁泄漏、数据/receipt 不一致和 writer starvation 属于当前合同。
- 连续两轮出现新的结构性 P1 时必须停止叠加 validation，回到规格/架构裁决。
- 测试、manifest 和 reviewer PASS 只证明候选；不能代替 main/GitHub/production/runtime/external route/真实数据。

## 退役边界

以下内容不属于目标平台，但当前仍可能存在代码或消费者依赖：opening gate、Green Gate 邮件、交易式 blocking、研究关系/impact、旧专用 endpoint、旧 cron/patrol/heal、DuckDB critical path、Crypto/PM/HK/US 默认调度。

处理顺序固定为：

```text
提供 registry/query 替代
→ 迁移消费者
→ 标记 deprecated 并观测
→ 证明无 import/test/doc/cron/service/external consumer
→ safe-delete
```

禁止为了“清洁”直接删除数据库、数据、Journal、ledger、history、evidence、rollback worktree 或未知消费者仍在使用的入口。

## 下一步

1. 只把 fresh PASS 候选 fast-forward 到 local main，核对 tracked/index clean 并保留 `.codegraphcontext/`；不得使用 `git add .`，不得自动 push/deploy。
2. 从 local main fresh readback Phase 1 commit chain、核心文档和定向 smoke；本地 PASS 不能替代 GitHub/生产。
3. Phase 1 local main PASS 后实现固定 `/v1/catalog`、`/v1/query` 和 `/tushare` compatibility adapter。
4. 再并行推进境内采集调度与受邀账户治理；共享合同只能有一个 owner。
5. 所有本地/GitHub 证据齐全后才进入 fresh safe-release；生产 readback 与真实采集稳定性通过后才可声明 Beta 可用。

## 验证入口

```bash
uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q
uv run --python 3.12 --with-requirements requirements.txt ruff check \
  tests/test_data_platform_docs.py tests/test_capability_coverage.py \
  tests/test_capability_scan.py tests/test_source_expansion_priority.py
uv run --python 3.12 python -m compileall -q .
git diff --check
```

全仓 Ruff legacy baseline 当前非零，不能报告为全仓绿；Phase 1 只按冻结精确路径执行
Ruff，完整清单和 `collectors/tushare/collector.py:E701` 既有归因见实施计划 Task 12 Step 4。

每次汇报必须分开：本地 worktree、local main、origin/GitHub、production checkout、production runtime、external route、真实 dataset receipt/API response。
