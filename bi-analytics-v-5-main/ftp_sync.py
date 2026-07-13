"""
Скачивание CSV с FTP в локальную папку web/ перед load_all_from_web().

Конфигурация (приоритет: переданный dict > переменные окружения BI_FTP_*):
  BI_FTP_HOST       — хост (например web.conall.ru)
  BI_FTP_USER       — пользователь
  BI_FTP_PASSWORD   — пароль
  BI_FTP_PORT       — порт (по умолчанию 21)
  BI_FTP_REMOTE_DIR — каталог на сервере (часто ``/web``; по умолчанию ``/``)
  BI_FTP_PASSWORD   — пароль; если пусто, берётся ``FTP_AI_PASSWORD`` (совместимость с VS Code SFTP)
  BI_FTP_TLS        — true / 1 для FTPS (AUTH_TLS)
  BI_FTP_TIMEOUT    — таймаут секунд (по умолчанию 60)
  BI_FTP_RECURSIVE  — 1/true (по умолчанию) — рекурсивно обходить подпапки.
                     0/false — только корень remote_dir (старое поведение).
  BI_FTP_FORCE_REDOWNLOAD — 1/true — игнорировать проверку размера и качать всё заново.
                            По умолчанию 0 (инкремент по SIZE).

Расписание выгрузки файлов **на** FTP (1С/MSP/TESSA): **07:00 МСК** ежедневно
(``config.ftp_export_schedule_label()``, переопределение: ``BI_FTP_EXPORT_HOUR_MSK`` /
``BI_FTP_EXPORT_MINUTE_MSK``). Автоподтягивание на VPS — workflow ``ftp-daily-ingest.yml``
(07:15 МСК) или ``scripts/ftp_daily_ingest.sh``.

В Streamlit можно передать секции из st.secrets (ключи host, user, password, remote_dir, port, use_tls).
"""
from __future__ import annotations

import os
import re
import sys
import time
from ftplib import FTP, FTP_TLS, error_perm
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

_FTP_CODE_RE = re.compile(r"(?<!\d)(\d{3})(?!\d)")


def _ftp_sync_lock_path() -> Path:
    """Inter-process lock рядом с web_data.db (Streamlit Cloud: web + worker одновременно)."""
    try:
        from web_loader import WEB_DB_PATH

        base = Path(WEB_DB_PATH).resolve().parent
    except Exception:
        base = Path(".").resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base / ".auto_ingest.lock"


def acquire_ftp_sync_lock(stale_seconds: int = 600) -> tuple[bool, str]:
    """Атомарный lock через O_CREAT|O_EXCL. При успехе вызвать release_ftp_sync_lock() в finally."""
    lock = _ftp_sync_lock_path()
    my_pid = os.getpid()
    if lock.exists():
        try:
            age = time.time() - lock.stat().st_mtime
        except Exception:
            age = 0.0
        try:
            holder_raw = lock.read_text(encoding="utf-8").strip()
        except Exception:
            holder_raw = ""
        try:
            holder_pid = int(holder_raw.splitlines()[0]) if holder_raw else 0
        except Exception:
            holder_pid = 0
        if holder_pid and holder_pid == my_pid:
            return False, f"self_reentry pid={holder_pid}"
        if age < stale_seconds:
            return False, f"locked by pid={holder_raw or '?'} age={age:.0f}s"
        try:
            lock.unlink()
        except Exception:
            pass
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, f"{my_pid}\n".encode("utf-8"))
        finally:
            os.close(fd)
        return True, "acquired"
    except FileExistsError:
        try:
            holder = lock.read_text(encoding="utf-8").strip()
        except Exception:
            holder = "?"
        return False, f"raced by pid={holder}"
    except Exception as e:
        return False, f"lock open failed: {e}"


def release_ftp_sync_lock() -> None:
    try:
        _ftp_sync_lock_path().unlink()
    except Exception:
        pass


def _env_config() -> Dict[str, Any]:
    return {
        "host": os.environ.get("BI_FTP_HOST", "").strip(),
        "user": os.environ.get("BI_FTP_USER", "").strip(),
        "password": os.environ.get("BI_FTP_PASSWORD", "").strip(),
        "port": int(os.environ.get("BI_FTP_PORT", "21") or 21),
        "remote_dir": (os.environ.get("BI_FTP_REMOTE_DIR", "/web") or "/web").strip() or "/web",
        "use_tls": os.environ.get("BI_FTP_TLS", "").lower() in ("1", "true", "yes"),
        "timeout": float(os.environ.get("BI_FTP_TIMEOUT", "120") or 120),
    }


def _excluded_dir_names() -> set[str]:
    """Имена подпапок FTP, которые не обходим (не содержат данных дашборда).

    По умолчанию — веб-каталоги AI-туннеля (``opencode.*``), которые лежат в /web,
    но не относятся к аналитике; их рекурсивный обход давал таймауты. Расширить/
    переопределить: BI_FTP_EXCLUDE_DIRS="dir1,dir2" (регистронезависимо).
    """
    default = {"opencode.conall.ru", "opencode.ai.conall.ru"}
    raw = str(os.environ.get("BI_FTP_EXCLUDE_DIRS", "") or "").strip()
    if not raw:
        return {d.lower() for d in default}
    extra = {p.strip().lower() for p in raw.split(",") if p.strip()}
    return {d.lower() for d in default} | extra


def merge_ftp_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = _env_config()
    if not (cfg.get("password") or "").strip():
        cfg["password"] = os.environ.get("FTP_AI_PASSWORD", "").strip()
    if overrides:
        for k, v in overrides.items():
            if v is None:
                continue
            if k == "use_tls" and isinstance(v, bool):
                cfg[k] = v
                continue
            if isinstance(v, str) and v.strip() == "":
                continue
            cfg[k] = v
    if overrides and overrides.get("port") is not None:
        try:
            cfg["port"] = int(overrides["port"])
        except (TypeError, ValueError):
            pass
    return cfg


def _connect(cfg: Dict[str, Any]):
    timeout = float(cfg.get("timeout") or 60)
    host = cfg["host"]
    port = int(cfg.get("port") or 21)
    user = cfg.get("user") or ""
    password = cfg.get("password") or ""
    if cfg.get("use_tls"):
        ftp = FTP_TLS()
        ftp.connect(host, port, timeout=timeout)
        ftp.login(user, password)
        ftp.prot_p()
    else:
        ftp = FTP()
        ftp.connect(host, port, timeout=timeout)
        ftp.login(user, password)
    # Passive-режим (PASV) явно: за NAT/файрволом активный режим не проходит,
    # это частая причина «cwd/LIST timed out» при успешном connect/login.
    try:
        ftp.set_pasv(True)
    except Exception:
        pass
    # Кириллица в именах: пробуем UTF-8 (многие vsftpd/proftpd отдают UTF8)
    try:
        ftp.encoding = "utf-8"
    except Exception:
        pass
    return ftp


def _connect_with_cwd(cfg: Dict[str, Any], remote_dir: str, *, attempts: int = 3, delay_s: float = 3.0):
    """connect + login + cwd с повтором при таймауте/обрыве.

    FTP-соединение с этим сервером бывает нестабильным (control-канал отвечает
    не сразу). Один timeout на старте не должен ронять всю загрузку — пробуем
    ещё раз с закрытием предыдущего сокета.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(max(1, int(attempts))):
        ftp = None
        try:
            ftp = _connect(cfg)
            ftp.cwd(remote_dir)
            return ftp
        except Exception as e:
            last_exc = e
            try:
                if ftp is not None:
                    ftp.close()
            except Exception:
                pass
            if attempt + 1 >= attempts:
                break
            time.sleep(delay_s)
    raise last_exc if last_exc is not None else RuntimeError("FTP connect failed")


def _list_dir(ftp) -> List[Tuple[str, str, Optional[int]]]:
    """Возвращает содержимое текущего cwd как список (name, kind, size).

    kind: 'file' | 'dir' | 'unknown'
    size: байт для file (если сервер сообщил), иначе None.

    Сначала пробуем MLSD (RFC 3659) — он сразу даёт type+size. Если его нет
    — парсим LIST (UNIX-style). Если и LIST не структурирован — возвращаем NLST,
    тогда тип будет определяться по факту попытки cwd.
    """
    items: List[Tuple[str, str, Optional[int]]] = []
    try:
        for name, facts in ftp.mlsd():
            if name in (".", ".."):
                continue
            t = (facts.get("type") or "").lower()
            kind = "dir" if t in ("dir", "cdir", "pdir") else ("file" if t == "file" else "unknown")
            size: Optional[int] = None
            if facts.get("size") is not None:
                try:
                    size = int(facts["size"])
                except (TypeError, ValueError):
                    size = None
            items.append((name, kind, size))
        return items
    except (error_perm, AttributeError, Exception):
        items = []

    lines: List[str] = []
    try:
        ftp.retrlines("LIST", lines.append)
    except Exception:
        lines = []

    parsed_any = False
    for line in lines:
        if not line:
            continue
        parts = line.split(None, 8)
        if len(parts) >= 9 and (line[:1] in ("-", "d", "l")):
            perm = line[:1]
            name = parts[-1]
            if name in (".", ".."):
                continue
            kind = "dir" if perm == "d" else "file"
            size: Optional[int] = None
            try:
                size = int(parts[4])
            except (TypeError, ValueError):
                size = None
            items.append((name, kind, size))
            parsed_any = True

    if parsed_any:
        return items

    try:
        names = [n for n in ftp.nlst() if n not in (".", "..")]
    except Exception:
        names = []
    for raw in names:
        name = Path(str(raw).strip().replace("\\", "/")).name
        if not name or name in (".", ".."):
            continue
        items.append((name, "unknown", None))
    return items


def _extract_ftp_code(message: str) -> str:
    """Извлекает трёхзначный код ответа FTP/HTTP из текста исключения."""
    m = _FTP_CODE_RE.search(str(message or ""))
    return m.group(1) if m else "неизвестен"


def format_ftp_file_error(rel_path: str, exc: Exception | str) -> str:
    """Читаемое сообщение для логов: «Ошибка экспорта файла <имя>. Код <код>»."""
    stem = Path(str(rel_path).replace("\\", "/")).stem
    msg = str(exc) if not isinstance(exc, Exception) else str(exc)
    code = _extract_ftp_code(msg)
    return f"Ошибка экспорта файла {stem}. Код {code}"


def _stderr_log(message: str) -> None:
    """Пишет в stderr (без зависимости от auto_ingest)."""
    line = message if message.endswith("\n") else message + "\n"
    try:
        buf = getattr(sys.stderr, "buffer", None)
        if buf is not None:
            buf.write(line.encode("utf-8", errors="replace"))
            buf.flush()
            return
    except Exception:
        pass
    try:
        sys.stderr.write(line)
        sys.stderr.flush()
    except Exception:
        pass


def log_ftp_sync_errors(
    result: Optional[Dict[str, Any]],
    *,
    log_fn: Optional[Callable[[str], None]] = None,
    log_prefix: str = "[ftp_sync]",
) -> None:
    """Логирует все per-file и системные ошибки результата sync_ftp_to_web."""
    if not result:
        return
    log = log_fn or _stderr_log
    downloaded = len(result.get("downloaded") or [])
    same = int(result.get("skipped_same_size") or 0)
    transient = result.get("transient_errors") or []
    errors = result.get("errors") or []
    log(
        f"{log_prefix} ftp_sync: downloaded={downloaded}, "
        f"skipped_same_size={same}, transient_errors={len(transient)}, errors={len(errors)}"
    )
    for msg in transient:
        log(f"{log_prefix} {msg}")
    for msg in errors:
        log(f"{log_prefix} {msg}")


def _safe_size(ftp, name: str) -> Optional[int]:
    """ftp.size() в ASCII режиме падает; перед SIZE переключаемся в TYPE I."""
    try:
        ftp.voidcmd("TYPE I")
    except Exception:
        pass
    try:
        return ftp.size(name)
    except Exception:
        try:
            safe = name.replace('"', '\\"')
            return ftp.size(f'"{safe}"')
        except Exception:
            return None


def _is_connection_dead_error(exc: Exception | str) -> bool:
    """421 / обрыв control-канала — сервер закрыл сессию (session/idle limit).

    После такой ошибки текущий FTP-объект непригоден: нужно переподключение,
    иначе все последующие файлы падают с «Код неизвестен» на дохлом сокете.
    """
    if isinstance(exc, (EOFError, ConnectionError, TimeoutError, OSError)):
        return True
    s = str(exc)
    msg = s.lower()
    return (
        "421" in s
        or "closing control connection" in msg
        or "connection reset" in msg
        or "broken pipe" in msg
        or "not connected" in msg
        or "timed out" in msg
        or "cannot read from timed out" in msg
        or "connection refused" in msg
        or "connection aborted" in msg
    )


def _is_transient_ftp_retrieve_error(exc: Exception | str) -> bool:
    """Временная ошибка загрузки: файл занят (550/busy) ИЛИ обрыв соединения (421).

    - 550 / file busy — файл на FTP перезаписывается (1С/MSP ~07:00 и каждые ~15 мин).
    - 421 / обрыв — сервер разорвал сессию; лечится переподключением.
    """
    msg = str(exc).lower()
    return (
        "550" in str(exc)
        or "failed to open" in msg
        or "file unavailable" in msg
        or "busy" in msg
        or _is_connection_dead_error(exc)
    )


def _retrieve(ftp, name: str, dest: Path, *, max_attempts: int = 3, retry_delay_s: float = 2.0) -> None:
    """Атомарно скачивает RETR в dest через уникальный *.part.

    Зачем .part: если RETR упадёт в середине (на FTP файл занят пишущим
    процессом — приходит 550 Failed to open file), мы НЕ должны затереть
    уже валидный локальный файл нулём байт. Поэтому пишем во временный файл,
    и только при успехе переименовываем поверх.

    Имя tmp уникально на процесс (pid + time_ns): на Streamlit Cloud web и
    worker могут одновременно качать один файл — общий ``file.json.tmp`` давал
    ENOENT при os.replace.
    """
    pid_ns = f"{os.getpid()}.{time.time_ns()}"
    last_exc: Optional[Exception] = None
    for attempt in range(max(1, int(max_attempts))):
        tmp: Optional[Path] = dest.with_name(f"{dest.name}.{pid_ns}.{attempt}.part")
        try:
            with tmp.open("wb") as fh:
                try:
                    ftp.retrbinary(f"RETR {name}", fh.write)
                except error_perm:
                    fh.seek(0)
                    fh.truncate()
                    safe = name.replace('"', '\\"')
                    ftp.retrbinary(f'RETR "{safe}"', fh.write)
            if not tmp.exists():
                raise OSError(f"FTP download incomplete: temp file missing for {name!r}")
            os.replace(tmp, dest)
            tmp = None
            return
        except Exception as e:
            last_exc = e
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
                tmp = None
            if attempt + 1 >= max_attempts or not _is_transient_ftp_retrieve_error(e):
                raise
            time.sleep(retry_delay_s)
    if last_exc is not None:
        raise last_exc


def sync_ftp_to_web(
    web_dir: Path,
    config: Optional[Dict[str, Any]] = None,
    extensions: tuple = (".csv", ".json"),
    progress: Optional[Callable[[str], None]] = None,
    recursive: Optional[bool] = None,
    force_redownload: Optional[bool] = None,
    use_interprocess_lock: bool = True,
    prune_orphans: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Скачивает файлы из remote_dir в web_dir с инкрементальной проверкой размера.

    - Для каждого remote-файла перед загрузкой берём размер (SIZE / MLSD).
      Если локально уже лежит файл такого же размера — пропускаем (skip_same_size).
    - По умолчанию обходим подпапки рекурсивно с сохранением структуры
      (например, /web/AI/msp.csv → web_dir/AI/msp.csv). Это нужно потому, что
      MSP-файлы лежат в /web/AI/, а старая плоская реализация их не подтягивала.
    - ``prune_orphans``: если True — после успешного полного листинга удаляет
      локальные файлы (по ``extensions``), которых больше нет на FTP. Удаление
      происходит ТОЛЬКО в папках, реально прочитанных с сервера, и ТОЛЬКО когда
      обход прошёл без критических ошибок (``ok`` и пустой ``errors``) и на
      сервере найден хотя бы один файл — чтобы сбой листинга не стёр локальные
      данные. По умолчанию ВКЛ (BI_FTP_PRUNE_ORPHANS=0 — отключить).

    Returns:
        {
          "ok": bool,
          "downloaded": [...],         # реально скачанные (новые/изменённые)
          "skipped_same_size": int,    # пропущены, потому что size совпал
          "skipped": int,              # пропущены по фильтру расширений
          "deleted": [...],            # локальные файлы, удалённые как отсутствующие на FTP
          "errors": [...],
        }
    """
    out: Dict[str, Any] = {
        "ok": True,
        "downloaded": [],
        "skipped_same_size": 0,
        "skipped": 0,
        "deleted": [],           # удалены локально (нет на FTP) при prune_orphans
        "errors": [],            # критичные (connect / auth / cwd / unexpected)
        "transient_errors": [],  # per-file временные блокировки (550 на занятый файл и т.п.)
    }
    cfg = merge_ftp_config(config)
    if not cfg.get("host") or not cfg.get("user"):
        out["ok"] = False
        out["errors"].append(
            "FTP не настроен: задайте host и user (BI_FTP_HOST, BI_FTP_USER или секреты)."
        )
        return out

    lock_acquired = False
    if use_interprocess_lock:
        lock_acquired, lock_reason = acquire_ftp_sync_lock()
        if not lock_acquired:
            out["ok"] = False
            out["errors"].append(
                f"FTP-sync уже выполняется другим процессом ({lock_reason}). "
                "Подождите завершения и повторите."
            )
            return out

    ftp = None
    try:
        if recursive is None:
            recursive = str(os.environ.get("BI_FTP_RECURSIVE", "1")).strip().lower() not in (
                "0",
                "false",
                "no",
                "off",
            )
        if force_redownload is None:
            force_redownload = str(os.environ.get("BI_FTP_FORCE_REDOWNLOAD", "0")).strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
        if prune_orphans is None:
            # По умолчанию ВКЛ: FTP — источник истины. Если файл удалён с FTP,
            # локальная копия тоже удаляется, и дашборд показывает последний
            # оставшийся файл. Отключить: BI_FTP_PRUNE_ORPHANS=0.
            prune_orphans = str(os.environ.get("BI_FTP_PRUNE_ORPHANS", "1")).strip().lower() not in (
                "0",
                "false",
                "no",
                "off",
            )

        web_dir = Path(web_dir).resolve()
        web_dir.mkdir(parents=True, exist_ok=True)

        remote_dir = cfg.get("remote_dir") or "/"
        if not remote_dir.startswith("/"):
            remote_dir = "/" + remote_dir

        try:
            ftp = _connect_with_cwd(cfg, remote_dir)
        except Exception as e:
            out["ok"] = False
            out["errors"].append(f"FTP подключение или cwd {remote_dir!r}: {e}")
            return out

        def _log(msg: str) -> None:
            if progress:
                try:
                    progress(msg)
                except Exception:
                    pass

        try:
            try:
                ftp.voidcmd("TYPE I")
            except Exception:
                pass

            stack: List[str] = [""]
            seen_dirs: set = set()
            _excluded_dirs = _excluded_dir_names()
            # Для prune_orphans: какие папки реально прочитаны с FTP и какие файлы
            # (rel-путь от web_dir) существуют на сервере.
            dirs_listed_ok: set = set()
            remote_files: set = set()
            pending_retries: list[tuple[str, Path, str]] = []
            while stack:
                rel = stack.pop()
                try:
                    if rel:
                        ftp.cwd(remote_dir.rstrip("/") + "/" + rel)
                    else:
                        ftp.cwd(remote_dir)
                except Exception as e:
                    out["errors"].append(f"cwd {(remote_dir + '/' + rel).rstrip('/')!r}: {e}")
                    out["ok"] = False
                    continue

                if rel in seen_dirs:
                    continue
                seen_dirs.add(rel)

                local_subdir = web_dir / rel if rel else web_dir
                local_subdir.mkdir(parents=True, exist_ok=True)

                try:
                    entries = _list_dir(ftp)
                except Exception as e:
                    out["errors"].append(f"list {(remote_dir + '/' + rel).rstrip('/')!r}: {e}")
                    out["ok"] = False
                    continue

                dirs_listed_ok.add(rel)
                for name, kind, size_hint in entries:
                    if not name or name in (".", ".."):
                        continue

                    if kind == "unknown":
                        try:
                            ftp.cwd(name)
                            ftp.cwd("..")
                            kind = "dir"
                        except error_perm:
                            kind = "file"
                        except Exception:
                            kind = "file"

                    if kind == "dir":
                        if recursive and name.lower() not in _excluded_dirs:
                            sub_rel = (rel + "/" + name).lstrip("/") if rel else name
                            stack.append(sub_rel)
                        continue

                    low = name.lower()
                    if not any(low.endswith(ext) for ext in extensions):
                        out["skipped"] += 1
                        continue

                    local_path = local_subdir / name
                    rel_for_report = str(local_path.relative_to(web_dir)).replace("\\", "/")
                    remote_files.add(rel_for_report)

                    remote_size: Optional[int] = size_hint
                    if remote_size is None:
                        remote_size = _safe_size(ftp, name)

                    # Skip ТОЛЬКО если локальный файл существует, его размер > 0
                    # и совпадает с remote. Файлы 0 байт — это мусор от прошлых
                    # неудачных перекачек, их форсированно перекачиваем.
                    if (
                        not force_redownload
                        and remote_size is not None
                        and remote_size > 0
                        and local_path.exists()
                        and local_path.stat().st_size > 0
                        and local_path.stat().st_size == remote_size
                    ):
                        out["skipped_same_size"] += 1
                        continue

                    try:
                        _log(f"Скачивание {rel_for_report!r}…")
                        _retrieve(ftp, name, local_path)
                        out["downloaded"].append(rel_for_report)
                    except Exception as e:
                        err_line = format_ftp_file_error(rel_for_report, e)
                        if _is_transient_ftp_retrieve_error(e):
                            out["transient_errors"].append(err_line)
                            pending_retries.append((name, local_path, rel_for_report))
                            # Обрыв control-канала (421) — переподключаемся на месте,
                            # иначе все оставшиеся файлы упадут на дохлом сокете.
                            if _is_connection_dead_error(e):
                                try:
                                    try:
                                        ftp.close()
                                    except Exception:
                                        pass
                                    ftp = _connect_with_cwd(cfg, remote_dir)
                                    try:
                                        ftp.voidcmd("TYPE I")
                                    except Exception:
                                        pass
                                    _cur_target = remote_dir.rstrip("/") + (
                                        ("/" + rel) if rel else ""
                                    )
                                    ftp.cwd(_cur_target)
                                except Exception:
                                    pass
                        else:
                            out["errors"].append(err_line)
                            out["ok"] = False

            if pending_retries:
                _log(
                    f"Повторная загрузка {len(pending_retries)} файл(ов) после 550/busy/обрыва…"
                )
                # После 421 control-канал мёртв — переподключаемся перед вторым проходом.
                try:
                    ftp.close()
                except Exception:
                    pass
                try:
                    ftp = _connect_with_cwd(cfg, remote_dir)
                    try:
                        ftp.voidcmd("TYPE I")
                    except Exception:
                        pass
                except Exception as _rc_e:
                    # Не удалось переподключиться — все pending остаются transient.
                    for _n, _lp, _rr in pending_retries:
                        out["transient_errors"].append(format_ftp_file_error(_rr, _rc_e))
                    ftp = None

                retry_stems = {Path(r[2]).stem for r in pending_retries}
                final_transient: list[str] = [
                    x
                    for x in (out.get("transient_errors") or [])
                    if not any(stem in str(x) for stem in retry_stems)
                ]
                seen_retry_stems: set[str] = set()
                for name, local_path, rel_for_report in pending_retries:
                    stem = Path(rel_for_report).stem
                    if ftp is None:
                        if stem not in seen_retry_stems:
                            final_transient.append(
                                format_ftp_file_error(rel_for_report, "нет соединения")
                            )
                            seen_retry_stems.add(stem)
                        continue
                    try:
                        # cwd в папку файла: rel_for_report = путь от web_dir (с подпапками).
                        _parent_rel = os.path.dirname(rel_for_report)
                        _target = remote_dir.rstrip("/") + (
                            ("/" + _parent_rel) if _parent_rel else ""
                        )
                        try:
                            ftp.cwd(_target)
                        except Exception:
                            pass
                        _retrieve(
                            ftp,
                            name,
                            local_path,
                            max_attempts=6,
                            retry_delay_s=5.0,
                        )
                        out["downloaded"].append(rel_for_report)
                    except Exception as e:
                        # На обрыве во втором проходе — переподключаемся и продолжаем.
                        if _is_connection_dead_error(e):
                            try:
                                try:
                                    ftp.close()
                                except Exception:
                                    pass
                                ftp = _connect_with_cwd(cfg, remote_dir)
                                try:
                                    ftp.voidcmd("TYPE I")
                                except Exception:
                                    pass
                            except Exception:
                                ftp = None
                        err_line = format_ftp_file_error(rel_for_report, e)
                        if _is_transient_ftp_retrieve_error(e):
                            if stem not in seen_retry_stems:
                                final_transient.append(err_line)
                                seen_retry_stems.add(stem)
                        else:
                            out["errors"].append(err_line)
                            out["ok"] = False
                out["transient_errors"] = final_transient

            # Зеркальная очистка: удаляем локальные файлы, которых нет на FTP.
            # Условия безопасности: включён prune_orphans, обход без критических
            # ошибок, на сервере найден хотя бы один файл. Удаляем только в папках,
            # реально прочитанных с FTP (dirs_listed_ok), и только по extensions.
            if prune_orphans and out["ok"] and not out["errors"] and remote_files:
                for local_file in web_dir.rglob("*"):
                    try:
                        if not local_file.is_file():
                            continue
                        low = local_file.name.lower()
                        if not any(low.endswith(ext) for ext in extensions):
                            continue
                        rel_file = str(local_file.relative_to(web_dir)).replace("\\", "/")
                        parent_rel = str(local_file.parent.relative_to(web_dir)).replace("\\", "/")
                        if parent_rel == ".":
                            parent_rel = ""
                        if parent_rel not in dirs_listed_ok:
                            continue
                        if rel_file in remote_files:
                            continue
                        local_file.unlink()
                        out["deleted"].append(rel_file)
                        _log(f"Удалён локальный файл (нет на FTP): {rel_file!r}")
                    except Exception as e:
                        out["errors"].append(f"prune {local_file!s}: {e}")
        finally:
            try:
                if ftp:
                    ftp.quit()
            except Exception:
                try:
                    if ftp:
                        ftp.close()
                except Exception:
                    pass
    finally:
        if lock_acquired:
            release_ftp_sync_lock()

    return out


def streamlit_secrets_to_config() -> Optional[Dict[str, Any]]:
    """Если вызвано из Streamlit и в secrets есть секция [ftp] / FTP — вернуть dict."""
    try:
        import streamlit as st  # type: ignore

        sec = getattr(st, "secrets", None)
        if not sec:
            return None
        block = sec.get("ftp") or sec.get("FTP")
        if not block:
            return None
        return {
            "host": block.get("host"),
            "user": block.get("user"),
            "password": block.get("password"),
            "port": block.get("port"),
            "remote_dir": block.get("remote_dir", "/web"),
            "use_tls": bool(block.get("use_tls", False)),
            "timeout": block.get("timeout", 60),
        }
    except Exception:
        return None


def main_cli() -> int:
    """python -m ftp_sync — тест из venv с переменными окружения."""
    from web_loader import get_web_dir

    cfg = merge_ftp_config()
    web = get_web_dir()

    def _p(msg: str) -> None:
        print(msg, file=sys.stderr)

    r = sync_ftp_to_web(web, config=cfg, progress=_p)
    print(
        f"ok={r['ok']} downloaded={len(r['downloaded'])} "
        f"skipped_same_size={r.get('skipped_same_size', 0)} "
        f"skipped_ext={r.get('skipped', 0)}"
    )
    for x in r["downloaded"]:
        print(x)
    log_ftp_sync_errors(r, log_prefix="[ftp_sync]")
    return 0 if r["ok"] and not r["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main_cli())
