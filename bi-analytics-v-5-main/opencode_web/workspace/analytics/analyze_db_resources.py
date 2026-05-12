from __future__ import annotations

from pathlib import Path

from db_common import connect_db, ensure_output_dir, get_effective_version_id, parse_db_args, query_to_df, resolve_db_path, save_table


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/db_resources")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        result = query_to_df(
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
            LIMIT 2000
            """,
            (version_id,),
        )

    save_table(result, output_dir / "resources_overview.csv")


if __name__ == "__main__":
    main()
