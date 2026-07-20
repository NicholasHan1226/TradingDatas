# TradingDatas 当前状态

最后更新：2026-07-21。

## 结论

- 2026-07-20 transport 假设已纠正：当前真实上游通道不是官方 `api.tushare.pro` 直连，而是 Tushare-compatible QuickSync。身份固定为 `provider=tushare`、`transport_service=quicksync`；官方 Tushare 文档继续作为 dataset/schema/cadence 参考，QuickSync 文档与有界真实观测才是 endpoint/auth/permission/error/rate/concurrency 的运行事实源。
- 因此，现有 registry、通用 executor、SQLite facts/receipts 与固定 catalog/query API 可以继续复用，不需要迁库或逐接口重写；旧 official-direct release 与服务器 transport readback 对生产采集结论作废，整体仍为 NO-GO。该旧证据只证明代码层、发布布局和 fail-closed impaired 投影。
- 2026-07-21 CST（证据时间 2026-07-20Z）已通过文档指定的 HTTP compatibility endpoint 对首期 190/190 个 API 做真实有界调用并形成唯一接口矩阵，缺失 0、额外 0：167 `success`、3 `empty`、14 `permission_denied`、1 `credential_rejected`、5 `unsupported_api`。该矩阵确认 145 个通过 contract-match 候选门禁；通用数字字段修复又在代码层补回 4 个接口的 29 个字段，形成 149 个候选，但它们都不因此自动 activation：新增 4 个仍待 fresh HTTPS provider -> SQLite -> receipt -> API 纵向 readback。17 个 schema drift、1 个质量异常和其余 impaired 接口继续 paused。矩阵 SHA-256 为 `ea102cd7b189e1c7d8d0c208c303b308ebf3a07bd4c9b682c8b10ada9ccfb1e1`，明确 `production_ready=false`；它不是正式 HTTPS server readback。
- 频率实测只证明健康单一 HTTPS 节点的小响应 request-start 能力至少 200 次/分钟：并发 4 下 210/210 成功，全部 request start 在 59.714 秒内，零限频、零 transport error、零重试；脱敏证据 SHA-256 为 `660c5ef6f1567b9be4673822f891d7ca3b388a6aad37224b2e62fdaa0b1cb935`。当前 `main` 代码设置保护门禁 200 次/60 秒、并发 4，但这不是 QuickSync 合同额度或已部署 production 配置；混合大响应、每日额度与 DNS failover 仍待验收。
- observations 代码提交 `c4fc5a1872b2fcae76b9e20a82911bdc88615b67` 已经 local main、origin/main 与 live GitHub 三方读回一致；其基线 `7ce02ea` 包含通用 transport commit `7bf7f71`、数字字段 commit `c92b001` 与证据文档 commit `7ce02ea`。通用 transport 在一个共享 monotonic deadline 内完成 DNS snapshot direct-connect、TLS 1.3、仅 pre-send 节点切换、send 后零 replay及 `rate_limited` 诚实分类；数字字段修复一次扩展 provider output field grammar，并保留 API/参数/window 的严格 grammar。observations 精确 17 路径经双路 fresh review 确认 P0/P1=0，主线定向回归 58 项通过，Ruff/compile/diff-check 通过；服务器、production 与真实 HTTPS 全接口 readback 仍尚未完成。
- QuickSync transport 修正已形成 commit `a7e2e59aae877f9cbe0345ce80cbe0dae1e1fff8`：receipt 的 `config_hash` 现在同时绑定 provider-neutral ingest 合同和代码固定的 QuickSync transport profile；query 只有在 receipt hash 与当前 registry/profile 精确匹配时才输出 `transport_service=quicksync`，旧或不明 transport receipt 会 fail closed。最终定向矩阵为 70 项与 72 项通过，fresh reviewer 判定 P0=0、P1=0。
- 服务器 immutable canary release `a7e2e59aae877f9cbe0345ce80cbe0dae1e1fff8` 已在独立 SQLite 与 `127.0.0.1:18084` transient API 上完成真实纵向切片：`trade_cal` 8 行、`stock_basic` 5,607 行、`daily` 5,524 行，共 11,139 facts；成功数据均有 transaction receipt。catalog 返回 190 个 dataset，`daily` 与 `security_master` query 为 ready/non-degraded、lineage 完整且 transport 为 QuickSync；无认证请求为 401，同一 as-of 两次响应哈希一致；含未来上界的 `trade_cal` 负例返回 `data=[]`、failed/degraded、transport null。
- 当前 QuickSync DNS 有两个 IPv4 节点，2026-07-20 服务器 fresh TLS 复核中 `111.229.23.244` 的 TLS 1.3 与证书验证正常，而 `101.35.23.219` 对同一 SNI 持续返回 TLS internal error。首次真实采集因此写入一条 failed receipt，系统 resolver 轮换到健康节点后纵向切片成功。这个上游节点不一致在修复或获得稳定 endpoint 前阻断 production timer，不允许通过硬编码 IP、关闭证书校验或伪造 success 绕过。

- GitHub 仓库已从 `NicholasHan1226/SharedSignals` 重命名为 `NicholasHan1226/TradingDatas`。
- 本地新目录为 `/Users/nicholashan/Projects/Finance/TradingDatas`。
- 历史提交 `9fa5838451c07fc8a328e37dd70db33976a733d2` 曾实现 request-profile 解析器。当前 profile/resolver 仅以 deprecated migration-only 形式保留官方输入映射，不是 activation authority，也不得进入 collector、scheduler 或生产命令；待映射迁入 provider-native runtime contracts 后删除。
- GitHub 集成和生产文件预置不等于生产 runtime；真实全量采集、正式 API readback 与消费者切换仍未完成。
- 历史隔离 pilot 已证明 `trade_cal`、`stock_basic`、`daily` 三个数据集的真实 Tushare -> SQLite -> receipt -> catalog/query 纵向切片；它不能替代当前服务器新 runtime 的 fresh 真实采集验收。
- 官方固定能力快照当前包含 239 个唯一 API 名称；首期境内只读候选当前分类为 190 个 in-scope。`in_scope` 不等于账号已授权或运行时已激活。
- registry 中的 `entitlement` 只表示经 QuickSync transport 真实受控调用观测到的 Tushare dataset 权限状态，不表示购买、按接口计费或订阅。官方积分说明不能替代 QuickSync 的账号权限、频率或并发证据。
- 2026-07-20 已对 190 个 in-scope 官方文档做一次批量读取验证：首轮 184 个成功，6 个瞬时网络失败在有界重试后均返回 200；190 个文档都包含可解析的输入参数与输出参数表。合同字段可以批量生成，不需要逐接口手写采集器。
- clean-slate capability catalog 已移除旧 114 接口计划、`legacy_coverage` 和 `in_legacy_inventory`，现在只由固定官方索引与范围分类生成；catalog SHA-256 为 `5bb4a2aae746e31b72ae610bdfe6a3feec469d6f4b8de769ce7e5395c20d3ea1`。
- `tools/snapshot_tushare_contracts.py` 已重新生成 `config/tushare_document_contracts.v1.yaml`：190 个合同、0 个解析错误，文件 SHA-256 为 `2cbc2b0012c8920b5cdcc89e9587a46bc4001d510c04990c00d39f502cff73da`，且绑定上述 catalog SHA。合同只证明文档解析完整，不代表账号 entitlement、activation 或真实采集已通过。
- `config/quicksync_interface_observations.v1.yaml` 已取代旧 manual entitlement probe/policy，成为唯一 QuickSync 权限、兼容性观测与 activation 输入。它绑定矩阵 SHA `ea102cd7b189e1c7d8d0c208c303b308ebf3a07bd4c9b682c8b10ada9ccfb1e1` 与 190 API 集合 SHA，并互斥分类为 145 contract match、4 个数字字段修复、17 schema subset、1 quality anomaly、3 empty、14 permission denied、1 credential rejected、5 unsupported。deprecated request-profile/resolver 只保留官方输入映射迁移信息，不参与上述权威链。
- `tools/compile_tushare_runtime_contracts.py` 与 `tools/compile_provider_native_registry.py` 把 190/190 个官方合同和上述观测编译进单一 provider-neutral registry；仅 `trade_cal`、`stock_basic`、`daily` 保持已有 active 证据，其余 187 个全部 paused。HTTP compatibility 矩阵明确 `production_ready=false`，不得用候选分类自动启用 scheduler。
- 通用 executor 已实现 typed variants、fanout、offset pagination、资源预算、受限重试和进程级调用预算。每个真实 provider call 都有独立 transaction receipt；数据行与 success receipt 同 SQLite 事务提交；失败调用不会被后续 empty 终止页洗白，后续独立执行可以恢复状态。
- clean-slate 候选已删除 204 个旧系统路径并保留 86 个目标路径。旧 probe 测试数量只作为历史提交证据；request-profile 测试只证明迁移资料与官方文档/registry/observations 自洽，均不代表 runtime activation。当前候选必须以 observations -> compiled registry 的 fresh 回归重新验收。
- 服务器已从 GitHub commit `b4a6aac9a346519b9e6d744fe6521f0a9510c381` 建立隔离 18083 transient canary：独立 `tradingdatas` 用户、新 SQLite 与新认证材料；未认证 catalog 为 401，认证 catalog/query 为 200，catalog 投影 190 个数据集（3 active / 187 paused），旧 `/tushare` 与 `/source_status` 均为 404。首次空库查询如实返回 `unobserved`；随后把 QuickSync 凭证错误发送到官方 Tushare endpoint 得到 provider code `40101`。这个结果证明旧 transport 假设错误和 API impaired 投影可用，不是 QuickSync 权限或数据采集证据。
- 本机保留的 2026-07-16 QuickSync capability report 记录 258 个工具，并在 20 个受控读调用中观测到 15 个 success/data-or-empty 与 5 个 permission denied `40203`。它证明 QuickSync 具备 Tushare-compatible 能力及独立权限语义，但不证明服务器正式凭证、全量 entitlement、正确 cadence、频率或并发。
- 正式 `current` 仍指向包含历史 probe 执行路径与旧 request-profile 运行耦合的 release `9fa5838451c07fc8a328e37dd70db33976a733d2`，因此不能作为新运行入口；其 archive 与回滚证据继续保留。当前 profile/resolver 仅是未接入运行面的迁移资料。唯一 collector service/timer 仍分别保持 static/inactive 与 disabled/inactive；正式 API 仍 disabled/inactive，正式 QuickSync 凭证仍缺失。production SQLite 未改写，尚未发生正式真实采集或消费者切换。
- 旧生产 `8082`、旧数据库、旧 cron 和旧文档不属于 TradingDatas 目标架构；在新生产与消费者切换前仅作为短期回滚源。

## 当前停止线

TradingDatas 尚未达到内部可接入停止线，原因：

1. provider-native target registry 已包含 190 个 dataset，3 active / 187 paused；观测分类已冻结，但候选仍未完成正式 HTTPS provider -> SQLite -> receipt -> API readback 和真实 cadence 验证；
2. 新 canary 凭证与三个真实数据集已验证，健康单节点小响应 request-start 吞吐下限已冻结；但正式 `/etc/tradingdatas/quicksync.token` 尚未安装，混合响应和双 DNS 节点的安全 failover 还没有经过新 release 的服务器 readback，每日额度也未知；因此正式 timer 继续 disabled，历史回填尚未开始；
3. 18084 已是可认证、可查询真实数据的隔离内部服务，但正式 18082 service 尚未切到 `a7e2e59`，TradingAgent/MarketGraph 也尚未完成 base URL 与 token 的消费者 readback；
4. 旧生产回滚源尚未经过新系统 readback 与消费者切换门禁，因此暂不能删除。

## 当前执行顺序

1. 把 190 接口矩阵作为独立、可校验的 transport observation 配置编译进 entitlement/activation，保持 SQLite schema 和 catalog/query 公共合同不变；
2. 正式 QuickSync 凭证通过 stat-only 安全门禁后，对 activation candidate 分小批执行 HTTPS provider -> SQLite -> receipt -> API one-shot readback；
3. 只激活已授权且完成频率复核的数据集，先采最新数据并完成内部 `catalog/query` API readback；
4. 后台回填历史数据；
5. 切换内部消费者；
6. 仅在回滚证据与消费者 readback 通过后删除旧生产代码和服务，数据库及历史数据另行保留或迁移。

## 已验证与未验证

已验证：

- GitHub repository rename；
- 新本地 clone 与远端 main 一致；
- 三个 pilot dataset 的历史隔离纵向切片；
- capability snapshot 与 generic cadence planner 的本地/GitHub 代码层。
- 本地 clean-slate 候选的 190 个 provider-neutral 合同、通用采集与 SQLite transaction receipt；
- 本地候选的独立 clean-overlay 完整回归、静态门禁及 86 PRESENT / 204 DELETED 精确范围。
- clean-slate commit `ea33fabfbac82c6e55ada31d32613ed8c73dac20` 的 local main、origin/main 与 GitHub main readback。
- commit `b4a6aac9a346519b9e6d744fe6521f0a9510c381` 的独立 Token-owner review、服务器隔离 API canary 与 impaired-state readback。
- commit `3fe693f345b19e203842b8e3b1ea80fbe050c283` 的独立 scheduler review、完整本地回归和 installed-but-inactive systemd readback；
- 历史证据：commit `718fed57544c70232fe8b0f55a688bc5f60011b9`、`72876e42f0b14c77476d5732d9f3b474b4193272` 与 `9fa5838451c07fc8a328e37dd70db33976a733d2` 曾完成 manual entitlement probe/request-profile/resolver 的独立 review 与服务器定向回归。probe/policy 已退役；profile/resolver 仅作迁移资料。它们都不定义当前 runtime、activation 或请求合同。
- commit `a7e2e59aae877f9cbe0345ce80cbe0dae1e1fff8` 的 fresh config-hash/lineage review、服务器 immutable release、独立 SQLite 真实 QuickSync 采集、authenticated catalog/query、impaired fail-closed、401 和 same-as-of readback；未切换正式 `current`、18082 或 timer。

未验证：

- 190 个接口在正式 HTTPS transport 与服务器 release 上的逐项 readback；
- QuickSync 每日额度及双 DNS 节点 failover 的 production runtime 证明；
- 所有首期接口的真实采集与正确频率；
- 正式 18082 TradingDatas production runtime；
- 真实 Tushare facts/receipts 的 catalog/query readback；
- 内部消费者切换；
- 旧生产系统删除。

任何后续“完成”必须分别给出 local、GitHub、production files、production runtime、真实 receipts、API readback 和消费者证据。

外部受邀账户 Beta 的上游缓存、再分发和对外服务条款尚未书面核验；当前只推进内部只读服务，不把 QuickSync 可调用误报为可对外再分发。
