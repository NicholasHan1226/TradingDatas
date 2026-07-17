# Infrastructure

> 本文件包含稳定拓扑和带日期的 legacy 运行记录，不是当前生产就绪证明。
> IP、路由、服务、数据路径或“已发布”字样可能已过期；本轮 fresh 生产事实和 NO-GO/GO
> 只认 [STATUS.md](../STATUS.md)。目标 SharedSignals 产品合同以
> [AGENTS.md](../AGENTS.md) 与根 [API_CONTRACT.md](../API_CONTRACT.md) 为准。

## 服务器
| 角色 | IP | 规格 | 职责 |
|------|-----|------|------|
| 主服务器 | 8.138.181.177 | 4 vCPU/约15GiB RAM；约99GB根盘；500GB 数据盘 | SharedSignals、MarketGraph、TradingAgent 生产主节点；`/dev/nvme1n1` 已建 ext4，UUID=`3f7cbf99-b15e-4c54-94cc-a57e38412874`，持久挂载于 `/opt/investment-data`。writer handoff readback：根盘 57%/41GB free，数据盘 12%/433GB free |
| 新加坡 | 47.82.153.58 | 30GB | 境外代理 relay（Polymarket/Crypto）和 SharedSignals Cloudflare Tunnel connector；不存权威数据 |
| Mac Mini | 本地 | — | TradingAgent A股模拟盘可选 Hermes/同花顺 GUI 第二路径；SharedSignals 不依赖 Mini |

## 域名
- tradingagent.cc — 统一域名
- dashboard.tradingagent.cc — Cloudflare前端看板入口
- api.tradingagent.cc — TradingAgent API 入口
- signals.tradingagent.cc — SharedSignals 外部受控 API 入口；Cloudflare DNS CNAME 指向 tunnel `88b5a0af-35fe-438d-b294-2d1b441631ca.cfargotunnel.com`。新加坡 cloudflared 通过本机 `127.0.0.1:8082` 接收广州 SSH reverse tunnel 转发，仍必须使用 SharedSignals API key/JWT 鉴权。外部 agent 只使用 `https://signals.tradingagent.cc`。

## 邮件
- 交易类: notice@tradingagent.cc → tradingadviser@coze.email
- 系统类: notice@tradingagent.cc → soc@coze.email

## 环境
- Python: 3.12.3 (venv /opt/sharedsignals/venv)
- OS: Ubuntu 24.04
- 存储 epoch（2026-07-13 20:07）：物理 authority 为 `/opt/investment-data/SharedSignals/runtime/read_model`，SharedSignals backups 为 `/opt/investment-data/SharedSignals/backups`，finance runtime-backups 为 `/opt/investment-data/runtime-backups`；canonical 旧路径由三个 bind mount 保持。`/etc/systemd/system/sharedsignals-api.service.d/20-finance-data-mount.conf` 是 API fail-closed guard。20:07 first-write run=`e5a1fd619a6e` 后旧 `read_model.root-predata-20260713T1956` 已 stale，不得直接回切。
- 迁移/回退证据：`/opt/investment-data/migration-evidence/storage-migration-20260713T192703+0800`、`/opt/investment/SharedSignals/logs/cron/storage-migration-20260713T192703+0800`、`/etc/fstab.before-finance-data-20260713T193012+0800`。只释放了两组经双 SHA 验证的旧根盘重复 backups/runtime-backups；旧 read model、DB、Journal、ledger、history、evidence 和空 staging 保留。
- 20:02:53–20:03:06 near-miss：独占锁提前释放约 13 秒后立即重获；DB/underlay size+mtime 无变化、无 collector、无写入。生产 `summary.json` 未包含该事实，事故审计以 [resource_pressure_2026-07-13.md](resource_pressure_2026-07-13.md) 为补充入口。
- SQLite + DuckDB mirror：`/opt/investment/SharedSignals/runtime/read_model/marketdata.sqlite` 是生产 read model，`/opt/investment/SharedSignals/data/marketdata.duckdb` 是只读分析镜像；2026-07-13 事故后 DuckDB cron 保持暂停，不再称为“每小时同步”。恢复时每轮先在 authority 同目录的 `.duckdb_sync_snapshots/` 用 SQLite backup API 生成 0600 临时 snapshot，16 表 sync 与 reconcile 只读该固定 source point，结束后精确清理；目录为 0700。默认在创建文件前按 `max(main file, page_count*page_size) + 5 GiB` 计算空间并要求 snapshot 落盘后 filesystem 使用率不超过 90%，backup 内部 deadline 240 秒，外层 cron 仍为 600 秒；超过两个外层 timeout 的固定前缀孤儿文件只由持有单实例锁的下一轮清理。Redis 未启用。
- DuckDB mirror schema 迁移（2026-07-13 production 已发布）：`create_schema()` 以单事务按“全部表 → 全部缺列 → 全部索引”迁移并验证合同，任一结构漂移失败即回滚；旧事件只从 SQLite authority 回填三项 identity 元数据，正文保持 append-only，reconcile 同时核验行数与 identity。生产本轮 16 表全部 delta=0，`market_events` 67,266/67,266 且 identity mismatch=0，三行业空表 0/0 合法；缺 source/mirror 或语义漂移仍 fail-closed。
- DuckDB source snapshot P0（2026-07-13 code layer）：修复 collectors 与 DuckDB sync 同持 maintenance shared lock 时，逐表 live `sqlite_scan` 和事后另开 live SQLite reconcile 产生跨时点视图的问题。snapshot metadata 记录 source inode/size/mtime、WAL/SHM、snapshot id、空间门禁、权限和清理结果；watchdog latest 保留连续失败计数、最后成功/失败时间和最近失败摘要，JSONL 历史 append-only。生产启用与 live green 证据必须单独验收，不能由本地测试或 GitHub main 代替。
- Tushare event runtime：无原生 ID/URL 的 `namechange` 与 `report_rc` 只使用各自明确的稳定业务复合键；已有同内容 revision 的 0 写入是合法 idempotent no-change，非 event 表非空采集写 0 行仍按失败处理。
- 旧 RSS/RSSHub 资产仅作历史审计，不作为当前生产采集或 API 数据源。

## 网络
- SharedSignals API：`127.0.0.1:8082`，通过 `signals.tradingagent.cc` 受控暴露；不得直接开放公网端口
- 公网路径：Cloudflare edge → 新加坡 `sharedsignals-cloudflared.service` → 新加坡 loopback `127.0.0.1:8082` → `sharedsignals-sg-relay-tunnel.service` 的 SSH reverse forward → 广州 `127.0.0.1:8082`。同一 Tunnel 还承载 TA 主站/API；SSH 服务因此保留广州 Nginx `127.0.0.1:80` reverse forward，而新加坡现有 TA Docker 自己占用 `127.0.0.1:8787`，不得再转发或覆盖 8787。广州和新加坡均不对公网开放 8082；这条路径不使用广州 Nginx 源站证书，避免未备案大陆公网源站的 403/525 问题。
- RSSHub :1200 已停用；旧 RSSCollector cron 条目已从模板和生产 crontab 删除，恢复前必须重新设计 SharedSignals collector 并直接写入 read model
- Mihomo :7890/:7891 (Clash代理, Binance/Polymarket走代理)
- 新加坡不运行 RSSHub/rsync staging，也不保存 SQLite/DuckDB；广州通过同一受控 SSH 服务连接新加坡 proxy `127.0.0.1:18888`，并把广州 API 反向转发到新加坡 loopback `127.0.0.1:8082` 供 cloudflared 使用。
- `cron/external_api_probe.sh` 每 5 分钟通过广州到新加坡的受控 SSH relay，由新加坡节点无凭据请求公网 `/health`；HTTP 401 表示 Cloudflare/Tunnel/API 链路已到达鉴权门，525、超时或其它状态为失败。可选 `SHAREDSIGNALS_EXTERNAL_PROBE_TOKEN` 才使用 200 口径，仓库不保存 token。

## API Keys
- 详见 .env (不在此文档记录值)
- 密钥存在不等于现役生产采集；当前现役采集源和频率以 `STATUS.md`、`collectors/tushare/config.yaml`、cron 和 `/capabilities` 为准。

## Git Repositories
- SharedSignals: https://github.com/NicholasHan1226/SharedSignals.git
- MarketGraph: https://github.com/NicholasHan1226/MarketGraph.git
- TradingAgent: https://github.com/NicholasHan1226/Tradingagent.cc.git
