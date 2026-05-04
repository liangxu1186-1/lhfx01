# EMA Pullback ATR v2 策略设计

## 1. 文档状态

本文档是评审后实施规格，不代表已经实现。

目标是定义一个独立于现有 `ema_crossover` 的 v2 策略方向，并明确执行层 SL/TP 语义、参数实验边界、实施阶段和验收标准。

本文档只描述策略与执行语义，不修改当前已落地的 v1 回测结果口径。

## 2. 背景

当前系统已经具备：

- 单次 EMA 回测
- 参数实验批次
- 杠杆维度
- IS/OOS 评分硬约束
- 最大回撤评分与筛选
- Research Note 决策状态机
- 参数实验页性能优化

当前主要短板不再是实验系统能力，而是策略结构本身仍然偏简单：

```text
EMA crossover -> signal -> next bar open fill
```

这类策略容易在震荡区间频繁反转，并且缺少明确的单笔风险结构。

v2 的研究目标是验证：

```text
趋势过滤 + 回踩确认 + ATR 风控 + RR 止盈
```

是否优于现有 EMA crossover baseline。

## 3. 非目标

第一版 v2 不做以下事项：

- 不覆盖或替换 `ema_crossover v1`
- 不引入 1H / 15m 多周期对齐
- 不做 ATR trailing stop
- 不做 limit order
- 不做实盘交易语义
- 不把所有参数一次性放入实验空间
- 不修改现有 batch scoring 公式

## 4. 核心原则

1. v1 保留作为 baseline。
2. v2 使用独立策略名和版本。
3. 策略层只负责生成信号和 risk spec。
4. 执行层负责真实成交、SL/TP 计算和 bar 内触发语义。
5. ATR 由 feature pipeline 预计算，策略不在内部临时计算指标。
6. 参数实验先收窄搜索空间，优先验证结构有效性。
7. 所有会改变交易输出的语义必须有测试覆盖。

## 5. 策略命名

新增策略使用独立策略名：

```text
strategy_name = ema_pullback_atr_v2
strategy_version = v2
```

代码类名：

```python
EMAPullbackATRStrategy
```

采用 `ema_pullback_atr_v2` 作为 `strategy_name` 的原因：

- 避免 v2.1 / v2.2 演进时在筛选、聚合和 UI 展示上混淆。
- 让参数实验、readmodel 和推荐过滤可以直接按策略名隔离。
- 保持 v1 / v2 横向比较简单。

历史 v1 保持：

```text
strategy_name = ema_crossover
strategy_version = v1
```

## 6. v2.0 范围

v2.0 只做单周期策略。

输入仍然是一个 dataset snapshot 和一个 timeframe。

多周期趋势过滤留到 v2.1：

```text
v2.0: 单周期 EMA pullback + ATR risk
v2.1: 多周期 trend filter
v2.2: regime filter 或更复杂确认条件
```

这样可以避免第一版同时处理：

- resample
- bar alignment
- lookahead bias
- partial higher-timeframe bar
- 多周期执行时序

## 7. 参数设计

### 7.1 第一版可实验参数

```python
trend_fast_period: int
trend_slow_period: int
atr_entry_tolerance: float
atr_stop_mult: float
risk_reward_ratio: float
leverage: float
```

约束：

```text
trend_fast_period > 0
trend_slow_period > 0
trend_fast_period < trend_slow_period
atr_entry_tolerance >= 0
atr_stop_mult > 0
risk_reward_ratio > 0
leverage > 0
```

### 7.2 第一版固定参数

```python
entry_ema_period = 21
atr_period = 14
min_atr_pct_of_price = 0.002
min_stop_pct = 0.003
qty_policy_ref = "percent_of_cash"
```

这些参数暂不进入 v2.0 参数实验空间。

但这些参数必须进入 `strategy_params` 和 `resolved_config_json`，不能隐藏为不可见硬编码。

原因：

- `entry_ema_period` 和 `atr_period` 会显著扩大组合数。
- 第一阶段目标是验证结构，不是寻找所有可能的局部最优。
- 固定 ATR 与 entry EMA 后，实验结果更容易解释。

### 7.3 后续可扩展参数

后续版本再考虑：

```python
entry_ema_periods
atr_periods
min_atr_pct_of_price_candidates
min_stop_pct_candidates
entry_confirmation_mode
```

## 8. Feature Pipeline

### 8.1 新增 ATR 指标

新增 indicator：

```python
compute_atr(candles, window)
```

True Range：

```text
TR = max(
  high - low,
  abs(high - previous_close),
  abs(low - previous_close)
)
```

ATR 建议使用：

```text
SMA seed + Wilder smoothing
```

### 8.2 v2 需要的 feature 列

```text
ema_close_{trend_fast_period}
ema_close_{trend_slow_period}
ema_close_{entry_ema_period}
atr_{atr_period}
```

例如默认固定参数下：

```text
ema_close_21
atr_14
```

### 8.3 Warmup 要求

v2 的 warmup 至少为：

```text
max(trend_slow_period, entry_ema_period, atr_period) + 20
```

其中 `+ 20` 是为了降低 EMA / ATR 初始平滑阶段不稳定带来的影响。

`feature_specs()` 应显式声明该 warmup，以避免策略在指标刚刚可用但仍不稳定的区间生成信号。

## 9. 入场逻辑

策略只在 bar close 后生成信号，成交仍由执行层在 next bar open 完成。

### 9.1 多头趋势

```text
trend_fast_ema > trend_slow_ema
```

### 9.2 空头趋势

```text
trend_fast_ema < trend_slow_ema
```

### 9.3 多头回踩确认

```text
trend_fast_ema > trend_slow_ema
abs(low - entry_ema) <= atr * atr_entry_tolerance
close > previous_high
atr / close >= min_atr_pct_of_price
```

含义：

- 趋势向上
- 当前 K 线盘中触碰 entry EMA 附近区域
- 收盘突破上一根高点，确认回踩后重新启动
- ATR 不得过小，避免止损距离过近

### 9.4 空头回踩确认

```text
trend_fast_ema < trend_slow_ema
abs(high - entry_ema) <= atr * atr_entry_tolerance
close < previous_low
atr / close >= min_atr_pct_of_price
```

含义：

- 趋势向下
- 当前 K 线盘中触碰 entry EMA 附近区域
- 收盘跌破上一根低点，确认回踩后重新启动
- ATR 不得过小

### 9.5 持仓约束

执行层仍保持单持仓。

策略层可以避免连续发同方向 OPEN；执行层仍以最终约束为准：

```text
OPEN while position exists -> warning
CLOSE while no position -> warning
REVERSE -> close then open
```

第一版 v2 只生成 `OPEN` 信号。

v2.0 不生成 `REVERSE`，也不生成趋势反向 `CLOSE`。

退出只来自执行层 SL/TP。

原因：

- v2.0 的研究目标是验证 pullback entry + ATR risk 结构。
- 如果同时引入 opposite signal exit，会混入第二套退出语义。
- OPEN-only 更容易解释每笔交易的风险收益结构。

后续 v2.1 可单独评审：

```text
trend invalidation exit
```

## 10. Risk Spec

### 10.1 为什么不直接传 SL/TP 价格

当前执行语义是：

```text
signal at bar close -> next bar open fill
```

如果策略在 close 上直接计算：

```python
stop_loss_price
take_profit_price
```

但真实入场价是下一根 open，则跳空时会导致：

- 实际风险距离偏离预期
- RR 结构偏离预期
- 不同市场缺口下比较不稳定

因此 v2 第一版直接使用 `risk_spec`，由执行层基于真实 fill price 计算 SL/TP。

### 10.2 SignalIntent meta_json

开仓信号在 `meta_json` 中携带：

```python
{
  "risk_spec": {
    "stop_loss_mode": "atr_multiple",
    "stop_loss_value": atr_stop_mult,
    "take_profit_mode": "rr",
    "take_profit_value": risk_reward_ratio,
    "atr_value": atr,
    "min_stop_pct": min_stop_pct
  },
  "strategy_params": {
    "trend_fast_period": trend_fast_period,
    "trend_slow_period": trend_slow_period,
    "entry_ema_period": entry_ema_period,
    "atr_period": atr_period,
    "atr_entry_tolerance": atr_entry_tolerance,
    "atr_stop_mult": atr_stop_mult,
    "risk_reward_ratio": risk_reward_ratio,
    "min_atr_pct_of_price": min_atr_pct_of_price,
    "min_stop_pct": min_stop_pct
  },
  "feature_values": {
    "trend_fast_ema": trend_fast_ema,
    "trend_slow_ema": trend_slow_ema,
    "entry_ema": entry_ema,
    "atr": atr
  }
}
```

### 10.3 执行层最终 SL/TP 计算

开仓 fill 后：

```text
stop_distance = max(
  atr_value * atr_stop_mult,
  entry_price * min_stop_pct
)
```

多头：

```text
stop_loss_price = entry_price - stop_distance
take_profit_price = entry_price + stop_distance * risk_reward_ratio
```

空头：

```text
stop_loss_price = entry_price + stop_distance
take_profit_price = entry_price - stop_distance * risk_reward_ratio
```

## 11. 执行层 SL/TP 语义

### 11.1 OpenPosition 扩展

执行层内部持仓对象保存：

```python
stop_loss_price: float | None
take_profit_price: float | None
```

开仓后计算出的计划风控价还需要写入 `TradeRecord.planned_stop_loss_price` 与 `TradeRecord.planned_take_profit_price`，用于后续研究复盘。

### 11.2 每根 K 线处理顺序

建议顺序：

```text
1. 如果已有持仓，先检查当前 bar 是否触发 SL/TP
2. 如触发，生成 close order/fill/trade
3. 再处理当前 bar 被调度执行的策略信号
4. 最后记录 equity point
```

这种顺序含义是：

- 风控优先于策略反向信号
- 同一 bar 如果止损先发生，则策略信号会在无持仓状态下按现有规则处理

### 11.3 SL/TP 触发规则

多头：

```text
stop_loss hit: candle.low <= stop_loss_price
take_profit hit: candle.high >= take_profit_price
```

空头：

```text
stop_loss hit: candle.high >= stop_loss_price
take_profit hit: candle.low <= take_profit_price
```

### 11.4 同 bar 同时触发

保守处理：

```text
如果同一根 bar 同时触发 stop loss 和 take profit，按 stop loss 先触发。
```

此规则固定，不建议做成参数。

### 11.5 跳空处理

多头：

```text
如果 open <= stop_loss_price:
  按 open 止损成交
elif open >= take_profit_price:
  按 open 止盈成交
elif low <= stop_loss_price:
  按 stop_loss_price 止损成交
elif high >= take_profit_price:
  按 take_profit_price 止盈成交
```

空头：

```text
如果 open >= stop_loss_price:
  按 open 止损成交
elif open <= take_profit_price:
  按 open 止盈成交
elif high >= stop_loss_price:
  按 stop_loss_price 止损成交
elif low <= take_profit_price:
  按 take_profit_price 止盈成交
```

成交价继续套用现有 slippage 规则。

### 11.6 Exit Reason

建议 `TradeRecord.exit_reason` 细分：

```text
stop_loss_intrabar
stop_loss_gap_open
take_profit_intrabar
take_profit_gap_open
```

用途：

- 后续可统计跳空止损占比
- 区分正常触发与 gap 穿越
- 支持研究者判断策略是否暴露在不适合的市场 regime 中

## 12. 数据模型变更

### 12.1 第一版持久化字段

第一版新增并持久化计划风控价：

```python
TradeRecord.planned_stop_loss_price: float | None = None
TradeRecord.planned_take_profit_price: float | None = None
```

原因：

- 研究者需要直接看到每笔交易原计划风险边界。
- 可以验证实际 exit 是否符合预期 RR。
- 不必从 `SignalIntent.meta_json` 和成交价事后反推。

Repository 需要兼容旧 CSV：

```text
旧 trades.csv 无该列时，读取为 None。
新 trades.csv 写出该列。
```

### 12.2 仍复用的字段

继续复用：

```python
SignalIntent.meta_json
TradeRecord.exit_reason
TradeRecord.exit_price
TradeRecord.gross_pnl
TradeRecord.net_pnl
TradeRecord.return_pct
```

## 13. 参数实验设计

### 13.1 策略选择

参数实验支持：

```text
strategy_name:
- ema_crossover
- ema_pullback_atr_v2
```

v1 参数空间保持：

```text
fast_periods
slow_periods
leverage_candidates
```

v2.0 参数空间：

```text
trend_fast_periods
trend_slow_periods
atr_entry_tolerances
atr_stop_mults
risk_reward_ratios
leverage_candidates
```

固定参数写入 resolved config：

```text
entry_ema_period = 21
atr_period = 14
min_atr_pct_of_price = 0.002
min_stop_pct = 0.003
```

### 13.2 组合主键

v1 聚合主键：

```text
strategy_name
fast_period
slow_period
leverage
```

v2 聚合主键：

```text
strategy_name
trend_fast_period
trend_slow_period
entry_ema_period
atr_period
atr_entry_tolerance
atr_stop_mult
risk_reward_ratio
leverage
```

### 13.3 第一版搜索空间建议

示例：

```text
trend_fast_periods = 2, 3, 5, 8
trend_slow_periods = 13, 21, 34
atr_entry_tolerances = 0.5, 1.0
atr_stop_mults = 1.5, 2.0
risk_reward_ratios = 1.5, 2.0
leverage_candidates = 1, 2, 3
```

单快照组合数：

```text
4 * 3 * 2 * 2 * 2 * 3 = 576
```

多快照批次应优先从更小组合开始，避免一次提交过大。

## 14. Readmodel 与展示

### 14.1 Run Summary

`RunSummaryView` 需要能暴露：

```text
strategy_name
strategy_version
v2 strategy params
exit_reason distribution
planned_stop_loss_price / planned_take_profit_price in trade detail
```

第一版可以先只从 `resolved_config_json.strategy_params` 中读取参数摘要。

### 14.2 参数组展示

参数组表不应强制所有策略共享固定列。

第一版前端可以显示：

```text
策略
参数摘要
杠杆
平均收益
样本外收益
最大回撤
收益回撤比
总分
置信度
自动标签
人工状态
```

其中 `参数摘要` 对 v1 / v2 分别格式化：

v1：

```text
快 5 / 慢 21 / 杠杆 2
```

v2：

```text
趋势 8/34 / tol 0.5 / SL 1.5ATR / RR 2 / 杠杆 2
```

### 14.3 策略过滤

批次推荐和参数组筛选需要支持：

```text
strategy_name
```

避免 v1 与 v2 组合混在同一个推荐集合里。

## 15. Scoring

v2 第一版复用现有评分：

```text
avg_total_return
avg_oos_total_return
avg_max_drawdown
worst_max_drawdown
return_over_drawdown
is_oos_gap
coverage
stability
confidence
```

暂不新增评分公式。

原因：

- 第一阶段要比较策略结构，不要同时改变评分标准。
- 现有评分已经包含收益、OOS、回撤和稳定性。

需要注意：

```text
推荐候选必须按 strategy_name 分组或过滤后比较。
```

## 16. API 与前端

### 16.1 单次回测

当前 `POST /api/run-ema` 是 EMA 专用入口。

v2 接入前建议先引入通用入口：

```text
POST /api/runs
```

请求结构：

```json
{
  "run_id": "run-...",
  "dataset_snapshot_id": "snapshot-...",
  "strategy_name": "ema_pullback_atr_v2",
  "strategy_version": "v2",
  "strategy_params": {},
  "execution_constraints": {}
}
```

`POST /api/run-ema` 可以保留兼容，内部映射到通用 workflow。

### 16.2 参数实验

参数实验请求增加：

```text
strategy_name
strategy_version
```

并根据策略选择不同参数空间。

### 16.3 前端表单

第一版前端建议：

- 策略选择放在发起实验表单顶部
- v1 参数区保持现状
- v2 参数区折叠展示
- 固定参数显示为只读说明
- 参数组表先使用参数摘要，不急于做复杂动态列

## 17. 测试计划

### 17.1 指标测试

- `compute_atr` 正确计算 TR
- ATR 使用 SMA seed + Wilder smoothing
- ATR leading `None` 或 warmup 行为符合 feature pipeline 约定

### 17.2 策略测试

- v2 声明所需 feature specs
- v2 warmup 为 `max(trend_slow_period, entry_ema_period, atr_period) + 20`
- 多头趋势 + 回踩 + 突破前高生成 OPEN
- 空头趋势 + 回踩 + 跌破前低生成 OPEN
- ATR 过小时不生成信号
- v2 不生成 REVERSE
- 缺少 feature 列时报错
- v1 EMA crossover 行为不变

### 17.3 执行测试

- 无 risk spec 的 v1 行为不变
- 开仓后基于真实 fill price 计算 SL/TP
- 持久化 `planned_stop_loss_price` / `planned_take_profit_price`
- 多头 stop loss intrabar
- 空头 stop loss intrabar
- 多头 take profit intrabar
- 空头 take profit intrabar
- 多头 stop loss gap open
- 空头 stop loss gap open
- 同 bar SL/TP 同时触发时按 stop loss
- 旧 trades.csv 缺少计划风控价字段时可兼容读取

### 17.4 参数实验测试

- v2 参数组合数量正确
- v1 / v2 聚合主键不混淆
- v2 run_id 可读且包含关键参数摘要
- 批次推荐按 strategy_name 分组或可过滤

### 17.5 API / 前端测试

- 单次 v2 run 可提交并持久化
- v2 参数实验可提交并查询状态
- 前端可切换 v1 / v2 参数表单
- 参数组表可展示 v2 参数摘要

## 18. 实施顺序

建议按以下阶段落地：

### Phase A：执行层 SL/TP 基础设施

1. 执行层支持 `risk_spec`。
2. 开仓 fill 后基于真实 entry price 计算 SL/TP。
3. `TradeRecord` 持久化计划风控价。
4. 完成 SL/TP edge case 单测。
5. 确认无 risk spec 的 v1 行为不变。

### Phase B：ATR Feature 与 v2 Strategy

1. 新增 ATR indicator 和 feature pipeline 支持。
2. 新增 `EMAPullbackATRStrategy`。
3. v2 只生成 OPEN 和 risk spec。
4. 完成 ATR、warmup、入场信号和 v1 不变测试。

### Phase C：通用 Run API 与单次 v2 回测

1. 新增 `POST /api/runs`。
2. `POST /api/run-ema` 保留兼容，内部映射到通用 workflow。
3. v2 可通过单次 run 提交、持久化和读取。

### Phase D：参数实验 v2

1. 参数实验支持 `strategy_name`。
2. v2 支持最小搜索空间。
3. 聚合主键包含 strategy-aware 参数摘要。
4. 推荐和筛选避免 v1 / v2 混合比较。

### Phase E：前端

1. 发起实验表单支持策略选择。
2. v2 参数区折叠展示。
3. 参数组表显示策略和参数摘要。
4. 交易明细展示计划风控价和 exit reason。
5. 全量测试和一次小批次 v1/v2 对比。

## 19. 已收敛决策

以下问题已按评审意见收敛：

1. v2.0 只做单周期。
2. v2.0 只生成 OPEN，不生成 REVERSE。
3. 回踩条件使用 `abs(low/high - entry_ema) <= atr * tolerance`。
4. 确认条件保留 `close > previous_high / close < previous_low`。
5. `min_atr_pct_of_price = 0.002` 与 `min_stop_pct = 0.003` 作为默认值，但必须进入 config。
6. SL/TP 由执行层基于真实 fill price 计算。
7. 同 bar SL/TP 固定按 stop loss 保守处理。
8. 第一版持久化 `planned_stop_loss_price` / `planned_take_profit_price` 到 `TradeRecord`。
9. 先做通用 `POST /api/runs`，再接 v2 单次和参数实验。
10. v2 参数空间维持 96 组合示例，不再进一步收窄。

## 20. 完成定义

v2.0 完成时应满足：

1. v1 行为和测试保持不变。
2. v2 可在单次回测中独立运行。
3. v2 交易能基于 ATR risk spec 生成 SL/TP。
4. SL/TP 触发语义有明确测试覆盖。
5. 参数实验可运行 v2 最小参数空间。
6. v1 / v2 的 readmodel 和参数组聚合不混淆。
7. 前端可以发起 v2 实验并查看结果。
8. 全量 `pytest` 与前端 build 通过。
