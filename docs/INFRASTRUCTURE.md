# Infrastructure

## 服务器
| 角色 | IP | 规格 | 职责 |
|------|-----|------|------|
| 主服务器 | 8.138.181.177 | 4核8GB/99GB | SharedSignals、MarketGraph、TradingAgent 生产主节点 |
| 新加坡 | 47.82.153.58 | 30GB | 境外代理 relay（Polymarket/Crypto）；RSS/RSSHub 已退役归档 |
| Mac Mini | 本地 | — | TradingAgent A股模拟盘可选 Hermes/同花顺 GUI 第二路径；SharedSignals 不依赖 Mini |

## 域名
- tradingagent.cc — 统一域名
- dashboard.tradingagent.cc — Cloudflare前端看板入口
- api.tradingagent.cc — TradingAgent API 入口
- signals.tradingagent.cc — SharedSignals 外部受控 API 入口；Cloudflare DNS 使用橙云 A 记录指向主服务器 `8.138.181.177`，广州 Nginx 在 443 终止源站 TLS 后反代到 `127.0.0.1:8082`，仍必须使用 SharedSignals API key/JWT 鉴权。Tunnel 不再承载该 hostname；外部 agent 应使用 `https://signals.tradingagent.cc`。

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
- Nginx :80/:443 → Cloudflare 代理后的 SharedSignals 源站入口，反代 `127.0.0.1:8082`；公网不开放 8082。源站证书当前为临时自签名证书，Cloudflare 回源使用 Full 模式，后续应替换为 Cloudflare Origin CA 证书并切换 Full (strict)。
- RSSHub :1200 已停用；旧 RSSCollector cron 条目已从模板和生产 crontab 删除，恢复前必须重新设计 SharedSignals collector 并直接写入 read model
- Mihomo :7890/:7891 (Clash代理, Binance/Polymarket走代理)
- 新加坡仅作为 Polymarket/Crypto 境外代理 relay，不运行 RSSHub/rsync staging；主服务器通过 SSH 隧道连接新加坡 127.0.0.1:18888

## API Keys
- 详见 .env (不在此文档记录值)
- 密钥存在不等于现役生产采集；当前现役采集源和频率以 `STATUS.md`、`collectors/tushare/config.yaml`、cron 和 `/capabilities` 为准。

## Git Repositories
- SharedSignals: https://github.com/NicholasHan1226/SharedSignals.git
- MarketGraph: https://github.com/NicholasHan1226/MarketGraph.git
- TradingAgent: https://github.com/NicholasHan1226/Tradingagent.cc.git
