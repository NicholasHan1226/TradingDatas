# TradingDatas 当前状态

最后更新：2026-09-02 09:12 CST（A 股生产运行 immutable release
`9da2aab777dda1443a9d0db44066e2e2973c3860`；QuickSync 续费与公开运行规则已脱敏复核；
Firecrawl 长故障水位与健康巡检账本兼容修复仍是本地候选，尚未合并或发布。短 SLA
提前刷新保持未启用）。
本文只保留当前可替换摘要；历史决策见
[`docs/adr/`](docs/adr/)，事故与验收复盘见
[`docs/reports/`](docs/reports/)。当前运行事实仍以本轮服务器、SQLite receipt 和认证
`catalog/query` readback 为准。

## 2026-09-02 残余健康收口

- QuickSync 用户提供的在线测试页已从本机和新加坡服务器分别取得 HTTPS 200。页面的脱敏
  订阅元数据显示 `anns_d/news/research_report/rt_min/stk_auction/stk_mins/tushare_15000`
  有效至 `2026-09-27T16:04:00Z`，与本次续费一致；页面路径和内容含凭据，不能入库或提交。
- 同页公开规则明确基础/标准/极速版最大速率分别为 120/600/1200 次每分钟，异常流量可降至
  60 或 0 次每分钟并在每日 0 点重置。页面没有声明当前 token 对应的速率档、每日总调用额度
  或并发上限；因此生产现有 per-run 预算不扩张，`freshness_refresh_lead_seconds` 继续为 0。
- 09:11 的过去 24 小时 `global.news.flash` 来源物理回执：CNBC 81 success、30
  provider_error、6 transport_error；美联储 74/7/1；SEC 37/36/3。最新一轮 CNBC 与
  美联储成功、SEC `provider_error`。上一份三来源全部成功 execution 完成于
  `2026-09-01T14:34:29Z`，之后已有 126 份物理回执，超出 catalog 每数据集最近 100 份窗口。
  现有事件波次保持单轮每分片一次、后续 timer 有界重试。本候选让 event/session-minute
  的最新 provider failure 继续显示 failed/degraded，同时从同一 active config 的完整历史
  execution 恢复上一成功 `data_through`，不会把旧成功改写为当前健康。
- 每日 `tradingdatas-collector-watch` 从 8 月 30 日起对滚动评估产生假告警：TA 已改为原子
  目录 `entry-*/entry.json`，巡检仍只识别旧顶层 `entry-*.json`。本候选同时识别两种成功
  条目，忽略空的失败暂存目录；它不修改、补写或伪造 TA 账本。生产巡检脚本尚未替换。
- 09:18 的 TA 开盘初始化均实际成功：30 标的会话发布今日 Copilot 跟踪列表；隔离 scale
  会话载入 3,187 标的，4 项因昨日收盘价缺失排除、2 项因上市未满 30 日 pending。两者都
  明确为模拟、无执行权限，并报告预期与当前 catalog version 漂移；scale 验收仍是
  `pending_two_live_snapshots`。`rt_min`/`rt_min_daily` 的当日 provider receipt、认证
  catalog/query 及 09:42 后消费者读回仍未完成，不能用初始化成功代替盘中数据健康。
- `fina_mainbz`、`stk_mins`、`top10_cb_holders`、`top10_floatholders` 当前 one-shot 合同会
  展开完整来源 universe，预计分别产生约 598、5,973、1,163、598 次 provider 调用；manifest
  不能任意截取单个代码。当前账号档位、并发和每日总额度仍无正式证据，且交易时段由分钟
  采集保留，因此本轮不执行这 8,332 次调用。该安全阻断不等于四项权限失败或数据不可用。

## 邮箱身份本地候选（2026-08-30）

### 2026-08-31 公开证据与 Agent 接入跟进（未发布）

- 在 PR #408 候选之上修正静态产品健康误示，保留本页未核验状态与合成样例标识；
  查询模板从真实 catalog 合同取值，五类 Agent 的中英文说明统一由文档派生。
- 本轮 143/143 前端测试、构建与本地 workerd/D1 回归通过；独立复核无剩余
  已确认 P0/P1。真实内部 A 股 catalog → 单条 query → receipt 投影回读通过，
  仅证明受控内部路径，不等于公共用户、全量历史或连续稳定验收。
- 公共 API 域名本轮未解析；线上邮箱 auth-methods 返回 404。未发真实邮件，
  未部署或修改远端配置；支付、短信与账户新功能生产开关保持原状。
  后续仍需精确候选 CI、PM 接受及分层发布验收，详见
  [本轮验收记录](docs/reports/2026-08-31-public-evidence-readiness.md)。

### 2026-08-31 账户连续性跟进候选（未发布）

- `codex/account-library-v1` 从邮件候选 `ea1c536` 独立推进，保留 PR #397；
  现有 Account 增加用户主动连接已有数据密钥、按身份隔离的云收藏与显式本机导入。
  `/admin/` 复用已有管理员界面，通过同站桥接逐请求验证后端管理员权限。
- 连接不创建订阅、租户或管理员；支付、短信和新功能生产开关均保持关闭。
  新账户连续性 schema 未应用到远端 D1，无本轮真实邮件发送或生产变更。
- 独立复核发现的跨标签页注销 P1 已修正：预期身份头强制匹配 Cookie 身份，
  回执绑定 user_id；两用户与迟到回执测试通过，复核未发现剩余 P0/P1。
  此修正不可在最终集成时丢失；单独发布旧邮件候选不包含该后续防护。
- 详细合同与下一步发布门禁见 [Account continuity](docs/design/account-library-v1.md)。
  本地 workerd/D1、合成邮箱与浏览器检查不等于线上登录、真实数据授权或商业开通。
- 21:48 本地验收：127/127 测试通过，前后端构建与实际 workerd/D1 回归通过；
  现有 Account 和同站 Admin 已用合成身份实点验证。详情与未验收项见
  [账户连续性验收记录](docs/reports/2026-08-31-account-continuity.md)。

- 23:30 保留与注销检查点：owner 已确认过期验证码 24h、失效会话 7d、明确注销后
  账户库资料 30d 的最长保留期，可提前清理。候选实现独立账户库的有界小时清理、
  显式注销队列，以及既有 Account → Security 内的确认入口；当前用户近期验证后
  原子停用并撤销所有邮箱会话。未申请注销的停用资料、其他用户、旧 API 密钥和
  金融事实不删除。构建与 109/109 本地测试通过，真实本地 workerd/D1 已验证
  注销、旧会话拒绝和 scheduled 清理；Wrangler 类型生成及 dry-run 通过。
  独立复核无 P0/P1，其退出按钮交互建议已修正。两个开关仍为 false；无真实发信、
  无远端新增表/清理/角色/部署。生产启用仍须精确 CI、Datas PM 门禁、私密配置和
  真实 OTP/调度回读。管理员共享身份和订阅关联仍未实现；详见
  [保留与注销准备记录](docs/reports/2026-08-30-identity-retention-readiness.md)。
- 22:30 语言检查点：首次发送/重发改按设备或浏览器首选语言选择中英文，与网页手动
  语言设置分离；中文区域/繁简变体均归中文，其他和缺省归英文。新增语言规则和真实
  handler 的模拟发送回归通过。一次授权中文版品牌测试获 Resend `delivered` 回读；
  收件箱分类/客户实际显示仍待确认，不是 OTP 登录或管理员授权。登录上线仍等待
  保留政策、密钥配置、精确候选 CI/安全审查及 PM 门禁；不提前开放短信、支付或角色。
  详见[语言与就绪检查](docs/reports/2026-08-30-email-language-readiness.md)。
- 21:15 模板检查点：owner 已确认收到此前授权的投递测试；这不证明实际验证码登录、
  角色绑定或收件箱分类。后续所有对外邮件（含测试）统一使用版本化品牌模板。
  现已接入中英文验证码 HTML + 纯文本，并准备独立投递测试模板；本轮没有新增发信。
  92/92 本地测试、构建及隔离 workerd/D1 回归通过；浏览器检查浅/暗、窄屏、无图和
  纯文本。QQ/Gmail/Outlook 实际 HTML 客户端显示仍未验收。候选保留邮箱关闭开关，
  没有改密钥、用户、角色、数据采集或生产部署。详见
  [品牌邮件规范](docs/design/transactional-email-system-v1.md)。以下是较早检查点，
  其中“未发送邮件”仅描述该检查点当时状态；后续一次投递证据见准备记录补充。
- 分支 `codex/email-identity-v1`，基于 `c6f7a45`，整理为独立候选交付；合入与部署
  仍须单独验证。不改冻结的购买流程候选 PR #394；本分支包含其前置提交，不能与它
  当作两个无依赖候选重复合入。以下旧发布表保留历史来源，不是本次生产复核。
- 早前 15:45 检查点：Resend `account.tradingdatas.com` 与三项 DKIM/MX/SPF 均
  verified，当时尚无数据库初始化。20:24 后独立账户库准备见本节末项；没有发信或开关启用。
- 既有 Login/Account 内实现邮箱一次性验证码、独立八小时可撤销会话，以及无租户、
  无数据授权的未订阅状态。短信与支付保持关闭；旧密钥不自动关联邮箱。
- 最终构建成功，`npm run test:sites` 85/85 通过，`git diff --check` 通过；
  Worker 源码与生成副本逐文件一致。本地 workerd + D1 已验证验证码原子消费、
  未订阅隔离、退出撤销和旧密钥兼容。
  发现并修正 Worker 不支持 `redirect: error` 的问题：改用 `manual`，显式拒绝
  3xx，仍不转发凭据或 Location。此修正同样只在本地，不能声称生产登录已修复。
- 运行入口、安全/数据保留/配置及发布回滚门禁：
  [Email identity v1](docs/design/email-identity-v1.md)。浏览器测试只使用 loopback
  与 example.com 模拟邮件；没有真实客户或上游数据写入。补验已确认真实 DOM 宽度
  390px 和 768px，页面无横向溢出；手机错误/成功验证码、未订阅账户、退出与
  明暗中英切换通过。修复重发/更换邮箱的原生按钮外观，触控高度实测 44px。
- 桌面实点验证：错误验证码、中文/英文与浅/暗主题、六个账户私有栏目、刷新会话、
  退出后回到未登录态，以及邮箱登录后返回基础版年付预览（总价 1,069.20，支付仍禁用）。
  最终预览浏览器 error 日志为空。本轮未运行 Python 全套或数据采集测试：未改数据面。
- owner 本次继续执行后，Cloudflare 最小范围 OAuth 已恢复；命令级使用系统证书
  文件解决 Node 信任链问题，未关闭 TLS 校验或扩大授权。20:24 创建独立账户 D1，
  随后初始化五表并回读全部为零行、外键检查无异常；非金融采集库，也不涉及 Hovvi 库。
  候选配置加入 `IDENTITY_DB` 与显式关闭的邮箱开关；未部署线上 Worker、生成 Resend
  key 或发信。20:21 Resend 域名/DKIM/MX/SPF 再次 verified。详见
  [账户库准备记录](docs/reports/2026-08-30-email-identity-provisioning.md)。
  仍需测试收件邮箱、保留政策与发布门禁；线上邮件/SMS/支付未开放。
  真实手机键盘/屏幕阅读器仍待设备验收。
- 20:36 owner 已提供测试收件邮箱，并确认该身份也作为平台管理员、同时进入现有
  用户 Account。已同步产品与账户规范：一个验证身份、两个明确工作区，管理员角色
  和数据套餐授权独立。实际邮箱验证、角色绑定和共享管理员登录仍未实现/启用；本次
  没有写入角色或真实用户，也没有发送邮件。个人地址不进入仓库。文档变更回归 85/85；
  项目规则文件已核对，新会话实际加载未验。发件地址确认和原发布门禁继续保留。

## 2026-08-30 晚间运行可靠性

PR #401 的 exact-main `c714dc9` CI 已通过，21:12 A股/新闻核心运行面完成切换；
三源真实回执和新增原始新闻字段已通过认证query验证，公开query仍保留partial语义。
21:33 A股目录192项为88 success、41 empty、57 paused、5 unobserved、1 stale
（stk_holdernumber）；该短SLA过期重复出现，不能算已恢复连续健康。

Crypto已于22:36切入PR #402的`4bb6fe8`及WAL，候选和精确主线CI通过；
240项目录与六类查询在停写窗口前后一致，七个原timer恢复，实际TA只读凭据通过。
22:39与22:49认证目录分别取得现货、盘口、资金费率各40项新的成功回执，最新现货窗口
query ready/valid/complete。但22:41、22:46仍有15秒超时；两路目录并发各超过35秒，
单路约7秒，不能称并发性能已恢复。PR #403合入855cec1，候选与精确主线CI通过，
但23:21真实双请求各15.017秒超时。单目录12.050秒及六查询与停写基线一致；
23:22回退4bb/WAL，认证回读相同后恢复七timer。23:24真实PID/cwd与manifest再次确认。
下一候选在相同UTF-8字节合同下采用数据库原生首匹配；多次/重叠前缀保留原完整Python
matcher，不改变原始候选/预算/parser或增加跨请求投影缓存。尚未取得生产通过证据。
event提前刷新默认为0，实际调用频率不变；非零候选的每日额度证据尚缺。
合同、证据限制及下一步见[运行可靠性报告](docs/reports/2026-08-30-runtime-reliability.md)。
并发修复的失败验收与下一候选见[原生匹配及同请求复用报告](docs/reports/2026-08-30-runtime-native-candidate.md)；
先前扫描锁合同见[并发目录报告](docs/reports/2026-08-30-runtime-concurrency.md)。

## 2026-08-30 采集恢复与覆盖复核

本轮数据运行事实见[覆盖与质量恢复报告](docs/reports/2026-08-30-coverage-quality-recovery.md)。
13:46 已在现有 A 股 release `385a4fa` 上补采五项 on-demand 数据，新增 1,148 行、
5 份回执，认证 query 均 ready/valid/complete；定时器恢复 active。
财报日窗口及分钟累计数据仍存在已量化的覆盖缺口，不能声称全量健康。
第二批 fut_basic 新增 11,196 行、6 份回执，但查询仍因缺 trade_time_desc 降级，
不能算质量健康。13:57 A 股目录为 87 success/43 empty/57 paused/4 unobserved/1 stale；
Crypto 为 240 success。质量合同 PR #393 已合入 TD `4ef9565`，精确主线 CI 通过。
三条只读消费者兼容 PR #609 已合入 TA `eb469916`，候选及精确主线 CI 通过；
这不代表 TA 运行或交易入口启用。分钟 major 3 与七项财务日期续采修复已完成实现、正在独立审查，
不会恢复此前缺乏 provider 日期校验的撤回方案。TD `4ef9565` 于15:27完成受控发布及
8份回执/11,740行补采，完整认证分页与5项无关样本通过；TA真实消费者已在15:37通过限定股票/月及期货M参考数据读取，TA主线5a74edf及精确CI通过；不启用交易。见
[发布检查点](docs/reports/2026-08-30-consumer-release-preflight.md) 与
[续采合同](docs/reports/2026-08-30-resumable-collection-contract.md)。下方 08-26 数据运行表为历史
快照，不能替代本轮当前 release/readback。公开站状态未在本轮重新验收。

## 16:35 续采发布与新闻检查点

PR #398 修复了生产优化加载遗漏 fanout 来源和日期变量覆盖时间参数两项 P1，已合入
`5526cff6a6cd636255e08b36eabd44e77a4b71c1`，精确主线 CI `33301029280` 通过。
16:25 已切入 A 股采集器和 18082；396 个声明文件完整性验证通过，回滚点 `4ef9565`
及全部旧事实/回执保留。两轮原服务执行产生七项财务的 14 份合法 empty 回执，每项
均从 batch 0 推进到 1，无失败或重试；没有新增财务事实，认证 query 继续返回
empty/partial/degraded，不能声称质量健康或覆盖完整。分钟 major 3 保持周日 unobserved；
真实交易日和财务自然跨日证据仍未取得。

16:26 管理后台与 18082 的十项目标公开合同、运行回执和覆盖快照一致；真实 TA 消费者
再次通过券商推荐限定月/股票 5 行及期货 M 参考数据 208 行读取，交易入口保持关闭。
16:24 Crypto 目录 240 项 success，BTC 行情和资金费率样本质量/lineage 有效；SG 中继
16:22 收到 16:00 资金费率，Crypto release 仍为 `15f463e`，本轮未切换。

额外验收发现：切换前国内新闻执行有真实 transport_error；全球新闻目录出现
receipt_execution_inconsistent，但同一 SQLite 快照的完整历史验证通过。最近 100 条
目录窗口截断了完整重试组的第一条，补读第 101 条即恢复正确投影。这是有界读取边界
误报，正在单独修复；不能删除回执、忽略真实缺损或把新成功暂时掩盖告警当作根修。
上述生产检查点与新修复的候选/CI/发布状态必须分别报告。

## 20:40 发布后复查与质量后续

PR #399 已合入并于17:18发布为 `a735163047e4e5fa8e5b40e08074bbd42d0c9773`，
候选 CI `33302884325` 与精确主线 CI `33303328478` 均成功；397文件通过可信 manifest
校验，回滚点 `5526cff` 和全部既有事实/回执保留。17:20管理后台与内部API的12项目标
合同、运行元数据和覆盖快照一致。真实 tradingagent 服务账号再次读到券商推荐5行及
期货M参考208个唯一ID/3页，未启用交易。上方16:35“新闻误报正在修复”为历史检查点，
不代表当前发布状态。

20:18复查：A股192项目录为88 success/42 empty/57 paused/5 unobserved，无failed或
stale；Crypto 240项success。现货新回执观察到20:14:59.999行情，新加坡中继20:18又
观察到当日16:00资金费率。API、原采集timer及独立Crypto服务均正常，运行release未变。
该快照不能替代逐数据集连续健康；分钟仍须实际交易时段验证。

七项财务在20:19的当前合同下各有49份回执，批次推进到47/48，日期均为20260830。
除balancesheet有1次失败外均为空响应；不存在回执完整性损坏。单码加精确公告日的
请求合同未发现拼接错误，周日少量代码为空不能证明接口故障，也不能证明权限或完整性。
20:36完成income固定000006.SZ的两次纯transport对照：20260826返回2行、85字段，
20260830返回0行。它支持该样本日期差异的解释，不代表其余六项也已验证；未写数据库
或receipt、未改股票池。20:39再次确认原timer/API active，release未变。

国际新闻query的两项保护性降级来自未知response completeness与未验证发布时间水位，
不是此次新闻目录误报复发。另已复现成功行原始日期字符串被归一化覆盖的缺陷；
本轮以minor兼容合同保留未来成功行的原值、原始item及精度，保持原查询降级，不用
采集时钟宣称发布时间。详见[晚间质量后续](docs/reports/2026-08-30-evening-data-quality-followup.md)
及[全球新闻原值合同](docs/reports/2026-08-30-global-news-provenance.md)。

## 分层交付状态（下表为08-26历史快照，当前数据面以上方新检查点为准）

| 层 | 本轮事实 | 声明边界 |
|---|---|---|
| 公开站功能基线 | `4869268`（PR #380/#381；账户同站会话与 Cloudflare 发布门禁修复） | 该功能基线 exact-main CI `33266061920` 四分片通过；后续纯文档 main 前进不改变该发布事实，也不替代数据运行面 release 验证 |
| 公开站 Worker | `4869268`，Cloudflare run `33266061919` | `/`、`/login/`、`/account/`、`/data/`、`/research/`、`/pricing/` 均 200 且精确资源回读；未登录账户 API 401、跨源换取会话 403；真实客户 key 的成功换取本轮未验证 |
| 本地 canonical | `cbde095b4080264e71e037ff95d60f024c2a7d4a`，behind 更多 | 已保留的非权威分叉；owner 交接前不 reset/清理；其 rt-min fanout 子集保留逻辑已被 main 等价覆盖 |
| A 股有效 release | `cf988f93e6dbe379f82fd0a530e081af6aab8965`（回滚点 `21d03183355d7de6578ab5761d83aa91a1925c1f`） | immutable 运行源码，2026-08-26 23:07 CST 由 Controller 切换；verify true + catalog 200 复核通过 |
| Crypto 有效 release | `f5388759cec0fb3f8f78af97c6f900587eb74b62`（回滚点 `7d04a1f6fe273d81e7ea20bef29c7c7701091df2`） | 隔离 immutable 运行源码，2026-08-23 15:26 CST 切换 |

上述各层必须分别读回；源码、service 或 timer 单层健康都不能写成"三端同步"、
消费者闭环或模拟交易结果。

## 2026-08-26 发布记录

第十一轮（23:07 CST 切换 `cf988f9`，PR #354；自愈验收与三项诊断同轮收口）：

- **#352 自愈验收（21:55 定时检查 + 查询面回读）**：`cn.news.flash` 的
  `invalid_receipt_authority` 跳过消失、窗口内 `data_through_in_future` 零命中；
  认证查询回读 state=success、首页 500 行、内容新鲜至当日且**零未来时间戳行**。
  恢复期一例 provider_error 与两例 ingest validation_failed 属采集面常态波动；
  发现缺口：validation_failed 的 `validation_reasons:[]` 为空，失败细节同样不可判读，
  排入后续改进。消费契约实证：快照型数据集 `as_of_field=null`，带 `as_of` 的
  `/v1/query` 一律 invalid_request——正确形状不含 as_of。
- **PR #354 firecrawl 信封诊断修复**：根因链——SEC 页抓取常态耗时 18-22s 贴近
  timeout_ms=30000 上限（复现 >30s 客户端超时），但生产主导失败形态是
  `success:false` 信封且 firecrawl 错误文本被适配器整体丢弃（今日两 news 数据集
  82 failed / 51 success 全为不可判读 provider_error）。修复按白名单标记把信封错误
  归类为固定罐头诊断（timed-out / refused-by-target / generic），经专用内部异常
  `_FirecrawlUpstreamFailure` 直达 outcome error_message，原文永不入日志/receipts；
  error_code、fail-closed 语义与契约哈希零变化。+4 单测含防泄漏断言，文件级
  35 passed、相邻套件 177 passed、CI 4/4。合并后由 Controller 于 23:07 标准流程
  部署并切换 current → `cf988f9`；本侧复核 verify true + catalog 200。
  待自然失败样本回报三类分布后再议 timeout_ms 上调或换源。
- **#309 关闭（带生产证据）**：share_float 断供已由 #344 解决（ann_date=20260826
  实测 73 行、data_through=当日）；float_date 四算子过滤实测正确生效、目录广告一致；
  "当日公告解禁日在次日"属正确时点语义；08-24 的 503 恶化归 #327 存储病。
- **cb_basic 停更=纯调度缺失（已回填 #350）**：cadence_policy 自 07-23 即 on_demand；
  journal 全窗零次调度成功（08-11 前 paused、08-12 起 on_demand skip）；上游探针
  空参快照 success 1162 行。建议归入 daily_reference 或常规 on-demand batch。
- **fina_mainbz 探针定案（已回填 #349）**：QuickSync 端点无任何公告日暴露，唯一日期
  杠杆是报告期 end_date；多码+start/end（现模板形态）静默空实锤；单码全史 ~150 行/码
  （4 报告期 ×~37）；type=P 硬编码会静默丢弃地区(D)/行业(I)构成。提案：单码低频全史
  快照扇出 + 去掉 type 过滤，实施前需解 dependency_seed_receipt_unresolved。

第十轮（19:28 CST，A 股面 → `21d0318`，PR #352）：Controller 侧修复 cls.cn 电报条目
携带 ~12h 未来时间戳毒化 `cn.news.flash` 收据水印、导致数据集被 planner 以
`invalid_receipt_authority` 持续跳过（09:50 起）的事故。修复为写时钳制：
`_clamp_future_watermark` 用与投影侧 `_data_through_in_utc` 完全一致的解析阶梯
（%Y%m/%Y%m%d/ISO，naive 按 dataset 时区），把严格晚于写入时刻的候选 data_through
钳到 `written_at`；trade_calendar 豁免与投影层镜像。审计通过后本地全量复跑
2322 passed / 1 skipped（25m54s），标准流程发布：build→scp→staging（manifest 驱动
chmod 0444/0555、目录 0555、root:root）→verify→停 timer 排空在途周期（90s）→
switch-current→恢复服务，认证 catalog readback 200/192 datasets。运维注记：本轮
回滚点 `252eb9b` 的顶层 manifest 缺失，按确定性重建（同 commit 同树 ⇒ 字节一致）
并先对已安装树 verify 通过后才切链；manifest 归位 `manifests/<sha>.json` 约定。
事故语义：修复只阻断新增毒化，存量未来水印需等墙钟越过该时间戳（约当日 21:45 CST）
后由 `state.invalid_reasons` 自然恢复干净，采集自动续跑——已排一次性验收检查。
另：`global.news.flash` 周期 state=failed 为 firecrawl `provider_error`（既有独立
问题，与本修复无关）。回滚点 `252eb9b2`。

第九轮（10:33 CST，A 股面 → `c5e8499`，PR #348）：#319 收尾——#347 把六个财报源
换到 ann_date 窗后，实弹探针（复刻 collector 传输 `tushare_rows_outcome`）证明
QuickSync 端点行为：income 族逗号多码 ts_code 携带任意第二参数静默返回空（单码+
同一 ann_date 返回 2 行；ann_date 单独被拒 20002 必填 ts_code）；pledge_stat 每
请求静默截断在 1000 行（三长历史码恰返回 1000，单码最大观测 641）。据此七源
（income/balancesheet/cashflow/express/fina_indicator/fina_audit/pledge_stat）
`batch_size` 10→1，U=`1eee7462…`、registry=`7f99b8f1…` 重生成重钉，新增生成态
registry 回归钉测并把七源移出 `TEN_CODE_FANOUT_APIS`（含原因注释）。流程同标准
发布：build→staging root:root→verify→停 timer 排空→switch-current→恢复。排障
记录：切链时 switch-current 报 "release directory mode must be 0555"，根因是此前
服务器端探针以 venv python 直接从发布树 import 且未设 PYTHONDONTWRITEBYTECODE，
在不可变树里留下 __pycache__（755）；清除并复验回滚树后切换成功。教训：对发布树
的任何一次性 python 调用必须带 `PYTHONDONTWRITEBYTECODE=1`。后续 issue：#349
（fina_mainbz 无 ann_date 字段需 period-window 设计）、#350（七个数据集
cadence=on_demand 从未被调度——生产零行的直接原因是调度缺失而非采集失败；
cb_basic 自 2026-08-14 停更待诊断）。回滚点 `9f2f19c8`。
实弹验收（当日两次 on_demand 单窗触发）：修复形态在生产路径真实出数——income
ann_date=20260826 落 389 行 valid（约 190 个真实公告码，半年报季）；pledge_stat
落 399,315 行单码全史、无 1000 行截断；重跑去重语义验证通过（62,520 行全部
unchanged）。两次扇出均在 ~1-2k 请求后遭上游同端点持续突发停滞（客户端传输超时
fail-fast 中止；同期混合定时周期正常，属 #350 已量化的上游行为）。数据集最新周期
state=failed 期间查询面按设计 fail-closed 返回空（`allow_rows=False`），干净周期
完成后恢复；全宇宙覆盖需 #350 的 resumable_fanout/排期决策。

第八轮（08:51 CST，A 股面 → `9f2f19c`，PR #347）：#319 第一轮——六个财报源
（income/balancesheet/cashflow/express/fina_indicator/fina_audit）请求模板从
run_clock 推导的 end_date/start_date 窗改为 ann_date 单日窗（公告日语义，窗口机制
全通用无需改调度 lane），pledge_stat 去掉 end_date 改纯 ts_code 扇出（stk_rewards
先例形态）；观察文件 registered pin → U=`8b372d0d…`、registry=`776a23a5…` 重生成
重钉。部署后实弹验收发现多码+过滤组合静默空（见第九轮），故本轮为"必要但不充分"，
由 #348 完成修复。回滚锚 `9f99800`。

第七轮（02:47 CST，A 股面 → `9f99800`，PR #344）：#339 修复——share_float 上游单次
响应静默截断在 ~6000 行而声明 pagination strategy=none，高流量 ann_date 六个分区
（20260801/03/05/06/10/19）以成功 receipt 入库了截断数据且无失败信号。声明层改为
offset 分页（page_size=6000、max_pages=8、budgets 48000→编译安全上限 42466，
满页 fail-closed 语义保留）。为表达多页分页，运行时契约编译器新增可选观察键
`pagination_max_pages`（正整数、默认 1，替代投影中硬编码的 max_pages=1，要求伴随
limit/offset literal，阻断 probe 禁用）；share_float 官方文档节补登 limit/offset 输入
（bak_daily 先例），下游全部哈希钉更新：runtime+cadence policy canonical SHA、
request-profiles 文档 SHA、观察 provenance 四项、upstream contracts 与
provider-native registry 重生成、activation wave registry 哈希重钉；双编译器字节级
幂等复现。回归测试断言编译产物分页参数与预算覆盖最大观测日（20411 行）。
流程：本地 build manifest（255 files）→ staging root:root 按 manifest 定模式 →
verify 通过 → 停 timer 排空采集（02:40 一轮 firecrawl 双源 provider_error 致 exit 1
为遗留问题非回归）→ switch-current → 服务恢复，catalog 认证回读正常。
重补验证：六分区 on_demand 单窗重采全部 success，唯一行数
6000→8068/17805/20411/11290/11277/10562（合计找回 43413 行），证明上游真实支持
offset 翻页；API query 回读 `ann_date=20260805` 数据可消费。回滚点 `423a9f49`。

## 2026-08-25 发布记录

第六轮（23:40 CST，A 股面 → `423a9f4`，PR #340 + #338）：#340 为 #283 修复——
dataset_field fanout 源读取从非阻塞抢锁改为有界共享锁等待
（`_FANOUT_SOURCE_LOCK_WAIT_SECONDS=180`），并发写入方（backfill/重叠采集）到来时
延迟读而非 fail-closed；#338 为 console 工作区统一与数据状态文案（静态资源随版）。
流程：本地 build manifest（255 files）→ staging 只读 root:root → verify 通过 →
safe-release preflight（timer disabled、collector 排空、API inactive）→ switch-current
→ verify-current verified=true → 认证 readback：catalog 192 datasets、
`cn.equity.daily` query 200（TA 消费者 token）。切换后新代码采集运行 Tushare 面
全部成功；`global.news.flash`（firecrawl）provider_error 致 exit 1 为部署前后一致的
遗留问题，非本次回归。回滚点 `4f7f894`。

后续（00:30 CST，#342，test-only）：修复 firecrawl 裸时间锚测试
`test_bare_wall_clock_time_is_anchored_to_source_day` 的日期边界缺陷——测试用真实
时钟推期望日，而生产代码在本地 00:00–08:09:28 窗口会正确回退一天避免未来时间戳，
故该窗口内 CI 必挂；注入固定 `observed_at` 后确定性通过。生产行为不变，无需重新发布；
旧分支 `fix/firecrawl-bare-time-anchor`（210c02e）的生产改动已由 main 等价承载，
归档候选。

## 2026-08-23 发布记录

第五轮（15:26 CST，crypto 面 → `f538875`，PR #271）：oi-dump 共享锁等待上限由
120s 提升至 480s（unit TimeoutStartSec=600s 内）。生产实弹验证 `systemctl start`
后 ExecMainStatus=0，数据集按设计报 unchanged/unpublished 软缺口，unit 不再标红。
回滚点 `7d04a1f`。

第四轮（15:07 CST，crypto 面 → `7d04a1f`，PR #270）：oi-dump 入口锁从非阻塞
flock 改为有界等待 `_timed_lock`，消除与 book-ticker/funding 批次的瞬时碰撞。
首次实弹暴露 120s 不足，引出第五轮。

第三轮（14:33 CST，A 股面 → `7f6ba42`，PR #269）：`daily_limit_exceeded` 补入
`_V1_ERROR_DETAILS`（对齐冻结合同的 429 语义）；`GET /admin/api/usage/history`
NameError 修复；调度器预算耗尽改 skipped 语义并新增错误码静态守卫测试。
匿名 401 readback 通过；消费者级认证 readback 待 owner 执行。

第二轮（02:20/02:23 CST，两面 → `5ca8e3e`，PR #267）：scheduled crypto 采集器
（spot bars / book-ticker / USDM）从非阻塞抢锁改为有界 120s 等待
（`_bounded_lock`），失败输出带具体错误与 `lock_wait_seconds`；`_private_lock`
保留给快路径调用方。同一 trusted verifier（SHA256 复核一致）、registry 重编译逐字节
一致；两面 switch-current、verify-current（含 manifest）、认证 readback 均通过。
回滚点统一为 `300182f`。

第一轮（00:22/00:25 CST，两面 → `300182f`）：

发布通道：本地 clean worktree（origin/main HEAD）→ `release_manifest.py build`
→ `marketgraph-root` 写入新 commit 目录 → trusted verifier 校验 → registry 重编译
逐字节一致 → safe-release preflight（API inactive、timers disabled、collector 排空）
→ `switch-current` → verify-current → service/timer 恢复 → 认证 readback。

- A 股面：匿名 catalog `401`、TradingAgent token catalog `200`（6.4s/874KB）；
  `tradingdatas-v1-internal.service` active、provider-native timer enabled。
- Crypto 面：切换前先按 OPERATIONS normalize-current 规程把遗留绝对 `current`
  指针改为相对形式（trusted verifier SHA256 与已验证 release 内副本一致）；
  匿名 `401`、crypto read token catalog `200`；API active、六个 binance timer enabled。
- Crypto 回滚 manifest 缺失已在切换前从同一 Git commit 重建并验证补齐
  （`manifests/d711414b….json`，与线上现存 release 字节一致）。
- 手动触发一轮 A 股模拟盘：`status=noop`、`reason=outside_delayed_session_window`、
  `selected_mode=rolling_eligible`、安全门全部关闭。对比 8 月 21 日的
  `fail_closed/minute_tradingdatas_request_failed`，数据面请求路径已恢复；
  最终结论以下一个交易日（周一）自然轮次为准。

## 当前运行面

- **A 股 / Tushare 数据面：** 有效 immutable release 为 `cf988f9`（2026-08-26 23:07 CST
  由 Controller 切换，回滚点 `21d0318`）；18082 API service active、通用 collector timer
  enabled。#350 调度合同已在源码完成、尚未 exact-main 发布：`cb_basic` 改为
  `daily_reference`（每轮 1 个空参快照）；income/balancesheet/cashflow/express/
  fina_indicator/fina_audit/pledge_stat 与 `cb_share` 离开 `on_demand`，改为
  `event`（与 `stk_holdernumber`/`disclosure_date` 的 ann_date 窗一致）并复用
  `cyq_chips` 的 `resumable_fanout.max_batches_per_run=1`。`top10_floatholders`
  仍 parked。生产触发/验收是发布后的运维步骤，本状态不声称已排期出数。
  `cn.news.flash` 已按预期墙钟自愈（查询面 success、零未来行），两 news 数据集的
  firecrawl 间歇失败等待 #354 新诊断字段回报类别分布。快照型数据集查询不带 as_of。
- **Crypto 隔离数据面：** immutable `current` 为 `300182f`；18083 API service 为
  `active/running`，匿名 `GET /v1/catalog` 返回 `401`。Spot、rules、book-ticker、USDM、
  OI dump 和 premium-index dump 六个 timer 均 enabled。切换后首轮 spot 采集
  40/40 数据集成功、零 retry。
- **已知残留：** crypto 共享存储锁冲突已在 `5ca8e3e` 改为有界等待（120s）+ 失败
  带错误详情；后续观察 journal 中 `lock_wait_seconds` 的出现频率与数值，确认
  长批次重叠不再造成整轮失败。若仍有等待超时，再评估错峰调度。
- **#327 WAL：** 可写采集连接请求 WAL、catalog/query 在 sidecar 存在时不用
  `immutable=1` 的代码已完成；广州生产库 journal mode 尚未在 write-pause /
  exact-main 发布路径切换，本状态不声称已释放。

## 能力和边界

- 数据集独立沿 `contract_ready -> observed -> stable` 推进。隔离观察 timer 可以持续收集
  证据；它既不等于 `stable`，也不允许无界扩容。
- TradingDatas 仅提供数据接入、采集、SQLite 事实、receipt/lineage 和固定
  `GET /v1/catalog` / `POST /v1/query`。它不拥有策略、资金、订单、成交、执行或任何
  TradingAgent authority。
- exact500 与 Crypto full-40 只约束各自命名覆盖声明，不阻止 PIT 安全的
  per-symbol/per-shard 模拟消费者。
- Prediction markets 与 CNFutures 保持暂停；本状态不产生真实交易、资金、订单或
  execution authority。

## 下一步

1. #350 调度合同已在源码完成（PR 待合入）：exact-main 发布后做生产触发与
   catalog/query 回读。`top10_floatholders` 仍 parked（无 ann_date 窗，不是本批
   同一 cadence 决策）。全宇宙覆盖靠 resumable_fanout 跨周期收敛，不是单轮扫完。
2. 依 #354 新诊断字段观察 firecrawl 失败类别分布（timeout / refused / other），
   决定 timeout_ms 上调或换源；顺手改进 validation_failed 的空
   `validation_reasons` 缺口。
3. #349：fina_mainbz 按探针提案落地（单码全史快照扇出 + 去 type 过滤），
   先解 dependency_seed_receipt_unresolved。
4. #327 WAL 代码已落地（可写 open 请求 WAL；生产 journal 切换仍待 write-pause +
   exact-main，本仓不自动部署 GZ）。
5. 归档候选交 Controller 收口（rt-min-daily-scan-budget 分支、rolling-simulation
   残留、ta-365/366、fix/firecrawl-bare-time-anchor 210c02e、约 60 陈旧分支）。
6. 发生值得长期追溯的异常、生产验收或迁移时，在 `docs/reports/YYYY-MM-DD-*.md` 新建日期化
   报告；普通变更由 Git history 追溯。
7. 下一次 material observation 直接替换本页，不追加事故年表，也不把这里的 SHA、count 或
   timer 状态复制进长期 API/Operations 合同。
