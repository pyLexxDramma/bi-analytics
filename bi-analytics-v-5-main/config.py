"""
Общая конфигурация приложения BI Analytics.
Единый источник для путей, констант и при необходимости переменных окружения.
"""
import os
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional


def switch_page_app(path: str) -> None:
    """
    Переход на страницу multipage. ``path`` — как в ``st.switch_page``, относительно
    каталога **главного скрипта** Streamlit.

    - Запуск ``bi-analytics-v-5-main/project_visualization_app.py`` — страницы во
      вложенном приложении, путь ``pages/admin.py`` валиден.

    - Запуск ``streamlit_app.py`` из корня репозитория: Streamlit регистрирует только
      ``<корень>/pages/*.py``. Рядом с ``streamlit_app.py`` добавлены прокси-файлы,
      делегирующие во ``bi-analytics-v-5-main/pages/`` (см. корневой каталог ``pages/``).
    """
    import streamlit as st

    path = path.replace("\\", "/").lstrip("/")
    st.switch_page(path)

# Пути
BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
BASE_PATH: Path = Path(BASE_DIR).resolve()


def get_analytics_sibling_web_dir() -> Optional[Path]:
    """
    Каталог данных «Analitics/web»: на уровень выше вложенного репозитория.

    Если приложение лежит в ``.../Analitics/bi-analytics-v-5-main/bi-analytics-v-5-main/``,
    возвращает ``.../Analitics/web``, если эта папка существует.

    Так можно хранить большие выгрузки вне Git рядом с проектом и подгружать их вместе с локальным ``web/``.
    """
    try:
        cand = BASE_PATH.parent.parent / "web"
        if cand.is_dir():
            return cand
    except (OSError, ValueError):
        pass
    return None


def get_extra_web_dirs_from_env() -> List[Path]:
    """
    Дополнительные корни для CSV/JSON (разделители ``;`` или ``,``).

    Переменная окружения: ``BI_ANALYTICS_WEB_EXTRA_PATHS``.
    Относительные пути разрешаются от текущего рабочего каталога процесса.
    """
    raw = os.environ.get("BI_ANALYTICS_WEB_EXTRA_PATHS", "").strip()
    if not raw:
        return []
    out: List[Path] = []
    seen: set = set()
    for part in raw.replace(";", ",").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            path = Path(p).expanduser()
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            else:
                path = path.resolve()
            if path.is_dir():
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    out.append(path)
        except (OSError, ValueError):
            continue
    return out
DB_PATH: str = os.path.join(BASE_DIR, "users.db")
ETL_DB_ENGINE: str = os.environ.get("DB_ENGINE", "sqlite").strip().lower()
ETL_SQLITE_DB_PATH: str = os.environ.get(
    "SQLITE_DB_PATH",
    os.path.join(BASE_DIR, "data", "etl.db"),
)
DATA_MODE: str = os.environ.get("DATA_MODE", "auto").strip().lower()

# Подписи «project name», которые не показываем в фильтрах (дубликаты/устаревшие метки без строк в данных).
MSP_PROJECT_FILTER_EXCLUDE_NAMES: FrozenSet[str] = frozenset({"Дмитровский-1"})

MSP_PROJECT_NAME_MAP: Dict[str, str] = {
    "dmitrovsky1": "Дмитровский 1",
    "dmitrovsky": "Дмитровский",
    # 1С и смежные выгрузки: «Дмитровский-1», лат. I вместо 1
    "дмитровский-1": "Дмитровский 1",
    "дмитровскийi": "Дмитровский 1",
    "esipovo5": "Есипово V",
    "esipovo": "Есипово",
    "leninsky": "Ленинский",
    "leninsky1": "Ленинский",
    "koledino": "Коледино",
    "дмитровский1": "Дмитровский 1",
    "дмитровский": "Дмитровский",
    "есипово5": "Есипово V",
    "есипово": "Есипово",
    "ленинский": "Ленинский",
}

# Русские названия месяцев (для графиков и отчётов)
RUSSIAN_MONTHS: Dict[int, str] = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}
