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
9. `AUTHORITY_AND_HISTORY.md`：事实权威与历史保留规则；
10. `reports/`：日期化事故、验收和迁移复盘。
11. `design/public-data-product-system-v1.md`：公共数据目录、Cookbook、套餐/加购和前端设计开发合同。
12. `AGENT_INTEGRATIONS.md`：Claude、Codex、OpenClaw、Hermes 与其它 Agent 的单一接入提示词、密钥边界和前端验收合同。

## 规则

- 文档只使用 TradingDatas 作为当前产品名。
- 旧 SharedSignals 名称只允许出现在迁移/删除清单中，不得成为当前接口、目录或运行时名称。
- 当前公共数据面只有 `GET /v1/catalog` 和 `POST /v1/query`。
- 公共网站只销售和解释原始金融数据。`Use Cases` 与 `Cookbook` 只能教授查询、对齐、连接、清洗和验证方法；不得发布平台研究结论、因子、Alpha、收益、胜率、推荐或交易信号。
- 示例图表、样本结果和数据组合必须标明数据集、窗口、方法、限制及 synthetic/observed 身份；它们不是 runtime、完整性、授权或生产可用证据。
- 不记录 opening gate、交易、资金、持仓、风险、预测市场、DuckDB 或旧专用 route 为当前能力。Crypto 只可在独立 Binance 运行面合同中记录为隔离的只读 provider；它不改变公共 API、也不是交易能力。
- 临时测试数字写入 `STATUS.md`；长期合同写入架构、API 或运维文档。
- Git 历史足以追溯已删除旧计划；当前树不保留重复历史说明。
- 接口接入与采集成功口径以 `OPERATIONS.md`「Datas PM 接入口径」为准：empty ≠ success；vendor 晚发/缺行/限频/文档≠现实/`provider_error` 是外部 blocker，不计入未完成，也不冻结下一可接接口。
