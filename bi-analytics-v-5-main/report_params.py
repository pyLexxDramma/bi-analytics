"""
Модуль для работы с параметрами отчетов, редактируемыми аналитиком
"""
import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, List

from config import DB_PATH

# Единый источник списка отчётов — dashboards.REPORT_CATEGORIES
try:
    from dashboards import get_all_report_names
    AVAILABLE_REPORTS = get_all_report_names()
except ImportError:
    AVAILABLE_REPORTS = [
        "Динамика отклонений",
        "Отклонение текущего срока от базового плана",
        "Значения отклонений от базового плана",
        "БДДС",
        "БДР",
        "Бюджет план/факт",
        "Утвержденный бюджет",
        "Прогнозный бюджет",
        "Выдача рабочей/проектной документации",
        "График движения рабочей силы",
        "Исполнительная документация",
    ]

# Типы параметров
PARAMETER_TYPES = {
    'string': 'Текст',
    'number': 'Число',
    'date': 'Дата',
    'select': 'Выбор из списка',
    'task_select': 'Выбор задачи',
    'boolean': 'Да/Нет'
}

# Предопределенные параметры для отчетов
PREDEFINED_PARAMETERS = {
    "Прогнозный бюджет": [
        {
            'key': 'selected_task_for_forecast',
            'name': 'Задача для расчета план-факта окончания проекта',
            'type': 'task_select',
            'description': 'Выберите задачу, которая будет использоваться для расчета прогноза окончания проекта',
            'editable': True
        },
        {
            'key': 'budget_adjustment',
            'name': 'Корректировка плана бюджета',
            'type': 'number',
            'description': 'Внесите корректировку в план бюджета (в рублях)',
            'editable': True
        },
        {
            'key': 'schedule_adjustment_days',
            'name': 'Корректировка графика проекта (дни)',
            'type': 'number',
            'description': 'Внесите корректировку в график проекта (положительное значение - сдвиг вперед, отрицательное - назад)',
            'editable': True
        }
    ],
    "Отклонение от базового плана": [
        {
            'key': 'selected_task_for_plan_fact',
            'name': 'Задача для расчета план-факта',
            'type': 'task_select',
            'description': 'Выберите задачу для расчета план-факта окончания проекта',
            'editable': True
        }
    ]
}

# Обратная совместимость со старым названием отчёта в БД/настройках
PREDEFINED_PARAMETERS["Отклонение текущего срока от базового плана"] = PREDEFINED_PARAMETERS[
    "Отклонение от базового плана"
]


def get_report_parameter(report_name: str, parameter_key: str) -> Optional[Dict]:
    """
    Получение параметра отчета

    Args:
        report_name: Название отчета
        parameter_key: Ключ параметра

    Returns:
        Словарь с информацией о параметре или None
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT parameter_value, parameter_type, description, is_editable_by_analyst, updated_at, updated_by
        FROM report_parameters
        WHERE report_name = ? AND parameter_key = ?
    ''', (report_name, parameter_key))

    result = cursor.fetchone()
    conn.close()

    if result:
        value, param_type, description, editable, updated_at, updated_by = result

        # Преобразуем значение в зависимости от типа
        if param_type == 'number':
            try:
                parsed_value = float(value) if value else None
            except:
                parsed_value = value
        elif param_type == 'boolean':
            parsed_value = value.lower() == 'true' if value else False
        elif param_type in ['select', 'task_select']:
            try:
                parsed_value = json.loads(value) if value else None
            except:
                parsed_value = value
        else:
            parsed_value = value

        return {
            'value': parsed_value,
            'type': param_type,
            'description': description,
            'editable': bool(editable),
            'updated_at': updated_at,
            'updated_by': updated_by
        }

    return None


def get_all_report_parameters(report_name: str) -> Dict[str, Dict]:
    """
    Получение всех параметров отчета

    Args:
        report_name: Название отчета

    Returns:
        Словарь параметров {parameter_key: parameter_info}
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT parameter_key, parameter_value, parameter_type, description, is_editable_by_analyst, updated_at, updated_by
        FROM report_parameters
        WHERE report_name = ?
        ORDER BY parameter_key
    ''', (report_name,))

    parameters = {}
    for row in cursor.fetchall():
        key, value, param_type, description, editable, updated_at, updated_by = row

        # Преобразуем значение
        if param_type == 'number':
            try:
                parsed_value = float(value) if value else None
            except:
                parsed_value = value
        elif param_type == 'boolean':
            parsed_value = value.lower() == 'true' if value else False
        elif param_type in ['select', 'task_select']:
            try:
                parsed_value = json.loads(value) if value else None
            except:
                parsed_value = value
        else:
            parsed_value = value

        parameters[key] = {
            'value': parsed_value,
            'type': param_type,
            'description': description,
            'editable': bool(editable),
            'updated_at': updated_at,
            'updated_by': updated_by
        }

    conn.close()
    return parameters


def set_report_parameter(report_name: str, parameter_key: str, parameter_value: any,
                        parameter_type: str = 'string', description: Optional[str] = None,
                        is_editable: bool = True, updated_by: Optional[str] = None) -> bool:
    """
    Установка параметра отчета

    Args:
        report_name: Название отчета
        parameter_key: Ключ параметра
        parameter_value: Значение параметра
        parameter_type: Тип параметра
        description: Описание параметра
        is_editable: Можно ли редактировать аналитику
        updated_by: Пользователь, который обновил

    Returns:
        True если успешно
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Преобразуем значение в строку для хранения
        if isinstance(parameter_value, (list, dict)):
            value_str = json.dumps(parameter_value, ensure_ascii=False)
        elif isinstance(parameter_value, bool):
            value_str = 'true' if parameter_value else 'false'
        else:
            value_str = str(parameter_value) if parameter_value is not None else None

        # Проверяем, существует ли параметр
        cursor.execute('''
            SELECT id FROM report_parameters
            WHERE report_name = ? AND parameter_key = ?
        ''', (report_name, parameter_key))

        exists = cursor.fetchone()

        if exists:
            # Обновляем существующий параметр
            cursor.execute('''
                UPDATE report_parameters
                SET parameter_value = ?, parameter_type = ?, description = ?,
                    is_editable_by_analyst = ?, updated_at = ?, updated_by = ?
                WHERE report_name = ? AND parameter_key = ?
            ''', (value_str, parameter_type, description, 1 if is_editable else 0,
                  datetime.now(), updated_by, report_name, parameter_key))
        else:
            # Создаем новый параметр
            cursor.execute('''
                INSERT INTO report_parameters (report_name, parameter_key, parameter_value,
                    parameter_type, description, is_editable_by_analyst, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (report_name, parameter_key, value_str, parameter_type, description,
                  1 if is_editable else 0, updated_by))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка при установке параметра: {e}")
        return False


def delete_report_parameter(report_name: str, parameter_key: str) -> bool:
    """Удаление параметра отчета"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM report_parameters
            WHERE report_name = ? AND parameter_key = ?
        ''', (report_name, parameter_key))

        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def initialize_predefined_parameters():
    """Инициализация предопределенных параметров для отчетов"""
    for report_name, parameters in PREDEFINED_PARAMETERS.items():
        for param_def in parameters:
            # Проверяем, существует ли уже параметр
            existing = get_report_parameter(report_name, param_def['key'])
            if not existing:
                set_report_parameter(
                    report_name=report_name,
                    parameter_key=param_def['key'],
                    parameter_value=None,
                    parameter_type=param_def['type'],
                    description=param_def.get('description', ''),
                    is_editable=param_def.get('editable', True),
                    updated_by='system'
                )
