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

## Release 与回滚身份

`tools/release_manifest.py` 只管理 Git release 字节与 `current` 指针，不安装 unit、
不读取凭证、不打开 SQLite、不调用 provider，也不启停服务或 timer。manifest 由 clean
Git HEAD 的 commit、tree 和全部 tracked blob 生成，保存在 release 目录之外；release
必须是以完整 commit 命名的直接子目录，且只包含 manifest 声明的文件。目录固定
`0555`，普通文件 `0444`，Git executable 为 `0555`，无链接、额外文件、`.git` 或
`__pycache__`。验证器从 commit object 重算 commit/tree 关系，从 manifest entries 重算
Git tree，并从 release 实际字节重算每个 Git blob 与 SHA256；manifest 本身也必须匹配
`--expected-uid/--expected-gid` 且不可被 group/world 写入。

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
   也不得改写 release 内任何文件。当前生产候选仍必须从
   `quicksync_interface_observations.v1.yaml` 得到历史合同子集
   190 个 dataset、3 active / 187 paused，且输出与 checked-in registry 逐字节一致。
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
5. 运行一次受控 latest/current collection；
6. 验证 facts、receipts、catalog/query 与 impaired negative cases；
7. 在 generic runner 独立验收后安装唯一采集 service/timer，但保持 disabled；
8. 正式 QuickSync 凭证、权限/流控 evidence、受控 latest collection 和 API readback 通过后才启用 timer，并观察完整 cadence 周期；
9. 后台运行 bounded backfill。

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
