# 模拟盘运行系统设计

## 1. 文档目标

本文档定义稳定策略进入模拟盘前后的系统设计。

目标是把当前研究系统中的稳定候选，推进到一个可持续运行、可复盘、可审计的模拟盘环境：

```text
稳定池候选
  -> 执行验证
  -> 创建模拟盘会话
  -> 实时增量 K 线
  -> 策略信号
  -> 模拟成交
  -> 持仓 / 资金曲线 / 交易记录
  -> 复盘与是否进入实盘判断
```

本文档重点定义：

- 模拟盘与回测研究的边界
- 实时 K 线数据获取方式
- `1h` 信号与 `5m` 执行的协作关系
- 模拟盘会话、账户、订单、成交、持仓模型
- paper broker 执行语义
- 状态持久化与故障恢复
- API / UI / CLI 的第一版落地范围
- 后续进入真实交易前的阶段门槛

本文档不改变：

- `ema_crossover v1` 策略逻辑
- `ema_pullback_atr_v2` 策略逻辑
- 当前回测 run 的结果口径
- 参数实验、稳定池、过滤实验的研究语义
- 现有 `execution_verification` 派生 run 的定义
- 真实交易所下单行为

第一版只做模拟盘，不做真实下单。

## 2. 背景

当前系统已经具备：

- 历史数据导入
- 单次回测
- 参数实验
- IS / OOS 验证
- 稳定池
- 5m execution verification
- 基于 5m execution run 的过滤实验
- 最大回撤归因分析

这些能力解决的是：

```text
历史上这套参数是否值得信任？
```

模拟盘要回答的是：

```text
从现在开始，这套策略在接近真实运行的状态机里是否仍然可靠？
```

两者差异很大：

- 回测是一次性批处理
- 模拟盘是持续运行的状态机
- 回测可以完整读取未来历史数据
- 模拟盘只能处理已经收盘的最新数据
- 回测结果主要是研究证据
- 模拟盘结果是实盘前的运行证据

因此模拟盘必须单独建运行层，但不能复制策略层。

## 3. 核心结论

新增模拟盘模块：

```text
src/crypto_backtest_workbench/app/paper_trading/
```

建议第一版结构：

```text
paper_trading/
  models.py
  market_feed.py
  broker.py
  runner.py
  risk_gate.py
  repository.py
  workflows.py
```

核心边界：

```text
engine/strategy       复用策略定义
engine/features       复用指标计算
engine/data           复用 fetcher 与 K 线规范化
app/paper_trading     新增模拟盘状态机
storage/repositories  新增模拟盘文件仓储
```

不要新增一套策略系统。

模拟盘只负责：

- 实时数据增量
- 已收盘 K 线判断
- 信号触发时机
- 模拟订单
- 模拟成交
- 持仓状态
- 账户资金
- 风控闸门
- checkpoint 与恢复

## 4. 设计原则

### 4.1 策略复用，执行隔离

策略仍来自现有 `engine/strategy`。

模拟盘不复制策略逻辑，不重新定义入场条件。

但模拟盘不直接把回测 `simulate_signals` 作为主循环。原因是：

- 回测是全量 candles + 全量 signals
- 模拟盘是每次 tick 只处理新数据
- 模拟盘必须保留未平仓状态
- 模拟盘必须处理重复启动、断点恢复、数据延迟

### 4.2 只处理已收盘 K 线

模拟盘不能用正在形成的 K 线生成策略信号。

例如 `1h` 策略：

```text
22:00 K 线
  open time = 22:00
  close time = 23:00
```

只有当前时间已经超过 `23:00`，并且交易所返回下一根或确认该 bar 完成后，才允许把这根 `22:00` K 线送入策略。

### 4.3 1h 决策，5m 执行

对于当前稳定池方向，推荐第一版采用：

```text
strategy_timeframe = 1h
execution_timeframe = 5m
```

含义：

```text
1h K 线：生成策略信号
5m K 线：推进成交、止损、止盈、资金曲线
```

`5m` K 线不改变策略入场条件，只用于更接近真实价格路径的执行模拟。

### 4.4 模拟盘数据不覆盖研究数据

研究数据写入：

```text
data/datasets/
```

模拟盘运行数据写入：

```text
data/paper_trading/
```

模拟盘数据是运行状态，不是不可变研究 snapshot。

如果后续要复盘某段模拟盘数据，可以从 `paper_trading` 导出为单独研究 dataset。

### 4.5 每一步都可恢复

模拟盘必须允许进程重启后继续运行。

因此每次 tick 后必须落盘：

- 已处理到哪根策略 K 线
- 已处理到哪根执行 K 线
- 当前账户
- 当前持仓
- 已发信号
- 已发订单
- 已成交记录
- 最近错误

## 5. 系统架构

## 5.1 模块分层

```text
app/paper_trading
  PaperSessionWorkflow
  PaperTickWorkflow
  PaperRunner

engine/strategy
  StrategyDefinition
  EMAPullbackATRStrategy

engine/features
  feature pipeline
  EMA / ATR / filter features

engine/data
  HistoryFetcher
  CcxtHistoryFetcher
  BinanceUsdMRestHistoryFetcher

paper_trading/market_feed.py
  增量拉取实时 K 线

paper_trading/broker.py
  模拟订单与成交

paper_trading/repository.py
  文件状态持久化
```

## 5.2 运行流程

```text
创建 PaperSession
  -> bootstrap 历史 warmup K 线
  -> 初始化账户
  -> 初始化 checkpoint
  -> 等待 tick

每次 tick
  -> 拉取 strategy timeframe 最新已收盘 K 线
  -> 拉取 execution timeframe 最新已收盘 K 线
  -> 去重并追加本地 market data
  -> 如果出现新 strategy bar，生成新 signal
  -> 用新 execution bars 推进 paper broker
  -> 更新订单 / 成交 / 持仓 / 资金曲线
  -> 更新 checkpoint
```

## 6. 数据模型

## 6.1 PaperSession

模拟盘会话。

建议字段：

- `paper_session_id`
- `stable_candidate_id`
- `source_run_id`
- `execution_verification_run_id`
- `strategy_name`
- `strategy_version`
- `symbol`
- `strategy_timeframe`
- `execution_timeframe`
- `strategy_params`
- `execution_constraints`
- `initial_cash`
- `fee_rate`
- `slippage_bps`
- `status`
- `created_at`
- `started_at`
- `stopped_at`
- `last_error`

状态：

- `created`
- `running`
- `paused`
- `stopped`
- `failed`

## 6.2 PaperCheckpoint

断点恢复状态。

建议字段：

- `paper_session_id`
- `last_strategy_bar_time`
- `last_execution_bar_time`
- `last_signal_id`
- `last_order_id`
- `last_fill_id`
- `last_trade_id`
- `updated_at`

## 6.3 PaperAccount

模拟账户。

建议字段：

- `paper_session_id`
- `available_cash`
- `used_margin`
- `equity`
- `unrealized_pnl`
- `realized_pnl`
- `fee_paid`
- `peak_equity`
- `max_drawdown`
- `updated_at`

## 6.4 PaperPosition

当前持仓。

第一版只支持单标的单仓位。

建议字段：

- `position_id`
- `paper_session_id`
- `symbol`
- `side`
- `qty`
- `entry_time`
- `entry_price`
- `mark_price`
- `planned_stop_loss_price`
- `planned_take_profit_price`
- `unrealized_pnl`
- `status`

## 6.5 PaperOrder

模拟订单。

建议字段：

- `order_id`
- `paper_session_id`
- `signal_id`
- `symbol`
- `side`
- `order_type`
- `qty`
- `request_time`
- `request_price`
- `status`
- `reject_reason_code`
- `created_at`

状态：

- `created`
- `accepted`
- `filled`
- `rejected`
- `cancelled`

## 6.6 PaperFill

模拟成交。

建议字段：

- `fill_id`
- `paper_session_id`
- `order_id`
- `trade_id`
- `fill_time`
- `fill_price`
- `qty`
- `fee`
- `slippage_cost`

## 6.7 PaperTrade

模拟交易记录。

建议字段尽量对齐现有 `TradeRecord`：

- `trade_id`
- `paper_session_id`
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
- `planned_stop_loss_price`
- `planned_take_profit_price`
- `entry_signal_meta_json`

## 7. 文件存储布局

第一版使用本地文件仓储。

建议目录：

```text
data/paper_trading/
  sessions/
    <paper_session_id>/
      session.json
      checkpoint.json
      account.json
      positions.json
      signals.csv
      orders.csv
      fills.csv
      trades.csv
      equity_curve.csv
      warnings.json
      market_data/
        BTC_USDT_USDT-1h.csv
        BTC_USDT_USDT-5m.csv
```

说明：

- `session.json` 保存配置和状态
- `checkpoint.json` 保存恢复点
- `market_data/` 保存模拟盘运行期增量 K 线
- `orders.csv` / `fills.csv` / `trades.csv` 用于后续复盘
- `equity_curve.csv` 用于 UI 展示资金曲线

## 8. 实时 K 线设计

## 8.1 为什么不用现有 ingest

现有 `ingest` 面向研究：

```text
给定 since/until
  -> 拉历史全量
  -> 保存不可变 dataset snapshot
```

模拟盘需要：

```text
启动时补 warmup
  -> 每次 tick 只拉新增 K 线
  -> 只保留已收盘 K 线
  -> 去重追加
  -> 更新 checkpoint
```

因此需要新增 `PaperMarketFeed`。

## 8.2 PaperMarketFeed

建议接口：

```python
class PaperMarketFeed:
    def bootstrap(
        self,
        *,
        symbol: str,
        timeframe: str,
        lookback_bars: int,
    ) -> list[CanonicalCandle]: ...

    def fetch_closed_bars_since(
        self,
        *,
        symbol: str,
        timeframe: str,
        since: datetime,
        now: datetime,
    ) -> list[CanonicalCandle]: ...
```

第一版使用 REST 轮询，不使用 WebSocket。

原因：

- 更容易调试
- 更容易重放
- 更容易恢复
- 更符合当前 fetcher 能力

## 8.3 已收盘 K 线判断

规则：

```text
bar_open_time + timeframe_delta <= now - safety_lag
```

建议第一版 safety lag：

```text
safety_lag_seconds = 10
```

例如：

```text
5m bar open = 10:00
bar close = 10:05
now >= 10:05:10
```

才认为该 bar 可用于模拟盘。

## 8.4 启动 warmup

启动时必须补足策略和指标所需历史。

建议第一版：

```text
strategy_timeframe lookback_bars = max(strategy_warmup_bars, feature_warmup_bars, 500)
execution_timeframe lookback_bars = 3000
```

对于 `1h + 5m`：

- `1h` 用于 EMA / ATR / 策略上下文
- `5m` 用于持仓路径和 SL / TP 执行

## 8.5 数据去重

本地 market data 以 `timestamp` 为唯一键。

每次追加前：

- 读取本地已有最后时间
- 丢弃早于或等于 checkpoint 的重复 K 线
- 对同 timestamp 行保留最新一次拉取结果
- 按 timestamp 排序落盘

## 8.6 Binance 限流

Binance REST 可能返回：

- `429` rate limit
- `418` temporary ban

模拟盘 feed 必须：

- 请求之间保留最小间隔
- 遇到 `429` / `418` 做退避重试
- 记录最近错误到 session
- 不因为单次拉取失败而破坏已有状态

## 9. 1h 信号与 5m 执行

## 9.1 基本语义

推荐第一版：

```text
1h bar close 后生成信号
下一根 5m bar open 模拟入场
持仓期间每根 5m bar 检查 SL / TP
```

示例：

```text
10:00 - 11:00 这根 1h K 线收盘
11:00 后策略生成 OPEN signal
11:00 这根 5m bar open 作为入场价
后续 5m bar 检查 stop loss / take profit
```

## 9.2 5m 的作用

`5m` K 线不决定是否开仓。

它只回答：

```text
策略已经决定要开仓后，实际价格路径会怎样推进？
```

具体作用：

- 模拟下一根低周期 open 成交
- 按更细路径检查 SL / TP
- 降低 `1h` OHLC 同 bar 顺序不明带来的偏差
- 生成更可信的持仓过程、最大回撤、资金曲线

## 9.3 同一根 5m 同时触发 SL / TP

第一版沿用保守原则：

```text
同一根 5m bar 同时触发 stop loss 和 take profit 时，按 stop loss 先触发。
```

原因：

- 5m 仍然是 OHLC，不是 tick
- 仍然无法知道 bar 内 high / low 先后顺序
- 模拟盘前期应保持保守

## 10. PaperBroker 设计

## 10.1 职责

`PaperBroker` 负责把策略信号转成模拟订单、成交和持仓变化。

职责：

- 校验是否允许开仓
- 计算下单数量
- 模拟成交价
- 扣除手续费
- 更新保证金
- 更新持仓
- 检查 SL / TP
- 平仓并生成 trade

## 10.2 不负责的内容

`PaperBroker` 不负责：

- 生成策略信号
- 拉 K 线
- 选择稳定候选
- 修改策略参数
- 自动优化参数

## 10.3 下单数量

第一版复用现有 execution constraints：

- `percent_of_cash`
- `risk_pct_of_equity`
- `risk_pct_of_cash_allocation`

但需要在模拟盘状态机中重新实现计算流程，不能依赖一次性回测循环隐式状态。

## 10.4 手续费与滑点

第一版使用配置化模拟：

```text
fee_rate
slippage_bps
```

成交价：

```text
多头买入：base_price * (1 + slippage_bps / 10000)
多头卖出：base_price * (1 - slippage_bps / 10000)
空头开仓：base_price * (1 - slippage_bps / 10000)
空头平仓：base_price * (1 + slippage_bps / 10000)
```

## 11. 风控闸门

模拟盘应有独立 `PaperRiskGate`。

第一版建议支持：

- 最大账户回撤停开
- 连续止损冷却
- 单会话最大持仓数
- 禁止重复同方向开仓
- 账户权益低于阈值停止

风控闸门只决定是否允许执行新开仓，不修改策略信号本身。

被拦截的信号应写入 warnings：

```text
signal generated
  -> risk gate blocked
  -> no order
  -> warning recorded
```

## 12. API 设计

## 12.1 创建模拟盘会话

```http
POST /api/paper-sessions
```

请求：

```json
{
  "stable_candidate_id": "candidate-xxx",
  "source_run_id": "run-xxx",
  "execution_verification_run_id": "ev-run-xxx",
  "initial_cash": 10000,
  "strategy_timeframe": "1h",
  "execution_timeframe": "5m"
}
```

响应：

```json
{
  "paper_session_id": "paper-xxx",
  "status": "created"
}
```

## 12.2 启动 / 暂停 / 停止

```http
POST /api/paper-sessions/{session_id}/start
POST /api/paper-sessions/{session_id}/pause
POST /api/paper-sessions/{session_id}/stop
```

第一版也可以先只做手动 tick，不做常驻 runner。

## 12.3 手动 tick

```http
POST /api/paper-sessions/{session_id}/tick
```

用途：

- 本地调试
- 验证状态机
- 避免第一版就引入复杂 scheduler

## 12.4 查询会话

```http
GET /api/paper-sessions
GET /api/paper-sessions/{session_id}
```

详情返回：

- session
- checkpoint
- account
- open position
- recent orders
- recent fills
- recent trades
- equity summary
- recent warnings

## 13. UI 设计

第一版新增页面：

```text
模拟盘
```

核心视图：

- 会话列表
- 当前状态
- 账户权益
- 当前持仓
- 最近信号
- 最近订单
- 最近成交
- 最近交易
- 资金曲线
- 最近错误

稳定池增加操作：

```text
创建模拟盘
```

但只有满足条件的候选才允许创建：

- 有稳定池候选
- 有最新 execution verification run
- execution verification 状态通过
- 策略参数完整
- 数据源可用

## 14. CLI 设计

为了本地调试，第一版建议提供 CLI：

```bash
.venv/bin/python -m crypto_backtest_workbench.cli paper-create ...
.venv/bin/python -m crypto_backtest_workbench.cli paper-tick --paper-session-id ...
.venv/bin/python -m crypto_backtest_workbench.cli paper-run --paper-session-id ... --interval-seconds 60
```

第一版最关键的是 `paper-tick`。

原因：

- 可重复执行
- 可观察每一步落盘结果
- 方便排查数据源失败

## 15. 任务与调度

第一版不引入外部队列。

推荐顺序：

1. 手动 tick
2. 本地后台线程 runner
3. 持久任务中心
4. 外部 scheduler 或 daemon

常驻 runner 的最小行为：

```text
while session.status == running:
  run tick
  sleep interval_seconds
```

每次 tick 必须捕获异常，写入 `session.last_error`，并保留上一次成功 checkpoint。

## 16. 故障处理

### 16.1 数据源失败

例如 Binance 返回 `418` / `429`。

处理：

- 记录 warning
- session 不直接 failed
- 保持 checkpoint 不前进
- 下次 tick 继续尝试

### 16.2 数据缺口

如果发现新 K 线与本地最后 K 线之间存在缺口：

- 尝试补拉缺口
- 补拉失败则阻止策略推进
- 记录 `MARKET_DATA_GAP`

### 16.3 重复启动

同一个 session 不允许多个 runner 同时运行。

第一版可使用文件锁：

```text
data/paper_trading/sessions/<id>/runner.lock
```

### 16.4 崩溃恢复

恢复流程：

```text
读取 session
读取 checkpoint
读取 account / positions
读取 market_data 最后时间
从最后时间之后补拉已收盘 K 线
继续 tick
```

## 17. 验收标准

第一版完成后应满足：

1. 可以从稳定池候选创建 paper session
2. session 能保存配置、账户、checkpoint
3. 能 bootstrap 最近历史 K 线
4. 能手动 tick 拉取新增已收盘 K 线
5. 能在出现新 `1h` bar 时生成策略信号
6. 能用 `5m` bar 推进模拟成交和 SL / TP
7. 能持久化 orders / fills / trades / equity curve
8. 进程重启后能从 checkpoint 继续
9. 数据源失败不会破坏已有状态
10. UI 或 API 能查看当前账户、持仓、交易和错误

## 18. 分阶段实施计划

### Phase A：设计与骨架

- 新增本文档
- 新增 `app/paper_trading/` 模块骨架
- 定义 `PaperSession` / `PaperAccount` / `PaperPosition`
- 定义文件仓储接口

### Phase B：Market Feed

- 实现 REST 轮询 feed
- 支持 bootstrap
- 支持 fetch closed bars since checkpoint
- 支持去重追加
- 支持 Binance 418 / 429 退避

### Phase C：Paper Broker

- 实现单仓位模拟 broker
- 支持 OPEN / CLOSE
- 支持 SL / TP
- 支持手续费与滑点
- 支持权益曲线

### Phase D：Tick Workflow

- 从 session 读取策略配置
- 计算 feature
- 生成新信号
- 推进 broker
- 更新 checkpoint

### Phase E：API / CLI

- `POST /api/paper-sessions`
- `POST /api/paper-sessions/{id}/tick`
- `GET /api/paper-sessions`
- `GET /api/paper-sessions/{id}`
- CLI `paper-tick`

### Phase F：UI

- 模拟盘列表
- 会话详情
- 账户 / 持仓 / 订单 / 成交 / 资金曲线
- 最近错误

### Phase G：常驻 Runner

- 本地后台 runner
- session start / pause / stop
- runner lock
- 错误恢复

## 19. 后续进入实盘前门槛

模拟盘不是实盘。

进入真实交易前至少需要：

- 连续运行一段时间无状态错误
- 交易记录与预期策略行为一致
- 数据源中断恢复正常
- 风控闸门有效
- 模拟盘最大回撤在预期范围内
- 手续费和滑点假设足够保守
- 明确最大亏损预算
- 支持真实交易所只读账户对账
- 支持 dry-run 下单请求审计

真实下单应作为独立后续阶段：

```text
paper broker
  -> exchange testnet broker
  -> live broker with small capital
```

不要从研究系统直接跳到真实下单。

