# TradingDatas 文档规则

## 唯一入口

1. `../AGENTS.md`：产品边界与开发规则；
2. `../README.md`：产品入口；
3. `../ROADMAP.md`：阶段与停止线；
4. `../STATUS.md`：当前事实；
5. `ARCHITECTURE.md`：架构与权威数据流；
6. `API.md`：固定 catalog/query 合同；
7. `OPERATIONS.md`：运行、回填、发布和回滚；
8. `adr/ADR-0010-tradingdatas-clean-slate.md`：重命名和旧系统退役决策。

## 规则

- 文档只使用 TradingDatas 作为当前产品名。
- 旧 SharedSignals 名称只允许出现在迁移/删除清单中，不得成为当前接口、目录或运行时名称。
- 当前公共数据面只有 `GET /v1/catalog` 和 `POST /v1/query`。
- 不记录 opening gate、交易、资金、持仓、风险、Crypto、预测市场、DuckDB 或旧专用 route 为当前能力。
- 临时测试数字写入 `STATUS.md`；长期合同写入架构、API 或运维文档。
- Git 历史足以追溯已删除旧计划；当前树不保留重复历史说明。
