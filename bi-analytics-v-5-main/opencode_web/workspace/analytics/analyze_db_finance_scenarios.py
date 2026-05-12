from __future__ import annotations

from pathlib import Path

from db_common import connect_db, ensure_output_dir, get_effective_version_id, parse_db_args, query_to_df, resolve_db_path, save_table


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/db_finance_scenarios")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        scenarios = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                COALESCE(json_extract(row_data, '$.Сценарий'), json_extract(row_data, '$.scenario'), 'unknown') AS scenario_name,
                COALESCE(json_extract(row_data, '$.Период'), json_extract(row_data, '$.period'), 'unknown') AS period_name,
                CAST(REPLACE(COALESCE(json_extract(row_data, '$.Сумма'), json_extract(row_data, '$.amount'), '0'), ',', '.') AS REAL) AS amount_value
              FROM web_data
              WHERE version_id = ? AND file_type = 'reference_dannye'
            )
            SELECT
              scenario_name AS scenario,
              period_name AS period,
              ROUND(SUM(COALESCE(amount_value, 0)), 2) AS amount_total
            FROM src
            GROUP BY scenario_name, period_name
            ORDER BY scenario, period
            LIMIT 4000
            """,
            (version_id,),
        )

    save_table(scenarios, output_dir / "finance_scenarios.csv")


if __name__ == "__main__":
    main()
