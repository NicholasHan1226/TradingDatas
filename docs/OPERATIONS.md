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
Tushare API 增加 service/timer。所有真实采集频率、失败重试与回填预算都来自
registry cadence。没有正式 QuickSync 凭证文件、冻结的 transport budget、真实 latest collection 与 fresh readback
前，不在生产启用采集 timer。

planner 对每个 `dataset + provider + request_window` 只生成一个包含 registry 全部 request variants 的 plan；snapshot 数据集只要任一 variant 到期，就重新运行完整 cohort，不能因一个 sibling receipt 跳过其余 variants。scheduler 每次 run 生成显式 UUID root，并按稳定 plan ordinal 派生 window attempt root；one-shot collection 也必须执行完整 registry cohort，但只把自己的 root 视为单 window execution。当前/最新 window 仍优先于 bounded backfill。

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

省略 `--activation-wave` 时保持完整 scheduler 行为。当前 `pilot_existing` 只包含已有
五个生产验证 dataset；它不是新增 entitlement、fresh probe 或启用 timer 的证据。fresh
probe 审核完成前，不得把其它候选加入该清单。只读 plan 可按以下方式检查：

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python tools/run_provider_native_schedule.py --activation-wave pilot_existing
```

`daily_reference` 不假设上游提前提供下一自然年的完整交易日历，range 数据集的
current window 只推进到本次可用日；历史覆盖由 bounded backfill 逐段补齐。不得为了
预取未来日历把固定未来天数当成 provider 能力事实，否则合法的 future-empty 响应会
被完整性合同误判为运行失败。未来日期只有在 transport 真实观测、registry 合同和
独立回归共同证明后才能受控启用。

## Release 与回滚身份

`tools/release_manifest.py` 只管理 Git release 字节与 `current` 指针，不安装 unit、
不读取凭证、不打开 SQLite、不调用 provider，也不启停服务或 timer。manifest 由 clean
Git HEAD 的 commit、tree 和全部 tracked blob 生成，保存在 release 目录之外；release
必须是以完整 commit 命名的直接子目录，且只包含 manifest 声明的文件。目录固定
`0555`，普通文件 `0444`，Git executable 为 `0555`，无链接、额外文件、`.git` 或
`__pycache__`。验证器从 commit object 重算 commit/tree 关系，从 manifest entries 重算
Git tree，并从 release 实际字节重算每个 Git blob 与 SHA256；manifest 本身也必须匹配
`--expected-uid/--expected-gid` 且不可被 group/world 写入。

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

当前 runtime 使用 `provider=tushare`、`transport_service=quicksync`。Tushare 官方文档只负责 dataset/schema/cadence 参考；QuickSync 文档与真实有界探测才负责 endpoint、认证、权限码、分钟/每日频控和并发事实。QuickSync 凭证只建立账号身份，不代表接口权限；`entitled_active` 不是购买或计费状态。2026-07-21 CST（证据时间 2026-07-20Z）的健康单一 HTTPS 节点小响应实测为并发 4、210/210 request starts 在一分钟内成功；当前 `main` 代码采用更保守的保护门禁 200 次/60 秒、并发 4。它不代表供应商合同额度或已部署 production 配置；混合大响应、每日额度和 DNS failover 仍未知，timer 保持 disabled，不因单个接口成功自动扩权。

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
   也不得改写 release 内任何文件。当前 `main` 的 release 候选仍必须从
   `quicksync_interface_observations.v1.yaml` 得到历史合同子集
   190 个 dataset、29 active / 161 paused，且输出与 checked-in registry 逐字节一致。
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

   若上游失败响应被 transport 判定为含敏感回显，probe 只可把它记录为失败，使用
   `response_redacted=true` 与 `response_sha256=null`；不会保存响应正文或降级为成功。
   成功或有效空响应仍必须携带合法 SHA-256，否则整批 fail closed。

   HTTPS activation evidence 必须保存在仓外，由调用方先核对 sidecar SHA-256，再通过
   显式 `--activation-evidence /outside/repository/path` 传入；仓库、release、CI fixture 和
   formal 编译均不得内置或默认寻找真实 evidence。只有同时指定
   `--compilation-mode preactivation_candidate` 且把 `--output` 指向仓外私有临时路径时，
   compiler 才会生成 canary registry。当前 `main` 的正式编译不传 activation evidence，
   固定生成 29 active / 161 paused；截至 2026-07-26，已部署 production release 仍为
   `0472be2f52338b64b0c2561afe2d1baaf19586b6` 的 26 / 164。受控 one-shot 不会把
   active 状态等同于 ready，collector timer 仍 disabled；回滚 release
   `c3232d0422aa09b83b8d8e9ed6cd87067bcb47cc` 为 12 / 178。任何时刻都必须以
   release readback 而不是仓库文本判定。用当前 main compiler 重编 2026-07-22
   观测 sidecar 得到的 119 active / 71 paused 仅属于 SHA-256
   `cebbff13971b4d6465b986089a152feb056dc8e56e0bc0d4992a63175d20268c` 的仓外 sidecar
   候选，不是 CI 期望值、checked registry 或 production activation。
5. 运行一次受控 latest/current collection；
6. 验证 facts、receipts、catalog/query 与 impaired negative cases；
7. 在 generic runner 独立验收后安装唯一采集 service/timer，但保持 disabled；

   GitHub `main` 的 runner 现在提供显式
   `--activation-wave pilot_existing --current-only` 入口：它只接受该 pilot wave，planner
   只保留 priority=`current`，执行前再次拒绝 backfill、correction 与非 current 项。它解决了
   2026-07-23 production no-write plan 同时生成 current、backfill 与 correction 的问题，
   但尚未发布到 production。timer 仍保持 disabled；先做 fresh release 和受控 one-shot，
   确认 0 backfill / 0 correction、facts/receipts/API readback 后，才可评估仅 Wave 1/2 的
   cadence pilot。已安装的 collector unit 也只传入这两个参数；后续扩大 cadence 的唯一
   路径是先审查并更新受控 activation wave，而不是删掉 current-only。`direct_wave_3`
   永远按 `on_demand` 跳过 scheduler。
8. 正式 QuickSync 凭证、权限/流控 evidence、受控 latest collection 和 API readback 通过后才启用 timer，并观察完整 cadence 周期；
9. 后台运行 bounded backfill。

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

退役必须分项执行并保留证据：

1. 新 TradingDatas 完成真实 provider -> SQLite facts/receipts -> `catalog/query` readback；
2. TradingAgent 及其它批准消费者只读新 API，完成 same-as-of、impaired 状态和无 legacy fallback parity；
3. 记录旧/新采集边界及最后成功 receipt，证明无数据窗口；
4. 冻结 root 与 `marketgraph` crontab、systemd override、旧服务和数据快照，生成可逐项回滚的 manifest；
5. 先禁用旧 writer/probe 并观察无旧调用，再删除 cron/override/service/code/docs；数据库与历史数据仍需独立批准。

## 回滚

回滚只切回已验证的 immutable release，不覆盖 SQLite，不恢复旧 cron，不把旧 provider route 重新引入新系统。

受邀外部账户 Beta 还需要单独核验 QuickSync/Tushare 的缓存与再分发条款；内部运行凭证和 API token 均不得复用于外部账户。
