"""
Лёгкий смоук: компиляция dashboards, импорт _renderers и get_dashboards.
Запуск из каталога bi-analytics-v-5-main:
  venv\\Scripts\\python scripts/smoke_dashboards.py
"""
from __future__ import annotations

import compileall
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_ROOT)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    if not compileall.compile_dir(_ROOT / "dashboards", quiet=1):
        print("FAIL: compileall dashboards")
        return 1
    try:
        from dashboards import get_dashboards
        d = get_dashboards()
        assert isinstance(d, dict) and len(d) > 5
    except Exception as e:
        print("FAIL: get_dashboards:", e)
        return 1
    try:
        import dashboards._renderers as r  # noqa: F401
    except Exception as e:
        print("FAIL: import _renderers:", e)
        return 1
    print("OK: smoke_dashboards (compile + import)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
