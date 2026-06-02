"""
URL Web UI OpenCode: маршрут /{base64url(directory)}/…

См. packages/core/src/util/encode.ts (base64url без padding).
Корень «/» даёт slug «Lw» → /Lw/session и бесконечная загрузка.
"""

from __future__ import annotations

import base64
import os

DEFAULT_XCA_WORKSPACE = os.getenv("XCA_WORKSPACE_DIR", "/workspace").strip() or "/workspace"

# base64url("/") — ловушка при открытии http://host:4096/ без slug проекта
ROOT_SLASH_SLUG = "Lw"


def encode_directory_slug(directory: str) -> str:
    """Как OpenCode base64Encode: btoa + replace +/-/_, без =."""
    raw = base64.b64encode(directory.encode("utf-8")).decode("ascii")
    return raw.replace("+", "-").replace("/", "_").replace("=", "")


def decode_directory_slug(slug: str) -> str | None:
    try:
        padded = slug.replace("-", "+").replace("_", "/")
        pad = "=" * ((4 - len(padded) % 4) % 4)
        return base64.b64decode(padded + pad).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _strip_directory_slug_suffix(base: str, slug: str) -> str:
    """Remove trailing /{slug} from URL path (root or workspace)."""
    b = base.rstrip("/")
    for s in (slug, ROOT_SLASH_SLUG):
        if b.endswith(f"/{s}"):
            return b[: -len(s) - 1]
    return b


def build_xca_ui_url(base_url: str, workspace_dir: str | None = None) -> str:
    """
    Открывать проект /workspace: http://127.0.0.1:4096/L3dvcmtzcGFjZQ/
    В index.html должен быть <base href="/"> — assets с /assets/, не относительно slug.
    """
    directory = (workspace_dir or DEFAULT_XCA_WORKSPACE).strip() or DEFAULT_XCA_WORKSPACE
    slug = encode_directory_slug(directory)
    base = _strip_directory_slug_suffix((base_url or "").strip().rstrip("/"), slug)
    return f"{base.rstrip('/')}/{slug}/"

def workspace_slug(workspace_dir: str | None = None) -> str:
    directory = (workspace_dir or DEFAULT_XCA_WORKSPACE).strip() or DEFAULT_XCA_WORKSPACE
    return encode_directory_slug(directory)


def normalize_opencode_browser_url(url: str, workspace_dir: str | None = None) -> str:
    directory = (workspace_dir or DEFAULT_XCA_WORKSPACE).strip() or DEFAULT_XCA_WORKSPACE
    slug = workspace_slug(directory)
    raw = (url or "").strip()
    if not raw:
        return build_xca_ui_url("http://127.0.0.1:4096", directory)
    path_part = raw.split("?", 1)[0].split("#", 1)[0]
    if f"/{slug}/" in path_part or path_part.rstrip("/").endswith(f"/{slug}"):
        clean = raw.split("#", 1)[0]
        return clean if clean.endswith("/") else clean + "/"
    base = _strip_directory_slug_suffix(path_part.rstrip("/"), slug)
    return build_xca_ui_url(base or "http://127.0.0.1:4096", directory)


def is_opencode_web_ui_url(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u or "_opencode_ai" in u:
        return False
    return any(
        hint in u
        for hint in ("/opencode", ":4096", "opencode.ai.conall.ru", "opencode.conall.ru")
    )

