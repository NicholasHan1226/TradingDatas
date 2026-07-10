# Infrastructure

## 服务器
| 角色 | IP | 规格 | 职责 |
|------|-----|------|------|
| 主服务器 | 8.138.181.177 | 4核8GB/99GB | SharedSignals、MarketGraph、TradingAgent 生产主节点 |
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
- SQLite + DuckDB mirror：`/opt/investment/SharedSignals/runtime/read_model/marketdata.sqlite` 是生产 read model，`/opt/investment/SharedSignals/data/marketdata.duckdb` 每小时同步用于只读分析加速；Redis 未启用。
- 旧 RSS/RSSHub 资产仅作历史审计，不作为当前生产采集或 API 数据源。

## 网络
- SharedSignals API：`127.0.0.1:8082`，通过 `signals.tradingagent.cc` 受控暴露；不得直接开放公网端口
- 公网路径：Cloudflare edge → 新加坡 `sharedsignals-cloudflared.service` → 新加坡 loopback `127.0.0.1:8082` → `sharedsignals-sg-relay-tunnel.service` 的 SSH reverse forward → 广州 `127.0.0.1:8082`。同一 Tunnel 还承载 TA 主站/API；SSH 服务因此保留广州 Nginx `127.0.0.1:80` reverse forward，而新加坡现有 TA Docker 自己占用 `127.0.0.1:8787`，不得再转发或覆盖 8787。广州和新加坡均不对公网开放 8082；这条路径不使用广州 Nginx 源站证书，避免未备案大陆公网源站的 403/525 问题。
- RSSHub :1200 已停用；旧 RSSCollector cron 条目已从模板和生产 crontab 删除，恢复前必须重新设计 SharedSignals collector 并直接写入 read model
- Mihomo :7890/:7891 (Clash代理, Binance/Polymarket走代理)
- 新加坡不运行 RSSHub/rsync staging，也不保存 SQLite/DuckDB；广州通过同一受控 SSH 服务连接新加坡 proxy `127.0.0.1:18888`，并把广州 API 反向转发到新加坡 loopback `127.0.0.1:8082` 供 cloudflared 使用。
- `cron/external_api_probe.sh` 每 5 分钟无凭据请求公网 `/health`；HTTP 401 表示 Cloudflare/Tunnel/API 链路已到达鉴权门，525、超时或其它状态为失败。可选 `SHAREDSIGNALS_EXTERNAL_PROBE_TOKEN` 才使用 200 口径，仓库不保存 token。

## API Keys
- 详见 .env (不在此文档记录值)
- 密钥存在不等于现役生产采集；当前现役采集源和频率以 `STATUS.md`、`collectors/tushare/config.yaml`、cron 和 `/capabilities` 为准。

## Git Repositories
- SharedSignals: https://github.com/NicholasHan1226/SharedSignals.git
- MarketGraph: https://github.com/NicholasHan1226/MarketGraph.git
- TradingAgent: https://github.com/NicholasHan1226/Tradingagent.cc.git
