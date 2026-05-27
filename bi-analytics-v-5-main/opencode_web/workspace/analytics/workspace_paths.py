"""Сопоставление путей /workspace/... с реальной ФС (Docker и локальный клон)."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# Частые ошибки ИИ в имени файла → каноническое имя в output скрипта
CHART_BASENAME_ALIASES: dict[str, str] = {
    "budget_plan_fact_by_project.png": "plan_fact_by_project.png",
    "budget_plan_fact.png": "plan_fact_by_project.png",
}


@lru_cache(maxsize=1)
def workspace_root() -> Path:
    env = os.getenv("WORKSPACE_ROOT", "").strip()
    if env:
        path = Path(env)
        if path.is_dir():
            return path.resolve()

    repo_workspace = (Path(__file__).resolve().parent.parent).resolve()
    if (repo_workspace / "AI_DATA_RULES.md").is_file() or (repo_workspace / "analytics").is_dir():
        return repo_workspace

    docker = Path("/workspace")
    if docker.is_dir() and (docker / "analytics").is_dir():
        return docker.resolve()
    return repo_workspace


def analytics_output_dir() -> Path:
    return workspace_root() / "analytics" / "output"


def resolve_output_dir(cli_path: str) -> Path:
    """
    Путь output из CLI: /workspace/analytics/output/... → каталог в текущем workspace_root,
    а не C:\\workspace на Windows.
    """
    raw = str(cli_path or "").strip()
    if not raw:
        return analytics_output_dir()
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/workspace/"):
        rel = normalized[len("/workspace/") :]
        return workspace_root() / rel
    if normalized == "/workspace":
        return workspace_root()
    return Path(raw)


def to_workspace_display_path(path: Path) -> str:
    """Путь для строки в ответе ИИ (всегда Unix-стиль под /workspace)."""
    root = workspace_root()
    try:
        rel = path.resolve().relative_to(root.resolve())
        return f"/workspace/{rel.as_posix()}"
    except ValueError:
        return path.as_posix()


def normalize_path_token(raw: str) -> str:
    token = str(raw or "").strip().strip(".,;:!?)(").strip('"').strip("'").strip("`")
    token = token.replace("\\\\", "\\")
    if token.startswith("\\workspace"):
        token = "/workspace" + token[len("\\workspace") :].replace("\\", "/")
    return token


def resolve_workspace_media_path(raw: str) -> Path | None:
    """
    Преобразует строку из ответа ИИ в существующий файл.
    Поддерживает /workspace/..., \\workspace\\..., относительные analytics/output/...
    """
    token = normalize_path_token(raw)
    if not token:
        return None
    suffix = Path(token).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        return None

    candidates: list[Path] = []
    path_obj = Path(token)
    if path_obj.is_absolute():
        candidates.append(path_obj)
    root = workspace_root()
    if token.startswith("/workspace/"):
        candidates.append(root / token[len("/workspace/") :])
    elif token.lower().startswith("workspace/"):
        candidates.append(root / token.split(":", 1)[-1].lstrip("/"))
    else:
        candidates.append(root / token.lstrip("/"))

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved

    # Поиск по имени файла в output (ИИ часто путает каталог или имя)
    basename = Path(token).name
    search_names = [basename] if basename else []
    if basename and basename in CHART_BASENAME_ALIASES:
        search_names.append(CHART_BASENAME_ALIASES[basename])
    output_root = analytics_output_dir()
    if output_root.is_dir():
        for name in search_names:
            if not name:
                continue
            for hit in output_root.rglob(name):
                if hit.is_file():
                    return hit.resolve()

    # Legacy: старые прогоны на Windows писали в C:\workspace
    if token.startswith("/workspace/"):
        legacy = Path("C:" + token.replace("/", "\\"))
        if legacy.is_file():
            return legacy.resolve()
    return None


_IMAGE_PATH_LINE_RE = re.compile(
    r"^\s*("
    r"/workspace/[^\s\]\)\"']+\.(?:png|jpg|jpeg|webp|gif)"
    r"|\\+workspace\\+[^\s\]\)\"']+\.(?:png|jpg|jpeg|webp|gif)"
    r"|[A-Za-z]:\\[^\s\]\)\"']+\.(?:png|jpg|jpeg|webp|gif)"
    r")\s*$",
    re.IGNORECASE,
)


def extract_image_path_tokens(text: str) -> list[str]:
    patterns = (
        r"(/workspace/[^\s\]\)\"']+\.(?:png|jpg|jpeg|webp|gif))",
        r"(\\+workspace\\+[^\s\]\)\"']+\.(?:png|jpg|jpeg|webp|gif))",
        r"([A-Za-z]:\\[^\s\]\)\"']+\.(?:png|jpg|jpeg|webp|gif))",
    )
    found: list[str] = []
    for pattern in patterns:
        found.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    return found


def resolve_images_in_text(text: str) -> list[Path]:
    seen: set[str] = set()
    resolved: list[Path] = []
    for token in extract_image_path_tokens(text):
        key = normalize_path_token(token)
        if key in seen:
            continue
        seen.add(key)
        path = resolve_workspace_media_path(token)
        if path is not None:
            resolved.append(path)
    return resolved


def strip_image_path_lines(text: str) -> str:
    """Убирает пути к PNG из текста — картинка показывается через st.image."""
    raw = str(text or "")
    tokens = extract_image_path_tokens(raw)
    lines_out: list[str] = []
    for line in raw.splitlines():
        if _IMAGE_PATH_LINE_RE.match(line):
            continue
        cleaned_line = line
        for token in tokens:
            cleaned_line = cleaned_line.replace(token, "")
        cleaned_line = re.sub(r"\s*\(изображения нет\)\s*", "", cleaned_line, flags=re.I)
        cleaned_line = re.sub(r"\s{2,}", " ", cleaned_line).strip()
        if cleaned_line:
            lines_out.append(cleaned_line)
    return "\n".join(lines_out).strip()
