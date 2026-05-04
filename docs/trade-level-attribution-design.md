# 交易级归因层设计

## 1. 文档目标

本文档定义稳定池之后的交易级归因能力。

目标不是直接生成新的策略规则，而是回答：

```text
稳定池候选的亏损交易和回撤段交易，在入场前到底有什么共同特征？
```

交易级归因层用于生成少量、可验证的过滤假设，再交给过滤器实验层验证。

本文档只涉及：

- 交易级归因对象
- 入场前特征采集
- 回撤段与亏损交易标记
- 分桶与对比口径
- 防过拟合约束
- readmodel、API 与前端展示方向

本文档不改变：

- `ema_pullback_atr_v2` 原始入场语义
- SL / TP 生成语义
- `risk_pct_of_cash_allocation`、`cash_allocation_pct`、`leverage` 的含义
- 现有执行层成交、gap open、同 bar 优先级语义
- 稳定池候选定义
- 过滤器实验层已有执行方式

## 2. 背景

当前稳定池中的候选组合在 BTC / ETH 1H 上具备较高 OOS 收益，但最大回撤仍偏高。

默认过滤器实验已经验证：

- ADX 过滤整体降低 OOS，且多数情况下增加回撤
- ATR 分位过滤整体降低 OOS，未稳定降低回撤
- HTF EMA50/200 趋势过滤收益损失过大
- 多过滤器叠加交易保留率过低，属于过度过滤

这说明问题不应继续从通用市场状态过滤器出发，而应先分析：

- 哪些交易贡献了主要亏损
- 最大回撤期内的交易有什么共同特征
- 盈利交易和亏损交易的入场前状态有什么差异
- long / short、BTC / ETH、不同参数组之间是否存在稳定坏特征

交易级归因层的定位是：

```text
稳定池候选 -> 交易级归因 -> 简单候选规则 -> 过滤器实验 -> OOS / 跨候选验证
```

## 3. 核心原则

### 3.1 归因只生成假设

交易级归因不能直接输出“推荐上线规则”。

归因结果只能形成候选假设，例如：

```text
trend_gap_atr 过低时，stop loss 交易显著集中。
```

该假设必须经过独立过滤器实验和 OOS 验证后，才允许进入稳定池建议。

### 3.2 防止过拟合优先于发现规则

交易级归因天然存在数据挖掘风险。

因此第一版必须把防过拟合约束写入工作流，而不是只放在人工判断里。

### 3.3 不以最高收益为目标

交易级归因后的规则评估不追求收益最大化。

优先指标是：

- 最大回撤下降
- OOS/DD 提升
- PF 不下降或小幅改善
- OOS 交易数不过度下降
- 跨候选、跨标的表现一致

### 3.4 不默认改风险参数

本层不通过降低杠杆、降低 `risk_pct_per_trade` 或修改 SL/TP 解决回撤。

当前研究问题是：

```text
在原风险配置不变的前提下，识别哪些入场状态更容易制造回撤。
```

## 4. 归因对象

## 4.1 单笔交易

每一笔 trade 是最小归因对象。

基础字段来自现有 `TradeRecord`：

- `trade_id`
- `run_id`
- `symbol`
- `side`
- `entry_time`
- `entry_price`
- `exit_time`
- `exit_price`
- `qty`
- `gross_pnl`
- `fee`
- `net_pnl`
- `return_pct`
- `holding_bars`
- `entry_reason`
- `exit_reason`
- `planned_stop_loss_price`
- `planned_take_profit_price`

## 4.2 回撤段交易

回撤段交易是指发生在某个 run 的最大回撤区间内的交易。

第一版至少标记：

- 是否在最大回撤区间内开仓
- 是否在最大回撤区间内平仓
- 该交易对回撤加深的贡献

后续可扩展为多段回撤：

- Top 3 drawdown windows
- rolling drawdown windows
- OOS drawdown windows

## 4.3 盈利贡献交易

盈利贡献交易用于与亏损交易对比。

第一版标记：

- `big_win`：净利润进入该 run 前 20% 的交易
- `big_loss`：净利润进入该 run 后 20% 的交易
- `stop_loss_trade`
- `take_profit_trade`

## 5. 入场前特征

## 5.1 已有信号特征

`ema_pullback_atr_v2` 的 `SignalIntent.meta_json.feature_values` 已包含部分入场前特征：

- `trend_fast_ema`
- `trend_slow_ema`
- `entry_ema`
- `atr`
- `close`
- `high`
- `low`
- `previous_high`
- `previous_low`

第一版应把开仓 signal 的 `meta_json.feature_values` 关联到对应 trade row。

## 5.2 派生特征

归因 readmodel 需要派生以下字段：

```text
trend_gap_pct = abs(trend_fast_ema - trend_slow_ema) / close
trend_gap_atr = abs(trend_fast_ema - trend_slow_ema) / atr
entry_distance_atr = abs(entry_price - entry_ema) / atr
breakout_distance_atr = abs(close - previous_high_or_low) / atr
atr_pct = atr / close
stop_distance_pct = abs(entry_price - planned_stop_loss_price) / entry_price
take_profit_distance_pct = abs(planned_take_profit_price - entry_price) / entry_price
```

其中：

- long 使用 `previous_high`
- short 使用 `previous_low`
- 缺失字段必须保留为 `null`，不能用 0 代替

## 5.3 可后续补充的特征

后续可以补充：

- EMA slope
- trend fast / slow 斜率
- 入场前 N 根 K 线方向一致性
- 入场前 N 根真实波幅
- 信号密度
- 距离上一次同方向交易的 bar 数
- 距离上一次止损的 bar 数

这些字段不进入第一版强依赖，避免一次性扩大实现范围。

## 6. 标签体系

每笔交易至少打以下标签：

- `winner`：`net_pnl > 0`
- `loser`：`net_pnl < 0`
- `big_win`：该 run 内净利润前 20%
- `big_loss`：该 run 内净利润后 20%
- `drawdown_entry`：开仓发生在最大回撤区间内
- `drawdown_exit`：平仓发生在最大回撤区间内
- `oos_trade`：交易属于 OOS 分段
- `stop_loss_trade`：`exit_reason` 以 `stop_loss` 开头
- `take_profit_trade`：`exit_reason` 以 `take_profit` 开头

标签只用于分析，不应直接作为策略条件。

## 7. 分析口径

## 7.1 方向归因

按 `side` 分组：

- 交易数
- OOS 交易数
- 胜率
- PF
- 净利润贡献
- 平均收益
- 最大单笔亏损
- stop loss 占比
- 回撤交易占比

目的：

```text
判断 long / short 是否拥有不同 edge，是否需要方向单独过滤。
```

## 7.2 退出原因归因

按 `exit_reason` 分组：

- stop loss
- take profit
- signal close
- gap open stop loss
- gap open take profit
- other

目的：

```text
判断回撤是由正常止损、gap、还是持仓时间/退出逻辑造成。
```

## 7.3 特征分桶归因

第一版使用四分位分桶，不使用精确阈值：

- `atr_pct`
- `trend_gap_atr`
- `entry_distance_atr`
- `breakout_distance_atr`
- `stop_distance_pct`

每个分桶展示：

- 交易数
- OOS 交易数
- 胜率
- PF
- 净利润贡献
- 平均收益
- 最大单笔亏损
- stop loss 占比
- 回撤交易占比

使用四分位的原因：

- 减少精确调参
- 降低过拟合
- 更容易跨 run 比较

## 7.4 回撤段归因

最大回撤段需要单独展示：

- 回撤开始时间
- 回撤谷底时间
- 回撤恢复时间
- 回撤幅度
- 区间内交易数
- 区间内净利润
- 区间内 stop loss 数
- 区间内 long / short 分布
- 区间内特征分桶分布

目的：

```text
找到真正制造回撤的交易结构，而不是只看全样本平均表现。
```

## 8. 防过拟合约束

## 8.1 IS 归因，OOS 验证

归因规则必须先在 IS 交易上生成。

OOS 只能用于验证，不能参与：

- 选择特征
- 选择阈值
- 选择组合规则
- 选择最终推荐规则

如果当前数据只有一个固定 IS/OOS split，第一版可以按已有 validation split 执行。

后续需要支持 walk-forward 或多切分复核。

## 8.2 候选规则必须简单

第一版只允许以下规则形态：

```text
单特征 + 单阈值
单特征分桶排除
side + 单特征分桶排除
exit-risk-derived cooldown
```

不允许第一版自动生成多条件复杂组合，例如：

```text
side=short 且 atr_pct 在 Q4 且 trend_gap_atr 在 Q1 且 entry_distance_atr > 0.73
```

复杂组合只允许人工记录为观察，不允许自动进入过滤器实验。

## 8.3 阈值必须粗

阈值来源优先级：

1. 四分位边界
2. 三分位边界
3. 领域稳定整数阈值

禁止使用过精确阈值，例如：

```text
trend_gap_atr < 0.873
```

应改为：

```text
trend_gap_atr 位于最低四分位
```

## 8.4 样本数下限

一个分桶或候选规则必须满足：

- 总交易数 >= 30
- OOS 交易数 >= 10
- 至少覆盖 2 个 run，或 2 个候选参数组

若样本不足，只能标记为：

```text
insufficient_sample
```

不能生成过滤建议。

## 8.5 交易保留下限

过滤实验必须保留足够交易数。

第一版建议：

- 总交易保留率 >= 60%
- OOS 交易保留率 >= 50%

低于阈值时，即使回撤下降，也应标记为：

```text
over_filtered
```

## 8.6 跨候选一致性

候选规则至少需要在多个对象上方向一致。

检查维度：

- BTC / ETH
- long / short
- 多个稳定池候选
- 多个 trend fast / slow 参数组

如果规则只对单个 run 有效，应标记为：

```text
single_run_pattern
```

不能进入稳定池配置建议。

## 8.7 只接受风险质量改善

过滤后至少需要满足以下之一：

- 最大回撤下降，且 OOS 不显著下降
- OOS/DD 提升，且交易数保留达标
- PF 提升，且最大回撤不变坏

如果只是收益变高但回撤不降，不能视为风险过滤成功。

## 9. 候选规则生成

交易级归因可以生成候选规则，但必须附带证据。

候选规则字段：

- `rule_id`
- `source_candidate_ids`
- `feature_name`
- `bucket_or_threshold`
- `side_scope`
- `sample_count`
- `oos_sample_count`
- `is_effect`
- `expected_risk_effect`
- `overfit_risk`
- `evidence_summary`
- `status`

状态：

- `hypothesis`
- `insufficient_sample`
- `ready_for_filter_experiment`
- `rejected_overfit_risk`
- `validated`
- `rejected_oos`

第一版只需要生成 `hypothesis` 和 `ready_for_filter_experiment`。

## 10. API 与 readmodel 边界

## 10.1 新增 readmodel

建议新增：

- `TradeAttributionView`
- `TradeAttributionRow`
- `TradeAttributionBucket`
- `DrawdownWindowAttribution`
- `AttributionHypothesis`

## 10.2 API 草案

查看某个研究候选或稳定候选的交易归因：

```text
GET /api/research-candidates/{candidate_id}/trade-attribution
```

稳定池可以复用同一接口，因为 `stable_candidate_id` 当前等于参数组 key。

查看多个稳定候选的聚合归因：

```text
GET /api/stable-pool/trade-attribution
```

将某个归因假设提交为过滤器实验：

```text
POST /api/attribution-hypotheses/{hypothesis_id}/filter-experiments
```

第一版可以先不实现第三个接口，只支持人工查看和记录。

## 11. 前端设计

## 11.1 稳定池入口

稳定池行操作新增：

```text
交易归因
```

点击后打开弹窗或详情抽屉。

## 11.2 归因页面结构

第一版页面包括：

- 基准 run 摘要
- 方向归因表
- 退出原因归因表
- 特征分桶表
- 最大回撤段交易表
- 候选假设列表

## 11.3 候选假设展示

候选假设必须显示：

- 规则描述
- 样本数
- OOS 样本数
- 交易保留率预估
- 过拟合风险标签
- 是否满足进入过滤实验条件

如果不满足防过拟合约束，按钮必须禁用。

## 12. 实施阶段

## 12.1 Phase 1：归因数据补齐

- 将 open signal `meta_json.feature_values` 关联到 trade row
- 派生 `trend_gap_atr`、`entry_distance_atr`、`breakout_distance_atr`、`atr_pct`
- 标记 `big_win`、`big_loss`、`stop_loss_trade`、`take_profit_trade`
- 标记最大回撤区间交易

## 12.2 Phase 2：稳定池交易归因视图

- 稳定池新增 `交易归因` 按钮
- 展示方向归因
- 展示退出原因归因
- 展示特征分桶
- 展示最大回撤段交易

## 12.3 Phase 3：候选假设生成

- 根据分桶差异生成简单假设
- 标记样本不足和过拟合风险
- 只允许简单规则进入下一步

## 12.4 Phase 4：归因过滤实验

- 将候选假设转为过滤器实验配置
- 固定规则，不在 OOS 上调阈值
- 展示 IS / OOS 分层结果
- 展示跨候选一致性

## 13. 验收标准

第一版完成后应能回答：

- 稳定池某个候选的亏损主要来自 long 还是 short
- 最大回撤段由哪些交易组成
- stop loss 交易集中在哪些入场前特征分桶
- big win 和 big loss 在 `atr_pct`、`trend_gap_atr`、`entry_distance_atr` 上是否有明显差异
- 是否存在样本足够、规则简单、过拟合风险可控的候选假设

第一版不要求：

- 自动生成最优过滤器
- 自动改策略代码
- 自动推荐稳定池上线配置
- 搜索复杂多条件规则

## 14. 结论

交易级归因层的核心价值是把研究问题从：

```text
试哪个外部过滤指标能降低回撤
```

转为：

```text
哪些真实亏损交易结构导致回撤，是否能用简单、可验证、不过拟合的规则排除
```

该层必须坚持：

- IS 归因
- OOS 验证
- 简单规则
- 粗阈值
- 样本数下限
- 交易保留下限
- 跨候选一致性

只有满足这些约束的规则，才允许进入过滤器实验层继续验证。
