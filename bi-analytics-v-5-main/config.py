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
      вложенном приложении, путь ``pages/_admin.py`` / ``pages/_analyst_params.py`` валиден.

    - Запуск ``streamlit_app.py`` из корня репозитория: Streamlit регистрирует только
      ``<корень>/pages/*.py``. Рядом с ``streamlit_app.py`` добавлены прокси-файлы,
      делегирующие во ``bi-analytics-v-5-main/pages/`` (см. корневой каталог ``pages/``).
    """
    import streamlit as st
    from streamlit.errors import StreamlitAPIException

    normalized = path.replace("\\", "/").lstrip("/")
    candidates: list[str] = [normalized]

    # Streamlit Cloud / обертка через streamlit_app.py:
    # страница дашбордов может быть зарегистрирована под корневым файлом.
    if normalized.endswith("project_visualization_app.py"):
        candidates.append("streamlit_app.py")

    # Для совместимости добавляем вариант по basename для страниц из папки pages/.
    if "/" in normalized:
        candidates.append(normalized.split("/")[-1])

    tried: set[str] = set()
    last_err: Exception | None = None
    for cand in candidates:
        if not cand or cand in tried:
            continue
        tried.add(cand)
        try:
            st.switch_page(cand)
            return
        except StreamlitAPIException as e:
            last_err = e
            continue

    if last_err is not None:
        raise last_err

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


def ignore_demo_data_files() -> bool:
    """
    Прод/сервер: ``BI_ANALYTICS_IGNORE_DEMO=1`` (или ``true``/``yes``/``on``) —
    не подмешивать демо из ``new_csv/`` рядом с приложением и не учитывать
    ``sample_*.csv`` и файлы в каталогах ``new_csv/`` внутри ``web/`` и доп. путей.
    """
    v = os.environ.get("BI_ANALYTICS_IGNORE_DEMO", "").strip().lower()
    return v in ("1", "true", "yes", "on")


DB_PATH: str = os.path.join(BASE_DIR, "users.db")
ETL_DB_ENGINE: str = os.environ.get("DB_ENGINE", "sqlite").strip().lower()
ETL_SQLITE_DB_PATH: str = os.environ.get(
    "SQLITE_DB_PATH",
    os.path.join(BASE_DIR, "data", "etl.db"),
)
DATA_MODE: str = os.environ.get("DATA_MODE", "auto").strip().lower()

# Точные подписи «project name», которые не показываем в фильтрах (устаревший дубликат написания).
# Важно: сравнение по строке, не по norm-key — иначе скрывались бы и «Дмитровский 1», если в исключении «Дмитровский-1».
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
    # Короткие коды из шапок MSP-выгрузок (колонка «project name» у корневой задачи).
    # Без этого маппинга в фильтре «Проект (ур. 1)» появляются D1/E5/Л1 вместо
    # нормальных русских названий.
    "d1": "Дмитровский 1",
    "е1": "Дмитровский 1",
    "e1": "Дмитровский 1",
    "e5": "Есипово V",
    "е5": "Есипово V",
    "л1": "Ленинский",
    "l1": "Ленинский",
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
