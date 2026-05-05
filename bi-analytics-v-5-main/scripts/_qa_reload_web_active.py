"""Перезагружает web/ через web_loader и активирует новую версию.

Использует тот же путь, что и UI «Перечитать web/» в сайдбаре.
"""
from __future__ import annotations

import sys
from pathlib import Path

_repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_repo))


def main() -> None:
    from web_loader import load_all_from_web
    from web_schema import get_active_version_id

    print(f"Active before reload: {get_active_version_id()}")
    result = load_all_from_web()
    print(f"Result keys: {sorted(result.keys()) if isinstance(result, dict) else type(result)}")
    print(f"version_id={result.get('version_id') if isinstance(result, dict) else None}")
    print(f"files_loaded={result.get('files_loaded') if isinstance(result, dict) else None}")
    print(f"rows_total={result.get('rows_total') if isinstance(result, dict) else None}")
    print(f"errors={result.get('errors') if isinstance(result, dict) else None}")
    print(f"warns={(result.get('warnings') or [])[:10] if isinstance(result, dict) else None}")
    print(f"Active after reload: {get_active_version_id()}")


if __name__ == "__main__":
    main()
