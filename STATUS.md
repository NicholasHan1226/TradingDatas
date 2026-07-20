# TradingDatas 当前状态

最后更新：2026-07-20。

## 结论

- 2026-07-20 transport 假设已纠正：当前真实上游通道不是官方 `api.tushare.pro` 直连，而是 Tushare-compatible QuickSync。身份固定为 `provider=tushare`、`transport_service=quicksync`；官方 Tushare 文档继续作为 dataset/schema/cadence 参考，QuickSync 文档与有界真实观测才是 endpoint/auth/permission/error/rate/concurrency 的运行事实源。
- 因此，现有 registry、通用 executor、SQLite facts/receipts 与固定 catalog/query API 可以继续复用，不需要迁库或逐接口重写；旧 official-direct release 与服务器 transport readback 对生产采集结论作废，整体仍为 NO-GO。该旧证据只证明代码层、发布布局和 fail-closed impaired 投影。
- 当前 QuickSync 账号的确切分钟/每日额度和并发上限尚未从可访问文档冻结，不允许沿用官方 Tushare 积分频次或猜测数值。修正版 production timer 必须保持 disabled，直到 provider-level transport 修复、1–5 dataset 零重试有界 canary、权限码/流控证据及 fresh API readback 全部通过。
- QuickSync transport 修正已形成 commit `a7e2e59aae877f9cbe0345ce80cbe0dae1e1fff8`：receipt 的 `config_hash` 现在同时绑定 provider-neutral ingest 合同和代码固定的 QuickSync transport profile；query 只有在 receipt hash 与当前 registry/profile 精确匹配时才输出 `transport_service=quicksync`，旧或不明 transport receipt 会 fail closed。最终定向矩阵为 70 项与 72 项通过，fresh reviewer 判定 P0=0、P1=0。
- 服务器 immutable canary release `a7e2e59aae877f9cbe0345ce80cbe0dae1e1fff8` 已在独立 SQLite 与 `127.0.0.1:18084` transient API 上完成真实纵向切片：`trade_cal` 8 行、`stock_basic` 5,607 行、`daily` 5,524 行，共 11,139 facts；成功数据均有 transaction receipt。catalog 返回 190 个 dataset，`daily` 与 `security_master` query 为 ready/non-degraded、lineage 完整且 transport 为 QuickSync；无认证请求为 401，同一 as-of 两次响应哈希一致；含未来上界的 `trade_cal` 负例返回 `data=[]`、failed/degraded、transport null。
- 当前 QuickSync DNS 有两个 IPv4 节点，2026-07-20 服务器 fresh TLS 复核中 `111.229.23.244` 的 TLS 1.3 与证书验证正常，而 `101.35.23.219` 对同一 SNI 持续返回 TLS internal error。首次真实采集因此写入一条 failed receipt，系统 resolver 轮换到健康节点后纵向切片成功。这个上游节点不一致在修复或获得稳定 endpoint 前阻断 production timer，不允许通过硬编码 IP、关闭证书校验或伪造 success 绕过。

- GitHub 仓库已从 `NicholasHan1226/SharedSignals` 重命名为 `NicholasHan1226/TradingDatas`。
- 本地新目录为 `/Users/nicholashan/Projects/Finance/TradingDatas`。
- 运行代码提交 `9fa5838451c07fc8a328e37dd70db33976a733d2` 已通过 fast-forward 进入 local、origin/main 与 GitHub main 历史。它在 `72876e4` 的单一 provider-neutral request-profile 配置上增加纯配置解析器，使 135 个已解析画像可以生成有界 one-shot 请求；当前 Git head 可包含后续状态文档提交，仍以实时 readback 为准。
- GitHub 集成和生产文件预置不等于生产 runtime；真实全量采集、正式 API readback 与消费者切换仍未完成。
- 历史隔离 pilot 已证明 `trade_cal`、`stock_basic`、`daily` 三个数据集的真实 Tushare -> SQLite -> receipt -> catalog/query 纵向切片；它不能替代当前服务器新 runtime 的 fresh 真实采集验收。
- 官方固定能力快照当前包含 239 个唯一 API 名称；首期境内只读候选当前分类为 190 个 in-scope。`in_scope` 不等于账号已授权或运行时已激活。
- registry 中的 `entitlement` 只表示经 QuickSync transport 真实受控调用观测到的 Tushare dataset 权限状态，不表示购买、按接口计费或订阅。官方积分说明不能替代 QuickSync 的账号权限、频率或并发证据。
- 2026-07-20 已对 190 个 in-scope 官方文档做一次批量读取验证：首轮 184 个成功，6 个瞬时网络失败在有界重试后均返回 200；190 个文档都包含可解析的输入参数与输出参数表。合同字段可以批量生成，不需要逐接口手写采集器。
- clean-slate capability catalog 已移除旧 114 接口计划、`legacy_coverage` 和 `in_legacy_inventory`，现在只由固定官方索引与范围分类生成；catalog SHA-256 为 `5bb4a2aae746e31b72ae610bdfe6a3feec469d6f4b8de769ce7e5395c20d3ea1`。
- `tools/snapshot_tushare_contracts.py` 已重新生成 `config/tushare_document_contracts.v1.yaml`：190 个合同、0 个解析错误，文件 SHA-256 为 `2cbc2b0012c8920b5cdcc89e9587a46bc4001d510c04990c00d39f502cff73da`，且绑定上述 catalog SHA。合同只证明文档解析完整，不代表账号 entitlement、activation 或真实采集已通过。
- 190 个合同中，144 个没有官方 `required=Y`，但这不等于都能安全空参数调用；46 个含 1–3 个显式必填入参，也不能猜值。当前 reviewed probe policy 将全集互斥分类为：3 个既有 activation evidence、3 个有界静态 probe、13 个条件参数待复核、111 个时间窗口待复核、14 个空参数待复核、46 个必填参数待配置。
- `config/tushare_request_profiles.v1.yaml` 已以单一配置覆盖其余 187 个合同：153 个具有已复核画像，135 个参数已解析，18 个需要 fresh stock anchor，总计 52 个仍为 plan-only。运行时 entitlement probe 仅接受显式选择 1–5 个上述 135 个 runtime-executable dataset，每个 dataset 最多一次调用、零重试、128 KiB 响应上限；原有 `bak_daily`、`fund_adj`、`fund_manager` 的字面量请求保持不变。52 个 plan-only 在读取凭证前拒绝。probe 只输出绑定 commit、合同、请求和结果的脱敏自哈希 evidence，不写 facts、ingest receipts 或 activation，也不自动启用 scheduler。
- `tools/compile_tushare_runtime_contracts.py` 已把 190/190 个官方文档合同编译进单一 provider-neutral registry；`trade_cal`、`stock_basic`、`daily` 继续使用已复核合同和 activation 证据，其余 187 个接口只作为 catalog-visible、append-only、paused 合同，不猜主键、请求参数、采集频率或 entitlement。运行合同与 registry 的编译/加载矩阵当前 98 项通过。
- 通用 executor 已实现 typed variants、fanout、offset pagination、资源预算、受限重试和进程级调用预算。每个真实 provider call 都有独立 transaction receipt；数据行与 success receipt 同 SQLite 事务提交；失败调用不会被后续 empty 终止页洗白，后续独立执行可以恢复状态。
- clean-slate 候选已删除 204 个旧系统路径并保留 86 个目标路径。独立 clean-overlay 验收结果为 P0=0、P1=0。当前 `9fa5838` 运行字节在本机 Python 3.12 完整套件为 `1411 passed, 1 skipped`；fresh reviewer 定向矩阵为 44 项与 128 项通过，服务器 request-profile/transport/storage 定向矩阵为 `457 passed`。`3fe693f` scheduler/deploy/API 定向矩阵此前在服务器专用账号下为 `52 passed`。前一提交 `e68d8fc` 的服务器 git-archive 完整 canary 为 `1347 passed, 1 skipped, 1 failed`；唯一 failure 是开发期源码 HEAD pin 测试要求 `.git`，而不可变发布 tar 按设计不包含 `.git`，其余服务器测试未失败。
- 服务器已从 GitHub commit `b4a6aac9a346519b9e6d744fe6521f0a9510c381` 建立隔离 18083 transient canary：独立 `tradingdatas` 用户、新 SQLite 与新认证材料；未认证 catalog 为 401，认证 catalog/query 为 200，catalog 投影 190 个数据集（3 active / 187 paused），旧 `/tushare` 与 `/source_status` 均为 404。首次空库查询如实返回 `unobserved`；随后把 QuickSync 凭证错误发送到官方 Tushare endpoint 得到 provider code `40101`。这个结果证明旧 transport 假设错误和 API impaired 投影可用，不是 QuickSync 权限或数据采集证据。
- 本机保留的 2026-07-16 QuickSync capability report 记录 258 个工具，并在 20 个受控读调用中观测到 15 个 success/data-or-empty 与 5 个 permission denied `40203`。它证明 QuickSync 具备 Tushare-compatible 能力及独立权限语义，但不证明服务器正式凭证、全量 entitlement、正确 cadence、频率或并发。
- 正式 `current` 已原子指向不可变 release `9fa5838451c07fc8a328e37dd70db33976a733d2`；使用 `COPYFILE_DISABLE=1` 生成的 release archive SHA-256 为 `20bd239f291227aefd1e35b02018b0cf706e8b8395240b0eb607fc6dfa91feb4`，共 115 个成员且不含 macOS AppleDouble，回滚目标完整保留为 `72876e42f0b14c77476d5732d9f3b474b4193272`。服务器专用账号下 entitlement plan 为 190 contracts / 187 profiles / 153 ready / 135 parameter-resolved / 135 runtime executable / 52 plan-only / 0 provider calls，定向 457 项通过且 6 个变更文件哈希与本地 `9fa5838` commit bytes 一致。唯一 collector service/timer 仍分别保持 static/inactive 与 disabled/inactive；正式 API 仍 disabled/inactive，正式 QuickSync 凭证仍缺失。production SQLite inode、大小、mtime、owner 与 mode 在切换前后不变，`quick_check=ok`、facts=0、receipts=0，尚未发生真实采集或消费者切换。
- 旧生产 `8082`、旧数据库、旧 cron 和旧文档不属于 TradingDatas 目标架构；在新生产与消费者切换前仅作为短期回滚源。

## 当前停止线

TradingDatas 尚未达到内部可接入停止线，原因：

1. provider-native target registry 已包含 190 个 dataset；其余 187 个已有统一 request profile，其中 135 个已具备有界 runtime request、52 个仍 plan-only，但它们仍全部 paused，尚未完成账号 entitlement、anchor/enum 补齐和真实频率验证；
2. 新 canary 凭证与三个真实数据集已验证，但正式 `/etc/tradingdatas/quicksync.token` 尚未安装，QuickSync 频率、并发及双 DNS 节点不一致仍未解决；因此正式 timer 继续 disabled，历史回填尚未开始；
3. 18084 已是可认证、可查询真实数据的隔离内部服务，但正式 18082 service 尚未切到 `a7e2e59`，TradingAgent/MarketGraph 也尚未完成 base URL 与 token 的消费者 readback；
4. 旧生产回滚源尚未经过新系统 readback 与消费者切换门禁，因此暂不能删除。

## 当前执行顺序

1. 先完成 provider-level QuickSync transport 修正与 fresh review，保持 registry、SQLite schema 和 catalog/query 不变；
2. 运行零调用 entitlement plan；正式 QuickSync 凭证通过 stat-only 安全门禁后，对 runtime-executable dataset 分小批执行有界 one-shot，人工审核权限码、entitlement、频控与并发 evidence；
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
- commit `718fed57544c70232fe8b0f55a688bc5f60011b9` 的 local、origin/main、GitHub main、entitlement probe 独立 review、服务器 426 项定向回归、immutable release、零调用 plan 和 inactive unit readback；旧 18082/18083 服务未改动。
- commit `72876e42f0b14c77476d5732d9f3b474b4193272` 的 local、origin/main、GitHub main、request-profile 独立 review、服务器 430 项定向回归、无 AppleDouble immutable release、零调用 plan 和 inactive unit readback；生产 SQLite 未改写。
- commit `9fa5838451c07fc8a328e37dd70db33976a733d2` 的 local、origin/main、GitHub main、request-profile resolver fresh independent review、服务器 457 项定向回归、无 AppleDouble immutable release、135 个 runtime request 的零调用 plan 和 inactive unit readback；生产 SQLite 未改写。
- commit `a7e2e59aae877f9cbe0345ce80cbe0dae1e1fff8` 的 fresh config-hash/lineage review、服务器 immutable release、独立 SQLite 真实 QuickSync 采集、authenticated catalog/query、impaired fail-closed、401 和 same-as-of readback；未切换正式 `current`、18082 或 timer。

未验证：

- 所有首期接口经 QuickSync transport 的账号 entitlement；
- QuickSync 健康 DNS/endpoint、权限码全集、频率与并发合同；
- 所有首期接口的真实采集与正确频率；
- 正式 18082 TradingDatas production runtime；
- 真实 Tushare facts/receipts 的 catalog/query readback；
- 内部消费者切换；
- 旧生产系统删除。

任何后续“完成”必须分别给出 local、GitHub、production files、production runtime、真实 receipts、API readback 和消费者证据。

外部受邀账户 Beta 的上游缓存、再分发和对外服务条款尚未书面核验；当前只推进内部只读服务，不把 QuickSync 可调用误报为可对外再分发。
