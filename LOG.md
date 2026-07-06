# SharedSignals Log
| 时间 | 动作 | 结果 |
|------|------|------|
| 2026-07-06 | 加强 CNFutures 5 分钟采集失败语义 | `rt_fut_min` 采集会保留 provider 错误码/权限错误并以 failed 退出；非空行情桥接 SQLite 写入 0 行时不再标记 ok；API 白名单补入 `rt_fut_min` 便于只读接口自检 |
| 2026-07-05 | 修复 DuckDB 同步空数值失败 | CSV bridge 将数值列空字符串规范化为 NULL；DuckDB sqlite_scan 先按 VARCHAR 读取 SQLite，再用 `TRY_CAST(NULLIF(...,''))` 处理历史空字符串，避免 `market_bars_daily` 单列脏值导致整表同步失败 |
| 2026-07-05 | 修复 A股资产合并覆盖问题 | `stock_company` 后写入不再用空字段覆盖 `stock_basic` 名称、行业、上市日期等字段；`industry` 规范化进入 `sector`；`get_tushare(stock_basic, ts_code=...)` 可读取合并后的 A股资产视图 |
| 2026-07-05 | 修复 5 分钟 read API 市场参数与迁移补列保护 | `/realtime_5min` 支持 `market` 参数并默认兼容 A股；非 A股市场可通过同一 API 读取 `market_bars_intraday`；schema hash 已最新但旧表缺可空列时仍会自动补齐 |
| 2026-07-05 | 扩展 CNFutures 5 分钟盘口与到期字段 | `market_bars_intraday` 增加可空 bid/ask、盘口量、last_trade_date/expiry_date；CSV bridge 可透传 `rt_fut_min` 盘口字段并从 `market_assets` 补合约到期字段 |
| 2026-07-05 | API 开盘高压稳定性修复 | SharedSignals API 增加 256 accept backlog，客户端断连降级 debug；生产复压 160/160 正常峰值与 640/640 尖峰请求均 200，TradingAgent 队列无新增副作用 |
| 2026-07-04 | 记录 RSS/RSSHub 迁移期边界与系统邮件 smoke | 旧 RSSCollector cron 禁用；RSSHub/旧 DB 标记为残留资产；系统邮件 `notice@tradingagent.cc -> soc@coze.email` 实发成功 |
| 2026-07-04 | 修复低频宏观/事件/资产桥接与 watchdog 误报 | P4 宏观 17/17 成功；shibor_lpr、cctv_news、index_global、etf_basic、fut_basic 已进入 read model；完整测试 79 passed |
| 2026-06-29 | 创建文件夹结构 | 初始化 |
| 2026-06-29 | Unit2: 迁移 RSS+Tushare+bridge 软链, 新增 market_calendar.py | bridge/ + reference/ 软链就位; market_calendar 实盘验证通过 (today=True, next=2026-06-30) |
