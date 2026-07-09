# SharedSignals 状态

> **给所有 agent：** 读完 [AGENTS.md](AGENTS.md) 后读本文件。这里只保留当前可执行状态、验证入口、风险边界和下一步。历史长记录已归档到 [docs/status_history_2026-07.md](docs/status_history_2026-07.md)。
>
> **变更规则：** 改采集源、API、频率、read model、治理规则或生产边界后，必须同步更新本文件和对应文档。
>
> 最后更新：2026-07-10（外部账号分层与 `signals.tradingagent.cc` 入口状态复核；SharedSignals API/账号已就绪，但 `tradingagent.cc` Cloudflare DNS/Tunnel 写权限仍未到位）

---

## 一、当前结论

- **系统角色**：SharedSignals 是共享数据采集、整理、增量入库和只读 API 输出层；不做 alpha、买卖方向、仓位、下单、资金、账户或执行回执。
- **交易边界**：支持分钟级/5 分钟级交易供数，不承诺毫秒级 HFT、订单簿撮合或执行系统能力。
- **现役数据源**：Tushare、Binance、Polymarket、CNFutures；RSS/RSSHub/Tavily/DeepSeek 不作为现役生产 collector。
- **存储边界**：SQLite read model 是权威读模型；DuckDB 是分析镜像；CSV/NDJSON/旧目录只能作为历史迁移或审计材料，不能作为生产读取兜底。
- **仓库数据边界**：仓库不跟踪生产数据库、旧 CSV/NDJSON、Parquet 冷归档或样本数据；冷归档样本、CSV bridge、旧 query_router/archive_manager 不作为当前 read path 或交接材料，且由测试门禁阻止恢复。
- **外部消费边界**：TradingAgent、MarketGraph 和外部 agent 必须通过 SharedSignals HTTP API 读取，不得绕过 SharedSignals 直接调用 provider、SQLite 文件、CSV/NDJSON 或兄弟仓库内部文件。
- **外部域名状态**：Wangzhi/internal tier 这类外部账号已在 SharedSignals 侧可控；正式域名 `https://signals.tradingagent.cc` 仍不可用。当前可操作的 Cloudflare origin certificate 只能写 `vorra.cc` DNS zone，不能写 `tradingagent.cc`；不要用该证书创建 `signals.tradingagent.cc` 路由，需拿到 `tradingagent.cc` zone 的 DNS Edit + Tunnel Edit 权限后再执行。

## 二、生产频率

| 数据 lane | 生产频率 | 说明 |
| --- | --- | --- |
| A-share P0 intraday | 交易时段 5 分钟 | 只保留分钟行情热路径；优先池来自 SharedSignals read model 或显式环境变量 |
| CNFutures intraday | 日盘/夜盘 5 分钟 | 独立 `cn_futures_5min` wrapper；不走 A-share P0 循环 |
| Crypto | ticker 30 分钟；1d support bars 每 6 小时 | 不与 A-share/Futures 5 分钟热路径抢写 |
| Polymarket | markets/prices 30 分钟 | 新加坡 relay 优先，本地 Mihomo/Clash 兜底；默认不直连 |
| Tushare daily/reference/fundamentals/macro | 盘后、晚间、盘前或低频窗口 | P1-P7 分层调度；低频周/月线独立 weekly wrapper |
| Events/news/announcements/reports | 30 分钟 full event lane；`news/major_news` 15 分钟 supplemental pilot | 写入 `market_events`，不生成交易信号 |
| DuckDB mirror/capability scan | 避开中国交易高峰 | DuckDB 不是 5 分钟交易 read path |

## 三、API 与扩展治理

- **HTTP surface**：`/health`、`/capabilities`、`/agent_config`、`/source_status`、`/cache/status`、`/cache/invalidate`、`/market_data`、`/realtime_5min`、`/is_trading_day`、`/events`、`/sentiment`、`/fundamentals`、`/reference`、`/industry`、`/macro`、`/capital_flow`、`/crypto`、`/pm_markets`、`/pm_prices`、`/associations`、`/impacts`、`/tushare`。
- **外部 agent 合同**：`GET /agent_config`，当前合同版本 `1.1.36`。
- **数据源治理状态**：`GET /source_status`，检查 API surface、频率标签、Tushare 115/115 active、API/module catalog、planned 扩源队列、cron、health SLA 和 capability registry。
- **Green Gate 日报**：每日 08:10 `cron/green_gate_report.sh` 发送系统邮件到 `soc@coze.email`，口径复用 `/source_status` 并追加 `data_artifact_guard`。green 时不需要 Nicholas 每天人工追问接口、数据源、频率和扩源边界；yellow/red 时先看邮件列出的检查项。
- **新增数据源规则**：先进入 [config/source_expansion_priority.yaml](config/source_expansion_priority.yaml) planned 队列，再按 [config/api_module_catalog.yaml](config/api_module_catalog.yaml) 映射模块、表和默认 API；通过 collector、直接入库、API 可读、SLA、限流、降级、测试和 pilot 后才能 scheduled。
- **新增 API 规则**：默认复用现有 API。只有新查询形态、独立 SLA/auth、分页/限流模型或明确新数据产品无法由现有 endpoint 表达时，才新增 endpoint。

## 四、当前风险与未完成项

- **外部域名未完成**：`signals.tradingagent.cc` 仍无公共 DNS 记录；`curl https://signals.tradingagent.cc/health` 会在 DNS 层失败。SharedSignals 生产 API 本机 `/health` 正常，`/agent_config` 仍标记 `access_status=pending_cloudflare_route`。
- **B1 扩源仍是 planned**：SEC EDGAR 已完成生产手动 pilot（2 个 CIK、6 条 filing metadata 写入 `market_events`、16 条 selected companyfacts 写入 `market_factors`，`/events` 与 `/fundamentals` API 可读），用于补 Tushare 没有的美国官方披露/结构化事实；但仍未装 cron。Tushare 已覆盖的公告/新闻/研报不重复补，官方交易所公告仍保持 planned。所有 B1 源必须继续先跑 pilot 和治理验收，不得直接装 cron。
- **`reader.py` / `api_server.py` 仍偏大**：当前测试覆盖通过，但长期应继续按市场数据、事件、fundamentals/macro、cache/auth 分层拆小。
- **历史兼容层仍存在**：`bridge/marketgraph_marketdata_db.py` 仅作兼容辅助，不是生产采集入口；未来拆独立服务器前应继续减少跨仓兼容依赖。
- **生产健康以 live 结果为准**：本地缺少生产 `health_sla.json` 时，`tools/source_governance_monitor.py --json` 可能显示 red；真实状态以生产 `/source_status` 和每日摘要为准。

## 五、验证入口

本地常用验证：

```bash
./.venv/bin/python3 -m pytest -q
./.venv/bin/python3 tools/source_governance_monitor.py --json
./.venv/bin/python3 tools/green_gate_report.py --dry-run --to soc@coze.email
```

生产常用验证：

```bash
curl -s http://127.0.0.1:8082/health
curl -s http://127.0.0.1:8082/source_status
curl -s http://127.0.0.1:8082/agent_config
```

生产状态口径需要分开汇报：

- 本地工作树 / GitHub main / 生产文件 / 生产 runtime / 真实 API live response。
- 不能用“测试通过”替代 `/health`、`/source_status` 和真实 API 响应。

## 六、下一步

1. [ ] B1 official event follow-up：观察 SEC EDGAR pilot 行 1-2 个交易日；若 `/events` 查询、SLA 和 Green Gate 继续正常，再评估 30-60 分钟 filing metadata pilot cron 或优先做官方交易所公告 collector。
2. [ ] 继续拆小 reader/API：优先抽离无状态配置读取和 response helpers，再逐步拆业务 endpoint。
3. [ ] 生产观察：继续看 `/source_status` 和 Green Gate 日报是否保持 green，尤其是 `api_module_catalog`、`health_sla_summary`、`capability_registry` 和 `data_artifact_guard`。
