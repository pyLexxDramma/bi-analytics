"""
Загрузка данных из CSV/Excel и обновление session state.
Вся логика «прочитать файл и положить в сессию» — только здесь.
"""
import csv
import re
from typing import Optional, Tuple

import pandas as pd
import streamlit as st


def detect_data_type(df: pd.DataFrame, file_name: Optional[str] = None) -> str:
    """Определение типа данных по структуре колонок и имени файла."""
    columns = [str(col).lower() for col in df.columns]
    columns_joined = " ".join(columns)
    file_name_lower = str(file_name).lower() if file_name else ""
    has_dd_mm_yyyy_col = any(
        re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", str(c)) for c in df.columns
    )

    # Данные проекта: задача, план дат, бюджет
    if (
        any(col in columns for col in ["задача", "task name"])
        and any(col in columns for col in ["старт план", "plan start"])
        and any(col in columns for col in ["бюджет план", "budget plan"])
    ):
        return "project"

    # ГДРС: кладём в resources — вкладка «Техника» при необходимости подхватывает тот же df из session.
    if ("гдрс" in file_name_lower or "gdrs" in file_name_lower) and (
        "тип ресурс" in columns_joined or has_dd_mm_yyyy_col
    ):
        return "resources"

    # Ресурсы/техника: sample_resources_data.csv, sample_technique_data.csv — Проект, Контрагент, Период, План, Среднее за месяц/неделю, 1–5 неделя, Дельта, Дельта (%)
    has_contractor = any(
        col in columns for col in ["контрагент", "подразделение", "contractor"]
    )
    has_weeks = (
        any(col in columns for col in ["1 неделя", "2 неделя", "3 неделя", "2 недели", "3 недели"])
        or any("неделя" in col or "недели" in col for col in columns)
    )
    has_plan = any(col in columns for col in ["план", "план на месяц", "plan"])
    has_delta = any(
        col in columns for col in ["дельта", "отклонение", "deviation", "delta"]
    )

    if has_contractor and has_weeks and (has_plan or has_delta):
        if "ресурс" in file_name_lower or "resource" in file_name_lower:
            return "resources"
        if "техник" in file_name_lower or "technique" in file_name_lower:
            return "technique"
        if "ресурс" in " ".join(columns) or "resource" in " ".join(columns):
            return "resources"
        if "техник" in " ".join(columns) or "technique" in " ".join(columns):
            return "technique"
        # sample_resources_data.csv — «Среднее за месяц»; sample_technique_data.csv — «Среднее за неделю»
        if any("среднее за месяц" in col for col in columns):
            return "resources"
        if any("среднее за неделю" in col for col in columns):
            return "technique"
        return "resources"

    return "project"


def _score_tabular_shape(df: pd.DataFrame) -> int:
    """
    Оценка «похожести» на нормальную таблицу (ГДРС, ресурсы, проект).
    Нужна, чтобы не брать вариант read_csv с sep=';', когда в файле запятая —
    тогда вся строка попадает в одну колонку и графики пустые.
    """
    if df is None or getattr(df, "empty", True):
        return -10**6
    ncol = len(df.columns)
    names = " ".join(str(c).lower() for c in df.columns)
    score = min(ncol * 2, 40)
    for key in (
        "проект",
        "контрагент",
        "подразделение",
        "план",
        "период",
        "тип ресурс",
        "data_source",
        "среднее",
        "неделя",
        "дельт",
        "задача",
        "бюджет",
        "старт",
        "факт",
    ):
        if key in names:
            score += 10
    for c in df.columns:
        s = str(c).strip()
        if re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", s):
            score += 3
    if ncol <= 2:
        score -= 60
    elif ncol <= 4:
        score -= 15
    try:
        c0 = df.iloc[:, 0]
        med = c0.astype(str).str.len().median()
        if pd.notna(med) and float(med) > 180:
            score -= 40
    except Exception:
        pass
    return score


def _maybe_promote_split_header_row(df: pd.DataFrame) -> pd.DataFrame:
    """
    В Excel-макетах ГДРС подписи недель (1–5 неделя) часто идут второй строкой под шапкой:
    переносим их в имена колонок и удаляем эту строку.
    """
    if df is None or getattr(df, "empty", True) or len(df) < 2:
        return df
    row0 = df.iloc[0]
    promoted = 0
    new_cols = []
    for i, c in enumerate(df.columns):
        v = row0.iloc[i]
        cs = str(c).strip().replace("\n", " ").replace("\r", " ").strip()
        if isinstance(v, str) and re.search(r"\d+\s*недел", v, re.I):
            new_cols.append(v.strip())
            promoted += 1
        else:
            new_cols.append(cs)
    if promoted < 2:
        return df
    out = df.iloc[1:].reset_index(drop=True)
    out.columns = new_cols
    return out


def _maybe_strip_gdrs_instruction_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Убирает строки с текстом ТЗ из макетов (колонка A / «Столбец … — данные из файла»)."""
    if df is None or getattr(df, "empty", True):
        return df
    col0 = df.columns[0]
    s0 = df[col0].map(lambda x: "" if pd.isna(x) else str(x))
    mask = s0.str.len() < 200
    mask &= ~s0.str.contains(r"Столбец\s+\"", regex=True, na=False)
    mask &= ~s0.str.contains("пример данных см", case=False, na=False)
    if "Контрагент" in df.columns:
        sk = df["Контрагент"].map(lambda x: "" if pd.isna(x) else str(x))
        mask &= sk.str.len() < 120
        mask &= ~sk.str.contains("Столбец", na=False)
    out = df.loc[mask.fillna(False)].reset_index(drop=True)
    return out if not out.empty else df


def _read_csv_best_effort(uploaded_file) -> Optional[pd.DataFrame]:
    """Перебор кодировок и разделителей; выбирается вариант с максимальной оценкой таблицы."""
    encodings = ["utf-8-sig", "utf-8", "windows-1251", "cp1251"]
    seps = [";", ",", "\t"]
    best_df = None
    best_sc = None
    for enc in encodings:
        for sep in seps:
            try:
                uploaded_file.seek(0)
                cand = pd.read_csv(
                    uploaded_file,
                    sep=sep,
                    encoding=enc,
                    quoting=csv.QUOTE_MINIMAL,
                    quotechar='"',
                    doublequote=True,
                    decimal=",",
                    low_memory=False,
                )
                sc = _score_tabular_shape(cand)
                if best_sc is None or sc > best_sc:
                    best_sc = sc
                    best_df = cand
            except Exception:
                continue
    if best_df is None:
        for enc in encodings:
            try:
                uploaded_file.seek(0)
                best_df = pd.read_csv(uploaded_file, encoding=enc)
                break
            except Exception:
                continue
        if best_df is None:
            uploaded_file.seek(0)
            best_df = pd.read_csv(uploaded_file)
    return best_df


def _read_excel_best_effort(
    uploaded_file, file_name: Optional[str] = None
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Чтение Excel: шапка может быть на 5–20-й строке; в книге «Правки» таблица ГДРС — на листе «ГДРС».
    Перебираем листы и skiprows, лучший вариант по _score_tabular_shape; затем подхватываем
    вторую строку заголовка (недели) и убираем строки-инструкции из макета.
    """
    best_df = None
    best_sc = None
    note = None

    try:
        uploaded_file.seek(0)
        xl = pd.ExcelFile(uploaded_file)
        sheet_names = list(xl.sheet_names)
    except Exception:
        sheet_names = [0]

    def _sheet_prio(name: object) -> tuple:
        n = str(name).strip().lower()
        if n in ("гдрс", "gdrs"):
            return (0, n)
        if "гдр" in n:
            return (1, n)
        if "ресурс" in n or "рабоч" in n:
            return (2, n)
        return (3, n)

    for sheet in sorted(sheet_names, key=_sheet_prio):
        for skip in range(0, 36):
            try:
                uploaded_file.seek(0)
                cand = pd.read_excel(uploaded_file, sheet_name=sheet, skiprows=skip)
                cand = _maybe_promote_split_header_row(cand)
                sc = _score_tabular_shape(cand)
                nval = f"sheet={sheet!r}, skiprows={skip}"
                if best_sc is None or sc > best_sc:
                    best_sc = sc
                    best_df = cand
                    note = nval
            except Exception:
                continue

    if best_df is None:
        try:
            uploaded_file.seek(0)
            best_df = pd.read_excel(uploaded_file)
            note = None
        except Exception:
            return None, None

    best_df = _maybe_strip_gdrs_instruction_rows(best_df)
    return best_df, note


def load_data(uploaded_file, file_name: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    Загрузка данных из загруженного файла (CSV/Excel).
    Возвращает DataFrame с attrs: data_type, file_name; при ошибке — None.
    """
    try:
        original_name = file_name if file_name else uploaded_file.name
        excel_note = None  # подсказка при чтении .xlsx (skiprows)
        if uploaded_file.name.endswith(".csv"):
            df = _read_csv_best_effort(uploaded_file)
        elif uploaded_file.name.endswith((".xlsx", ".xls")):
            df, excel_note = _read_excel_best_effort(uploaded_file, original_name)
            if df is None:
                uploaded_file.seek(0)
                df = pd.read_excel(uploaded_file)
                excel_note = None
        else:
            st.error("Неподдерживаемый формат файла. Загрузите CSV или Excel файл.")
            return None

        # Нормализация названий колонок (BOM, переносы, пробелы)
        df.columns = [
            str(col).replace("\ufeff", "").replace("\n", " ").replace("\r", " ").strip()
            for col in df.columns
        ]

        # Валидация: пустой файл или нет колонок
        if df.empty or len(df.columns) == 0:
            st.warning(
                f"Файл '{original_name}' пуст или не содержит колонок. "
                "Проверьте кодировку (UTF-8 или Windows-1251) и разделитель (; или ,)."
            )
            return None

        # Маппинг по sample_project_data_fixed.csv (разделитель ;, кодировка UTF-8).
        # Колонки в файле: №, Проект, Аббревиатура, Блок, Раздел, Задача, Старт План, Конец План,
        # Старт Факт, Конец Факт, Отклонение, Отклонений в днях, Причина отклонений, Бюджет План,
        # Бюджет Факт, Резерв, РД по Договору, Отклонение разделов РД, Всего загружено, На согласовании,
        # Выдана подрядчику, Выдано в производство работ, На доработке
        column_mapping = {
            "№": "row no",
            "No": "row no",
            "Проект": "project name",
            "Аббревиатура": "abbreviation",
            "Блок": "block",
            "Раздел": "section",
            "Задача": "task name",
            "Старт Факт": "base start",
            "Конец Факт": "base end",
            "Старт План": "plan start",
            "Конец План": "plan end",
            "Отклонение": "deviation",
            "Отклонений в днях": "deviation in days",
            "Причина отклонений": "reason of deviation",
            "Бюджет План": "budget plan",
            "Бюджет Факт": "budget fact",
            "Бюджет план": "budget plan",
            "Бюджет факт": "budget fact",
            "Резерв": "reserve",
            "Резерв бюджета": "reserve budget",
        }
        for russian_name, english_name in column_mapping.items():
            if russian_name in df.columns and english_name not in df.columns:
                df[english_name] = df[russian_name]
        # Выгрузки MS Project (CSV): «Начало»/«Окончание» вместо «Старт План»/«Конец План»;
        # «Название», «ЛОТ», «ID_проекта» — задача, лот, проект.
        if "plan start" not in df.columns:
            for alt in ("Начало", "начало", "Start"):
                if alt in df.columns:
                    df["plan start"] = df[alt]
                    break
            if "plan start" not in df.columns:
                for alt in ("Базовое_начало", "Базовое начало"):
                    if alt in df.columns:
                        df["plan start"] = df[alt]
                        break
        if "plan end" not in df.columns:
            for alt in ("Окончание", "окончание", "Finish"):
                if alt in df.columns:
                    df["plan end"] = df[alt]
                    break
            if "plan end" not in df.columns:
                for alt in ("Базовое_окончание", "Базовое окончание"):
                    if alt in df.columns:
                        df["plan end"] = df[alt]
                        break
        if "task name" not in df.columns and "Название" in df.columns:
            df["task name"] = df["Название"]
        if "section" not in df.columns:
            for alt in ("ЛОТ", "Лот", "лот"):
                if alt in df.columns:
                    df["section"] = df[alt]
                    break
        if "project name" not in df.columns:
            for alt in ("Проект", "ID_проекта"):
                if alt in df.columns:
                    df["project name"] = df[alt]
                    break
        # Нормализация колонок РД: приводим к виду из sample_project_data_fixed.csv (регистр РД/Договору)
        rd_columns_normalize = {
            "РД по договору": "РД по Договору",
            "рд по договору": "РД по Договору",
            "Отклонение разделов рд": "Отклонение разделов РД",
        }
        for alt_name, canonical in rd_columns_normalize.items():
            if alt_name in df.columns and canonical not in df.columns:
                df[canonical] = df[alt_name]
        # Дополнительно: варианты названий бюджета (регистр, пробелы)
        budget_plan_aliases = ("Бюджет План", "Бюджет план", "Budget Plan", "budget_plan")
        budget_fact_aliases = ("Бюджет Факт", "Бюджет факт", "Budget Fact", "budget_fact")
        for col in list(df.columns):
            c = str(col).strip()
            if "budget plan" not in df.columns and c in budget_plan_aliases:
                df["budget plan"] = df[col].copy()
            if "budget fact" not in df.columns and c in budget_fact_aliases:
                df["budget fact"] = df[col].copy()

        # Даты
        date_columns = ["base start", "base end", "plan start", "plan end"]
        for col in date_columns:
            if col in df.columns:
                if df[col].dtype == "object":
                    df[col] = pd.to_datetime(
                        df[col], errors="coerce", dayfirst=True, format="mixed"
                    )
                else:
                    df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)

        # Периоды для группировки
        for date_col, prefix in [
            ("plan start", "plan_start"),
            ("plan end", "plan"),
            ("base start", "base_start"),
            ("base end", "base"),
        ]:
            if date_col in df.columns:
                mask = df[date_col].notna()
                if mask.any():
                    df.loc[mask, f"{prefix}_day"] = df.loc[mask, date_col].dt.date
                    df.loc[mask, f"{prefix}_month"] = df.loc[
                        mask, date_col
                    ].dt.to_period("M")
                    df.loc[mask, f"{prefix}_quarter"] = df.loc[
                        mask, date_col
                    ].dt.to_period("Q")
                    df.loc[mask, f"{prefix}_year"] = df.loc[
                        mask, date_col
                    ].dt.to_period("Y")

        if "plan end" in df.columns:
            mask = df["plan end"].notna()
            if mask.any():
                df.loc[mask, "plan_month"] = df.loc[mask, "plan end"].dt.to_period("M")
                df.loc[mask, "plan_quarter"] = df.loc[mask, "plan end"].dt.to_period("Q")
                df.loc[mask, "plan_year"] = df.loc[mask, "plan end"].dt.to_period("Y")

        if "base end" in df.columns:
            mask = df["base end"].notna()
            if mask.any():
                df.loc[mask, "actual_month"] = df.loc[mask, "base end"].dt.to_period(
                    "M"
                )
                df.loc[mask, "actual_quarter"] = df.loc[mask, "base end"].dt.to_period(
                    "Q"
                )
                df.loc[mask, "actual_year"] = df.loc[mask, "base end"].dt.to_period("Y")

        data_type = detect_data_type(df, original_name)
        df.attrs["data_type"] = data_type
        df.attrs["file_name"] = original_name
        if excel_note:
            df.attrs["excel_read_hint"] = excel_note
        return df
    except Exception as e:
        st.error(f"Ошибка загрузки файла: {str(e)}")
        return None


def ensure_data_session_state() -> None:
    """Инициализирует ключи данных в st.session_state при отсутствии."""
    if "project_data" not in st.session_state:
        st.session_state.project_data = None
    if "resources_data" not in st.session_state:
        st.session_state.resources_data = None
    if "technique_data" not in st.session_state:
        st.session_state.technique_data = None
    if "debit_credit_data" not in st.session_state:
        st.session_state.debit_credit_data = None
    if "loaded_files_info" not in st.session_state:
        st.session_state.loaded_files_info = {}
    if "project_data_all_snapshots" not in st.session_state:
        st.session_state["project_data_all_snapshots"] = None
    if "previous_uploaded_files" not in st.session_state:
        st.session_state.previous_uploaded_files = []
    if "tessa_data" not in st.session_state:
        st.session_state.tessa_data = None
    if "tessa_tasks_data" not in st.session_state:
        st.session_state.tessa_tasks_data = None
    if "reference_contractors" not in st.session_state:
        st.session_state.reference_contractors = None
    if "reference_krstates" not in st.session_state:
        st.session_state.reference_krstates = None
    if "reference_docstates" not in st.session_state:
        st.session_state.reference_docstates = None
    if "reference_1c_dannye" not in st.session_state:
        st.session_state.reference_1c_dannye = None
    if "reference_partner_to_project" not in st.session_state:
        st.session_state.reference_partner_to_project = None


def update_session_with_loaded_file(df: pd.DataFrame, file_id: str) -> None:
    """Добавляет загруженный DataFrame в session state по его типу."""
    data_type = df.attrs.get("data_type", "project")
    if data_type == "project":
        if st.session_state.project_data is None:
            st.session_state.project_data = df
        else:
            st.session_state.project_data = pd.concat(
                [st.session_state.project_data, df], ignore_index=True
            )
        st.session_state.loaded_files_info[file_id] = {
            "type": "project",
            "rows": len(df),
            "columns": list(df.columns),
        }
    elif data_type == "resources":
        if st.session_state.resources_data is None:
            st.session_state.resources_data = df
        else:
            st.session_state.resources_data = pd.concat(
                [st.session_state.resources_data, df], ignore_index=True
            )
        st.session_state.loaded_files_info[file_id] = {
            "type": "resources",
            "rows": len(df),
            "columns": list(df.columns),
        }
    elif data_type == "technique":
        if st.session_state.technique_data is None:
            st.session_state.technique_data = df
        else:
            st.session_state.technique_data = pd.concat(
                [st.session_state.technique_data, df], ignore_index=True
            )
        st.session_state.loaded_files_info[file_id] = {
            "type": "technique",
            "rows": len(df),
            "columns": list(df.columns),
        }
    elif data_type == "debit_credit":
        if st.session_state.debit_credit_data is None:
            st.session_state.debit_credit_data = df
        else:
            st.session_state.debit_credit_data = pd.concat(
                [st.session_state.debit_credit_data, df], ignore_index=True
            )
        st.session_state.loaded_files_info[file_id] = {
            "type": "debit_credit",
            "rows": len(df),
            "columns": list(df.columns),
        }
    elif data_type == "tessa_tasks":
        if st.session_state.tessa_tasks_data is None:
            st.session_state.tessa_tasks_data = df
        else:
            st.session_state.tessa_tasks_data = pd.concat(
                [st.session_state.tessa_tasks_data, df], ignore_index=True
            )
        st.session_state.loaded_files_info[file_id] = {
            "type": "tessa_tasks",
            "rows": len(df),
            "columns": list(df.columns),
        }


def remove_file_from_session(file_name: str) -> None:
    """Удаляет один файл из loaded_files_info и обнуляет соответствующий тип данных."""
    if file_name not in st.session_state.loaded_files_info:
        return
    file_info = st.session_state.loaded_files_info[file_name]
    file_type = file_info["type"]
    if file_type == "project":
        st.session_state.project_data = None
    elif file_type == "resources":
        st.session_state.resources_data = None
    elif file_type == "technique":
        st.session_state.technique_data = None
    elif file_type == "debit_credit":
        st.session_state.debit_credit_data = None
    elif file_type == "tessa_tasks":
        st.session_state.tessa_tasks_data = None
    del st.session_state.loaded_files_info[file_name]


def clear_all_data_for_removed_files(files_to_remove: list) -> None:
    """Удаляет из сессии все файлы из списка; при непустом списке сбрасывает все данные и loaded_files_info."""
    for file_name in files_to_remove:
        remove_file_from_session(file_name)
    if files_to_remove:
        st.session_state.project_data = None
        st.session_state.resources_data = None
        st.session_state.technique_data = None
        st.session_state.debit_credit_data = None
        st.session_state.tessa_tasks_data = None
        st.session_state.loaded_files_info = {}
        st.session_state["project_data_all_snapshots"] = None


def get_main_df() -> Optional[pd.DataFrame]:
    """Возвращает основной DataFrame для отчётов (project_data)."""
    return st.session_state.get("project_data", None)
