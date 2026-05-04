# 回测系统下一阶段执行清单

## 1. 文档目的

本文档用于把“React 页面层已基本可用之后，回测系统接下来该做什么”落成可执行清单。

目标不是重复设计稿，而是补充：

- 当前仓库已经完成到什么程度
- 下一阶段的优先级顺序
- 每一步的最小落地范围
- 每一步的完成定义

## 2. 当前判断

截至当前版本，以下能力已经闭环：

- 数据集导入
- 单次 EMA 回测
- run 结果持久化
- API 读取 run / overview / parameter readmodel
- React 页面查看执行台、运行总览、单次分析、参数实验

当前系统最明显的短板已经不在“能不能跑起来”，而在研究结论如何沉淀、复用和治理：

1. Research Note 已能记录 run / 批次 / 参数组级结论，并开始升级为显式决策状态流
2. 参数实验已支持批次、杠杆维度、回撤评分和自动推荐，评分规则已抽到独立模块
3. IS/OOS 与回撤已进入 run / parameter readmodel 和批次评分；无 OOS 数据不再允许进入稳健候选
4. 任务系统已经持久化，但执行方式仍是进程内后台线程，缺少更稳的本地异步执行治理
5. 大 workspace 下总览和参数实验仍有全量读模型带来的性能压力
6. 策略入口仍偏 EMA 专用，扩第二个策略前应先把研究闭环收口

## 3. 执行顺序

### P0：参数实验任务化

目标：

让参数实验从“只读汇总页”变成“可提交、可执行、可追踪”的系统能力。

最小范围：

- 增加参数实验任务对象
- 支持 `grid search`
- 支持 `random search`
- 产出实验任务记录和子 run 列表
- API 支持提交实验和查询实验状态
- 参数实验页支持查看实验执行状态

完成定义：

- 用户可以从页面提交一次参数实验
- 一次实验可以生成多条 run
- 实验执行结果可被重新读取，不依赖页面内存态

### P0：任务中心持久化

目标：

把当前临时的同步任务执行，推进为可治理的任务中心。

最小范围：

- 增加 `TaskRepository`
- 持久化任务记录
- 提供任务列表接口
- 提供任务详情接口
- 单次回测先接入任务持久化

完成定义：

- 任意一次单次回测执行后，都能在任务列表里查到
- 任务失败原因可以重新查看
- 后续参数实验任务可以复用同一套任务中心

### P1：研究结论沉淀

目标：

让系统不只保存 run，还能保存研究者的判断和结论。

最小范围：

- `ResearchNote`
- run 备注
- run 标签
- 基准 run / 候选 run 标记

完成定义：

- 同一批实验的分析结论可以被保存和回看

### P1：IS/OOS 研究页补齐

目标：

让 `ValidationSplit` 真正服务研究，而不仅存在于对象模型和执行层。

最小范围：

- 单次分析显示 IS / OOS 对照
- 关键指标按 IS / OOS 分开呈现
- benchmark / baseline 对照
- 参数实验支持按 OOS 表现筛选

完成定义：

- 用户能直接看到样本内外表现差异，而不需要手工推断

### P1：策略注册机制

目标：

把当前偏 EMA 的运行入口改造成可扩展的策略入口。

最小范围：

- `StrategyRegistry`
- 策略参数 schema
- API 支持通用策略入口
- React 表单按策略定义渲染

完成定义：

- 接入第二个策略时，不需要复制 EMA 专用流程

## 4. 当前不优先做的事项

以下能力暂不应抢占优先级：

- stop loss / take profit / limit order
- 多用户 / 登录 / 权限
- 更复杂 benchmark
- 存储层大改造
- 实盘交易相关能力

原因：

这些能力会显著扩大边界，但不直接改善当前“研究效率”和“研究闭环”。

## 5. 当前轮次执行策略

本轮先收口研究可信度和决策闭环，不改回测核心策略，不引入 ATR 策略 v2。

本轮范围：

- Phase 1：IS/OOS 评分硬化
- Phase 1 文档同步
- Research Note 决策状态机最小切片

本轮明确不做：

- 不修改回测核心策略
- 不引入 ATR / stop loss / take profit 策略 v2
- 不引入新的搜索器
- 不做多用户 / 权限

## 6. 验收方式

本轮完成后，至少满足：

1. `high_return_candidates` 必须有正 OOS 收益和足够 OOS 交易数
2. `stable/robust_candidates` 必须有 OOS 数据，且 IS/OOS 都为正
3. `is_oos_gap` 超阈值不能进入稳健候选
4. 无 OOS 数据只能进入 `exploratory_candidates`
5. `excluded_combinations` 优先级高于推荐候选
6. Research Note 支持显式 `decision_status`
7. 不改变现有单次回测结果语义

## 7. 当前已完成

截至当前轮次，已经完成：

- 单次回测任务记录持久化
- `GET /api/tasks`
- `GET /api/tasks/<task_id>`
- 参数实验元数据仓储
- 参数实验任务工作流最小后端切片
- `POST /api/parameter-experiments`
- `GET /api/parameter-experiments`
- `GET /api/parameter-experiments/<experiment_id>`
- 参数实验提交后以后台线程方式执行，并通过任务状态查询结果
- `ExperimentBatch` 多快照批量实验
- `POST /api/parameter-experiment-batches`
- `GET /api/parameter-experiment-batches`
- `GET /api/parameter-experiment-batches/<batch_id>`
- 单次分析页已显示样本内 / 样本外摘要
- 参数实验批次与单实验结果已增加样本外收益、样本外超额等研究字段
- `ResearchNote` 第一版已落盘
- `POST /api/research-notes`
- `GET /api/research-notes`
- 单次分析页已支持 run 备注、标签与候选标记
- 批次评分已抽出到 [batch_scoring.py](../src/crypto_backtest_workbench/app/batch_scoring.py)
- 参数实验批次聚合主键已扩展为 `fast_period + slow_period + leverage`
- 批次评分已接入 `avg_max_drawdown`、`worst_max_drawdown`、`return_over_drawdown`
- 批次评分已接入 `is_oos_gap`、`min_oos_trade_count`
- `high_return_candidates` 与 `excluded_combinations` 保持互斥
- `stable/robust_candidates` 在无 OOS 数据时不再命中
- 无 OOS 但 IS 表现为正的组合进入 `exploratory_candidates`
- Research Note 已支持 `decision_status`、`decision_reason`、`confidence_score`、`linked_batch_id`、`linked_parameter_group`
- 参数实验页已支持按批次 / 参数组决策状态筛选
- 推荐卡默认不再展示最新人工状态为 `rejected` / `archived` 的参数组
- 参数实验页已增加“人工关注参数组”，集中展示最新状态为 `approved` / `observing` 的参数组
- `GET /api/research-notes` 已支持按 `decision_status`、`label`、`linked_batch_id`、`linked_parameter_group` 查询
- 参数实验页已增加“研究决策台账”，可按状态、标签、对象类型、关联批次和关联参数组复盘人工记录
- 批次 Run 表已继承展示所属参数组的最新人工决策状态

当前实现仍然刻意收敛在以下边界内：

- 仅支持 EMA 参数实验
- 主 `run` 结果口径仍保持样本内 IS，不改现有执行语义
- 参数实验执行仍使用本地进程内 worker，不引入外部队列
- IS/OOS 已进入候选推荐硬约束，但策略结构本身仍是 EMA

## 8. 下一步

下一步优先做：

1. 完成 Research Note 决策状态机的前端筛选、展示和测试收口
2. 把 Research Note 的状态语义继续用于推荐卡和参数组表，沉淀“候选 / 观察 / 通过 / 拒绝 / 归档”的研究路径
3. 把总览和参数实验筛选继续下推到服务端查询参数，减轻大 workspace 下的前端过滤压力
4. 在研究闭环补齐后，再考虑更稳的本地异步执行器
5. 最后再推进 `StrategyRegistry` 或策略 v2，避免在研究语义未稳定前过早扩张策略空间

补充：

- 策略 v2 的评审后实施规格见 [EMA Pullback ATR v2 策略设计](./ema-pullback-atr-v2-design.md)

## 9. 多快照批量实验与自动评估

### 9.1 背景

当前参数实验已经具备：

- 单快照提交
- 后台执行
- 子 run 结果查看

但研究者当前仍需要手工切换快照、反复提交实验，再自己判断哪些结果更好。

这会带来两个问题：

1. 多周期 / 多快照研究成本高
2. 页面能展示结果，但还不能稳定给出“哪些更值得看”的候选集合

### 9.2 设计边界

本轮不改变以下既有语义：

- `ParameterExperiment` 仍保持单实验结果口径
- 仍然只支持 EMA 参数实验
- 仍然使用现有本地任务执行方式
- 不引入新的执行语义，不改回测内核撮合与账户规则

本轮新增的只是一个上层协调对象：

- `ExperimentBatch`

其职责是：

- 接收一次多快照选择
- fan-out 为多个已有 `ParameterExperiment`
- 汇总多个实验的结果
- 生成批次级推荐结论

### 9.3 最小落地范围

后端：

- 新增批次对象与仓储
- 新增批次提交 / 列表 / 详情 API
- 支持一次提交多个 `DatasetSnapshot`
- 每个快照仍然生成一个独立 `ParameterExperiment`
- 批次详情返回实验列表、子 run 汇总和推荐结果

前端：

- 参数实验页支持多选数据快照发起实验
- 新增“实验批次”视角
- 新增批次结果汇总表
- 新增推荐候选区

自动评估：

- 第一版采用规则驱动
- 不直接输出“唯一最优参数”
- 输出三类结果：
  - 稳健候选
  - 高收益候选
  - 需排除组合

### 9.4 推荐规则第一版

第一版推荐规则至少考虑：

- 自动稳健候选：
  - 覆盖快照数 `>= 2`
  - 正收益占比 `>= 60%`
  - 平均收益率 `> 0`
  - 平均超额收益 `> 0`
  - 平均最大回撤 `<= 35%`
  - 最少交易数 `>= 3`
  - 相邻参数稳定度 `>= 50%` 且至少有 `1` 个稳定邻居
  - 若存在样本外数据，则平均样本外收益 `> 0`、平均样本外超额 `> 0`、样本外正收益占比 `>= 50%`
- 自动高收益候选：
  - 最佳收益率 `> 0`
  - 平均收益率 `> 0`
  - 未命中自动排除
  - 但尚未达到稳健候选标准
- 自动排除：
  - 平均收益率 `<= 0`，或
  - 正收益占比 `= 0`，或
  - 最差最大回撤 `>= 80%`，或
  - 存在样本外数据且样本外正收益占比 `= 0`

说明：

- 推荐规则的目标是帮助缩小研究范围
- 不是替代人工复盘
- 相邻参数稳定度定义为：在本次搜索网格中，当前 `fast/slow/leverage` 组合相邻参数里，仍然保持正收益与正样本外表现的邻居占比
- 批次结果额外给出：
  - `score`：偏综合表现，综合收益、超额、样本外表现、回撤约束与置信度
  - `confidence`：偏稳定性，综合覆盖快照数、正收益占比、样本外正收益、最少交易数与邻域稳定度
  - `avg_max_drawdown` / `worst_max_drawdown`：参数组风险维度
  - `return_over_drawdown`：收益回撤比
- 最终仍应跳转单次分析确认资金曲线、交易结构和 IS / OOS 表现

### 9.5 验收标准

本轮完成后，至少满足：

1. 用户可多选数据快照发起参数实验
2. 系统会自动拆成多个单快照 `ParameterExperiment`
3. 页面可查看批次级汇总结果
4. 页面可给出规则驱动的推荐候选
5. 不改变现有单 run 与单 experiment 的执行语义

## 10. 动态资金开仓调整

### 9.1 背景

现有实现里：

- `qty` 由用户直接输入
- `leverage` 只影响保证金占用与可开仓检查
- 因此杠杆不会直接改变实际开仓规模

这会导致两个问题：

- 用户感知上，“杠杆倍数”不像真实仓位控制参数
- 盈利或亏损后的动态资金，不能自然传导到下一笔开仓规模

### 9.2 本轮调整边界

本轮只引入新的仓位策略，不重写回测内核对象模型：

- 保留 `SignalIntent.qty_policy_ref`
- 保留执行层内部 `qty` 作为最终成交数量
- 新增默认仓位策略 `percent_of_cash`
- React 页面去掉手填“下单数量”，改为“资金使用比例 (%)”
- 旧的固定数量输入在 API / CLI 层继续兼容，不强制立即迁移

### 9.3 新语义

当 `qty_policy_ref = percent_of_cash` 时：

- 开仓基于当前 `available_cash` 动态计算
- `leverage` 直接参与名义仓位放大
- `qty` 在执行时派生，不再由用户手工输入

计算口径：

- `allocated_cash = available_cash * cash_allocation_pct / 100`
- `notional = allocated_cash / (1 / leverage + fee_rate)`
- `qty = notional / entry_price`

该公式的目的，是让“资金使用比例”同时覆盖：

- 保证金占用
- 开仓手续费预留

避免 100% 资金使用时，因为手续费导致名义上能开、实际被拒。

### 9.4 明确不做

本轮仍然不做：

- 爆仓
- 强平
- 维持保证金联动
- 多仓位并发账户模型
- 更复杂风控 sizing

### 9.5 验收标准

本轮完成后，至少满足：

1. React 单次回测表单不再要求输入固定数量
2. `leverage` 会直接影响动态开仓规模
3. 盈亏会影响下一笔开仓 `qty`
4. 旧的固定数量调用仍然可执行
5. 设计稿与代码实现口径一致
