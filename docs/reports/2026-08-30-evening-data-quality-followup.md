# 2026-08-30 晚间数据质量后续

范围：Datas PM下的发布后复查、财务空结果诊断、全球新闻原值保留和下一交易时段验收准备。
本记录区分已观察事实与待完成动作；未新增服务、定时器、权限、预算或交易能力。

## 发布后三小时观察

20:17服务器仍运行A股a735163、Crypto15f463e，原timer正常，数据盘348GB可用。
20:18认证catalog：A股192项（88success、42empty、57paused、5unobserved），Crypto240项success；
请求耗时9.02秒/6.08秒，无目录分页遗漏。20:19认证query样本国内新闻、券商推荐、BTC现货和
资金费率的质量/lineage有效；国际新闻和income保留各自partial原因。以上不是连续健康声明。

20:19同一已验证SQLite快照：财务7项当前config各49份回执，批次47/48；balancesheet
48empty+1failed，其余各49empty，没有无效回执历史。window均为ann_date=20260830。
旧income事实保留000006.SZ公告20260826、报告期20260630，另有其它真实公告代码。
当前registry在20260826窗口的下一批是000001.SZ，其历史数据无正控；因此不改universe、
不跳写进度、不循环采到非空。使用既有transport内核做固定000006.SZ两日期对照，
仅证明transport参数行为，不生成或冒充SQLite receipt/新合同observed。

20:36对照完成：同一000006.SZ/相同默认字段，20260826返回2行且代码、公告日、
85字段验证通过；20260830返回0行。两次请求各约0.25秒，无重试、无SQLite写入或回执。
这证明income该历史样本的请求参数有效、周日为空，不能外推六项其它财务接口或全股票池。
维护窗口前后各保留61秒限频间隔；20:39原timer/API均active，release仍为a735163。

## 国际新闻已验证缺口

global的response_completeness为空；查询层主动置空未证明的发布时间水位，保留partial。
成功行的日期-only原值会被归一化午夜覆盖，原字符串未另存；实际存储样本只有归一化时间，
不能逆推出上游是否真正给出午夜。minor修复只为未来成功行保留原始item/原值/精度，
不把该修复描述为全球新闻完整覆盖。冻结合同与测试见同日global-news-provenance报告。

## 下一交易时段/跨日验收

先用当前registry和真实交易日历判断是否开市，再观察原timer，不创建替代采集任务。
分钟验收必须包含：真实provider时间属于请求日、非空事实与事务receipt一致、相邻轮次
代码批次推进、固定catalog/query认证回读、TA分钟兼容读取；周日模拟不替代这些证据。
财务跨日验收必须分清新日与旧日window，在同config/universe下验证旧日期继续推进，
且空响应仍无数据水位。保持当前预算，不宣称5971代码的全覆盖。

## 独立下一批候选

现有矩阵可优先复核forecast、pledge_detail；次选etf_mins、fut_daily、opt_basic。
五项均on_demand/paused，当前静态请求可解析，但没有fresh HTTPS activation证据。
etf_mins还需重验etf_basic seed；fut_daily/opt_basic旧HTTP为schema_subset需字段复核。
旧20260720 HTTP矩阵不能替代现账号权限。候选不受无关数据集stable缺失阻断，但本轮
未激活、未改cadence，也不把它们加入timer。

## 验证与运行入口

仓库：当前registry、quicksync/request observations、activation waves、OPERATIONS。
外置本轮诊断脚本及脱敏输出：`work/evening-followup-20260830/`。纯transport控制
必须暂停原timer、自然排空、持有同collect.lock并使用既有服务身份/凭据；结束恢复原timer。
provider对照结果见上文；候选CI和生产发布仍待完成，不能由诊断成功推断生产修复完成。
