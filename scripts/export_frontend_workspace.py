from __future__ import annotations

import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPOSITORY_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from crypto_backtest_workbench.app.readmodels import (  # noqa: E402
    build_workspace_snapshot,
    json_ready,
)


def main() -> None:
    data_dir = REPOSITORY_ROOT / "data"
    payload = build_workspace_snapshot(data_dir=data_dir)
    output_path = REPOSITORY_ROOT / "frontend" / "public" / "demo" / "workspace.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(json_ready(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Exported frontend workspace snapshot to {output_path}")


if __name__ == "__main__":
    main()
