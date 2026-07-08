# Infrastructure

## 服务器
| 角色 | IP | 规格 | 职责 |
|------|-----|------|------|
| 华南3/广州 (主) | 8.138.181.177 | 4核8GB/99GB | SharedSignals、MarketGraph、TradingAgent 生产主节点 |
| 新加坡 | 47.82.153.58 | 30GB | 境外 RSS mirror / 待收口节点 |
| Mac Mini | 本地 | — | TradingAgent A股模拟盘可选 Hermes/同花顺 GUI 第二路径；SharedSignals 不依赖 Mini |

## 域名
- tradingagent.cc — 统一域名
- dashboard.tradingagent.cc — Cloudflare前端看板 (未来)
- api.tradingagent.cc — API反代 (未来)

## 邮件
- 交易类: notice@tradingagent.cc → tradingadviser@coze.email
- 系统类: notice@tradingagent.cc → soc@coze.email

## 环境
- Python: 3.12.3 (venv /opt/sharedsignals/venv)
- OS: Ubuntu 24.04
- SQLite + DuckDB mirror：`/opt/investment/SharedSignals/runtime/read_model/marketdata.sqlite` 是生产 read model，`/opt/investment/SharedSignals/data/marketdata.duckdb` 每小时同步用于只读分析加速；Redis 未启用。
- 旧 RSS/RSSHub 资产仅作历史审计，不作为当前生产采集或 API 数据源。

## 网络
- Nginx :80 → 127.0.0.1:8082 (API server)
- RSSHub :1200 已停用；旧 RSSCollector cron 条目已从模板和生产 crontab 删除，恢复前必须重新设计 SharedSignals collector 并直接写入 read model
- Mihomo :7890/:7891 (Clash代理, Binance/Polymarket走代理)
- 新加坡 → rsync → 主服务器 staging (每5min)

## API Keys
- 详见 .env (不在此文档记录值)
- Tushare/Firecrawl/Tavily/DeepSeek 4个key

## Git Repositories
- SharedSignals: https://github.com/NicholasHan1226/SharedSignals.git
- MarketGraph: https://github.com/NicholasHan1226/MarketGraph.git
- TradingAgent: https://github.com/NicholasHan1226/Tradingagent.cc.git
