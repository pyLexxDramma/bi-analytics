"""
etl/ — модуль ETL для BI Analytics.

Точки входа:
    from etl.loader import load_from_web_dir, get_etl_versions, set_active_version
    from etl.loader import get_current_version_id, query_msp, query_budget, ...
    from etl.schema import init_etl_schema, ETL_DB_PATH
"""
from etl.schema import init_etl_schema, ETL_DB_PATH
from etl.loader import (
    load_from_web_dir,
    get_etl_versions,
    set_active_version,
    get_current_version_id,
    get_current_version_info,
    query_msp,
    query_budget,
    query_debit_credit,
    query_tessa_rd,
    query_tessa_id,
    query_resources,
)

__all__ = [
    "init_etl_schema",
    "ETL_DB_PATH",
    "load_from_web_dir",
    "get_etl_versions",
    "set_active_version",
    "get_current_version_id",
    "get_current_version_info",
    "query_msp",
    "query_budget",
    "query_debit_credit",
    "query_tessa_rd",
    "query_tessa_id",
    "query_resources",
]
