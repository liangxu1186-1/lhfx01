# 参考仓库笔记

## 范围

这些仓库是本地只读参考仓库，用于辅助工程设计。

它们不是当前项目的实现基础。

当前项目的主设计依据仍然是：

- [crypto-backtest-workbench-v1-implementation-design.md](/Users/liangxu/code/lhfx01/docs/crypto-backtest-workbench-v1-implementation-design.md)
- [REFERENCE_USAGE.md](/Users/liangxu/code/lhfx01/docs/REFERENCE_USAGE.md)

## 已固定参考仓库

### Freqtrade

- 路径：`/Users/liangxu/code/lhfx01/references/freqtrade`
- 版本：commit `c1795c79f3fa8b762e98a7baee4daa5dd272e727`

建议重点参考：

- 项目 / 模块目录组织
- 回测命令流
- 策略注册和策略类形态
- 配置分层方式
- hyperopt 工作流边界

不建议带入当前项目：

- bot 生命周期假设
- telegram / 运行控制层
- live / dry trading 语义
- 超出当前项目 v1 边界的 stop/limit 逻辑

### vectorbt

- 路径：`/Users/liangxu/code/lhfx01/references/vectorbt`
- 版本：commit `993ceca7116fc8e55f4cd3a36fe43d83dab62b27`

建议重点参考：

- portfolio / trade / drawdown 分析对象
- 参数扫描组织方式
- 向量化实验思路
- 分析结果打包方式

不建议带入当前项目：

- 整体框架继承
- 许可证敏感代码的直接复制
- 用它替换本项目本地定义的 `RunManifest` / `FeatureArtifact`

## 实际使用规则

当 Codex 结合这些参考仓库编码时，应遵守：

1. 参考仓库是用来学结构，不是继承框架身份。
2. 优先本地小粒度重实现，而不是复制代码。
3. 如果参考仓库和本地设计冲突，以本地设计为准。
4. 当前项目 v1 边界必须保持收敛：
   - 不做 stop/tp
   - 不引入 limit order 语义
   - 不引入 live trading 生命周期
5. 参考仓库主要用于：
   - 命名
   - 模块边界
   - 工作流拆解
   - 分析对象设计

## 推荐优先查看的位置

### Freqtrade

- `freqtrade/optimize/`
- `freqtrade/strategy/`
- `freqtrade/data/`
- `freqtrade/commands/`

### vectorbt

- `vectorbt/portfolio/`
- `vectorbt/records/`
- `vectorbt/generic/`
- `examples/`
