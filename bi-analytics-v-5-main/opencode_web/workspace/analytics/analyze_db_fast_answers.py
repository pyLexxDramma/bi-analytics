from __future__ import annotations

from pathlib import Path

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


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/ai_fast_db")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        inventory = query_to_df(
            conn,
            """
            SELECT file_type, COUNT(*) AS files_count, SUM(rows_count) AS rows_count
            FROM web_files
            WHERE version_id = ?
            GROUP BY file_type
            ORDER BY rows_count DESC
            """,
            (version_id,),
        )
        msp_overview = query_to_df(
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
        msp_long = query_to_df(
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
            LIMIT 300
            """,
            (version_id,),
        )
        resources = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                COALESCE(json_extract(row_data, '$.Проект'), json_extract(row_data, '$.project'), 'unknown') AS project_name,
                COALESCE(json_extract(row_data, '$.Подрядчик'), json_extract(row_data, '$.Контрагент'), 'unknown') AS contractor_name,
                COALESCE(json_extract(row_data, '$.тип ресурсов'), json_extract(row_data, '$.тип ресурсов '), json_extract(row_data, '$.resource_kind'), 'unknown') AS resource_type,
                CAST(REPLACE(COALESCE(json_extract(row_data, '$.avg_resources_per_day'), json_extract(row_data, '$.среднее значение количество ресурсов в день за месяц'), '0'), ',', '.') AS REAL) AS avg_resources
              FROM web_data
              WHERE version_id = ? AND file_type IN ('resources', 'technique')
            )
            SELECT
              project_name AS project,
              contractor_name AS contractor,
              resource_type,
              ROUND(AVG(COALESCE(avg_resources, 0)), 2) AS avg_resources_per_day
            FROM src
            GROUP BY project_name, contractor_name, resource_type
            ORDER BY project, contractor, resource_type
            LIMIT 1000
            """,
            (version_id,),
        )
        rd_registry = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                COALESCE(json_extract(row_data, '$.project'), json_extract(row_data, '$.Проект'), 'unknown') AS project_name,
                COALESCE(json_extract(row_data, '$.Шифр'), json_extract(row_data, '$.DivisionCipher'), '') AS division_cipher,
                COALESCE(json_extract(row_data, '$.Наименование раздела'), json_extract(row_data, '$.SubDivisionVersionName'), '') AS division_name,
                CAST(REPLACE(COALESCE(json_extract(row_data, '$.Количество разделов по Договору'), '0'), ',', '.') AS REAL) AS sections_total
              FROM web_data
              WHERE version_id = ? AND file_type IN ('rd_plan', 'tessa')
            )
            SELECT
              project_name AS project,
              division_cipher,
              division_name,
              MAX(COALESCE(sections_total, 0)) AS sections_total
            FROM src
            WHERE division_cipher <> '' OR division_name <> ''
            GROUP BY project_name, division_cipher, division_name
            ORDER BY project, division_cipher, division_name
            LIMIT 1500
            """,
            (version_id,),
        )

    save_table(inventory, output_dir / "data_inventory.csv")
    save_table(msp_overview, output_dir / "msp_overview.csv")
    save_table(msp_long, output_dir / "msp_long_open_tasks.csv")
    save_table(resources, output_dir / "resources_overview.csv")
    save_table(rd_registry, output_dir / "rd_registry_overview.csv")

    diagnostics = pd.DataFrame(
        [
            {
                "db_path": str(db_path),
                "version_id": int(version_id),
                "inventory_rows": len(inventory),
                "msp_overview_rows": len(msp_overview),
                "msp_long_open_rows": len(msp_long),
                "resources_overview_rows": len(resources),
                "rd_registry_rows": len(rd_registry),
            }
        ]
    )
    save_table(diagnostics, output_dir / "diagnostics.csv")


if __name__ == "__main__":
    main()
