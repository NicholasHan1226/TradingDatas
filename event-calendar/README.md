# A股事件日历（存档构建）

**状态：存档，未上线。** Nicholas 于 2026-08-24 决定：页面只进仓库存档，不发布到公网站点。
因此本目录**刻意放在 `static/` 之外**——`static/**` 的改动会触发 deploy.yml 自动发布到
https://tradingdatas-admin.pages.dev/ ，本目录不会。

## 文件

| 文件 | 作用 |
|---|---|
| `index.html` | 页面外壳 + 全部样式（设计 token 三段式定义，支持深浅色） |
| `app.js` | 渲染器：读同目录 JSON，画月历格、当日明细表、远期年份折叠 |
| `calendar-data.json` | 结构化事件数据（schema `tradingdatas.event-calendar.v0`） |

## 本地查看

```bash
cd event-calendar && python3 -m http.server 8011
# 打开 http://localhost:8011/
```

直接双击 index.html 会因浏览器对 file:// 的 fetch 限制看不到数据（页面会显示"数据未接入"，属预期的失败关闭表现）。

## 数据现状与来源

`calendar-data.json` 是 2026-08-23 从桌面静态研究页（Tushare 数据，覆盖 2026-07 至
2029-07，92 个事件日、725 条事件）提取的一次性种子快照，**不是实时管道产物**。

实时数据的前置条件（均为生产变更，需治理窗口）：

1. `cn.dataset.forecast` 已改为 `event` + ann_date-only snapshot 并单独激活；
   需 GZ 切到含该合同的 head 后才能产生非空 SUCCESS（empty ≠ success）；
2. `cn.dataset.share_float` / `cn.dataset.disclosure_date` 因 ann_date 分区在每日
   00:30 扫描中恒得「可信为空」，2026-08 起分区冻结 → 已由 PR #304 把两者改为
   event 节律修复；合并部署并回补缺口后即恢复产出。

## 将来上线的路径

1. td-v1 公告数据集恢复采集（PR #304 部署 + forecast 单独激活）并验证产出；
2. 用管道按本 schema 重新生成 `calendar-data.json`；
3. 把整个 `event-calendar/` 目录移入 `static/` 下（会自动部署到公开站点）——该步骤是
   对外可见动作，需 Nicholas 明确批准。
