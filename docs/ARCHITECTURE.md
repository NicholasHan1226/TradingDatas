# TradingDatas Architecture

## 产品边界

TradingDatas 是金融数据基础设施，不是研究或交易系统。它负责 provider catalog、采集、无损标准化、SQLite facts、transaction receipts、数据质量元数据和只读 API。

## 权威顺序

1. dataset registry：数据集身份、provider binding、schema、cadence、entitlement 和 query policy；
2. SQLite facts + transaction-scoped receipts：真实采集结果；
3. registry + receipts + 读取时钟：runtime metadata；
4. HTTP API：只读投影。

JSON 缓存、日志、HTTP 200、静态接口数量、消费者状态和旧数据库都不是权威。

## 通用采集

普通 Tushare 请求统一为：

```text
api_name + params + fields -> fields/items
```

registry 声明 request template、variants、window、fanout、pagination、字段、主键、分区、预算、频率和回填。executor 不包含 dataset_id 或 api_name 条件分支。

官方接口文档只通过批量 compiler 进入 registry：`tools/snapshot_tushare_contracts.py` 读取固定能力目录，批量解析输入/输出表与更新说明，冻结 URL 和内容哈希；`tools/compile_tushare_runtime_contracts.py` 保留已复核合同，并把其余官方接口编译为可发现但 paused 的 append-only 合同；registry compiler 再结合独立 activation/entitlement 声明生成运行 registry。不能确定的 entitlement、主键、频率或参数模板必须保持 paused，不用猜测填充。

四种 request shape：

- snapshot/date range；
- entity fanout；
- dimension fanout；
- event/intraday window。

当前数据优先于历史回填；回填必须有界、可恢复、可观察，并遵守账号级和 API 级预算。

## 通用存储

所有 provider-native 数据进入同一类通用事实表。provider 返回的 payload 必须无损保留；技术列不能覆盖 provider 字段。每个真实写事务必须同时提交 success receipt；rollback 后不得留下 success。

empty、failed、permission denied、rate limited、validation failed 和 storage failed 必须分开记录。未知字段保留并标记 schema drift，不能静默删除。

## 数据服务

catalog 和 query 只读 SQLite。缺数据库、缺表、缺 receipt、损坏或 metadata 不一致时 fail closed；不得同步调用 provider 或回退旧文件/旧数据库。

## 扩展模型

新增普通 Tushare dataset 只改 registry/config。新增 provider 仅在 transport、auth 或 pagination 不同时增加 provider adapter。公共 API 不随数据源增长。
