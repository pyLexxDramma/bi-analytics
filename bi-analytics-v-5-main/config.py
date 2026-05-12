"""
Общая конфигурация приложения BI Analytics.
Единый источник для путей, констант и при необходимости переменных окружения.
"""
import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional

try:
    from dotenv import load_dotenv as _load_dotenv
except ImportError:  # pragma: no cover
    _load_dotenv = None  # type: ignore[misc, assignment]


def _apply_simple_env_file(path: Path, *, override: bool) -> None:
    """Минимальная подстановка KEY=VALUE из .env без пакета python-dotenv."""
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if override or key not in os.environ:
            os.environ[key] = val


_APP_DIR = Path(__file__).resolve().parent
_parent_env = _APP_DIR.parent / ".env"
_local_env = _APP_DIR / ".env"
if _load_dotenv is not None:
    # Родительский .env (корень репо рядом с корневым streamlit_app.py), затем каталог приложения — второй перекрывает ключи.
    if _parent_env.is_file():
        _load_dotenv(_parent_env, override=False)
    _load_dotenv(_local_env, override=True)
else:
    _apply_simple_env_file(_parent_env, override=False)
    _apply_simple_env_file(_local_env, override=True)


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


def _read_env_or_secret(name: str) -> str:
    """Значение переменной из ``os.environ`` или (fallback) из ``st.secrets``.

    На Streamlit Cloud переменные верхнего уровня ``secrets.toml`` копируются
    в ``os.environ`` только после первого обращения к ``st.secrets`` (lazy
    load). До этого момента ``os.environ.get("BI_ANALYTICS_RELEASE_MODE")``
    возвращает пустую строку — даже если в secrets написано ``= "1"``.
    Из-за этого ``is_release_client_mode()`` возвращал False на release →
    был виден тумблер «Подмешивать демо-данные» и в БД попадали sample_*.

    Здесь сначала читаем env (быстро, без импорта streamlit при cold-start),
    а если пусто — пытаемся прочитать ``st.secrets[name]`` (что заодно
    тригерит lazy-load и заполняет os.environ для последующих вызовов).
    """
    val = os.environ.get(name, "")
    if val:
        return str(val).strip()
    try:
        import streamlit as st  # type: ignore
        # st.secrets — Mapping; .get() безопасен при отсутствии ключа.
        v = st.secrets.get(name, None) if hasattr(st, "secrets") else None
    except Exception:
        v = None
    return str(v).strip() if v is not None else ""


def _env_truthy(name: str) -> bool:
    return _read_env_or_secret(name).lower() in ("1", "true", "yes", "on")


def _env_falsy(name: str) -> bool:
    return _read_env_or_secret(name).lower() in ("0", "false", "no", "off")


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


def get_ai_assistant_open_url() -> str:
    """
    URL страницы **XCA AI** (чат), открываемый из BI в **новой вкладке** браузера.

    Задаётся отдельно от SSH-переменных сервиса ``opencode_web``: те нужны только
    процессу чата (см. ``opencode_web/AI_INTEGRATION_GUIDE.md``), а здесь —
    публичный ``https://…`` (или ``http://`` в LAN), по которому пользователь
    реально открывает UI чата.

    Приоритет ключей (первый непустой): ``AI_ASSISTANT_URL``, ``XCA_AI_CHAT_URL``,
    ``AI_CHAT_PUBLIC_URL``.
    """
    for key in ("AI_ASSISTANT_URL", "XCA_AI_CHAT_URL", "AI_CHAT_PUBLIC_URL"):
        u = _read_env_or_secret(key).strip()
        if u:
            return u
    return ""


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
