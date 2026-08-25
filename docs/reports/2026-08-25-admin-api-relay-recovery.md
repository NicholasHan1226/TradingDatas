# 2026-08-25 管理 API 中继回源恢复记录

## 结论

2026-08-25 10:19 CST，`td-admin-api.tradingagent.cc` 已通过独立的新加坡中继回源恢复。
故障发生在广州 ECS 到 Cloudflare edge 的 Tunnel 出站连接；广州本地
`tradingdatas-admin.service` 与数据采集 timer 在故障期间保持运行。本次没有变更管理员
Token、用户 API Key、DNS、数据库、facts/receipts、provider 配置或采集计划。

## 实施边界

- 广州新增并启用 `tradingdatas-admin-relay-origin.service`，仅反向转发管理 API 的
  `127.0.0.1:18084`。
- 新加坡中继新增并启用 `tradingdatas-admin-api-tunnel.service`，使用既有 Tunnel 身份连接
  Cloudflare；凭据保留在 root-only 文件中，未写入仓库或日志。
- 既有数据管道的 SSH/SOCKS relay、`tradingdatas-provider-native-collect.timer`、
  `tradingdatas-v1-internal.service` 与 SQLite 均未修改。

## 2026-08-25 新鲜验证

| 层级 | 结果 |
|---|---|
| 广州管理服务 | `active` / `enabled`；本地 `/portal/api/me` 返回 `401` |
| 广州反向回源 | `active` / `enabled` |
| 新加坡 Tunnel | `active` / `enabled`；4 条连接在 `sin09`、`sin11`、`sin20`、`sin12` 注册 |
| 中继 origin | `/portal/api/me` 返回 `401` |
| 公网 API | `/portal/api/me` 返回 `401`；管理 API CORS preflight 返回 `204` |
| 管理工作台 | 客户、用量、数据管道、运行健康、数据浏览均读取生产数据 |
| 数据浏览 | 目录返回 192 项；`cn.dataset.anns_d` 只读查询返回 20 条样本并提供下一页游标 |
| 客户工作台 | 概览、权限、文档、返回管理端与退出登录入口均可用 |

数据浏览首次目录读取约 45 秒，功能已完成但性能不理想，应单独做 catalog 投影与网络时延
分析，不能把本次连通性恢复等同于性能问题已解决。

运行健康面板同时报告 14 个失败、71 个警告和 42 个提示；数据管道页报告 192 个数据集、
136 个激活、14 个运行失败和 85 个质量降级。这证明面板读取了真实运行状态，不代表底层
数据集全部健康。具体 dataset 的 receipt、provider 和数据质量修复必须另行评审，不应在
公网回源事故中通过重跑、改状态或隐藏告警处理。

## 回滚

1. 在新加坡中继停用 `tradingdatas-admin-api-tunnel.service`。
2. 在广州停用 `tradingdatas-admin-relay-origin.service`。
3. 验证广州本地 `127.0.0.1:18084/portal/api/me` 仍返回 `401`。
4. 单独恢复广州直连 Tunnel，并验证公网 `401`、CORS `204`、登录和两套工作台后再结束回滚。

回滚不删除 Tunnel 凭据，不修改 DNS、Token、数据库、采集 service/timer 或历史收据。
