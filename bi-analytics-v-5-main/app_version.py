"""Идентификатор «версии приложения» для единого состояния dev / release / localhost.

Зачем:
- Streamlit Cloud сохраняет ``web/`` и ``web_data.db`` на эфемерном диске.
  При cold start на новой машине данные пустые, при rerun на той же машине —
  старые. Без явного маркера пользователь видит несоответствие «код новый,
  данные старые» (или наоборот), и старые версии из in-process / browser-кэша
  затирают свежие правки.
- Сравнивая «версию приложения» при каждом старте с тем, что записано в
  маркере auto-ingest и в ``st.session_state``, можно:
    * принудительно перевыкачать данные (auto_ingest force) при смене кода,
    * очистить ``st.cache_data`` / ``st.cache_resource`` для текущей сессии,
    * показать клиенту в footer/sidebar явный бейдж версии.

Источники версии (по приоритету):
    1) ``BI_ANALYTICS_BUILD_VERSION`` из env / st.secrets — самый явный (CI / Cloud).
    2) ``_build_info.json`` рядом с этим файлом (можно записать на этапе деплоя).
    3) ``git rev-parse --short HEAD`` + ``git log -1 --format=%cI`` (если git доступен).
    4) mtime самого крупного исходника (`project_visualization_app.py`) — fallback
       на голом окружении, чтобы версия всё равно менялась при выкатывании.

Возвращаемая структура — словарь ``{"sha", "ts", "label", "source"}`` —
дружелюбная для логов / UI. Все функции защищены от исключений: если ничего
не доступно, вернётся «unknown» и приложение продолжит работу.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

_APP_DIR = Path(__file__).resolve().parent
_BUILD_INFO_PATH = _APP_DIR / "_build_info.json"
_FALLBACK_FILE = _APP_DIR / "project_visualization_app.py"

VERSION_ENV_VAR = "BI_ANALYTICS_BUILD_VERSION"
VERSION_TS_ENV_VAR = "BI_ANALYTICS_BUILD_TS"


def _try_env() -> Optional[Dict[str, str]]:
    sha = (os.environ.get(VERSION_ENV_VAR) or "").strip()
    if not sha:
        return None
    ts = (os.environ.get(VERSION_TS_ENV_VAR) or "").strip()
    return {"sha": sha[:16], "ts": ts, "source": "env"}


def _try_build_info() -> Optional[Dict[str, str]]:
    if not _BUILD_INFO_PATH.exists():
        return None
    try:
        data = json.loads(_BUILD_INFO_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    sha = str(data.get("sha") or data.get("commit") or "").strip()
    ts = str(data.get("ts") or data.get("date") or data.get("built_at") or "").strip()
    if not sha:
        return None
    return {"sha": sha[:16], "ts": ts, "source": "build_info"}


def _try_git() -> Optional[Dict[str, str]]:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short=10", "HEAD"],
            cwd=str(_APP_DIR),
            stderr=subprocess.DEVNULL,
            timeout=4,
        ).decode("utf-8", errors="ignore").strip()
        if not sha:
            return None
        try:
            ts = subprocess.check_output(
                ["git", "log", "-1", "--format=%cI"],
                cwd=str(_APP_DIR),
                stderr=subprocess.DEVNULL,
                timeout=4,
            ).decode("utf-8", errors="ignore").strip()
        except Exception:
            ts = ""
        return {"sha": sha[:16], "ts": ts, "source": "git"}
    except Exception:
        return None


def _try_mtime_fallback() -> Dict[str, str]:
    try:
        target = _FALLBACK_FILE if _FALLBACK_FILE.exists() else _APP_DIR
        mtime = target.stat().st_mtime
        ts = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sha = f"mt{int(mtime)}"
        return {"sha": sha, "ts": ts, "source": "mtime"}
    except Exception:
        return {"sha": "unknown", "ts": "", "source": "fallback"}


@lru_cache(maxsize=1)
def get_app_version() -> Dict[str, str]:
    """Стабильный идентификатор текущей сборки (кэшируется на процесс).

    Возвращает словарь с ключами ``sha``, ``ts``, ``source`` и человекочитаемым
    ``label`` (например ``"v 99ffd4061a · 2026-05-10T08:42Z"``).
    """
    info: Optional[Dict[str, str]] = (
        _try_env() or _try_build_info() or _try_git() or _try_mtime_fallback()
    )
    info = dict(info)  # type: ignore[arg-type]
    sha = (info.get("sha") or "unknown")[:16]
    ts = info.get("ts") or ""
    source = info.get("source") or "unknown"
    short_ts = ""
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            short_ts = dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
        except Exception:
            short_ts = ts
    label = f"v {sha}" + (f" · {short_ts}" if short_ts else "")
    return {"sha": sha, "ts": ts, "source": source, "label": label}


def get_app_version_sha() -> str:
    return get_app_version().get("sha", "unknown")


def get_app_version_label() -> str:
    return get_app_version().get("label", "v unknown")


def reset_app_version_cache() -> None:
    """Сбросить кэш — нужно после ручной перезаписи _build_info.json."""
    try:
        get_app_version.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass


if __name__ == "__main__":
    info = get_app_version()
    json.dump(info, sys.stdout, ensure_ascii=False, indent=2)
    print()
