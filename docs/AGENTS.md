# SharedSignals Docs — 文档导航

> **阅读顺序：** 先读 [../AGENTS.md](../AGENTS.md) → [../STATUS.md](../STATUS.md) 了解规则和当前状态，再按需查阅本目录文档。

## 文档分类

### 活跃的参考文档（反映当前架构）

| 文件 | 用途 |
|------|------|
| [../API_CONTRACT.md](../API_CONTRACT.md) | SharedSignals 当前对外 API 契约（reader 函数、数据格式、生产边界） |
| [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | 基础设施说明 |
| [repo_structure.md](repo_structure.md) | 仓库结构说明 |

`docs/API_CONTRACT.md` 是 `tools/capability_scan.py` 生成的历史能力快照；如需刷新，运行 capability scan 生成新快照。当前生产 API 边界以根层 `API_CONTRACT.md`、`STATUS.md`、`/health` 和 `/capabilities` live 输出为准。

## 规则优先级

1. [../AGENTS.md](../AGENTS.md) — SharedSignals 总规则（最高优先级）
2. 本目录参考文档（补充背景和交接说明）
