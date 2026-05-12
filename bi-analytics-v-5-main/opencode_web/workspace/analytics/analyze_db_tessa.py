from __future__ import annotations

from db_common import connect_db, ensure_output_dir, get_effective_version_id, parse_db_args, query_to_df, resolve_db_path, save_table


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/db_tessa")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        tasks = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                COALESCE(json_extract(row_data, '$.TypeCaption'), json_extract(row_data, '$.type'), 'unknown') AS task_type,
                COALESCE(json_extract(row_data, '$.OptionCaption'), json_extract(row_data, '$.Result'), json_extract(row_data, '$.status'), 'unknown') AS task_status
              FROM web_data
              WHERE version_id = ? AND file_type = 'tessa_tasks'
            )
            SELECT task_type, task_status, COUNT(*) AS tasks_count
            FROM src
            GROUP BY task_type, task_status
            ORDER BY tasks_count DESC, task_type, task_status
            LIMIT 1500
            """,
            (version_id,),
        )
        rd = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                COALESCE(json_extract(row_data, '$.ObjectName'), json_extract(row_data, '$.ObjectProjectName'), json_extract(row_data, '$.Проект'), 'unknown') AS project_name,
                COALESCE(json_extract(row_data, '$.KrState'), json_extract(row_data, '$.status'), 'unknown') AS rd_status
              FROM web_data
              WHERE version_id = ? AND file_type = 'tessa'
            )
            SELECT project_name AS project, rd_status, COUNT(*) AS rows_count
            FROM src
            GROUP BY project_name, rd_status
            ORDER BY project, rows_count DESC
            LIMIT 2000
            """,
            (version_id,),
        )
        id_docs = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                COALESCE(json_extract(row_data, '$.KindName'), json_extract(row_data, '$.doc_type'), 'unknown') AS doc_type,
                COALESCE(json_extract(row_data, '$.KrState'), json_extract(row_data, '$.status'), 'unknown') AS doc_status
              FROM web_data
              WHERE version_id = ? AND file_type = 'tessa'
            )
            SELECT doc_type, doc_status, COUNT(*) AS docs_count
            FROM src
            GROUP BY doc_type, doc_status
            ORDER BY docs_count DESC, doc_type, doc_status
            LIMIT 2000
            """,
            (version_id,),
        )

    save_table(tasks, output_dir / "tessa_tasks_summary.csv")
    save_table(rd, output_dir / "tessa_rd_summary.csv")
    save_table(id_docs, output_dir / "tessa_id_summary.csv")


if __name__ == "__main__":
    main()
