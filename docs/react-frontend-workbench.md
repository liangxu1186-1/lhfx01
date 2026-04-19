# React 前端工程说明

## 目的

当前仓库已经有 Python 回测内核和 Streamlit 原型。

当前方向已经明确为：

- 用 React 替换当前页面层
- Python 保留 engine / storage / workflow
- 增加一个轻 API 层服务 React

本次新增内容的目标是：

- 在不影响现有 Python 回测内核的前提下，完成页面层替换
- 把工作台主界面迁到 React
- 用轻 API 暴露 workspace / ingest / run-ema
- 让图表、表格、筛选区都在前端可控

## 当前范围

当前 React 工程已经覆盖：

- 执行台
- 运行总览
- 单次分析
- 参数实验

当前 Python 轻 API 已提供：

- `GET /api/datasets`
- `GET /api/overview`
- `GET /api/runs`
- `GET /api/runs/<run_id>`
- `GET /api/parameters`
- `GET /api/workspace`
- `POST /api/ingest`
- `POST /api/run-ema`

当前仍不包含：

- WebSocket / 任务轮询
- 登录、权限、多用户
- 参数实验任务提交

## 目录

```text
frontend/
  public/demo/workspace.json
  src/
    components/
    lib/
```

```text
scripts/
  export_frontend_workspace.py
```

```text
src/crypto_backtest_workbench/app/
  api.py
  readmodels/
```

## 技术栈

页面层：

- React
- Ant Design
- Plotly
- TanStack Table

后端页面服务层：

- Python 标准库 HTTP server
- 现有 `workflow / readmodel / storage repository`

## 数据流

当前运行时主数据流是：

```text
React
-> /api/datasets + /api/runs
-> 按页签继续请求 /api/overview /api/runs/<run_id> /api/parameters
-> app/readmodels/*
-> data/runs + data/datasets
```

执行动作流是：

```text
React
-> POST /api/ingest 或 POST /api/run-ema
-> app/api.py
-> workflow
-> engine / storage
```

静态快照仍保留，作为无 API 时的 fallback：

```text
data/ 下已有 dataset / run 产物
-> scripts/export_frontend_workspace.py
-> frontend/public/demo/workspace.json
-> React 页面 fetch 该静态快照
```

这样做的目的不是替代 API，而是：

- 允许前端在没有后端进程时继续做静态验证
- 保留一个可回放的 demo workspace

## 前端状态约定

当前 React 页面已把核心页面状态落到 URL query 中：

- `tab`：当前页签，值为 `execution` / `overview` / `analysis` / `parameters`
- `run`：分析页当前选中的 `run_id`
- `compare`：总览页资金曲线对比 run 列表，逗号分隔
- `overviewQuery`：总览页搜索词
- `parameterQuery`：参数实验页搜索词

这保证：

- 刷新页面后还能恢复当前视图
- 大屏演示时能稳定回到同一状态
- 可以直接复制 URL 分享当前分析上下文

## 本地使用

先构建 React 前端：

```bash
cd frontend
npm install
npm run build
```

然后启动统一 UI 服务：

```bash
./.venv/bin/python -m crypto_backtest_workbench.cli ui --repository-root . --host 127.0.0.1 --port 8501
```

若只想单独跑 API：

```bash
./.venv/bin/python -m crypto_backtest_workbench.cli api --repository-root . --host 127.0.0.1 --port 8000
```

旧的 Streamlit 入口仍保留为：

```bash
./.venv/bin/python -m crypto_backtest_workbench.cli ui-streamlit --repository-root .
```

可选：更新静态前端快照：

```bash
./.venv/bin/python scripts/export_frontend_workspace.py
```

前端本地开发模式：

```bash
cd frontend
npm run dev
```

若只想更新静态快照，也可以在 `frontend/` 下运行：

```bash
npm run export-demo
```

若要验证生产构建：

```bash
cd frontend
npm run build
```

## 下一步建议

下一步优先做：

1. 把 Plotly 按页面或图表做懒加载，压缩当前较大的前端 bundle。
2. 把总览和参数实验筛选继续下推到服务端查询参数，减少大 workspace 下的前端过滤成本。
3. 把参数实验提交和任务状态轮询接进 API。
4. 视情况再引入正式路由库，把分析页拆成更明确的独立 URL。
