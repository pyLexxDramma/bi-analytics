"""Однократный sync FTP -> локальная web/.

Читает .streamlit/secrets.toml (секция [ftp]) и качает свежие файлы.
Запуск:
    python scripts/_qa_ftp_sync_local.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import tomllib  # py311+
except ImportError:
    import tomli as tomllib  # type: ignore

from ftp_sync import merge_ftp_config, sync_ftp_to_web
from web_loader import get_web_dir


def load_ftp_secrets() -> dict:
    secrets_path = ROOT / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        print(f"ERROR: {secrets_path} не найден.", file=sys.stderr)
        print("Создай его по шаблону:", file=sys.stderr)
        print("[ftp]", file=sys.stderr)
        print('host = "..."', file=sys.stderr)
        print('user = "..."', file=sys.stderr)
        print('password = "..."', file=sys.stderr)
        print("port = 21", file=sys.stderr)
        print('remote_dir = "/web"', file=sys.stderr)
        print("use_tls = false", file=sys.stderr)
        sys.exit(2)
    with open(secrets_path, "rb") as f:
        data = tomllib.load(f)
    block = data.get("ftp") or data.get("FTP") or {}
    if not block:
        print("ERROR: в secrets.toml нет секции [ftp]", file=sys.stderr)
        sys.exit(2)
    return {
        "host": block.get("host"),
        "user": block.get("user"),
        "password": block.get("password"),
        "port": int(block.get("port") or 21),
        "remote_dir": block.get("remote_dir", "/"),
        "use_tls": bool(block.get("use_tls", False)),
        "timeout": float(block.get("timeout", 60) or 60),
    }


def main() -> int:
    overrides = load_ftp_secrets()
    cfg = merge_ftp_config(overrides)
    web = get_web_dir()
    print(f"FTP: {cfg.get('user')}@{cfg.get('host')}:{cfg.get('port')}{cfg.get('remote_dir')} (tls={cfg.get('use_tls')})")
    print(f"Local target: {web}")
    print("---")

    def _p(msg: str) -> None:
        print(msg, file=sys.stderr)

    r = sync_ftp_to_web(web, config=cfg, progress=_p)
    print("---")
    print(
        f"ok={r['ok']} downloaded={len(r['downloaded'])} "
        f"skipped_same_size={r.get('skipped_same_size', 0)} "
        f"skipped_ext={r.get('skipped', 0)}"
    )
    if r["downloaded"]:
        print("\nСвежие файлы:")
        for x in r["downloaded"][:50]:
            print(f"  + {x}")
        if len(r["downloaded"]) > 50:
            print(f"  ... ещё {len(r['downloaded']) - 50}")
    if r["errors"]:
        print("\nОшибки:")
        for e in r["errors"][:20]:
            print(f"  ! {e}", file=sys.stderr)
    return 0 if r["ok"] and not r["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
