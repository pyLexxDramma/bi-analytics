"""
Общая конфигурация приложения BI Analytics.
Единый источник для путей, констант и при необходимости переменных окружения.
"""
import os
import subprocess
from functools import lru_cache
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


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _env_falsy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("0", "false", "no", "off")


@lru_cache(maxsize=1)
def _git_current_branch() -> str:
    """Текущая git-ветка приложения. Кешируется на процесс. На сервере без git вернёт ''."""
    try:
        br = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(BASE_PATH),
            capture_output=True,
            text=True,
            timeout=1.5,
        )
        return (br.stdout or "").strip().lower()
    except Exception:
        return ""


def is_release_client_mode() -> bool:
    """
    Единый предикат «клиентского релиза».

    True, если выполнено ЛЮБОЕ из:

    - ``BI_ANALYTICS_HIDE_DEV_DIAGNOSTICS=1`` — явный флаг для деплоя на хостинге без git
      (Streamlit Cloud, Docker, systemd unit). Рекомендуется для production.
    - ``BI_ANALYTICS_RELEASE_MODE=1`` — синоним явного флага.
    - текущая git-ветка приложения = ``release`` — чтобы при работе из этой ветки локально
      поведение совпадало с production.

    Используется:
    - ``project_visualization_app.py`` — скрытие dev-диагностики в UI.
    - ``ignore_demo_data_files()`` — автоматически включает игнор sample_*/new_csv/.
    """
    if _env_truthy("BI_ANALYTICS_HIDE_DEV_DIAGNOSTICS"):
        return True
    if _env_truthy("BI_ANALYTICS_RELEASE_MODE"):
        return True
    return _git_current_branch() == "release"


def is_dev_branch() -> bool:
    """Текущая git-ветка = ``dev`` (или содержит «dev» в начале/как префикс)."""
    br = _git_current_branch()
    return br == "dev" or br.startswith("dev/") or br.startswith("dev-")


def ignore_demo_data_files() -> bool:
    """
    Не подмешивать демо: каталог ``new_csv/`` рядом с приложением,
    ``sample_*.csv`` и любые файлы в каталогах ``new_csv/`` внутри ``web/`` и доп. путей.

    Приоритет источников решения (сверху → вниз, первый сработавший побеждает):

    1. ``release``-режим (см. :func:`is_release_client_mode`) — на release демо
       **всегда отключены**, никакие сессионные/env-переключатели не возвращают их.
       Это аппаратное правило безопасности для клиентского деплоя.
    2. Сессионный admin-тумблер ``st.session_state["_admin_demo_pref"]`` — действует
       только в dev, ставится из сайдбара (`auth.render_sidebar_menu`):
       - ``"include"`` → демо подмешиваются (вернёт ``False``);
       - ``"ignore"``  → демо игнорируются (вернёт ``True``).
    3. ``BI_ANALYTICS_INCLUDE_DEMO=1`` (env) → ``False`` (явное включение демо
       для текущего процесса, например для UI-демонстрации).
    4. ``BI_ANALYTICS_IGNORE_DEMO=1`` (env) → ``True``.
    5. **Дефолт**: ``True`` — демо игнорируются. Это «безопасный по умолчанию»
       подход: разработчик видит данные так же, как клиент на release; чтобы
       подмешать демо, admin явно включает тумблер в сайдбаре или задаётся
       ``BI_ANALYTICS_INCLUDE_DEMO=1``.
    """
    if is_release_client_mode():
        return True
    try:
        import streamlit as st  # type: ignore

        pref = str(st.session_state.get("_admin_demo_pref", "") or "").strip().lower()
        if pref == "ignore":
            return True
        if pref == "include":
            return False
    except Exception:
        pass
    if _env_truthy("BI_ANALYTICS_INCLUDE_DEMO"):
        return False
    if _env_truthy("BI_ANALYTICS_IGNORE_DEMO"):
        return True
    return True


def web_load_latest_snapshots_only() -> bool:
    """
    При загрузке из ``web/``: оставлять только последний снимок по дате в имени файла
    (1С, TESSA, MSP, выгрузки с датой в названии), чтобы не раздувать SQLite и память.

    По умолчанию включено (не задано или ``1``/``true``/``yes``/``on``).
    Полная история всех файлов: ``BI_ANALYTICS_WEB_LATEST_ONLY=0`` (или ``false``/``no``/``off``).
    """
    v = os.environ.get("BI_ANALYTICS_WEB_LATEST_ONLY", "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "yes", "on"):
        return True
    return True


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
