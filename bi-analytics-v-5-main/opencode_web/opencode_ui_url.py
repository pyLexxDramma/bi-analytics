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


def build_xca_ui_url(base_url: str, workspace_dir: str | None = None) -> str:
    """
    Открывать проект /workspace: http://127.0.0.1:4096/L3dvcmtzcGFjZQ/
    В index.html должен быть <base href="/"> — assets с /assets/, не относительно slug.
    """
    directory = (workspace_dir or DEFAULT_XCA_WORKSPACE).strip() or DEFAULT_XCA_WORKSPACE
    slug = encode_directory_slug(directory)
    return f"{base_url.rstrip('/')}/{slug}/"
