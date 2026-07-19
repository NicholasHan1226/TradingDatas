# TradingDatas 当前状态

最后更新：2026-07-20。

## 结论

- GitHub 仓库已从 `NicholasHan1226/SharedSignals` 重命名为 `NicholasHan1226/TradingDatas`。
- 本地新目录为 `/Users/nicholashan/Projects/Finance/TradingDatas`。
- 运行代码提交 `3fe693f345b19e203842b8e3b1ea80fbe050c283` 已通过普通 fast-forward 进入 GitHub main；它包含 `b4a6aac` 的专用 `tradingdatas` Token-owner 合同，以及唯一 registry-driven collection service/timer。后续状态文档提交不改变该运行字节，Git 引用的当前 head 仍以实时 readback 为准。
- GitHub 集成和生产文件预置不等于生产 runtime；真实全量采集、正式 API readback 与消费者切换仍未完成。
- 历史隔离 pilot 已证明 `trade_cal`、`stock_basic`、`daily` 三个数据集的真实 Tushare -> SQLite -> receipt -> catalog/query 纵向切片；它不能替代当前服务器新 runtime 的 fresh 真实采集验收。
- 官方固定能力快照当前包含 239 个唯一 API 名称；首期境内只读候选当前分类为 190 个 in-scope。`in_scope` 不等于账号已授权或运行时已激活。
- 2026-07-20 已对 190 个 in-scope 官方文档做一次批量读取验证：首轮 184 个成功，6 个瞬时网络失败在有界重试后均返回 200；190 个文档都包含可解析的输入参数与输出参数表。合同字段可以批量生成，不需要逐接口手写采集器。
- clean-slate capability catalog 已移除旧 114 接口计划、`legacy_coverage` 和 `in_legacy_inventory`，现在只由固定官方索引与范围分类生成；catalog SHA-256 为 `5bb4a2aae746e31b72ae610bdfe6a3feec469d6f4b8de769ce7e5395c20d3ea1`。
- `tools/snapshot_tushare_contracts.py` 已重新生成 `config/tushare_document_contracts.v1.yaml`：190 个合同、0 个解析错误，文件 SHA-256 为 `2cbc2b0012c8920b5cdcc89e9587a46bc4001d510c04990c00d39f502cff73da`，且绑定上述 catalog SHA。合同只证明文档解析完整，不代表账号 entitlement、activation 或真实采集已通过。
- 190 个合同中，144 个没有官方必填入参，可进入统一 entitlement probe；46 个含 1–3 个必填入参，必须先由配置提供真实参数或 fanout 来源，不能猜值。
- `tools/compile_tushare_runtime_contracts.py` 已把 190/190 个官方文档合同编译进单一 provider-neutral registry；`trade_cal`、`stock_basic`、`daily` 继续使用已复核合同和 activation 证据，其余 187 个接口只作为 catalog-visible、append-only、paused 合同，不猜主键、请求参数、采集频率或 entitlement。运行合同与 registry 的编译/加载矩阵当前 98 项通过。
- 通用 executor 已实现 typed variants、fanout、offset pagination、资源预算、受限重试和进程级调用预算。每个真实 provider call 都有独立 transaction receipt；数据行与 success receipt 同 SQLite 事务提交；失败调用不会被后续 empty 终止页洗白，后续独立执行可以恢复状态。
- clean-slate 候选已删除 204 个旧系统路径并保留 86 个目标路径。独立 clean-overlay 验收结果为 P0=0、P1=0。当前运行字节在本机 Python 3.12 完整套件为 `1358 passed, 1 skipped`；新 release 的 scheduler/deploy/API 定向矩阵在服务器专用账号下为 `52 passed`。前一提交 `e68d8fc` 的服务器 git-archive 完整 canary 为 `1347 passed, 1 skipped, 1 failed`；唯一 failure 是开发期源码 HEAD pin 测试要求 `.git`，而不可变发布 tar 按设计不包含 `.git`，其余服务器测试未失败。
- 服务器已从 GitHub commit `b4a6aac9a346519b9e6d744fe6521f0a9510c381` 建立隔离 18083 transient canary：独立 `tradingdatas` 用户、新 SQLite 与新认证材料；未认证 catalog 为 401，认证 catalog/query 为 200，catalog 投影 190 个数据集（3 active / 187 paused），旧 `/tushare` 与 `/source_status` 均为 404。首次空库查询如实返回 `unobserved`；随后旧 QuickSync Token 对官方 Tushare endpoint 返回 provider code `40101`，当前查询如实返回 `failed`、`degraded=true`、0 facts、1 failed receipt，同请求除 request_id 外可复现。
- 官方 Tushare 连接器已在 2026-07-20 本次客户端会话实时读回 `trade_cal`、`stock_basic` 与 `daily`；但服务器当前只有旧 SharedSignals 的 HTTP QuickSync 配置，没有正式 Tushare HTTPS Token 文件。不能把客户端连接器或旧 QuickSync 误报为服务器真实 Tushare 采集。
- 正式 `current` 已原子指向不可变 release `3fe693f345b19e203842b8e3b1ea80fbe050c283`；release archive SHA-256 为 `4ce95c746f45e5b82a56dae289269d51375d48569037f56b6afd7b16ce02100a`。唯一 collector service/timer 已安装并通过 `systemd-analyze verify`，但分别保持 static/inactive 与 disabled/inactive；正式 API 仍 disabled/inactive。production SQLite `quick_check=ok` 且 0 facts / 0 receipts，旧 SharedSignals 18082 仍 active，尚未发生切换。
- 旧生产 `8082`、旧数据库、旧 cron 和旧文档不属于 TradingDatas 目标架构；在新生产与消费者切换前仅作为短期回滚源。

## 当前停止线

TradingDatas 尚未达到内部可接入停止线，原因：

1. provider-native target registry 已包含 190 个 dataset，但只有三个 pilot dataset 具有 activation 证据；其余 187 个仍 paused，尚未完成真实 entitlement、参数和频率验证；
2. 服务器尚未安装由 `tradingdatas` 用户持有、权限精确为 `0600` 的正式 Tushare Token；因此真实 entitlement、最新数据采集和历史回填尚未完成；
3. 18083 仅为隔离 transient canary；正式 release 与 unit 虽已预置，但正式 18082 service 和采集 timer 均未启用，内部消费者也尚未完成 TradingDatas 名称切换；
4. 旧生产回滚源尚未经过新系统 readback 与消费者切换门禁，因此暂不能删除。

## 当前执行顺序

1. 对账号权限做安全探测，按 entitlement 激活并冻结真实频率；
2. 按安全发布门禁建立 TradingDatas 新生产 runtime；
3. 先采最新数据并完成内部 `catalog/query` API readback；
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
- commit `3fe693f345b19e203842b8e3b1ea80fbe050c283` 的 local、origin/main、GitHub main、独立 scheduler review、完整本地回归、服务器定向回归、immutable release 和 installed-but-inactive systemd readback；旧 18082 服务未改动。

未验证：

- 所有首期接口的账号 entitlement；
- 所有首期接口的真实采集与正确频率；
- 正式 18082 TradingDatas production runtime；
- 真实 Tushare facts/receipts 的 catalog/query readback；
- 内部消费者切换；
- 旧生产系统删除。

任何后续“完成”必须分别给出 local、GitHub、production files、production runtime、真实 receipts、API readback 和消费者证据。
