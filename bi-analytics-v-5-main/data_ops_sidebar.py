# -*- coding: utf-8 -*-
"""Компактная панель «Источник данных» в сайдбаре (только admin/superadmin)."""

from __future__ import annotations

from typing import Any, Callable, Optional


def _safe_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def render_admin_data_ops_sidebar(st: Any) -> None:
    """
    Маленькая панель в сайдбаре: источник данных, загрузка web/, версия, FTP.
    Вызывать из ``auth.render_sidebar_menu`` после «Обновить данные и кэш».
    """
    try:
        from config import is_release_client_mode
    except Exception:
        is_release_client_mode = lambda: False  # type: ignore[assignment,misc]

    if is_release_client_mode():
        opts = ["Из папки web/", "FTP → web/", "Загрузить вручную"]
    else:
        opts = ["Загрузить вручную", "Из папки web/", "FTP → web/"]

    st.markdown(
        '<p class="sidebar-section-title" style="margin-top:0.5rem;">Данные</p>',
        unsafe_allow_html=True,
    )

    def _on_mode_change() -> None:
        try:
            v = st.session_state.get("data_mode_radio")
            if v in ("Из папки web/", "FTP → web/"):
                st.session_state["_pending_web_folder_load"] = True
                st.session_state["_pending_web_load_quiet"] = False
        except Exception:
            pass

    st.radio(
        "Источник",
        opts,
        key="data_mode_radio",
        label_visibility="collapsed",
        on_change=_on_mode_change,
    )

    mode = str(st.session_state.get("data_mode_radio") or "Из папки web/")

    if mode in ("Из папки web/", "FTP → web/"):
        if st.button(
            "Загрузить из web/",
            width="stretch",
            key="sidebar_load_web",
        ):
            st.session_state["_pending_web_folder_load"] = True
            st.session_state["_pending_web_load_quiet"] = False

    if mode == "FTP → web/":
        with st.expander("FTP", expanded=False):
            _render_ftp_sidebar_controls(st)

    _render_version_sidebar_compact(st)


def _render_ftp_sidebar_controls(st: Any) -> None:
    from ftp_sync import merge_ftp_config, streamlit_secrets_to_config, sync_ftp_to_web
    from web_loader import get_web_dir, load_all_from_web

    st.text_input("Host", key="ftp_host_override")
    st.text_input("User", key="ftp_user_override")
    st.text_input("Password", type="password", key="ftp_pass_override")
    st.text_input("Папка", value="/web", key="ftp_remote_dir_override")

    cfg = merge_ftp_config(streamlit_secrets_to_config())
    _h = str(st.session_state.get("ftp_host_override") or "").strip()
    _u = str(st.session_state.get("ftp_user_override") or "").strip()
    _p = st.session_state.get("ftp_pass_override")
    _d = str(st.session_state.get("ftp_remote_dir_override") or "").strip()
    if _h:
        cfg["host"] = _h
    if _u:
        cfg["user"] = _u
    if _p:
        cfg["password"] = _p
    if _d:
        cfg["remote_dir"] = _d

    if st.button("FTP → web/ → БД", width="stretch", key="sidebar_ftp_sync"):
        if not cfg.get("host") or not cfg.get("user"):
            st.error("Задайте host и user.")
            return
        web_p = get_web_dir()
        web_p.mkdir(parents=True, exist_ok=True)
        with st.spinner("FTP…"):
            ftp_res = sync_ftp_to_web(
                web_p,
                config=cfg,
                extensions=(".csv", ".json"),
                progress=lambda _m: None,
            )
        if ftp_res.get("errors"):
            for e in ftp_res["errors"]:
                st.error(str(e))
        else:
            with st.spinner("web/ → БД…"):
                result = load_all_from_web()
            st.session_state["last_load_result"] = result
            st.cache_data.clear()
            st.session_state.pop("web_version_id", None)
            st.session_state["_pending_web_folder_load"] = False
            st.rerun()


def _render_version_sidebar_compact(st: Any) -> None:
    try:
        from web_schema import get_active_version_id, get_all_versions
    except Exception:
        return

    versions = get_all_versions()
    if not versions:
        st.caption("Версия данных: нет снимков в БД")
        return

    active_id = get_active_version_id()
    ids_ordered = [int(v["id"]) for v in versions]
    by_id = {int(v["id"]): v for v in versions}

    def _fmt(vid: int) -> str:
        v = by_id.get(int(vid)) or {}
        base = (
            f"{v.get('created_at', '')} | "
            f"файлов: {v.get('files_count', 0)}, "
            f"строк: {v.get('rows_count', 0)}"
        )
        try:
            cur = get_active_version_id()
        except Exception:
            cur = active_id
        if cur is not None and int(vid) == int(cur):
            return f"{base} ✅"
        return base

    _default = (
        int(active_id)
        if active_id is not None and _safe_int(active_id) in ids_ordered
        else ids_ordered[0]
    )
    _cur = _safe_int(st.session_state.get("web_version_pick_id"))
    if _cur is None or _cur not in ids_ordered:
        st.session_state["web_version_pick_id"] = _default

    st.selectbox(
        "Версия",
        ids_ordered,
        format_func=_fmt,
        key="web_version_pick_id",
        label_visibility="visible",
    )


def apply_web_version_pick(
    st: Any,
    *,
    build_pseudo_lr_from_db: Callable[[int], Optional[dict]],
) -> None:
    """Синхронизировать session_state с выбранной в сайдбаре версией (без UI на main)."""
    try:
        from data_health import build_environment_fingerprint, save_schema_health_report
        from data_readiness import build_data_readiness_report
        from web_loader import read_version_to_session
        from web_schema import activate_version, get_active_version_id, get_all_versions
    except Exception:
        return

    versions = get_all_versions()
    if not versions:
        return

    active_id = get_active_version_id()
    ids_ordered = [int(v["id"]) for v in versions]
    selected = _safe_int(st.session_state.get("web_version_pick_id"))
    if selected is None or selected not in ids_ordered:
        selected = (
            int(active_id)
            if active_id is not None and _safe_int(active_id) in ids_ordered
            else ids_ordered[0]
        )
        st.session_state["web_version_pick_id"] = selected

    if selected != st.session_state.get("web_version_id") or st.session_state.get(
        "project_data"
    ) is None:
        activate_version(selected)
        read_version_to_session(selected)
        st.session_state["web_version_id"] = selected
        try:
            _pseudo = build_pseudo_lr_from_db(int(selected))
            if _pseudo:
                st.session_state["last_load_result"] = _pseudo
        except Exception:
            pass
        try:
            st.session_state["last_data_readiness"] = build_data_readiness_report(
                st.session_state.get("last_load_result")
            )
            st.session_state["last_data_schema_health"] = save_schema_health_report(
                load_result=st.session_state.get("last_load_result")
            )
            st.session_state["last_env_fingerprint"] = build_environment_fingerprint(
                st.session_state.get("last_load_result")
            )
            from data_contract import evaluate_data_contract

            st.session_state["last_data_contract"] = evaluate_data_contract(
                st.session_state.get("last_load_result")
            )
        except Exception:
            pass
