"""Smoke-тест работы admin-тумблера: при ON в матрице должны появляться Завод/Дмитровский,
при OFF — отсекаться. Прогон сразу читает активную версию БД и моделирует фильтр из _renderers."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pandas as pd

_repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_repo))


def _load_active_msp() -> pd.DataFrame:
    """Эмулирует выборку MSP-строк активной версии (без Streamlit-runtime)."""
    import json
    import sqlite3

    db = _repo / "data" / "web_data.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    vid = cur.execute("SELECT id FROM web_versions WHERE is_active=1").fetchone()
    if not vid:
        raise SystemExit("No active version in DB")
    vid = int(vid["id"])
    rows = []
    for r in cur.execute(
        "SELECT row_data, source_file FROM web_data WHERE version_id=? AND file_type='project'",
        (vid,),
    ).fetchall():
        try:
            obj = json.loads(r["row_data"]) if r["row_data"] else {}
        except Exception:
            obj = {}
        obj["__source_file"] = str(r["source_file"])
        rows.append(obj)
    return pd.DataFrame(rows)


def _project_labels_after_renderer_filter(df: pd.DataFrame, ignore_demo: bool) -> set[str]:
    """Повторяет логику dashboard_developer_projects: при ignore_demo=True отсекает sample_*."""
    work = df.copy()
    if ignore_demo:
        src_col = next((c for c in ("__source_file", "source_file", "_source_file") if c in work.columns), None)
        if src_col is not None:
            _src_l = work[src_col].fillna("").astype(str).str.strip().str.lower()
            _is_demo = _src_l.str.startswith("sample_") | _src_l.str.startswith("new_csv/sample_")
            if _is_demo.any():
                work = work[~_is_demo]
    pcol = next((c for c in work.columns if str(c).strip().lower() in ("project name", "проект", "project")), None)
    if pcol is None:
        return set()
    vals = work[pcol].fillna("").astype(str).str.strip()
    return set(v for v in vals if v and v.lower() not in ("nan", "none", "nat"))


def case(name: str, env: dict[str, str | None], pref: str) -> None:
    saved = {}
    for k in ("BI_ANALYTICS_HIDE_DEV_DIAGNOSTICS", "BI_ANALYTICS_RELEASE_MODE",
              "BI_ANALYTICS_IGNORE_DEMO", "BI_ANALYTICS_INCLUDE_DEMO"):
        saved[k] = os.environ.get(k)
        os.environ.pop(k, None)
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    import config
    importlib.reload(config)
    try:
        import streamlit as st
        if pref:
            st.session_state["_admin_demo_pref"] = pref
        else:
            st.session_state.pop("_admin_demo_pref", None)
    except Exception:
        pass

    ign = config.ignore_demo_data_files()
    rel = config.is_release_client_mode()
    df = _load_active_msp()
    labels = _project_labels_after_renderer_filter(df, ign)
    has_demo = bool({"Завод", "Дмитровский"} & labels)

    print(f"\n=== {name} ===")
    print(f"  env={env}  pref={pref!r}")
    print(f"  is_release={rel}  ignore_demo={ign}")
    print(f"  labels seen: {sorted(labels)}")
    print(f"  demo (Завод/Дмитровский) present in matrix: {has_demo}")

    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        import streamlit as st
        st.session_state.pop("_admin_demo_pref", None)
    except Exception:
        pass


if __name__ == "__main__":
    case("dev + tumbler OFF (admin pref='ignore')", {}, "ignore")
    case("dev + tumbler ON (admin pref='include')", {}, "include")
    case("dev + tumbler unset (default)", {}, "")
    case("release (HIDE_DEV_DIAGNOSTICS=1) — demo всегда скрыты", {"BI_ANALYTICS_HIDE_DEV_DIAGNOSTICS": "1"}, "")
    case("release + admin pref='include' (попытка обойти)", {"BI_ANALYTICS_HIDE_DEV_DIAGNOSTICS": "1"}, "include")
