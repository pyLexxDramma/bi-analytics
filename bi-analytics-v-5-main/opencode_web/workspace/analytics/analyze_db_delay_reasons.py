from __future__ import annotations

from pathlib import Path

import pandas as pd

from db_common import connect_db, ensure_output_dir, get_effective_version_id, parse_db_args, query_to_df, resolve_db_path, save_table


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/db_delay_reasons")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        reasons_latest = query_to_df(
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
            filtered AS (
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
            FROM filtered
            GROUP BY project_name, reason_name
            ORDER BY reason_count DESC, project, reason
            LIMIT 2000
            """,
            (version_id,),
        )
        reasons_all_snapshots = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                source_file,
                COALESCE(json_extract(row_data, '$.project name'), json_extract(row_data, '$.Проект'), 'unknown') AS project_name,
                TRIM(COALESCE(json_extract(row_data, '$.reason of deviation'), json_extract(row_data, '$.Причины_отклонений'), json_extract(row_data, '$.Причина отклонений'), '')) AS reason_name
              FROM web_data
              WHERE version_id = ? AND file_type = 'project'
                AND source_file NOT LIKE 'sample_%'
                AND source_file NOT LIKE 'new_csv/%'
            )
            SELECT
              project_name AS project,
              reason_name AS reason,
              COUNT(*) AS reason_count
            FROM src
            WHERE reason_name <> ''
              AND LOWER(reason_name) NOT IN ('nan', 'none', 'null')
            GROUP BY project_name, reason_name
            ORDER BY reason_count DESC, project, reason
            LIMIT 4000
            """,
            (version_id,),
        )
        base_counts = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                source_file,
                COALESCE(json_extract(row_data, '$.project name'), json_extract(row_data, '$.Проект'), 'unknown') AS project_name,
                TRIM(COALESCE(json_extract(row_data, '$.reason of deviation'), json_extract(row_data, '$.Причины_отклонений'), json_extract(row_data, '$.Причина отклонений'), '')) AS reason_name,
                COALESCE(json_extract(row_data, '$.snapshot_date'), '') AS snapshot_date,
                TRIM(COALESCE(json_extract(row_data, '$.deviation'), '')) AS deviation_flag
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
              COUNT(*) AS total_rows_latest,
              SUM(CASE WHEN reason_name <> '' AND LOWER(reason_name) NOT IN ('nan', 'none', 'null') THEN 1 ELSE 0 END) AS rows_with_reason_latest,
              SUM(CASE WHEN deviation_flag IN ('1', 'true', 'True') THEN 1 ELSE 0 END) AS rows_with_deviation_flag_latest
            FROM current_rows
            """,
            (version_id,),
        )

    save_table(reasons_latest, output_dir / "delay_reasons_latest.csv")
    save_table(reasons_all_snapshots, output_dir / "delay_reasons_all_snapshots.csv")
    save_table(base_counts, output_dir / "delay_reasons_base_counts.csv")

    top_latest = (
        reasons_latest.groupby("reason", dropna=False)["reason_count"].sum().reset_index()
        if not reasons_latest.empty
        else pd.DataFrame(columns=["reason", "reason_count"])
    )
    if not top_latest.empty:
        top_latest = top_latest.sort_values("reason_count", ascending=False).head(20)
    save_table(top_latest, output_dir / "delay_reasons_top_latest.csv")


if __name__ == "__main__":
    main()
