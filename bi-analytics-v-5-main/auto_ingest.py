"""Автоматический ingest при старте Streamlit-инстанса.

Цель: эфемерный диск Streamlit Cloud не сохраняет `web_data.db` между перезапусками,
а ingest всегда был ручным. После добавления флага `BI_ANALYTICS_AUTO_INGEST=1`
приложение при первом холодном старте инстанса автоматически:

    1) (опционально) подтягивает свежие файлы с FTP в локальную `web/`,
    2) вызывает `load_all_from_web()` — создаёт новую SUCCESS-версию в БД,
       которая сразу становится «активной» через `get_active_version_id()`
       (берёт последнюю `success`).

Поведение управляется переменными окружения / `st.secrets` (через `os.environ`,
который Streamlit Cloud прокидывает из секций `[env]` / `[ftp]` зависимости от
вашей `secrets.toml`):

- `BI_ANALYTICS_AUTO_INGEST` — мастер-флаг (`1`/`true`/`yes` → включено).
- `BI_ANALYTICS_AUTO_INGEST_FTP` — `1`(default) / `0`: вызывать ли `sync_ftp_to_web`
  перед `load_all_from_web` (требует BI_FTP_HOST/USER/PASSWORD).
- `BI_ANALYTICS_AUTO_INGEST_AGE_H` — повтор только если предыдущий auto-ingest
  старше N часов (default `12`). 0 = всегда при старте инстанса (когда нет маркера).
- `BI_ANALYTICS_AUTO_INGEST_FORCE` — `1` → игнорировать маркер, ingest каждый старт.

Безопасность:
- Маркер хранится **рядом с web_db_path** на эфемерном диске → при пересоздании
  инстанса Streamlit Cloud ingest повторится (что и нужно).
- Любые ошибки логируются в stderr, но не падают приложение — UI запустится
  даже если FTP/ingest упал.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

_AUTO_INGEST_DONE_IN_PROCESS = False


def _flag(name: str, default: str = "") -> bool:
    raw = str(os.environ.get(name, default)).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _maybe_secrets_to_env() -> None:
    """Streamlit Cloud отдаёт секреты через st.secrets, не через os.environ.
    Прокинем в env только нужные ключи (host/user/password/...), чтобы
    `ftp_sync.merge_ftp_config()` подхватил их единообразно с локальным режимом.
    """
    try:
        import streamlit as st  # type: ignore
        secrets = getattr(st, "secrets", None)
        if not secrets:
            return
        # Поддерживаем оба варианта: плоский и секцию [ftp].
        ftp_section: Any = None
        try:
            ftp_section = secrets.get("ftp")  # type: ignore[attr-defined]
        except Exception:
            ftp_section = None
        env_map = {
            "BI_FTP_HOST": ("host",),
            "BI_FTP_USER": ("user",),
            "BI_FTP_PASSWORD": ("password",),
            "BI_FTP_PORT": ("port",),
            "BI_FTP_REMOTE_DIR": ("remote_dir",),
            "BI_FTP_USE_TLS": ("use_tls",),
            "BI_ANALYTICS_AUTO_INGEST": ("auto_ingest",),
            "BI_ANALYTICS_AUTO_INGEST_FTP": ("auto_ingest_ftp",),
            "BI_ANALYTICS_AUTO_INGEST_AGE_H": ("auto_ingest_age_h",),
            "BI_ANALYTICS_AUTO_INGEST_FORCE": ("auto_ingest_force",),
            "BI_ANALYTICS_IGNORE_DEMO": ("ignore_demo",),
        }
        for env_key, paths in env_map.items():
            if os.environ.get(env_key):
                continue
            val: Any = None
            for p in paths:
                if ftp_section is not None:
                    try:
                        if p in ftp_section:
                            val = ftp_section[p]
                            break
                    except Exception:
                        pass
                try:
                    if p in secrets:  # type: ignore[operator]
                        val = secrets[p]  # type: ignore[index]
                        break
                except Exception:
                    pass
            if val is not None and str(val).strip() != "":
                os.environ[env_key] = str(val)
    except Exception:
        # Streamlit может быть не импортирован (CLI).
        pass


def _marker_path() -> Path:
    """Маркер «auto-ingest уже сделан в этом инстансе»."""
    try:
        from web_loader import WEB_DB_PATH

        base = Path(WEB_DB_PATH).resolve().parent
    except Exception:
        base = Path(".").resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base / ".auto_ingest_done.txt"


def _need_ingest_by_marker() -> tuple[bool, str]:
    if _flag("BI_ANALYTICS_AUTO_INGEST_FORCE"):
        return True, "FORCE=1"
    marker = _marker_path()
    if not marker.exists():
        return True, "no marker"
    try:
        age_h = (time.time() - marker.stat().st_mtime) / 3600.0
    except Exception:
        return True, "marker stat failed"
    try:
        max_age = float(os.environ.get("BI_ANALYTICS_AUTO_INGEST_AGE_H", "12") or "12")
    except ValueError:
        max_age = 12.0
    if max_age <= 0:
        return True, "age limit = 0"
    if age_h >= max_age:
        return True, f"age {age_h:.1f}h >= {max_age:.1f}h"
    return False, f"age {age_h:.1f}h < {max_age:.1f}h"


def _do_ftp_sync() -> dict | None:
    if not _flag("BI_ANALYTICS_AUTO_INGEST_FTP", default="1"):
        return None
    if not (os.environ.get("BI_FTP_HOST") and os.environ.get("BI_FTP_USER")):
        print("[auto_ingest] FTP host/user not set → пропуск FTP-sync", file=sys.stderr)
        return None
    try:
        from ftp_sync import sync_ftp_to_web
        from web_loader import get_web_dir

        web_dir = get_web_dir()
        result = sync_ftp_to_web(web_dir)
        downloaded = len(result.get("downloaded", []))
        same = result.get("skipped_same_size", 0)
        errs = result.get("errors", [])
        print(
            f"[auto_ingest] ftp_sync: downloaded={downloaded}, "
            f"skipped_same_size={same}, errors={len(errs)}",
            file=sys.stderr,
        )
        for e in errs[:5]:
            print(f"[auto_ingest] ftp err: {e}", file=sys.stderr)
        return result
    except Exception as e:
        print(f"[auto_ingest] ftp_sync exception: {e}", file=sys.stderr)
        return None


def _do_load_all() -> dict | None:
    try:
        from web_schema import init_web_schema
        from web_loader import load_all_from_web, web_dir_exists

        init_web_schema()
        if not web_dir_exists():
            print("[auto_ingest] web/ dir not found → пропуск load_all_from_web", file=sys.stderr)
            return None
        result = load_all_from_web()
        print(
            f"[auto_ingest] load_all_from_web: loaded={result.get('loaded', 0)}, "
            f"skipped={result.get('skipped', 0)}, version_id={result.get('version_id')}",
            file=sys.stderr,
        )
        for e in (result.get("errors") or [])[:5]:
            print(f"[auto_ingest] ingest err: {e}", file=sys.stderr)
        return result
    except Exception as e:
        print(f"[auto_ingest] load_all_from_web exception: {e}", file=sys.stderr)
        return None


def maybe_run_auto_ingest_on_startup() -> None:
    """Запустить auto-ingest при первом старте процесса (idempotent в рамках процесса)."""
    global _AUTO_INGEST_DONE_IN_PROCESS
    if _AUTO_INGEST_DONE_IN_PROCESS:
        return
    _maybe_secrets_to_env()
    if not _flag("BI_ANALYTICS_AUTO_INGEST"):
        return
    need, why = _need_ingest_by_marker()
    if not need:
        print(f"[auto_ingest] skip: {why}", file=sys.stderr)
        _AUTO_INGEST_DONE_IN_PROCESS = True
        return
    print(f"[auto_ingest] START ({why})", file=sys.stderr)
    _do_ftp_sync()
    res = _do_load_all()
    try:
        marker = _marker_path()
        marker.write_text(
            f"{int(time.time())}\nversion_id={res.get('version_id') if res else None}\n",
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[auto_ingest] marker write failed: {e}", file=sys.stderr)
    _AUTO_INGEST_DONE_IN_PROCESS = True
    print("[auto_ingest] DONE", file=sys.stderr)
