from __future__ import annotations

from pathlib import Path

from db_common import connect_db, ensure_output_dir, get_effective_version_id, parse_db_args, query_to_df, resolve_db_path, save_table


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/db_tessa_overdue")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        overdue = query_to_df(
            conn,
            """
            WITH src AS (
              SELECT
                COALESCE(json_extract(row_data, '$.DocID'), json_extract(row_data, '$.CardID'), '') AS doc_id,
                COALESCE(json_extract(row_data, '$.ObjectName'), json_extract(row_data, '$.ObjectProjectName'), 'unknown') AS project_name,
                COALESCE(json_extract(row_data, '$.KrState'), json_extract(row_data, '$.status'), 'unknown') AS doc_status,
                COALESCE(json_extract(row_data, '$.CreationDate'), json_extract(row_data, '$.created_at'), '') AS created_date
              FROM web_data
              WHERE version_id = ? AND file_type = 'tessa'
            )
            SELECT
              project_name AS project,
              doc_status,
              COUNT(*) AS docs_count
            FROM src
            GROUP BY project_name, doc_status
            ORDER BY docs_count DESC, project, doc_status
            LIMIT 2000
            """,
            (version_id,),
        )

    save_table(overdue, output_dir / "tessa_status_distribution.csv")


if __name__ == "__main__":
    main()
