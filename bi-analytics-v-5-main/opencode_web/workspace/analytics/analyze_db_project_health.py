from __future__ import annotations

from pathlib import Path

from db_common import connect_db, ensure_output_dir, get_effective_version_id, parse_db_args, query_to_df, resolve_db_path, save_table


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/db_project_health")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        health = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                COALESCE(json_extract(row_data, '$.project name'), json_extract(row_data, '$.Проект'), 'unknown') AS project_name,
                CAST(REPLACE(COALESCE(json_extract(row_data, '$.pct complete'), json_extract(row_data, '$.Процент_завершения'), '0'), ',', '.') AS REAL) AS progress_pct,
                CAST(REPLACE(REPLACE(COALESCE(json_extract(row_data, '$.duration'), json_extract(row_data, '$.Длительность'), '0'), ' дн', ''), ',', '.') AS REAL) AS duration_days
              FROM web_data
              WHERE version_id = ? AND file_type = 'project'
            )
            SELECT
              project_name AS project,
              COUNT(*) AS tasks_total,
              ROUND(AVG(COALESCE(progress_pct, 0)), 2) AS avg_progress_pct,
              SUM(CASE WHEN progress_pct < 100 THEN 1 ELSE 0 END) AS tasks_open,
              SUM(CASE WHEN progress_pct < 100 AND duration_days >= 30 THEN 1 ELSE 0 END) AS long_open_tasks,
              ROUND(
                CASE WHEN COUNT(*) = 0 THEN 0
                     ELSE 100.0 * SUM(CASE WHEN progress_pct < 100 THEN 1 ELSE 0 END) / COUNT(*)
                END,
                2
              ) AS open_share_pct
            FROM src
            GROUP BY project_name
            ORDER BY long_open_tasks DESC, tasks_open DESC, project
            """,
            (version_id,),
        )

    save_table(health, output_dir / "project_health.csv")


if __name__ == "__main__":
    main()
