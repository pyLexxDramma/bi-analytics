# -*- coding: utf-8 -*-
"""
Содержимое вкладок административной панели (без Streamlit bootstrap страницы).

Импортируется из pages/profile.py и pages/_admin.py.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timezone

_TABLE_CSS = (
    "<style>"
    ".ht-wrap{overflow-x:auto;min-width:0;margin:.5rem 0 1rem}"
    ".ht{width:100%;border-collapse:collapse;font-size:13px;font-family:Inter,system-ui,sans-serif}"
    ".ht th{position:sticky;top:0;background:#1a1c23;color:#fafafa;padding:6px 8px;text-align:left;"
    "border-bottom:2px solid #444;font-weight:600;white-space:nowrap;max-width:18em;overflow:hidden;text-overflow:ellipsis}"
    ".ht td{padding:5px 8px;border-bottom:1px solid #333;color:#e0e0e0;white-space:nowrap;"
    "max-width:16em;overflow:hidden;text-overflow:ellipsis}"
    ".ht tr:hover td{background:#262833}"
    "</style>"
)

def _html_table(df, max_rows=300):
    show = df.head(max_rows).copy()
    for col in show.columns:
        show[col] = [str(v) if pd.notna(v) else "" for v in show[col]]
    html = show.to_html(index=False, classes="ht", escape=True, border=0)
    st.markdown(_TABLE_CSS + '<div class="ht-wrap">' + html + '</div>', unsafe_allow_html=True)
import sqlite3

from auth import (
    get_user_role_display,
    delete_user,
    ROLES,
)
from config import DB_PATH, switch_page_app
from logger import log_action, get_logs, get_logs_count
from settings import get_setting, set_setting, get_all_settings, SETTING_KEYS
from utils import (
    format_dataframe_as_html,
    load_custom_css,
    outline_level_numeric,
    render_dataframe_excel_csv_downloads,
)
try:
    from filters import (
        get_default_filters,
        set_default_filter,
        delete_default_filter,
        get_all_default_filters,
        copy_filters_to_role,
        AVAILABLE_REPORTS,
        FILTER_TYPES,
    )
except ImportError as e:
    # Определяем заглушки для избежания ошибок
    AVAILABLE_REPORTS = []
    FILTER_TYPES = {}

    def get_default_filters(*args, **kwargs):
        return {}

    def set_default_filter(*args, **kwargs):
        return False

    def delete_default_filter(*args, **kwargs):
        return False

    def get_all_default_filters(*args, **kwargs):
        return []

    def copy_filters_to_role(*args, **kwargs):
        return False

    # Логируем ошибку, но не используем st, так как он может быть не инициализирован
    import warnings

# ┌──────────────────────────────────────────────────────────────────────────┐ #
# │ ⊗ Benchmark LLM — логика вкладки                                         │ #
# └──────────────────────────────────────────────────────────────────────────┘ #

import json as _json
import time as _time
import pathlib as _pathlib

_BENCH_SYSTEM = (
    "Ты — помощник аналитика строительных проектов. "
    "Отвечай на русском, кратко и по делу."
)

_BENCH_PROMPTS: dict[str, tuple[str, str]] = {
    "G1": ("KPI список", "Перечисли 5 ключевых KPI строительного проекта. Ответ — нумерованным списком, без пояснений."),
    "G2": ("JSON формат", 'Верни JSON-объект с полями "metric", "value", "unit" для фразы: «Отклонение бюджета 12.5 млн руб.»'),
    "G3": ("Математика", "Бюджет плана 84 615 384.62 руб. Факт — 78 000 000 руб. Посчитай абсолютное отклонение и процент. Ответ — Markdown-таблицей."),
    "G4": ("Суммаризация", "Сократи до 2 предложений: «Проект Дмитровский-8 — жилой комплекс из 4 корпусов. Старт: март 2023, план завершения: декабрь 2025. Выполнено 72 %. Отклонение — задержка фундамента корпуса 3 на 45 дней (грунтовые условия). Бюджет в плане.»"),
    "G5": ("Галлюцинации", "У тебя нет доступа к базе данных. Какова точная дата завершения проекта «Сколково-7»? Если не знаешь — скажи, что данных нет."),
    "D1": ("Отклонение сроков", "Задача «Фундамент сборный»: план 10.01.2026, факт 19.01.2026. Отклонение в днях? Критично? Ответ — 3 предложения."),
    "D2": ("Бюджет план/факт", "Раздел «КОРОБКА, КРОВЛЯ, СТЕНЫ»: план 120 млн руб., факт 134.2 млн руб. Перерасход в % и 2 причины."),
    "D3": ("Причина отклонения", "Задача «Идеальные полы» отклонилась на 28 дней, раздел «КОРОБКА». Сформулируй 3 вероятные причины."),
    "D4": ("РД документация", "Объясни колонки «РД по Договору», «Отклонение разделов РД», «Всего загружено», «На согласовании» — 4 пункта."),
    "D5": ("Прогноз", "Старт 01.03.2023, план конец 30.12.2025, выполнено 72 %, отклонение +45 дн. Прогноз завершения с расчётом."),
    "D6": ("Таблица → вывод", "Таблица: Альфа 100/95, Бета 200/230, Гамма 150/150 (план/факт). Какой проект в зоне риска? 1 предложение."),
    "D7": ("Ресурсы", "Контрагент «Строй-М»: 3 неделя — 120 чел.-дней, план 95. Дельта +26 %. Хорошо или плохо?"),
    "D8": ("Сравнение этапов", "«Кабелетоковые каналы»: 0 дн. отклонения. «Металлические конструкции»: +18 дн. Аналитический вывод для руководителя."),
    "D9": ("Markdown-отчёт", "Markdown-таблица «Топ-3 задачи по отклонению»: Фундамент +9, Полы +28 (нет подрядчика), Кровля +3. Колонки: Задача, Отклонение (дни), Причина."),
    "D10": ("Классификация", "0 дн. — зелёный, 1–14 — жёлтый, >14 — красный. Задача с 18 дн. — какой статус? Одно слово + цвет."),
    "D11": ("Текст слайда", "Абзац для слайда «Статус Дмитровский-8»: 72 %, бюджет ОК, срок +45 дн., причина — грунт. 3–4 предложения."),
    "D12": ("SQL", "«Покажи задачи проекта Есенина-V с отклонением >10 дней». SQL к tasks(project_name, task_name, deviation_days)."),
    "D13": ("Интерпретация", "На Gantt красный столбец (факт) правее синего (план). Что это значит? 2 предложения."),
    "D14": ("Рекомендации", "3 задачи в красной зоне, 5 в жёлтой, 12 в зелёной. 3 конкретных управленческих действия."),
    "D15": ("Перевод", "Переведи на англ.: «Отклонение фактических сроков от базового плана — 45 дней. Причина — изменение решений по фундаменту.»"),
}

_BENCH_RESULTS_DIR = _pathlib.Path(__file__).resolve().parent / "docs" / "bench_results"


_PROVIDER_PRESETS = {
    "Свой сервер (vLLM / Ollama)": {"url": "http://localhost:8000/v1", "model": "Qwen/Qwen3-8B", "needs_key": False},
    "Groq (free tier)":            {"url": "https://api.groq.com/openai/v1", "model": "qwen-qwq-32b", "needs_key": True},
    "Together.ai":                 {"url": "https://api.together.xyz/v1", "model": "Qwen/Qwen2.5-7B-Instruct-Turbo", "needs_key": True},
    "OpenRouter":                  {"url": "https://openrouter.ai/api/v1", "model": "qwen/qwen3-8b", "needs_key": True},
    "OpenAI":                      {"url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "needs_key": True},
}


def _call_llm(base_url: str, model: str, prompt: str, temperature: float, max_tokens: int, api_key: str = ""):
    """Один вызов к OpenAI-совместимому API. Возвращает (content, tok_in, tok_out, elapsed_s, error)."""
    import urllib.request
    import urllib.error

    url = base_url.rstrip("/") + "/chat/completions"
    payload = _json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _BENCH_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "top_p": 0.9,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=payload, headers=headers)
    t0 = _time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = _json.loads(resp.read().decode("utf-8"))
        elapsed = _time.perf_counter() - t0
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        return content, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), round(elapsed, 3), None
    except Exception as exc:
        elapsed = _time.perf_counter() - t0
        return "", 0, 0, round(elapsed, 3), str(exc)[:200]


def _render_benchmark_tab(user):
    """Содержимое вкладки Benchmark LLM в админке."""
    st.markdown("<h2 class='Duquhununee'>Benchmark LLM</h2>", unsafe_allow_html=True)

    st.info(
        "Сравнение LLM-моделей на доменных промптах (строительная аналитика). "
        "Выберите провайдер, укажите API-ключ (если нужен) и нажмите «Запустить»."
    )

    # --- Шаг 1: настройки ---
    st.markdown("### 1. Настройки подключения")

    provider_names = list(_PROVIDER_PRESETS.keys())
    provider = st.selectbox(
        "Провайдер",
        provider_names,
        index=0,
        key="bench_provider",
    )
    preset = _PROVIDER_PRESETS[provider]

    col_url, col_model = st.columns(2)
    with col_url:
        base_url = st.text_input(
            "Base URL (OpenAI-compatible)",
            value=st.session_state.get("bench_base_url", preset["url"]),
            key="bench_base_url_input",
        )
    with col_model:
        model_name = st.text_input(
            "Имя модели",
            value=st.session_state.get("bench_model", preset["model"]),
            key="bench_model_input",
        )

    api_key = ""
    if preset["needs_key"]:
        api_key = st.text_input(
            "API Key",
            type="password",
            value=st.session_state.get("bench_api_key", ""),
            key="bench_api_key_input",
        )
        if not api_key:
            st.warning(f"Для {provider} нужен API-ключ. Получите его на сайте провайдера.")

    # Быстрая проверка подключения
    if st.button("Проверить подключение", key="bench_ping_btn"):
        with st.spinner("Подключение..."):
            content, _ti, _to, elapsed, error = _call_llm(
                base_url, model_name, "Ответь одним словом: работает?", 0.0, 16, api_key=api_key
            )
        if error:
            st.error(f"Ошибка: {error}")
        else:
            st.success(f"OK ({elapsed:.2f}с): {content[:80]}")

    col_temp, col_tok, col_runs = st.columns(3)
    with col_temp:
        temperature = st.slider("Температура", 0.0, 1.0, 0.3, 0.05, key="bench_temp")
    with col_tok:
        max_tokens = st.number_input("max_tokens", 64, 2048, 512, 64, key="bench_max_tok")
    with col_runs:
        runs = st.number_input("Прогонов на промпт", 1, 5, 1, 1, key="bench_runs")

    # --- Шаг 2: выбор промптов ---
    st.markdown("### 2. Промпты")
    prompt_ids = list(_BENCH_PROMPTS.keys())
    general_ids = [p for p in prompt_ids if p.startswith("G")]
    domain_ids = [p for p in prompt_ids if p.startswith("D")]

    col_g, col_d = st.columns(2)
    with col_g:
        select_general = st.checkbox("Общие (G1–G5)", value=True, key="bench_sel_g")
    with col_d:
        select_domain = st.checkbox("Доменные (D1–D15)", value=True, key="bench_sel_d")

    selected = []
    if select_general:
        selected += general_ids
    if select_domain:
        selected += domain_ids

    if selected:
        with st.expander(f"Выбрано промптов: {len(selected)}", expanded=False):
            for pid in selected:
                label, text = _BENCH_PROMPTS[pid]
                st.markdown(f"**{pid}** — {label}")
                _prev = text[:120] + ("…" if len(text) > 120 else "")
                st.markdown(f"*{_prev}*")

    # --- Шаг 3: запуск ---
    st.markdown("### 3. Запуск")
    if not selected:
        st.warning("Выберите хотя бы одну группу промптов.")
        return

    total_calls = len(selected) * int(runs)
    st.write(f"Будет выполнено **{total_calls}** запросов к `{model_name}`.")

    can_run = bool(not preset["needs_key"] or api_key)
    if st.button("Запустить benchmark", type="primary", key="bench_run_btn", disabled=not can_run):
        st.session_state["bench_base_url"] = base_url
        st.session_state["bench_model"] = model_name
        if api_key:
            st.session_state["bench_api_key"] = api_key

        results = []
        progress = st.progress(0, text="Подготовка...")
        status_area = st.empty()
        done = 0

        for pid in selected:
            label, prompt_text = _BENCH_PROMPTS[pid]
            for run_idx in range(1, int(runs) + 1):
                done += 1
                progress.progress(done / total_calls, text=f"{pid} (прогон {run_idx}/{int(runs)})")
                status_area.caption(f"Отправка {pid}...")

                content, tok_in, tok_out, elapsed, error = _call_llm(
                    base_url, model_name, prompt_text, temperature, int(max_tokens), api_key=api_key
                )
                tok_s = round(tok_out / elapsed, 1) if elapsed > 0 and tok_out > 0 else 0.0
                results.append({
                    "prompt_id": pid,
                    "label": label,
                    "run": run_idx,
                    "model": model_name,
                    "input_tokens": tok_in,
                    "output_tokens": tok_out,
                    "elapsed_s": elapsed,
                    "tok_per_sec": tok_s,
                    "answer": content,
                    "error": error,
                })
                if done < total_calls:
                    _time.sleep(2)

        progress.progress(1.0, text="Готово!")
        status_area.empty()
        st.session_state["bench_last_results"] = results

    # --- Шаг 4: результаты ---
    results = st.session_state.get("bench_last_results")
    if not results:
        # Попробуем загрузить последний сохранённый файл
        _show_saved_results()
        return

    st.markdown("### 4. Результаты")

    df = pd.DataFrame(results)
    ok = df[df["error"].isna()]
    err = df[df["error"].notna()]

    if not err.empty:
        st.error(f"Ошибок: {len(err)} из {len(df)}")
        with st.expander("Ошибки"):
            for _, row in err.iterrows():
                st.markdown(f"**{row['prompt_id']}** run {row['run']}: `{row['error']}`")

    if ok.empty:
        st.warning("Нет успешных ответов.")
        return

    # Сводка
    st.markdown("#### Производительность")
    perf = ok.groupby("prompt_id").agg(
        tok_s_median=("tok_per_sec", "median"),
        elapsed_median=("elapsed_s", "median"),
        output_tokens_median=("output_tokens", "median"),
    ).reset_index()
    perf.columns = ["Промпт", "tok/s (медиана)", "Latency, с (медиана)", "Выход, токенов"]
    _html_table(perf)

    avg_tok_s = ok["tok_per_sec"].median()
    avg_latency = ok["elapsed_s"].median()
    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Медиана tok/s", f"{avg_tok_s:.1f}")
    col_m2.metric("Медиана latency", f"{avg_latency:.2f} с")
    col_m3.metric("Успешных", f"{len(ok)}/{len(df)}")

    # Ответы
    st.markdown("#### Ответы модели")
    for pid in selected:
        pid_rows = ok[ok["prompt_id"] == pid]
        if pid_rows.empty:
            continue
        label, prompt_text = _BENCH_PROMPTS.get(pid, (pid, ""))
        best_row = pid_rows.loc[pid_rows["tok_per_sec"].idxmax()]
        with st.expander(f"{pid} — {label}  |  {best_row['tok_per_sec']} tok/s, {best_row['elapsed_s']}s"):
            st.markdown(f"**Промпт:** {prompt_text}")
            st.markdown("---")
            st.markdown(best_row["answer"])

    # Сохранение
    st.markdown("#### Сохранить")
    if st.button("Сохранить результаты в JSON", key="bench_save_btn"):
        _BENCH_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = model_name.replace("/", "_")
        out = _BENCH_RESULTS_DIR / f"bench_{safe}_{ts}.json"
        out.write_text(_json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        log_action(user["username"], "llm_benchmark", f"Benchmark {model_name}: {len(ok)} ok, {len(err)} err → {out.name}")
        st.success(f"Сохранено: `{out.name}`")


def _show_saved_results():
    """Показывает список ранее сохранённых JSON-файлов с результатами."""
    if not _BENCH_RESULTS_DIR.exists():
        return
    files = sorted(_BENCH_RESULTS_DIR.glob("bench_*.json"), reverse=True)
    if not files:
        return
    st.markdown("### Ранее сохранённые прогоны")
    chosen = st.selectbox(
        "Файл", [f.name for f in files], key="bench_saved_select"
    )
    if chosen and st.button("Загрузить", key="bench_load_btn"):
        data = _json.loads((_BENCH_RESULTS_DIR / chosen).read_text(encoding="utf-8"))
        st.session_state["bench_last_results"] = data
        st.rerun()


def _render_control_points_msp_tab(user: dict) -> None:
    """
    Администратор: вкладка «MSP: задача для метрик».
    Вехи, заголовки и соответствие MSP для «Контрольных точек»; задача MSP для «Отклонения от базового плана».
    """
    def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
        if df is None or getattr(df, "empty", True):
            return None
        for cand in candidates:
            for col in df.columns:
                if str(col).strip().lower() == cand.lower():
                    return col
        for cand in candidates:
            for col in df.columns:
                if cand.lower() in str(col).strip().lower():
                    return col
        return None

    def _msp_metric_task_options() -> tuple[list[tuple[int, str]], str | None, str | None]:
        df = st.session_state.get("project_data")
        if df is None or getattr(df, "empty", True):
            return [], None, "MSP-данные еще не загружены в текущую сессию."
        task_col = _find_col(df, ["task name", "Task Name", "Название", "Задача"])
        level_col = _find_col(df, ["level structure", "outline level", "level", "Уровень"])
        if not task_col or not level_col:
            return [], task_col, "Не найдены колонки MSP с названием задачи и уровнем."
        levels = outline_level_numeric(df[level_col])
        li = pd.to_numeric(levels, errors="coerce").round()
        mask = li.isin([2, 3])
        sub = df.loc[mask, [task_col, level_col]].copy()
        sub["_msp_lvl"] = li.loc[sub.index].astype(float).round().astype(int)
        if sub.empty:
            return [], task_col, "В текущей выгрузке MSP нет задач уровней 2 и 3."
        sub[task_col] = sub[task_col].astype(str).str.strip()
        sub = sub[sub[task_col].ne("") & sub[task_col].str.lower().ne("nan")]
        sub = sub.drop_duplicates(subset=[task_col, "_msp_lvl"]).sort_values(
            ["_msp_lvl", task_col], kind="stable"
        )
        options = [(int(row["_msp_lvl"]), str(row[task_col])) for _, row in sub.iterrows()]
        if not options:
            return [], task_col, "В MSP не найдено ни одной валидной задачи уровней 2 и 3."
        return options, task_col, None

    st.subheader("Email администратора")
    st.caption(
        "Используется как контактный email в отчёте «Девелоперские проекты» и может применяться в уведомлениях."
    )
    cur_em = (get_setting("admin_notification_email") or "").strip()
    new_em = st.text_input(
        "Email администратора",
        value=cur_em,
        placeholder="например, admin@company.ru",
        key="admin_notification_email_field",
    )
    if st.button("Сохранить email администратора", type="secondary", key="admin_save_notification_email_btn"):
        set_setting(
            "admin_notification_email",
            str(new_em).strip(),
            description=SETTING_KEYS.get("admin_notification_email", ""),
            updated_by=user.get("username"),
        )
        log_action(
            user.get("username") or "admin",
            "admin_setting",
            "admin_notification_email updated",
        )
        st.success("Сохранено.")
        st.rerun()

    st.divider()

    st.subheader("Контрольные точки: вехи, столбцы, MSP")
    from dashboards._renderers import render_control_points_milestones_admin_settings

    render_control_points_milestones_admin_settings(key_prefix="admin_cp_msp")

    st.subheader("Девелоперские проекты: матрица контрольных точек")
    from dashboards._renderers import render_developer_projects_matrix_admin_settings

    render_developer_projects_matrix_admin_settings(key_prefix="admin_dev_matrix")

    st.divider()
    st.markdown("<h2 class='Duquhununee'>MSP: задача для метрик</h2>", unsafe_allow_html=True)

    st.markdown("### Отчёт «Отклонение от базового плана»")
    st.markdown(
        "Название задачи MSP для метрик **«окончание проекта»** в отчёте «Отклонение от базового плана» "
        "(здесь — запасной выбор, если на странице отчёта не задано). "
        "Оставьте пустым — эвристика (ЗОС / ввод в эксплуатацию)."
    )
    _cur_task = (get_setting("baseline_plan_task_for_metrics") or "").strip()
    task_options, task_col, task_options_hint = _msp_metric_task_options()
    if task_options:
        option_values = [("", "")] + task_options
        selected_option = ("", "")
        if _cur_task:
            for opt in task_options:
                if opt[1] == _cur_task:
                    selected_option = opt
                    break
        try:
            _sel_idx = option_values.index(selected_option)
        except ValueError:
            _sel_idx = 0
        _selected_task = st.selectbox(
            "Задача для расчёта окончания проекта (MSP)",
            option_values,
            index=_sel_idx,
            key="admin_baseline_task_for_metrics_select",
            format_func=lambda opt: "Автовыбор" if not opt[1] else f"Уровень {opt[0]} - {opt[1]}",
        )
        _tf_task = _selected_task[1]
    else:
        _tf_task = st.text_input(
            "Задача для расчёта окончания проекта (MSP)",
            value=_cur_task,
            key="admin_baseline_task_for_metrics",
        )
        if task_options_hint:
            st.warning(task_options_hint)
    if st.button("Сохранить задачу для метрик", type="primary", key="admin_save_baseline_task"):
        set_setting(
            "baseline_plan_task_for_metrics",
            str(_tf_task).strip(),
            description=SETTING_KEYS.get("baseline_plan_task_for_metrics", ""),
            updated_by=user.get("username"),
        )
        log_action(
            user.get("username") or "admin",
            "admin_setting",
            "baseline_plan_task_for_metrics",
        )
        st.success("Сохранено.")
        st.rerun()


# ┌──────────────────────────────────────────────────────────────────────────┐ #
# │ ⊗ Красивый формат даты ¤ Start                                           │ #
# └──────────────────────────────────────────────────────────────────────────┘ #

def format_russian_datetime(dt_str):

    """Преобразует ISO-строку в формат '12 фев. 2026, 14:35' с неразрывными пробелами"""

    if not dt_str or dt_str in ("-", None, ""):

        return "-"

    try:
        import pytz
        from datetime import timezone

        dt_str_clean = dt_str.split('.')[0]
        dt = datetime.fromisoformat(dt_str_clean)

        # Если дата без timezone — считаем её UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # Конвертируем в московское время
        moscow_tz = pytz.timezone("Europe/Moscow")
        dt = dt.astimezone(moscow_tz)

        months_ru = ["янв.", "фев.", "мар.", "апр.", "май", "июн.",
                     "июл.", "авг.", "сен.", "окт.", "ноя.", "дек."]
        month = months_ru[dt.month - 1]
        nbsp = "\u00A0"
        return f"{dt.day}{nbsp}{month}{nbsp}{dt.year},{nbsp}{dt:%H:%M}"

    except Exception:

        return dt_str

# ┌──────────────────────────────────────────────────────────────────────────┐ #

def render_admin_panel_tabs(user: dict) -> None:
    """Скрипт автоскролла вкладок + шесть вкладок админки."""

    # JavaScript для автоматического скролла к содержимому выбранной вкладки
    st.markdown(
        """
        <script>
        (function() {
            function scrollToActiveTabContent() {
                setTimeout(function() {
                    // Находим активную панель вкладки (содержимое, не заголовок)
                    const activePanel = document.querySelector('[role="tabpanel"][aria-hidden="false"]');
                    if (!activePanel) return;

                    // Находим первый значимый элемент контента внутри панели
                    // Пропускаем заголовки вкладок и ищем реальное содержимое
                    const contentElements = activePanel.querySelectorAll('div[data-testid="stVerticalBlock"] > div, h1, h2, h3, .stSubheader');
                    let targetElement = null;

                    // Ищем первый элемент, который не является частью заголовка вкладки
                    for (let i = 0; i < contentElements.length; i++) {
                        const elem = contentElements[i];
                        // Проверяем, что элемент не находится в заголовке вкладки
                        if (!elem.closest('[data-baseweb="tab-list"]') &&
                            !elem.closest('[data-baseweb="tab"]')) {
                            targetElement = elem;
                            break;
                        }
                    }

                    // Если не нашли, используем саму панель, но с отступом
                    if (!targetElement) {
                        targetElement = activePanel;
                    }

                    // Вычисляем позицию с учетом отступа от верха
                    const elementPosition = targetElement.getBoundingClientRect().top;
                    const offsetPosition = elementPosition + window.pageYOffset - 100; // 100px отступ от верха

                    // Плавный скролл
                    window.scrollTo({
                        top: offsetPosition,
                        behavior: 'smooth'
                    });
                }, 200);
            }

            // Выполняем скролл при загрузке
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', scrollToActiveTabContent);
            } else {
                scrollToActiveTabContent();
            }

            // Отслеживаем клики по вкладкам
            document.addEventListener('click', function(e) {
                if (e.target.closest('[data-baseweb="tab"]')) {
                    scrollToActiveTabContent();
                }
            });

            // Отслеживаем изменения активной вкладки через MutationObserver
            const observer = new MutationObserver(function(mutations) {
                mutations.forEach(function(mutation) {
                    if (mutation.type === 'attributes') {
                        // Проверяем изменения aria-selected или aria-hidden
                        if ((mutation.attributeName === 'aria-selected' &&
                             mutation.target.getAttribute('aria-selected') === 'true') ||
                            (mutation.attributeName === 'aria-hidden' &&
                             mutation.target.getAttribute('aria-hidden') === 'false' &&
                             mutation.target.getAttribute('role') === 'tabpanel')) {
                            scrollToActiveTabContent();
                        }
                    }
                });
            });

            // Наблюдаем за вкладками и панелями
            setTimeout(function() {
                const tabs = document.querySelectorAll('[data-baseweb="tab"]');
                const panels = document.querySelectorAll('[role="tabpanel"]');

                tabs.forEach(tab => {
                    observer.observe(tab, {
                        attributes: true,
                        attributeFilter: ['aria-selected']
                    });
                });

                panels.forEach(panel => {
                    observer.observe(panel, {
                        attributes: true,
                        attributeFilter: ['aria-hidden']
                    });
                });
            }, 500);
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        [
            "Пользователи",
            "Статистика",
            "Логи",
            "Права доступа",
            "Benchmark LLM",
            "MSP: задача для метрик",
        ]
    )

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 1: Управление пользователями ¤ Start                           │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    with tab1:

        st.markdown("<h2 class='Duquhununee'>Управление пользователями</h2>", unsafe_allow_html=True)

        # Список пользователей
        st.markdown("<h3 class='Muquhununee'>Список пользователей</h3>", unsafe_allow_html=True)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, username, role, email, created_at, last_login, is_active
            FROM users
            ORDER BY created_at DESC
        """
        )

        users = cursor.fetchall()

        conn.close()

        if users:
            users_data = []
            for u in users:
                created_formatted = format_russian_datetime(u[4]) if u[4] else "-"
                last_login_formatted = format_russian_datetime(u[5]) if u[5] else "Никогда"

                users_data.append(
                    {
                        "ID": u[0],
                        "Имя пользователя": u[1],
                        "Роль": get_user_role_display(u[2]),
                        "Email": u[3] or "-",
                        "Создан": created_formatted,
                        "Последний вход": last_login_formatted,
                        "Активен": "✅" if u[6] else "❌",
                    }
                )

            df_users = pd.DataFrame(users_data)
            html_table = format_dataframe_as_html(df_users)
            st.markdown(html_table, unsafe_allow_html=True)
        else:
            st.info("Пользователи не найдены")

        # st.markdown("---")

        # Добавление нового пользователя
        st.markdown("### Добавить нового пользователя")

        with st.form("add_user_form"):

            # ─── Ловушки для автозаполнения браузера ────────────────────────────────
            st.markdown('<input type="text"     name="fake_username"    style="display:none" autocomplete="username">',     unsafe_allow_html=True)
            st.markdown('<input type="password" name="fake_password"    style="display:none" autocomplete="new-password">', unsafe_allow_html=True)

            col1, col2 = st.columns(2)

            with col1:
                new_username = st.text_input("Имя пользователя *")
                new_email = st.text_input("Email")

            with col2:
                new_password = st.text_input("Пароль *", type="password")
                new_role = st.selectbox(
                    "Роль *", options=list(ROLES.keys()), format_func=lambda x: ROLES[x]
                )

            submitted = st.form_submit_button("Добавить пользователя", type="primary")

            if submitted:
                if new_username and new_password:
                    if new_role == "superadmin":
                        conn = sqlite3.connect(DB_PATH)
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT COUNT(*) FROM users WHERE role = 'superadmin' AND is_active = 1"
                        )
                        superadmin_count = cursor.fetchone()[0]
                        conn.close()
                        if superadmin_count >= 1:
                            st.error("В системе уже есть суперадминистратор. Допускается только один.")
                            st.stop()
                    from auth import create_user

                    if create_user(
                        new_username,
                        new_password,
                        new_role,
                        new_email if new_email else None,
                        user["username"],
                    ):
                        st.success(f"Пользователь {new_username} успешно создан!")
                        st.rerun()
                    else:
                        st.error(
                            "Ошибка при создании пользователя. Возможно, пользователь с таким именем уже существует."
                        )
                else:
                    st.warning("Заполните обязательные поля (отмечены *)")

        # st.markdown("---")

        # Изменение роли пользователя
        st.markdown("### Изменить роль пользователя")

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, role FROM users WHERE is_active = 1 ORDER BY username"
        )
        active_users = cursor.fetchall()
        conn.close()

        if active_users:
            with st.form("change_role_form"):
                user_options = {
                    f"{u[1]} ({get_user_role_display(u[2])})": u[0]
                    for u in active_users
                }
                selected_user_display = st.selectbox(
                    "Выберите пользователя", options=list(user_options.keys())
                )
                selected_user_id = user_options[selected_user_display]

                # Получаем текущую роль
                selected_username = selected_user_display.split(" (")[0]
                current_role = None
                for u in active_users:
                    if u[0] == selected_user_id:
                        current_role = u[2]
                        break

                new_role = st.selectbox(
                    "Новая роль *",
                    options=list(ROLES.keys()),
                    format_func=lambda x: ROLES[x],
                    index=list(ROLES.keys()).index(current_role) if current_role else 0,
                )

                submitted = st.form_submit_button("Изменить роль", type="primary")

                if submitted:
                    if new_role != current_role:
                        conn = sqlite3.connect(DB_PATH)
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT COUNT(*) FROM users WHERE role = 'superadmin' AND is_active = 1"
                        )
                        superadmin_count = cursor.fetchone()[0]
                        conn.close()
                        if new_role == "superadmin" and current_role != "superadmin" and superadmin_count >= 1:
                            st.error("В системе уже есть суперадминистратор. Допускается только один.")
                            st.stop()
                        if current_role == "superadmin" and new_role != "superadmin" and superadmin_count <= 1:
                            st.error("Нельзя снять роль у единственного суперадминистратора.")
                            st.stop()
                        conn = sqlite3.connect(DB_PATH)
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE users SET role = ? WHERE id = ?",
                            (new_role, selected_user_id),
                        )
                        conn.commit()
                        conn.close()

                        log_action(
                            user["username"],
                            "change_role",
                            f"Изменена роль пользователя {selected_username} с {get_user_role_display(current_role)} на {get_user_role_display(new_role)}",
                        )
                        if selected_username == user["username"]:
                            session_user = st.session_state.get("user") or {}
                            session_user["role"] = new_role
                            st.session_state["user"] = session_user
                            user["role"] = new_role
                        st.success(
                            # f"✅ Роль пользователя {selected_username} успешно изменена на {get_user_role_display(new_role)}!"
                            f"Роль пользователя {selected_username} успешно изменена на {get_user_role_display(new_role)}!"
                        )
                        st.rerun()
                    else:
                        st.warning("Выберите другую роль")
        else:

            st.info("Нет активных пользователей")

        # Удаление пользователя (только для суперадминистратора)
        if user["role"] == "superadmin":
            st.markdown("### Удалить пользователя")

            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, username, role FROM users WHERE username != ? AND role != 'superadmin' ORDER BY username",
                (user["username"],),
            )
            deletable_users = cursor.fetchall()
            conn.close()

            if deletable_users:
                del_options = {
                    f"{u[1]} ({get_user_role_display(u[2])})": u[0]
                    for u in deletable_users
                }
                del_selected = st.selectbox(
                    "Выберите пользователя для удаления",
                    options=list(del_options.keys()),
                    key="del_user_select",
                )
                del_user_id = del_options[del_selected]
                del_username = del_selected.split(" (")[0]

                confirm = st.checkbox(
                    f"Подтверждаю удаление пользователя «{del_username}» и всех его данных",
                    key="del_user_confirm",
                )

                if st.button(
                    "Удалить пользователя",
                    type="primary",
                    disabled=not confirm,
                    key="del_user_btn",
                ):
                    ok, msg = delete_user(del_user_id, user["username"])
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            else:
                st.info("Нет пользователей, доступных для удаления")

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 1: Управление пользователями ¤ End                             │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 2: Статистика ¤ Start                                          │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    with tab2:

        st.markdown("<h2 class='Duquhununee'>Статистика системы</h2>", unsafe_allow_html=True)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Общая статистика
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
        active_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE last_login IS NOT NULL")
        users_with_login = cursor.fetchone()[0]

        # Статистика по ролям
        cursor.execute(
            """
            SELECT role, COUNT(*) as count
            FROM users
            GROUP BY role
        """
        )
        role_stats = cursor.fetchall()

        # Статистика логов
        total_logs = get_logs_count()
        recent_logs = get_logs_count(action="login")

        conn.close()

        col1, col2, col3, col4 = st.columns(4)

        with col1:

            st.metric("Всего пользователей", total_users)

        with col2:

            st.metric("Активных пользователей", active_users)

        with col3:

            st.metric("Пользователей с входом", users_with_login)

        with col4:

            st.metric("Всего действий в логах", total_logs)

        st.markdown("---")

        # Статистика по ролям
        st.markdown("### Распределение по ролям")
        if role_stats:
            role_data = [
                {"Роль": get_user_role_display(r[0]), "Количество": r[1]}
                for r in role_stats
            ]
            df_roles = pd.DataFrame(role_data)
            html_table = format_dataframe_as_html(df_roles)
            st.markdown(html_table, unsafe_allow_html=True)
        else:
            st.info("Нет данных")

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 2: Статистика ¤ End                                            │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 3: Логи действий ¤ Start                                       │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    with tab3:

        st.markdown("<h2 class='Duquhununee'>Логи действий пользователей</h2>", unsafe_allow_html=True)

        # Фильтры
        col1, col2, col3 = st.columns(3)
        col4, col5 = st.columns(2)

        with col1:

            conn = sqlite3.connect(DB_PATH)

            usernames = pd.read_sql_query(
                "SELECT DISTINCT username FROM user_activity_logs ORDER BY username",
                conn
            )["username"].tolist()

            conn.close()

            filter_username = st.selectbox("Фильтр по пользователю", ["Все"] + usernames)

        with col2:

            conn = sqlite3.connect(DB_PATH)

            actions = pd.read_sql_query(
                "SELECT DISTINCT action FROM user_activity_logs ORDER BY action",
                conn
            )["action"].tolist()

            conn.close()

            filter_action = st.selectbox("Фильтр по действию", ["Все"] + actions)

        with col3:

            log_limit = st.number_input("Количество записей", 10, 1000, 100, 10)

        with col4:
            date_from = st.date_input("С даты (UTC)", value=None, key="log_date_from")
        with col5:
            date_to = st.date_input("По дату (UTC)", value=None, key="log_date_to")

        username_filter = None if filter_username == "Все" else filter_username
        action_filter = None if filter_action == "Все" else filter_action
        created_after_iso = None
        created_before_iso = None
        if date_from:
            created_after_iso = datetime.combine(date_from, time.min, tzinfo=timezone.utc).isoformat()
        if date_to:
            created_before_iso = datetime.combine(date_to, time.max, tzinfo=timezone.utc).isoformat()

        # Получаем логи
        logs = get_logs(
            limit=log_limit,
            username=username_filter,
            action=action_filter,
            created_after=created_after_iso,
            created_before=created_before_iso,
        )

        if logs:

            logs_data = []

            for log in logs:

                created_at = log.get("created_at", None)

                formatted_time = format_russian_datetime(log.get("created_at")) if log.get("created_at") else "-"

                ip = log.get("ip_address") or "-"

                logs_data.append({
                    "ID": log.get("id", "-"),
                    "Пользователь": log.get("username", "-"),
                    "Действие": log.get("action", "-"),
                    "Детали": log.get("details") or "-",
                    "IP\u00A0адрес": ip,
                    "Дата\u00A0и\u00A0время": formatted_time,
                })

            df_logs = pd.DataFrame(logs_data)

            # Если хочешь красивую дату ещё и в сортировке — можно добавить скрытую колонку
            # df_logs["sort_time"] = pd.to_datetime(df_logs["Время"], format=..., errors="coerce")
            # но обычно достаточно просто сортировки по строке

            html_table = format_dataframe_as_html(df_logs)
            st.markdown(html_table, unsafe_allow_html=True)

            # Экспорт
            _logs_stem = f"logs_{datetime.now():%Y%m%d_%H%M%S}"
            render_dataframe_excel_csv_downloads(
                df_logs,
                file_stem=_logs_stem,
                key_prefix="admin_action_logs",
                csv_label="Скачать логи (CSV для Excel)",
            )

        else:
            st.info("Логи не найдены")

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 3: Логи действий ¤ End                                         │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 4: Права доступа к проектам ¤ Start                            │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    with tab4:
        st.markdown("<h2 class='Duquhununee'>Права доступа</h2>", unsafe_allow_html=True)
        st.info(
            "Разрезка прав по отдельным проектам отключена. "
            "Доступ определяется только ролью пользователя."
        )
        roles_df = pd.DataFrame(
            [
                {"Код роли": code, "Роль": title}
                for code, title in ROLES.items()
            ]
        )
        _html_table(roles_df)

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 4: Права доступа к проектам ¤ End                              │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 5: Benchmark LLM ¤ Start                                       │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    with tab5:
        _render_benchmark_tab(user)

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 5: Benchmark LLM ¤ End                                         │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 6: MSP — задача для метрик отчёта «Отклонение от базового плана»│ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    with tab6:
        _render_control_points_msp_tab(user)
