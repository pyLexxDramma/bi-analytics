# -*- coding: utf-8 -*-
"""Синхронное обновление данных: FTP → web/ → SQLite → session_state."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional


def _fmt_duration(seconds: float) -> str:
    """Человекочитаемая длительность: '45с', '2м 05с', '1ч 03м'."""
    s = max(0, int(round(seconds)))
    if s < 60:
        return f"{s}с"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m}м {sec:02d}с"
    h, m2 = divmod(m, 60)
    return f"{h}ч {m2:02d}м"


class _FtpProgressTracker:
    """Живой статус FTP-загрузки: счётчик скачанных файлов + прошедшее время.

    FTP-обход рекурсивный и общее число файлов заранее неизвестно, поэтому
    показываем счётчик скачанных и текущий файл (без процентов).
    """

    def __init__(self, writer: Optional[Callable[[str], None]] = None) -> None:
        self._writer = writer
        self._downloaded = 0
        self._start = time.monotonic()
        self._last_emit = 0.0

    def __call__(self, msg: str) -> None:
        text = str(msg or "")
        if text.startswith("Скачивание"):
            self._downloaded += 1
        if self._writer is None:
            return
        now = time.monotonic()
        # Не чаще ~2 раз в секунду, чтобы не спамить перерисовкой.
        if now - self._last_emit < 0.5 and not text.startswith("Повторная"):
            return
        self._last_emit = now
        elapsed = _fmt_duration(now - self._start)
        try:
            self._writer(
                f"Скачано файлов: {self._downloaded} · прошло {elapsed}\n\n{text}"
            )
        except Exception:
            pass


def make_db_rebuild_progress(st: Any):
    """Прогресс-бар пересборки БД из web/ с оценкой оставшегося времени (ETA).

    Возвращает ``(callback, finish)``: ``callback(done, total, name)`` передаётся в
    ``load_all_from_web(progress=...)``, ``finish()`` убирает индикатор после загрузки.
    """
    bar = st.progress(0.0, text="Подготовка к пересборке БД…")
    state = {"start": time.monotonic()}

    def _callback(done: int, total: int, name: str) -> None:
        total = max(1, int(total))
        done = max(0, min(int(done), total))
        frac = done / total
        elapsed = time.monotonic() - state["start"]
        eta_txt = ""
        if done >= 2 and frac < 1.0:
            rate = elapsed / done
            remaining = rate * (total - done)
            eta_txt = f" · осталось ~{_fmt_duration(remaining)}"
        short = str(name or "")
        if len(short) > 48:
            short = short[:45] + "…"
        try:
            bar.progress(
                frac,
                text=f"Файл {done}/{total}{eta_txt} · {short}",
            )
        except Exception:
            pass

    def _finish() -> None:
        try:
            bar.empty()
        except Exception:
            pass

    return _callback, _finish


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
        ftp_res = maybe_ftp_sync_before_web_load(
            log_prefix="[ftp_force_reload]", prune_orphans=True
        )
    else:
        with st.status("Обновление данных с FTP…", expanded=True) as status:
            status.write("Шаг 1/2: синхронизация с FTP (1–5 мин)…")
            _ftp_line = st.empty()
            _ftp_tracker = _FtpProgressTracker(writer=lambda m: _ftp_line.markdown(m))
            ftp_res = maybe_ftp_sync_before_web_load(
                log_prefix="[ftp_force_reload]", prune_orphans=True,
                progress=_ftp_tracker,
            )
            try:
                _ftp_line.empty()
            except Exception:
                pass
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
                    _deleted_n = len(ftp_res.get("deleted") or [])
                    _del_txt = f", удалено отсутствующих на FTP {_deleted_n}" if _deleted_n else ""
                    status.write(
                        f"FTP: скачано {len(ftp_res.get('downloaded') or [])} файлов, "
                        f"без изменений {int(ftp_res.get('skipped_same_size') or 0)}{_del_txt}"
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

            status.write("Шаг 2/2: пересборка БД из web/ (оценка появится по ходу)…")
            _db_cb, _db_finish = make_db_rebuild_progress(st)
            _t0 = time.monotonic()
            try:
                result = load_all_from_web(progress=_db_cb)
            finally:
                _db_finish()
            finalize_web_load_session(st, result, quiet=quiet)
            loaded = int(result.get("loaded") or 0)
            _elapsed = _fmt_duration(time.monotonic() - _t0)
            status.update(
                label=f"Готово за {_elapsed}: {loaded} файлов в БД, отчёты обновлены",
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
