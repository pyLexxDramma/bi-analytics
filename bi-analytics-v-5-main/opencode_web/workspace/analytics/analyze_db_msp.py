from __future__ import annotations

from pathlib import Path

from db_common import connect_db, ensure_output_dir, get_effective_version_id, parse_db_args, query_to_df, resolve_db_path, save_table


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/db_msp")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        overview = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                source_file,
                COALESCE(json_extract(row_data, '$.project name'), json_extract(row_data, '$.Проект'), 'unknown') AS project_name,
                CAST(REPLACE(COALESCE(json_extract(row_data, '$.pct complete'), json_extract(row_data, '$.Процент_завершения'), '0'), ',', '.') AS REAL) AS progress_pct,
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
              SELECT s.project_name, s.progress_pct
              FROM src s
              JOIN latest l
                ON l.project_name = s.project_name
               AND l.max_snapshot_date = s.snapshot_date
            )
            SELECT
              project_name AS project,
              COUNT(*) AS tasks_total,
              SUM(CASE WHEN progress_pct >= 100 THEN 1 ELSE 0 END) AS tasks_finished,
              SUM(CASE WHEN progress_pct < 100 THEN 1 ELSE 0 END) AS tasks_open,
              ROUND(AVG(COALESCE(progress_pct, 0)), 2) AS avg_progress_pct
            FROM filtered
            GROUP BY project_name
            ORDER BY tasks_open DESC, project
            """,
            (version_id,),
        )
        long_open = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                source_file,
                COALESCE(json_extract(row_data, '$.project name'), json_extract(row_data, '$.Проект'), 'unknown') AS project_name,
                COALESCE(json_extract(row_data, '$.task name'), json_extract(row_data, '$.Название'), json_extract(row_data, '$.Задача'), '') AS task_name,
                CAST(REPLACE(COALESCE(json_extract(row_data, '$.pct complete'), json_extract(row_data, '$.Процент_завершения'), '0'), ',', '.') AS REAL) AS progress_pct,
                CAST(REPLACE(REPLACE(COALESCE(json_extract(row_data, '$.duration'), json_extract(row_data, '$.Длительность'), '0'), ' дн', ''), ',', '.') AS REAL) AS duration_days,
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
              SELECT s.project_name, s.task_name, s.progress_pct, s.duration_days
              FROM src s
              JOIN latest l
                ON l.project_name = s.project_name
               AND l.max_snapshot_date = s.snapshot_date
            )
            SELECT project_name AS project, task_name, progress_pct, duration_days
            FROM filtered
            WHERE progress_pct < 100 AND duration_days >= 30
            ORDER BY duration_days DESC
            LIMIT 1000
            """,
            (version_id,),
        )

    save_table(overview, output_dir / "msp_overview.csv")
    save_table(long_open, output_dir / "msp_long_open_tasks.csv")


if __name__ == "__main__":
    main()
