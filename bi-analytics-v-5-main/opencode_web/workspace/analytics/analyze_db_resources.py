from __future__ import annotations

from pathlib import Path

from db_common import connect_db, ensure_output_dir, get_effective_version_id, parse_db_args, query_to_df, resolve_db_path, save_table
from gdrs_kontr_common import contractor_in_kontr, load_kontr_index_from_db


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
                COALESCE(json_extract(row_data, '$.project_name'), json_extract(row_data, '$.Проект'), 'unknown') AS project_name,
                COALESCE(json_extract(row_data, '$.contractor_name'), json_extract(row_data, '$.Подрядчик'), json_extract(row_data, '$.Контрагент'), 'unknown') AS contractor_name,
                COALESCE(json_extract(row_data, '$.contractor_id'), json_extract(row_data, '$.ID_Подрядчика'), '') AS contractor_id,
                COALESCE(json_extract(row_data, '$.vid_resursa'), json_extract(row_data, '$.тип ресурсов'), 'unknown') AS resource_type,
                CAST(REPLACE(COALESCE(json_extract(row_data, '$.fact'), '0'), ',', '.') AS REAL) AS fact_val
              FROM web_data
              WHERE version_id = ? AND file_type = 'gdrs_fact'
            )
            SELECT
              project_name AS project,
              contractor_name AS contractor,
              contractor_id,
              resource_type,
              ROUND(AVG(COALESCE(fact_val, 0)), 2) AS avg_resources_per_day
            FROM src
            GROUP BY project_name, contractor_name, contractor_id, resource_type
            ORDER BY project, contractor, resource_type
            LIMIT 2000
            """,
            (version_id,),
        )
        _kontr = load_kontr_index_from_db(conn, version_id)
    if _kontr is not None and not result.empty and "contractor" in result.columns:
        mask = result.apply(
            lambda r: contractor_in_kontr(
                str(r.get("contractor_id", "")),
                str(r.get("contractor", r.get("contractor_name", ""))),
                _kontr,
            ),
            axis=1,
        )
        result = result.loc[mask].copy()

    save_table(result, output_dir / "resources_overview.csv")


if __name__ == "__main__":
    main()
