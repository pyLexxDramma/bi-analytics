from __future__ import annotations

from pathlib import Path

from db_common import connect_db, ensure_output_dir, get_effective_version_id, parse_db_args, query_to_df, resolve_db_path, save_table


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/db_rd")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        result = query_to_df(
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
            LIMIT 2000
            """,
            (version_id,),
        )

    save_table(result, output_dir / "rd_registry_overview.csv")


if __name__ == "__main__":
    main()
