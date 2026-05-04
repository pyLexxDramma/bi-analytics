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

В Streamlit можно передать секции из st.secrets (ключи host, user, password, remote_dir, port, use_tls).
"""
from __future__ import annotations

import os
import sys
from ftplib import FTP, FTP_TLS, error_perm
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


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


def sync_ftp_to_web(
    web_dir: Path,
    config: Optional[Dict[str, Any]] = None,
    extensions: tuple = (".csv", ".json"),
    progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Скачивает все файлы с расширениями из extensions из remote_dir в web_dir (плоский список).
    Не удаляет старые локальные файлы — только перезаписывает совпадающие имена.

    Returns:
        {"ok": bool, "downloaded": [...], "errors": [...], "skipped": int}
    """
    out: Dict[str, Any] = {
        "ok": True,
        "downloaded": [],
        "errors": [],
        "skipped": 0,
    }
    cfg = merge_ftp_config(config)
    if not cfg.get("host") or not cfg.get("user"):
        out["ok"] = False
        out["errors"].append(
            "FTP не настроен: задайте host и user (BI_FTP_HOST, BI_FTP_USER или секреты)."
        )
        return out

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
            progress(msg)

    try:
        # nlst быстрее, но на части серверов падает на кириллице — тогда LIST
        try:
            names = [n for n in ftp.nlst() if n not in (".", "..")]
        except error_perm:
            lines: List[str] = []
            ftp.retrlines("LIST", lines.append)
            names = []
            for line in lines:
                parts = line.split(None, 8)
                if len(parts) >= 9:
                    names.append(parts[-1])
            if not names:
                names = lines

        for raw_name in names:
            name = Path(str(raw_name).strip().replace("\\", "/")).name
            if not name or name in (".", ".."):
                continue
            low = name.lower()
            if not any(low.endswith(ext) for ext in extensions):
                out["skipped"] += 1
                continue
            local_path = web_dir / name
            try:
                _log(f"Скачивание {name!r}…")

                with local_path.open("wb") as fh:
                    cmd = f"RETR {name}"
                    try:
                        ftp.retrbinary(cmd, fh.write)
                    except error_perm:
                        # Имя с пробелами / спецсимволами — в кавычках
                        fh.seek(0)
                        fh.truncate()
                        safe = name.replace('"', '\\"')
                        ftp.retrbinary(f'RETR "{safe}"', fh.write)
                out["downloaded"].append(str(local_path.relative_to(web_dir)))
            except Exception as e:
                out["errors"].append(f"{name}: {e}")
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
    print(f"ok={r['ok']} downloaded={len(r['downloaded'])} skipped={r['skipped']}")
    for x in r["downloaded"]:
        print(x)
    for e in r["errors"]:
        print(e, file=sys.stderr)
    return 0 if r["ok"] and not r["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main_cli())
