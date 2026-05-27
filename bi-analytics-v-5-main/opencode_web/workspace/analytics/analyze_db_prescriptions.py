"""Предписания TESSA: просрочки, статусы, контролёры (tessa_tasks)."""
from __future__ import annotations

from pathlib import Path

from db_common import connect_db, ensure_output_dir, get_effective_version_id, parse_db_args, query_to_df, resolve_db_path, save_table


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/db_prescriptions")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        by_status = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                COALESCE(json_extract(row_data, '$.TypeCaption'), json_extract(row_data, '$.type'), 'unknown') AS task_type,
                COALESCE(json_extract(row_data, '$.OptionCaption'), json_extract(row_data, '$.Result'), 'unknown') AS task_status,
                COALESCE(json_extract(row_data, '$.RoleName'), '') AS controller_name,
                COALESCE(json_extract(row_data, '$.Completed'), '') AS completed_flag
              FROM web_data
              WHERE version_id = ? AND file_type = 'tessa_tasks'
            )
            SELECT
              task_type,
              task_status,
              controller_name,
              COUNT(*) AS tasks_count
            FROM src
            GROUP BY task_type, task_status, controller_name
            ORDER BY tasks_count DESC
            LIMIT 3000
            """,
            (version_id,),
        )
        overdue_hint = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                COALESCE(json_extract(row_data, '$.TypeCaption'), 'unknown') AS task_type,
                COALESCE(json_extract(row_data, '$.OptionCaption'), json_extract(row_data, '$.Result'), 'unknown') AS task_status,
                COALESCE(json_extract(row_data, '$.RoleName'), '') AS controller_name
              FROM web_data
              WHERE version_id = ? AND file_type = 'tessa_tasks'
            )
            SELECT task_type, task_status, controller_name, COUNT(*) AS tasks_count
            FROM src
            WHERE LOWER(task_status) LIKE '%просроч%'
               OR LOWER(task_status) LIKE '%overdue%'
               OR LOWER(task_status) LIKE '%критич%'
            GROUP BY task_type, task_status, controller_name
            ORDER BY tasks_count DESC
            """,
            (version_id,),
        )

    save_table(by_status, output_dir / "prescriptions_by_status.csv")
    save_table(overdue_hint, output_dir / "prescriptions_overdue_or_critical.csv")


if __name__ == "__main__":
    main()
