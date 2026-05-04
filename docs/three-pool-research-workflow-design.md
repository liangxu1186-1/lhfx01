# 三池研究流程重构设计

## 1. 文档目标

本文档定义参数实验研究界面的下一版重构方案。

目标是把当前偏工程对象的页面：

```text
批次 / 实验 / Run / 参数组 / 台账 / 邻域
```

重构为更贴近实际研究动作的三池流程：

```text
初筛池 -> 研究池 -> 稳定池
```

本文档重点定义：

- 三个池子的职责
- 每个池子的对象粒度
- 每个池子的字段与操作
- Run、参数组、邻域、风险矩阵如何进入流程
- 自动评分与标签规则
- 前端页面组织方式
- API/readmodel 落地边界
- 分阶段实施清单

本文档不改变：

- `ema_crossover v1` 策略逻辑
- `ema_pullback_atr_v2` 策略逻辑
- 执行层成交、SL/TP、gap open、同 bar 优先级语义
- 现有回测任务、参数实验任务的执行能力
- 现有 `ResearchNote` 作为人工结论记录的基础能力

## 2. 背景与问题

当前系统已经具备较多能力：

- 发起单次 run
- 发起参数实验
- 参数实验批次
- 推荐研究 run
- 参数组排行榜
- 趋势周期邻域
- 风险/杠杆对比
- 冻结追踪
- 单次分析
- 决策台账

问题不在功能缺失，而在信息架构偏复杂。

当前页面要求用户理解：

- batch 是什么
- experiment 是什么
- run 属于哪个 batch
- 参数组聚合来自哪里
- 决策台账怎么和 run/参数组关联
- 邻域结果在哪里看
- 冻结对象和研究对象的关系是什么

这些是系统内部结构，不是用户的研究流程。

用户真正想做的是：

```text
1. 我跑了一批实验，哪些值得看？
2. 我挑出一些候选，怎么深入验证？
3. 哪些组合已经足够稳定，可以进入后续操作？
```

因此下一版应把页面中心从“数据来源”改为“研究阶段”。

## 3. 设计结论

页面主流程固定为三个池子：

```text
发起实验
  -> 初筛池
  -> 研究池
  -> 稳定池
```

其中：

- 初筛池：自动聚合所有已落盘 run，用评分和标签快速发现候选。
- 研究池：人工挑入的候选组合，用邻域、风险矩阵和单次分析深入验证。
- 稳定池：已经通过验证的候选配置，作为后续复测、导出、模拟或实盘候选的入口。

批次、实验、validation、dataset snapshot 等工程信息保留，但默认隐藏到详情和高级信息里。

## 4. 核心原则

### 4.1 用户不再默认关心 batch

batch 只是任务容器，不是研究主对象。

初筛池应直接展示所有 run 的综合结果，默认不按 batch 切页。

### 4.2 Run 是初筛证据，不是最终结论

Run 可以进入初筛池，也可以被加入研究池。

但最终稳定池不应只是“某一条 run”，而应是：

```text
策略 + 标的 + 周期 + 入场结构 + 风险配置
```

### 4.3 研究池是核心工作区

研究池不是收藏夹。

进入研究池的对象必须能继续操作：

- 看单次分析
- 看趋势周期邻域
- 跑趋势周期邻域
- 跑风险/杠杆矩阵
- 记录研究结论
- 进入稳定池
- 归档/拒绝

### 4.4 稳定池只放通过验证的组合

稳定池不追求数量。

稳定池对象必须至少说明：

- 为什么进入稳定池
- 哪些数据支持
- 哪些风险仍然存在
- 推荐风险参数是什么
- 后续应做什么

### 4.5 策略语义不因研究流程改变

三池流程只改变研究层和 UI 编排。

不引入动态止盈/止损，不改变 v2 初始 SL/TP，不改变执行层成交逻辑。

## 5. 三个池子定义

## 5.1 池子 1：初筛池

### 5.1.1 目标

回答：

```text
刚跑出这么多 run，哪些值得看？
```

### 5.1.2 对象粒度

初筛池的主对象是 `RunCandidate`。

每一行对应一条已落盘 run。

### 5.1.3 数据来源

来自所有已完成 run，不按 batch 强制分组。

默认包含：

- 单次 run
- 参数实验产生的 run
- 邻域实验产生的 run
- 风险矩阵实验产生的 run

可以通过筛选控制来源，但主流程不要求用户先选择 batch。

### 5.1.4 主表字段

建议字段：

- `Run`
- `策略`
- `标的`
- `周期`
- `参数摘要`
- `评分`
- `标签`
- `收益率`
- `OOS 收益`
- `IS/OOS Gap`
- `最大回撤`
- `PF`
- `交易数`
- `OOS 交易数`
- `杠杆`
- `risk`
- `资金比例`
- `创建时间`

默认排序：

```text
评分 desc -> OOS 收益 desc -> PF desc -> 最大回撤 asc
```

### 5.1.5 自动标签

初筛池应自动给 run 打标签。

推荐标签：

- `值得研究`
- `高收益`
- `OOS 强`
- `Gap 小`
- `Gap 大`
- `回撤过大`
- `PF 偏低`
- `样本不足`
- `风险偏激`
- `邻域待跑`
- `建议排除`

标签只用于初筛，不等同于最终结论。

### 5.1.6 评分原则

评分应强调：

- OOS 收益
- OOS 超额收益
- PF
- 交易数
- 回撤惩罚
- Gap 惩罚
- 高 risk / 高杠杆惩罚

示意：

```text
score =
  OOS return contribution
  + OOS excess contribution
  + PF contribution
  + sample contribution
  - drawdown penalty
  - gap penalty
  - high risk penalty
```

评分不负责最终决策，只负责排序和推荐。

### 5.1.7 操作

初筛池每行保留少量操作：

- `加入研究池`
- `打开分析`
- `看邻域`
- `跑邻域`
- `排除`

不再把 `删除 run` 放在主操作位。

删除可以放进更多操作或详情页。

### 5.1.8 进入/退出

进入初筛池：

- run 落盘且状态成功。

退出初筛池：

- 不物理退出。
- 如果用户排除，仍可通过筛选隐藏。

## 5.2 池子 2：研究池

### 5.2.1 目标

回答：

```text
这些候选是否真的稳定？
```

### 5.2.2 对象粒度

研究池的主对象不应只是单条 run。

建议使用 `ResearchCandidate`：

```text
ResearchCandidate =
  strategy_name
  symbol
  timeframe
  validation regime
  entry parameter structure
  optional risk profile
```

对 v2，入场结构至少包括：

- `trend_fast_period`
- `trend_slow_period`
- `entry_ema_period`
- `atr_period`
- `atr_entry_tolerance`
- `atr_stop_mult`
- `risk_reward_ratio`

风险 profile 包括：

- `qty_policy_ref`
- `risk_pct_per_trade`
- `cash_allocation_pct`
- `leverage`

研究池可以从 run 创建，但需要把 run 映射成候选组合。

### 5.2.3 为什么研究池要升维

单条 run 可能只是偶然好。

研究池应关注：

- 同一入场结构在不同风险参数下是否仍有效
- 趋势快慢周期邻域是否稳定
- 降低 risk 后是否仍赚钱
- 不同杠杆下回撤是否可控
- OOS 是否仍有正收益

### 5.2.4 主表字段

建议字段：

- `研究对象`
- `入场结构`
- `风险配置`
- `状态`
- `综合结论`
- `代表 Run`
- `代表 Run 评分`
- `OOS`
- `Gap`
- `回撤`
- `PF`
- `交易数`
- `邻域状态`
- `风险矩阵状态`
- `最近更新`

### 5.2.5 状态

研究池状态建议：

- `待研究`
- `邻域待跑`
- `风险待跑`
- `继续观察`
- `降风险复测`
- `可入稳定池`
- `拒绝`
- `归档`

这些状态可以继续复用 `ResearchNote.decision_status`，但前端需要映射成更直观的研究状态。

### 5.2.6 操作

研究池每行操作：

- `打开研究`
- `打开代表 Run`
- `看趋势邻域`
- `跑趋势邻域`
- `看风险矩阵`
- `跑风险矩阵`
- `记录结论`
- `加入稳定池`
- `归档`

### 5.2.7 趋势邻域

趋势邻域用于回答：

```text
当前 trend_fast / trend_slow 是否只是单点偶然有效？
```

固定：

- strategy
- symbol
- timeframe
- validation
- entry_ema_period
- atr_period
- atr_entry_tolerance
- atr_stop_mult
- risk_reward_ratio
- qty_policy_ref
- risk_pct_per_trade
- cash_allocation_pct
- leverage

变化：

- `trend_fast_period`
- `trend_slow_period`

输出：

- 邻居数
- OOS 正比例
- 平均 OOS
- 平均 Gap
- 最差回撤
- 最少交易数
- 平均 PF
- 稳定评分
- 结论：稳定 / 观察 / 不稳定 / 样本不足

### 5.2.8 风险矩阵

风险矩阵用于回答：

```text
这个入场结构在不同 risk / 杠杆 / 资金比例下是否仍有效？
```

固定：

- strategy
- symbol
- timeframe
- validation
- 入场结构参数

变化：

- `risk_pct_per_trade`
- `cash_allocation_pct`
- `leverage`
- 可选 `qty_policy_ref`

推荐第一版矩阵：

```text
risk_pct_per_trade: 1%, 3%, 5%, 10%
cash_allocation_pct: 30%, 50%, 95%
leverage: 1, 3, 5, 10
```

第一版可以允许用户从 UI 选择候选列表。

输出：

- 每组风险参数的收益
- OOS
- Gap
- 回撤
- PF
- 最大单笔亏损
- 交易数
- 是否比原始 run 更可控

### 5.2.9 加入研究池

从初筛池点击 `加入研究池` 时：

- 创建或更新一条研究记录
- 记录来源 run
- 保存当时参数快照
- 状态设为 `待研究`
- 标签包含 `research_pool`

如果相同研究候选已存在：

- 不重复创建
- 把新的 run 作为证据追加
- 更新最近观察时间

### 5.2.10 退出研究池

退出方式：

- `拒绝`
- `归档`
- `加入稳定池`

退出不删除历史记录。

## 5.3 池子 3：稳定池

### 5.3.1 目标

回答：

```text
哪些组合已经通过验证，可以作为后续候选配置？
```

### 5.3.2 对象粒度

稳定池对象是 `StableCandidate`：

```text
StableCandidate =
  strategy
  symbol
  timeframe
  entry structure
  chosen risk profile
  validation summary
```

稳定池必须包含风险配置。

只有入场结构、不包含 risk / leverage 的组合，不应进入稳定池。

### 5.3.3 准入建议

第一版建议人工确认，但系统给准入提示。

建议门槛：

- OOS 收益 > 0
- PF >= 1.1
- 交易数足够
- 最大回撤在可接受范围
- 邻域不是明显单点
- 降风险后仍有正收益
- 最大单笔亏损没有明显失控

对不同周期可有不同交易数要求：

```text
1H: 总交易数 >= 100
4H: 总交易数 >= 50
1D: 总交易数 >= 20
```

### 5.3.4 主表字段

建议字段：

- `稳定组合`
- `策略`
- `标的`
- `周期`
- `入场结构`
- `风险配置`
- `状态`
- `最终建议`
- `代表收益`
- `OOS`
- `最大回撤`
- `PF`
- `最大单笔亏损`
- `邻域结论`
- `风险矩阵结论`
- `最近复测`

### 5.3.5 操作

稳定池操作：

- `打开详情`
- `查看证据`
- `重新复测`
- `扩展标的验证`
- `扩展周期验证`
- `导出配置`
- `降风险版本`
- `归档`

第一版可以先实现：

- 打开详情
- 查看证据
- 重新复测
- 导出配置
- 归档

## 6. 页面信息架构

建议参数实验页改成：

```text
参数研究工作台

Tab 1: 发起实验
Tab 2: 初筛池
Tab 3: 研究池
Tab 4: 稳定池
```

高级入口放到右上角或折叠区：

- 批次明细
- 单实验明细
- 决策台账
- 参数组排行榜
- 敏感度

这些能力保留，但不再占主流程。

## 7. Tab 设计

## 7.1 发起实验

保留现有发起实验能力，但表单也应简化。

默认只展示：

- 数据快照
- 策略
- validation 切分
- 核心参数候选
- 仓位模式
- risk / cash / leverage
- 初始资金
- 手续费 / 滑点

高级参数折叠。

提交后引导：

```text
实验提交成功，完成后结果会进入初筛池。
```

不要求用户立刻进入 batch 页面。

## 7.2 初筛池

默认视图：

- 汇总所有 run
- 自动评分
- 自动标签
- 可筛选策略、标的、周期、标签、评分、PF、回撤、OOS

主 CTA：

- `加入研究池`

辅助操作：

- 打开分析
- 看邻域
- 跑邻域
- 排除

## 7.3 研究池

默认视图：

- 当前人工选择的研究候选
- 展示每个候选的验证进度

进度示例：

```text
邻域：已跑 / 未跑 / 样本不足
风险矩阵：已跑 / 未跑
结论：观察 / 降风险复测 / 可入稳定池
```

主 CTA：

- `跑风险矩阵`
- `加入稳定池`

辅助操作：

- 看代表 Run
- 看趋势邻域
- 跑趋势邻域
- 记录结论
- 归档

## 7.4 稳定池

默认视图：

- 已通过验证的组合
- 只展示少量高价值字段

主 CTA：

- `导出配置`
- `重新复测`

辅助操作：

- 查看证据
- 降风险版本
- 归档

## 8. 数据模型建议

第一版可以复用现有 `ResearchNote`，不急着新增数据库表。

### 8.1 用标签表达池子

建议标签：

- `screening_pool_excluded`
- `research_pool`
- `stable_pool`
- `risk_review`
- `neighborhood_review`
- `risk_matrix_review`

### 8.2 用状态表达阶段

可以继续使用：

- `candidate`
- `observing`
- `approved`
- `rejected`
- `archived`

前端映射：

```text
candidate -> 待研究
observing -> 观察中
approved -> 通过
rejected -> 拒绝
archived -> 归档
```

### 8.3 target_type 建议

第一版：

- 初筛池操作对象：`run`
- 研究池操作对象：`research_candidate`
- 稳定池操作对象：`stable_candidate`

如果暂不新增后端类型，也可以先用：

- `run`
- `parameter_group`

但文档建议尽快引入更贴近流程的 target type，避免长期把研究对象伪装成 run。

## 9. Readmodel 设计

新增或重构一个研究流程 readmodel：

```text
/api/research-workflow
```

返回：

```json
{
  "screening_pool": {
    "runs": []
  },
  "research_pool": {
    "candidates": []
  },
  "stable_pool": {
    "candidates": []
  }
}
```

### 9.1 ScreeningRunView

字段：

- run 基本信息
- 参数摘要
- metrics
- validation metrics
- score
- auto_labels
- manual_labels
- pool_status
- neighborhood_status

### 9.2 ResearchCandidateView

字段：

- candidate_id
- source_run_ids
- strategy/symbol/timeframe
- entry_structure
- risk_profile
- representative_run
- latest_note
- neighborhood_summary
- risk_matrix_summary
- recommendation
- status

### 9.3 StableCandidateView

字段：

- stable_candidate_id
- strategy/symbol/timeframe
- entry_structure
- chosen_risk_profile
- evidence_run_ids
- validation_summary
- neighborhood_summary
- risk_matrix_summary
- final_recommendation
- status

## 10. API 设计

第一版建议新增流程 API。

### 10.1 获取研究工作台

```http
GET /api/research-workflow
```

筛选参数：

- strategy_name
- symbol
- timeframe
- pool
- label
- status

### 10.2 加入研究池

```http
POST /api/research-pool
```

请求：

```json
{
  "source_run_id": "run-xxx",
  "note": "加入研究池原因"
}
```

行为：

- 从 run 解析研究候选 key
- 如果候选不存在则创建
- 追加 source run
- 创建 ResearchNote

### 10.3 加入稳定池

```http
POST /api/stable-pool
```

请求：

```json
{
  "research_candidate_id": "candidate-xxx",
  "chosen_run_id": "run-xxx",
  "decision_reason": "邻域和风险矩阵通过",
  "risk_profile": {}
}
```

### 10.4 跑风险矩阵

```http
POST /api/research-candidates/{candidate_id}/risk-matrix
```

请求：

```json
{
  "risk_pct_per_trade_candidates": [0.01, 0.03, 0.05],
  "cash_allocation_pct_candidates": [30, 50, 95],
  "leverage_candidates": [1, 3, 5]
}
```

行为：

- 固定入场结构
- 扩展风险参数
- 发起参数实验 batch
- 结果回流研究候选

### 10.5 跑趋势邻域

可以复用现有 run neighborhood 能力，但入口应支持 candidate：

```http
POST /api/research-candidates/{candidate_id}/trend-neighborhood
```

第一版也可以由前端找到代表 run 后调用现有 run 入口。

## 11. 自动推荐规则

## 11.1 初筛池推荐

初筛池推荐的是 run。

推荐条件示例：

- OOS > 0
- PF >= 1.05
- 交易数达标
- 回撤低于阈值
- Gap 不过大

### 11.2 研究池推荐

研究池推荐的是候选组合。

推荐应基于：

- 代表 run
- 趋势邻域
- 风险矩阵
- 人工备注

### 11.3 稳定池推荐

稳定池不自动进入。

系统只给提示：

- `建议进入稳定池`
- `建议降风险后再评估`
- `建议归档`

最终由用户确认。

## 12. 第一版实施计划

## Phase 1：前端主流程重排

目标：

- 参数实验页面改成 4 个主 Tab：
  - 发起实验
  - 初筛池
  - 研究池
  - 稳定池
- batch / experiment / decisions / sensitivity 放入高级区
- 初筛池直接展示所有 run
- 初筛池支持加入研究池
- 研究池显示已加入对象
- 稳定池显示已通过对象

可复用：

- 现有 `parameter_lab.rows`
- 现有 `research_notes`
- 现有冻结追踪逻辑

## Phase 2：研究池候选建模

目标：

- 从 run 生成 `research_candidate_id`
- 同一入场结构合并为一个研究候选
- 研究池不再只是 run 列表
- 候选可展示 source runs

## Phase 3：风险矩阵

目标：

- 在研究池中对候选跑风险矩阵
- 固定入场结构
- 扩展 risk/cash/leverage
- 结果回流研究池

## Phase 4：稳定池

目标：

- 支持从研究池加入稳定池
- 保存 chosen risk profile
- 展示证据摘要
- 支持导出配置

## Phase 5：后台 readmodel/API 收敛

目标：

- 新增 `/api/research-workflow`
- 减少前端自己拼装状态
- 后端统一计算池子、评分、标签、推荐

## 13. 第一版不做的事

第一版不做：

- 自动实盘跟踪
- 动态止盈/止损
- 自动定时复测
- 自动把稳定池推到实盘
- 新增复杂权限或多用户协作
- 删除现有 batch/experiment 页面能力

这些可以后续作为扩展。

## 14. 验收标准

第一版完成后，用户应能完成以下闭环：

1. 发起实验。
2. 不看 batch，直接在初筛池看到所有 run 的评分和标签。
3. 从初筛池把候选加入研究池。
4. 在研究池对候选看/跑趋势邻域。
5. 在研究池对候选跑风险矩阵。
6. 根据邻域和风险矩阵结果记录结论。
7. 把通过的组合加入稳定池。
8. 在稳定池看到最终候选配置和证据摘要。

## 15. 与现有功能映射

| 现有功能 | 新流程位置 |
| --- | --- |
| 发起参数实验 | 发起实验 |
| 实验 Run 结果 | 初筛池 |
| 推荐研究 Run | 初筛池推荐标签 |
| 冻结追踪 | 加入研究池 |
| 参数组排行榜 | 研究池候选聚合 |
| 看邻域 / 跑邻域 | 研究池操作 |
| 风险 / 杠杆对比 | 研究池风险矩阵 |
| 决策台账 | 高级区 / 详情记录 |
| 单次分析 | Run 详情 |
| 稳健候选 | 稳定池候选 |

## 16. 结论

三池流程更符合实际研究动作。

下一步不应继续在旧页面上堆更多入口，而应把能力重新组织为：

```text
初筛池：发现
研究池：验证
稳定池：沉淀
```

这样既保留现有回测、邻域、风险比较和研究备注能力，又能让用户从“看不完结果”转向“推进候选状态”。
