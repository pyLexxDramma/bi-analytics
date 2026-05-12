from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from db_common import (
    connect_db,
    ensure_output_dir,
    get_effective_version_id,
    parse_db_args,
    query_to_df,
    resolve_db_path,
    save_table,
)


def _build_pie_chart(df: pd.DataFrame, target_png: Path) -> None:
    target_png.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.text(0.5, 0.5, "Нет данных по причинам отклонений", ha="center", va="center")
        ax.axis("off")
        plt.tight_layout()
        plt.savefig(target_png, dpi=140)
        plt.close(fig)
        return

    chart_df = df.copy()
    chart_df = chart_df.sort_values("reason_count", ascending=False)
    if len(chart_df) > 12:
        top = chart_df.head(11).copy()
        other_count = int(chart_df.iloc[11:]["reason_count"].sum())
        chart_df = pd.concat(
            [
                top,
                pd.DataFrame([{"reason": "Прочие", "reason_count": other_count}]),
            ],
            ignore_index=True,
        )

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.pie(
        chart_df["reason_count"],
        labels=chart_df["reason"],
        autopct="%1.1f%%",
        startangle=90,
        textprops={"fontsize": 9},
    )
    ax.set_title("Причины отклонений (актуальные срезы по проектам)")
    ax.axis("equal")
    plt.tight_layout()
    plt.savefig(target_png, dpi=140)
    plt.close(fig)


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/db_deviations_chat")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)

        # Логика максимально близка к сайту:
        # 1) исключаем demo-источники;
        # 2) берем последний snapshot_date по каждому проекту;
        # 3) "отклонения" = deviation=true/1 ИЛИ заполненная причина;
        # 4) причины считаем только по непустой reason.
        base_df = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                source_file,
                COALESCE(json_extract(row_data, '$.project name'), json_extract(row_data, '$.Проект'), 'unknown') AS project_name,
                TRIM(COALESCE(json_extract(row_data, '$.reason of deviation'), json_extract(row_data, '$.Причины_отклонений'), json_extract(row_data, '$.Причина отклонений'), '')) AS reason_name,
                TRIM(COALESCE(json_extract(row_data, '$.deviation'), '')) AS deviation_flag,
                COALESCE(json_extract(row_data, '$.snapshot_date'), '') AS snapshot_date
              FROM web_data
              WHERE version_id = ? AND file_type = 'project'
                AND source_file NOT LIKE 'sample_%'
                AND source_file NOT LIKE 'new_csv/%'
            ),
            latest AS (
              SELECT project_name, MAX(snapshot_date) AS max_snapshot_date
              FROM src
              GROUP BY project_name
            ),
            current_rows AS (
              SELECT s.*
              FROM src s
              JOIN latest l
                ON l.project_name = s.project_name
               AND l.max_snapshot_date = s.snapshot_date
            )
            SELECT
              project_name AS project,
              reason_name AS reason,
              deviation_flag,
              CASE
                WHEN deviation_flag IN ('1', 'true', 'True') THEN 1
                WHEN reason_name <> '' AND LOWER(reason_name) NOT IN ('nan', 'none', 'null') THEN 1
                ELSE 0
              END AS is_deviation
            FROM current_rows
            """,
            (version_id,),
        )

    deviations_df = base_df[base_df["is_deviation"] == 1].copy() if not base_df.empty else pd.DataFrame()
    reasons_df = (
        deviations_df[
            deviations_df["reason"].astype(str).str.strip().ne("")
            & ~deviations_df["reason"].astype(str).str.lower().isin(["nan", "none", "null"])
        ]
        .groupby("reason", dropna=False)
        .size()
        .reset_index(name="reason_count")
        .sort_values("reason_count", ascending=False)
        if not deviations_df.empty
        else pd.DataFrame(columns=["reason", "reason_count"])
    )

    summary_df = pd.DataFrame(
        [
            {
                "version_id": int(version_id),
                "rows_total_latest": int(len(base_df)),
                "rows_deviation_logic": int(len(deviations_df)),
                "rows_with_non_empty_reason": int(reasons_df["reason_count"].sum()) if not reasons_df.empty else 0,
                "top_reason": str(reasons_df.iloc[0]["reason"]) if not reasons_df.empty else "",
                "top_reason_count": int(reasons_df.iloc[0]["reason_count"]) if not reasons_df.empty else 0,
            }
        ]
    )

    save_table(summary_df, output_dir / "deviations_summary_for_chat.csv")
    save_table(reasons_df, output_dir / "deviations_reasons_for_chat.csv")

    pie_path = output_dir / "deviations_reasons_for_chat_pie.png"
    _build_pie_chart(reasons_df, pie_path)


if __name__ == "__main__":
    main()
