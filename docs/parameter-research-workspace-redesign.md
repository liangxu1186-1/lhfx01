# 参数研究工作台重构设计

## 1. 文档目标

本文档定义参数实验与结果分析层的重构方案。

重构目标不是改变回测策略或执行语义，而是把当前以：

```text
batch -> run
```

为主的浏览方式，重构为以：

```text
research subject -> parameter group -> run observation
```

为主的研究工作台。

本文档只涉及：

- 信息架构
- readmodel
- API
- 前端研究界面
- 推荐与横向比较方式

本文档不改变：

- `ema_crossover v1` 策略逻辑
- `ema_pullback_atr_v2` 策略逻辑
- 执行层下单与成交语义
- v2 静态初始 SL/TP 语义
- `percent_of_cash` / `risk_pct_of_equity` 含义
- 参数实验任务提交与回测执行流程

## 2. 背景与问题定义

当前系统已经具备：

- 单次 run 回测
- 参数实验
- 参数实验批次
- 研究分、推荐标签、邻域分析
- OOS / Gap / 回撤 / PF 等关键指标

当前主要问题不在于结果不够多，而在于结果组织方式不匹配研究问题。

现在主视角是：

```text
批次 -> 推荐 run -> run 详情
```

但用户真正想回答的问题是：

- `ETH/USDT 1H` 下哪组参数更好
- 同一组参数在不同实验中是否持续表现较好
- 哪个参数区域更稳，而不是某一条 run 偶然最好

因此当前工作流存在三个结构性错位：

### 2.1 把 batch 当成研究主对象

`batch` 只是实验执行容器，不是研究主对象。

用户不研究“某个 batch”，而是在研究：

- 某个策略
- 某个标的
- 某个周期
- 某种 validation 条件

### 2.2 把 run 当成结论主实体

`run` 只是某一组参数在某一次数据快照上的一次观测结果。

它适合作为证据，不适合作为研究结论主实体。

### 2.3 参数组缺少一级地位

用户真正要横向比较的是参数组：

```text
tf2 ts13 tol1 sl2 rr1.5 risk3% l5
vs
tf3 ts13 tol1 sl2 rr2 risk3% l5
```

因此新的研究系统应把 `parameter group` 提升为一级实体。

## 3. 设计结论

重构后的主模型应为：

```text
ResearchSubject
  -> ParameterGroup
    -> RunObservation
```

含义如下：

### 3.1 ResearchSubject

研究对象。

用于定义“当前到底在研究哪一类市场与策略对象”。

### 3.2 ParameterGroup

参数组。

是横向比较、推荐、人工判断和下一轮收敛的主实体。

### 3.3 RunObservation

单次观测样本。

每一条 run 是参数组在某次实验、某个 snapshot 下的一次具体观测。

## 4. 设计原则

### 4.1 不偏离最初策略设计

本方案只重构研究与展示层，不改策略或执行边界。

特别保持：

- v2 仍是单周期
- v2 仍只生成 `OPEN`
- v2 `SL/TP` 仍由执行层基于真实 fill price 计算
- v2 仍使用静态初始 SL/TP，不引入动态止损/止盈

### 4.2 参数组是研究主实体

首页主表展示参数组，而不是 run。

### 4.3 run 退到证据层

run 作为参数组详情中的观测明细使用。

### 4.4 batch 退到执行审计层

batch 保留，但只承担：

- 任务提交记录
- 成功/失败状态
- 新增样本来源追踪

### 4.5 横向比较优先于最新批次

研究工作台必须优先回答：

> 同一研究对象下，不同参数组谁更好

而不是优先回答：

> 最新这个 batch 跑出来哪些 run

## 5. 核心实体定义

## 5.1 ResearchSubject

定义一个研究对象：

- `strategy_name`
- `symbol`
- `timeframe`
- `validation_split_id`

第一版不把 `dataset_snapshot_id` 放入 research subject key。

原因：

- research subject 关注的是一个市场对象与验证 regime
- snapshot 是观测样本维度，不应提前切碎研究对象

### 5.1.1 示例

```text
ema_pullback_atr_v2 | ETH/USDT:USDT | 1H | validation:none
```

### 5.1.2 作用

ResearchSubject 是新研究工作台的主入口。

用户应先选择研究对象，再看参数组。

## 5.2 ParameterGroup

ParameterGroup 是参数比较的主实体。

每个参数组属于一个研究对象，并包含一组固定参数。

### 5.2.1 v1 参数组 key

对 `ema_crossover`：

- `strategy_name`
- `symbol`
- `timeframe`
- `validation_split_id`
- `fast_period`
- `slow_period`
- `qty_policy_ref`
- `cash_allocation_pct` 或 `risk_pct_per_trade`
- `leverage`

### 5.2.2 v2 参数组 key

对 `ema_pullback_atr_v2`：

- `strategy_name`
- `symbol`
- `timeframe`
- `validation_split_id`
- `trend_fast_period`
- `trend_slow_period`
- `entry_ema_period`
- `atr_period`
- `atr_entry_tolerance`
- `atr_stop_mult`
- `risk_reward_ratio`
- `qty_policy_ref`
- `cash_allocation_pct` 或 `risk_pct_per_trade`
- `leverage`

### 5.2.3 固定策略参数

对于 v2：

- `entry_ema_period`
- `atr_period`
- `min_atr_pct_of_price`
- `min_stop_pct`

其中：

- `entry_ema_period`
- `atr_period`

进入参数组 key，因为它们会直接影响可比性。

其中：

- `min_atr_pct_of_price`
- `min_stop_pct`

第一版不进入主显示摘要，但必须进入详情展示与可追溯配置。

### 5.2.4 参数组摘要

参数组摘要继续沿用现有紧凑文本风格，例如：

```text
tf2 ts13 ema21 atr14 tol1 sl2 rr1.5 risk3% l5
```

这是展示层摘要，不等同于参数组唯一 key。

## 5.3 RunObservation

RunObservation 表示参数组的一次观测样本。

字段包括：

- `run_id`
- `batch_id`
- `experiment_id`
- `dataset_snapshot_id`
- `created_at`
- `status`
- `parameter_group_key`
- `total_return`
- `oos_total_return`
- `gap`
- `max_drawdown`
- `trade_count`
- `oos_trade_count`
- `win_rate`
- `oos_win_rate`
- `profit_factor`
- `final_equity`

其中：

```text
gap = is_total_return - oos_total_return
```

或沿用当前系统一致的 Gap 定义。

RunObservation 不承担推荐主逻辑，只用于参数组详情与证据展示。

## 6. 研究工作流重构

## 6.1 现有工作流

当前流程更接近：

```text
看 batch
  -> 看推荐 run
    -> 手工记住参数
      -> 再去看别的 batch
        -> 自己做横向对比
```

问题在于：

- 需要大量人工记忆
- 同类参数容易分散在不同 batch
- 参数比较依赖脑内拼接
- 很难直接形成稳定研究结论

## 6.2 新工作流

目标流程：

```text
先选研究对象
  -> 看参数组排行榜
    -> 点开参数组详情
      -> 看 run 样本分布
        -> 看邻域稳定性
          -> 记录研究结论
```

这样系统会先给出“参数组级结论”，而不是先暴露大量 run 噪声。

## 7. 页面与信息架构

## 7.1 新主页面：研究对象工作台

参数实验区域重构为以研究对象为主入口的工作台。

### 7.1.1 顶部研究对象选择器

筛选条件：

- `strategy_name`
- `symbol`
- `timeframe`
- `validation_split_id`
- 可选：
  - `qty_policy_ref`
  - `leverage`
  - snapshot 范围

目标是快速进入：

```text
某个策略 + 某个标的 + 某个周期
```

的横向比较场景。

### 7.1.2 研究对象摘要卡

展示：

- 参数组数量
- run 样本数
- snapshot 数
- 最新更新时间
- 当前研究对象名称

## 7.2 主表：参数组排行榜

参数组排行榜是新工作台的主表。

每一行表示一个 `ParameterGroup`。

### 7.2.1 建议列

- 参数摘要
- run 数
- snapshot 数
- 平均总收益
- 平均 OOS
- OOS 正比例
- 平均 Gap
- 平均回撤
- 最差回撤
- 平均 PF
- 最少交易数
- 邻域稳定度
- 研究分
- 分类
- 人工状态
- 操作

### 7.2.2 默认排序逻辑

默认按：

1. 分类优先级
2. 研究分
3. OOS
4. 回撤
5. Gap

### 7.2.3 目标

这张表优先回答：

> 哪组参数最值得继续研究

而不是：

> 哪条 run 排第一

## 7.3 参数组详情页

点开参数组后进入参数组详情。

建议包含四个区域。

### 7.3.1 聚合摘要

展示：

- 参数摘要
- 策略 / 标的 / 周期
- qty 模式
- 杠杆
- run 数
- snapshot 数
- 平均总收益
- 平均 OOS
- OOS 正比例
- 平均 Gap
- 平均回撤
- 最差回撤
- 平均 PF
- 平均胜率
- 人工结论

### 7.3.2 Run 观测明细

展示每个 run 的明细：

- `run_id`
- `batch_id`
- `dataset_snapshot_id`
- `created_at`
- `total_return`
- `oos_total_return`
- `gap`
- `max_drawdown`
- `profit_factor`
- `trade_count`
- `打开单次分析`

这一层是证据层，用来解释为什么参数组被判断为好或不好。

### 7.3.3 邻域分析

邻域分析从 run 迁移到参数组。

邻域规则保持策略设计原意，不引入新参数。

对于 v2：

- 固定：
  - `atr_entry_tolerance`
  - `atr_stop_mult`
  - `risk_reward_ratio`
  - `qty_policy_ref`
  - `risk_pct_per_trade / cash_allocation_pct`
  - `leverage`
  - `entry_ema_period`
  - `atr_period`
- 只比较：
  - `trend_fast_period`
  - `trend_slow_period`

这样邻域结论更符合“趋势周期邻域”的原始分析目标。

### 7.3.4 人工研究结论

对参数组记录：

- 标签
- 状态
- 备注
- 是否进入下一轮实验

人工判断对象也从 run 优先改为 parameter group 优先。

## 7.4 批次页定位调整

批次页保留，但角色调整为辅助页。

### 7.4.1 批次页保留用途

- 查看该批次执行是否成功
- 查看该批次包含哪些实验
- 查看该批次新增了哪些参数组样本
- 审计某次实验提交来源

### 7.4.2 批次页不再承担的职责

- 不再作为主横向比较入口
- 不再承载长期研究结论主视角

## 8. readmodel 重构方案

本轮建议新增专用研究 readmodel，而不是继续在现有批次 readmodel 上叠功能。

## 8.1 新增 `ResearchSubjectView`

字段建议：

- `subject_key`
- `strategy_name`
- `symbol`
- `timeframe`
- `validation_split_id`
- `parameter_group_count`
- `run_count`
- `snapshot_count`
- `latest_run_at`

### 8.1.1 作用

用于研究对象列表与顶部选择器。

## 8.2 新增 `ParameterGroupView`

字段建议：

- `group_key`
- `subject_key`
- `strategy_name`
- `symbol`
- `timeframe`
- `validation_split_id`
- `parameter_summary`
- 参数字段明细
- `qty_policy_ref`
- `cash_allocation_pct`
- `risk_pct_per_trade`
- `leverage`
- `run_count`
- `snapshot_count`
- `avg_total_return`
- `avg_oos_total_return`
- `oos_positive_ratio`
- `avg_gap`
- `avg_max_drawdown`
- `worst_max_drawdown`
- `avg_profit_factor`
- `avg_win_rate`
- `min_trade_count`
- `neighbor_count`
- `stable_neighbor_count`
- `neighbor_stability_score`
- `research_score`
- `classification`
- `representative_run_id`

### 8.2.1 分类字段

`classification` 建议沿用现有认知，但以参数组为单位输出：

- `robust_candidate`
- `high_return_candidate`
- `exploratory_candidate`
- `excluded`

## 8.3 新增 `ParameterGroupRunView`

字段建议：

- `group_key`
- `run_id`
- `batch_id`
- `experiment_id`
- `dataset_snapshot_id`
- `created_at`
- `total_return`
- `oos_total_return`
- `gap`
- `max_drawdown`
- `profit_factor`
- `trade_count`
- `oos_trade_count`
- `win_rate`
- `oos_win_rate`
- `final_equity`

### 8.3.1 作用

用于参数组详情中的观测样本明细。

## 8.4 现有 ParameterLab 的定位

当前 `parameter_lab.rows` 已经接近全量 run 事实表。

建议：

- 保留现有 `ParameterLabRow` 作为事实层输入
- 新增一层 research readmodel 做真正聚合

不要继续直接让前端在 `rows` 上做过多研究逻辑拼装。

## 9. 推荐与评分重构

## 9.1 推荐对象改为参数组

当前系统已具备研究分和候选分类逻辑。

重构后改为：

- 推荐参数组
- run 只作为代表样本与证据

## 9.2 参数组级分类逻辑

### 9.2.1 稳健候选

倾向条件：

- `avg_oos_total_return > 0`
- `oos_positive_ratio` 高
- `avg_gap` 小
- `avg_max_drawdown` 可接受
- `worst_max_drawdown` 不失控
- `neighbor_stability_score` 高
- `min_trade_count` 不过低

### 9.2.2 高收益候选

倾向条件：

- 收益上限高
- `avg_oos_total_return > 0`
- 回撤可接受但未必低
- 邻域不崩

### 9.2.3 探索候选

倾向条件：

- 收益有亮点
- 样本量不足或稳定性尚未确认

### 9.2.4 排除组合

倾向条件：

- OOS 正比例低
- 最差回撤过大
- 邻域稳定性差
- Gap 过大
- 交易数过少

## 9.3 代表 run 规则

参数组可以附一个 `representative_run_id`。

建议优先级：

1. OOS 最好的 run
2. 若 OOS 缺失，则总收益最好的 run
3. 若需要更稳健，可改为最接近组内中位数的 run

第一版推荐使用：

```text
OOS 最好的 run
```

因为它更符合当前研究工作流。

## 10. API 设计

## 10.1 新增研究对象接口

建议：

```text
GET /api/research-subjects
```

返回：

- 研究对象列表
- 每个对象的 group 数 / run 数

## 10.2 新增参数组列表接口

建议：

```text
GET /api/parameter-groups
```

支持过滤：

- `strategy_name`
- `symbol`
- `timeframe`
- `validation_split_id`
- `qty_policy_ref`
- `leverage`

## 10.3 新增参数组详情接口

建议：

```text
GET /api/parameter-groups/{group_key}
```

返回：

- 参数组聚合指标
- run 明细
- 邻域结果
- 人工结论

## 10.4 兼容性

现有：

- `/api/parameter-experiment-batches`
- `/api/parameter-experiments`
- `/api/parameters`

继续保留。

新接口只作为研究层新入口，不破坏旧接口。

## 11. 前端页面设计

## 11.1 参数实验页重构方向

参数实验页建议分为两个明确区域：

### A. 研究工作台

默认入口。

以研究对象和参数组为主。

### B. 实验台账

保留 batch / experiment 明细。

用于执行与审计。

## 11.2 研究工作台布局

建议页面结构：

### 11.2.1 顶部筛选带

- 策略
- 标的
- 周期
- validation
- qty 模式
- 杠杆

### 11.2.2 参数组排行榜

大表，支持：

- 排序
- 筛选
- 高亮候选

### 11.2.3 右侧详情或弹窗详情

点开后看：

- 聚合摘要
- run 样本
- 邻域
- 人工笔记

## 11.3 人工研究记录对象调整

当前人工结论如果优先挂 run，会导致结论碎片化。

建议未来优先挂在：

- `parameter_group`

必要时保留：

- `run`
- `batch`

这样：

- batch 结论 = 这次实验整体判断
- parameter group 结论 = 真正的研究判断
- run 结论 = 某次具体证据说明

## 12. 迁移策略

## 12.1 不做一次性替换

建议分阶段落地。

### Phase A

先补后端 research readmodel 和新 API。

不改策略，不改回测执行。

### Phase B

新增研究工作台 UI：

- 研究对象选择器
- 参数组排行榜
- 参数组详情

### Phase C

逐步降低 batch 页面复杂度。

把：

- 推荐研究 Run
- 参数组结论

迁移为：

- 推荐参数组
- 参数组详情

### Phase D

如新工作台足够稳定，再考虑进一步简化旧批次视图。

## 12.2 数据兼容性

现有 run 数据、批次数据、实验数据都继续保留。

本轮主要新增的是聚合 readmodel，不做历史数据迁移。

## 13. 验收标准

当以下问题能由系统直接回答，而不需要用户自己跨 batch 记忆拼接时，说明方案落地成功：

### 13.1 研究对象问题

系统能直接回答：

```text
ETH/USDT 1H 下，当前最值得研究的参数组是哪几组？
```

### 13.2 参数组问题

系统能直接回答：

```text
tf2 ts13 tol1 sl2 rr1.5 risk3% l5
这组参数在多个 run 上是否持续较好？
```

### 13.3 横向比较问题

系统能直接回答：

```text
在同一个研究对象下，
tf2/ts13 与 tf3/ts13 谁更稳、谁更强？
```

### 13.4 研究决策问题

系统能直接支持：

- 哪组参数进入下一轮实验
- 哪组参数只是高收益但高波动
- 哪组参数应排除

## 14. 最终结论

本方案不改变策略设计，只改变研究设计。

重构后的参数实验系统应从：

```text
以 batch 和 run 为中心的浏览系统
```

升级为：

```text
以 research subject 和 parameter group 为中心的研究系统
```

这样才能让系统真正帮助用户回答：

> 同一研究对象下，哪些参数组更好、更稳、更值得继续研究

而不是把大量 run 结果交给用户自己在脑中做横向拼接。
