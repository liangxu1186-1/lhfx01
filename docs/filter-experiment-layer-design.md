# 过滤器实验层设计

## 1. 文档目标

本文档定义三池研究流程之后的下一层验证能力：过滤器实验层。

目标是让用户在已经筛选出的 run / 参数组基础上，单独测试或叠加测试外部过滤指标，用于降低回撤、识别不适合交易的市场状态，并验证这些过滤是否改善 OOS/DD、PF、Gap 和回撤表现。

本文档只涉及：

- 研究层工作流
- 过滤器定义与参数范围
- 实验任务组织方式
- readmodel 与前端展示
- 结果评价标准

本文档不改变：

- `ema_crossover v1` 策略逻辑
- `ema_pullback_atr_v2` 策略逻辑
- 原策略入场信号定义
- 原策略 SL/TP 生成语义
- 执行层成交、gap open、同 bar 优先级语义
- 现有风险矩阵的 risk / cash / 杠杆含义

过滤器实验层的定位是：

```text
原策略信号生成后，进入订单执行前，额外判断当前市场状态是否允许交易。
```

因此它是研究验证层和执行前置条件，不是新策略重写。

## 2. 背景

当前三池流程已经能支持：

- 初筛池发现高分 run
- 研究池聚合候选参数组
- 邻域验证参数是否稳定
- 风险矩阵比较 risk / cash / 杠杆组合
- 稳定池沉淀人工确认后的候选配置

当前新的研究问题是：

```text
部分候选标的和参数盈利能力可以，但最大回撤偏高。
不希望通过降低杠杆或降低单笔风险来解决，而希望用其他指标过滤掉不适合交易的行情。
```

因此下一步不应继续扩大原策略参数搜索，也不应默认做风险降档，而应验证：

- 哪些市场状态导致回撤集中出现
- 哪些过滤指标能减少差行情中的交易
- 哪些过滤不会过度牺牲收益和交易数
- 哪些过滤对多个标的、多个参数组都有效

## 3. 核心原则

### 3.1 固定原 run 参数

过滤器实验的输入必须来自已经选中的 run / 参数组。

实验时固定原策略参数，例如：

```text
tf / ts / ema / atr / tol / sl / rr / risk / cash / leverage
```

过滤器实验不重新搜索这些参数。

### 3.2 每个指标必须能单独测试

每一种过滤器都必须支持单独开关和独立实验。

原因：

- 判断单个过滤器是否真正有效
- 避免多个过滤器叠加后无法解释收益变化来源
- 降低二次过拟合风险

### 3.3 支持手动叠加

用户可以从单指标结果中挑选有效过滤器，再手动叠加。

第一版不做全量暴力组合搜索。

### 3.4 不把过滤器混入原策略参数

过滤器参数不应污染原策略参数组定义。

原策略参数组仍表示：

```text
策略 + 标的 + 周期 + 入场结构 + 风险配置
```

过滤器实验结果应作为额外验证样本和过滤配置建议存在。

### 3.5 评价重点是风险质量，不是单纯收益

过滤器的目标不是让收益最大，而是改善收益质量。

核心评价顺序：

```text
OOS/DD -> 最大回撤 -> PF -> OOS 超额 -> Gap -> 交易数保留率
```

## 4. 对象模型

## 4.1 FilterExperiment

过滤器实验批次。

建议字段：

- `filter_experiment_id`
- `source_type`
- `source_ids`
- `strategy_name`
- `symbols`
- `timeframes`
- `mode`
- `filters`
- `created_at`
- `status`
- `planned_run_count`
- `run_count`

其中 `source_type` 可选：

- `run`
- `research_candidate`
- `stable_candidate`
- `parameter_group`

## 4.2 FilterConfig

过滤器配置。

建议字段：

- `filter_id`
- `filter_type`
- `enabled`
- `params`
- `description`

示例：

```json
{
  "filter_type": "higher_timeframe_trend",
  "enabled": true,
  "params": {
    "timeframe": "4h",
    "ema_fast": 50,
    "ema_slow": 200,
    "mode": "direction_aligned"
  }
}
```

## 4.3 FilteredRunObservation

过滤器实验生成的新 run 观测。

建议保留：

- 原 run id
- 新 run id
- 原策略参数摘要
- 过滤器配置摘要
- 原始指标
- 过滤后指标
- 指标变化

过滤后的 run 可以进入参数实验结果和研究读模型，但必须能识别为：

```text
source = filter_experiment
```

避免和原始策略参数搜索混在一起。

## 5. 过滤器类型

## 5.1 大周期趋势过滤

目标：

```text
只在更高周期趋势方向一致时允许交易。
```

适用场景：

- EMA Pullback ATR
- 趋势回调类策略
- 高回撤来自震荡或逆大势交易的情况

候选参数：

- `higher_timeframe`: `4h`, `1d`
- `trend_mode`:
  - `close_above_ema`
  - `ema_fast_above_slow`
  - `direction_aligned`
- `ema_fast`: 50
- `ema_slow`: 200

第一版建议组合：

```text
1H 策略 + 4H EMA50/EMA200 趋势方向过滤
```

## 5.2 ATR 分位过滤

目标：

```text
过滤掉波动过低或波动极端过高的行情。
```

适用场景：

- ATR 止损策略
- 假突破频繁
- 极端波动扫损严重

候选参数：

- `atr_period`: 14
- `lookback_bars`: 200, 500
- `min_percentile`: 10, 20, 30
- `max_percentile`: 70, 80, 90

第一版建议测试：

```text
ATR 分位 20%-80%
ATR 分位 10%-90%
ATR 分位 >= 20%
```

## 5.3 ADX 趋势强度过滤

目标：

```text
只在趋势强度足够时允许交易。
```

适用场景：

- 震荡期亏损较多
- 趋势策略在无趋势环境中频繁止损

候选参数：

- `adx_period`: 14
- `min_adx`: 15, 20, 25
- `max_adx`: 可选，第一版可不启用

第一版建议测试：

```text
ADX >= 15
ADX >= 20
ADX >= 25
```

## 5.4 BTC 大盘状态过滤

目标：

```text
用 BTC 的大周期状态作为全市场风险开关。
```

适用场景：

- 非 BTC 标的
- 山寨币受 BTC 方向和波动影响明显
- 单币信号和大盘风险状态冲突

候选参数：

- `market_symbol`: `BTC/USDT:USDT`
- `market_timeframe`: `4h`, `1d`
- `mode`:
  - `btc_trend_aligned`
  - `btc_not_extreme_volatility`
  - `btc_risk_on_only`

第一版建议：

```text
非 BTC 标的做多时，BTC 4H 趋势必须不为空头。
非 BTC 标的做空时，BTC 4H 趋势必须不为强多头。
```

## 5.5 连续亏损暂停

目标：

```text
当策略近期连续失效时暂停一段时间。
```

适用场景：

- 回撤由连续亏损簇造成
- 策略进入某种行情后持续失效

候选参数：

- `loss_streak`: 2, 3, 4
- `cooldown_bars`: 12, 24, 48

注意：

该过滤器依赖交易结果状态，属于执行层保护条件。第一版应作为后置实验，不应优先实现。

## 5.6 回撤暂停

目标：

```text
当当前配置进入局部回撤后暂停交易。
```

候选参数：

- `drawdown_threshold`: 5%, 10%, 15%
- `cooldown_bars`: 24, 48, 72
- `resume_condition`:
  - `cooldown_elapsed`
  - `new_equity_high`
  - `trend_recovered`

注意：

该过滤器更接近资金曲线管理，不是市场状态过滤。第一版可以设计但不优先落地。

## 6. 实验模式

## 6.1 单指标测试

每次只启用一种过滤器。

示例：

```text
原始 run
原始 run + HTF 趋势过滤
原始 run + ATR 分位过滤
原始 run + ADX 过滤
原始 run + BTC 状态过滤
```

目标：

- 判断单个过滤器是否有正贡献
- 为后续叠加提供候选

## 6.2 手动叠加测试

用户手动选择多个过滤器叠加。

示例：

```text
HTF 趋势 + ATR 分位
HTF 趋势 + BTC 状态
ATR 分位 + ADX
HTF 趋势 + ATR 分位 + BTC 状态
```

目标：

- 验证互补性
- 找出收益质量更好的组合

## 6.3 推荐组合测试

系统根据单指标测试结果推荐少量组合。

第一版推荐规则可以很保守：

```text
只推荐单指标 OOS/DD 提升且交易数保留率 >= 50% 的过滤器组合。
```

## 7. 前端工作流

## 7.1 入口

入口建议放在：

- 研究池行操作：`过滤器实验`
- 稳定池行操作：`过滤器实验`
- Run 对比弹窗：选中 run 后 `过滤器实验`

第一版优先支持研究池和稳定池。

## 7.2 配置面板

配置面板包括：

- 来源对象
- 测试模式
- 过滤器选择
- 每个过滤器的参数范围
- 预计 run 数
- 提交按钮

默认模式：

```text
单指标测试
```

默认过滤器：

```text
HTF 趋势过滤
ATR 分位过滤
BTC 状态过滤
```

ADX、连续亏损暂停、回撤暂停可以先放到高级选项。

## 7.3 结果表

结果表以原始 run / 参数组为基准，展示过滤前后变化。

建议字段：

- `来源`
- `过滤器`
- `参数摘要`
- `OOS`
- `OOS 超额`
- `IS 超额`
- `最大回撤`
- `OOS/DD`
- `PF`
- `交易数`
- `交易数保留率`
- `Gap`
- `结论`

默认排序：

```text
OOS/DD desc -> 最大回撤 asc -> PF desc -> OOS 超额 desc
```

## 7.4 结论标签

建议自动标签：

- `有效降回撤`
- `OOS/DD 改善`
- `PF 改善`
- `过度过滤`
- `收益损失过大`
- `交易数不足`
- `无明显改善`
- `建议叠加测试`

## 8. 评价标准

一个过滤器可以被认为有价值，需要至少满足以下条件之一：

- 最大回撤明显下降
- OOS/DD 提高
- PF 提高
- Gap 变小
- OOS 超额仍为正
- 多个标的上效果一致

同时必须避免：

- 交易数过少
- 只在单一标的有效
- OOS 提升来自极少数交易
- IS 改善但 OOS 恶化
- 回撤下降但收益质量没有改善

第一版建议硬性警戒线：

```text
交易数保留率 < 30% -> 过度过滤
OOS 交易数 < 30 -> 样本不足
OOS 超额转负 -> 不建议采用
最大回撤未下降且 OOS/DD 未提高 -> 无明显改善
```

## 9. API 与 readmodel 边界

## 9.1 新增 API 草案

提交过滤器实验：

```text
POST /api/filter-experiments
```

查看过滤器实验列表：

```text
GET /api/filter-experiments
```

查看过滤器实验详情：

```text
GET /api/filter-experiments/{filter_experiment_id}
```

查看某个研究候选的过滤器结果：

```text
GET /api/research-candidates/{candidate_id}/filter-results
```

## 9.2 readmodel

建议新增：

- `FilterExperimentSummary`
- `FilterExperimentDetail`
- `FilterResultView`
- `FilterComparisonView`

研究池和稳定池可以只显示聚合摘要：

- `filter_experiment_summary.status`
- `filter_experiment_summary.best_verdict`
- `filter_experiment_summary.best_oos_dd_delta`
- `filter_experiment_summary.best_drawdown_delta`
- `filter_experiment_summary.result_count`

## 10. 实施阶段

## 10.1 Phase 1：文档与对象边界

- 固化本文档
- 明确过滤器实验不改变策略语义
- 明确实验输入来自研究池 / 稳定池

## 10.2 Phase 2：单指标测试骨架

- 支持 `HTF 趋势过滤`
- 支持 `ATR 分位过滤`
- 支持 `BTC 状态过滤`
- 支持从研究池单个候选发起过滤器实验
- 结果表展示原始 vs 过滤后

## 10.3 Phase 3：叠加测试

- 支持用户手动选择多个过滤器叠加
- 支持预计 run 数
- 支持结果自动标签

## 10.4 Phase 4：稳定池接入

- 稳定池显示过滤器验证摘要
- 进入稳定池时可附带推荐过滤器配置
- 后续导出或模拟时保留过滤器配置

## 10.5 Phase 5：高级保护条件

- 连续亏损暂停
- 回撤暂停
- 更复杂的 BTC 风险状态
- 多市场共振过滤

## 11. 暂不做事项

第一版不做：

- 全量暴力过滤器组合搜索
- 自动修改原策略参数
- 自动替换稳定池配置
- 动态止损 / 动态止盈
- 仓位降档
- 实盘执行接入

这些能力应在单指标过滤器验证有效之后再考虑。

## 12. 结论

过滤器实验层的核心价值是：

```text
不改变已经选出的策略参数和风险配置，通过识别不适合交易的市场状态来降低回撤。
```

下一步应优先落地：

```text
研究池候选 -> 单指标过滤器实验 -> 原始 vs 过滤后结果对比
```

只有当单指标实验证明某些过滤器有效后，才进入手动叠加测试。
