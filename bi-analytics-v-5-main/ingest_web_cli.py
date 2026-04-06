#!/usr/bin/env python3
"""
Загрузка CSV из web/ в data/web_data.db без браузера (для локальной подготовки данных).
Запуск: python ingest_web_cli.py
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

_app_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_app_dir))


class _FakeSessionState:
    """Минимальная замена st.session_state для вызова load_all_from_web() вне Streamlit."""

    def __init__(self) -> None:
        self._d: dict = {}

    def __contains__(self, k: object) -> bool:
        return k in self._d

    def __getitem__(self, k: str):
        return self._d[k]

    def __setitem__(self, k: str, v) -> None:
        self._d[k] = v

    def get(self, k: str, default=None):
        return self._d.get(k, default)

    def pop(self, k: str, default=None):
        return self._d.pop(k, default) if k in self._d else default

    def __getattr__(self, name: str):
        if name == "_d" or name.startswith("__"):
            raise AttributeError(name)
        return self._d.get(name)

    def __setattr__(self, name: str, value) -> None:
        if name == "_d":
            object.__setattr__(self, "_d", value)
        else:
            if not hasattr(self, "_d"):
                object.__setattr__(self, "_d", {})
            self._d[name] = value


_mock_st = types.ModuleType("streamlit")
_mock_st.session_state = _FakeSessionState()
_mock_st.error = lambda *a, **kw: print("ERROR:", *a, file=sys.stderr)
_mock_st.warning = lambda *a, **kw: print("WARN:", *a, file=sys.stderr)
_mock_st.cache_data = lambda *a, **kw: (lambda f: f)
sys.modules["streamlit"] = _mock_st

from web_schema import init_web_schema  # noqa: E402
from web_loader import load_all_from_web, web_dir_exists  # noqa: E402


def main() -> int:
    init_web_schema()
    if not web_dir_exists():
        print("Папка web/ не найдена рядом с приложением.", file=sys.stderr)
        return 1
    result = load_all_from_web()
    print(
        f"Файлов загружено: {result['loaded']}, пропущено: {result['skipped']}, "
        f"version_id: {result['version_id']}"
    )
    for err in result["errors"]:
        print(err, file=sys.stderr)
    return 0 if result["version_id"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
