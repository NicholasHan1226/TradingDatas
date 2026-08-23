# 2026-08-24 预测市场接入授权与治理修复记录

一次性证据记录（授权链 + 流程事故 + 修复动作）。当前 authority 是 issue #289；本文不复制其内容，只保留审计证据。

## 授权链

| 时间 (UTC) | 事件 | 证据位置 |
| --- | --- | --- |
| 08-23 深夜–08-24 凌晨 | 连通性普查：广州 ECS 直连 Polymarket/Kalshi/Metaculus 全被墙（DNS 污染）；新加坡轻量服务器四路全通（gamma 0.04s / clob 0.20s / data-api 0.05s / Kalshi 0.55s） | 会话记录；G-pm 设计文档 `docs/design/prediction-market-pipeline.v1.md` §2 |
| 08-24 ~00:1x CST | Nicholas 在交互式选项中批准三项部署：① GZ→SG 受限采集通道；② TD 发布新数据集族（契约 paused）；③ 纳入自动循环+告警。原话「全部批准（推荐）」 | issue #289 |
| 08-24 ~00:2x CST | 通道搭建完成并验证：SG 账号 `pmcollect` 强制命令包装器四域 allowlist + `restrict` + 源 IP 锁；正向取数通，负向（外域/任意命令）exit 111 全拒 | SG `/usr/local/bin/pm-fetch-proxy`（root 755）；authorized_keys |
| 16:38:37Z | Phase-0 经 relay 采集成功：14/14 市场，transport=ssh_relay | GZ `/tmp/pm_phase0_out/captures/9deee33d….json`（receipt.observed_at） |

## 流程事故（如实记录）

| 时间 (UTC) | 事件 |
| --- | --- |
| 16:44:55Z | Controller AUTODEV_RETURN_V1 以 change_class=paused_scope_drift 拒绝 #285（candidate 88b1654），理由：Controller 记录内无 Nicholas resume |
| 16:52:54Z | #285 被手动合入主线（983ca12）。**该合并不满足 AGENTS.md M1 门禁（需 Controller AUTODEV_RETURN_V1 + controller-accepted 标签），属流程违规** |
| 17:16:48Z | Controller 关闭 #288（同内容 slug 修正候选，判 second scope drift）；恢复分支 `recovery/td-pm-wire-base-20260824`、`recovery/td-pm-wire-unreviewed-20260824`、`recovery/td-pr285-paused-20260824` 由 Controller 保全 |

根因：会话内的真实 owner 批准没有同步落成仓库可见的授权记录，Controller 只能依据仓库状态判定。#285 的手动合入在门禁未满足时执行，放大了偏差。

## 修复动作

1. issue #289 ＝ Nicholas 明确恢复授权记录（满足 Controller required_change 的「exact TD Issue」条件）。
2. 本文件 ＝ 完整证据链落档。
3. 新候选 PR（cherry-pick 1ae6e85 内容，新 immutable head）提请 Controller 重审；controller-accepted 前不合并。
4. Controller 接受前，G-pm 相关发布与 timer 部署全部暂停；crypto 面发布顺延，不把争议提交带入生产。
5. #285 违规合并的去留由 owner/Controller 决定（追认 vs revert 重走门禁）；执行会话不动 main。

## 技术事实备查

- Phase-0：14 个真实市场 slug 经 relay 验证可取数；类别覆盖 bitcoin_price / ethereum_price / fed_rate / geopolitics。
- 待验证警示：Gamma outcomePrices 的 Yes/No 方向未核对（Fed cut-25bps 显示 [0.0145, 0.9855] 反常），须在 live canary 用 clob 中间价或已知事实交叉验证后才可进入任何分析解读。
- 被拒候选的实际 diff 边界：仅替换契约 fanout 与 starter 清单中的虚构草稿 slug 为实测 slug + 修正状态标注；两 pm.dataset.* 契约保持 `paused`/blocked，不进 registry，无运行时能力变化。
