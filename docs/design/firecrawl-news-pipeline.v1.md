# 境内新闻/公告/舆情采集管线设计（Firecrawl provider）

> 状态：Phase 0 合同已冻结（2026-08-16，基线提交 ec624f0ec494596af44ae5006cd42cad472f0b2d）。调查日期 2026-08-16。基于 TradingDatas main 分支代码实读。
> Phase 0 冻结时对草案的三处调整（均由已冻结的 registry 编译器/加载器机制强制，不改变设计语义）：
> 1. `windowed_unique_primary_key` 要求 `date_field` 以 `local_datetime_seconds` 解码且属于主键，因此 adapter 从同一解析时间戳额外派生 `published_local`（`%Y-%m-%d %H:%M:%S`，Asia/Shanghai）字段并加入主键；`published_at` 仍按设计保持 RFC3339（+08:00）。
> 2. `cn.news.flash` 主键相应为 `[source, published_local, content_uid]`（草案为 `[source, content_uid]`）。
> 3. `point_in_time: append_only` 在冻结的加载器中强制 `row_key_strategy: payload_hash`，故不采用草案的 `primary_key` 策略；同窗重抓载荷逐字节一致时去重语义不变。
> 关键已核实事实：`dataset_registry.py:248` 的 `_DATA_CLASSIFICATIONS` 目前只有 `objective_factual`；
> 非 Tushare provider adapter 先例为 `collectors/binance/collector.py`（`provider` 属性 + `collect_outcome(api_name, params, fields, *, scan_budget) -> ProviderCallOutcome`）；
> 通用 executor `collectors/tushare/provider_native_ingest.py` 本身 provider 无关（只从 `tushare_common` 引入 `ProviderCallOutcome`/`SensitiveScanBudget`）；
> provider 分发表：`tools/collect_provider_dataset.py:426-429`。

## 1. provider/adapter 切分

### 1.1 Firecrawl 与 QuickSync/Tushare 的协议差异（满足"新增 provider-level adapter"条件）

| 维度 | Tushare/QuickSync | Firecrawl |
|---|---|---|
| auth | token 文件（`TUSHARE_TOKEN_FILE`），token 在 JSON body | `Authorization: Bearer fc-...` header，key 一次性、额度制 |
| 请求形状 | `api_name + params + fields -> fields/items` 行集 | `POST /v2/scrape {url, formats}` → 单页对象；`POST /v2/search {query, sources, scrapeOptions}` → `data.web[]/data.news[]` |
| 分页 | offset/limit | scrape 无分页（一页一调用）；search `limit<=100`，无 offset |
| 限频/额度 | 200 req/60s、并发 4（本地门禁） | credit 制：scrape 1 credit/次、search 2 credits/次；并发按 plan；一次性 key 总额度有限 |
| 响应语义 | 结构化行 | 页面 markdown + 可选 LLM json 抽取 |

结论：transport/auth/pagination 协议真实不同，按根 AGENTS.md 允许新增一个 provider-level adapter。**只允许一个** `collectors/firecrawl/collector.py`，所有源共用；源差异全部进 registry/config。

### 1.2 新 adapter 合同（对齐 Binance 先例）

- `provider_transport.py` 新增 `FIRECRAWL_DATA_PROVIDER = "firecrawl"`、`FIRECRAWL_TRANSPORT_SERVICE = "firecrawl_web_scrape_api"`、endpoint `https://api.firecrawl.dev/v2`，profile 含 `credential_mode: "bearer_key_file"`、串行、`redirects_allowed: False`、profile_sha256 自动派生。
- `FirecrawlWebCollector.collect_outcome(api_name, params, fields=None, *, scan_budget=None) -> ProviderCallOutcome`：
  - `api_name` 白名单：`scrape_page`（列表页抽取）、`search_news`（`/search` + `sources:[{type:"news"}]`）。其余拒绝。
  - `params` 完全来自 registry `request_template` 经 window 占位符替换后的结果：`url`、`extraction_schema`、`prompt`、`max_age_ms`、`timeout_ms` 等。adapter 不持有任何源 URL——URL 走 `dimension_fanout.literal_values`（架构文档已明确该机制"例如新闻来源"）。
  - 归一化：Firecrawl `data.json` 抽取结果的每个 item → 一行 dict；adapter 只做两件 provider-neutral 加工（写入 adapter 冻结合同）：
    1. `published_at` 归一为 RFC3339（Asia/Shanghai 偏移），并派生 `event_date`（yyyymmdd 分区字段）；
    2. `content_uid` = sha256(canonical_url | title | published_at)，作为主键分量与重抓去重键。
  - 凭证：`FIRECRAWL_API_KEY_FILE`（0600、仓库外），复用 `tushare_common` 的 sensitive-scan/redaction 机制；key 永不入 payload/receipt/log。
  - 错误映射：HTTP 402/429 → `rate_limited`；5xx → `provider_error`；403/401 → `permission_denied`（key 失效即 entitlement 降级，dataset 级降级不阻塞其它 provider）。
- 存储/receipt/scheduler 零改动复用：executor 仍是 `provider_native_ingest.collect_provider_native_dataset`；`tools/collect_provider_dataset.py` 的 provider 分发表加一行 `"firecrawl": FirecrawlWebCollector()`。scheduler（`run_provider_native_schedule.py:316`）当前硬编码 TushareCollector，第一期不走 scheduler（on_demand），timer 化时按 Binance 先例另立独立 service/timer 合同，属于生产变更单独门禁。

### 1.3 无损与合规的折衷（重要决策）

生产 dataset 的 Firecrawl 请求只声明 `formats: [{type:"json", prompt, schema}]`——**不请求 markdown/rawHtml**。这样 provider payload 本身就是结构化抽取结果，"无损保留"对该 payload 完整成立，同时避免在 facts 中长期存放全文，降低转载合规风险。prompt 只允许结构性字段抽取（时间/标题/链接/来源/页面上的客观计数），**禁止**让 Firecrawl 生成情绪判断、摘要改写或任何加工结论（TradingDatas 不生产 feature）。markdown 格式只允许在一次性 canary/调试中手工使用，不进入 registry 合同。

## 2. dataset 设计

统一条目骨架（参照 `config/provider_native_dataset_registry.yaml` 现有条目）：

- `domain: provider_data`、`market: CN`、`entity_type: provider_row`、`schema_version: 1.0.0`（新 dataset 从 1.0.0 起）、`timezone: Asia/Shanghai`、`data_classification: objective_factual`（雪球帖也只存标题/链接/回复点赞计数等客观事实，观点本身不作为事实；若评审要求新增分类值，属于 registry 代码改动，须显式冻结）。
- `read_model_adapter`: `provider-native-json.v1` / `provider_dataset_rows` / `provider_native_rows` / `row_key_strategy: primary_key`。
- `point_in_time: append_only`、`empty_data_policy: allowed`、`backfill_policy: provider_limited`（列表页只能看到最近 N 条，无历史回填能力）。
- `request_shape: event_or_intraday_window`，`fanout: {strategy: literal_values, parameter: url, batch_size: 1}`，`response_completeness: {strategy: windowed_unique_primary_key}`（允许单源当窗为空，越窗/缺主键行拒收）。

### 2.1 `cn.news.flash`（快讯，第一期核心）

- fields：`source`(text)、`content_uid`(text)、`published_at`(text, RFC3339)、`event_date`(text, yyyymmdd)、`title`(text)、`url`(text)、`summary`(text, nullable)。payload_json 另保留 Firecrawl 原始 item 的全部 key。
- primary_key: `[source, content_uid]`；as_of_field: `published_at`（rfc3339）；partition_field: `event_date`。
- cadence_class: 第一期 `on_demand`；第二期 `event`（现有 event cadence `minimum_interval_seconds: 900`，即 15 分钟下限，分钟级快讯受此约束——见风险节）。
- 去重：同 window 重抓 → 相同 `content_uid` + append_only → SQLite 主键去重；同一新闻多源/重发 → 源不同即不同行（客观事实如此），跨源语义去重是消费者职责，TradingDatas 不做。

### 2.2 `cn.news.regulator_policy`（监管/政策，第二期）

- 源：证监会"新闻发布/政策"列表页、交易所官网公告栏、央行新闻。结构同 2.1，`cadence_class: event`，频率更低。
- 不与 tushare `anns_d`（公司公告）重复：本 dataset 只覆盖监管机构与交易所官方发布。

### 2.3 `cn.sentiment.social_hot`（客观舆情，第三期）

- 源：雪球热帖/热股榜页面。fields 增加 `stock_tags`(text, nullable，页面上客观存在的 $代码$ 标签，逗号分隔)、`reply_count`/`like_count`(integer, nullable)。
- 只存页面客观字段；不存正文全文（json 抽取只声明结构字段）。
- cadence `event`，低频（小时级），`freshness_sla_seconds: 21600`。

## 3. 落库与 receipt

完全复用 `provider_dataset_rows` + `storage/ingest_receipts`：行与 success receipt 同事务；empty/failed/rate_limited/validation_failed 分别写 terminal receipt；provider failure 不伪装 empty。不新增任何业务表、route、query 分支。未知字段（Firecrawl item 多出 schema 的 key）按现有机制标 schema drift，不删不改。query/catalog 侧零改动——新 dataset 自动出现在 `/v1/catalog`，`/v1/query` 通用过滤直接可用。

## 4. 源清单与频率预算

### 4.1 第一批源（按优先级）

| # | 源 | dataset | 抓取方式 | 建议节奏 |
|---|---|---|---|---|
| 1 | 财联社电报 cls.cn/telegraph | flash | scrape 列表页 + json 抽取 | 手动→4次/日 |
| 2 | 东方财富 7×24 快讯 | flash | 同上 | 同上 |
| 3 | 新浪财经 7×24 | flash | 同上 | 第二期 |
| 4 | 同花顺快讯 | flash | 同上 | 第二期 |
| 5 | 证监会新闻发布 | regulator_policy | scrape 列表页 | 1-2次/日 |
| 6 | 上交所公告/新闻栏 | regulator_policy | 同上 | 1次/日 |
| 7 | 深交所公告/新闻栏 | regulator_policy | 同上 | 1次/日 |
| 8 | 央行新闻 | regulator_policy | 同上 | 1次/日 |
| 9 | 雪球热帖榜 | social_hot | scrape + json 抽取（含股票标签） | 2-4次/日 |
| 10 | 东方财富股吧热榜 | social_hot | 同上 | 第三期备选 |
| 11-14 | 国务院/发改委/工信部政策页 | regulator_policy | scrape | 第三期备选 |

`search_news`（Firecrawl `/search`，2 credits/次）不进自动节奏，只作 on_demand 补充手段（按主题/个股补漏）。不使用 crawl/interact（额度与反爬风险不匹配第一批目标）。

### 4.1b 快讯主干改走 tushare（2026-08-16 实测，优先于 Firecrawl 源）

2026-08-16 真实有界探测（本地 QuickSync 账号）：tushare `news`（start/end 时间窗，1 小时实测 114 行，字段 datetime/content/title/channels）与 `major_news`（同窗 127 行，字段 title/pub_time/src）**均有权限且返回正常**。因此快讯主干改为两个 tushare dataset（`cn.dataset.news_flash`、`cn.dataset.major_news`），走现有 QuickSync 管线的**纯 registry onboarding（零新代码、零 Firecrawl 额度）**，event cadence 15 分钟。Firecrawl 的财联社/东财快讯源降级为冗余校验备选（第一期不做）；Firecrawl 专注于它独有的源：监管/政策页面与雪球舆情。

### 4.2 额度预算（2026-08-16 所有者决策 + 实测更新）

所有者已确认 key 可续且实测每个 key 有 8 万+ credits（5 key ≈ 40 万，可续），并明确否决自建开源 Firecrawl（核心价值是云端代理网络/反爬对抗，自建会失去该能力并增加生产服务器 headless 浏览器运维负担）。adapter endpoint 保持可配置，未来如需自建可零代码切换。快讯主干走 tushare 后 Firecrawl 只承担政策+舆情源。

- scrape 1 credit/次。**节奏（价值导向）**：政策源交易时段小时级、非交易时段 1-2 次/日；舆情源交易时段 15-30 分钟、非交易时段小时级。估算 ≈ **30-50 credits/日 ≈ 1,000-1,500/月**，相对 40 万可续额度可忽略。频率上限由数据价值决定，不由额度决定。
- registry `freshness_sla_seconds` 与实际节奏一致，不虚标；rate_budget 复用现有 `event` class 并在 schedule config 为 firecrawl 单设保守上限（如 `api_requests_per_run: 4`）。
- **key 耗尽/替换平滑设计**：key 只在 `FIRECRAWL_API_KEY_FILE`（0600 文件）；换 key = 换文件，零代码零 registry 改动。402/429 → `rate_limited` terminal receipt，planner 跳过，dataset 降级为 degraded，不阻塞 tushare/binance 管线。key 全尽时把 binding `activation_state` 调回 paused（registry/config 改动），管线形态不变。文档化运维步骤入 `docs/OPERATIONS.md`。

## 5. 与固定 API 的衔接

消费方（Tradingagent 六维打分 `_score_sentiment`，`shared/screening/six_dimension_scorer.py:875`）经 `POST /v1/query` 读，无需新 route：

- 快讯/政策：`{dataset_id: "cn.news.flash", filters: [{field: "event_date", op: "between", ...}], order: [{field: "published_at", desc}], limit}`；`source` filterable 支持按源筛选。
- 舆情：`cn.sentiment.social_hot` 同上，另可按 `stock_tags` 过滤——但注意现有 query 合同是精确匹配/in 过滤，`stock_tags` 是逗号分隔多值，**不能**精确匹配单代码。因此第一/二期决策：**新闻↔ts_code 不做关联，原文（结构字段）落库**；雪球 `stock_tags` 也只作存储字段。消费侧（Tradingagent 的 sentiment reader）先按时间窗拉取再自行匹配代码，或在第三/四期评估是否在 registry 允许的通用能力内表达多值过滤（不能表达则保持消费侧匹配，不为此加 query 分支）。
- scorer 需要的 `direction/confidence/status` 语义当前由其 reader 层产出；TradingDatas 只供客观行。Tradingagent 侧的适配（reader 从 SharedSignals 切到 TD `/v1/query`）属于 Tradingagent 仓库改动，不在本设计范围，但本设计的字段（title/summary/published_at/source/url + 客观计数）已覆盖其 `_text_direction_hint` 等降级路径的输入需求。

## 6. 实施分期

### Phase 0：合同冻结（contract_ready，不触发真实调用）

- 改动文件：
  - `provider_transport.py`：firecrawl profile 常量与分支；
  - `collectors/firecrawl/__init__.py`、`collectors/firecrawl/collector.py`：adapter 实现（scrape_page/search_news 两个 api_name 白名单）；
  - `config/provider_native_dataset_registry.yaml`：`cn.news.flash`（on_demand、activation paused→候选）1 个条目；
  - `tools/collect_provider_dataset.py`：分发表 +1 行；
  - 测试：`tests/test_firecrawl_collector.py`（mock transport：归一化、content_uid、错误映射、敏感扫描）、registry 编译测试快照更新、`test_provider_native_zero_code.py` 类比的"新 provider 合同"测试；
  - 文档：`docs/ARCHITECTURE.md`（新 provider 一节）、`collectors/AGENTS.md` 关键文件表、`STATUS.md`。
- 验收：全部测试绿；registry 编译通过；条目为 `contract_ready` 且 `activation_state: paused`。

### Phase 1：MVP（observed）

- 改动：`cn.news.flash` 条目 activation 候选（财联社 + 东财 2 个 literal_values）；`config/internal_consumer_capability_profile.v1.yaml` 标注一次性内部只读试用；`docs/OPERATIONS.md` 增 firecrawl 手工采集与换 key 步骤。
- 操作：真实 key 文件放到服务器（0600，仓库外）；先用 registry dry-run 证明计划非零（采集前门禁）；`tools/collect_provider_dataset.py --batch-file ... --execute` 手动有界执行 1-2 窗；`/v1/catalog` + `/v1/query` readback 验证行、receipt、freshness。
- 验收：一次真实 provider → SQLite receipt → query readback 闭环；重复执行同窗行数不增（去重验证）；429/断网场景产生正确 terminal receipt（可用有界负例）；Firecrawl 调用量 ≤ 预算（记录 creditsUsed）。

### Phase 2：事件节奏 + 政策源（stable 候选）

- 改动：registry 增 `cn.news.regulator_policy`；`config/provider_native_schedule.yaml` 不动 cadence 定义，只为 firecrawl binding 启用 event；`deploy/systemd/` 新增独立 firecrawl collect service/timer（**生产变更，按 collectors/AGENTS.md 第 8 条单独 fresh inventory + 锁/预算/回滚验收**）；A 股运行面不受影响（独立 unit，同 Binance 隔离先例的精神，但可共用 A 股 SQLite——需评审决定，默认共用现有 provider-native 库以复用 API）。
- 验收：按 event cadence 连续成功 N 个窗口（建议 ≥5 个交易日）；degraded 路径演练（拔 key）；消费者受控 readback。

### Phase 3：舆情源 + 消费切换

- 改动：registry 增 `cn.sentiment.social_hot`；Tradingagent 侧 sentiment reader 切换（另一仓库）；视实测决定 `stock_tags` 过滤是否需通用能力扩展。
- 验收：六维打分 sentiment 维度在受控标的集合上出现非空 evidence（`_mark_evidence rows>0`）。

## 7. 风险与对策

- **一次性 key 额度**：最大风险。对策：预算导向节奏（4.2 节奏 A）；creditsUsed 记录进 receipt evidence 之外的运行报告；key 文件热替换；全尽即 paused，管线形态不变。禁止 search_news 进自动节奏（2 credits/次）。
- **源反爬/结构漂移**：Firecrawl 代理层缓解 IP 封禁，但页面 DOM 变化会使 json 抽取缺字段 → 现有 `validation_failed`/schema drift 机制自动降级该 dataset 并留 receipt，不静默出错；对策为更新 registry 中该源的 extraction_schema（config 改动）。
- **分钟级快讯诉求 vs event cadence 15 分钟下限**：现有 `event` cadence `minimum_interval_seconds: 900`，即自动节奏最快 15 分钟。key 可续后额度不再是约束（4.2），15 分钟×2 源先行；若日后确需更快，改 schedule config（config 改动+评审）即可，设计不阻塞。
- **内容合规**：只请求结构化 json 抽取（标题/摘要原文短句/链接/时间/计数），不存全文 markdown；payload 无损原则对"所请求的响应"成立。链接回原站，不转载正文。雪球内容为用户观点，dataset 只承载客观元数据并在 `data_classification` 上保持 `objective_factual`。
- **舆情噪声**：TradingDatas 不过滤；消费侧已有 confidence≥0.2、allowed_status 等门槛（scorer 内）。雪球计数字段为消费者提供客观权重依据。
- **Tushare 快讯主干（已实测落地为首选路径）**：2026-08-16 实测 QuickSync 账号对 tushare `news`（1 小时窗 114 行）与 `major_news`（同窗 127 行）均有权限，快讯主干已改为这两个 tushare dataset 的纯 registry onboarding（见 4.1b），零 Firecrawl 额度。Firecrawl 只承载其独有源（监管/政策页面、雪球舆情）。

