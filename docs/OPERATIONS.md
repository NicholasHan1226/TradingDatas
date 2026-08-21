# TradingDatas Operations

## 目标生产布局

```text
/opt/investment/releases/tradingdatas/<immutable-release>
/opt/investment/releases/tradingdatas/current
/opt/investment/releases/tradingdatas/manifests/<immutable-release>.json
/opt/investment-data/tradingdatas/read_model/provider_native.sqlite
/etc/tradingdatas/internal-api.env
```

仓库当前只定义以下 systemd 服务面：

- `tradingdatas-v1-internal.service`
- `tradingdatas-provider-native-collect.service`
- `tradingdatas-provider-native-collect.timer`

API service 只监听 `127.0.0.1:18082`，只提供 `GET /v1/catalog` 与
`POST /v1/query`，并以独立 `tradingdatas` 账号只读访问数据目录。仓库不安装
公网入口或 provider 专用路由。

采集调度只允许一个 registry-driven runner；timer 每五分钟只唤醒一次 cadence
planner，不拥有 dataset 或 provider API 清单。不再使用项目 crontab，也不按
Tushare API 增加 service/timer。生产 timer 只采集每个 automatic dataset 的最新
eligible window；它不会隐式启动历史回填。历史回填必须经同一 registry 的外部、有界
one-shot manifest 明确选择，且继续受同一 transport budget 约束。没有正式 QuickSync
凭证文件、冻结的 transport budget、真实 latest collection 与 fresh readback
前，不在 production 启用采集 timer。采集 unit 只调用一次不带 dataset 参数的通用 cadence
planner：所有 registry 中 `active` 且 cadence 为 automatic 的绑定由同一计划器按预算、窗口和
receipt 状态选择；`on_demand` 绑定始终不会被 timer 自动执行。受审沪深主板
`cn.dataset.rt_min` 5MIN 是其中一个受控 canary：当前 registry 的 5,963 个冻结代码以每批 300
拆为 20 个确定性批次；resumable cursor v2 每轮最多推进 20 批，并以 bar_time 窗口在每根
5 分钟 bar 独立重置游标，因此一个 bar 内完整扫完 5,963 个冻结代码。只有带匹配
dataset/provider、config hash、frozen universe、batch identity 与
success/empty 状态的 receipt 才能推进游标；失败批次只在本数据集内优先重试，不能借用其它
dataset、其它 universe 或其它 config 的 receipt。这只证明配置在 intraday 每轮账号/provider 24、
rt_min 单 API override 60 的本地门禁内，不证明 provider entitlement、完整率、稳定性、低延迟或 production runtime
已接纳。每轮仍须保留实际 bar time、observed_at 和 receipt；上游晚一根 bar 时不得声明低延迟或执行
可用。它不是研究或交易 Universe。`cn.dataset.rt_min_daily` 的 security-master fanout 每批 10，在 registry 中保持 dataset-local
`paused`；这不撤销它的 executable/ingest-ready 合同，也不阻断其它
dataset。只有新的有界证据证明完整 cohort 可在相同全局门禁内完成，才可恢复其精确
`active_evidence` 并重编 registry。回滚时切回上一 immutable registry/release 并更新 activation-wave
输入 hash；不删除既有 facts/receipts，也不新增服务或 timer。
`session_minute` 还必须同时命中 registry 的开市日历和配置的本地上午/下午窗口；
午休与收盘后均为 `not_due`，不得为“补一根分钟线”继续请求上游。在同一计划优先级内，
所有 `session_minute` 合同先于其它 automatic 合同执行；该排序只按 cadence class 决定，
不为某个 dataset、provider 或消费者增加专用分支。

`daily_reference` 的下一日期窗口只适用于 registry 声明为 `trade_calendar` 的已知未来事实，
用于在 provider 已发布时提前写入下一交易日的 `is_open` / `pretrade_date`。其它日参考数据仍只
请求当前可用日期，不能因日历预取而创建未来数据 receipt。

`session_minute` 的最小成功间隔为 240 秒：五分钟 timer 在上一个窗口于临界时刻完成
（例如完成后 265 秒触发下一次）时，仍会规划下一窗口；失败重试、开市日历、窗口和预算
规则不变。当前 `standard` budget 每轮最多 12 个账号请求、12 个 provider 请求，
同一 provider API 最多 6 个请求。runner 仍是串行、每五分钟最多运行一次；历史
QuickSync 小响应探测不是当前 scheduler 容量或上游合同额度。发布前必须在目标 release 上证明完整
一轮能在下一次 timer 触发前结束；若超时、出现上游限流或任一 current-window receipt 失败，
回退到前一 immutable release，不通过重试或静默跳过伪造连续性。

回滚固定为先 `systemctl disable --now tradingdatas-provider-native-collect.timer`，再由已验证
release manifest 切回不含该 canary 的 release；不删除 SQLite facts 或 receipts。

planner 对每个 `dataset + provider + request_window` 只生成一个包含 registry 全部 request variants 的 plan；snapshot 数据集只要任一 variant 到期，就重新运行完整 cohort，不能因一个 sibling receipt 跳过其余 variants。scheduler 每次 run 生成显式 UUID root，并按稳定 plan ordinal 派生 window attempt root；one-shot collection 也必须执行完整 registry cohort，但只把自己的 root 视为单 window execution。生产 timer 只处理当前/最新 window；有界历史回填不占用它的周期。

收据的完整性校验按 dataset 隔离：某一 dataset 的损坏、伪造或时间非法 receipt 必须让该 dataset 以 `invalid_receipt_authority` 停止计划和 provider 调用；它不能为自身或其它 dataset 提供事实，也不能让无关 dataset 的受控计划停摆。该 skip 的 scheduler 输出只附带验证器已生成、稳定排序的 `reasons` 代码列表，不暴露 receipt payload、provider rows 或运行路径；其它 skip 的输出结构保持不变。

### `market_ingest_runs` 的收据读取索引

`market_ingest_runs` 是追加式收据运行日志。收据历史、evidence 与 journal 的验证读取必须按
目标 dataset 隔离：已知其它 dataset 的行不消耗该 dataset 的读取预算，未知 source 的 tombstone
行仍须纳入验证，避免以索引跳过未知 authority。`market_ingest_runs_source_idx (source)` 是可选的
单列索引合同：旧 SQLite 在索引缺失时仍可验证；目标 release 首次成功写入 receipt 时，会在同一
写入事务内幂等创建该索引。若存在同名但列定义不精确的自定义索引，schema 验证必须失败，不能
继续读取或静默替换。该变更不需要单独数据库迁移，也不表示 production release 已切换。

若已验证的 release 需要回退索引本身，可在维护窗口执行
`DROP INDEX market_ingest_runs_source_idx`；不得删除 `market_ingest_runs` 或任一 receipt/fact。
代码回滚继续遵循 immutable release 切换与同层 receipt/API readback，索引缺失在旧 release 中是
允许状态。

对于已经执行的 dataset，scheduler summary 可附带 `receipt_provenance`：它只按本轮已持久化且通过同一 receipt validator 的 receipt ID 投影 `status`、`returned`/`validated`/`rejected`/`committed` 计数、稳定的 `error_layer`、原始结构化 `error_codes` 与 `validation_reasons`。无法通过验证的 receipt 只保留其稳定 reason code，计数字段为 `null`；`validation_failed` 默认归入通用 `ingest_validation` 层，只有持久化证据证明更具体层级时才细分，未持久化时不推断确切谓词；读取 provenance 失败不会改变采集结果。该字段不包含 receipt payload、provider rows、请求凭据或本机路径，且不替代 SQLite receipt authority。

非可恢复 fanout 的覆盖缺口在公开采集路径中保留顶层 `validation_failed`，并附带脱敏的
`validation_fanout_coverage_incomplete` reason code；scheduler 的 `error_layer` 仍为
`ingest_validation`，不会暴露 fanout 值、provider rows、摘要或路径。声明
`resumable_fanout` 的分钟批次允许保留请求集合内实际返回的严格子集，单只股票缺失只降低
该批 coverage；停牌代码带回的历史最后 bar 也按 `[ts_code,time]` 独立保留。越界代码、重复
主键和非可恢复批次的跨日快照仍失败。允许空结果和禁止空结果继续遵循各自既有策略。

生产 one-shot 必须通过安装好的 collector service 启动，使 systemd 按 unit 合同创建并回收
`RuntimeDirectory=tradingdatas`。不得从 shell 直接执行 runner 却继续使用
`/run/tradingdatas/collect.lock`；这种调用绕过 systemd，运行账号无权创建 `/run` 子目录。
隔离验证如需直接运行，只能使用该隔离目录内的私有 lock path，不能借此启用 timer、改变
正式 cadence 或新增第二套调度入口。

## Activation wave

`config/provider_native_activation_waves.v1.yaml` 是 repository-owned 的受审波次
清单。它只记录 canonical `dataset_id` 与 runtime registry、schedule 的输入 SHA-256；
不得放入 provider 参数、字段、token、request values 或任何 dataset-specific 行为。选择
`--activation-wave <wave_id>` 时，runner 会在打开 SQLite、执行 provider 调用或产生写入前
一次读取 registry 与 schedule 原始字节，先核对输入 hash，再从同一份字节解析实际用于
active 检查、规划和执行的对象，避免路径复读或外部对象造成合同脱绑定。清单内所有 wave
都会在选择前验证 exact keys、canonical ID、排序、全局去重与 active/entitled 状态；未知
wave、布尔版本、别名、额外字段、非 active/entitled 项或任一输入 hash 漂移均 fail
closed。波次外的 active dataset 以
`not_selected` 记录，global flock、planner/runtime budgets、retry、receipt 和公开输出
redaction 均不变。

省略 `--activation-wave` 时保持完整 automatic scheduler 行为；这是正式采集 unit 的唯一入口。
`pilot_existing` 仅用于受控、只选择当前窗口的历史复现，不是 production 范围开关。其中的
`cn.dataset.rt_min` 5 分钟 canary 不是新增 entitlement、全市场分钟覆盖、研究/交易
Universe 或低延迟执行证据：每轮必须保留实际 bar time、observed_at 和 receipt，不能把上游
延迟伪装成实时数据。上述 5,963-code / 300-per-batch / cursor-v2 只是受审的 registry 请求形状；真实供应能力
仍须由目标 release 的 provider、receipt、catalog/query 与 consumer fresh readback 分层证明。

正式 registry 还可以声明受审的 `dependency_seed_authorities`。它只绑定已持久化
receipt、来源字段/schema 与明确列出的依赖 API；编译器仅把这些依赖标为
`probe_state=executable`、`ingest_contract_state=ready`，仍保持 `activation_state=paused`。
未列出的 sibling、缺少 receipt authority 或其它未解析 requiredness/anchor 的 API 继续
fail-closed，不会因为同一 source dataset 自动扩张。receipt payload、provider rows 和 token
不写入仓库；receipt_id 与 data_through 作为不可变 authority binding 保留。Controller 发布前
必须用同一 registry/compiler、collector receipt 与 catalog/query 做有界 readback。
raw HTTPS sidecar 可以引用已经 formal 注册的 dependency seed authority，而不必在同一批次再次
把 seed producer 作为 result 发出；compiler 仍逐字段精确比较 dataset、field、schema、receipt_id
与 data_through，并要求 dependent API 已在 authority 的显式清单中。不匹配、未列出的 sibling
或缺少 fresh result 的 API 都保持 fail-closed/paused，不会由 seed authority 推断 provider rows
或扩大 activation。
只读 plan 可按以下方式检查：

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python tools/run_provider_native_schedule.py --activation-wave pilot_existing
```

`daily_reference` 不假设上游提前提供下一自然年的完整交易日历；历史覆盖仍由
bounded backfill 逐段补齐。固定未来天数不能被当成 provider 能力事实：只有
registry 明确声明、transport 实际观测且独立回归覆盖的日历窗口才能受控请求下一日。
future-empty 响应必须按既有完整性合同诚实处理，不能把其它日参考数据推进到未来。

## 有界 one-shot batch

`tools/collect_provider_dataset.py --batch-file <external-json>` 是唯一的按需批量
采集入口，不新增 systemd unit、timer、cron 或公共 API。外部 JSON manifest 固定为：

```json
{
  "version": 1,
  "items": [
    {"dataset_id": "cn.example.dataset", "request_window": {}}
  ]
}
```

最多 32 项，`dataset_id` 必须 canonical、唯一且排序；每项只能使用该 registry 已声明的
window keys。plan 模式会先校验整批所有 item，失败时不会构造 provider client 或打开
SQLite；execute 模式随后串行调用相同的通用 adapter，每个 dataset 保持自己的
facts + receipt transaction。manifest 不得含 token、provider API name、fields、路径或
业务逻辑，也不进入仓库。`on_demand` 仍不会被 scheduler 自动计划：只有已验证的
window 被明确放进该 manifest，才会采集。

生产按需 batch 复用唯一的 `tradingdatas-provider-native-collect.service`，不创建第二个
service 或 timer。发布 operator 只能在该 unit 空闲时，在其 `RuntimeDirectory` 写入由
`tradingdatas` 账号拥有、`0600`、无链接且单链接的
`/run/tradingdatas/on-demand-batch.json` 与 `/run/tradingdatas/on-demand.env`。后者只能
逐字节指定该固定 batch 路径，不能含任何其它环境变量；手工启动同一 service 后，通用 dispatcher 先消费 selector，再以
同一 `/run/tradingdatas/collect.lock` 串行执行 batch。无 selector 时 timer 保持原有 cadence
planner 路径。无论成功、合法 empty、失败或 validation，batch 文件均在本轮结束时删除，
避免下一次 timer 重放。batch 仍需先经过同 release 的 no-write plan，且不得含 token、
provider API 名、字段或专用行为。

按需 batch 的合法 empty 是当前窗口的有效采集事实，因此该 service 将 CLI 的 empty
exit code `3` 与并发 busy code `75` 都视为完成；validation 与 provider failure 仍为失败，
不会被该映射掩盖。

## 只读 onboarding 与稀有分区审计

`tools/report_dataset_onboarding_status.py` 只读取已验证的 SQLite 快照、runtime registry 与可选的脱敏 formal API snapshot；不得调用 provider、写数据库或触碰 API/timer。可选的 `config/readiness_partition_audit.v1.json` 预注册少量已经完成的精确分区，汇总 receipt、provider、行数、身份空值/重复、上限与 terminal-empty 事实。它不是采集 manifest，也不会激活、调度或提升数据集。

普通读取仍仅按 receipt authority 做单遍历。只有 onboarding、合同漂移、事故恢复和每日 scrub 才执行独立双遍历验证。合法 empty 只证明该观察窗口没有数据；历史读取默认仍为 `observation_only`，除非另有 immutable receipt、as-of、first-seen 与 revision-vintage 的完整证据，不能据此声称 PIT 或非空完整性。

## Release 与回滚身份

`tools/release_manifest.py` 只管理 Git release 字节与 `current` 指针，不安装 unit、
不读取凭证、不打开 SQLite、不调用 provider，也不启停服务或 timer。manifest 由 clean
Git HEAD 的 commit、tree 和全部 tracked blob 生成，保存在 release 目录之外；release
必须是以完整 commit 命名的直接子目录，且只包含 manifest 声明的文件。目录固定
`0555`，普通文件 `0444`，Git executable 为 `0555`，无链接、额外文件、`.git` 或
`__pycache__`。验证器从 commit object 重算 commit/tree 关系，从 manifest entries 重算
Git tree，并从 release 实际字节重算每个 Git blob 与 SHA256；manifest 本身也必须匹配
`--expected-uid/--expected-gid` 且不可被 group/world 写入。

发布前的一致性检查只比较 manifest 声明的精确 Git tree 文件及其 mode/blob/hash，不能先
对普通服务器 worktree 做整目录相等比较。现役 worktree 中未纳入 manifest 的缓存、运行输出
或其它已登记未跟踪资产必须原样保留并单独报告；它们既不能进入 release，也不能因发布而被
清理。只有 manifest 声明文件发生漂移才阻断该 release。

生产 release 内的任何 Python 诊断都必须同时设置
`PYTHONDONTWRITEBYTECODE=1` 并使用 `python3 -B`；只读诊断也不能在 immutable release
生成 `__pycache__` 或 `.pyc`。诊断前后都要运行 trusted `verify-current`，并检查 release
内不存在 manifest 外文件。若误生成缓存，只能先冻结精确路径、字节数和 SHA-256，确认
全部为 manifest 外缓存且声明文件零漂移后，再删除精确缓存目录并重新验证；不得借此做
广义目录清理。

本地从 clean checkout 生成确定性 manifest。构建、服务器验证和切换必须使用已审查的
trusted verifier，不能从尚未验证的 target release 执行 `release_manifest.py`；常规升级
使用当前已验证 release 中的 verifier，首次 bootstrap 则先把本地已审查 verifier 作为
独立文件传入并核对其 SHA256 后再运行：

```bash
python3 tools/release_manifest.py build \
  --source-root /absolute/path/to/TradingDatas \
  --output /private/tmp/<commit>.release.json
```

### Source 与 API readiness preflight

每次发布必须读回 GitHub `main`、将要 archive 的 target commit 与 clean working tree。
服务器可用时，先从 clean source checkout 执行受限的 `fetch origin main`；该通道只能使用独立、
root-only 的只读 deploy key，以及严格校验的 GitHub host key，不得复用个人 GitHub key、在
Git config/环境变量中保存 token，或把 source checkout 当作运行中的 release。若 fetch 或
commit 比对失败，服务器 checkout 不能被当作 target；此时可使用已验证为 GitHub/main 的本地
clean commit，传输它的受控 Git archive 与 manifest 到新的 immutable staging 目录。不得用旧
release、已运行 API 或未经核对的本地文件猜测源码身份。

重启 API 后，发布脚本必须在一个短、有界的循环内等待 loopback `/v1/catalog` 返回预期的
认证状态；连接被拒绝只表示 listener 尚未就绪，不能立即将已验证 target 回滚。循环超时、
非预期认证状态或 service/timer 未恢复时才执行既定 rollback，并分别记录 pointer、unit 和
HTTP/consumer readback。

### 发布通道选择（强制顺序）

生产发布的权威通道是：**本地已验证的 clean Git commit -> `marketgraph-root` 的
immutable release staging -> manifest/rollback 验证 -> 原子 `current` 切换 -> service
与消费者 readback**。目标 ECS 使用 `marketgraph-root`（严格 host-key 校验）进行 root-only
release 操作；`marketgraph-server` 仅可用于最小权限诊断。服务器工作树能否从 GitHub 拉取，
只是可选的源码同步能力，绝不能作为“是否可以发布”的前置条件或阻塞结论。

当服务器 GitHub deploy key、known_hosts 或网络异常时，保留已审查本地 commit 的 Git archive
与其 manifest，通过 `marketgraph-root` 写入一个**不存在的新 commit 目录**，再按本节验证；不得
覆盖已有 release、复制未受 manifest 覆盖的文件，或把服务器 checkout 当作未经核对的发布源。
Aliyun CLI 是 ECS 身份、实例状态和应急控制面的备选验证渠道，不替代 release manifest，也不
改变 SSH host identity 的校验要求。每次发布记录必须分别写明：选择了哪条通道、GitHub/main
状态、server checkout 状态、active release、rollback release、service/timer 与 HTTP/consumer
readback，避免把任意单层状态合并成“已部署”。

服务器 staging 完成且尚未切换 `current` 时，以 root owner 身份只读验证：

```bash
/opt/tradingdatas/venv/bin/python3 \
  /opt/investment/releases/tradingdatas/current/tools/release_manifest.py verify \
  --release-root /opt/investment/releases/tradingdatas/<commit> \
  --manifest /opt/investment/releases/tradingdatas/manifests/<commit>.json \
  --expected-uid 0 --expected-gid 0
```

`switch-current` 只允许从已验证的 rollback manifest 切到已验证的 target manifest；
在 releases 根目录加排他锁，以相对 40 位 commit symlink、`os.replace` 和目录 fsync
完成原子切换，post-switch 失败时恢复旧 pointer。执行前必须由外部 safe-release
preflight 证明 API/collector 均 inactive、timer disabled、18082 切换方案与旧服务回滚
已冻结。重复验证使用 `verify-current`；它持共享锁覆盖 pointer 读取、release 验证和
pointer 重读，不能与协作切换交错产生伪 readback。manifest 不记录 secret 内容或 SQLite hash；
回滚不覆盖 SQLite，也不恢复旧 official-direct collector。

早期 bootstrap 可能遗留一个绝对 `current` pointer。普通 `verify-current` 与
`switch-current` 继续只接受相对 40 位 commit，不兼容或跟随该遗留形式。只允许在
API/collector 均 inactive、timer disabled，且 rollback release 与外置 rollback
manifest 已独立验证后，使用已审查并核对 SHA256 的 trusted verifier 执行一次：

```bash
/opt/tradingdatas/venv/bin/python3 \
  /path/to/reviewed/trusted-release_manifest.py normalize-current \
  --releases-root /opt/investment/releases/tradingdatas \
  --rollback-manifest /opt/investment/releases/tradingdatas/manifests/<rollback-commit>.json \
  --expected-uid 0 --expected-gid 0
```

该命令只接受原始 pointer 逐字等于 canonical absolute
`/opt/investment/releases/tradingdatas/<rollback-commit>` 的单一遗留情形，在同一排他锁
内验证 rollback release 后原子改写为相对 `<rollback-commit>`，目录 fsync 并读回。
任意其它绝对路径、不同 rollback、已经相对的 pointer、链接链或不安全 releases root
都必须拒绝。相对 pointer 完成 `replace`、目录 fsync 和 post-readback 后即为提交点；
提交点之前的改写失败会恢复原绝对 pointer，恢复失败必须高声失败并停止发布。提交点
之后的 unlock/close 只是 cleanup，不得反向覆盖已提交 pointer 或把成功伪报为失败；
关闭前必须先解绑本地 descriptor 状态，不能因 close-after-close 异常误关复用的 FD。
成功后立即用同一 rollback manifest 运行 `verify-current`，再进入常规
`switch-current`。该 normalization 不安装 unit、不启停服务、不读取凭证、不打开或
覆盖 SQLite，也不能用作第二种常驻 pointer 格式。

systemd 仅从 `current` 启动入口脚本。入口立即解析到同一物理 immutable release，
registry 与 schedule 不接受 `/current/config/...` 环境覆盖；execute 模式也拒绝非本物理
release 的 `--schedule-config`，避免代码/配置跨版本混配。

当前 runtime 使用 `provider=tushare`、`transport_service=quicksync`。Tushare 官方文档只负责 dataset/schema/cadence 参考；QuickSync 文档与真实有界探测才负责 endpoint、认证、权限码、分钟/每日频控和并发事实。QuickSync 凭证只建立账号身份，不代表接口权限；`entitled_active` 不是购买或计费状态。2026-07-21 CST（证据时间 2026-07-20Z）的单一 HTTPS 节点小响应探测曾取得并发 4、210/210 request starts 在一分钟内成功；该历史探测只是 transport 观测，不是当前 scheduler budget、供应商合同额度或已部署 production 配置。当前 scheduler 仍以本文上述每轮账号/provider/API `12/12/6` 为绑定上限；混合大响应、每日额度和 DNS failover 仍未知。timer 仅在 target release 的 preflight、rollback 与 server readback 通过后显式启用，单个接口成功不会自动扩权。

## 运行顺序

1. 安装代码与只读配置；
2. 以独立运行账号初始化全新 SQLite schema（不会迁移或读取旧库）。入口使用
   绝对路径，因此不依赖调用方当前目录：

   ```bash
   /opt/tradingdatas/venv/bin/python3 \
     /opt/investment/releases/tradingdatas/current/tools/init_tradingdatas_store.py \
     --database /opt/investment-data/tradingdatas/read_model/provider_native.sqlite
   ```

3. 创建 `root:tradingdatas` 持有、权限为 `0750` 且不含 symlink 的
   `/etc/tradingdatas` 父目录。API 认证加载器会逐级打开并绑定目录，只有执行位的
   `0710` 不足以完成安全读取；Tushare loader 当前只使用 `O_NOFOLLOW` 绑定 Token
   叶子文件，因此发布 preflight 必须另外拒绝父目录 symlink。再创建由
   `tradingdatas:tradingdatas` 持有且权限严格为 `0600` 的
   `/etc/tradingdatas/api_tokens.json`、`/etc/tradingdatas/token_salt` 与
   `/etc/tradingdatas/quicksync.token`。QuickSync token 必须是单一硬链接的普通文件，
   文件 owner 必须等于采集进程的有效 UID；因此采集进程会拒绝 root-owned 或
   其他账号持有的 token。采集 runner 与 API service 都使用独立 `tradingdatas` 账号，使采集写入
   和 API 只读访问协作于同一 SQLite 权限模型，不以 root 运行采集器。内部
   loopback 调用同样必须携带显式 token 或 JWT；没有 localhost 免认证路径；

   TradingAgent 使用独立的只读 token，不能复用 bootstrap 或 QuickSync 凭证。token 明文的
   持久源固定为 root-owned、`0600`、单链接普通文件
   `/etc/tradingagent/tradingdatas-read.token`；API registry 只保存带
   `/etc/tradingdatas/token_salt` 的 PBKDF2 hash、`tenant_id=tradingagent`、`scopes=[read]`
   和有界并发。运行时文件固定为
   `/run/secrets/tradingagent/tradingdatas-read.token`，必须是
   `tradingagent:tradingagent`、`0600`、单链接普通文件，父路径不得含 symlink。生产使用
   最终切换后，TradingAgent release 提供的 `/etc/tmpfiles.d/tradingagent-runtime.conf` 只拥有
   `root:tradingagent 0710` runtime 父目录合同；TradingDatas credential publisher 的
   `/etc/tmpfiles.d/tradingagent-secrets.conf` 只拥有从持久源重建 leaf 的 `C` 规则。两个文件
   不得重复定义 parent。配置、日志、evidence、任务消息和环境变量均不得包含 token 值。
   轮换分为两个有回滚的阶段：先在 root-only staging 生成新 credential，把新旧两个 hash
   同时注册并重启 API，证明旧/新都可读而 canonical source 与 runtime 完全不变；只有消费者
   明确给出 freeze-window GO 后，才原子提升持久源、父目录和 runtime leaf。消费者 metadata
   与 bounded parity 通过后再删除旧 hash、重启 API，并证明旧 credential 为 401、新
   credential 为 200。consumer 尚未暂停且 legacy front 尚未隔离时，阶段 A 失败可以恢复
   旧 registry、source/runtime 与 tmpfiles 合同；一旦 TradingAgent 已暂停 recurring job、
   隔离 legacy front 并进入 publisher freeze，后续失败必须保持 consumer unavailable、freeze
   和零 holder，只能保存证据并受控前滚，禁止恢复旧 credential、旧 runtime leaf、旧 front、
   8082 fallback 或旧 tmpfiles owner。两种阶段都不得改 SQLite 或临时放宽权限。
4. 在不读取凭证、不调用 provider 的情况下，从目标 immutable release 的物理
   `FINAL` 路径重新编译 registry。`FINAL` 必须是以完整 commit 命名的直接目录，不得是
   `/current`、其它 symlink 或可写 checkout。compiler 的 `--output` 必须指向 release 之外
   由 `mktemp` 创建的私有临时文件，不得使用会改写 checked-in registry 的默认输出：

   ```bash
   (
     set -eu
     TARGET_COMMIT="<40-character-commit>"
     test "${#TARGET_COMMIT}" -eq 40
     case "$TARGET_COMMIT" in *[!0-9a-f]*) exit 1 ;; esac
     FINAL="/opt/investment/releases/tradingdatas/$TARGET_COMMIT"
     test -d "$FINAL"
     test ! -L "$FINAL"
     REGISTRY_VERIFY="$(umask 077 && mktemp /tmp/tradingdatas-registry.verify.XXXXXX)"
     trap 'rm -f -- "$REGISTRY_VERIFY"' EXIT
     trap 'exit 1' HUP INT TERM

     PYTHONDONTWRITEBYTECODE=1 \
       /opt/tradingdatas/venv/bin/python3 \
       "$FINAL/tools/compile_provider_native_registry.py" \
       --upstream-contracts "$FINAL/config/tushare_upstream_contracts.v1.yaml" \
       --observations "$FINAL/config/quicksync_interface_observations.v1.yaml" \
       --output "$REGISTRY_VERIFY"
     cmp --silent \
       "$REGISTRY_VERIFY" \
       "$FINAL/config/provider_native_dataset_registry.yaml"

     rm -f -- "$REGISTRY_VERIFY"
     trap - EXIT HUP INT TERM
   )
   ```

   `cmp --silent` 成功才证明重建结果与该 release 内 checked-in registry 逐字节一致；
   无论成功、失败或中断都必须清理临时文件。验证过程不得从 `/current` 执行 compiler，
   也不得改写 release 内任何文件。目标 release 必须从同版本的
   `quicksync_interface_observations.v1.yaml` 重建其 190 个 runtime contract，并与
   checked-in registry 逐字节一致；active/paused 的精确计数由该次目标 release 的读回
   决定，不能在本说明中写死或由旧候选推断。
   scope v2 的产品目录已扩为 222，但新增 32 项在正式合同、HTTPS entitlement 与
   runtime registry 接线完成前只允许 `unobserved/paused`，不得由 MCP 可见性自动加入
   采集计划。观测配置必须保持
   `interface_probe_scheme=http`、`production_ready=false` 和生产 transport
   blocked；它不读取 Token，也不是正式 HTTPS 采集证明。旧 manual entitlement probe
   与 policy 已退役；request-profile 配置与 resolver 仅作官方输入映射迁移资料，既不是
   entitlement/activation authority，也不得接入 collector、scheduler 或生产命令；
   runtime contract compiler 与 HTTPS probe plan 还必须分别从磁盘重新读取并核对其
   official/request/transport/reviewed 或 registered 四类冻结输入；调用方传入的映射不能
   绕过原始字节 SHA。seed receipt 的 producer schema 必须与 registry 精确一致；

   HTTPS probe 的 `--scope executable` 仅从同一冻结 190 项 plan 中选择已经标记
   `probe_state=executable` 的条目，保留 blocked 条目及其原因，不改写 registry、SQLite、
   activation 或 scheduler。它用于一次批量复验安全请求形状；`all` 仍在任一 blocked 条目
   存在时 fail closed。若完整选择会超过单次响应字节预算，调用方必须保持同一 plan 和
   SHA-256，使用 `--start-index` 与 `--max-interfaces` 生成连续、不重叠的受控批次；每份
   evidence 都会保留完整 scope 的 `planned/executable` 数及该批的 `selected/executed` 数，
   不能把一个批次的成功写成全体接口成功。
   当 `selected < executable` 时，该 evidence 只能提升其 `results` 中实际成功、且已具备
   ingestion contract 的接口 cohort；它必须保留既有 active 集合，且绝不能提升未执行接口。

   若上游失败响应被 transport 判定为含敏感回显，probe 只可把它记录为失败，使用
   `response_redacted=true` 与 `response_sha256=null`；不会保存响应正文或降级为成功。
   成功或有效空响应仍必须携带合法 SHA-256，否则整批 fail closed。

   HTTPS activation evidence 必须保存在仓外，由调用方先核对 sidecar SHA-256，再通过
   显式 `--activation-evidence /outside/repository/path` 传入；现有 QuickSync probe 直接
   写出的 evidence sidecar 可作为该输入，compiler 会重新计算其结果、cohort 与 activation
   projection，不能信任调用方自报投影。仓库、release、CI fixture 和 formal 编译均不得内置
   或默认寻找真实 evidence。只有同时指定
   `--compilation-mode preactivation_candidate` 且把 `--output` 指向仓外私有临时路径时，
   compiler 才会生成 canary registry。正式 release 的 activation 只来自同版本、已审查的
   `active_evidence` 配置；因此 active/paused 计数必须由 immutable target 的 compiler 和
   checked-in registry 共同读回。截至 2026-07-27，已部署 production release
   `42fcf6c8822cf0b3268ee9ebdd20b207d69a3902` 的 99 / 91 是历史快照。main 的 `stk_factor_pro` 宽 schema
   候选会在同一 2,000,000-node 安全上限内自动下调每批行数；它在 fresh release/readback 前
   不是 production activation。受控 one-shot 不会把 active 状态等同于 ready；collector timer 的实际状态
   必须由当前 release/runtime readback 判定，而不是仓库文本、历史 sidecar 或 CI fixture。
5. 运行一次受控 latest/current collection；
6. 验证 facts、receipts、catalog/query 与 impaired negative cases；
7. 在 generic runner 独立验收后安装唯一采集 service/timer；仅在发布 preflight 和回滚验证
   都通过后，按数据集 cadence 显式启用。

   生产 collector unit 不传入 activation wave 或 dataset 参数，始终由同一 registry-driven
   planner 选择所有 automatic cadence。发布前必须在目标 release 和正式 SQLite 上做 plan
   readback：计划只能包含 active/entitled automatic bindings，`on_demand` 必须显式跳过；超出
   本轮 budget 的计划项必须是 `rate_budget` skip，不能生成失败 receipt。再以受控 one-shot 或
   一个完整 timer 周期验证 facts、receipts 和 API readback。`direct_wave_3` 等保留作有界历史
   batch 选择，但其 `on_demand` 合同不会被 scheduler 自动执行。
8. 正式 QuickSync 凭证、权限/流控 evidence、受控 latest collection 和 API readback 通过后才启用 timer，并观察完整 cadence 周期；
9. 如有批准的历史需求，再运行独立、有界且可回滚的 backfill manifest；它不得影响当前 timer 的 latest-window 可用性。

`POST /v1/query` 的稳定性证明必须符合数据集粒度。对于 `daily`、`sw_daily` 等按
`trade_date` 分区的数据集，latest/current readback 使用显式 `eq` 或有界日期范围并完整
翻页；不得用无筛选第一页成功代替完整查询证明。无界跨多分区读取仍受 SQLite VM-step
预算约束，消费者应缩小日期范围，不能通过无限重试或旧 route fallback 绕过。非分区
snapshot（如 security master）及有界 calendar 可按 registry 默认排序完整翻页。

运行证据的校验清单不得包含清单自身。payload 全部关闭后生成仅列 payload 的
`PAYLOADS.sha256`，再用独立 sidecar 记录该清单的 SHA-256；交接前必须分别执行
`sha256sum -c PAYLOADS.sha256` 和 sidecar 校验。若已生成自引用或不自洽清单，保留原件
作为事故证据，在相邻只读目录新增修正版；若修正版使用相对 payload 路径，必须从原
payload 目录执行 `sha256sum -c /absolute/fix/PAYLOADS.sha256`，再进入修复目录校验
sidecar。不得覆盖原始 payload 或把失败清单改写成通过。

## 发布门禁

必须分别验证：local、origin/GitHub、production checkout、active release、service/timer、SQLite、真实 provider receipt、API readback 和消费者调用。

旧 `api.tushare.pro` official-direct release 只保留代码与回滚证据，不得启动为生产采集 runtime；修正版必须 fresh 验证 QuickSync endpoint/TLS、禁止 redirect、权限码分类、200 次/60 秒账号门禁、并发 4、单一 deadline、仅 pre-send DNS failover 和 impaired API readback。历史 190 接口本机矩阵、222 静态能力目录或分钟吞吐证明都不能替代服务器 provider -> SQLite -> receipt -> API readback；每日额度未知时仍不启用自动历史回填。

## 旧系统退役

新 TradingDatas runtime 和消费者切换通过后：

1. 停止旧写任务；
2. 观察无旧调用；
3. 保留可验证回滚快照；
4. 删除旧服务、cron、代码、文档和依赖；
5. 数据删除另走单独保留策略，不与代码退役混在一起。

2026-07-21 已验证的旧运行面清单如下，不得用模糊的“旧 cron”概括后一次性删除：

- root crontab：`opening_gate.sh` 的 preopen、morning_first_sample、afternoon_resume、close_check 四个时点，以及 `external_api_probe.sh`；
- `marketgraph` crontab：`SharedSignals/cron/` 下的 Tushare collectors、CNFutures、Crypto、事件、低频、patrol、proxy health、watchdog、SLA、governance、capability scan 和 PM 采集任务；
- systemd override：`/etc/systemd/system/tradingagent-front-api.service.d/sharedsignals.conf`，其 `SHAREDSIGNALS_API_URL` 仍指向 `127.0.0.1:8082`；
- 旧 `8082` 服务、旧 SharedSignals 代码与数据路径。

**2026-07-29 20:46 CST 退役 readback：** 已先生成 root-only 回滚快照，随后停用
`sharedsignals-api.service` 与 `sharedsignals-sg-relay-tunnel.service`。随后 7 个历史
SharedSignals service/timer 的 unit 均已移出 systemd 搜索路径并 `masked`，因此不能被意外
启动；原 unit 副本和摘要保留在受限退役证据目录。`127.0.0.1:8082` 已无监听；root 的 5 条与
`marketgraph` 的 22 条非注释旧 SharedSignals 计划任务均已移除。TradingDatas 18082 仍为
active，自己的 collector timer 继续 disabled。基础退役证据位于受限目录
`/opt/investment/release-evidence/tradingdatas/20260729T124623Z-sharedsignals-runtime-retirement`。
旧 SharedSignals 的代码、runtime、release candidate、systemd unit/override 与 active-path
归档已经完成退役和物理清理，不再是可用 rollback 或恢复入口，也不得重新创建旧 unit、cron、
provider route 或 SQLite 直读。TradingDatas 回滚只允许切换到已验证的 immutable release。
历史 Tushare 数据归档与退役证据是独立的数据保留范围；未取得单独批准前继续只读保留，不能因
代码/runtime 已清理而一并删除。具体删除时间、路径清单、数量、服务状态和 readback 属于带
`observed_at` 的运行事实，记录在 `STATUS.md`，不复制为长期运行合同。

退役必须分项执行并保留证据：

1. 新 TradingDatas 完成真实 provider -> SQLite facts/receipts -> `catalog/query` readback；
2. TradingAgent 及其它批准消费者只读新 API，完成 same-as-of、impaired 状态和无 legacy fallback parity；
3. 记录旧/新采集边界及最后成功 receipt，证明无数据窗口；
4. 冻结 root 与 `marketgraph` crontab、systemd override、旧服务和数据快照，生成可逐项回滚的 manifest；
5. 先禁用旧 writer/probe 并观察无旧调用，再删除 cron/override/service/code/docs；数据库与历史数据仍需独立批准。

## 回滚

回滚只切回已验证的 immutable release，不覆盖 SQLite，不恢复旧 cron，不把旧 provider route 重新引入新系统。

外部账户不属于当前运行范围；内部运行凭证和 API token 不得复用于任何外部账户或公网入口。

## Firecrawl 凭证与额度运维

Firecrawl 是境内新闻/公告/舆情采集的第三个 provider-level adapter（transport 协议与
QuickSync 实质不同，按根合同允许单独 adapter）。其凭证边界与 Tushare/QuickSync 完全一致：

- 凭证只从 `FIRECRAWL_API_KEY_FILE` 读取：绝对路径、单一硬链接普通文件、owner 等于采集进程
  有效 UID（当前 `tradingdatas`）、mode `0600`、非空且为单行 UTF-8。当前生产文件为
  `/etc/tradingdatas/firecrawl.token`，不在仓库内。
- Firecrawl key 是一次性成品号、按 credit 计费。换 key 只替换该文件内容并保持 owner/mode，
  零代码、零 registry 改动；替换后下一轮 event 采集自然使用新 key，无需重启服务。
- 402/429 → 该 dataset 记 `rate_limited` terminal receipt、planner 跳过、runtime 降级
  degraded，不阻塞 tushare/binance 管线。401/403 → `permission_denied`（key 失效即 entitlement
  降级，同样 dataset 级隔离）。
- 额度消费以 Firecrawl 后台 `creditsUsed` 为准；本仓库不持久化任何 Firecrawl 凭据或额度数字。
  全部 key 耗尽且暂无新 key 时，把 `config/firecrawl_upstream_contracts.v1.yaml` 中
  `cn.news.flash` 的 `activation.activation_state` 改回 `paused`（registry/config 改动），
  管线形态不变，恢复新 key 后按同一路径改回 `active` 并重编 registry。
- 生产采集单元的环境变量 `FIRECRAWL_API_KEY_FILE` 由
  `/etc/systemd/system/tradingdatas-provider-native-collect.service.d/20-firecrawl.conf`
  提供；修改凭证文件路径时必须同步该 drop-in，并 `systemctl daemon-reload`。

Firecrawl 的 `search_news`（`POST /v2/search`）当前无 registry binding，仅作为 on_demand
补充手段设计，不在自动调度内；激活前需先验证其真实响应契约。
