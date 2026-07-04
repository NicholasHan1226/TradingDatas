# SharedSignals Log
| 时间 | 动作 | 结果 |
|------|------|------|
| 2026-07-04 | 记录 RSS/RSSHub 迁移期边界与系统邮件 smoke | 旧 RSSCollector cron 禁用；RSSHub/旧 DB 标记为残留资产；系统邮件 `notice@tradingagent.cc -> soc@coze.email` 实发成功 |
| 2026-07-04 | 修复低频宏观/事件/资产桥接与 watchdog 误报 | P4 宏观 17/17 成功；shibor_lpr、cctv_news、index_global、etf_basic、fut_basic 已进入 read model；完整测试 79 passed |
| 2026-06-29 | 创建文件夹结构 | 初始化 |
| 2026-06-29 | Unit2: 迁移 RSS+Tushare+bridge 软链, 新增 market_calendar.py | bridge/ + reference/ 软链就位; market_calendar 实盘验证通过 (today=True, next=2026-06-30) |
