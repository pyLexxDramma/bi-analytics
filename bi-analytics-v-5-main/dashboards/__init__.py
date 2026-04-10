"""
Регистр дашбордов: имя отчёта -> функция отрисовки.
Функции отрисовки импортируются из dashboards._renderers.
"""
from functools import partial
from typing import Callable, Dict, List, Tuple

from dashboards.export_wrap import run_dashboard_with_auto_export, slug_report_name

REPORT_CATEGORIES: List[Tuple[str, List[str]]] = [
    (
        "Девелоперские проекты",
        [
            "Девелоперские проекты",
        ],
    ),
    (
        "Предписания по подрядчикам",
        [
            "Предписания по подрядчикам",
        ],
    ),
    (
        "Исполнительная документация",
        [
            "Исполнительная документация",
        ],
    ),
    (
        "ГДРС",
        [
            "ГДРС",
        ],
    ),
    (
        "Проектные работы",
        [
            "Рабочая/Проектная документация",
            "Просрочка выдачи РД",
        ],
    ),
    (
        "Финансы",
        [
            "БДДС",
            "БДР",
            "Бюджет план/факт",
            "Утвержденный бюджет",
            "Прогнозный бюджет",
            "Дебиторская и кредиторская задолженность подрядчиков",
        ],
    ),
    (
        "Сроки",
        [
            "Динамика отклонений",
            "Отклонение от базового плана",
            "Значения отклонений от базового плана",
        ],
    ),
    (
        "Здоровье проектов",
        [
            "Здоровье проектов",
        ],
    ),
]


def _get_dashboards() -> Dict[str, Callable]:
    """Строит словарь имя_отчёта -> render(df). Импорт из dashboards._renderers."""
    import os
    import sys
    import streamlit as st
    # Родительская папка (bi-analytics) должна быть в sys.path для config, utils и т.д.
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _parent = os.path.dirname(_this_dir)
    if _parent and _parent not in sys.path:
        sys.path.insert(0, _parent)
    try:
        from dashboards import _renderers
    except Exception as e:
        import traceback
        _tb = traceback.format_exc()
        # Печатаем причину в stderr, чтобы она не терялась при обрезке логов
        import sys
        print(f"[dashboards] Ошибка загрузки _renderers: {e!r}", file=sys.stderr)
        print(_tb, file=sys.stderr)
        raise RuntimeError(
            f"Ошибка при загрузке дашбордов (dashboards._renderers): {e!r}. "
            f"Проверьте: 1) наличие config.py и utils.py в корне проекта; "
            f"2) что проект запускается из корня bi-analytics (или он в sys.path). "
            f"Полный traceback:\n{_tb}"
        ) from e

    dashboard_deviations_combined = _renderers.dashboard_deviations_combined
    dashboard_reasons_of_deviation = _renderers.dashboard_reasons_of_deviation
    dashboard_dynamics_of_deviations = _renderers.dashboard_dynamics_of_deviations
    dashboard_plan_fact_dates = _renderers.dashboard_plan_fact_dates
    dashboard_deviation_by_tasks_current_month = _renderers.dashboard_deviation_by_tasks_current_month
    dashboard_dynamics_of_reasons = _renderers.dashboard_dynamics_of_reasons
    dashboard_budget_by_period = _renderers.dashboard_budget_by_period
    dashboard_budget_by_section = _renderers.dashboard_budget_by_section
    dashboard_bdr = getattr(_renderers, "dashboard_bdr", None)
    if dashboard_bdr is None:

        def _stub_bdr(df):
            st.error(
                "Дашборд БДР не найден в dashboards/_renderers.py. "
                "Убедитесь, что функция dashboard_bdr определена в файле."
            )

        dashboard_bdr = _stub_bdr
    dashboard_budget_by_type = _renderers.dashboard_budget_by_type
    dashboard_approved_budget = _renderers.dashboard_approved_budget
    dashboard_forecast_budget = _renderers.dashboard_forecast_budget
    dashboard_rd_delay = _renderers.dashboard_rd_delay
    dashboard_documentation = _renderers.dashboard_documentation
    dashboard_technique = _renderers.dashboard_technique
    dashboard_technique_tabs = getattr(_renderers, "dashboard_technique_tabs", None)
    if dashboard_technique_tabs is None:
        dashboard_technique_tabs = _renderers.dashboard_technique
    dashboard_workforce_movement = _renderers.dashboard_workforce_movement
    dashboard_executive_documentation = getattr(_renderers, "dashboard_executive_documentation", None)
    if dashboard_executive_documentation is None:

        def _stub_executive(df):
            st.header("Исполнительная документация")
            st.info("Раздел в разработке.")

        dashboard_executive_documentation = _stub_executive
    dashboard_project_health = getattr(_renderers, "dashboard_project_health", None)
    if dashboard_project_health is None:

        def _stub_health(df):
            st.header("Здоровье проектов")
            st.info("Загрузите файл с данными проекта с колонкой «Фаза».")

        dashboard_project_health = _stub_health
    dashboard_debit_credit = getattr(_renderers, "dashboard_debit_credit", None)
    if dashboard_debit_credit is None:

        def _stub_debit(df):
            st.header("Дебиторская и кредиторская задолженность подрядчиков")
            st.info("Загрузите файл с данными по задолженности подрядчиков.")

        dashboard_debit_credit = _stub_debit

    dashboard_predpisania = getattr(_renderers, "dashboard_predpisania", None)
    if dashboard_predpisania is None:

        def _stub_predpisania(df):
            st.header("Предписания по подрядчикам")
            tessa_df = st.session_state.get("tessa_data")
            if tessa_df is None or tessa_df.empty:
                st.warning("Для отчёта необходимы данные из TESSA. Загрузите файлы tessa_*.")
                return
            work = tessa_df.copy()
            work.columns = [str(c).strip() for c in work.columns]
            kind_col = None
            for c in ["KindName", "kindname"]:
                if c in work.columns:
                    kind_col = c
                    break
            if kind_col:
                pred = work[work[kind_col].astype(str).str.contains("Предписан", case=False, na=False)]
            else:
                pred = pd.DataFrame()
            if pred.empty:
                st.info("Нет данных по предписаниям в загруженных файлах TESSA.")
                return
            st.metric("Всего предписаний", len(pred))
            import plotly.express as px
            if "CONTR" in pred.columns:
                by_contr = pred.groupby("CONTR").size().reset_index(name="Количество").sort_values("Количество", ascending=True)
                fig = px.bar(by_contr, y="CONTR", x="Количество", orientation="h",
                             labels={"CONTR": "Подрядчик"}, text="Количество",
                             color_discrete_sequence=["#E85D75"])
                fig.update_traces(textposition="outside", textfont=dict(color="white"))
                fig.update_layout(height=max(350, len(by_contr)*35+100), yaxis_title="", xaxis_title="Количество")
                from dashboards._renderers import apply_chart_background, render_chart
                fig = apply_chart_background(fig)
                render_chart(fig, caption_below="Предписания по подрядчикам")
            display_cols = [c for c in ["ObjectName","CONTR","DocNumber","DocDescription","KrState","CreationDate"] if c in pred.columns]
            if display_cols:
                from dashboards._renderers import _render_html_table
                st.subheader("Таблица предписаний")
                _render_html_table(pred[display_cols].rename(columns={
                    "ObjectName": "Объект", "CONTR": "Контрагент",
                    "DocNumber": "Номер", "DocDescription": "Описание",
                    "KrState": "Статус", "CreationDate": "Дата создания",
                }))

        dashboard_predpisania = _stub_predpisania

    dashboard_developer_projects = getattr(_renderers, "dashboard_developer_projects", None)
    if dashboard_developer_projects is None:

        def _stub_developer(df):
            st.header("Девелоперские проекты")
            if df is None or df.empty:
                st.warning("Загрузите данные проекта (MSP) для отчёта «Девелоперские проекты».")
                return
            st.info("Отчёт «Девелоперские проекты» находится в разработке. "
                    "Будут реализованы: таблица по фазам/стадиям, план/факт/отклонение, "
                    "подсветка при % выполнения ≠ 100, выборка ДС и предписания.")

        dashboard_developer_projects = _stub_developer

    raw: Dict[str, Callable] = {
        "Динамика отклонений": dashboard_deviations_combined,
        "Динамика отклонений по месяцам": dashboard_deviations_combined,
        "Динамика причин отклонений": dashboard_deviations_combined,
        "БДДС": dashboard_budget_by_period,
        "БДДС по месяцам": dashboard_budget_by_period,
        "БДР": dashboard_bdr,
        "Бюджет по лотам": dashboard_budget_by_period,
        "Бюджет план/факт": dashboard_budget_by_type,
        "Бюджет План/Прогноз/Факт": dashboard_budget_by_type,
        "Утвержденный бюджет": dashboard_approved_budget,
        "Бюджет по проекту": dashboard_approved_budget,
        "Прогнозный бюджет": dashboard_forecast_budget,
        "Отклонение от базового плана": dashboard_plan_fact_dates,
        "Значения отклонений от базового плана": dashboard_deviation_by_tasks_current_month,
        "Рабочая/Проектная документация": dashboard_documentation,
        "ГДРС": dashboard_technique_tabs,
        "Дебиторская и кредиторская задолженность подрядчиков": dashboard_debit_credit,
        "Исполнительная документация": dashboard_executive_documentation,
        "Здоровье проектов": dashboard_project_health,
        "Просрочка выдачи РД": dashboard_rd_delay,
        "Предписания по подрядчикам": dashboard_predpisania,
        "Девелоперские проекты": dashboard_developer_projects,
    }
    return raw


# Ленивая загрузка, чтобы при импорте dashboards не тянуть project_visualization_app
_dashboards_cache: Dict[str, Callable] = {}


def get_dashboards() -> Dict[str, Callable]:
    """Возвращает словарь DASHBOARDS (кэшируется)."""
    global _dashboards_cache
    if not _dashboards_cache:
        _dashboards_cache = _get_dashboards()
    return _dashboards_cache


def get_dashboard_renderer(name: str) -> Callable:
    """Возвращает функцию отрисовки по имени отчёта или None."""
    return get_dashboards().get(name)


def get_all_report_names() -> List[str]:
    """Возвращает плоский список всех имён отчётов (для report_params, filters и т.д.)."""
    return [r for _, reports in REPORT_CATEGORIES for r in reports]
