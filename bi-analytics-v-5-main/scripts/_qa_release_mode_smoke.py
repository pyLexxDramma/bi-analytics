"""Smoke-тест: поведение ignore_demo_data_files() / is_release_client_mode() при разных env."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_repo))


def _reload_config_and_run():
    """Перезагружает config (lru_cache, env-чтения) и возвращает (is_release, ignore_demo, demos_in_scan)."""
    import importlib
    import config
    importlib.reload(config)
    is_rel = config.is_release_client_mode()
    ign = config.ignore_demo_data_files()
    import web_loader
    importlib.reload(web_loader)
    files = web_loader.scan_web_files((".csv", ".json"))
    demo_in_scan = [
        f for f in files
        if f["name"].lower().startswith("sample_")
        or "/new_csv/" in str(f["rel_path"]).replace("\\", "/").lower()
    ]
    return is_rel, ign, len(files), demo_in_scan


def case(name: str, env: dict[str, str | None]) -> None:
    print(f"\n=== {name} ===")
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

    is_rel, ign, total, demos = _reload_config_and_run()
    print(f"  env applied: {env}")
    print(f"  is_release_client_mode = {is_rel}")
    print(f"  ignore_demo_data_files = {ign}")
    print(f"  scan_web_files: total={total}, demo_files_present={len(demos)}")
    for d in demos:
        print(f"    DEMO -> {d['rel_path']}")

    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def case_with_session_flag(name: str, env: dict[str, str | None], pref: str) -> None:
    """Эмуляция admin-тумблера: ставит st.session_state['_admin_demo_pref']."""
    print(f"\n=== {name} ===")
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

    import importlib
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
    is_rel = config.is_release_client_mode()
    ign = config.ignore_demo_data_files()
    print(f"  env applied: {env}")
    print(f"  session['_admin_demo_pref'] = {pref!r}")
    print(f"  is_release_client_mode = {is_rel}")
    print(f"  ignore_demo_data_files = {ign}")

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
    case("baseline (no env)", {})
    case("release (HIDE_DEV_DIAGNOSTICS=1)", {"BI_ANALYTICS_HIDE_DEV_DIAGNOSTICS": "1"})
    case("release (RELEASE_MODE=1)", {"BI_ANALYTICS_RELEASE_MODE": "1"})
    case("release + INCLUDE_DEMO=1 (override)",
         {"BI_ANALYTICS_HIDE_DEV_DIAGNOSTICS": "1", "BI_ANALYTICS_INCLUDE_DEMO": "1"})
    case("dev with explicit IGNORE_DEMO=1", {"BI_ANALYTICS_IGNORE_DEMO": "1"})

    print("\n--- ADMIN session-flag tests ---")
    case_with_session_flag("dev + admin pref='include' (force demo ON)", {}, "include")
    case_with_session_flag("dev + admin pref='ignore' (force demo OFF)", {}, "ignore")
    case_with_session_flag("dev + admin pref unset (default)", {}, "")
    case_with_session_flag("release + admin pref='include' (must STILL be ignored)",
                           {"BI_ANALYTICS_HIDE_DEV_DIAGNOSTICS": "1"}, "include")
    case_with_session_flag("dev + ENV IGNORE_DEMO=1, admin pref='include' (override ENV)",
                           {"BI_ANALYTICS_IGNORE_DEMO": "1"}, "include")
