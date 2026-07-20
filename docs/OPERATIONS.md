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
registry cadence。没有正式 Tushare Token、真实 latest collection 与 fresh readback
前，不在生产启用采集 timer。

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
   `/etc/tradingdatas/tushare.token`。Tushare token 必须是单一硬链接的普通文件，
   文件 owner 必须等于采集进程的有效 UID；因此采集进程会拒绝 root-owned 或
   其他账号持有的 token。采集 runner 与 API service 都使用独立 `tradingdatas` 账号，使采集写入
   和 API 只读访问协作于同一 SQLite 权限模型，不以 root 运行采集器。内部
   loopback 调用同样必须携带显式 token 或 JWT；没有 localhost 免认证路径；
4. 先执行零调用 plan，核对它报告 190 个合同、187 个 request profile、135 个
   runtime executable probe、52 个 plan-only profile 和 0 次 provider call：

   ```bash
   /opt/tradingdatas/venv/bin/python3 \
     /opt/investment/releases/tradingdatas/current/tools/probe_provider_entitlements.py
   ```

   只有 release commit、正式 Token 文件和受控 evidence 目录均通过 preflight 后，
   才执行一次人工 one-shot。`CODE_COMMIT` 必须来自当前不可变 release 的发布
   manifest，`OBSERVED_AT` 必须是执行前生成的 UTC 秒；不得手填别的版本或时间：

   ```bash
   install -d -o tradingdatas -g tradingdatas -m 0700 \
     /opt/investment-data/tradingdatas/evidence
   CODE_COMMIT='<40-hex-release-commit>'
   OBSERVED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
   sudo -u tradingdatas env \
     CODE_COMMIT="$CODE_COMMIT" \
     OBSERVED_AT="$OBSERVED_AT" \
     TUSHARE_API_URL=https://api.tushare.pro \
     TUSHARE_TOKEN_FILE=/etc/tradingdatas/tushare.token \
     sh -c 'umask 077; exec /opt/tradingdatas/venv/bin/python3 \
       /opt/investment/releases/tradingdatas/current/tools/probe_provider_entitlements.py \
       --execute \
       --code-commit "$CODE_COMMIT" \
       --observed-at "$OBSERVED_AT" \
       --dataset-id cn.dataset.bak_daily \
       --dataset-id cn.dataset.fund_adj \
       --dataset-id cn.dataset.fund_manager \
       > "/opt/investment-data/tradingdatas/evidence/entitlement-$OBSERVED_AT.json"'
   ```

   每次执行必须显式选择 1–5 个属于 135 个 runtime-executable profile 的 dataset。
   单一 resolver 只接受冻结的 literal 与 `observed_at` 五种时钟转换，按
   `Asia/Shanghai` 和有界 `offset_seconds` 确定性生成参数，并只请求官方冻结合同中
   第一个合法输出字段。每个 dataset 最多调用一次、零重试，响应上限固定为
   128 KiB；既有 `bak_daily`、`fund_adj`、`fund_manager` 请求保持不变。52 个需要
   fresh anchor、无界空参数或未冻结枚举的 profile 仍为 plan-only；缺失、重复、
   未知、超过 5 个或包含 plan-only 的选择都必须在读取凭证前整体拒绝。
   stdout evidence 不含 Token、
   Token 路径、原始响应或 provider diagnostic；probe 不写 facts、ingest receipts、
   activation，也不修改 registry、timer 或 API。`entitled_active`/`locked`/`unknown`
   只是一份待审核证据，不能自动启用数据集；
5. 运行一次受控 latest/current collection；
6. 验证 facts、receipts、catalog/query 与 impaired negative cases；
7. 在 generic runner 独立验收后安装唯一采集 service/timer，但保持 disabled；
8. 正式 Token、受控 latest collection 和 API readback 通过后才启用 timer，并观察完整 cadence 周期；
9. 后台运行 bounded backfill。

## 发布门禁

必须分别验证：local、origin/GitHub、production checkout、active release、service/timer、SQLite、真实 provider receipt、API readback 和消费者调用。

## 旧系统退役

新 TradingDatas runtime 和消费者切换通过后：

1. 停止旧写任务；
2. 观察无旧调用；
3. 保留可验证回滚快照；
4. 删除旧服务、cron、代码、文档和依赖；
5. 数据删除另走单独保留策略，不与代码退役混在一起。

## 回滚

回滚只切回已验证的 immutable release，不覆盖 SQLite，不恢复旧 cron，不把旧 provider route 重新引入新系统。
