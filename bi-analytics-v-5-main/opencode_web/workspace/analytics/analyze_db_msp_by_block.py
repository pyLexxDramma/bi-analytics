"""MSP: отставание по проектам и задачам в разрезе блока (поле block)."""
from __future__ import annotations

from pathlib import Path

from db_common import connect_db, ensure_output_dir, get_effective_version_id, parse_db_args, query_to_df, resolve_db_path, save_table


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/db_msp_by_block")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        delays_by_block = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                COALESCE(json_extract(row_data, '$.project name'), json_extract(row_data, '$.Проект'), 'unknown') AS project_name,
                COALESCE(json_extract(row_data, '$.block'), json_extract(row_data, '$.БЛОК'), json_extract(row_data, '$.Блок'), '') AS block_name,
                COALESCE(json_extract(row_data, '$.task name'), json_extract(row_data, '$.Название'), json_extract(row_data, '$.Задача'), '') AS task_name,
                CAST(REPLACE(COALESCE(json_extract(row_data, '$.deviation in days'), json_extract(row_data, '$.Отклонение_окончания'), json_extract(row_data, '$.Отклонений в днях'), '0'), ',', '.') AS REAL) AS deviation_days,
                TRIM(COALESCE(json_extract(row_data, '$.reason of deviation'), json_extract(row_data, '$.Причины_отклонений'), json_extract(row_data, '$.Причина отклонений'), '')) AS deviation_reason,
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
              SELECT s.*
              FROM src s
              JOIN latest l
                ON l.project_name = s.project_name
               AND l.max_snapshot_date = s.snapshot_date
            )
            SELECT
              project_name AS project,
              block_name AS block,
              task_name,
              deviation_days,
              deviation_reason
            FROM filtered
            WHERE deviation_days > 0
              AND TRIM(block_name) <> ''
            ORDER BY block, deviation_days DESC, project, task_name
            LIMIT 5000
            """,
            (version_id,),
        )
        project_summary = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                COALESCE(json_extract(row_data, '$.project name'), json_extract(row_data, '$.Проект'), 'unknown') AS project_name,
                COALESCE(json_extract(row_data, '$.block'), json_extract(row_data, '$.БЛОК'), '') AS block_name,
                CAST(REPLACE(COALESCE(json_extract(row_data, '$.deviation in days'), json_extract(row_data, '$.Отклонений в днях'), '0'), ',', '.') AS REAL) AS deviation_days,
                COALESCE(json_extract(row_data, '$.snapshot_date'), '') AS snapshot_date
              FROM web_data
              WHERE version_id = ? AND file_type = 'project'
                AND source_file NOT LIKE 'sample_%'
                AND source_file NOT LIKE 'new_csv/%'
            ),
            latest AS (
              SELECT project_name, MAX(snapshot_date) AS max_snapshot_date
              FROM src GROUP BY project_name
            ),
            filtered AS (
              SELECT s.project_name, s.block_name, s.deviation_days
              FROM src s
              JOIN latest l ON l.project_name = s.project_name AND l.max_snapshot_date = s.snapshot_date
            )
            SELECT
              project_name AS project,
              block_name AS block,
              COUNT(*) AS delayed_tasks,
              ROUND(MAX(deviation_days), 1) AS max_deviation_days,
              ROUND(AVG(deviation_days), 1) AS avg_deviation_days
            FROM filtered
            WHERE deviation_days > 0 AND TRIM(block_name) <> ''
            GROUP BY project_name, block_name
            ORDER BY delayed_tasks DESC, max_deviation_days DESC
            """,
            (version_id,),
        )

    save_table(delays_by_block, output_dir / "msp_delays_by_block.csv")
    save_table(project_summary, output_dir / "msp_delayed_projects_by_block.csv")


if __name__ == "__main__":
    main()
