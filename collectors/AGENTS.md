# TradingDatas provider adapters

> **阅读顺序：** [../AGENTS.md](../AGENTS.md) → [../STATUS.md](../STATUS.md) → 本文件

> **所有 agent 修改本目录前，必须先读 [../AGENTS.md](../AGENTS.md) 和本文件。**

## 本目录职责

本目录只实现 **provider-level transport adapter**：调用已批准上游、保留其原始 outcome/rows、按 registry 的技术合同写入 provider-native SQLite facts 与同事务 receipt。它不重新生产上游已有数据，也不做研究、特征或交易加工。

Tushare 是已购买的现成上游数据能力。普通 Tushare dataset 必须复用统一 `api_name + params + fields -> fields/items` transport；**不得为每个 Tushare 接口编写独立 collector**。新增 Tushare 接口只改 registry/config 和调度参数。未来自建新闻、公告、舆情等来源仅在 transport/auth/pagination 确实不同的情况下新增 provider adapter，并继续复用同一存储、receipt、metadata 和公共 API。

## 核心架构

```text
registry/config dataset binding
  → provider adapter (Tushare 首期为一个 generic adapter)
  → provider-native SQLite facts + transaction-scoped receipt
  → metadata/query service
  → GET /v1/catalog + POST /v1/query
```

cron、scheduler 和 backfill 只负责按 registry cadence 编排 dataset/window，不能拥有另一份 API allowlist、字段映射、业务表映射或 dataset-specific 调用分支。

## 关键文件

| 文件 | 职责 |
|------|------|
| `tushare/collector.py` | 唯一 generic Tushare transport adapter；普通接口不得复制它 |
| `tushare/provider_native_ingest.py` | registry 驱动的 provider-native SQLite/receipt 入口 |
| `tushare/tushare_common.py` | Tushare 通用请求/响应与凭证边界 |
| `binance/collector.py` | Binance public spot 的 provider-level 只读 adapter；不得加入账户、私钥或下单能力 |
| `binance/usdm_collector.py` | Binance public USDⓈ-M 永续 funding rate / open interest 的 provider-level 只读 adapter（transport host `fapi.binance.com` 与现货不同）；同样不得加入账户、私钥或下单能力 |
| `binance/oi_dump_collector.py` | Binance public USDⓈ-M 日度 dump 的 provider-level 只读 adapter（transport host `data.binance.vision` 批量 zip 下载，`fapi.binance.com` 被 SNI 阻断期间 open interest 的降级来源与 premium index（funding 压力代理，非 funding rate 本身）日度 premiumIndexKlines dump 来源，funding rate 无 dump）；同样不得加入账户、私钥或下单能力 |
| `firecrawl/collector.py` | Firecrawl web 抽取的 provider-level 只读 adapter（bearer key 文件凭证，`scrape_page`/`search_news` 白名单，只声明结构化 JSON 抽取）；不得加入 crawl/interact、全文留存或情绪/摘要加工能力 |

### 子 Collector

| 目录 | 市场 | 数据源 | 关键文件 |
|------|------|--------|----------|
| `tushare/` | 首期境内金融事实数据 | Tushare API | `collector.py`, `provider_native_ingest.py` |
| `binance/` | 冻结的 Crypto spot canary 与 USDⓈ-M 永续公共只读切片 | Binance public market data | `collector.py`, `usdm_collector.py`, `oi_dump_collector.py` |
| `firecrawl/` | 境内新闻/公告/客观舆情（合同冻结，未激活） | Firecrawl web scrape/search API | `collector.py` |

预测市场、港股、美股及其历史 collector/cron 不在新代码树中。Crypto 仅允许根层合同已批准的 Binance 公共现货与同一冻结标的的 USDⓈ-M 永续 funding rate / open interest 隔离运行面；不得扩展为账户、订单、执行或共享 A 股运行面。未来新闻、公告或舆情来源按新的 provider adapter 接入，不恢复旧 RSS/MarketGraph fallback。

## 修改规则

1. **新增普通 Tushare dataset**：只改 registry/config；不得新增 Python collector、table、route、专用 fixture 或专用 query 分支。zero-code onboarding 失败即架构 FAIL。
2. **新增 provider**：只有 transport/auth/pagination 与现有 adapter 真正不同才允许新增 provider-level adapter；必须先冻结 provider-neutral 输出、资源预算、凭证防泄漏和回滚合同。
3. **无损输出**：provider 返回的全部 key/value 原样保存在 `payload_json`；未知字段和类型漂移只标记 quality/degraded，除硬 admission failure 外不得丢行或改值。
4. **事务事实**：数据和 success receipt 同 SQLite transaction；empty/failed 写 terminal receipt；provider failure 不能伪装为 empty。合同正确时的 empty / `provider_error` 是外部事实，不是新增 collector、cadence class 或 VIP transport 的理由；见 `docs/OPERATIONS.md`「Datas PM 接入口径」。
5. **数据不分析**：不产生 feature、factor、alpha、候选、预测、资金、持仓、风险、订单或建议；事实型资金/持仓排名仍只是 provider payload。
6. **API 隔离**：外部消费者只能经 `GET /v1/catalog` 和 `POST /v1/query`；不得直连 provider、collector、SQLite 或 staging 文件。
7. **首期市场**：只激活中国境内且当前账户确有权限的数据集；根层合同明确批准的 Binance 公共现货与 USDⓈ-M 永续公共只读 canary 例外，必须保持独立 release、SQLite、loopback API 和 timer。预测市场、港股和美股保持 paused/excluded。
8. **调度安全**：安装或修改 cron/systemd 属于生产变更，必须另做 fresh inventory、锁/预算/回滚验收；不得在普通 onboarding 中顺手增加 cron。

## 运行方式

生产运行命令以 registry-driven runner 与 `docs/OPERATIONS.md` 为准。任何文档或代码若要求为新 Tushare API 新增 tier、wrapper 或 collector，应停止并回到根层产品合同修正。
