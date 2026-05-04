# EMA Pullback ATR v2 Risk-Based Position Sizing 设计

## 1. 文档目标

本文档定义 `ema_pullback_atr_v2` 的下一阶段风险模型扩展：

```text
qty_policy_ref = risk_pct_of_equity
```

目标不是替换现有 `percent_of_cash`，而是新增一个**风险预算驱动**的仓位模式，让 ATR 止损与仓位大小在风险语义上闭环。

本文档只定义工程规格，不代表已经实现。

## 2. 设计结论

新增 `risk_pct_of_equity` 的原因不是“功能增强”，而是修复当前 v2 的风险语义缺口：

- 当前：
  - `ATR` 决定 stop distance
  - `percent_of_cash` 决定仓位
- 结果：
  - ATR 只决定退出距离
  - 不决定账户实际承担的风险金额

新增 `risk_pct_of_equity` 后：

- `ATR stop` 负责给出价格风险距离
- `risk_pct_per_trade` 负责给出账户允许承担的风险预算
- 执行层根据两者反推 qty

这样才能把 v2 从：

```text
有 ATR 止损的 percent-of-cash 策略
```

推进到：

```text
风险预算闭环的 ATR 风险模型策略
```

## 3. 非目标

本轮不做：

- trailing stop
- break-even stop
- run 级回撤熔断
- 多仓同时持有
- 多层分批止盈
- 自动替换现有 `percent_of_cash`
- 修改 `ema_crossover v1` 行为

## 4. 兼容性原则

### 4.1 不破坏已有 v2 行为

第一版引入方式：

- 保留现有：
  - `qty_policy_ref = percent_of_cash`
- 新增：
  - `qty_policy_ref = risk_pct_of_equity`

这样可以：

1. 保持已有回测结果和实验结果可复现
2. 允许新旧仓位模型 A/B 对比
3. 避免一次性混入过多收益分布变化

### 4.2 不影响 v1

`ema_crossover` 相关逻辑保持不变。

所有新增字段、校验和 UI 行为都必须策略感知，不能污染 v1 默认路径。

## 5. 新增概念

### 5.1 qty_policy_ref

新增仓位策略标识：

```text
risk_pct_of_equity
```

### 5.2 risk_pct_per_trade

新增参数：

```text
risk_pct_per_trade: float
```

含义：

```text
每一笔交易允许亏损的账户权益比例
```

示例：

```text
0.005 = 0.5%
0.010 = 1.0%
```

### 5.3 风险预算定义

开仓时定义：

```text
risk_cash = equity_reference * risk_pct_per_trade
```

其中 `equity_reference` 第一版建议取：

```text
available_cash + used_margin + unrealized_pnl
```

也就是当前账户权益。

## 6. 执行层语义

### 6.1 输入要求

当：

```text
qty_policy_ref = risk_pct_of_equity
```

执行层需要：

1. `SignalIntent.meta_json.risk_spec` 提供可解析的 stop distance 输入
2. `ExecutionConstraints` 提供 `risk_pct_per_trade_by_policy`

其中 stop distance 仍由现有 v2 风险规格提供：

```text
atr_value
stop_loss_value
min_stop_pct
```

### 6.2 计算顺序

#### 6.2.1 开仓前先推导 stop distance

继续沿用现有规则：

```text
stop_distance = max(atr_value * atr_stop_mult, entry_price * min_stop_pct)
```

#### 6.2.2 再推导风险预算

```text
risk_cash = account_equity * risk_pct_per_trade
```

其中：

```text
account_equity = available_cash + used_margin + unrealized_pnl
```

#### 6.2.3 再反推 qty

基础公式：

```text
qty_from_risk = risk_cash / stop_distance
```

这是**价格风险角度**的 qty。

#### 6.2.4 再通过杠杆和现金约束裁剪

仍需满足：

- `min_notional`
- `required_margin <= available_cash`
- fee 可支付

所以最终：

```text
qty = min(qty_from_risk, qty_allowed_by_margin)
```

其中：

```text
qty_allowed_by_margin
= 现有保证金模型下允许开的最大数量
```

### 6.3 第一版保守语义

如果账户权益较小、stop distance 过大，导致：

```text
qty_from_risk <= 0
```

或裁剪后：

```text
notional < min_notional
```

则按现有拒单语义处理，不强行开仓。

建议新增或复用拒单原因：

- `MIN_NOTIONAL`
- `INSUFFICIENT_MARGIN`
- 可新增：
  - `RISK_BUDGET_TOO_SMALL`

第一版如果不想扩展拒单枚举，也可以先复用 `MIN_NOTIONAL` / `INSUFFICIENT_MARGIN`，但推荐增加单独原因，方便分析。

### 6.4 planned SL/TP 仍然基于真实 fill price

该原则保持不变：

- 策略层只传 `risk_spec`
- 执行层基于真实 fill price 计算 `planned_stop_loss_price` / `planned_take_profit_price`

这保证：

1. `risk_pct_of_equity` 通过 fill price 与 stop distance 一致计算 qty
2. SL/TP 仍与真实成交价一致

## 7. 数据结构改动

### 7.1 ExecutionConstraints

当前已有：

```python
qty_by_policy: dict[str, float]
cash_allocation_pct_by_policy: dict[str, float]
```

新增：

```python
risk_pct_per_trade_by_policy: dict[str, float] = field(default_factory=dict)
```

### 7.2 resolved_config_json.execution_constraints

新增字段：

```json
{
  "risk_pct_per_trade_by_policy": {
    "risk_pct_of_equity": 0.01
  }
}
```

### 7.3 resolved_config_json.strategy_params

v2 run 必须显式持久化：

```json
{
  "qty_policy_ref": "risk_pct_of_equity",
  "risk_pct_per_trade": 0.01
}
```

原因：

1. 参数实验聚合要区分仓位模型
2. UI 和 readmodel 要可解释
3. 不能把风险预算参数藏在不可见 execution 层

## 8. 策略层设计

### 8.1 v2 策略参数

`EMAPullbackATRStrategy` 新增支持：

```python
qty_policy_ref: str = "percent_of_cash"
risk_pct_per_trade: float | None = None
```

### 8.2 参数约束

当：

```text
qty_policy_ref = risk_pct_of_equity
```

要求：

```text
risk_pct_per_trade > 0
risk_pct_per_trade < 1
```

推荐 UI 和实验默认值范围：

```text
0.25%
0.5%
1.0%
```

如果第一版先只做单次 run，实验层也可以先固定默认 `1.0%`，后续再放入参数空间。

### 8.3 SignalIntent

`SignalIntent.qty_policy_ref` 继续由策略层携带。

`risk_pct_per_trade` 不需要写进 signal 本身，只需要：

1. 进入 `strategy_params`
2. 经 workflow 下沉到 `execution_constraints`

## 9. API 设计

### 9.1 单次 run API

通用 `POST /api/runs` 以及兼容入口都要支持：

```json
{
  "qty_policy_ref": "risk_pct_of_equity",
  "risk_pct_per_trade": 0.01
}
```

校验规则：

#### 当 `qty_policy_ref = percent_of_cash`

- 需要 `cash_allocation_pct`
- 不允许 `risk_pct_per_trade`

#### 当 `qty_policy_ref = risk_pct_of_equity`

- 需要 `risk_pct_per_trade`
- 不允许 `cash_allocation_pct`

### 9.2 参数实验 API

参数实验请求同样支持：

```json
{
  "qty_policy_ref": "risk_pct_of_equity",
  "risk_pct_per_trade_candidates": [0.005, 0.01]
}
```

如果第一版想控制复杂度，可以采用两阶段：

#### 第一阶段

- 单次 run 支持 `risk_pct_of_equity`
- 参数实验只支持固定一个 `risk_pct_per_trade`

#### 第二阶段

- 参数实验开放 `risk_pct_per_trade_candidates`

建议第一版就把 batch/task 数据结构设计成可容纳 candidates，即便 UI 先不开放。

## 10. 参数实验设计

### 10.1 搜索空间

对于 v2，新聚合主键必须纳入仓位模型维度。

建议参数组主键扩展为：

```text
strategy_name
trend_fast_period
trend_slow_period
entry_ema_period
atr_period
atr_entry_tolerance
atr_stop_mult
risk_reward_ratio
qty_policy_ref
cash_allocation_pct 或 risk_pct_per_trade
leverage
```

### 10.2 resolved_config_json

参数实验生成的每个 run 都必须把完整仓位参数落入：

- `strategy_params`
- `execution_constraints`

不能只在 batch `search_space_json` 保存。

### 10.3 比较原则

推荐和筛选时，不应把：

- `percent_of_cash`
- `risk_pct_of_equity`

混成同一种参数组结论。

至少需要：

1. 参数组聚合 key 区分
2. UI 参数摘要区分
3. 推荐逻辑保留 `qty_policy_ref`

## 11. ReadModel 设计

### 11.1 ParameterLabRow

新增：

```python
risk_pct_per_trade: float | None
```

### 11.2 Run Summary / Run Detail 参数摘要

v2 参数摘要建议升级为：

#### `percent_of_cash`

```text
tf5/ts21 ema21/atr14 tol0.5 sl2.0 rr2.0 cash95 l1
```

#### `risk_pct_of_equity`

```text
tf5/ts21 ema21/atr14 tol0.5 sl2.0 rr2.0 risk1.0% l1
```

### 11.3 风险诊断指标

为后续验证 risk sizing 是否按预期工作，建议预留新增指标：

```text
avg_r_multiple
median_r_multiple
max_consecutive_losses
avg_loss_pct_of_equity
worst_loss_pct_of_equity
risk_utilization_ratio
```

第一版可以先只做数据结构与 readmodel 预留，不一定要在同一轮全部实现。

## 12. 前端设计

### 12.1 单次 run 表单

v2 策略下新增仓位模式选择：

- `按可用资金比例` (`percent_of_cash`)
- `按账户风险比例` (`risk_pct_of_equity`)

交互规则：

#### 选 `percent_of_cash`

- 展示 `cash_allocation_pct`
- 隐藏 `risk_pct_per_trade`

#### 选 `risk_pct_of_equity`

- 展示 `risk_pct_per_trade`
- 隐藏 `cash_allocation_pct`

### 12.2 参数实验表单

第一版建议：

- 先允许选仓位模式
- 若为 `risk_pct_of_equity`，先只展示单值输入：
  - `risk_pct_per_trade`

第二版再开放 candidates。

### 12.3 Run / 参数组展示

所有与 v2 相关的参数摘要、推荐 Run、邻域分析、参数组表都要显式展示仓位模式。

至少做到：

- `qty_policy_ref`
- `cash_allocation_pct` 或 `risk_pct_per_trade`

不会被隐藏在“高级信息”之外。

## 13. 测试清单

### 13.1 执行层

必须新增：

1. `risk_pct_of_equity` 基于 stop distance 正确推导 qty
2. stop distance 变大时，qty 变小
3. equity 变大时，在相同 risk_pct 下 qty 按比例扩大
4. 杠杆 / fee / margin 限制仍生效
5. `planned_stop_loss_price` / `planned_take_profit_price` 仍按真实 fill price 计算
6. `risk_pct_of_equity` 与现有 `percent_of_cash` 路径互不影响

### 13.2 API / Workflow

1. 单次 run 支持 `qty_policy_ref = risk_pct_of_equity`
2. 缺少 `risk_pct_per_trade` 时拒绝
3. 同时提交 `cash_allocation_pct` 和 `risk_pct_per_trade` 时拒绝
4. `resolved_config_json` 正确持久化
5. 参数实验请求能正确写入 batch/task/search space

### 13.3 ReadModel

1. `ParameterLabRow` 正确读出 `risk_pct_per_trade`
2. 参数摘要正确区分 `cash95` 与 `risk1.0%`
3. 参数组聚合 key 不混淆两种仓位模式

### 13.4 前端

1. v2 表单切换仓位模式时显示正确字段
2. build 通过
3. 推荐 / 参数摘要 / 单次分析页能看到仓位模式信息

## 14. 推荐实施顺序

### Phase A

先做：

1. ExecutionConstraints 扩展
2. 执行层 qty 推导逻辑
3. 单次 run API
4. `resolved_config_json` 持久化
5. 核心执行层测试

### Phase B

再做：

1. v2 策略参数扩展
2. readmodel
3. 单次分析 UI

### Phase C

最后做：

1. 参数实验支持
2. 参数组聚合 key 扩展
3. 实验 UI
4. 风险诊断字段预留或首批指标

## 15. 推荐默认策略

为了避免一次性冲击既有 v2 结果，建议：

### 第一版实现策略

1. 保留 `percent_of_cash` 为现有默认
2. 新增 `risk_pct_of_equity` 作为显式可选模式
3. 在研究层和文档层明确推荐优先使用 `risk_pct_of_equity` 做新一轮 v2 验证

### 第二版策略

如果新实验表明风险曲线显著改善，再考虑：

1. 将 v2 默认仓位模式切到 `risk_pct_of_equity`
2. 逐步淡化 `percent_of_cash` 在 v2 中的默认地位

## 16. 一句话总结

一句话总结本设计：

```text
新增 risk_pct_of_equity 的目的，不是增加一个新玩法，而是让 ATR 止损第一次真正决定“这笔交易应该开多大”。
```

