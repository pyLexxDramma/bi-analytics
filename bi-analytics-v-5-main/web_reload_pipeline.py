# -*- coding: utf-8 -*-
"""Синхронное обновление данных: FTP → web/ → SQLite → session_state."""

from __future__ import annotations

from typing import Any, Optional


def finalize_web_load_session(st: Any, result: dict, *, quiet: bool = False) -> None:
    """После load_all_from_web: контракт, активная версия, session из БД."""
    try:
        from data_health import build_environment_fingerprint, save_schema_health_report
        from data_readiness import build_data_readiness_report

        st.session_state["last_load_result"] = result
        st.session_state["last_data_readiness"] = build_data_readiness_report(result)
        st.session_state["last_data_schema_health"] = save_schema_health_report(
            load_result=result
        )
        st.session_state["last_env_fingerprint"] = build_environment_fingerprint(result)
        from data_contract import evaluate_data_contract

        st.session_state["last_data_contract"] = evaluate_data_contract(result)
    except Exception:
        st.session_state["last_data_readiness"] = None
        st.session_state["last_data_schema_health"] = None
        st.session_state["last_env_fingerprint"] = None
        st.session_state["last_data_contract"] = None

    st.cache_data.clear()

    try:
        from web_schema import get_active_version_id
        from web_loader import read_version_to_session

        active_id = get_active_version_id()
        if active_id is not None:
            read_version_to_session(int(active_id))
            st.session_state["web_version_id"] = int(active_id)
            st.session_state["web_version_pick_id"] = int(active_id)
            st.session_state["_auto_hydrated_from_db"] = True
    except Exception as exc:
        try:
            from auto_ingest import safe_stderr_log

            safe_stderr_log(f"[web_reload] read_version_to_session failed: {exc!r}")
        except Exception:
            pass

    if not quiet:
        loaded = int(result.get("loaded") or 0)
        skipped = int(result.get("skipped") or 0)
        if result.get("errors"):
            st.warning(f"Загружено: {loaded}, пропущено: {skipped}")
            for err in (result.get("errors") or [])[:10]:
                st.error(str(err))
        else:
            try:
                st.toast(f"Данные обновлены: {loaded} файлов", icon="✅")
            except Exception:
                pass

    try:
        from auth import get_current_user
        from logger import log_action

        u = get_current_user()
        if u:
            log_action(
                u["username"],
                "data_loaded",
                f"ftp+web: loaded={result.get('loaded')}, skipped={result.get('skipped')}",
            )
    except Exception:
        pass


def run_ftp_force_reload_ui(st: Any, *, quiet: bool = False) -> None:
    """
    Полный цикл по кнопке «FTP + перезагрузить БД».
    Выполняется в основной области (после сайдбара), затем один st.rerun().
    """
    for _k in ("_auto_hydrated_from_db", "_auto_hydrated_from_web"):
        st.session_state.pop(_k, None)

    from auto_ingest import _ftp_credentials_configured, maybe_ftp_sync_before_web_load
    from web_loader import load_all_from_web, web_dir_exists

    _ftp_ok = False
    _ftp_reason = ""
    ftp_res: Optional[dict] = None

    if quiet:
        ftp_res = maybe_ftp_sync_before_web_load(log_prefix="[ftp_force_reload]")
    else:
        with st.status("Обновление данных с FTP…", expanded=True) as status:
            status.write("Шаг 1/2: синхронизация с FTP (1–5 мин)…")
            ftp_res = maybe_ftp_sync_before_web_load(log_prefix="[ftp_force_reload]")
            if isinstance(ftp_res, dict):
                st.session_state["last_ftp_sync_result"] = ftp_res
                _errs = ftp_res.get("errors") or []
                _trans = ftp_res.get("transient_errors") or []
                if _errs:
                    _ftp_ok = False
                    _ftp_reason = f"FTP: ошибки ({len(_errs)})"
                    status.write("⚠ " + _ftp_reason)
                elif _trans:
                    _ftp_ok = True
                    _ftp_reason = f"FTP: временные ошибки ({len(_trans)}), локальные копии сохранены"
                    status.write("⚠ " + _ftp_reason)
                else:
                    _ftp_ok = True
                    status.write(
                        f"FTP: скачано {len(ftp_res.get('downloaded') or [])} файлов, "
                        f"без изменений {int(ftp_res.get('skipped_same_size') or 0)}"
                    )
            elif not _ftp_credentials_configured():
                _ftp_reason = "FTP не настроен (BI_FTP_HOST / USER / PASSWORD)"
                status.write("⚠ " + _ftp_reason)
            else:
                _ftp_reason = "Авто-FTP отключён (BI_ANALYTICS_AUTO_FTP_ON_START=0)"
                status.write("⚠ " + _ftp_reason)

            if not web_dir_exists():
                status.update(label="Ошибка: каталог web/ не найден", state="error")
                st.error(
                    "Не найден каталог web/. Проверьте FTP и пути BI_ANALYTICS_WEB_EXTRA_PATHS."
                )
                return

            status.write("Шаг 2/2: пересборка БД из web/ (5–15 мин при полном скане)…")
            result = load_all_from_web()
            finalize_web_load_session(st, result, quiet=quiet)
            loaded = int(result.get("loaded") or 0)
            status.update(
                label=f"Готово: {loaded} файлов в БД, отчёты обновлены",
                state="complete",
            )

    if quiet:
        if isinstance(ftp_res, dict):
            st.session_state["last_ftp_sync_result"] = ftp_res
            _ftp_ok = not (ftp_res.get("errors") or [])
        if not web_dir_exists():
            return
        result = load_all_from_web()
        finalize_web_load_session(st, result, quiet=True)

    st.session_state["_data_pull_ftp_ok"] = _ftp_ok
    st.session_state["_data_pull_ftp_reason"] = _ftp_reason
    if isinstance(ftp_res, dict):
        st.session_state["_ftp_sync_notice"] = ftp_res

    if not quiet:
        st.rerun()
