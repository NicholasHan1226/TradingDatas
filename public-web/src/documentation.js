// Authored public guidance. Stable slugs preserve search results and bookmarks.
const categoryCopy = [
  ["start", "开始使用", "从了解平台到连接已有数据访问。", "Get started", "Find your way around and connect existing data access."],
  ["data", "理解数据", "看懂分类、字段、覆盖与更新状态。", "Understand data", "Read categories, fields, coverage, and update status."],
  ["api", "API 与 Agent", "发现数据、发起查询并接入你的工具。", "API & Agents", "Discover datasets, query them, and connect your tools."],
  ["learn", "研究与方法", "从外部文献走向可复现的数据准备。", "Research & methods", "Move from external reading to reproducible data preparation."],
  ["commerce", "账户与订阅", "了解套餐、已有权限和账户安全。", "Account & plans", "Understand plans, existing access, and account security."],
];

const catalogExample = 'curl https://tradingdatas.com/v1/catalog \\\n  -H "Authorization: Bearer ${TRADINGDATAS_API_KEY}"';
const queryExample = JSON.stringify({ dataset_id: "cn.equity.daily", schema_major: 2, fields: [], filters: {}, as_of: null, limit: 10, cursor: null }, null, 2);
const section = (id, title, paragraphs, extra = {}) => ({ id, title, paragraphs, ...extra });
const link = (label, path) => ({ label, path });
const guide = (slug, title, description, sections, related) => ({ slug, category: slug.split("-")[0], title, description, sections, related });

const zh = [
  guide("start-1", "认识 TradingDatas", "先浏览数据与研究，再按需连接账户和工具。", [
    section("explore", "从你要完成的事开始", ["Data 用于查找数据产品、字段与覆盖；Research 整理外部论文及其所需材料；Pricing 解释套餐和请求频率。Docs 集中提供使用说明，可从右上角账户菜单打开。", "这些内容和 Agent 接入说明都可以免登录阅读。想保存某个数据产品、文献或方法时，使用收藏按钮，稍后从顶部收藏入口继续。"]),
    section("access", "什么时候需要登录", ["查看个人订阅、用量、API 密钥、账单或安全设置时需要登录。未登录访问账户分区，会先进入登录页，成功后回到原分区。", "邮箱登录用于识别你的账户，不自动附带数据权限。数据 API 的每次请求仍需要有效的 Bearer 密钥，网页登录状态不会代替它。"]),
    section("personalize", "设置阅读习惯", ["右上角菜单可以切换中文、英文及明亮、暗色或系统外观，无需登录。全站搜索可查找数据、研究、方法和 Docs。", "收藏保存在当前浏览器，不会自动同步到其它设备或账户；清除浏览器数据可能同时清除收藏。"]),
  ], [link("浏览数据", "/data"), link("首次接入", "/docs/start-2"), link("本机收藏", "/bookmarks")]),
  guide("start-2", "连接已有数据访问", "已有 API 密钥的用户，从连接账户到完成第一次请求。", [
    section("prepare", "先准备有效密钥", ["你需要已有的 TradingDatas 数据 API 密钥。仅注册或登录邮箱不会创建订阅，也不会自动生成可查询数据的权限。购买与续费目前暂停。", "如果暂时没有密钥，可以先浏览 Data、阅读研究和接入说明；无需等待登录或购买即可了解数据。"]),
    section("connect", "在账户中查看已有权限", ["连接已有密钥后，账户根据服务端返回显示数据访问、有效期、用量和可用的密钥管理操作。连接不会扩大原密钥的数据范围。"], { steps: ["打开账户中的“订阅与数据访问”并登录。", "在可用的连接入口提交已有密钥，按页面提示完成身份验证。", "确认页面显示的套餐、有效期和数据分类；若连接失败，检查密钥和错误提示后再试。"] }),
    section("first-request", "先调用 Catalog", ["在你自己的终端或工具中安全设置 TRADINGDATAS_API_KEY，再运行下面的请求。这里仅提供可复制示例，不会替你发送请求。", "从返回目录选择数据集，确认当前 schema、字段、权限与限制，再按 Query 指南读取小页数据。"], { code: catalogExample }),
  ], [link("订阅与数据访问", "/account/subscription"), link("Catalog 指南", "/docs/api-1"), link("Query 指南", "/docs/api-2")]),
  guide("data-1", "选择数据与理解字段", "用数据身份、时间口径和覆盖范围判断是否适合你的任务。", [
    section("choose", "从分类找到具体数据集", ["Data 中的分类用于发现产品，API 中的 dataset_id 用于指定一个数据集。分类名称、产品标题和 dataset_id 不能互相替代。", "网站会同时介绍已观测、计划中及待发布的产品。实际可查询的数据集和字段，请以有效密钥调用 Catalog 后的结果为准；公开数据入口目前不聚合独立的 Crypto 运行面。"]),
    section("schema", "先看身份、字段和时间", ["核对 dataset_id、schema_version 和 identity_fields，再了解字段单位、日期格式、时区与更新频率。主键帮助识别重复记录，但不能证明历史完整。", "保留 provider 原始字段的含义。遇到 schema major 变化，先更新字段和过滤条件，再继续查询；不要把旧字段名或自造字段补入结果。"]),
    section("coverage", "确认窗口和限制", ["coverage.row_count 是已存储行数；earliest_observed_at 与 latest_observed_at 描述观测范围，不代表完整交易日覆盖。", "读取 limits.max_page_size、max_in_values 和 max_lookback_days，按实际返回值设置查询。一次查询成功不等于全历史或所有标的都有数据。"]),
  ], [link("浏览数据", "/data"), link("更新状态与凭证", "/docs/data-3"), link("Catalog 指南", "/docs/api-1")]),
  guide("data-2", "了解另类数据", "区分数据产品介绍、实际覆盖和可用的访问权限。", [
    section("scope", "先确认内容与来源", ["新闻、公告和其它另类数据需要逐项查看来源、时间口径、样本、更新方式与限制。同属一个分类不代表它们有相同的字段或覆盖。", "阅读产品说明中的来源和使用范围，判断它是否适合你的研究任务；网站列出产品不代表已开通查询或允许任意转发。"]),
    section("availability", "看清当前可用状态", ["计划中或待发布的产品可以用于了解后续方向，不能当作当前可查询的数据。已有观测的产品也需要结合最新状态、实际覆盖和你的数据权限判断。", "基础套餐与另类数据试用、加购是不同事项。当前不能通过页面选择自动开启试用、购买加购或获得权限。"]),
    section("use", "使用前做一个小窗口检查", ["对于 Catalog 中实际可用且已授权的数据集，先读取少量记录，核对发布时间、采集时间、重复项和缺失情况。", "将产品的限制保留在后续输出中；不要把新闻数量、更新延迟或来源覆盖当作某个市场结论。"]),
  ], [link("数据目录", "/data"), link("数据来源", "/data/sources"), link("订阅说明", "/docs/commerce-2")]),
  guide("data-3", "阅读更新状态与数据凭证", "把有无数据、是否新鲜和是否可追溯分开理解。", [
    section("states", "状态分别说明什么", ["success 表示一次成功采集；empty 表示该次请求没有数据；paused 表示采集暂停；failed 表示失败。freshness 中的 stale 描述数据已超出适用的新鲜度窗口。", "degraded 提醒你注意质量或更新限制。数据源出现问题时，仍可验证的已有数据可能继续返回，并携带相应状态；空数据不会被补成成功数据。"]),
    section("timestamps", "看两个不同的时间", ["observed_at 是实际采集观测时间，data_through 描述数据覆盖到的时间。今天采集的记录可能属于更早的业务日期。", "同时检查 freshness、quality、lineage 和 coverage。HTTP 200 只表示请求完成，不能单独证明数据新鲜、历史完整或适合时点研究。"]),
    section("retain", "为复现保留查询上下文", ["保存 dataset_id、schema_version、查询参数、request_id 和响应中的 receipt 信息，让后续处理能追溯到本次读取。", "遇到 503 service_unavailable 时暂缓使用该页并有限重试。持续失败时保留 request_id 与错误码排查，不要用旧响应伪装成当前结果。"]),
  ], [link("Query 指南", "/docs/api-2"), link("研究方法", "/docs/learn-2")]),
  guide("api-1", "通过 Catalog 发现数据", "读取已有权限范围内的数据合同，作为每次接入的起点。", [
    section("request", "请求目录", ["使用 GET https://tradingdatas.com/v1/catalog，并携带 Authorization: Bearer 密钥。浏览网站不需要密钥，读取数据 API 需要。", "当前公共入口使用 A 股数据运行面。不要根据网站中的跨市场产品介绍，假设该接口已经聚合 Crypto 数据。"], { code: catalogExample }),
    section("inspect", "选择前核对这些字段", ["dataset_id 指定数据身份，schema_version 给出当前版本，identity_fields 表示记录身份。再查看可用字段、过滤能力、更新频率和 coverage。", "limits.max_page_size 限制单页数量，max_in_values 限制 in 过滤列表长度，max_lookback_days 限制回看范围。它们是数据集查询限制，和账户请求频率不同。"]),
    section("next", "从可发现到可查询", ["目录中的状态仍需逐项阅读：看到一个数据集不代表它当前已激活、已有记录或满足你的时间窗口。结合权限、激活状态与运行信息后，再发送 Query。", "保存本次目录中的版本。接口提示版本或字段不匹配时，重新读取 Catalog 并更新请求，不要继续套用旧示例。"]),
  ], [link("Query 指南", "/docs/api-2"), link("理解字段", "/docs/data-1"), link("API 密钥", "/account/keys")]),
  guide("api-2", "用 Query 读取数据", "从一个小请求开始，正确处理字段、分页和错误。", [
    section("request", "构造第一条请求", ["向 https://tradingdatas.com/v1/query 发送 POST JSON，携带 Authorization: Bearer 密钥和 Content-Type: application/json。", "下例是请求格式示例，不是已执行结果。cn.equity.daily 与 schema_major: 2 需先与当前认证 Catalog 核对；limit 也不能超过该数据集上限。fields 为空数组表示返回完整原始字段。"], { code: queryExample }),
    section("pagination", "读取下一页", ["检查 data、metadata 与 next_cursor。存在 next_cursor 时，将它作为下一次请求的 cursor，并保持原查询条件；next_cursor 为 null 时停止。", "先用必要字段和有界窗口读取。不要靠单纯加大 limit 拉取所有历史；调整数据集、字段或窗口时，从不带 cursor 的新请求开始。"]),
    section("errors", "按错误原因处理", ["400 invalid_request：检查字段、过滤算子和请求格式。413 budget_exceeded：缩小页大小、字段数或过滤列表；请求不会被自动截断。", "401 时检查密钥；429 rate_limited 时降低频率并等待窗口恢复。503 service_unavailable 时进行有限退避重试，持续失败保留 request_id；retryable 不保证相同请求随后必然成功。"]),
    section("history", "历史查询的时间边界", ["as_of 使用 RFC3339 时间，且需要对应数据集支持相关时间口径。as_of 限制当时已观测的事实，不会把后来回填的数据变成当时已知的数据。", "需要逐行 receipt proofs 的使用者可设置 include_receipt_proofs: true；它要求单一采集序列，同页跨序列会被拒绝。普通查询省略即可，基础行回执校验仍然执行。"]),
  ], [link("Catalog 指南", "/docs/api-1"), link("更新状态与凭证", "/docs/data-3"), link("Agent 接入", "/connect")]),
  guide("api-3", "接入 Agent 与 MCP 工具", "让工具使用相同的数据接口，同时保留密钥和数据状态边界。", [
    section("setup", "从公开接入页选择工具", ["打开 Agent 接入页，选择 Claude、Codex、OpenClaw、Hermes 或其它 HTTP 工具，按页面生成的说明配置。教程无需登录。", "这些工具共用 GET /v1/catalog 与 POST /v1/query。选择某种 Agent 或复制 MCP 说明，不会额外开通数据，也不会创建新的数据接口。"]),
    section("secrets", "将密钥交给工具的安全配置", ["把已有密钥放入工具支持的密钥存储或环境配置中。不要把真实密钥粘贴到提示词、公开链接、截图或共享文档。", "让 Agent 先读取 Catalog，再按实际数据身份、schema 和查询限制请求。网页邮箱登录不能替代 API 的 Bearer 认证。"]),
    section("results", "要求工具如实呈现结果", ["让工具保留 dataset_id、查询窗口、receipt 与更新状态；结果为空或陈旧时直接说明，不要编造缺失值或把缓存说成刚读取的数据。", "接口出错时应有限重试并显示错误码。接入完成意味着工具能读取已有授权数据，不意味着可以预测、交易或替你下单。"]),
  ], [link("打开接入页", "/connect"), link("Catalog 指南", "/docs/api-1"), link("账户安全", "/docs/commerce-3")]),
  guide("learn-1", "阅读 Research", "从研究问题找到原文、材料和下一步的数据准备方法。", [
    section("find", "精选与主题各有用途", ["精选提供问题驱动的阅读起点；主题按研究方向组织完整文献库。也可以用顶部全站搜索查找标题、作者或主题。", "先阅读导读和数据需求，再决定是否打开原文。TradingDatas 整理的是外部文献，保留原作者、年份和来源。"]),
    section("read", "将结论放回研究范围", ["阅读原文时核对样本市场、时间区间、假设和方法。论文中的结论属于作者，不能直接外推到当前市场或你的数据窗口。", "关联的数据产品说明了可能需要哪些材料，不代表平台已经复现论文、验证效果或提供投资建议。"]),
    section("continue", "保存与继续准备数据", ["使用阅读原文、收藏和复制引用继续工作。收藏只保存在当前浏览器；引用时保留原文作者与来源。", "把论文需要的数据字段和时间窗口列出来，再到 Data 核对覆盖，到研究方法中选择查询、连接或时间对齐方法。"]),
  ], [link("阅读 Research", "/research"), link("研究方法", "/docs/learn-2"), link("本机收藏", "/bookmarks")]),
  guide("learn-2", "准备可复现的数据", "从小窗口开始，处理时间、连接键、缺失和修订。", [
    section("define", "先确定输入与输出", ["记录所用 dataset_id、schema、标的范围、时间窗口和需要的字段。明确最终输出的每一行代表什么，再选择连接键。", "Recipes 提供数据准备方法；Features 中标为计划或产品定义的内容，不应被当作当前可调用的衍生数据服务。"]),
    section("align", "处理时间与缺失", ["区分业务日期、发布时间和采集时间。按信息实际可得的时间对齐，避免把晚发布或后修订的记录提前放进研究窗口。", "连接前检查键是否唯一、单位是否一致、复权口径是否匹配。缺失、暂停和空结果分别记录；除非方法明确允许，不用零或前值静默填充。"]),
    section("reproduce", "留下能重复执行的记录", ["保存查询条件、分页过程、返回版本和 receipt；记录去重、过滤、连接与缺失处理的方法以及前后行数。", "先在小窗口检查，再扩展范围。示例和合成样本用于解释方法，不能作为真实覆盖、完整性或研究效果的证明。"]),
  ], [link("浏览方法", "/recipes"), link("选择数据", "/data"), link("数据凭证", "/docs/data-3")]),
  guide("commerce-1", "比较套餐与请求频率", "三档基础套餐如何区分，以及当前可做哪些操作。", [
    section("plans", "按请求频率选择", ["基础版、专业版与旗舰版共享基础数据范围和历史政策，分别为每分钟 200、600 和 1000 次请求。商业三档不设每日查询额度或商业档并发上限。", "套餐介绍不能代替你的有效权限。实际可查询分类、接口范围、有效期和限制以已连接账户及 API 返回为准；存量套餐可能使用不同限制。"]),
    section("period", "理解月付与年付展示", ["Pricing 可以切换月付与年付。年付显示年度总额；折算月均价只是比较口径，不代表逐月扣款。", "基础套餐不自动包含另行说明的另类数据加购。选择套餐或计费周期不会改变当前账户权限，也不表示自动续费。"]),
    section("availability", "购买与续费目前暂停", ["你可以比较套餐或查看非付款预览，但预览不会创建订单、收款或开通数据。当前不能通过网站完成购买与续费。", "已有数据访问的用户可以继续按有效权限查询，并在账户查看订阅信息。"]),
  ], [link("比较 Pricing", "/pricing"), link("订阅与账单", "/docs/commerce-2"), link("查看订阅", "/account/subscription")]),
  guide("commerce-2", "管理已有订阅与用量", "查看现有数据访问；了解账单和续费的当前状态。", [
    section("subscription", "先查看有效访问", ["登录后进入“订阅与数据访问”。只有邮箱身份而没有连接数据访问时，不会出现已付费套餐或自动获得查询权限。", "连接已有有效密钥后，核对服务端返回的套餐、有效期和数据范围。密钥失效或连接不可用时，先处理数据访问问题，不必把它理解成邮箱退出。"]),
    section("usage", "区分趋势与请求限制", ["用量页用于查看已有访问的请求历史与限额。每日趋势是用量统计，不等于商业三档存在每日查询额度。", "遇到限流时降低每分钟请求数、分批读取并等待窗口恢复；数据集单页大小或过滤列表限制需要在 Query 参数中单独处理。"]),
    section("billing", "账单入口不代表已开通支付", ["购买、续费和在线账单流程目前未开放。预览选择不会生成订单、发票或支付记录，也不会自动续费。", "需要判断是否有数据权限时，查看当前订阅与 API 返回；不要把价格页、付款预览或页面按钮当作已生效的订阅。"]),
  ], [link("订阅与数据访问", "/account/subscription"), link("用量", "/account/usage"), link("账单", "/account/billing")]),
  guide("commerce-3", "保护账户与 API 密钥", "区分邮箱会话和数据凭证，安全查看、轮换及停用密钥。", [
    section("identity", "邮箱身份与数据访问分开管理", ["邮箱验证用于登录个人账户；可用登录方式以登录页显示为准。连接已有数据密钥后，才可读取相应数据访问和管理能力。", "邮箱会话过期时重新登录。身份服务暂时不可用时，页面提供重试；Docs、数据产品介绍和本机收藏仍可访问。"]),
    section("keys", "管理已有权限下的密钥", ["在 API 密钥页使用当前账户提供的操作。新建密钥继承现有有效权限，不会升级套餐；完整密钥仅显示一次，请立即保存到安全位置。", "轮换时先配置并验证替代密钥，再停用旧密钥。当前用于访问门户的密钥不能直接停用；不要将真实密钥放进聊天、文档或公开代码。"]),
    section("sessions", "退出与删除的影响", ["退出网站结束相应登录会话，不等于停用外部工具正在使用的 API 密钥；需要停止工具访问时处理该密钥。", "安全页在可用时提供邮箱资料删除，需要重新验证和明确确认。它不删除数据平台记录或替你撤销独立的既有 API 密钥；提交删除也不等于所有备份已立即清除。"]),
  ], [link("API 密钥", "/account/keys"), link("安全设置", "/account/security"), link("Agent 接入", "/connect")]),
];

const en = [
  guide("start-1", "Meet TradingDatas", "Explore data and research, then connect your account and tools when needed.", [
    section("explore", "Start with your task", ["Use Data to find products, fields, and coverage; Research to explore external papers and their materials; Pricing to compare plans and request rates. Open Docs from the account menu for guidance.", "You can read these pages and Agent setup instructions without signing in. Bookmark a dataset, paper, or method and return through the bookmark icon in the header."]),
    section("access", "When sign-in is needed", ["Personal subscription, usage, API keys, billing, and security pages require sign-in. If you open one as a guest, you go to Login first and return to the same section after signing in.", "Email sign-in identifies your account. It does not grant data access. Every data API request still needs a valid Bearer key; your website session cannot replace it."]),
    section("personalize", "Set up your reading preferences", ["The upper-right menu offers Chinese, English, and light, dark, or system appearance without sign-in. Global search covers data, research, methods, and Docs.", "Bookmarks stay in this browser. They do not automatically sync across accounts or devices, and clearing browser data may remove them."]),
  ], [link("Explore data", "/data"), link("First connection", "/docs/start-2"), link("Local bookmarks", "/bookmarks")]),
  guide("start-2", "Connect existing data access", "Use an existing API key to view your access and make your first request.", [
    section("prepare", "Have a valid key ready", ["You need an existing TradingDatas data API key. Creating or signing into an email account does not create a subscription or query access. Purchase and renewal are currently paused.", "Without a key, you can still explore Data, read research, and review setup instructions without waiting for sign-in or checkout."]),
    section("connect", "View access in your account", ["Once an existing key is connected, the account displays server-returned access, expiry, usage, and available key controls. Connecting does not expand that key's permissions."], { steps: ["Open Subscription & data access and sign in.", "Use the available connection control to submit your existing key and complete any requested identity verification.", "Check the returned plan, expiry, and data categories. If connection fails, check the key and the error before retrying."] }),
    section("first-request", "Call Catalog first", ["Securely configure TRADINGDATAS_API_KEY in your own terminal or tool before running this request. This is a copyable example; this page sends no request for you.", "Choose a dataset from the response, check its current schema, fields, access, and limits, then follow Query to read a small page."], { code: catalogExample }),
  ], [link("Subscription & data access", "/account/subscription"), link("Catalog guide", "/docs/api-1"), link("Query guide", "/docs/api-2")]),
  guide("data-1", "Choose data and understand fields", "Check identity, time conventions, and coverage against your task.", [
    section("choose", "Find a specific dataset", ["Data categories help you discover products. The API uses dataset_id to identify one dataset. A category name, product title, and dataset_id are not interchangeable.", "The website includes observed, planned, and pending-release products. Use authenticated Catalog to confirm queryable datasets and fields; the public API currently does not aggregate the separate Crypto runtime."]),
    section("schema", "Read identity, fields, and time", ["Check dataset_id, schema_version, and identity_fields, then field units, date formats, timezone, and cadence. Identity fields help detect duplicates but do not prove complete history.", "Preserve the meaning of provider fields. When a schema major changes, update your field selection and filters before querying again; do not fill in obsolete or invented fields."]),
    section("coverage", "Check the window and limits", ["coverage.row_count counts stored rows. earliest_observed_at and latest_observed_at describe observations, not complete trading-day coverage.", "Read limits.max_page_size, max_in_values, and max_lookback_days and use the returned values. One successful query does not establish all-history or all-symbol coverage."]),
  ], [link("Explore data", "/data"), link("Updates & receipts", "/docs/data-3"), link("Catalog guide", "/docs/api-1")]),
  guide("data-2", "Understand alternative data", "Separate product descriptions from actual coverage and access.", [
    section("scope", "Check content and sources", ["For news, announcements, and other alternative data, inspect each product's sources, time conventions, samples, updates, and limitations. Sharing a category does not imply shared fields or coverage.", "Read the stated source and usage scope before choosing data for your research. A listed product does not imply query access or unrestricted redistribution."]),
    section("availability", "Read current availability", ["Planned and pending-release products describe future direction, not currently queryable data. Observed products still need current status, coverage, and your access to be checked.", "Base plans are separate from alternative-data trials and add-ons. Selecting a page option currently cannot activate a trial, purchase an add-on, or grant access."]),
    section("use", "Start with a small window", ["For an available, authorized dataset in Catalog, read a few records and check publication time, observation time, duplicates, and gaps.", "Keep the product's limitations alongside your output. Article counts, delays, and source coverage are not market conclusions."]),
  ], [link("Data catalog", "/data"), link("Data sources", "/data/sources"), link("Subscription guide", "/docs/commerce-2")]),
  guide("data-3", "Read updates and data receipts", "Understand availability, freshness, and traceability separately.", [
    section("states", "What each state means", ["success describes a successful collection; empty means no data for that request; paused means collection is paused; failed describes failure. stale in freshness means data is outside its applicable freshness window.", "degraded flags a quality or update limitation. Previously collected, verifiable data may still be returned during a source issue with its status preserved. Empty data is never filled in to look successful."]),
    section("timestamps", "Read two different times", ["observed_at is the actual collection observation time. data_through describes how far the data extends. Records collected today may belong to an earlier business date.", "Check freshness, quality, lineage, and coverage together. HTTP 200 alone does not prove freshness, complete history, or suitability for point-in-time research."]),
    section("retain", "Keep context for reproducibility", ["Save dataset_id, schema_version, query parameters, request_id, and receipt information with the response so later processing can be traced to this read.", "For 503 service_unavailable, pause use of that page and retry a bounded number of times. If it persists, retain request_id and the error code; do not present an old response as a current result."]),
  ], [link("Query guide", "/docs/api-2"), link("Preparation methods", "/docs/learn-2")]),
  guide("api-1", "Discover data with Catalog", "Read the data contract within your existing access before querying.", [
    section("request", "Request the catalog", ["Send GET https://tradingdatas.com/v1/catalog with Authorization: Bearer and your key. Website browsing needs no key; data API requests do.", "The current public entry point uses the A-share data runtime. Cross-market product descriptions on the website do not mean this endpoint aggregates Crypto data."], { code: catalogExample }),
    section("inspect", "Inspect the contract", ["dataset_id identifies the dataset, schema_version gives its current version, and identity_fields identifies records. Inspect available fields, filters, cadence, and coverage next.", "limits.max_page_size bounds a page, max_in_values bounds an in filter list, and max_lookback_days bounds lookback. These dataset limits are separate from your account's request rate."]),
    section("next", "Move from discovery to a query", ["Read each dataset's status. An entry being listed does not mean it is active, contains records, or covers your desired window. Check access, activation, and runtime information before Query.", "Keep the catalog version you used. When a version or field no longer matches, read Catalog again and update the request instead of reusing an old example."]),
  ], [link("Query guide", "/docs/api-2"), link("Understand fields", "/docs/data-1"), link("API keys", "/account/keys")]),
  guide("api-2", "Read data with Query", "Start small and handle fields, pagination, and errors correctly.", [
    section("request", "Build your first request", ["POST JSON to https://tradingdatas.com/v1/query with Authorization: Bearer and Content-Type: application/json.", "The example below shows a request format, not an executed result. Verify cn.equity.daily and schema_major: 2 against current authenticated Catalog; limit must fit that dataset's budget. An empty fields array returns the complete original fields."], { code: queryExample }),
    section("pagination", "Read the next page", ["Inspect data, metadata, and next_cursor. When next_cursor is present, pass it as cursor on the next request while keeping the original query conditions. Stop when next_cursor is null.", "Use necessary fields and a bounded window first. Do not just increase limit to fetch all history. Start without a cursor when changing datasets, fields, or windows."]),
    section("errors", "Respond to the cause", ["400 invalid_request: check fields, filter operators, and request format. 413 budget_exceeded: reduce the page size, selected fields, or filter list; requests are not silently truncated.", "For 401, check your key. For 429 rate_limited, slow down and wait for the window to recover. For 503 service_unavailable, use bounded backoff and retain request_id if it persists; retryable does not promise that the same request will succeed later."]),
    section("history", "Respect historical time boundaries", ["as_of uses RFC3339 and needs the dataset's applicable time support. It limits facts observed by that time; later backfills do not become facts known earlier.", "Set include_receipt_proofs: true if you need per-row receipt proofs. This requires one collection sequence and rejects pages spanning sequences. Ordinary queries may omit it; base row-receipt validation still runs."]),
  ], [link("Catalog guide", "/docs/api-1"), link("Updates & receipts", "/docs/data-3"), link("Agent setup", "/connect")]),
  guide("api-3", "Connect Agents and MCP tools", "Use the same data APIs while protecting credentials and preserving data status.", [
    section("setup", "Choose your tool on the setup page", ["Open Agent setup, select Claude, Codex, OpenClaw, Hermes, or another HTTP tool, and follow the generated instructions. The tutorials need no sign-in.", "All tools share GET /v1/catalog and POST /v1/query. Choosing an Agent or copying MCP instructions does not grant data access or create another data endpoint."]),
    section("secrets", "Use your tool's secure configuration", ["Store an existing key in the tool's supported secret storage or environment configuration. Keep real keys out of prompts, public links, screenshots, and shared documents.", "Ask the Agent to read Catalog first and use its actual dataset identity, schema, and query limits. Website email sign-in cannot replace API Bearer authentication."]),
    section("results", "Keep outputs faithful to the data", ["Ask your tool to retain dataset_id, the query window, receipts, and update status. Empty or stale results should be stated clearly; missing values must not be invented or cached results called fresh reads.", "Errors should produce bounded retries and a visible error code. A working connection lets the tool read existing authorized data; it does not add prediction, trading, or order execution."]),
  ], [link("Open setup", "/connect"), link("Catalog guide", "/docs/api-1"), link("Account security", "/docs/commerce-3")]),
  guide("learn-1", "Read Research", "Find original sources, required materials, and your next preparation method.", [
    section("find", "Use Featured and Topics", ["Featured provides question-led starting points. Topics organizes the full library by subject. Global search also finds titles, authors, and themes.", "Read the orientation and data requirements before opening the original. TradingDatas curates external literature and retains its authors, year, and source."]),
    section("read", "Keep conclusions within their scope", ["Check the paper's sample market, dates, assumptions, and method. Its conclusions belong to the authors and cannot automatically be extended to today's market or your data window.", "Linked products identify potentially useful materials. They do not mean the platform reproduced the paper, verified its results, or offers investment advice."]),
    section("continue", "Save and prepare your next step", ["Use Read source, Bookmark, and Copy citation to continue. Bookmarks stay in this browser. Keep the original authors and source when citing.", "List the fields and time window the paper needs. Check their coverage in Data, then choose a query, join, or time-alignment method."]),
  ], [link("Read Research", "/research"), link("Preparation methods", "/docs/learn-2"), link("Local bookmarks", "/bookmarks")]),
  guide("learn-2", "Prepare reproducible data", "Start with a small window and handle time, join keys, gaps, and revisions.", [
    section("define", "Define inputs and output", ["Record dataset_id, schema, symbols, time window, and required fields. Decide what each output row represents before choosing join keys.", "Recipes describe preparation methods. Features marked planned or product definition must not be treated as currently callable derived-data services."]),
    section("align", "Handle time and missing values", ["Distinguish business dates, publication times, and collection times. Align by when information became available so late publications or revisions do not enter an earlier research window.", "Before joining, check key uniqueness, units, and adjustment conventions. Record missing, paused, and empty results separately; do not silently fill with zero or the previous value unless your method explicitly allows it."]),
    section("reproduce", "Keep an executable record", ["Save query conditions, pagination, returned versions, and receipts. Record deduplication, filtering, joins, missing-value methods, and before-and-after row counts.", "Validate a small window before expanding. Examples and synthetic samples explain a method; they do not prove actual coverage, completeness, or research results."]),
  ], [link("Browse methods", "/recipes"), link("Choose data", "/data"), link("Data receipts", "/docs/data-3")]),
  guide("commerce-1", "Compare plans and request rates", "Understand the three base tiers and which actions are currently available.", [
    section("plans", "Choose by request rate", ["Basic, Professional, and Flagship share base-data scope and history policy, with 200, 600, and 1000 requests per minute respectively. These commercial tiers have no daily query quota or commercial concurrency limit.", "Plan descriptions do not replace your effective access. Check your connected account and API responses for categories, endpoint access, expiry, and limits. Legacy plans may have different limits."]),
    section("period", "Read monthly and annual pricing", ["Pricing lets you switch monthly and annual views. Annual pricing shows the yearly total; the monthly equivalent is a comparison, not a monthly charge.", "Base plans do not automatically include separately described alternative-data add-ons. Selecting a plan or period does not change account access or enable automatic renewal."]),
    section("availability", "Purchase and renewal are paused", ["You can compare plans or open a non-paying preview, but a preview creates no order, payment, or data access. Website purchase and renewal are currently unavailable.", "Existing data-access users can continue querying within valid permissions and review their subscription in Account."]),
  ], [link("Compare Pricing", "/pricing"), link("Subscription & billing", "/docs/commerce-2"), link("View subscription", "/account/subscription")]),
  guide("commerce-2", "Manage existing access and usage", "Review current data access and understand billing and renewal availability.", [
    section("subscription", "Check effective access first", ["After sign-in, open Subscription & data access. Email identity without connected data access does not create a paid plan or query permissions.", "Connect an existing valid key, then check the server-returned plan, expiry, and data scope. An invalid key or unavailable connection is a data-access issue, not necessarily an email sign-out."]),
    section("usage", "Separate trends from limits", ["Usage shows request history and limits for existing access. A daily trend is a statistic; it does not imply a daily quota for the three commercial tiers.", "For rate limiting, lower per-minute traffic, batch reads, and wait for the window to recover. Query page size and filter-list limits must be handled separately in request parameters."]),
    section("billing", "A billing entry does not mean payment is live", ["Purchase, renewal, and online billing workflows are not currently open. Preview selections create no orders, invoices, payment records, or automatic renewal.", "To confirm data permissions, check your current subscription and API responses. A price, preview, or page button does not establish an active subscription."]),
  ], [link("Subscription & data access", "/account/subscription"), link("Usage", "/account/usage"), link("Billing", "/account/billing")]),
  guide("commerce-3", "Protect your account and API keys", "Keep email sessions separate from data credentials and rotate keys safely.", [
    section("identity", "Manage identity and data access separately", ["Email verification signs you into your personal account; the Login page shows available methods. Connecting an existing data key enables its corresponding access and management capabilities.", "Sign in again when your email session expires. If identity services are temporarily unavailable, retry from the page. Docs, product descriptions, and local bookmarks remain accessible."]),
    section("keys", "Manage keys within existing permissions", ["Use the operations available on your API keys page. A new key inherits existing effective access and does not upgrade your plan. Its full value is displayed once, so save it securely immediately.", "For rotation, configure and verify a replacement before disabling the old key. The key currently used for portal access cannot be disabled directly. Keep real keys out of chat, documents, and public code."]),
    section("sessions", "Understand sign-out and deletion", ["Website sign-out ends the relevant sign-in session; it does not disable API keys used by external tools. To stop tool access, manage that key.", "When available, Security offers email-profile deletion with fresh verification and explicit confirmation. It does not delete data-platform records or revoke independent existing API keys for you. Submission does not mean every backup is immediately erased."]),
  ], [link("API keys", "/account/keys"), link("Security", "/account/security"), link("Agent setup", "/connect")]),
];

export function getDocumentation(locale = "en") {
  const chinese = locale === "zh" || locale === "zh-CN";
  return {
    categories: categoryCopy.map(([key, zhLabel, zhDescription, enLabel, enDescription]) => ({ key, label: chinese ? zhLabel : enLabel, description: chinese ? zhDescription : enDescription })),
    guides: chinese ? zh : en,
  };
}
