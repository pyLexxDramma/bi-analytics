"""
Регистр дашбордов: имя отчёта -> функция отрисовки.
Функции отрисовки импортируются из dashboards._renderers.
"""
from typing import Callable, Dict, List, Tuple

from dashboards.export_wrap import run_dashboard_with_auto_export, slug_report_name

# Категории для трёх блоков радиокнопок на главной странице (не путать с порядком REPORT_CATEGORIES).
MAIN_PANEL_TIMELINE_CATEGORY = "Сроки"
MAIN_PANEL_FINANCE_CATEGORY = "Финансы"


def get_main_panel_report_lists(role: str) -> Tuple[List[str], List[str], List[str]]:
    """
    Возвращает (отчёты «Сроки», отчёты «Финансы», все остальные отчёты) с учётом RBAC.
    Единый источник — REPORT_CATEGORIES; не зависит от порядка категорий в списке.
    """
    from auth import filter_reports_for_role

    timeline: List[str] = []
    finance: List[str] = []
    for title, reps in REPORT_CATEGORIES:
        if title == MAIN_PANEL_TIMELINE_CATEGORY:
            timeline = list(reps)
        elif title == MAIN_PANEL_FINANCE_CATEGORY:
            finance = list(reps)
    all_flat: List[str] = []
    for _, reps in REPORT_CATEGORIES:
        all_flat.extend(list(reps))
    other = [r for r in all_flat if r not in timeline and r not in finance]
    return (
        filter_reports_for_role(role, timeline),
        filter_reports_for_role(role, finance),
        filter_reports_for_role(role, other),
    )


REPORT_CATEGORIES: List[Tuple[str, List[str]]] = [
    (
        "Девелоперские проекты",
        [
            "Девелоперские проекты",
        ],
    ),
    (
        "Сроки",
        [
            "Причины отклонений",
            "Отклонение от базового плана",
            "Контрольные точки",
            "График проекта",
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
        "Проектные работы",
        [
            "Рабочая документация",
            "Проектная документация",
            "Просрочка выдачи РД",
            "Просрочка выдачи ПД",
        ],
    ),
    (
        "ГДРС",
        [
            "ГДРС",
            "ГДРС Техника",
        ],
    ),
    (
        "Исполнительная документация",
        [
            "Исполнительная документация",
        ],
    ),
    (
        "Неустраненные предписания",
        [
            "Неустраненные предписания",
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
    dashboard_working_documentation = getattr(
        _renderers, "dashboard_working_documentation", dashboard_documentation
    )
    dashboard_project_documentation = getattr(
        _renderers, "dashboard_project_documentation", dashboard_documentation
    )
    dashboard_technique = _renderers.dashboard_technique
    dashboard_technique_tabs = getattr(_renderers, "dashboard_technique_tabs", None)
    if dashboard_technique_tabs is None:
        dashboard_technique_tabs = _renderers.dashboard_technique
    dashboard_workforce_movement = _renderers.dashboard_workforce_movement
    # R23-05 стр.14: восстановленный отчёт «Техника».
    dashboard_gdrs_equipment = getattr(_renderers, "dashboard_gdrs_equipment", None)
    if dashboard_gdrs_equipment is None:
        dashboard_gdrs_equipment = dashboard_technique_tabs
    dashboard_executive_documentation = getattr(_renderers, "dashboard_executive_documentation", None)
    if dashboard_executive_documentation is None:

        def _stub_executive(df):
            st.header("Исполнительная документация")
            st.info("Раздел в разработке.")

        dashboard_executive_documentation = _stub_executive
    dashboard_debit_credit = getattr(_renderers, "dashboard_debit_credit", None)
    if dashboard_debit_credit is None:

        def _stub_debit(df):
            st.header("Дебиторская и кредиторская задолженность подрядчиков")
            st.info("Загрузите файл с данными по задолженности подрядчиков.")

        dashboard_debit_credit = _stub_debit

    dashboard_predpisania = _renderers.dashboard_predpisania
    dashboard_developer_projects = _renderers.dashboard_developer_projects
    dashboard_control_points = getattr(_renderers, "dashboard_control_points", None)
    dashboard_project_schedule_chart = getattr(_renderers, "dashboard_project_schedule_chart", None)
    dashboard_pravki_report_hidden = getattr(_renderers, "dashboard_pravki_report_hidden", None)
    dashboard_pd_delay = getattr(_renderers, "dashboard_pd_delay", None)

    if dashboard_control_points is None:

        def _stub_cp(df):
            st.header("Контрольные точки")
            st.info("Модуль в разработке (правки 04.2026).")

        dashboard_control_points = _stub_cp

    if dashboard_project_schedule_chart is None:

        def _stub_psc(df):
            st.header("График проекта")
            st.info("Модуль в разработке (правки 04.2026).")

        dashboard_project_schedule_chart = _stub_psc

    if dashboard_pravki_report_hidden is None:

        def _stub_hidden(df):
            st.info("Отчёт скрыт по правкам заказчика.")

        dashboard_pravki_report_hidden = _stub_hidden

    if dashboard_pd_delay is None:
        dashboard_pd_delay = dashboard_rd_delay

    raw: Dict[str, Callable] = {
        # Сроки: каноническое имя «Причины отклонений» + обратная совместимость
        "Причины отклонений": dashboard_deviations_combined,
        "Динамика отклонений": dashboard_deviations_combined,
        "Динамика причин отклонений": dashboard_deviations_combined,
        "Контрольные точки": dashboard_control_points,
        "График проекта": dashboard_project_schedule_chart,
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
        "Значения отклонений от базового плана": dashboard_pravki_report_hidden,
        "Рабочая/Проектная документация": dashboard_documentation,
        "Рабочая документация": dashboard_working_documentation,
        "Проектная документация": dashboard_project_documentation,
        # R23-05 стр.14: «ГДРС» — рабочие; отдельный пункт «ГДРС Техника»; отдельный экран «СКУД по неделям» удалён (4.3).
        "ГДРС": dashboard_technique_tabs,
        "ГДРС Техника": dashboard_gdrs_equipment,
        "Дебиторская и кредиторская задолженность подрядчиков": dashboard_debit_credit,
        "Исполнительная документация": dashboard_executive_documentation,
        "Просрочка выдачи РД": dashboard_rd_delay,
        "Просрочка выдачи ПД": dashboard_pd_delay,
        "Неустраненные предписания": dashboard_predpisania,
        # Обратная совместимость со старым именем отчёта.
        "Предписания по подрядчикам": dashboard_predpisania,
        "Девелоперские проекты": dashboard_developer_projects,
    }
    return raw


# Ленивая загрузка, чтобы при импорте dashboards не тянуть project_visualization_app
# Увеличьте версию при изменении реестра отчётов — иначе долгоживущий процесс Streamlit
# может держать устаревший словарь в памяти.
_DASHBOARDS_REGISTRY_VERSION = 46
_dashboards_cache: Dict[str, Callable] = {}
_dashboards_cache_version: int = 0


def get_dashboards() -> Dict[str, Callable]:
    """Возвращает словарь DASHBOARDS (кэшируется)."""
    global _dashboards_cache, _dashboards_cache_version
    if not _dashboards_cache or _dashboards_cache_version != _DASHBOARDS_REGISTRY_VERSION:
        _dashboards_cache = _get_dashboards()
        _dashboards_cache_version = _DASHBOARDS_REGISTRY_VERSION
    return _dashboards_cache


def get_dashboard_renderer(name: str) -> Callable:
    """Возвращает функцию отрисовки по имени отчёта или None."""
    return get_dashboards().get(name)


def get_all_report_names() -> List[str]:
    """Возвращает плоский список всех имён отчётов (для report_params, filters и т.д.)."""
    return [r for _, reports in REPORT_CATEGORIES for r in reports]
