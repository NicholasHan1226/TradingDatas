# TradingDatas Operations

## 目标生产布局

```text
/opt/investment/releases/tradingdatas/<immutable-release>
/opt/investment/releases/tradingdatas/current
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
4. 在不读取凭证、不调用 provider 的情况下重新编译 registry：

   ```bash
   /opt/tradingdatas/venv/bin/python3 \
     /opt/investment/releases/tradingdatas/current/tools/compile_provider_native_registry.py
   ```

   编译必须从 `quicksync_interface_observations.v1.yaml` 得到 190 个 dataset、
   3 active / 187 paused，且输出与 checked-in registry 逐字节一致。观测配置必须保持
   `interface_probe_scheme=http`、`production_ready=false` 和生产 transport
   blocked；它不读取 Token，也不是正式 HTTPS 采集证明。旧 manual entitlement probe
   与 policy 已退役；request-profile 配置与 resolver 仅作官方输入映射迁移资料，既不是
   entitlement/activation authority，也不得接入 collector、scheduler 或生产命令；
5. 运行一次受控 latest/current collection；
6. 验证 facts、receipts、catalog/query 与 impaired negative cases；
7. 在 generic runner 独立验收后安装唯一采集 service/timer，但保持 disabled；
8. 正式 QuickSync 凭证、权限/流控 evidence、受控 latest collection 和 API readback 通过后才启用 timer，并观察完整 cadence 周期；
9. 后台运行 bounded backfill。

## 发布门禁

必须分别验证：local、origin/GitHub、production checkout、active release、service/timer、SQLite、真实 provider receipt、API readback 和消费者调用。

旧 `api.tushare.pro` official-direct release 只保留代码与回滚证据，不得启动为生产采集 runtime；修正版必须 fresh 验证 QuickSync endpoint/TLS、禁止 redirect、权限码分类、200 次/60 秒账号门禁、并发 4、单一 deadline、仅 pre-send DNS failover 和 impaired API readback。190 接口本机矩阵或分钟吞吐证明都不能替代服务器 provider -> SQLite -> receipt -> API readback；每日额度未知时仍不启用自动历史回填。

## 旧系统退役

新 TradingDatas runtime 和消费者切换通过后：

1. 停止旧写任务；
2. 观察无旧调用；
3. 保留可验证回滚快照；
4. 删除旧服务、cron、代码、文档和依赖；
5. 数据删除另走单独保留策略，不与代码退役混在一起。

## 回滚

回滚只切回已验证的 immutable release，不覆盖 SQLite，不恢复旧 cron，不把旧 provider route 重新引入新系统。

受邀外部账户 Beta 还需要单独核验 QuickSync/Tushare 的缓存与再分发条款；内部运行凭证和 API token 均不得复用于外部账户。
