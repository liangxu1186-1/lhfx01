# 稳定池执行验证 Run 设计

## 1. 文档目标

本文档定义稳定池候选进入模拟盘前的执行验证方案。

当前稳定池中的候选主要来自 `1h` K 线回测。`1h` OHLC 只能说明一小时内出现过 `open/high/low/close`，但无法说明这一小时内价格先触达 `high` 还是先触达 `low`。因此，当同一根 `1h` K 线同时覆盖止损价和止盈价时，回测只能依赖执行层假设。

本文档的目标是补一层独立验证：

```text
稳定池候选
  -> 保留原 1h 研究 run
  -> 派生低周期执行验证 run
  -> 对比原 run 与验证 run
  -> 判断是否可进入模拟盘
```

本文档只设计新增验证能力，不改变现有普通 run、参数实验、稳定池 readmodel、策略信号和执行层默认语义。

## 2. 核心结论

不要覆盖或重跑替换原有 run。

原有 `1h` run 继续作为研究证据保存。新增一类派生 run：

```text
run_type = execution_verification
```

它使用原 run 的策略配置重新生成 `1h` 信号，但用 `1m` 或 `5m` K 线按时间顺序模拟成交、止损和止盈。

第一版推荐使用：

```text
strategy_timeframe = 1h
execution_timeframe = 5m
```

原因是 `5m` 已能显著减少 `1h` OHLC 内部先后顺序不明的问题，同时数据量和运行成本比 `1m` 更可控。关键候选后续可再用 `1m` 精验。

## 3. 背景问题

### 3.1 1h OHLC 的顺序不可见

一根 `1h` K 线包含：

```text
open
high
low
close
```

但不包含：

```text
先 high 后 low
还是先 low 后 high
```

因此，如果一笔持仓在某根 `1h` K 线中同时满足：

```text
high >= take_profit_price
low <= stop_loss_price
```

仅凭 `1h` OHLC 无法判断真实交易结果。

当前执行层采用保守规则可以保证研究口径一致，但不能消除模拟盘前的执行不确定性。

### 3.2 稳定池候选不能直接等于模拟盘策略

稳定池当前更接近：

```text
研究稳定候选
```

它证明某组策略参数在历史 `1h` 研究口径下表现较好，但尚未证明：

- 止损止盈在低周期价格路径下仍然成立
- 交易结果不是 `1h` 同 bar 假设带来的偏差
- 新 run 在更接近模拟盘的执行语义下仍满足风险门槛

因此稳定池进入模拟盘前需要增加执行验证状态。

## 4. 不改变的内容

本方案不改变：

- `ema_pullback_atr_v2` 入场信号定义
- `1h` 策略参数搜索与参数实验结果
- 普通 run 的回测执行语义
- 现有稳定池候选的生成方式
- 现有 Research Note 和三池流程的基本用法
- 现有单次分析页、交易明细和资金曲线的主体能力

本方案新增的是派生验证 run 和稳定池验证状态，不回写或覆盖原始 run。

## 5. 新对象：Execution Verification Run

### 5.1 定义

执行验证 run 是从一个原始研究 run 派生出来的验证 run。

它回答的问题是：

```text
同一套 1h 策略信号，在低周期 K 线顺序执行下，结果是否仍然可接受？
```

### 5.2 元数据

建议在 `resolved_config_json` 或 manifest 中增加：

```json
{
  "run_type": "execution_verification",
  "parent_run_id": "run-xxx",
  "stable_candidate_id": "candidate-xxx",
  "strategy_timeframe": "1h",
  "execution_timeframe": "5m",
  "execution_model_version": "intrabar-v1",
  "source": {
    "type": "stable_candidate",
    "id": "candidate-xxx"
  }
}
```

其中：

- `parent_run_id` 指向原始 `1h` run
- `stable_candidate_id` 指向稳定池候选
- `strategy_timeframe` 表示信号生成周期
- `execution_timeframe` 表示成交和 SL/TP 回放周期
- `execution_model_version` 用于后续兼容执行语义演进

### 5.3 产物

执行验证 run 仍应产出和普通 run 一致的核心文件：

```text
orders.csv
fills.csv
trades.csv
equity.csv
metrics.json
manifest.json
resolved_config.json
```

这样可以复用现有单次分析页、资金曲线、交易明细、归因分析和指标展示。

## 6. 执行流程

### 6.1 入口

建议第一版新增入口：

```http
POST /api/stable-candidates/{stable_candidate_id}/execution-verification
```

请求：

```json
{
  "source_run_id": "run-xxx",
  "execution_timeframe": "5m"
}
```

第一版只支持：

- `strategy_timeframe = 1h`
- `execution_timeframe = 5m`
- 单 stable candidate
- 单 source run

### 6.2 读取原 run 配置

从 `source_run_id` 读取：

- `strategy_name`
- `strategy_version`
- `strategy_params`
- `execution_constraints`
- `fee_model_params_json`
- `slippage_model_params_json`
- `validation_split_id`
- `dataset_snapshot_id`

读取后重新构造策略对象，而不是直接复用原 trades。

### 6.3 重新生成 1h 信号

用原 run 配置重新生成 `1h` signals。

第一版应做基础一致性校验：

- 生成的信号数量与原 run 接近或一致
- 关键时间范围一致
- 策略参数摘要一致

如果校验失败，执行验证 run 不应继续生成结果，应返回明确失败原因。

### 6.4 补充低周期数据

根据原 run 的标的和时间范围拉取低周期 K 线：

```text
symbol = 原 run symbol
execution_timeframe = 5m
start = 原 run 分析开始时间
end = 原 run 分析结束时间
```

数据应保存为独立 dataset snapshot，避免污染原 `1h` snapshot。

建议 snapshot id 包含：

```text
symbol
execution_timeframe
source_run_id
时间范围
```

### 6.5 低周期执行回放

执行语义：

```text
1h bar close 生成 OPEN signal
-> 下一根可交易 execution_timeframe K 线 open 开仓
-> 持仓期间按 execution_timeframe K 线时间顺序检查 SL/TP
-> 触发后按低周期规则生成 close order/fill/trade
-> 若未触发，继续等待后续低周期 K 线
```

SL/TP 仍基于真实 fill price 和原策略 risk spec 计算。

### 6.6 保存派生 run

验证 run 使用新的 run id，不覆盖原 run。

建议命名：

```text
ev-{parent_run_id}-exec5m-{timestamp}
```

或者：

```text
execution-verification-{stable_candidate_short_id}-{timestamp}
```

## 7. 分析与展示

### 7.1 单次分析页复用

执行验证 run 可以像普通 run 一样打开单次分析页。

页面需要展示额外标识：

```text
执行验证 run
父 run: run-xxx
策略周期: 1h
执行周期: 5m
执行模型: intrabar-v1
```

### 7.2 稳定池详情对比

稳定池详情应新增对比区：

```text
原 1h run vs 5m 执行验证 run
```

建议字段：

- 总收益差异
- OOS 收益差异
- 最大回撤差异
- PF 差异
- 胜率差异
- 交易数差异
- 止损次数差异
- 止盈次数差异
- gap open 次数差异
- 最大单笔亏损差异
- 是否仍满足 paper ready 门槛

### 7.3 初筛池隔离

执行验证 run 不应默认进入普通初筛评分。

推荐规则：

```text
普通参数 run -> 进入初筛池
execution_verification run -> 进入稳定池证据和对比分析
```

原因是执行验证 run 是证据，不是新的参数候选。混入初筛池会污染参数搜索排序。

## 8. 稳定池状态升级

建议把稳定池候选拆成三层状态：

```text
research_stable
execution_verified
paper_ready
```

### 8.1 research_stable

候选已经通过现有稳定池研究判断，但只基于普通回测和研究验证。

### 8.2 execution_verified

候选至少有一条执行验证 run，并且验证结果没有显著恶化。

建议门槛：

- 验证 run OOS 收益仍为正
- 验证 run PF 仍达到最低阈值
- 验证 run 最大回撤未超过稳定池阈值，当前稳定池阈值为 `< 40%`
- 验证 run 交易数没有严重下降
- 验证 run 最大单笔亏损没有明显失控

### 8.3 paper_ready

候选可以进入本地模拟盘。

建议额外要求：

- `execution_timeframe = 5m` 已通过
- 关键候选可选补充 `1m` 精验
- 风险配置使用 `risk_pct_of_equity` 或 `risk_pct_of_cash_allocation`
- 杠杆和单笔风险不超过预设上限
- 最近一次验证未过期

## 9. API 建议

### 9.1 发起执行验证

```http
POST /api/stable-candidates/{stable_candidate_id}/execution-verification
```

返回：

```json
{
  "task_id": "task-xxx",
  "task_status": "pending",
  "stable_candidate_id": "candidate-xxx",
  "parent_run_id": "run-xxx",
  "execution_timeframe": "5m"
}
```

### 9.2 查询验证结果

可以先复用现有 run 查询：

```http
GET /api/runs/{verification_run_id}
```

稳定池 readmodel 中增加：

```json
{
  "execution_verification": {
    "latest_run_id": "ev-xxx",
    "status": "passed",
    "strategy_timeframe": "1h",
    "execution_timeframe": "5m",
    "summary": {}
  }
}
```

## 10. 数据边界

### 10.1 时间范围

第一版使用 parent run 的分析时间范围，不扩展到更长时间。

后续可增加：

- 最近窗口复测
- forward-only 新数据验证
- 多 source run 合并验证

### 10.2 数据缺失

低周期数据缺失时必须明确失败或降级，不应静默跳过。

建议失败条件：

- 低周期数据不能覆盖 parent run 分析区间
- 低周期 K 线存在明显断档
- 关键开仓时间找不到下一根可交易低周期 open

### 10.3 同周期回退

如果低周期数据不可用，不建议自动回退到 `1h`。

可以返回：

```text
execution_verification_failed: lower_timeframe_data_missing
```

这样不会让用户误以为已经完成执行验证。

## 11. 验证方式

后续实施时至少需要测试：

1. 原 run 不被覆盖。
2. 执行验证 run 能保存完整 run 产物。
3. `run_type = execution_verification` 的 run 不进入普通初筛池评分。
4. 同一 `1h` 信号能映射到下一根低周期 open。
5. 低周期 K 线能按时间顺序触发 SL/TP。
6. 低周期数据缺失时返回明确失败。
7. 稳定池详情能展示 parent run 与 verification run 对比。
8. 验证通过后候选状态可升级为 `execution_verified`。

## 12. 分阶段实施

### Phase A：文档与模型边界

- 确认 `run_type`、`parent_run_id`、`strategy_timeframe`、`execution_timeframe` 字段落点
- 确认执行验证 run 不进入普通初筛池
- 确认稳定池状态命名

### Phase B：后端最小闭环

- 新增执行验证 workflow
- 读取 parent run 配置
- 生成 `1h` signals
- 加载或拉取 `5m` K 线
- 生成派生 run 产物

### Phase C：稳定池展示

- 稳定池详情增加验证 run 列表
- 增加 parent run vs verification run 指标对比
- 增加验证状态和失败原因

### Phase D：模拟盘入口前置

- 只有 `paper_ready` 候选可以进入模拟盘
- 模拟盘只消费稳定池导出的策略配置，不直接消费普通 run

## 13. 当前结论

稳定池候选不能直接进入模拟盘。

正确路径是：

```text
1h 研究 run
  -> 稳定池候选
  -> 5m/1m 执行验证 run
  -> execution_verified
  -> paper_ready
  -> 本地模拟盘
```

这样既保留原有研究 run 的可复现性，也能用更接近真实价格路径的低周期数据验证 SL/TP 顺序，避免把 `1h` OHLC 假设直接带入模拟盘。
