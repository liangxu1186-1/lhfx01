# EMA Pullback ATR v2 账户风险缺口分析

## 1. 背景

在 EMA Pullback ATR v2 的参数实验中，部分 run 出现了非常高的最大回撤，个别样本的 `max_drawdown` 接近 `100%`。

目前这个现象在 1H 样本上最明显，因此最先被观察到；但问题本质并不局限于 1H，而是当前执行与仓位模型中的全局账户风险缺口。

这引出了一个需要先澄清的问题：

- 是执行层的止损没有生效？
- 还是止损生效了，但账户级风险仍然失控？

本文件的目标是把现象、原因和后续可选方案讲清楚，供后续评审与决策使用。

## 2. 结论摘要

结论先说：

1. 当前 v2 的 SL/TP 执行逻辑是生效的。
2. 高回撤的根因不是“单笔止损失效”，而是“价格级止损 + 资金百分比分配 + 高杠杆 + 高频交易”组合下，账户级风险没有被限制。
3. 当前系统实现的是“单笔价格风控”，不是“账户风险风控”。
4. 更进一步说，当前 `ATR stop` 与 `percent_of_cash` 仓位语义并不一致：ATR 决定了价格退出距离，但没有决定账户愿意为这笔交易承担多少风险。
5. 1H 只是最先放大问题的观测样本；同类风险在 4H、1D 或其他策略/周期中同样成立。
6. 如果要解决这个问题，重点不在修补现有 SL/TP，而在新增账户级风险控制和实验层筛选约束。

## 3. 已确认事实

### 3.1 执行层止损逻辑

当前 v2 开仓后，执行层会在真实 fill 价基础上计算计划止损和止盈：

```text
stop_distance = max(atr_value * atr_stop_mult, entry_price * min_stop_pct)
```

多头：

```text
planned_stop_loss_price = entry_price - stop_distance
planned_take_profit_price = entry_price + stop_distance * rr
```

空头：

```text
planned_stop_loss_price = entry_price + stop_distance
planned_take_profit_price = entry_price - stop_distance * rr
```

对应代码：

- [simulator.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/execution/simulator.py:467)

### 3.2 止损触发与成交一致性

对本地运行结果做了两层核对：

1. 高回撤样本 run 的 `trades.csv` 中，`planned_stop_loss_price` / `planned_take_profit_price` 都存在，没有缺失。
2. 对全部 intrabar 止损/止盈出场做校验后，`exit_price` 与计划 SL/TP 价格一致，没有发现绕过计划价的情况。

核对结果：

```text
checked_intrabar_exits = 340,414
gap_exits = 16,035
violations = 0
```

这说明：

- `stop_loss_intrabar` / `take_profit_intrabar` 按计划价成交。
- `stop_loss_gap_open` / `take_profit_gap_open` 属于 gap 语义，按 open 成交，不是止损失效。

### 3.3 高回撤 run 的典型特征

本地样本扫描后，高回撤 run 普遍具备这些特征：

1. 杠杆较高，尤其是 `l5`
2. 交易数很多，常见 `400-800+`
3. 止损出场次数非常高
4. 中途权益曾显著放大，后续从峰值大幅回吐

其中，1H 样本最容易把这个问题放大，因为它通常：

1. 信号更密
2. 交易更多
3. 连续止损序列更常见
4. 高频下更容易叠加高杠杆风险

典型例子：

```text
run_id: batch-20260501123858071-exp-03-db323903-run-051-tf5-ts13-tol0p5-sl2-rr1p5-l5
timeframe: 1h
leverage: 5
max_drawdown: 99.98%
total_return: -93.76%
trade_count: 614
exit_counts:
  take_profit_intrabar: 253
  stop_loss_intrabar: 338
  stop_loss_gap_open: 11
  take_profit_gap_open: 12
missing planned SL/TP: 0
```

该 run 的权益曾从 `10,000` 增长到约 `2,312,794`，随后回撤到几百，因而最大回撤接近 `100%`。

## 4. 为什么“止损生效了”，回撤仍然会极大

这是本问题最容易误解的地方。

### 4.1 当前止损是“价格级止损”，不是“账户级止损”

当前止损只约束一笔仓位在价格上的最大允许反向波动距离：

- 基于 ATR
- 基于入场价
- 在开仓时确定一次

它并不会直接回答下面这些账户层问题：

- 这一笔最多亏总权益的多少？
- 连续 10 笔止损后要不要停？
- 权益从高点回撤 20% 后要不要熔断？
- 账户已经翻很多倍后，下一笔是否应该自动降风险？

所以，当前系统有：

- 单笔价格风控

但没有：

- 单笔账户风险上限
- 组合级回撤熔断
- 浮盈保护
- 权益高位降杠杆

### 4.2 仓位会随可用现金扩大

v2 当前默认 `qty_policy_ref = percent_of_cash`。

下单数量来自：

```text
allocated_cash = available_cash * cash_allocation_pct
notional = allocated_cash / ((1 / leverage) + fee_rate)
qty = notional / price
```

对应代码：

- [_resolve_order_qty](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/execution/simulator.py:513)
- [_qty_from_cash_allocation](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/execution/simulator.py:530)

这意味着：

1. 权益变大
2. 可用现金变大
3. 下一笔仓位也会变大
4. 即使止损距离相对价格不变，单笔亏损的绝对金额也会放大

也就是说：

```text
止损规则没变
仓位规模变大了
绝对亏损金额也变大了
```

### 4.2.1 更核心的矛盾：ATR Stop 与 Percent-of-Cash Sizing 语义不匹配

当前组合是：

```text
ATR 决定 stop distance
Percent of Cash 决定仓位
```

这会导致一个更本质的问题：

```text
ATR 影响出场距离
但不直接影响账户实际承担的风险预算
```

举例：

场景 A：

```text
stop distance = 1%
notional = 100,000
实际风险 ≈ 1,000
```

场景 B：

```text
stop distance = 5%
notional = 100,000
实际风险 ≈ 5,000
```

两笔交易都使用 ATR 止损，但账户实际承担的风险并不一致。

因此更准确的表述不是：

```text
当前只是“账户级风控缺失”
```

而是：

```text
ATR Stop + Percent-of-Cash Sizing 在风险语义上天然不闭环
```

这也是为什么本问题不能只通过优化筛选层解决，最终仍需要引入风险预算驱动的仓位模型。

### 4.3 止损价格不会随权益上涨自动收紧

当前 v2 的计划止损是在开仓后一次性设定的，后续不会自动更新。

因此它不是：

- trailing stop
- break-even stop
- 浮盈锁定 stop

所以即使账户从 `10,000` 增长到 `100,000` 或更高，后续新开仓的风险绝对金额仍会继续放大，只要仓位按现金百分比继续扩张。

### 4.4 高频 + 杠杆 + 连续止损，会形成账户级回撤

当某个周期或策略组合具备更高交易频率时：

1. 信号频次更高
2. 交易次数更多
3. 连续止损序列更容易出现
4. 高杠杆会放大每笔损失
5. gap open 还会产生比 planned stop 更差的实际退出价

因此，即使每一笔都遵守 SL/TP，账户曲线仍可能出现深度回撤。

1H 只是最容易观察到这一现象的周期，不是该问题成立的前提。

## 5. 问题本质

本问题不是执行 bug，而是风险设计边界问题。

更精确地说：

```text
当前 v2 的风控层只覆盖了“单笔价格退出”
没有覆盖“账户级风险预算”和“权益曲线回撤控制”
```

这也是为什么会出现下面这种表面矛盾：

```text
每一笔都有止损
但整个 run 仍然可能接近归零
```

这个现象在“百分比资金仓位 + 高杠杆 + 高频交易”体系里是完全可能的。

同样重要的是，这不是 1H 特有问题，而是当前执行模型在所有周期上的共同结构性风险，只是不同周期暴露速度不同。

如果继续维持：

```text
ATR stop 用来定退出
Percent of Cash 用来定仓位
```

那么 v2 的风险语义将始终是不完整的。它只能被描述为：

```text
有 ATR 止损的 percent-of-cash 策略
```

而不是：

```text
风险预算闭环的 ATR 风险模型策略
```

## 6. 解决方案选项

下面按优先级分层列出，不建议只做其中最表面的那一层。

### 方案 A：实验与推荐层先加硬约束

目标：先减少明显不可用的结果进入候选集。

建议：

1. 默认将 `max_drawdown > 35%` 或 `> 40%` 的 run 标红或降权
2. 对高频周期优先限制高杠杆；若保守起步，可先从 1H 默认不推荐 `leverage > 2` 开始
3. 对交易数过高且 PF 不高的 run 增加惩罚
4. 邻域稳定性结论中显式纳入：
   - 最差回撤
   - OOS 正比例
   - 最少交易数

优点：

- 开发成本低
- 不改变执行语义
- 立刻改善实验筛选体验

缺点：

- 只能过滤坏结果，不能从根源控制 run 内部风险

### 方案 B：新增账户级风险仓位模式

目标：把单笔亏损和账户权益挂钩。

思路：

```text
risk_per_trade_cash = equity * risk_pct
qty = risk_per_trade_cash / stop_distance
```

如有杠杆与最小名义价值约束，再叠加裁剪。

核心含义：

- 每笔仓位不再由“可用现金百分比”决定
- 而由“账户允许承担的止损金额”决定

优点：

- 直接解决“权益越大，绝对亏损越夸张”的问题
- 直接解决 “ATR stop 与仓位大小风险语义脱节” 的问题
- 与 ATR 止损天然匹配
- 更符合系统化交易里的标准风险预算模型

缺点：

- 这是执行层语义变更
- 需要新增参数、readmodel、实验入口与测试

### 方案 C：新增浮盈保护机制

目标：减少从权益高点大幅回吐。

可选实现：

1. break-even stop
   - 当浮盈达到 `1R` 后，把 stop 提到 entry
2. trailing stop
   - 按 ATR 或 swing high/low 动态抬升止损
3. 分段锁盈
   - 到 `1R` 锁部分收益，到 `2R` 再抬 stop

优点：

- 能显著减少“权益冲高后回吐很深”
- 更贴近“让盈利 run 留住收益”的需求

缺点：

- 会改变 v2 的收益分布
- 策略逻辑与执行逻辑复杂度都上升

### 方案 D：新增 run 级回撤熔断

目标：限制单个回测 run 的最坏结果。

示例规则：

```text
如果 equity 从峰值回撤超过 25% / 30%
则停止后续开仓，或直接结束本 run
```

优点：

- 非常直接
- 对防止接近归零有效

缺点：

- 这更像组合管理规则，不完全是策略原生逻辑
- 需要明确是否允许“停交易后继续观察”或“直接终止 run”

### 方案 E：对 1H 与高杠杆做策略级约束

目标：避免明显危险的参数域。

建议：

1. 高频周期限制最大杠杆
2. 高频周期提高 `atr_entry_tolerance` 或收窄快慢周期空间
3. 加入最小预期交易间隔或信号冷却

优点：

- 对用户体验简单直接

缺点：

- 更偏经验裁剪
- 没有解决通用账户风险建模问题

## 7. 推荐处理顺序

建议不要一步到位做所有改动，而是分层推进。

### 第一优先级

先做：

1. 实验/推荐层风险约束
2. 邻域稳定性里增加回撤与交易密度惩罚
3. 高频周期默认抑制高杠杆候选

原因：

- 不改执行语义
- 风险最小
- 能立刻改善实验使用体验

### 第二优先级

再做：

1. 账户风险仓位模式（高优先）

这不是普通增强项，而是 v2 风险闭环的必要组成。因为它真正把：

```text
单笔风险 -> 和账户权益绑定
```

而不是和“可用现金放大后的仓位”被动绑定。

如果目标是让 `ema_pullback_atr_v2` 被定义为一个有完整风险语义的 ATR 策略，那么这一步应被视为高优先，而不是长期增强。

### 第三优先级

最后视需要做：

1. break-even / trailing stop
2. run 级回撤熔断

这些更像收益曲线管理增强，不建议在问题尚未拆清前直接叠加。

## 8. 推荐决策

如果目标是尽快把 v2 从“能跑”推进到“能研究、能筛选、能避免明显误导”，推荐决策如下：

### 建议立即做

1. 在实验 UI 和推荐评分里强化回撤约束
2. 默认抑制高频周期的高杠杆候选；第一步可先从 1H 开始
3. 在 run/邻域结论里明确区分：
   - 价格级止损已生效
   - 账户级风险未受控

### 建议下一阶段做

4. 新增账户风险仓位模式（高优先，推荐作为 v2.x 能力）

建议形式：

```text
qty_policy_ref = risk_pct_of_equity
```

配套参数示例：

```text
risk_pct_per_trade = 0.5% / 1.0%
```

再结合当前 ATR stop 计算 stop distance，由执行层反推 qty。

这一步完成后，ATR 止损才会从：

```text
价格保护工具
```

变成：

```text
风险预算工具
```

### 建议暂缓

5. trailing stop / break-even stop
6. run 级回撤熔断

这些可以在账户风险仓位模式落地后再评估，否则容易把多个变化混在一起，难以判断真实效果。

## 8.1 建议补充的 Risk Diagnostics

如果后续引入 `risk_pct_of_equity`，建议同步补充风险诊断字段，否则难以确认风险模型是否按预期工作。

建议新增的 Run / 参数组级指标：

```text
avg_r_multiple
median_r_multiple
max_consecutive_losses
avg_loss_pct_of_equity
worst_loss_pct_of_equity
risk_utilization_ratio
```

这些指标的价值在于：

1. 验证 risk sizing 后的单笔风险是否真的被稳定约束
2. 识别高频条件下连续亏损序列是否仍然过强
3. 区分“策略 edge 不足”和“风险模型不合理”

## 9. 一句话总结

一句话总结这个问题：

```text
当前 v2 的止损是生效的，但它只控制“价格怎么出场”，不控制“账户一次愿意亏多少钱”。
在资金百分比扩仓与高杠杆条件下，账户级回撤仍然可能非常大；而 ATR stop 与 percent_of_cash sizing 的语义不匹配，是这个全局问题的核心。
```
