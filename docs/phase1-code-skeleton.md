# Phase 1 代码骨架说明

## 目的

本文档说明仓库中为 `Phase 1` 新增的第一批代码骨架。

它不是实施设计稿的替代品，作用更具体：

- 把设计文档映射成实际包结构
- 说明哪些对象已经以代码骨架形式存在
- 明确当前骨架暂时没有实现的部分
- 为后续 AI / 工程实现提供精确起点

当前主设计依据仍然是：

- [crypto-backtest-workbench-v1-implementation-design.md](/Users/liangxu/code/lhfx01/docs/crypto-backtest-workbench-v1-implementation-design.md)

## 本次新增内容

### 包配置

- [pyproject.toml](/Users/liangxu/code/lhfx01/pyproject.toml)

当前已完成：

- 建立以 `src/` 为根的 Python 包结构
- 包名为 `crypto-backtest-workbench`
- 提供一个最小 CLI 入口：`cbw`

### 包根目录

- [src/crypto_backtest_workbench](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench)

当前根模块：

- [__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/__init__.py)
- [cli.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/cli.py)

CLI 故意保持极简，它的作用是：

- 验证包结构和入口 wiring 正常
- 给后续任务提供稳定入口

## 当前代码结构

```text
src/crypto_backtest_workbench/
  app/
  domain/
    models/
  engine/
    analytics/
    data/
    execution/
    experiments/
    features/
    portfolio/
    strategy/
    validation/
  jobs/
  storage/
```

这与主设计文档中的高层分层一致：

- `domain`：核心对象定义
- `engine`：纯回测机制
- `jobs`：任务编排与生命周期状态
- `storage`：产物路径与持久化辅助
- `app`：面向 UI 的占位包

## 当前已落地文件清单

以下文件可视为当前 `Phase 1` 骨架的权威清单。

### 包入口与根模块

- [pyproject.toml](/Users/liangxu/code/lhfx01/pyproject.toml)
- [__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/__init__.py)
- [cli.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/cli.py)

### Domain

- [domain/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/domain/__init__.py)
- [models/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/domain/models/__init__.py)
- [common.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/domain/models/common.py)
- [dataset.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/domain/models/dataset.py)
- [features.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/domain/models/features.py)
- [execution.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/domain/models/execution.py)
- [run.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/domain/models/run.py)

### Engine

- [engine/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/__init__.py)
- [engine/data/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/data/__init__.py)
- [engine/data/fetchers.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/data/fetchers.py)
- [engine/data/canonicalizer.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/data/canonicalizer.py)
- [engine/data/integrity.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/data/integrity.py)
- [engine/data/service.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/data/service.py)
- [engine/execution/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/execution/__init__.py)
- [engine/execution/policies.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/execution/policies.py)
- [engine/experiments/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/experiments/__init__.py)
- [engine/features/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/features/__init__.py)
- [engine/features/cache.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/features/cache.py)
- [engine/portfolio/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/portfolio/__init__.py)
- [engine/portfolio/account.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/portfolio/account.py)
- [engine/strategy/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/strategy/__init__.py)
- [engine/strategy/base.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/strategy/base.py)
- [engine/validation/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/validation/__init__.py)
- [engine/analytics/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/analytics/__init__.py)

### Jobs / Storage / App

- [jobs/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/jobs/__init__.py)
- [task_models.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/jobs/task_models.py)
- [storage/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/storage/__init__.py)
- [paths.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/storage/paths.py)
- [repositories/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/storage/repositories/__init__.py)
- [datasets.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/storage/repositories/datasets.py)
- [app/__init__.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/app/__init__.py)

说明：

- 上述清单中的 `__init__.py` 多数属于边界占位文件，不代表该模块已具备业务能力。
- 需要判断某模块是否“可用”，以本文后续的完成定义而不是文件是否存在为准。

## 已实现的领域对象

### 数据层

定义位置：

- [dataset.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/domain/models/dataset.py)

当前包括：

- `CanonicalCandle`
- `DatasetSnapshot`
- `DatasetBundle`
- `ValidationSplit`
- `DataIntegrityReport`

意义：

- `DatasetSnapshot` 和 `ValidationSplit` 是 `Phase 1` 的身份对象
- `DataIntegrityReport` 让数据质量有独立对象，而不是只埋在 warning 里

### 特征层

定义位置：

- [features.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/domain/models/features.py)

当前包括：

- `FeatureSpec`
- `FeatureCacheKey`
- `FeatureArtifact`

这是 `Phase 1` 最核心的性能边界之一。

当前已经通过代码固定下来的关键决策：

- 特征产物是显式的一等对象
- cache 身份基于 `dataset + version + input field + params hash + warmup`
- 代码已为未来依赖跟踪预留 `depends_on`

### 执行层

定义位置：

- [execution.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/domain/models/execution.py)

当前包括：

- `ExecutionPolicy`
- `SignalIntent`
- `OrderRequest`
- `FillEvent`
- `TradeRecord`
- `BenchmarkConfig`
- `BenchmarkResult`
- `StructuredWarning`

已经体现在代码中的关键决策：

- signal / order / fill / trade 严格分层
- `SignalIntent` 不携带最终执行结果
- `OrderRequest` 可以记录拒单元数据
- benchmark 结果可以指向时间序列产物，而不只是摘要指标

### Run 层

定义位置：

- [run.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/domain/models/run.py)

当前包括：

- `MetricPolicy`
- `RunManifest`
- `BacktestRun`
- `ParameterExperiment`
- `ResearchNote`

已经体现在代码中的关键决策：

- `RunManifest` 是显式对象，不再依赖隐式约定
- `BacktestRun` 自带失败元数据
- experiment 可以追踪共享特征产物

## 已实现的 Engine 骨架

### 策略接口

- [engine/strategy/base.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/strategy/base.py)

当前定义：

- `StrategyInput`
- `StrategyDefinition`

最重要的约束：

- 策略先声明所需特征
- 策略基于已预计算的特征生成信号
- 策略不负责特征计算

### 特征缓存注册器

- [engine/features/cache.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/features/cache.py)

当前特征：

- 仅内存版
- 按 `feature_cache_key` 提供 `register/get/has`

它现在存在的意义：

- 把缓存模型做成具体代码，而不是停留在文档
- 后续可以替换成 DuckDB / 索引化持久层，而不改对象语义

### 默认执行语义

- [engine/execution/policies.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/execution/policies.py)

当前已经钉死默认策略：

- `signal_on_bar_close_fill_on_next_bar_open`

### 账户快照

- [engine/portfolio/account.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/portfolio/account.py)

当前提供的第一个账户对象：

- `AccountSnapshot`

它故意保持精简，只携带设计文档已钉死的字段：

- `available_cash`
- `used_margin`
- `maintenance_margin`
- `equity`
- `unrealized_pnl`

## 已实现的 Job 骨架

定义位置：

- [jobs/task_models.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/jobs/task_models.py)

当前包括：

- `TaskRecord`
- `SingleRunTaskPayload`
- `ParameterExperimentTaskPayload`

这是第一步把以下三者分开：

- run 身份
- job 编排
- 执行结果

## 已实现的 Storage 辅助

定义位置：

- [storage/paths.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/storage/paths.py)

当前状态：

- 只有产物 URI / 路径生成辅助函数

这对于 `Phase 1` 骨架已经足够，同时避免过早把持久化实现写死。

## 当前骨架的完成定义

以下完成定义用于约束后续代码实现，不以“写了代码”为完成，而以“闭环达成”为完成。

### DatasetRepository 的完成定义

- 能保存 `DatasetSnapshot`
- 能保存 canonical candles
- 能保存 `DataIntegrityReport`
- 能通过 `dataset_snapshot_id` 反查 metadata
- 能返回 candles 的持久化位置或读取入口

### Feature cache 的完成定义

- 能按 `feature_cache_key` 查询
- 命中时返回 `FeatureArtifact`
- 未命中时可注册新 artifact
- 对同一个 `feature_cache_key` 的重复注册必须幂等

### Fill engine 的完成定义

- 支持 `signal_on_bar_close_fill_on_next_bar_open`
- 支持基础 `close` 与 `reverse`
- 若订单因约束失败，能记录拒单原因
- 能输出 `FillEvent` 与最终 `TradeRecord`

### Run assembly 的完成定义

- 能创建并校验 `RunManifest`
- 能落盘 `BacktestRun`
- 能关联 warning 和 failure metadata
- 能把结果与数据、执行语义、指标口径串起来

## 当前骨架刻意没有实现的部分

当前代码 **还没有** 实现：

- 完整的 `ccxt` 分页拉取流程
- feature 计算 pipeline
- 策略具体实现
- fill engine 逻辑
- trade 生命周期组装
- DuckDB repository
- Streamlit 页面
- benchmark 计算
- validation 执行

这是有意为之。

当前阶段的目标是：

- 先冻结形状
- 先冻结接口
- 先冻结包边界

再写重逻辑。

## 当前新增的数据层骨架

本轮已把 `Phase 1` 的数据层从“空目录”推进到“可实现状态”。

### 数据抓取接口

定义位置：

- [fetchers.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/data/fetchers.py)

当前包括：

- `HistoryFetchRequest`
- `OhlcvRow`
- `HistoryFetcher`
- `CcxtHistoryFetcher`
- `FetchBatch`

当前作用：

- 定义历史 OHLCV 抓取请求的统一输入
- 将 `ccxt` 的使用隔离在数据层，不让全项目直接耦合
- 为后续分页抓取和数据补洞保留稳定接口

当前边界：

- 已支持最小 `ccxt` 调用适配
- 尚未实现完整分页拉取与批处理编排

### 数据编排服务

定义位置：

- [service.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/data/service.py)

当前包括：

- `DatasetIngestionResult`
- `DatasetIngestionService`

当前作用：

- 串起“抓取 -> 标准化 -> 开放 bar 处理 -> 完整性报告 -> 仓储落盘”
- 让 `Phase 1` 的数据层已经具备最小可执行编排形状

当前边界：

- 仍然只覆盖最小历史抓取闭环
- 尚未实现完整分页拉取、增量更新和补洞策略

### K 线标准化

定义位置：

- [canonicalizer.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/data/canonicalizer.py)

当前包括：

- `timeframe_to_timedelta`
- `ohlcv_rows_to_canonical_candles`
- `sort_and_deduplicate_candles`
- `drop_open_last_candle`

当前作用：

- 把原始 OHLCV 行转换为 `CanonicalCandle`
- 按时间排序并去重
- 支持剔除最后一根未闭合 candle

### 数据完整性报告

定义位置：

- [integrity.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/engine/data/integrity.py)

当前包括：

- `build_integrity_report`

当前作用：

- 统计缺失 bar
- 记录 gap 区间
- 结合“最后一根是否闭合”生成 `DataIntegrityReport`

### 数据仓储骨架

定义位置：

- [datasets.py](/Users/liangxu/code/lhfx01/src/crypto_backtest_workbench/storage/repositories/datasets.py)

当前包括：

- `DatasetRepository`
- `FileDatasetRepository`

当前作用：

- 保存 `DatasetSnapshot`
- 保存 canonical candles
- 保存 `DataIntegrityReport`

当前实现是：

- 基于本地文件系统
- metadata 写成 JSON
- canonical candles 写成 CSV

说明：

- 这不是最终持久化方案
- 它的目标是先把数据流闭环跑通
- 后续可替换成 DuckDB / Parquet 而不改变仓储接口

替换约束：

- 任何业务逻辑不得依赖 CSV 的列顺序
- 任何业务逻辑不得依赖 JSON 文件的组织细节
- 任何业务逻辑不得依赖本地文件路径命名约定
- 上层只能依赖 `DatasetRepository` 返回的对象与接口

这意味着 `FileDatasetRepository` 只是临时适配器，不是未来持久化契约本身。

## 为什么这个结构是安全的

这批骨架主要在 4 个地方降低后续返工风险：

1. `FeatureArtifact` 已显式存在，缓存不再是事后补丁。
2. `RunManifest` 已显式存在，可复现性不再依赖约定。
3. `SignalIntent -> OrderRequest -> FillEvent -> TradeRecord` 已显式存在，执行语义后续可演进而不用重写策略层。
4. `TaskRecord` 已显式存在，UI 和后台执行可以保持解耦。

另外还具备两条重要工程约束：

5. 文件系统仓储已被限制为接口后端，可在不破坏上层调用的情况下替换成 DuckDB / Parquet。
6. 骨架已经区分“对象存在”和“模块完成”，可以避免后续实现阶段的假完成。

## 任务幂等与任务身份规则

当前 `jobs` 层虽然还只是骨架，但后续实现必须遵守以下规则：

- 同一个 `SingleRunTaskPayload` 若 identity 相同，不应产生语义重复的多个 run
- 若允许重试，必须记录重试关系，而不是静默创建无关联的新 run
- 同一个 `feature_cache_key` 不应因任务重复执行而生成多个等价 artifact
- 批量实验中的单 run 若失败，必须保留失败状态和失败原因，不能静默跳过

建议后续把 task identity 固定到以下维度：

- `dataset_snapshot_id`
- `strategy_version`
- `execution_policy_id`
- `metric_policy_id`
- `resolved_config`
- `seed`

## 推荐的下一步实现顺序

### 第一步

实现数据落盘与 repository 接口：

- raw ohlcv 落盘
- canonical candle 存储
- dataset snapshot 注册
- data integrity report 持久化

### 第二步

实现 feature pipeline：

- feature 参数哈希
- feature cache 查询
- feature artifact 生成
- 第一批指标：EMA、RSI

### 第三步

实现策略注册和一个参考策略：

- 均线交叉
  或
- RSI 阈值策略

### 第四步

实现执行循环：

- `SignalIntent -> OrderRequest -> FillEvent -> TradeRecord`
- 不支持 stop/tp
- 先只做单 symbol

### 第五步

实现 run 组装：

- 创建 `RunManifest`
- 写入 `BacktestRun`
- 产出 warnings

## 供后续 AI 评估的问题

后续评审应重点看：

1. 当前包边界是否与设计文档一致
2. `Phase 1` 对象是否还缺关键字段
3. feature caching 语义是否已经足够具体
4. 策略代码是否足够隔离于特征生成
5. 当前骨架是否已经把 UI、jobs、engine 清楚分开
6. 模块完成定义是否足够支撑后续拆任务
7. 任务身份和幂等规则是否已经足够明确
