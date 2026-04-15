#!/usr/bin/env python3
"""
Проверка: после px.bar(...) / go.Bar(...) в коде дашбордов ожидается один из helpers
для подписей и uniformtext: _apply_finance_bar_label_layout или _apply_bar_uniformtext.

Запуск из корня проекта (где лежит папка dashboards/):

    python scripts/check_bar_label_helpers.py

Код возврата: 0 — замечаний нет; 1 — есть участки без helpers. Флаг --warnings-only — всегда 0 (только вывод).

Ограничения эвристики:
- Смотрит только следующие SCAN_LINES строк после вхождения (по умолчанию 160).
- Не разбирает AST: возможны ложные срабатывания (bar в строке, закомментированный код).
- Ручные исключения — в ALLOWLIST (кортежи path, line).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCAN_LINES = 160
HELPERS = (
    "_apply_finance_bar_label_layout",
    "_apply_bar_uniformtext",
)
# Если в том же фрагменте явно задан uniformtext в layout — считаем ок (редкие кастомные графики).
ALT_UNIFORMTEXT = "uniformtext"

# (относительный путь от корня проекта, номер строки) — только при необходимости после ревью.
ALLOWLIST: set[tuple[str, int]] = set()

SKIP_DIR_NAMES = {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache"}


def _project_root() -> Path:
    # scripts/check_bar_label_helpers.py -> parent.parent
    return Path(__file__).resolve().parent.parent


def _iter_py_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*.py"):
        if any(part in SKIP_DIR_NAMES for part in p.parts):
            continue
        out.append(p)
    return sorted(out)


def _line_starts_with_comment_or_string_heavy(line: str) -> bool:
    s = line.lstrip()
    if s.startswith("#"):
        return True
    return False


def _find_bar_calls(text: str) -> list[tuple[int, int, str]]:
    """
    Возвращает список (line_1based, col_0based, match_text).
    Ищем px.bar( и go.Bar(.
    """
    out: list[tuple[int, int, str]] = []
    for pat in (r"px\.bar\s*\(", r"go\.Bar\s*\("):
        for m in re.finditer(pat, text):
            pre = text[: m.start()]
            line_no = pre.count("\n") + 1
            col = m.start() - (pre.rfind("\n") + 1 if "\n" in pre else 0)
            if line_no > 0:
                line_text = text.splitlines()[line_no - 1]
                if _line_starts_with_comment_or_string_heavy(line_text):
                    continue
            out.append((line_no, col, m.group(0)))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def _chunk_after_line(lines: list[str], start_line_idx: int) -> str:
    end = min(len(lines), start_line_idx + SCAN_LINES)
    return "\n".join(lines[start_line_idx:end])


def check_file(path: Path, root: Path) -> list[tuple[int, str]]:
    rel = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return [(0, f"<не прочитан {rel}: {e}>")]
    lines = text.splitlines()
    issues: list[tuple[int, str]] = []
    seen = _find_bar_calls(text)
    for line_no, _col, mtxt in seen:
        if (rel, line_no) in ALLOWLIST:
            continue
        idx = line_no - 1
        chunk = _chunk_after_line(lines, idx)
        ok = any(h in chunk for h in HELPERS)
        if not ok and ALT_UNIFORMTEXT in chunk:
            ok = True
        if not ok:
            preview = lines[idx].strip() if 0 <= idx < len(lines) else ""
            issues.append((line_no, f"{mtxt.strip()} … {preview[:100]}"))
    return issues


def _iter_all_py(root: Path) -> list[Path]:
    """Все *.py под корнем проекта, кроме служебных каталогов."""
    out: list[Path] = []
    for p in root.rglob("*.py"):
        if any(part in SKIP_DIR_NAMES for part in p.parts):
            continue
        out.append(p)
    return sorted(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка helpers для bar-графиков Plotly.")
    parser.add_argument(
        "--warnings-only",
        action="store_true",
        help="Не падать по коду возврата (0 даже при находках); для локального просмотра.",
    )
    parser.add_argument(
        "--only-dashboards",
        action="store_true",
        help="Только папки dashboards/, pages/ и project_visualization_app.py (быстрее).",
    )
    args = parser.parse_args()

    root = _project_root()
    if args.only_dashboards:
        targets = [
            root / "dashboards",
            root / "pages",
            root / "project_visualization_app.py",
        ]
        files: list[Path] = []
        for t in targets:
            if t.is_file():
                files.append(t)
            elif t.is_dir():
                files.extend(_iter_py_files(t))
    else:
        files = _iter_all_py(root)

    all_issues: list[tuple[str, int, str]] = []
    for f in files:
        rel = f.relative_to(root).as_posix()
        res = check_file(f, root)
        for line_no, msg in res:
            if line_no == 0:
                all_issues.append((rel, 0, msg))
            else:
                all_issues.append((rel, line_no, msg))

    print(f"Корень проекта: {root}")
    print(f"Проверено файлов: {len(files)}")
    print(f"Окно поиска helpers после bar: {SCAN_LINES} строк")
    print()

    if not all_issues:
        print("OK: после всех вхождений px.bar( / go.Bar( найден helper или uniformtext в фрагменте.")
        return 0

    print("ВНИМАНИЕ: возможные пропуски helpers (проверьте вручную):\n")
    for rel, line_no, msg in all_issues:
        if line_no:
            print(f"  {rel}:{line_no}: {msg}")
        else:
            print(f"  {rel}: {msg}")

    print()
    print(
        "Если это ложное срабатывание, добавьте кортеж в ALLOWLIST в scripts/check_bar_label_helpers.py "
        "или вынесите bar в функцию с helper ближе к вызову."
    )
    return 0 if args.warnings_only else 1


if __name__ == "__main__":
    sys.exit(main())
