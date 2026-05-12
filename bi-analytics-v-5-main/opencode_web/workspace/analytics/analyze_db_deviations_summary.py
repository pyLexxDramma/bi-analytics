from __future__ import annotations

from pathlib import Path

import pandas as pd

from db_common import connect_db, ensure_output_dir, get_effective_version_id, parse_db_args, query_to_df, resolve_db_path, save_table


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/db_deviations")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        base = query_to_df(
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
              COUNT(*) AS total_rows,
              SUM(CASE WHEN reason_name <> '' AND LOWER(reason_name) NOT IN ('nan', 'none', 'null') THEN 1 ELSE 0 END) AS rows_with_reason,
              SUM(CASE WHEN deviation_flag IN ('1', 'true', 'True') THEN 1 ELSE 0 END) AS rows_with_deviation_flag
            FROM current_rows
            GROUP BY project_name
            ORDER BY total_rows DESC
            """,
            (version_id,),
        )
        reasons = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                source_file,
                COALESCE(json_extract(row_data, '$.project name'), json_extract(row_data, '$.Проект'), 'unknown') AS project_name,
                TRIM(COALESCE(json_extract(row_data, '$.reason of deviation'), json_extract(row_data, '$.Причины_отклонений'), json_extract(row_data, '$.Причина отклонений'), '')) AS reason_name,
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
              SELECT s.project_name, s.reason_name
              FROM src s
              JOIN latest l
                ON l.project_name = s.project_name
               AND l.max_snapshot_date = s.snapshot_date
              WHERE s.reason_name <> ''
                AND LOWER(s.reason_name) NOT IN ('nan', 'none', 'null')
            )
            SELECT
              project_name AS project,
              reason_name AS reason,
              COUNT(*) AS reason_count
            FROM current_rows
            GROUP BY project_name, reason_name
            ORDER BY reason_count DESC, project, reason
            LIMIT 3000
            """,
            (version_id,),
        )

    save_table(base, output_dir / "deviations_base_by_project.csv")
    save_table(reasons, output_dir / "deviations_reasons_by_project.csv")

    totals = pd.DataFrame(
        [
            {
                "projects_count": int(base["project"].nunique()) if not base.empty else 0,
                "rows_total_latest": int(base["total_rows"].sum()) if not base.empty else 0,
                "rows_with_reason_latest": int(base["rows_with_reason"].sum()) if not base.empty else 0,
                "rows_with_deviation_flag_latest": int(base["rows_with_deviation_flag"].sum()) if not base.empty else 0,
            }
        ]
    )
    save_table(totals, output_dir / "deviations_totals.csv")

    top_reasons = (
        reasons.groupby("reason", dropna=False)["reason_count"].sum().reset_index()
        if not reasons.empty
        else pd.DataFrame(columns=["reason", "reason_count"])
    )
    if not top_reasons.empty:
        top_reasons = top_reasons.sort_values("reason_count", ascending=False)
    save_table(top_reasons, output_dir / "deviations_reasons_top.csv")


if __name__ == "__main__":
    main()
