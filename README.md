# Crypto Backtest Workbench

This repository contains the code for the local research workbench. A fresh `git clone` only includes source code. It does not include the local Python virtualenv, frontend dependencies, frontend build output, or any workspace data under `data/`.

## Prerequisites

- Python `3.11`
- `npm`

## Quick Start

1. Bootstrap the local environment and seed a minimal offline workspace:

```bash
./scripts/bootstrap_local.sh --with-sample-data
```

2. Start the co-hosted UI and API:

```bash
.venv/bin/python -m crypto_backtest_workbench.cli ui --repository-root . --host 127.0.0.1 --port 8501
```

3. Open [http://127.0.0.1:8501](http://127.0.0.1:8501)

## What Bootstrap Does

`./scripts/bootstrap_local.sh` will:

- create `.venv/` if missing
- install Python dependencies from [pyproject.toml](/Users/liangxu/code/lhfx01/pyproject.toml)
- install frontend dependencies from [frontend/package.json](/Users/liangxu/code/lhfx01/frontend/package.json)
- build `frontend/dist/` so `cbw ui` can serve the React app

If `--with-sample-data` is passed, it will also create a local sample workspace in `data/`.

## Sample Workspace

The sample workspace is intentionally small. It is only meant to prove that a new machine can open the UI and inspect a dataset and a run without first connecting to an exchange.

It seeds:

- one `1h` BTC sample dataset
- one `5m` BTC sample dataset
- one sample EMA crossover run

Rebuild the sample workspace manually:

```bash
.venv/bin/python scripts/init_sample_workspace.py --force
```

If you also want to refresh the committed fallback demo snapshot:

```bash
.venv/bin/python scripts/init_sample_workspace.py --force --export-demo
```

## Real Data

The sample workspace is not the same thing as your real research data. Stable-pool candidates, 5m execution verification runs, and experiment batches still need either:

- your real `data/` directory copied from another machine, or
- fresh ingestion and reruns on the current machine

To ingest real market data:

```bash
.venv/bin/python -m crypto_backtest_workbench.cli ingest --exchange binanceusdm --symbol BTC/USDT:USDT --timeframe 1h --since 2024-01-01T00:00:00+00:00
```

## Why A Fresh Clone Was Not Enough

This repository ignores local runtime artifacts in [.gitignore](/Users/liangxu/code/lhfx01/.gitignore):

- `.venv/`
- `node_modules/`
- `dist/`
- `data/`

That is why another machine could receive the code but still be missing the environment, frontend build output, and local workspace data.
