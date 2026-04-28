# 加密量化回测研究工作台 v1 实施设计稿

## 1. 文档定位

本文档是 **v1 实施设计稿**，不是方向性评审稿。

目标是为后续工程实现和外部 AI 评审提供统一依据，重点回答以下问题：

- v1 的边界是否足够收敛
- 数据、执行、计量语义是否闭合
- 页面是否能支撑研究闭环
- 对象模型和存储是否足够支撑后续扩展
- 哪些能力必须纳入 v1，哪些必须后置

本文档默认面向：

- 单机研究使用场景
- Python 技术栈
- 加密货币量化回测
- 页面化研究工作台

## 2. v1 定义

### 2.1 一句话定义

**v1 = 一个可复现、可追踪、可复盘、支持基础参数实验与样本内外对照的单机加密回测研究工作台。**

### 2.2 v1 要解决的问题

让研究者可以稳定完成以下闭环：

```text
选择数据集与标的
-> 选择策略
-> 调整参数
-> 提交回测任务
-> 生成可复现的 run 结果
-> 查看资金曲线、回撤、交易明细
-> 对比 benchmark 与 IS/OOS
-> 保存实验结果与研究结论
```

### 2.2.1 当前实现状态补充

截至当前实现，v1 研究闭环已经落地到以下层级：

- React 页面已覆盖执行台、运行总览、单次分析和参数实验
- 参数实验支持多快照批次、`grid/random search`、`fast/slow/leverage` 组合维度
- run / parameter readmodel 已透出 IS/OOS、benchmark、`max_drawdown`
- 批次聚合结果已按 `fast_period + slow_period + leverage` 聚合
- 批次评分已包含收益、样本外表现、回撤、收益回撤比、置信度和邻域稳定度
- Research Note 已从 run 级备注扩展到批次和参数组级研究决策

因此后续工程重点从“页面替换和基础执行”转向：

- 研究决策如何参与筛选和复盘
- 批次评分规则如何模块化、可测试和可解释
- 大 workspace 下读模型和筛选如何下推到服务端
- 任务执行如何从进程内后台线程演进为更稳的本地执行器

### 2.3 v1 不解决的问题

以下能力明确后置，不进入 v1：

- 实盘交易
- 高频撮合
- 订单簿级回测
- DEX / 链上执行
- 多用户与权限系统
- 多策略资金竞争
- 复杂组合优化
- Regime Analysis 主系统
- 复杂 limit/stop/trailing 订单语义
- liquidation/funding 的高精度模拟

## 3. v1 范围

### 3.1 支持范围

v1 支持：

- 单机本地运行
- 单交易所
- 单市场类型
- 单 timeframe
- 单策略单 run
- 单 symbol 回测
- 多 symbol 批量独立回测
- long / short / both
- signal-driven market open
- signal-driven market close
- signal-driven reverse
- 手续费模型
- 简单滑点模型
- benchmark 对照
- IS/OOS 单次切分对照
- 手动参数运行
- grid search
- random search
- 页面化结果查看

### 3.2 明确不支持

v1 明确不支持：

- stop loss
- take profit
- trailing stop
- partial fill 精细模拟
- same-bar 复杂成交推演
- limit order 成交推演
- 复杂资金分配和组合层风控

说明：

为避免 OHLC 内部路径歧义，**Phase 1 不支持任何保护性退出语义**。相关能力放入后续版本，并要求单独补充执行语义规范。

## 4. 核心原则

### 4.1 原则 1：先做研究工作台，不做交易平台

v1 只服务研究闭环，不承担实盘执行职责。

### 4.2 原则 2：统一数据语义

所有策略、指标、回测结果必须建立在统一数据口径之上。

### 4.3 原则 3：统一执行语义

所有 run 必须共享同一主执行语义，避免结果不可比较。

### 4.4 原则 4：run 必须可复现

任何一次 run 都必须能反查：

- 用了哪份数据
- 用了哪版策略
- 用了哪版执行语义
- 用了哪版指标与参数
- 用了哪版 benchmark 和指标口径

v1 要求每次 `BacktestRun` 都对应一份最小不可缺的 **run manifest**。该 manifest 至少包含：

- `dataset_snapshot_id`
- `strategy_version`
- `engine_version`
- `execution_policy_id`
- `metric_policy_id`
- `validation_split_id`
- `fee_model_version`
- `slippage_model_version`
- `fee_model_params`
- `slippage_model_params`
- `benchmark_config`
- `seed`
- `resolved_config`

上述字段缺一不可，否则该 run 不视为可复现 run。

### 4.5 原则 5：先保证交易级追踪，再扩功能

任何 run 都必须能追到：

- 配置快照
- 信号
- 订单请求
- 成交事件
- 交易记录
- 资金曲线

### 4.6 原则 6：参数实验重稳健性，不重最优值

Parameter Lab 的目标是发现稳健区间，而不是制造参数赌博机。

## 5. 市场与计量边界

### 5.1 v1 固定市场类型

**v1 只支持 linear USDT perpetual。**

不支持现货与其他合约类型混合实现。

### 5.2 v1 固定计量体系

- `qty`：base asset 数量
- `notional`：`qty * fill_price`
- `fee`：以 quote currency 结算
- `pnl`：以 quote currency 结算
- `equity`：以 quote currency 表示
- `leverage`：影响保证金占用与暴露
- `qty` 始终表示最终成交的 base asset 数量
- 当使用 `percent_of_cash` 仓位策略时，`qty` 由 `available_cash`、`leverage` 和成交价动态派生，不再由用户直接输入

### 5.3 仓位与账户规则

v1 默认采用单账户模型：

- 单账户初始资金以 USDT 计
- 单 symbol 单方向持仓
- 同一 symbol 不允许同时持有多空双向仓位
- `reverse` 语义为先平后开
- 是否允许满仓由配置显式控制

v1 账户层至少跟踪以下状态：

- `available_cash`
- `used_margin`
- `maintenance_margin`
- `equity`
- `unrealized_pnl`

### 5.4 可下单约束

v1 不能只做理论成交，还必须检查基础可下单约束。

至少包括：

- 最小下单名义金额检查
- 最小下单数量检查
- 数量精度检查
- 价格精度检查
- 保证金是否足够

不满足约束的请求不得静默成交，必须生成结构化拒单信息。

## 6. 系统总体架构

```text
app/        页面层
jobs/       任务层
engine/     回测内核
storage/    存储与查询层
```

### 6.0 代码结构目标

代码结构必须满足以下目标：

- 分层清晰，不将数据、特征、策略、执行、分析逻辑堆在一起
- 页面层不直接承担重计算
- 参数实验可复用已有数据与特征产物
- 能定位性能瓶颈属于哪一层
- 为后续新增策略和指标保留稳定扩展点

建议目录结构：

```text
app/
  pages/
  components/

jobs/
  task_runner.py
  run_backtest_job.py
  run_experiment_job.py

engine/
  data/
    loaders/
    canonicalizer/
    validators/
  features/
    indicators/
    pipelines/
    cache/
  strategy/
    base.py
    registry.py
    implementations/
  execution/
    order_simulator.py
    fill_engine.py
    fee_model.py
    slippage_model.py
  portfolio/
    account.py
    position.py
    sizing.py
  analytics/
    metrics.py
    reports.py
  experiments/
    grid_search.py
    random_search.py

storage/
  duckdb/
  parquet/
  repositories/

domain/
  models/
    run.py
    dataset.py
    feature_artifact.py
    signal.py
    trade.py
    benchmark.py

configs/
  execution_policies/
  metric_policies/
  benchmark_policies/
```

要求：

- `app/` 只负责展示与交互
- `jobs/` 只负责任务调度和状态更新
- `engine/features/` 统一负责指标和特征计算
- `engine/strategy/` 不直接重算指标
- `engine/execution/` 不关心页面和存储细节
- `storage/` 不承载策略逻辑

### 6.1 `app/`

职责：

- 选择标的
- 选择策略
- 调整参数
- 提交回测任务
- 查询任务状态
- 展示 run / trades / benchmark / IS-OOS 结果

### 6.2 `jobs/`

职责：

- 创建 single run task
- 创建 parameter experiment task
- 管理任务状态
- 调用回测内核
- 将结果写入存储

### 6.3 `engine/`

建议拆分：

- `engine/data/`
- `engine/strategy/`
- `engine/execution/`
- `engine/portfolio/`
- `engine/analytics/`
- `engine/validation/`

### 6.4 `storage/`

职责：

- 保存 run 元信息
- 保存交易、成交、曲线
- 保存实验结果
- 提供查询接口给页面层

### 6.5 性能原则

v1 必须满足以下性能设计原则：

- 相同 `DatasetSnapshot` 不重复拉取
- 相同 `FeatureArtifact` 不重复计算
- 参数实验优先复用只读数据与特征产物
- 页面请求线程不直接执行重计算
- 特征层优先批量化与向量化
- 回测阶段尽量只做信号、执行、分析，不重算基础特征

### 6.6 参数分层原则

为避免无意义重算，参数分为三类：

#### A. Feature Params

会改变指标本身，需要重建 `FeatureArtifact`。

例如：

- `ema_fast`
- `ema_slow`
- `rsi_period`
- `bb_window`
- `atr_period`

#### B. Signal Params

主要影响信号判断，不一定需要重算底层特征。

例如：

- `rsi_threshold`
- `macd_signal_threshold`
- `enable_filter_x`

#### C. Execution / Portfolio Params

只影响执行、仓位和结果统计，不应触发特征重算。

例如：

- `risk_per_trade`
- `leverage`
- `fee/slippage`
- `position_size_mode`

要求：

- 参数变更必须声明触发哪一层重算
- 修改 execution 参数时，不得重复计算 EMA / RSI 等基础特征
- 修改纯展示筛选条件时，不得触发回测任务

## 7. 行情获取与特征计算设计

### 7.1 数据源策略

v1 采用以下数据源策略：

- 历史 K 线主来源：`ccxt` REST
- 实时增量主来源：`ccxt pro` WebSocket
- 指标与特征：本地统一计算

原则：

- 不依赖交易所提供的 EMA / RSI / MACD / 布林带等平台指标
- 原始行情与衍生特征严格分层
- 历史回测优先保证完整性与可复现，不追求全链路实时性

### 7.2 为什么历史数据主走 REST

v1 中历史数据以 REST 为主，原因如下：

- `fetchOHLCV` 适合按 symbol/timeframe/since 分段拉取历史
- REST 更适合做补数、重跑与可复现归档
- WebSocket 更适合实时增量，不适合作为深历史主接口
- 交易所普遍限制单次返回的历史 K 线长度，需要分页或循环拉取

### 7.3 为什么 WebSocket 不作为历史主接口

v1 不将 WebSocket 作为深历史主来源，原因如下：

- `watchOHLCV` / `watchTrades` 基于缓存窗口
- 默认只保留最近一段缓存，不适合任意深度历史回放
- 断线重连、去重、补洞、乱序修复会显著增加复杂度

因此 v1 采用：

- REST 回补历史
- WebSocket 接收最新增量
- 本地存储统一归档

### 7.4 K 线获取方案

#### A. 历史 K 线

优先使用：

- `exchange.fetch_ohlcv(symbol, timeframe, since, limit, params)`

要求：

- 显式传 `since`
- 显式控制分页
- 不依赖交易所默认返回区间
- 按 symbol/timeframe 独立落盘

适用内容：

- 标准 OHLCV
- mark price K 线
- index price K 线

#### B. 实时增量 K 线

可使用：

- `exchange.watch_ohlcv(symbol, timeframe, since, limit, params)`

用途限定为：

- 订阅最近更新
- 维护本地最新窗口
- 在数据采集服务运行期间持续写入最新 bar

不作为：

- 深历史拉取接口
- 唯一数据来源

#### C. 更高质量的实时 K 线

若后续需要更低延迟或更可控的 candle 语义，采用：

- `fetch_trades` / `watch_trades`
- 本地聚合 OHLCV

v1 不强制采用 trade-to-candle 聚合，但设计上必须允许后续切换。

### 7.5 数据获取分层

v1 将市场数据分为三层：

#### Raw Market Data

交易所原始返回数据。

包括：

- raw OHLCV
- raw trades
- funding rate
- mark/index price

#### Canonical Candles

本地标准化后的 K 线。

字段要求：

- UTC
- bar open time
- symbol
- exchange
- market_type
- timeframe
- open/high/low/close/volume
- data_source
- price_type

#### Features

基于 canonical candles 本地计算得到的特征。

包括：

- EMA
- RSI
- MACD
- Bollinger Bands
- ATR
- 其他 rolling / ewm 类特征

### 7.6 指标计算原则

v1 中技术指标必须本地统一计算，不从交易所直接读取平台指标。

原因：

- 平台指标计算口径通常不透明
- 不同交易所之间口径不可比
- warmup、缺失值、EMA 初始化方式可能不同
- 不利于回测复现与策略对比

### 7.7 指标层约束

所有指标计算必须显式记录：

- 输入价格字段，例如 `close` / `hlc3`
- 指标参数
- warmup 长度
- 计算公式版本
- 特征版本号

v1 推荐：

- 使用单一特征计算实现
- 不混用多个技术分析库
- 优先保证口径统一，再考虑性能优化

性能要求：

- 离散参数空间内的常用均线和 rolling 指标应优先批量预计算
- 不允许在 100 个参数组合中重复计算同一列 EMA/RSI
- 特征计算优先使用向量化实现
- 若状态型执行层成为瓶颈，可单独优化，不得回退到整链路重复重算

### 7.8 推荐的数据采集工作流

#### 历史初始化

```text
load markets
-> 按 symbol/timeframe 调用 fetch_ohlcv
-> 循环分页直到覆盖目标区间
-> 写入 raw ohlcv
-> 标准化为 canonical candles
-> 生成 DatasetSnapshot
-> 本地计算 features
-> 生成 feature artifacts
```

#### 增量更新

```text
启动 watcher
-> watch_ohlcv 或 watch_trades
-> 写入本地增量缓存
-> 定期落盘
-> 用 REST 对最近窗口补洞与校正
-> 刷新 DatasetSnapshot / Feature artifacts
```

### 7.9 v1 推荐选择

如果目标是尽快做出可信回测闭环，v1 推荐：

- K 线：直接使用交易所 OHLCV
- 指标：本地计算
- 历史：REST
- 增量：可选 WebSocket

如果后续对分钟级实时性要求更高，再升级为：

- trades 流
- 本地聚合 candles
- 本地统一计算全部二级统计数据

## 8. 用户核心流程

### 8.1 单次回测流程

```text
页面选择 symbol
-> 页面选择 strategy
-> 页面调整参数
-> 选择 validation split 与 benchmark
-> 提交 single run task
-> jobs 调用 engine 执行
-> storage 保存结果
-> 页面查看 Run Detail
```

### 8.2 参数实验流程

```text
页面选择 strategy
-> 定义参数空间
-> 选择 dataset bundle / validation / benchmark
-> 提交 parameter experiment task
-> jobs 逐个生成 run
-> storage 保存 experiment 与 result
-> 页面在 Parameter Lab 查看结果分布与稳健性
```

当研究者希望一次面向多个 `DatasetSnapshot` 或多个周期同时发起实验时，
v1 不要求把这些快照直接塞进同一个 `ParameterExperiment`。

推荐工程落地方式是：

```text
页面多选 DatasetSnapshot
-> 创建一个 ExperimentBatch
-> batch fan-out 为多个单快照 ParameterExperiment
-> 每个 experiment 各自产生一批 run
-> 页面在 Parameter Lab 查看批次汇总、实验结果和推荐候选
```

这样做的目的：

- 保持单个 `ParameterExperiment` 的结果口径清晰
- 避免把多快照比较、参数搜索和结果汇总混成一个对象
- 允许后续对批次层增加推荐、评分和研究结论沉淀

## 9. 主执行语义

### 9.1 默认执行语义

v1 统一采用：

`signal_on_bar_close_fill_on_next_bar_open`

即：

- 当前 bar 收盘后计算信号
- 下一根 bar 开盘价执行成交

### 9.2 语义约束

- 所有策略只可在已闭合 bar 上生成信号
- 当前 bar 内不进行 same-bar 成交推演
- 若最后一根 bar 后不存在下一根 bar，则该信号不成交
- benchmark 必须使用相同成交语义

### 9.3 信号与执行分层

必须严格区分以下对象：

- `SignalIntent`
- `OrderRequest`
- `FillEvent`
- `TradeRecord`

策略只表达意图，不直接修改账户和成交状态。

## 10. 数据语义

### 10.1 时间与时区

- 时间统一使用 UTC
- candle 时间戳统一表示 **bar open time**
- 所有数据存储与比较都以 UTC 为准

### 10.2 特征与未来函数约束

- 特征只能使用当前 bar 及历史数据
- 禁止未来数据泄漏
- 若指标窗口不足，则该 bar 的信号无效

### 10.3 缺失 bar 规则

v1 要求：

- 缺失 bar 必须显式识别
- 数据预处理必须输出缺失信息
- 不允许在未声明规则的情况下隐式补齐

### 10.3.1 原始 K 线拉取约束

使用交易所 OHLCV 时，必须遵守以下规则：

- 默认最后一根未闭合 candle 不进入回测输入
- 显式传入 `since`
- 显式控制 `limit` 与分页方向
- 对分页结果按时间升序去重
- 对缺失 bar、重复 bar、时间错位 bar 生成结构化告警

### 10.3.2 price type 约束

对于 perpetual 市场，v1 允许以下 price type：

- `last`
- `mark`
- `index`

要求：

- 价格类型必须进入 `resolved_config`
- 不同 price type 的 run 不可直接比较
- 若使用交易所 mark/index K 线，必须在数据快照中记录来源

### 10.4 warmup 规则

指标允许使用 warmup 区间完成预热，但：

- warmup bar 不计入有效交易统计
- warmup bar 不计入 IS/OOS 指标
- 若 warmup 后指标仍不足窗口，则当前 bar 信号无效

## 11. 验证与 benchmark

### 11.1 Validation 规则

v1 支持单次 IS/OOS 切分：

- In-Sample：用于策略开发与参数筛选
- Out-of-Sample：用于稳健性验证

### 11.2 benchmark 规则

v1 至少提供两个 benchmark：

- Buy & Hold
- Fixed-hold naive baseline

benchmark 必须与主策略保持相同口径：

- 相同数据集
- 相同 warmup / split
- 相同主执行语义
- 相同 fee / slippage 处理规则

其中 `Fixed-hold naive baseline` 在 v1 中固定为唯一实现：

- 在验证区间起点后的第一个可交易 bar 产生开多信号
- 按主执行语义在下一根 bar open 成交
- 固定持有 `N` 根 bar
- 到期后按主执行语义平仓
- 若区间未结束则重复该过程

说明：

- `N` 为 benchmark 配置的一部分，必须写入 run manifest
- v1 不提供其他 naive baseline 变体

### 11.3 指标口径

v1 固定指标口径：

- 日收益聚合
- 年化因子 = 365
- risk free rate = 0
- Sharpe / Sortino / Calmar 基于日级收益计算

## 12. 页面设计

v1 固定 4 个主页面。

### 12.1 Dashboard

目标：

- 快速筛选候选 run
- 观察 OOS 与 benchmark 表现

主要组件：

- run 过滤器
- 指标卡
- return vs drawdown 散点图
- sharpe vs trade_count 散点图
- run 表格

表格建议字段：

- `run_id`
- `strategy_name`
- `symbol`
- `total_return`
- `oos_return`
- `oos_trade_count`
- `benchmark_excess_return`
- `sharpe`
- `max_drawdown`
- `trade_count`
- `config_hash`
- `created_at`

### 12.2 Run Detail

目标：

- 查看单次 run 的完整结果
- 下钻到交易级复盘

Tab 设计：

#### Tab A：Summary

- 核心指标卡
- equity curve
- drawdown curve
- benchmark 对比曲线
- fee/slippage 贡献拆解
- `signal_count -> order_count -> fill_count -> trade_count` 漏斗

#### Tab B：Trades

- 交易表
- 盈亏分布
- holding time vs pnl
- long/short 拆分

#### Tab C：Timeline

- K 线
- entry / exit 点位
- 点击交易查看详情

#### Tab D：Config

- dataset snapshot
- execution policy
- strategy version
- resolved config
- logs / warnings

### 12.3 Trade Explorer

目标：

- 对交易记录做集中筛选和定位

v1 只要求：

- 筛选
- 排序
- 导出
- 跳转 timeline

筛选条件：

- winner / loser
- side
- symbol
- holding range
- pnl range
- reason_code

### 12.4 Parameter Lab

目标：

- 选择参数
- 发起实验
- 判断参数稳健性

区域设计：

#### A. 参数控制区

- 策略参数输入
- 参数模板保存
- validation split 选择
- benchmark 选择

#### B. 单次运行区

- 提交 single run task
- 展示任务状态
- 展示结果摘要

#### C. 批量实验区

- grid/random 选择
- search space 定义
- max trials
- 固定 random seed
- 排除无效组合

#### D. 结果分析区

- heatmap
- 单参数敏感性图
- IS/OOS 双结果表
- 稳定区间提示
- 排名表
- 无效组合数
- 被过滤组合数
- OOS 空交易组合数
- 多快照批次汇总
- 推荐候选区

补充说明：

- `Parameter Lab` 的主目标不是给出一个“唯一最优参数”
- 页面应优先帮助研究者识别：
  - 哪些参数在单个快照内较稳健
  - 哪些参数在多个快照 / 多个周期下重复表现较好
  - 哪些结果只是单点高收益但不具备稳定性

## 13. 核心对象模型

### 13.1 `DatasetSnapshot`

表示单个 symbol/timeframe 的固定数据快照。

字段建议：

- `dataset_snapshot_id`
- `source`
- `exchange`
- `market_type`
- `symbol`
- `timeframe`
- `time_range_start`
- `time_range_end`
- `row_count`
- `schema_version`
- `feature_version`
- `storage_uri`
- `data_source`
- `price_type`
- `created_at`

### 13.2 `DatasetBundle`

表示实验级别引用的一组数据快照。

字段建议：

- `dataset_bundle_id`
- `dataset_snapshot_ids`
- `exchange`
- `market_type`
- `timeframe`
- `symbol_list`
- `time_range_start`
- `time_range_end`
- `data_source`
- `price_type`
- `created_at`

### 13.2.1 `FeatureArtifact`

表示一组本地计算的特征产物。

字段建议：

- `feature_artifact_id`
- `dataset_snapshot_id`
- `feature_version`
- `feature_params_json`
- `feature_params_hash`
- `input_price_field`
- `warmup_bars`
- `feature_cache_key`
- `storage_uri`
- `created_at`

说明：

- `feature_cache_key` 至少由 `dataset_snapshot_id + feature_version + input_price_field + feature_params_hash + warmup_bars` 组成
- 相同 `feature_cache_key` 的特征产物只能计算一次，后续 run 必须复用

### 13.3 `ExecutionPolicy`

表示执行语义。

字段建议：

- `execution_policy_id`
- `signal_timing`
- `fill_timing`
- `price_field_used`
- `allow_same_bar_exit`
- `version`

v1 中该对象只有一种默认值，但对象必须存在。

### 13.4 `ValidationSplit`

表示样本切分。

字段建议：

- `validation_split_id`
- `target_type`
- `target_id`
- `warmup_bars`
- `is_start`
- `is_end`
- `oos_start`
- `oos_end`
- `is_start_inclusive`
- `is_end_exclusive`
- `oos_start_inclusive`
- `oos_end_exclusive`
- `feature_cutoff_rule`
- `split_type`

说明：

- `target_type` 取值为 `dataset_snapshot` 或 `dataset_bundle`
- 单 symbol run 可绑定 `dataset_snapshot`
- 多 symbol experiment 可绑定 `dataset_bundle`

### 13.5 `MetricPolicy`

表示指标口径。

字段建议：

- `metric_policy_id`
- `return_aggregation_freq`
- `annualization_factor`
- `risk_free_rate`
- `sharpe_formula_version`

### 13.6 `SignalIntent`

表示策略层意图，不直接表达最终成交结果。

字段建议：

- `signal_id`
- `run_id`
- `timestamp`
- `symbol`
- `action`
- `side`
- `qty_policy_ref`
- `reason_code`
- `signal_score`
- `meta_json`

约束：

- `SignalIntent` 不包含最终下单价格
- `SignalIntent` 不包含手续费假设
- `SignalIntent` 不包含最终成交数量

### 13.7 `OrderRequest`

字段建议：

- `order_id`
- `run_id`
- `signal_id`
- `symbol`
- `side`
- `order_type`
- `qty`
- `request_time`
- `request_price`
- `status`

### 13.8 `FillEvent`

字段建议：

- `fill_id`
- `run_id`
- `order_id`
- `trade_id`
- `fill_time`
- `fill_price`
- `qty`
- `fee`
- `slippage_cost`

### 13.9 `TradeRecord`

字段建议：

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

### 13.10 `BacktestRun`

字段建议：

- `run_id`
- `strategy_name`
- `strategy_version`
- `dataset_snapshot_id`
- `execution_policy_id`
- `metric_policy_id`
- `feature_artifact_id`
- `engine_version`
- `fee_model_version`
- `slippage_model_version`
- `fee_model_params_json`
- `slippage_model_params_json`
- `validation_split_id`
- `config_hash`
- `resolved_config_uri`
- `benchmark_config_uri`
- `seed`
- `run_manifest_uri`
- `status`
- `created_at`

### 13.11 `RunManifest`

表示一次 run 的最小可复现快照。

字段建议：

- `run_id`
- `dataset_snapshot_id`
- `strategy_version`
- `engine_version`
- `execution_policy_id`
- `metric_policy_id`
- `feature_artifact_id`
- `validation_split_id`
- `fee_model_version`
- `slippage_model_version`
- `fee_model_params_json`
- `slippage_model_params_json`
- `benchmark_config_json`
- `resolved_config_json`
- `seed`
- `created_at`

### 13.12 `ParameterExperiment`

字段建议：

- `experiment_id`
- `strategy_name`
- `dataset_bundle_id`
- `validation_split_id`
- `metric_policy_id`
- `benchmark_policy_version`
- `benchmark_config_uri`
- `search_type`
- `search_space_json`
- `base_config_uri`
- `seed_policy`
- `seed`
- `shared_feature_artifact_ids`
- `created_at`

说明：

- `ParameterExperiment` 负责表达一次参数搜索任务本身
- v1 当前工程切片建议保持其结果口径收敛：
  - 一个 `ParameterExperiment` 对应一个可明确追踪的数据口径
  - 不把多快照直接混入同一个 experiment 结果表
- 若用户一次多选多个 `DatasetSnapshot` 发起实验，应由上层批次对象协调，而不是改变 experiment 本身的职责

### 13.12.1 `ExperimentBatch`

表示一次面向多个数据快照的批量实验提交。

字段建议：

- `batch_id`
- `strategy_name`
- `dataset_snapshot_ids`
- `validation_split_id`
- `metric_policy_id`
- `benchmark_policy_version`
- `search_type`
- `search_space_json`
- `base_config_uri`
- `seed_policy`
- `seed`
- `experiment_ids`
- `status`
- `recommendation_version`
- `created_at`

职责说明：

- `ExperimentBatch` 不直接替代 `ParameterExperiment`
- 它的职责是：
  - 记录一次多快照发起动作
  - fan-out 为多个已有 `ParameterExperiment`
  - 汇总多实验结果
  - 承载批次级推荐与自动评估结果

v1 对 `ExperimentBatch` 的自动评估要求先收敛为规则驱动，不引入黑盒模型。

推荐输出至少分为三类：

- 稳健候选
- 高收益候选
- 需排除组合

### 13.13 `ParameterResult`

字段建议：

- `experiment_id`
- `run_id`
- `param_json`
- `in_sample_return`
- `out_of_sample_return`
- `in_sample_sharpe`
- `out_of_sample_sharpe`
- `max_drawdown`
- `trade_count`
- `benchmark_excess_return`
- `stability_score`

### 13.14 `BenchmarkResult`

字段建议：

- `benchmark_id`
- `run_id`
- `benchmark_type`
- `return_pct`
- `max_drawdown`
- `sharpe`
- `equity_uri`

### 13.15 `StructuredWarning`

表示结构化告警，而不是纯文本日志。

字段建议：

- `warning_id`
- `run_id`
- `warning_type`
- `warning_code`
- `severity`
- `message`
- `payload_json`
- `created_at`

建议类型：

- `data_warning`
- `execution_warning`
- `analytics_warning`

建议数据类告警码至少包含：

- `MISSING_BAR_DETECTED`
- `DUPLICATE_BAR_DETECTED`
- `BAR_TIMESTAMP_MISALIGNED`
- `UNCLOSED_LAST_CANDLE_DROPPED`
- `DATA_SOURCE_GAP_DETECTED`

### 13.16 `ResearchNote`

字段建议：

- `note_id`
- `target_type`
- `target_id`
- `content`
- `author`
- `labels`（v1 可选，用于保存基准 / 候选 / 排除等轻量研究标记）
- `created_at`

## 14. 存储设计

### 14.1 存储技术

建议：

- 行情与大体量结果：Parquet
- 查询索引与分析表：DuckDB

### 14.2 存储原则

- 原始行情和曲线走文件存储
- run 索引、交易表、实验结果入 DuckDB
- 页面优先查询 DuckDB
- `resolved_config`、日志、图表产物使用 URI 关联
- 结构化 warnings 与 task failure metadata 入 DuckDB
- 特征缓存产物按 `feature_cache_key` 落盘和索引

### 14.3 特征缓存原则

v1 要求建立显式特征缓存，而不是在回测时临时重算。

要求：

- 先检查 `feature_cache_key` 是否命中
- 命中则直接复用 `FeatureArtifact`
- 未命中才触发特征计算任务
- 特征缓存必须可被多个 run 和 experiment 共享读取

## 15. 任务执行模型

v1 固定采用异步任务模型：

```text
UI 提交任务
-> jobs 创建 task
-> engine 执行回测
-> storage 写结果
-> UI 查询状态
-> 页面展示结果
```

任务类型：

- `single_run`
- `parameter_experiment`

任务状态：

- `pending`
- `running`
- `success`
- `failed`

不允许在页面请求线程内直接执行完整回测。

### 15.0 执行分工

回测任务的有效链路应为：

```text
数据准备
-> 特征准备
-> 信号生成
-> 执行模拟
-> 结果分析
```

要求：

- 数据准备与特征准备优先前置
- 回测任务默认读取已有 `DatasetSnapshot` 和 `FeatureArtifact`
- 参数实验中的各个 worker 不得重复生成相同特征

### 15.1 失败分类

v1 要求最小失败码体系：

- `DATA_INVALID`
- `DATA_INSUFFICIENT_WARMUP`
- `CONFIG_INVALID`
- `ORDER_REJECTED_BY_CONSTRAINT`
- `ENGINE_RUNTIME_ERROR`
- `ANALYTICS_FAILED`

任务失败时必须记录：

- `failure_code`
- `failure_stage`
- `failure_message`
- `failure_payload_uri`

### 15.2 结构化 warnings

v1 的日志不能只停留在文本输出，至少要产出结构化 warnings。

建议最小覆盖：

- data warnings：缺失 bar、重复 bar、时间异常
- execution warnings：最后一根信号未成交、因资金不足拒单、因精度约束拒单
- analytics warnings：OOS 样本过少、trade_count 过低、收益不具年化解释性

### 15.3 并行执行原则

参数实验允许并行，但遵守以下原则：

- 并行单位是 run task，而不是特征重复计算
- `DatasetSnapshot` 和 `FeatureArtifact` 作为只读输入共享
- worker 不得各自重新拉取历史数据
- worker 不得各自重新生成同一特征集合
- 并行写结果时，存储层必须避免重复注册相同 cache artifact

## 16. 稳定区间定义

v1 不使用抽象产品语言，采用朴素工程规则。

某参数组合可被标记为“稳定候选”，需要同时满足：

1. IS 指标进入前 20% 分位
2. OOS 指标相对 IS 的劣化不超过 20%
3. 参数邻域半径为 1 的相邻组合中，至少 40% 进入前 30% 分位

说明：

- 该规则用于 v1 页面提示
- 后续版本可替换为更复杂稳健性评估

## 17. Phase 划分

### 17.1 Phase 1：最小可信闭环

目标：

先实现可信、可复现、可查看的单次回测。

范围：

- DatasetSnapshot
- FeatureArtifact
- ExecutionPolicy
- ValidationSplit
- MetricPolicy
- BacktestRun
- RunManifest
- SignalIntent / OrderRequest / FillEvent / TradeRecord
- ccxt REST 历史 K 线拉取
- canonical candle 标准化
- 本地 feature 计算
- feature cache key 与缓存复用
- 单策略单 symbol 回测
- market open / close / reverse
- fee/slippage
- Buy & Hold benchmark
- resolved config 固化
- 结构化 warnings 与 failure codes
- Run Detail 基础版

### 17.2 Phase 2：研究可用

目标：

让系统具备基础研究效率。

范围：

- Dashboard
- Trade Explorer
- IS/OOS 对照
- Fixed-hold naive baseline
- ccxt pro 增量更新
- 参数实验并行执行
- ResearchNote

### 17.3 Phase 3：参数实验

目标：

让系统具备参数实验与稳健性分析能力。

范围：

- Parameter Lab
- parameter experiment task
- grid/random
- heatmap
- 稳定区间提示

### 17.4 Phase 4：后续增强

后续再做：

- stop/tp 执行语义
- perpetual funding
- liquidation approximation
- 多 symbol 批量增强
- 更复杂 benchmark

## 18. 附录 A：执行语义规范

### A.1 信号生成

- 信号仅在 bar close 后生成
- 策略只能访问当前 bar 及其历史数据

### A.2 订单请求生成

- 每个有效信号生成一个 `OrderRequest`
- v1 只支持 market 类型请求

### A.3 成交

- `OrderRequest` 在下一根 bar open 成交
- fill price 使用下一根 bar 的 open
- 若无下一根 bar，则该请求作废，不成交

### A.4 平仓与反手

- `close` 表示平掉当前方向持仓
- `reverse` 表示先平掉当前持仓，再按新方向开仓
- v1 不支持同一 symbol 同时持有双向仓位

### A.5 v1 明确不支持

- stop loss
- take profit
- trailing stop
- limit order
- same-bar exit 推演

## 19. 附录 B：数据与切分规范

### B.1 数据时间口径

- 时间统一 UTC
- candle 时间戳为 bar open time

### B.2 缺失 bar 处理

- 必须显式识别并记录缺失 bar
- 不允许隐式填补后继续回测而不留痕

### B.2.1 历史 K 线获取

- 历史 K 线优先使用 `ccxt.fetchOHLCV`
- 必须显式传 `since`
- 必须显式分页或循环拉取
- 不依赖交易所默认返回区间
- 返回结果必须按时间升序去重后落盘

### B.2.2 增量 K 线获取

- 增量更新可使用 `ccxt pro.watchOHLCV`
- WebSocket 只用于最新窗口维护，不作为深历史主来源
- 需要周期性用 REST 对最近窗口补洞与校正

### B.2.3 trades 聚合预留

- 如需更低延迟或更严格 candle 语义，可使用 trades 本地聚合 K 线
- v1 不强制 trades 聚合，但必须为后续切换预留接口

### B.3 warmup

- 指标可使用 `warmup_bars` 进行预热
- warmup 区间不计入交易统计与绩效指标

### B.4 IS/OOS 边界

- `is_start_inclusive = true`
- `is_end_exclusive = true`
- `oos_start_inclusive = true`
- `oos_end_exclusive = true`

### B.5 feature cutoff

- 若某 bar 的特征窗口不足，则该 bar 信号无效
- 不因窗口不足自动补算未来数据

### B.6 数据集层级

- `DatasetSnapshot` 表示单 symbol/timeframe 数据快照
- `DatasetBundle` 表示实验级一组快照
- `FeatureArtifact` 表示基于数据快照计算出的特征产物
- `BacktestRun` 绑定单个 `DatasetSnapshot`
- `ParameterExperiment` 绑定 `DatasetBundle`
- `ValidationSplit` 可绑定 `DatasetSnapshot` 或 `DatasetBundle`
- `ExperimentBatch` 绑定多个 `DatasetSnapshot`，并协调多个 `ParameterExperiment`

## 20. 附录 C：账户与计量规范

### C.1 市场类型

v1 固定为 `linear USDT perpetual`。

### C.2 资金口径

- 初始资金使用 USDT
- equity 使用 USDT
- pnl 使用 USDT
- fee 使用 USDT

### C.3 持仓口径

- `qty` 为 base asset 数量
- `notional = qty * fill_price`

### C.4 leverage

- leverage 影响保证金占用和风险暴露
- leverage 不改变 `qty` 的计量单位
- 在 `percent_of_cash` 仓位策略下，leverage 会直接影响最终派生出的 `qty`
- v1 默认允许 run 级全局 leverage 配置
- symbol 级差异化 leverage 后置

### C.5 仓位行为

- 同一 symbol 同时只允许单方向持仓
- `reverse` 先平后开
- benchmark 与主策略使用同一资金口径

### C.6 下单约束

- 下单前检查 `available_cash` 与保证金是否足够
- 下单前检查最小名义金额
- 下单前检查数量与价格精度
- 不满足约束时生成 `ORDER_REJECTED_BY_CONSTRAINT`

## 21. 附录 D：指标与特征规范

### D.1 统一原则

- 技术指标一律本地计算
- 不依赖交易所平台指标
- 指标输入字段、参数、warmup 和版本号必须显式记录

### D.2 v1 必做指标

建议纳入：

- EMA
- RSI
- MACD
- Bollinger Bands
- ATR

### D.3 指标计算输入

每个指标必须明确：

- 输入价格字段
- 时间窗口
- 初始化方式
- 是否允许缺失值传播

### D.4 feature 版本化

每次特征生成至少记录：

- `feature_version`
- `feature_params_json`
- `input_price_field`
- `warmup_bars`

### D.5 与回测的关系

- 回测 run 必须绑定唯一 `FeatureArtifact`
- 不同 feature version 的 run 不可直接横向比较
- 特征计算变更必须视为研究口径变更

### D.6 性能约束

- 特征不得在每次回测时全量重算
- 常用离散窗口集合应允许一次性批量生成
- 参数实验优先复用特征列，而不是重复构造指标表
- 若仅修改 execution / portfolio 参数，不得触发特征重算

## 22. 附录 E：代码结构与性能设计

### E.1 分层要求

- `data` 层只负责原始行情和标准化
- `features` 层只负责指标和特征缓存
- `strategy` 层只负责信号逻辑
- `execution` 层只负责订单、成交和手续费/滑点
- `portfolio` 层只负责账户和仓位
- `analytics` 层只负责统计与报告
- `app` 层不直接写重计算逻辑

### E.2 禁止事项

禁止以下实现方式：

- Streamlit 页面直接执行完整回测
- 在策略类中顺手重算 EMA/RSI/MACD
- 每个 run 都重新从交易所拉历史数据
- 参数实验中每个 worker 重复构建相同特征
- 将数据、特征、执行、分析堆在单个大脚本中

### E.3 推荐优化顺序

优先按以下顺序优化：

1. 去掉重复数据拉取
2. 去掉重复特征计算
3. 将常用离散窗口批量预计算
4. 减少大 DataFrame 重复复制
5. 将瓶颈状态机局部优化

### E.4 目标性能

对于 bar-based 回测，v1 建议目标：

- 单 symbol、1 年小时线或日线：秒级到十几秒
- 单 symbol、1 年 1m 数据：尽量控制在秒级到几十秒
- 100 组参数实验：在特征已缓存情况下控制在分钟级，而不是数小时

若实际表现远慢于上述目标，优先排查：

- 是否重复拉取历史数据
- 是否重复计算特征
- 是否存在大量 Python 层逐行循环
- 是否存在不必要的大表复制

## 23. 建议外部评审问题

将以下问题发给其他 AI 或工程师继续评审：

```text
1. v1 边界是否足够收敛，是否仍存在明显范围蔓延？
2. 执行语义、数据语义、计量语义三套规范是否已经闭合？
3. v1 完全移除 stop/tp 是否合理，是否有必要在 Phase 1 保留任何保护性退出？
4. DatasetSnapshot / DatasetBundle / ValidationSplit 的关系是否足够支撑可复现性？
5. SignalIntent -> OrderRequest -> FillEvent -> TradeRecord 的链路是否合理？
6. linear USDT perpetual 作为 v1 固定市场类型是否合理？
7. ccxt REST + ccxt pro WebSocket 的数据获取分工是否合理？
8. 指标全部本地计算而不依赖交易所平台指标是否合理？
9. benchmark 与 MetricPolicy 的定义是否足够稳定和可解释？
10. Dashboard / Run Detail / Trade Explorer / Parameter Lab 四页是否足够支撑研究闭环？
11. `FeatureArtifact` / `feature_cache_key` / 参数分层设计是否足够支撑性能复用？
12. DuckDB + Parquet + Streamlit + Plotly + 本地 jobs 是否适合作为单机研究型工具的 v1 技术路线？
13. 哪些对象字段仍缺失，可能导致后续扩展困难？
```
