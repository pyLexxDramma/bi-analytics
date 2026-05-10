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
from typing import Any, Dict

_AUTO_INGEST_DONE_IN_PROCESS = False


def _flag(name: str, default: str = "") -> bool:
    raw = str(os.environ.get(name, default)).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _maybe_secrets_to_env() -> None:
    """Streamlit Cloud отдаёт секреты через st.secrets, не через os.environ.
    Прокинем в env нужные ключи, чтобы:
      - ftp_sync.merge_ftp_config() подхватил их единообразно с локальным режимом;
      - наш _flag() мог проверить BI_ANALYTICS_AUTO_INGEST через os.environ.

    Поддерживаем три способа задания одного ключа в Streamlit Cloud Secrets:
      1) полное имя на верхнем уровне:           BI_ANALYTICS_AUTO_INGEST = "1"
      2) короткое имя в [ftp]:                   [ftp]\nauto_ingest = "1"
      3) короткое имя на верхнем уровне:         auto_ingest = "1"
    Первый вариант — рекомендованный (как привычные env-переменные).
    """
    try:
        import streamlit as st  # type: ignore
        secrets = getattr(st, "secrets", None)
        if not secrets:
            return
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
            "BI_ANALYTICS_HIDE_DEV_DIAGNOSTICS": ("hide_dev_diagnostics",),
            "BI_ANALYTICS_RELEASE_MODE": ("release_mode",),
            "BI_ANALYTICS_AUTO_FTP_ON_START": ("auto_ftp_on_start",),
        }
        for env_key, short_aliases in env_map.items():
            if os.environ.get(env_key):
                continue
            val: Any = None
            # 1) полное имя на верхнем уровне (BI_ANALYTICS_AUTO_INGEST = "1")
            try:
                if env_key in secrets:  # type: ignore[operator]
                    val = secrets[env_key]  # type: ignore[index]
            except Exception:
                pass
            # 2) короткое имя в [ftp] (для ftp-полей и совместимости)
            if val is None and ftp_section is not None:
                for p in short_aliases:
                    try:
                        if p in ftp_section:
                            val = ftp_section[p]
                            break
                    except Exception:
                        pass
            # 3) короткое имя на верхнем уровне (на всякий случай)
            if val is None:
                for p in short_aliases:
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


def _read_marker() -> Dict[str, str]:
    """Прочитать маркер прошлого auto-ingest. Формат: ``key=value`` строки.
    Первой строкой исторически писали int(time.time()) — обрабатываем и его.
    """
    out: Dict[str, str] = {}
    marker = _marker_path()
    if not marker.exists():
        return out
    try:
        text = marker.read_text(encoding="utf-8")
    except Exception:
        return out
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if "=" in s:
            k, v = s.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            # legacy: первая строка — unix timestamp
            out.setdefault("ts", s)
    return out


def _current_app_version_sha() -> str:
    try:
        from app_version import get_app_version_sha

        return get_app_version_sha()
    except Exception:
        return "unknown"


def _need_ingest_by_marker() -> tuple[bool, str]:
    """Решить, нужно ли запускать auto-ingest при текущем cold-start процессе.

    Триггеры (в порядке приоритета):
      1. ``BI_ANALYTICS_AUTO_INGEST_FORCE=1`` — всегда.
      2. Маркер отсутствует — первый старт инстанса.
      3. В маркере другая ``app_version`` (поменялся git-sha / build) —
         перевыкачиваем данные, чтобы не было «код новый, БД старая».
      4. Маркер старше ``BI_ANALYTICS_AUTO_INGEST_AGE_H`` часов (default 12).
    """
    if _flag("BI_ANALYTICS_AUTO_INGEST_FORCE"):
        return True, "FORCE=1"
    marker = _marker_path()
    if not marker.exists():
        return True, "no marker"

    info = _read_marker()
    cur_sha = _current_app_version_sha()
    prev_sha = info.get("app_version") or info.get("sha") or ""
    if cur_sha and prev_sha and cur_sha != prev_sha:
        return True, f"app_version changed: {prev_sha} → {cur_sha}"

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
    return False, f"age {age_h:.1f}h < {max_age:.1f}h, app_version={cur_sha}"


def _clear_streamlit_caches() -> None:
    """Очистить ``st.cache_data`` / ``st.cache_resource`` (если streamlit доступен)."""
    try:
        import streamlit as st  # type: ignore
    except Exception:
        return
    for fn_name in ("cache_data", "cache_resource"):
        try:
            obj = getattr(st, fn_name, None)
            if obj is None:
                continue
            clear = getattr(obj, "clear", None)
            if callable(clear):
                clear()
                print(f"[auto_ingest] cleared st.{fn_name}", file=sys.stderr)
        except Exception as e:
            print(f"[auto_ingest] clear st.{fn_name} failed: {e}", file=sys.stderr)


def _purge_web_dir_artifacts() -> None:
    """Удалить устаревший snapshot БД (``web_data.db``), чтобы load_all_from_web()
    с гарантией создал свежую SUCCESS-версию из текущих ``web/*`` файлов.

    Сами CSV/JSON в ``web/`` не трогаем — они являются источником правды для
    ingest, а очисткой устаревших файлов занимается ``ftp_sync`` (там уже
    есть инкрементальная логика).
    """
    if not _flag("BI_ANALYTICS_AUTO_INGEST_PURGE_DB", default="1"):
        return
    try:
        from web_loader import WEB_DB_PATH

        p = Path(WEB_DB_PATH)
        if p.exists():
            p.unlink()
            print(f"[auto_ingest] purged stale {p.name}", file=sys.stderr)
        for sidecar in (".db-wal", ".db-shm"):
            sp = p.with_suffix(p.suffix + sidecar) if not p.suffix.endswith(sidecar) else p
            if sp.exists():
                sp.unlink()
    except Exception as e:
        print(f"[auto_ingest] purge web_data.db failed: {e}", file=sys.stderr)


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


def _lock_path() -> Path:
    """Inter-process lock рядом с web_data.db (на эфемерном диске)."""
    try:
        from web_loader import WEB_DB_PATH

        base = Path(WEB_DB_PATH).resolve().parent
    except Exception:
        base = Path(".").resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base / ".auto_ingest.lock"


def _acquire_lock(stale_seconds: int = 600) -> tuple[bool, str]:
    """Атомарный inter-process lock через O_CREAT|O_EXCL.

    Возвращает (acquired, reason). Если acquired=True — текущий процесс
    обязан вызвать _release_lock() в finally.
    Stale-lock (старше N секунд) автоматически удаляется и берётся заново
    (на случай SIGKILL предыдущего инстанса).
    """
    lock = _lock_path()
    if lock.exists():
        try:
            age = time.time() - lock.stat().st_mtime
        except Exception:
            age = 0.0
        if age < stale_seconds:
            try:
                holder = lock.read_text(encoding="utf-8").strip()
            except Exception:
                holder = "?"
            return False, f"locked by pid={holder} age={age:.0f}s"
        # stale — удалим и попробуем взять заново.
        try:
            lock.unlink()
            print(
                f"[auto_ingest] removed stale lock (age={age:.0f}s > {stale_seconds}s)",
                file=sys.stderr,
            )
        except Exception:
            pass
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
        finally:
            os.close(fd)
        return True, "acquired"
    except FileExistsError:
        # Кто-то опередил между exists()-проверкой и open() — это и есть гонка
        # двух процессов Streamlit Cloud. Отдаём управление победителю.
        try:
            holder = lock.read_text(encoding="utf-8").strip()
        except Exception:
            holder = "?"
        return False, f"raced by pid={holder}"
    except Exception as e:
        return False, f"lock open failed: {e}"


def _release_lock() -> None:
    try:
        _lock_path().unlink()
    except Exception:
        pass


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
    # Inter-process lock: Streamlit Cloud стартует web и worker процессы
    # одновременно — без замка оба полезут в FTP и устроят гонку за .tmp.
    # Также защищает от повторного захода в этом же процессе пока ingest идёт
    # фоном (например, Streamlit делает rerun страницы во время начального
    # ingest, и наш in-process flag ещё не выставлен).
    acquired, reason = _acquire_lock()
    if not acquired:
        print(f"[auto_ingest] skip: another process holds lock ({reason})", file=sys.stderr)
        # Ставим in-process flag, чтобы при следующем rerun страницы
        # этот же процесс не писал ту же строку повторно.
        _AUTO_INGEST_DONE_IN_PROCESS = True
        return
    print(f"[auto_ingest] START ({why}, pid={os.getpid()})", file=sys.stderr)
    try:
        # При смене версии приложения снапшот БД может быть «несовместим»
        # (изменилась схема ingest, набор колонок, нормализация и т.п.) —
        # удаляем web_data.db, чтобы заново построить SUCCESS-версию из web/*.
        if "app_version changed" in why:
            _purge_web_dir_artifacts()
        _do_ftp_sync()
        res = _do_load_all()
        # После успешной загрузки данных чистим streamlit-кэши, иначе
        # @st.cache_data будет отдавать старые DataFrame'ы из памяти процесса.
        _clear_streamlit_caches()
        try:
            marker = _marker_path()
            cur_sha = _current_app_version_sha()
            marker.write_text(
                "\n".join(
                    [
                        f"ts={int(time.time())}",
                        f"app_version={cur_sha}",
                        f"version_id={res.get('version_id') if res else None}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception as e:
            print(f"[auto_ingest] marker write failed: {e}", file=sys.stderr)
    finally:
        _release_lock()
        _AUTO_INGEST_DONE_IN_PROCESS = True
        print("[auto_ingest] DONE", file=sys.stderr)
