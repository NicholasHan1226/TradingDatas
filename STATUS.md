# TradingDatas 当前状态

最后更新：2026-07-20。

## 结论

- GitHub 仓库已从 `NicholasHan1226/SharedSignals` 重命名为 `NicholasHan1226/TradingDatas`。
- 本地新目录为 `/Users/nicholashan/Projects/Finance/TradingDatas`。
- 当前 local main、origin/main、GitHub main 与候选分支均为 `ea33fabfbac82c6e55ada31d32613ed8c73dac20`；clean-slate 代码已通过普通 fast-forward 进入 GitHub main。
- GitHub 集成不等于生产发布；TradingDatas 新生产 runtime、真实全量采集、API readback 与消费者切换仍未完成。
- provider-native pilot 已证明 `trade_cal`、`stock_basic`、`daily` 三个数据集的真实 Tushare -> SQLite -> receipt -> catalog/query 纵向切片。
- 官方固定能力快照当前包含 239 个唯一 API 名称；首期境内只读候选当前分类为 190 个 in-scope。`in_scope` 不等于账号已授权或运行时已激活。
- 2026-07-20 已对 190 个 in-scope 官方文档做一次批量读取验证：首轮 184 个成功，6 个瞬时网络失败在有界重试后均返回 200；190 个文档都包含可解析的输入参数与输出参数表。合同字段可以批量生成，不需要逐接口手写采集器。
- clean-slate capability catalog 已移除旧 114 接口计划、`legacy_coverage` 和 `in_legacy_inventory`，现在只由固定官方索引与范围分类生成；catalog SHA-256 为 `5bb4a2aae746e31b72ae610bdfe6a3feec469d6f4b8de769ce7e5395c20d3ea1`。
- `tools/snapshot_tushare_contracts.py` 已重新生成 `config/tushare_document_contracts.v1.yaml`：190 个合同、0 个解析错误，文件 SHA-256 为 `2cbc2b0012c8920b5cdcc89e9587a46bc4001d510c04990c00d39f502cff73da`，且绑定上述 catalog SHA。合同只证明文档解析完整，不代表账号 entitlement、activation 或真实采集已通过。
- 190 个合同中，144 个没有官方必填入参，可进入统一 entitlement probe；46 个含 1–3 个必填入参，必须先由配置提供真实参数或 fanout 来源，不能猜值。
- `tools/compile_tushare_runtime_contracts.py` 已把 190/190 个官方文档合同编译进单一 provider-neutral registry；`trade_cal`、`stock_basic`、`daily` 继续使用已复核合同和 activation 证据，其余 187 个接口只作为 catalog-visible、append-only、paused 合同，不猜主键、请求参数、采集频率或 entitlement。运行合同与 registry 的编译/加载矩阵当前 98 项通过。
- 通用 executor 已实现 typed variants、fanout、offset pagination、资源预算、受限重试和进程级调用预算。每个真实 provider call 都有独立 transaction receipt；数据行与 success receipt 同 SQLite 事务提交；失败调用不会被后续 empty 终止页洗白，后续独立执行可以恢复状态。
- clean-slate 候选已删除 204 个旧系统路径并保留 86 个目标路径。独立 clean-overlay 验收结果为 P0=0、P1=0，完整套件 `1348 passed, 1 skipped`；唯一 skip 是未配置的可选离线文档重建源，checked-in 生成物的确定性和当前性已另行验证。
- 旧生产 `8082`、旧数据库、旧 cron 和旧文档不属于 TradingDatas 目标架构；在新生产与消费者切换前仅作为短期回滚源。

## 当前停止线

TradingDatas 尚未达到内部可接入停止线，原因：

1. provider-native target registry 已包含 190 个 dataset，但只有三个 pilot dataset 具有 activation 证据；其余 187 个仍 paused，尚未完成真实 entitlement、参数和频率验证；
2. 全量 entitlement 探测、最新数据采集和历史回填尚未完成；
3. 新生产目录、service/timer、token 和内部消费者尚未完成 TradingDatas 名称切换；
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

未验证：

- 所有首期接口的账号 entitlement；
- 所有首期接口的真实采集与正确频率；
- TradingDatas 新生产 runtime；
- 全量 catalog/query readback；
- 内部消费者切换；
- 旧生产系统删除。

任何后续“完成”必须分别给出 local、GitHub、production files、production runtime、真实 receipts、API readback 和消费者证据。
