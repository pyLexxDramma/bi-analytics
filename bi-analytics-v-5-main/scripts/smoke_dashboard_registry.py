"""
Smoke: реестр отчётов — каждое имя из REPORT_CATEGORIES имеет функцию отрисовки.

Запуск из корня приложения (bi-analytics-v-5-main), желательно тем же Python, что и Streamlit:
  .\\venv\\Scripts\\python.exe scripts\\smoke_dashboard_registry.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    from dashboards import (
        REPORT_CATEGORIES,
        _DASHBOARDS_REGISTRY_VERSION,
        get_all_report_names,
        get_dashboards,
    )

    names = get_all_report_names()
    dupes = [k for k, n in Counter(names).items() if n > 1]
    if dupes:
        print("FAIL: дубли имён отчётов в REPORT_CATEGORIES:", dupes)
        return 1

    d = get_dashboards()
    missing = [n for n in names if d.get(n) is None]
    if missing:
        print("FAIL: нет функции отрисовки для:", missing)
        return 1

    print(
        f"OK: {len(names)} отчётов, _DASHBOARDS_REGISTRY_VERSION = {_DASHBOARDS_REGISTRY_VERSION}."
    )
    print("Категории:", len(REPORT_CATEGORIES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
