#!/usr/bin/env python3
"""Smoke-тест читаемости «График проекта»: 10 / 30 / 60 / 140 строк."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboards._renderers import (  # noqa: E402
    _GANTT_MIN_ROW_PX,
    _GANTT_MIN_TASK_FONT,
    _GANTT_MARGINS_V,
    _GANTT_VIEWPORT_MAX_HEIGHT,
    _gantt_effective_row_px,
    _gantt_max_label_lines_for_row_px,
    _gantt_resolve_y_labels,
    _gantt_wrap_task_label,
    _project_schedule_gantt_max_label_lines,
)


def _long_name(i: int) -> str:
    return (
        f"Задача {i:04d} — этап проектирования и согласования "
        f"раздела КР/J{i % 7} с длинным названием для проверки переноса"
    )


def _check_row_count(n_rows: int) -> None:
    task_font = _GANTT_MIN_TASK_FONT
    dense = n_rows > 55
    row_block_scale = 2.0
    raw = [_long_name(i) for i in range(1, n_rows + 1)]
    labels, chart_h = _gantt_resolve_y_labels(
        raw,
        n_rows=n_rows,
        task_font=task_font,
        dense=dense,
        row_block_scale=row_block_scale,
    )
    row_px = _gantt_effective_row_px(chart_h, n_rows)
    used_lines = _project_schedule_gantt_max_label_lines(labels)
    allowed_lines = _gantt_max_label_lines_for_row_px(row_px, task_font)

    assert len(labels) == n_rows, f"{n_rows}: labels count"
    assert row_px >= _GANTT_MIN_ROW_PX - 0.5, f"{n_rows}: row_px={row_px:.1f} < min {_GANTT_MIN_ROW_PX}"
    assert used_lines <= allowed_lines, (
        f"{n_rows}: used {used_lines} label lines > allowed {allowed_lines} at row_px={row_px:.1f}"
    )
    assert chart_h >= _GANTT_MARGINS_V + n_rows * _GANTT_MIN_ROW_PX, (
        f"{n_rows}: chart_h={chart_h} too small for {n_rows} rows"
    )

    # При полной высоте (без clamp) каждая строка должна вмещать минимум один ряд текста.
    lh = max(14.0, float(task_font) * 1.48)
    assert row_px >= lh * 0.95, f"{n_rows}: row too thin for font (row_px={row_px:.1f}, lh={lh:.1f})"

    scroll = chart_h > _GANTT_VIEWPORT_MAX_HEIGHT
    print(
        f"OK n={n_rows:3d}  h={chart_h:5d}px  row={row_px:5.1f}px  "
        f"lines={used_lines}/{allowed_lines}  scroll={'yes' if scroll else 'no'}"
    )


def main() -> int:
    for n in (10, 30, 60, 140):
        _check_row_count(n)

    # Однострочная метка не должна давать <br>.
    one = _gantt_wrap_task_label("Короткое имя", max_lines=1)
    assert "<br>" not in one
    print("OK wrap single-line")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
