# TradingDatas 当前状态

观察时间：2026-09-05 13:17 Asia/Shanghai。本页是可替换摘要，运行事实由同轮服务器、
receipt 与认证 API 读回确认；候选修复不等于已部署。

## 源码、发布和运行

- 最近已合主线：`878567a253c00c2fe26973efb80d35c9b4392c22`（#478）。
- A股与 Crypto 生产不可变 `current` 均为上述 SHA；发布清单各 1052 个文件，
  `verify=true`，API 实际进程目录一致。此状态与服务器源码 checkout 分开核对。
- 双认证 catalog HTTP 200。13:03–13:07 有界测量：A股
  16.647 / 16.839 / 15.645 / 5.851 秒，四次三次超过既有 15 秒门槛；
  Crypto 8.441 / 11.121 / 9.543 / 11.295 秒。不能用最后一次达标掩盖整组未通过。
- `fina_mainbz` 真实查询 HTTP 200、lineage 完整，但仍为 partial、degraded、
  quality.valid=false；字段漂移与缺失需按上游响应合同处理，不删质量条件制造可用。
- 本轮正在修复 catalog 历史 receipt 读取成本；候选测试与发布另行验收。

## 接入与外部边界

接入成功口径与排期唯一正文为 [OPERATIONS](docs/OPERATIONS.md)「Datas PM 接入口径」。
correct contract + empty/provider_error 是明确列出的外部事实，不阻止下一可接接口；
empty 不等于 success，不伪造非空，不提高 catalog 超时门槛或发明新晋级门禁。
每日交付仍须实际发布、适用的双 catalog 门槛及真实 receipts；GitHub 合并不足以验收。

- next-wave：`fina_mainbz`、`pledge_detail`、`top10_cb_holders` 已有接入合同；
  具体早先读回见 [next-wave 报告](docs/reports/2026-09-05-next-wave-onboarding.md)。
- #395 仍为资金费率 settlement 合同草稿，涉及 identity/迁移及来源合同决定；
  不是编译或合并冲突，不自动代选方案。
- 单数据集供应商失败、empty、paused、stale 与内部性能问题分别跟踪，
  不把单次 HTTP 200 写成全量 stable。

## 历史与下一步验证

本页原有 693 行历史/重复快照保留在
[本轮前的固定 Git 版本](https://github.com/NicholasHan1226/TradingDatas/blob/878567a253c00c2fe26973efb80d35c9b4392c22/STATUS.md)，
不再与当前摘要并列为事实。既有重要报告继续位于 [docs/reports](docs/reports/README.md)。
长期合同见 [API](docs/API.md)、[架构](docs/ARCHITECTURE.md)、[运维](docs/OPERATIONS.md)。

下一次更新需分别写明精确主线、双发布清单、实际进程、固定次数延迟测量及查询质量；
不得以改配置、清失败状态或重启后的暂时低负载替代根因验证。
