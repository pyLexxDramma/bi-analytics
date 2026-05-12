from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from db_common import connect_db, ensure_output_dir, get_effective_version_id, parse_db_args, query_to_df, resolve_db_path, save_table


def _safe_json_keys(series: pd.Series, top_n: int = 80) -> pd.DataFrame:
    keys: dict[str, int] = {}
    for raw in series.dropna().head(20000):
        try:
            payload = json.loads(str(raw))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        for key in payload.keys():
            skey = str(key)
            keys[skey] = keys.get(skey, 0) + 1
    rows = [{"key": key, "rows_with_key": cnt} for key, cnt in sorted(keys.items(), key=lambda x: (-x[1], x[0]))[:top_n]]
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_db_args(default_output="/workspace/analytics/output/db_inspect")
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(Path(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        versions = query_to_df(
            conn,
            """
            SELECT id, created_at, status, files_count, rows_count, is_active
            FROM web_versions
            ORDER BY id DESC
            LIMIT 20
            """,
        )
        files = query_to_df(
            conn,
            """
            SELECT file_type, file_name, rel_path, rows_count, loaded_at
            FROM web_files
            WHERE version_id = ?
            ORDER BY file_type, file_name
            """,
            (version_id,),
        )
        row_samples = query_to_df(
            conn,
            """
            SELECT file_type, source_file, row_data
            FROM web_data
            WHERE version_id = ?
            ORDER BY id DESC
            LIMIT 2000
            """,
            (version_id,),
        )

    save_table(versions, output_dir / "versions_top20.csv")
    save_table(files, output_dir / "active_version_files.csv")
    if not row_samples.empty:
        for file_type, chunk in row_samples.groupby("file_type", dropna=False):
            type_name = str(file_type or "unknown").replace("/", "_")
            keys_df = _safe_json_keys(chunk["row_data"])
            if not keys_df.empty:
                save_table(keys_df, output_dir / f"keys_{type_name}.csv")


if __name__ == "__main__":
    main()
