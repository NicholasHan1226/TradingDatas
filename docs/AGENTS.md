# SharedSignals Docs — 文档导航

> **阅读顺序：** 先读 [../AGENTS.md](../AGENTS.md) → [../STATUS.md](../STATUS.md) 了解规则和当前状态，再按需查阅本目录文档。

## 文档分类

### 活跃的参考文档（反映当前架构）

| 文件 | 用途 |
|------|------|
| [../API_CONTRACT.md](../API_CONTRACT.md) | SharedSignals 当前对外 API 契约（reader 函数、数据格式、生产边界） |
| [market_capability_matrix.md](market_capability_matrix.md) | 按市场说明现役数据源、接口能力、采集频率、Tushare 白名单与生产采集计划的边界 |
| [external_agent_api_prompt.md](external_agent_api_prompt.md) | 可复制给外部 agent 的 API 接入 prompt；必须保持 API-only 和 fail-closed 边界 |
| [tushare_activation_backlog.md](tushare_activation_backlog.md) | 剩余 planned Tushare 接口按市场/模块/频率分批激活计划 |
| [../config/api_module_catalog.yaml](../config/api_module_catalog.yaml) | 模块到 API/read-model 的规划目录；新增数据源先归类到模块，默认复用现有 API |
| [../config/source_expansion_priority.yaml](../config/source_expansion_priority.yaml) | 新增外部数据源横向扩展优先级；当前只表示 planned 候选，不代表生产 collector 已启用 |
| [data_source_onboarding.md](data_source_onboarding.md) | 新增数据源准入字段、产物、频率、入库/API/降级验收门槛 |
| [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | 基础设施说明 |
| [repo_structure.md](repo_structure.md) | 仓库结构说明 |

`docs/API_CONTRACT.md` 是 `tools/capability_scan.py` 生成的历史能力快照；如需刷新，运行 capability scan 生成新快照。当前生产 API 边界以根层 `API_CONTRACT.md`、`STATUS.md`、`/health` 和 `/capabilities` live 输出为准。

## 规则优先级

1. [../AGENTS.md](../AGENTS.md) — SharedSignals 总规则（最高优先级）
2. 本目录参考文档（补充背景和交接说明）
