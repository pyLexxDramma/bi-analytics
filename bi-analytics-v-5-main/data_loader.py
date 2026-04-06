"""
Загрузка данных из CSV/Excel и обновление session state.
Вся логика «прочитать файл и положить в сессию» — только здесь.
"""
import csv
from typing import Optional

import pandas as pd
import streamlit as st


def detect_data_type(df: pd.DataFrame, file_name: Optional[str] = None) -> str:
    """Определение типа данных по структуре колонок и имени файла."""
    columns = [str(col).lower() for col in df.columns]
    file_name_lower = str(file_name).lower() if file_name else ""

    # Данные проекта: задача, план дат, бюджет
    if (
        any(col in columns for col in ["задача", "task name"])
        and any(col in columns for col in ["старт план", "plan start"])
        and any(col in columns for col in ["бюджет план", "budget plan"])
    ):
        return "project"

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


def load_data(uploaded_file, file_name: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    Загрузка данных из загруженного файла (CSV/Excel).
    Возвращает DataFrame с attrs: data_type, file_name; при ошибке — None.
    """
    try:
        original_name = file_name if file_name else uploaded_file.name
        if uploaded_file.name.endswith(".csv"):
            encodings = ["utf-8", "utf-8-sig", "windows-1251", "cp1251"]
            df = None
            for encoding in encodings:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(
                        uploaded_file,
                        sep=";",
                        encoding=encoding,
                        quoting=csv.QUOTE_MINIMAL,
                        quotechar='"',
                        doublequote=True,
                        decimal=",",  # европейский формат: 84615,38462
                    )
                    break
                except (UnicodeDecodeError, pd.errors.ParserError):
                    try:
                        uploaded_file.seek(0)
                        df = pd.read_csv(
                            uploaded_file,
                            sep=",",
                            encoding=encoding,
                            quoting=csv.QUOTE_MINIMAL,
                            quotechar='"',
                            doublequote=True,
                            decimal=",",
                        )
                        break
                    except (UnicodeDecodeError, pd.errors.ParserError):
                        continue
            if df is None:
                uploaded_file.seek(0)
                try:
                    df = pd.read_csv(uploaded_file, encoding="utf-8")
                except Exception:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file)
        elif uploaded_file.name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(uploaded_file)
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
    if "previous_uploaded_files" not in st.session_state:
        st.session_state.previous_uploaded_files = []


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
        st.session_state.loaded_files_info = {}


def get_main_df() -> Optional[pd.DataFrame]:
    """Возвращает основной DataFrame для отчётов (project_data)."""
    return st.session_state.get("project_data", None)
