from __future__ import annotations

from db_common import connect_db, ensure_output_dir, get_effective_version_id, parse_db_args, query_to_df, resolve_db_path, save_table


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/db_finance")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        flows = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                COALESCE(json_extract(row_data, '$.Сценарий'), json_extract(row_data, '$.scenario'), 'unknown') AS scenario_name,
                COALESCE(json_extract(row_data, '$.Проект'), json_extract(row_data, '$.project'), 'unknown') AS project_name,
                COALESCE(json_extract(row_data, '$.Период'), json_extract(row_data, '$.period'), 'unknown') AS period_name,
                CAST(REPLACE(COALESCE(json_extract(row_data, '$.Сумма'), json_extract(row_data, '$.amount'), '0'), ',', '.') AS REAL) AS amount_value
              FROM web_data
              WHERE version_id = ? AND file_type = 'reference_dannye'
            )
            SELECT
              scenario_name AS scenario,
              project_name AS project,
              period_name AS period,
              ROUND(SUM(COALESCE(amount_value, 0)), 2) AS amount_total
            FROM src
            GROUP BY scenario_name, project_name, period_name
            ORDER BY scenario_name, project_name, period_name
            LIMIT 3000
            """,
            (version_id,),
        )
        dk = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                COALESCE(json_extract(row_data, '$.Название контрагента'), json_extract(row_data, '$.Контрагент'), 'unknown') AS contractor_name,
                CAST(REPLACE(COALESCE(json_extract(row_data, '$.ОстатокНаНачало'), json_extract(row_data, '$.ОстатокНаНачалоПериода'), '0'), ',', '.') AS REAL) AS opening_balance,
                CAST(REPLACE(COALESCE(json_extract(row_data, '$.Выплачено'), json_extract(row_data, '$.ВсегоОплат'), '0'), ',', '.') AS REAL) AS paid_amount,
                CAST(REPLACE(COALESCE(json_extract(row_data, '$.ОстатокНаКонец'), json_extract(row_data, '$.ОстатокНаКонецПериода'), '0'), ',', '.') AS REAL) AS closing_balance
              FROM web_data
              WHERE version_id = ? AND file_type = 'debit_credit'
            )
            SELECT
              contractor_name AS contractor,
              ROUND(SUM(COALESCE(opening_balance, 0)), 2) AS opening_balance_total,
              ROUND(SUM(COALESCE(paid_amount, 0)), 2) AS paid_total,
              ROUND(SUM(COALESCE(closing_balance, 0)), 2) AS closing_balance_total
            FROM src
            GROUP BY contractor_name
            ORDER BY closing_balance_total DESC, contractor_name
            LIMIT 2000
            """,
            (version_id,),
        )

    save_table(flows, output_dir / "finance_dannye_summary.csv")
    save_table(dk, output_dir / "debit_credit_summary.csv")


if __name__ == "__main__":
    main()
