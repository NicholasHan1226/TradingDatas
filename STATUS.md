# TradingDatas 当前状态

观察时间：2026-09-05 17:13 Asia/Shanghai。本页是可替换的运行快照；源码、运行版本、数据状态和外部入口分别核验。

## 源码与运行

- 本轮目录优化合入 #485，运行代码基线 `a093d407d23fe6cf7f82c1fb2a27359c82b7d803`；候选与精确主线 CI 均通过。纯文档 CI 优化 #484 已合入。
- A股与 Crypto 不可变 current 均为上述代码版本，各 1056 个文件清单通过；实际 API 进程目录与版本一致。定时任务恢复至发布前状态。回退代码版本 `3ad50fc4ca325dea25b49914d5d6189e860cf033` 保留，不回滚数据。
- 源码及本地、服务器 checkout 用 `git rev-parse HEAD origin/main` 当场读取。仅文档提交允许领先于运行版本，不为刷新文档 SHA 重启服务。

## 同轮接口验证

- A股目录 192 项、Crypto 目录 240 项，认证 HTTP 200；数据集身份摘要与发布前一致。
- 16:44 发布前基线：A股目录 15.390 秒、Crypto 5.970 秒。发布后：A股首次 15.591 秒、后续 4.332 秒；Crypto 首次 7.793 秒，均 HTTP 200；财务查询 0.160 秒。首次目录读取仍偏慢，15 秒性能目标尚未在冷启动满足。这是有限次数的真实 HTTP 测量，不是持续 SLA 或全量数据稳定性保证。
- `fina_mainbz` 查询 HTTP 200、1 行，lineage 完整；partial/degraded 与 quality.valid=false 继续如实返回，没有通过清除质量条件制造成功。
- coverage 仍精确统计同一 SQLite 快照，已有索引仅用于加快端点读取；收据 memo 绑定原始内容和 provider binding，当前时钟、完整性和授权校验保持不变。没有新表、索引、迁移、响应缓存或超时放宽。

## 接入、服务与外部边界

源的 empty、partial、stale、provider_error 按数据集/窗口展示，不要求全量 stable 才接入、开发、发布或供数；授权、合同与存储身份校验继续保留。接入口径与排期唯一正文见 [OPERATIONS](docs/OPERATIONS.md)。

- 新闻仍 provider_error；周末时效、未观测和暂停状态独立展示，不当成全平台故障。没有额外付费源探测。
- `tradingdatas.com` 网站可达；`api.tradingdatas.com` 尚无解析，规范域名配置未完成。
- 现有 `td-admin-api.tradingagent.cc/v1/catalog` 从本机读到标准 JSON 401，说明已有外部 API 入口；广州探测仍有边缘 403。无凭据拒绝不是客户成功接入证明。
- 当前已检查凭证记录仅有内部身份，未完成普通客户凭证的外部 catalog/query 验收。Cloudflare 控制台登录与域名/访问配置仍待完成，不能把内部 bootstrap 试读冒充客户接入。
- #395 的 settlement identity/迁移合同草稿不在本轮优化范围。

## 入口与后续验证

[API](docs/API.md)、[架构](docs/ARCHITECTURE.md)、[运维](docs/OPERATIONS.md) 保存长期合同；历史报告见 [reports](docs/reports/README.md)。纯文档快路径保留 required checks，不替代代码测试或生产证据。

下一步是完成规范域名与正式消费者外部读回，并在日常负载中继续观察目录耗时；不因此停止其它接口接入与开发。
