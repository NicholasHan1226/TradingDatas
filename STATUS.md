# TradingDatas 当前状态

检查日期：2026-09-09，Asia/Shanghai。本页只记录当前可核对结果；历史快照由 Git 保存。运行恢复、代码修复、发布及新数据采集分别验收。

## 当前生产与故障

- 本地/GitHub main 为 `b9208174726f895606ac1dd9ca64caa9b405136a`。现场两个 immutable `current` 和 API 进程物理目录均已是该版本；9 月 6 日文档中的「尚未切换」不再代表现场。服务器 `/opt/investment/TradingDatasSource` 为干净的 `12fd4097`，它不是运行版本权威。
- A 股认证 `GET /v1/catalog` 返回 503（0.360 秒）；匿名仍为 401。最近 cadence service 在约 2 秒内以 exit 2 / `schedule_run` / validation 失败。直接只读快照诊断定位为 `receipt database sidecars are stale`。
- 当时主库 18,464,755,712 字节，WAL 18,198,072 字节；SHM 显示 `mx_frame=4417`、`n_backfill=0`。主库 mtime 比 WAL 晚约 25 毫秒。普通只读收据来源审计为 `unmapped_source_count=0`；这不替代结构/完整性检查。
- Crypto 认证 catalog 为 200 / 6.417 秒 / 240 项，runtime state 均 success；匿名 401。此瞬时结果不是全部查询、连续稳定或完整历史证明。Crypto 不计入对外数据目录、套餐或接入数量。
- A 股 release 声明的 1092 个文件无字节漂移，但含 7 个额外 `__pycache__` 目录、25 个 `.pyc`。已按精确路径、字节数和 SHA-256 归档移出，随后两侧 `verify-current` 均通过；没有修改声明代码或放宽 manifest。

## 恢复与修复边界

- 先暂停 A 股 API/采集 timer，在独占 authority lock 下保留主库与 WAL/SHM 一致副本，源文件与备份 SHA-256 逐项相符；原件证据位于服务器私有 `/var/tmp/td-audit-20260909/`。未删除事实、收据或侧车，未改变 journal mode。恢复结果待本次数据库检查、checkpoint、服务及 API 回读完成后更新。
- 标准 SQLite 自然部分 checkpoint 可复现错误 mtime 拒绝：PASSIVE 返回 `(0,2,1)`，完整性检查 `ok`，旧读者和新读者分别看到正确快照。最小候选仅删除 mtime 推断，保留身份、完整侧车集合、页大小、SHM 双头、salt、帧/回填边界、schema 和双连接 epoch 检查。
- 新回归同时验证自然部分 checkpoint 可读与 WAL salt 篡改仍拒绝。问题、威胁边界及测试入口见 [WAL 复现记录](docs/reports/2026-09-09-wal-partial-checkpoint.md)。候选未合入/未部署，不把本地修复当成生产完成。双认证目录冷启动/重启小于 15 秒的门槛保持。

## 接入与下一批

- registry 的配置状态不是落库状态。下一批先核对已激活 `ci_index_member`、`index_member_all`、`fund_adj` 的真实 receipt/API，再决定有界采集；使用原 registry、真实源数据选出的 fanout seed 和原有 `max_batches_per_run=1`，不把探测 seed 固定进请求。
- `fund_company` 的 15371 行超出 10000 硬预算；`fund_nav`、`ft_mins` 和其它暂停项继续服从各自合同/权限/完整性边界。不批量解暂停，不抬预算，不重复 `etf_mins` 已知失败首批来伪造成功。
- empty、partial、provider_error 分别记录，单个上游问题不冻结其它独立接口。当前排期与采集/供数边界仍以 [OPERATIONS](docs/OPERATIONS.md) 为唯一入口。

## 本地收尾与其它边界

- 三个遗留工作树 `catalog-perf`、`nineturn`、`unregistered` 的改动已被主线覆盖，旧 patch 重放会回退后续修复。已整体移动至本机归档目录，未提交改动及 ignored 文件哈希一致，无需重复 PR。
- 本轮不变更真实交易、资金、账号、数据权限或支付。公共站、账户和真实商业开通不由上述内部供数检查推导；未发送邮件、创建客户 key 或执行付款。
- 长期事实入口：[API](docs/API.md)、[架构](docs/ARCHITECTURE.md)、[运维](docs/OPERATIONS.md)、[账户与订阅](docs/design/customer-identity-commerce-v1.md)。
