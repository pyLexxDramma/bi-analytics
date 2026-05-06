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

В Streamlit можно передать секции из st.secrets (ключи host, user, password, remote_dir, port, use_tls).
"""
from __future__ import annotations

import os
import sys
from ftplib import FTP, FTP_TLS, error_perm
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


def _env_config() -> Dict[str, Any]:
    return {
        "host": os.environ.get("BI_FTP_HOST", "").strip(),
        "user": os.environ.get("BI_FTP_USER", "").strip(),
        "password": os.environ.get("BI_FTP_PASSWORD", "").strip(),
        "port": int(os.environ.get("BI_FTP_PORT", "21") or 21),
        "remote_dir": (os.environ.get("BI_FTP_REMOTE_DIR", "/") or "/").strip() or "/",
        "use_tls": os.environ.get("BI_FTP_TLS", "").lower() in ("1", "true", "yes"),
        "timeout": float(os.environ.get("BI_FTP_TIMEOUT", "60") or 60),
    }


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
    # Кириллица в именах: пробуем UTF-8 (многие vsftpd/proftpd отдают UTF8)
    try:
        ftp.encoding = "utf-8"
    except Exception:
        pass
    return ftp


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


def _retrieve(ftp, name: str, dest: Path) -> None:
    """Атомарно скачивает RETR в dest через временный *.tmp.

    Зачем .tmp: если RETR упадёт в середине (на FTP файл занят пишущим
    процессом — приходит 550 Failed to open file), мы НЕ должны затереть
    уже валидный локальный файл нулём байт. Поэтому пишем в tmp, и только
    при успехе переименовываем поверх.
    """
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with tmp.open("wb") as fh:
            try:
                ftp.retrbinary(f"RETR {name}", fh.write)
            except error_perm:
                fh.seek(0)
                fh.truncate()
                safe = name.replace('"', '\\"')
                ftp.retrbinary(f'RETR "{safe}"', fh.write)
        # os.replace атомарен на одном томе и работает на Windows
        os.replace(tmp, dest)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def sync_ftp_to_web(
    web_dir: Path,
    config: Optional[Dict[str, Any]] = None,
    extensions: tuple = (".csv", ".json"),
    progress: Optional[Callable[[str], None]] = None,
    recursive: Optional[bool] = None,
    force_redownload: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Скачивает файлы из remote_dir в web_dir с инкрементальной проверкой размера.

    - Для каждого remote-файла перед загрузкой берём размер (SIZE / MLSD).
      Если локально уже лежит файл такого же размера — пропускаем (skip_same_size).
    - По умолчанию обходим подпапки рекурсивно с сохранением структуры
      (например, /web/AI/msp.csv → web_dir/AI/msp.csv). Это нужно потому, что
      MSP-файлы лежат в /web/AI/, а старая плоская реализация их не подтягивала.
    - Не удаляет локальные файлы.

    Returns:
        {
          "ok": bool,
          "downloaded": [...],         # реально скачанные (новые/изменённые)
          "skipped_same_size": int,    # пропущены, потому что size совпал
          "skipped": int,              # пропущены по фильтру расширений
          "errors": [...],
        }
    """
    out: Dict[str, Any] = {
        "ok": True,
        "downloaded": [],
        "skipped_same_size": 0,
        "skipped": 0,
        "errors": [],
    }
    cfg = merge_ftp_config(config)
    if not cfg.get("host") or not cfg.get("user"):
        out["ok"] = False
        out["errors"].append(
            "FTP не настроен: задайте host и user (BI_FTP_HOST, BI_FTP_USER или секреты)."
        )
        return out

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

    web_dir = Path(web_dir).resolve()
    web_dir.mkdir(parents=True, exist_ok=True)

    remote_dir = cfg.get("remote_dir") or "/"
    if not remote_dir.startswith("/"):
        remote_dir = "/" + remote_dir

    ftp = None
    try:
        ftp = _connect(cfg)
        ftp.cwd(remote_dir)
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

            entries = _list_dir(ftp)
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
                    if recursive:
                        sub_rel = (rel + "/" + name).lstrip("/") if rel else name
                        stack.append(sub_rel)
                    continue

                low = name.lower()
                if not any(low.endswith(ext) for ext in extensions):
                    out["skipped"] += 1
                    continue

                local_path = local_subdir / name
                rel_for_report = str(local_path.relative_to(web_dir)).replace("\\", "/")

                remote_size: Optional[int] = size_hint
                if remote_size is None:
                    remote_size = _safe_size(ftp, name)

                if (
                    not force_redownload
                    and remote_size is not None
                    and local_path.exists()
                    and local_path.stat().st_size == remote_size
                ):
                    out["skipped_same_size"] += 1
                    continue

                try:
                    _log(f"Скачивание {rel_for_report!r}…")
                    _retrieve(ftp, name, local_path)
                    out["downloaded"].append(rel_for_report)
                except Exception as e:
                    out["errors"].append(f"{rel_for_report}: {e}")
                    out["ok"] = False
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
            "remote_dir": block.get("remote_dir", "/"),
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
    for e in r["errors"]:
        print(e, file=sys.stderr)
    return 0 if r["ok"] and not r["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main_cli())
