import os
import re
import sqlite3
import time
import uuid
import json
import html
import atexit
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import streamlit as st
from sshtunnel import SSHTunnelForwarder

_WEB_DIR = Path(__file__).resolve().parent


def _bootstrap_opencode_dotenv() -> None:
    """Загрузка ``opencode_web/.env``; без пакета ``python-dotenv`` — простой разбор KEY=VALUE."""
    env_path = _WEB_DIR / ".env"
    try:
        from dotenv import load_dotenv  # type: ignore[import-untyped]

        load_dotenv(dotenv_path=env_path, override=True)
        return
    except ImportError:
        pass
    if not env_path.is_file():
        return
    try:
        text = env_path.read_text(encoding="utf-8-sig")
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
        os.environ[key] = val


_bootstrap_opencode_dotenv()

DEFAULT_OPENCODE_URL = os.getenv("OPENCODE_URL", "http://opencode:4096").rstrip("/")
WEB_AUTH_TOKEN = os.getenv("WEB_AUTH_TOKEN", "").strip()
REQUEST_TIMEOUT_SECONDS = 120
MAX_MESSAGE_LENGTH = 4000
ASYNC_TOTAL_TIMEOUT_SECONDS = 600
POLL_INTERVAL_SECONDS = 0.6
POLL_REQUEST_TIMEOUT_SECONDS = 8
QUESTION_REPLY_TIMEOUT_SECONDS = 2.5
SSE_CONNECT_TIMEOUT_SECONDS = 2.5
SSE_READ_TIMEOUT_SECONDS = 2.5
SSE_MAX_EVENTS_PER_TICK = 40
SSE_EVENT_PATHS = ("/global/event", "/event")
ANALYTICS_OUTPUT_DIR = Path("/workspace/analytics/output")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
DEFAULT_DB_PATH = "/workspace/analytics/sessions.db" if Path("/workspace").exists() else "workspace/analytics/sessions.db"
SESSIONS_DB_PATH = Path(os.getenv("SESSIONS_DB_PATH", DEFAULT_DB_PATH))
RULES_MD_PATH = Path(os.getenv("AI_ASSISTANT_RULES_PATH", "/workspace/AI_ASSISTANT_RULES.md"))
ENABLE_SSH_TUNNEL = str(os.getenv("ENABLE_SSH_TUNNEL", "false")).strip().lower() in {"1", "true", "yes", "on"}
AI_SSH_HOST = os.getenv("AI_SSH_HOST", "").strip()
AI_SSH_PORT = int(os.getenv("AI_SSH_PORT", "22"))
AI_SSH_USER = os.getenv("AI_SSH_USER", "").strip()
AI_SSH_PASSWORD = os.getenv("AI_SSH_PASSWORD", "").strip()
AI_OPENCODE_REMOTE_PORT = int(os.getenv("AI_OPENCODE_REMOTE_PORT", "4096"))
AI_LOCAL_TUNNEL_PORT = int(os.getenv("AI_LOCAL_TUNNEL_PORT", "0"))
APP_LOGO_PATH = Path(__file__).resolve().parent / "logo.svg"

XCA_THEME_CSS = """
<style>
:root {
  --xca-bg: #1a1a1a;
  --xca-surface: #202020;
  --xca-surface-soft: #2a2a2a;
  --xca-border: #666666;
  --xca-text: #f2f2f2;
  --xca-muted: #bdbdbd;
}
.stApp {
  background: linear-gradient(180deg, var(--xca-bg) 0%, #141414 100%);
  color: var(--xca-text);
}
[data-testid="stSidebar"] {
  background: var(--xca-surface);
  border-right: 1px solid var(--xca-border);
}
div.stButton > button {
  background: var(--xca-surface-soft);
  color: var(--xca-text);
  border: 1px solid var(--xca-border);
}
div.stButton > button:hover {
  border-color: #e0e0e0;
}
</style>
""".strip()


def apply_xca_theme() -> None:
    st.markdown(XCA_THEME_CSS, unsafe_allow_html=True)


def render_xca_branding(title: str) -> None:
    if APP_LOGO_PATH.exists():
        st.image(str(APP_LOGO_PATH), width=88)
    st.title(title)


def render_back_to_main_menu_button(on_back_requested: Any | None) -> None:
    """
    Отрисовывает кнопку возврата в главное меню и обрабатывает переход.

    Разработчику достаточно передать callback в `main(on_back_requested=...)`.
    При клике вызывается callback, затем выполняется `st.rerun()`, чтобы
    экран чата сразу сменился на главное меню.
    """
    if on_back_requested is None:
        return
    if st.button("Назад", key="ai_chat_back_to_menu"):
        on_back_requested()
        st.rerun()


KNOWLEDGE_HINT = """
[INTERNAL-KNOWLEDGE-FOR-AGENT]
Рабочая директория: /workspace
Анализ данных: используй /workspace/AI_AGENT_GUIDE.md и /workspace/analytics/KNOWLEDGE_BASE.md.
Единственный источник данных для аналитики: /workspace/web_data.db (или /workspace/data/web_data.db).
Запрещено использовать CSV как первичный источник аналитики.
Для быстрых ответов сначала используй /workspace/analytics/analyze_db_fast_answers.py.
Для детализации используй профильные DB-скрипты analyze_db_*.py из /workspace/analytics.
Сначала запускай релевантный DB-скрипт в /workspace/analytics, затем давай только итог.
Если нужна сверка состава данных/ключей — используй /workspace/analytics/inspect_web_db.py.
Для запросов про отклонения обязательно сначала используй /workspace/analytics/analyze_db_deviations_for_chat.py.
Перед ответом по отклонениям всегда пересоздавай свежие output-файлы этим скриптом.
Не использовать устаревшие файлы из /workspace/analytics/output/esipovo_deviations* и подобные legacy-отчеты.
При расхождениях с сайтом опирайся на активную версию в web_versions (is_active=1) и срезы, близкие к логике дашборда.
Никогда не говори "данных нет", пока не проверил web_data.db и не запустил DB-скрипт.
Не выводи пользователю промежуточные действия ("проверяю", "сначала изучу", "запускаю"). Пиши только финальный результат.
Если нужен график — сохрани PNG в /workspace/analytics/output и укажи абсолютный путь.
[/INTERNAL-KNOWLEDGE-FOR-AGENT]
""".strip()

BASE_PERSONA_HINT = """
[INTERNAL-ROLE]
Ты бизнес-ассистент для руководителей проектов.
Отвечай простым деловым языком, без фокуса на программирование.
Всегда пиши и рассуждай на русском языке.
Соблюдай UTF-8 кодировку, не допускай нечитаемые последовательности вида "Ð..." или "Ñ...".
В финальном ответе не показывай цепочку рассуждений, промежуточные шаги и внутренние инструкции.
Пиши только итоговый ответ для пользователя: структурированно, конкретно и по делу.
Мысли (для внутреннего потока) формулируй только на русском языке.
В финальном ответе не упоминай скрипты, команды, инструменты, внутренние пути файлов и технические шаги выполнения.
Вопрос "что ты можешь?" трактуй как возможности аналитики по данным из web_data.db и отчетам в /workspace/analytics/output.
Не обещай внешний поиск, рынок, конкурентов или веб-исследования, если это не запрошено явно.
[/INTERNAL-ROLE]
""".strip()


def add_connection_log(event: str, details: str = "") -> None:
    if "connection_logs" not in st.session_state:
        st.session_state.connection_logs = []
    ts = time.strftime("%H:%M:%S", time.localtime())
    line = f"[{ts}] {event}"
    if details:
        line = f"{line} | {details}"
    logs: list[str] = st.session_state.connection_logs
    logs.append(line)
    st.session_state.connection_logs = logs[-80:]


@st.cache_resource(show_spinner=False)
def open_ssh_tunnel() -> SSHTunnelForwarder:
    if not ENABLE_SSH_TUNNEL:
        raise RuntimeError("SSH tunnel is disabled")
    required = {
        "AI_SSH_HOST": AI_SSH_HOST,
        "AI_SSH_USER": AI_SSH_USER,
        "AI_SSH_PASSWORD": AI_SSH_PASSWORD,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Missing tunnel env vars: {', '.join(missing)}")

    add_connection_log(
        "SSH tunnel: connecting",
        f"{AI_SSH_USER}@{AI_SSH_HOST}:{int(AI_SSH_PORT)} -> 127.0.0.1:{AI_OPENCODE_REMOTE_PORT}",
    )
    # Локальный порт: 0 = выбрать свободный (на Windows фиксированный 4096 часто занят).
    _local_port = AI_LOCAL_TUNNEL_PORT if AI_LOCAL_TUNNEL_PORT > 0 else 0
    forwarder = SSHTunnelForwarder(
        ssh_address_or_host=AI_SSH_HOST,
        ssh_port=int(AI_SSH_PORT),
        ssh_username=AI_SSH_USER,
        ssh_password=AI_SSH_PASSWORD,
        ssh_config_file=None,
        ssh_proxy_enabled=False,
        allow_agent=False,
        host_pkey_directories=[],
        remote_bind_address=("127.0.0.1", AI_OPENCODE_REMOTE_PORT),
        local_bind_address=("127.0.0.1", _local_port),
    )
    try:
        forwarder.start()
    except Exception as exc:
        if "DSSKey" in str(exc):
            add_connection_log(
                "SSH dependency error",
                "Incompatible paramiko version detected. Install paramiko<4",
            )
        add_connection_log("SSH tunnel: failed", str(exc))
        raise
    add_connection_log("SSH tunnel: connected", f"local 127.0.0.1:{forwarder.local_bind_port}")
    atexit.register(forwarder.stop)
    return forwarder


def get_runtime_opencode_url() -> str:
    if not ENABLE_SSH_TUNNEL:
        return DEFAULT_OPENCODE_URL
    tunnel = open_ssh_tunnel()
    return f"http://127.0.0.1:{tunnel.local_bind_port}"


def init_state() -> None:
    if "sessions" not in st.session_state:
        st.session_state.sessions = []
    if "active_session_local_id" not in st.session_state:
        st.session_state.active_session_local_id = None
    if "opencode_health_ok" not in st.session_state:
        st.session_state.opencode_health_ok = False
    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = WEB_AUTH_TOKEN == ""
    if "auth_input" not in st.session_state:
        st.session_state.auth_input = ""
    if "error_message" not in st.session_state:
        st.session_state.error_message = ""
    if "pending_request" not in st.session_state:
        st.session_state.pending_request = None
    if "pending_opencode_question" not in st.session_state:
        st.session_state.pending_opencode_question = None
    if "dismissed_question_ids" not in st.session_state:
        st.session_state.dismissed_question_ids = set()
    if "last_selected_clarification" not in st.session_state:
        st.session_state.last_selected_clarification = ""
    if "selected_question_option" not in st.session_state:
        st.session_state.selected_question_option = ""
    if "awaiting_images" not in st.session_state:
        st.session_state.awaiting_images = {}
    if "pending_question_reply" not in st.session_state:
        st.session_state.pending_question_reply = None
    if "data_hint_sent_sessions" not in st.session_state:
        st.session_state.data_hint_sent_sessions = {}
    if "assistant_rules_text" not in st.session_state:
        st.session_state.assistant_rules_text = ""
    if "sessions_loaded_from_db" not in st.session_state:
        st.session_state.sessions_loaded_from_db = False
    if not st.session_state.sessions_loaded_from_db:
        init_sessions_db()
        load_sessions_from_db()
        st.session_state.sessions_loaded_from_db = True
    if not st.session_state.assistant_rules_text:
        st.session_state.assistant_rules_text = load_assistant_rules_text()
    if "runtime_opencode_url" not in st.session_state:
        st.session_state.runtime_opencode_url = ""
    if "connection_logs" not in st.session_state:
        st.session_state.connection_logs = []
    # Повторная попытка разрешения backend URL (SSH): не чаще раз в N секунд, если URL ещё пустой.
    _resolve_interval_s = 10.0
    _last_try = float(st.session_state.get("_opencode_url_resolve_last_ts", 0.0))
    _should_try = (not st.session_state.runtime_opencode_url) or bool(
        st.session_state.get("_force_opencode_url_resolve", False)
    )
    if _should_try and (time.time() - _last_try >= _resolve_interval_s or st.session_state.get("_force_opencode_url_resolve")):
        st.session_state._opencode_url_resolve_last_ts = time.time()
        st.session_state._force_opencode_url_resolve = False
        try:
            st.session_state.runtime_opencode_url = get_runtime_opencode_url()
            add_connection_log("Backend URL resolved", st.session_state.runtime_opencode_url)
        except Exception as exc:
            st.session_state.runtime_opencode_url = ""
            add_connection_log("Backend URL resolve failed", str(exc))
            st.session_state.error_message = f"Ошибка SSH-туннеля: {exc}"


def load_assistant_rules_text() -> str:
    try:
        if RULES_MD_PATH.exists() and RULES_MD_PATH.is_file():
            return RULES_MD_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return ""


def init_sessions_db() -> None:
    SESSIONS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(SESSIONS_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                local_id TEXT PRIMARY KEY,
                server_session_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                messages_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )


def load_sessions_from_db() -> None:
    if not SESSIONS_DB_PATH.exists():
        return
    with sqlite3.connect(SESSIONS_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT local_id, server_session_id, title, created_at, messages_json
            FROM sessions
            ORDER BY created_at DESC
            """
        ).fetchall()
        sessions: list[dict[str, Any]] = []
        for row in rows:
            try:
                messages = json.loads(row["messages_json"])
            except json.JSONDecodeError:
                messages = []
            if not isinstance(messages, list):
                messages = []
            sessions.append(
                {
                    "local_id": row["local_id"],
                    "server_session_id": row["server_session_id"],
                    "title": row["title"],
                    "created_at": int(row["created_at"]),
                    "messages": messages,
                }
            )
        st.session_state.sessions = sessions
        active_row = conn.execute("SELECT value FROM app_meta WHERE key = 'active_session_local_id'").fetchone()
        if active_row and any(s["local_id"] == active_row["value"] for s in sessions):
            st.session_state.active_session_local_id = active_row["value"]
        elif sessions:
            # В БД есть сессии, но нет валидного active в meta — выбираем последнюю по времени (первая в списке).
            st.session_state.active_session_local_id = sessions[0]["local_id"]


def persist_sessions_to_db() -> None:
    init_sessions_db()
    with sqlite3.connect(SESSIONS_DB_PATH) as conn:
        conn.execute("DELETE FROM sessions")
        for session in st.session_state.sessions:
            conn.execute(
                """
                INSERT INTO sessions (local_id, server_session_id, title, created_at, messages_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session["local_id"],
                    session["server_session_id"],
                    session["title"],
                    int(session["created_at"]),
                    json.dumps(session.get("messages", []), ensure_ascii=False),
                ),
            )
        active_id = st.session_state.active_session_local_id or ""
        conn.execute(
            """
            INSERT INTO app_meta (key, value) VALUES ('active_session_local_id', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (active_id,),
        )


def delete_session(local_id: str) -> None:
    st.session_state.sessions = [s for s in st.session_state.sessions if s["local_id"] != local_id]
    if st.session_state.active_session_local_id == local_id:
        st.session_state.active_session_local_id = st.session_state.sessions[0]["local_id"] if st.session_state.sessions else None
    persist_sessions_to_db()


def render_loading_status() -> None:
    if st.session_state.pending_question_reply:
        st.info("Обрабатываю выбранное уточнение...")
        return

    pending = st.session_state.pending_request
    if not pending:
        return

    sync_mode = bool(pending.get("sync_mode", False))
    mode = str(pending.get("mode", ""))
    if mode == "submit" and sync_mode:
        st.info("Формирую ответ...")
    elif mode == "submit":
        st.info("Запускаю обработку запроса...")
    else:
        st.info("Готовлю итоговый ответ...")


def fetch_json(
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
) -> tuple[bool, int, dict[str, Any] | None, str]:
    opencode_url = str(st.session_state.get("runtime_opencode_url") or "").strip()
    if not opencode_url:
        return (
            False,
            0,
            None,
            "Backend OpenCode не готов (нет URL). Подождите повторной попытки SSH или нажмите «Сбросить подключение» в диагностике.",
        )
    url = f"{opencode_url}{path}"
    add_connection_log("HTTP request", f"{method} {url}")
    try:
        response = requests.request(
            method=method,
            url=url,
            json=payload,
            timeout=timeout_seconds or REQUEST_TIMEOUT_SECONDS,
        )
        response.encoding = "utf-8"
    except requests.RequestException as exc:
        add_connection_log("HTTP request failed", f"{method} {url} | {exc}")
        return False, 0, None, str(exc)

    text = response.text
    parsed: dict[str, Any] | None = None
    if text:
        try:
            parsed = response.json()
        except ValueError:
            parsed = None
    add_connection_log("HTTP response", f"{response.status_code} {method} {url}")
    return response.ok, response.status_code, parsed, text


def _flush_sse_event(
    result: list[dict[str, Any]],
    event_name: str,
    data_lines: list[str],
) -> None:
    if not data_lines:
        return
    raw_data = "\n".join(data_lines).strip()
    if not raw_data:
        return
    payload: Any = raw_data
    try:
        payload = json.loads(raw_data)
    except json.JSONDecodeError:
        payload = {"raw": raw_data}
    result.append({"event": event_name or "message", "payload": payload})


def render_thought_block(text: str) -> None:
    safe = html.escape(text)
    st.markdown(
        (
            "<div style='background:#2b2f36;border:1px solid #3a404a;"
            "padding:10px 12px;border-radius:8px;color:#d7dde8;white-space:pre-wrap;"
            "font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;'>"
            f"{safe}</div>"
        ),
        unsafe_allow_html=True,
    )


def format_thought_text(raw: str) -> str:
    prepared = str(raw or "").strip()
    if not prepared:
        return ""
    normalized = prepared.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    paragraphs = [re.sub(r"[ \t]+", " ", p).strip() for p in normalized.split("\n") if p.strip()]
    if not paragraphs:
        return normalized
    # Если модель отдает длинную "простыню", делаем мягкую структуризацию по предложениям.
    if len(paragraphs) == 1 and len(paragraphs[0]) > 220:
        chunks = re.split(r"(?<=[\.\!\?;])\s+", paragraphs[0])
        chunks = [chunk.strip(" -") for chunk in chunks if chunk.strip()]
        if len(chunks) > 1:
            return "\n".join(f"- {item}" for item in chunks)
    return "\n".join(paragraphs)


def _read_sse_events_once() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        opencode_url = str(st.session_state.get("runtime_opencode_url") or get_runtime_opencode_url())
    except Exception:
        return events
    for sse_path in SSE_EVENT_PATHS:
        url = f"{opencode_url}{sse_path}"
        try:
            with requests.get(
                url,
                stream=True,
                timeout=(SSE_CONNECT_TIMEOUT_SECONDS, SSE_READ_TIMEOUT_SECONDS),
                headers={"Accept": "text/event-stream"},
            ) as response:
                if response.status_code != 200:
                    continue
                response.encoding = "utf-8"
                event_name = "message"
                data_lines: list[str] = []
                for line in response.iter_lines(decode_unicode=True):
                    if line is None:
                        continue
                    if line == "":
                        _flush_sse_event(events, event_name, data_lines)
                        event_name = "message"
                        data_lines = []
                        if len(events) >= SSE_MAX_EVENTS_PER_TICK:
                            break
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip() or "message"
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line.split(":", 1)[1].lstrip())
                _flush_sse_event(events, event_name, data_lines)
                if events:
                    return events
        except requests.RequestException:
            continue
    return events


def _deep_find_first_string(payload: Any) -> str:
    if isinstance(payload, str):
        stripped = payload.strip()
        return stripped
    if isinstance(payload, list):
        for item in payload:
            found = _deep_find_first_string(item)
            if found:
                return found
        return ""
    if isinstance(payload, dict):
        text_keys = ("text", "delta", "content", "value", "message")
        for key in text_keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("part", "parts", "properties", "payload", "data", "info"):
            if key in payload:
                found = _deep_find_first_string(payload.get(key))
                if found:
                    return found
    return ""


def _extract_text_fragments(payload: Any) -> list[dict[str, str]]:
    fragments: list[dict[str, str]] = []
    if isinstance(payload, str):
        stripped = payload.strip()
        if stripped:
            fragments.append({"text": stripped, "kind": "unknown"})
        return fragments
    if isinstance(payload, list):
        for item in payload:
            fragments.extend(_extract_text_fragments(item))
        return fragments
    if not isinstance(payload, dict):
        return fragments

    part = payload.get("part")
    if isinstance(part, dict):
        part_type = str(part.get("type", "")).lower()
        part_text = part.get("text")
        if isinstance(part_text, str) and part_text.strip():
            kind = "thought" if part_type in {"reasoning", "thinking", "analysis"} or "thought" in part_type else "final"
            fragments.append({"text": part_text.strip(), "kind": kind})

    parts = payload.get("parts")
    if isinstance(parts, list):
        for entry in parts:
            if not isinstance(entry, dict):
                continue
            part_type = str(entry.get("type", "")).lower()
            part_text = entry.get("text")
            if isinstance(part_text, str) and part_text.strip():
                kind = "thought" if part_type in {"reasoning", "thinking", "analysis"} or "thought" in part_type else "final"
                fragments.append({"text": part_text.strip(), "kind": kind})

    text_candidate = _deep_find_first_string(payload)
    if text_candidate:
        fragments.append({"text": text_candidate, "kind": "unknown"})
    return fragments


def _append_delta_text(current: str, delta: str) -> str:
    base = current.strip()
    chunk = delta.strip()
    if not chunk:
        return base
    if not base:
        return chunk
    if chunk in base:
        return base
    if base.endswith(chunk):
        return base
    return f"{base}\n{chunk}"


def _append_assistant_message(
    active_session: dict[str, Any],
    text: str,
    pending: dict[str, Any],
    server_message_id: str,
) -> None:
    normalized_text = sanitize_final_answer_text(text)
    if not is_valid_final_answer_candidate(normalized_text):
        return
    if server_message_id:
        already_seen = set(str(x) for x in pending.get("seen_message_ids", []) if x)
        if server_message_id in already_seen:
            return
        pending["seen_message_ids"] = list(already_seen | {server_message_id})[-120:]

    existing_messages = active_session.get("messages", [])
    if existing_messages:
        last_msg = existing_messages[-1]
        if (
            isinstance(last_msg, dict)
            and str(last_msg.get("role")) == "assistant"
            and str(last_msg.get("text", "")).strip() == normalized_text
        ):
            return

    payload: dict[str, Any] = {"role": "assistant", "text": normalized_text}
    if server_message_id:
        payload["server_message_id"] = server_message_id
    active_session["messages"].append(payload)


def _append_thought_message(active_session: dict[str, Any], thought_text: str) -> None:
    normalized = format_thought_text(thought_text)
    if not normalized:
        return
    messages = active_session.get("messages", [])
    if messages:
        last_msg = messages[-1]
        if (
            isinstance(last_msg, dict)
            and str(last_msg.get("role")) == "assistant_thought"
            and str(last_msg.get("text", "")).strip() == normalized
        ):
            return
    active_session["messages"].append({"role": "assistant_thought", "text": normalized})


def _deep_find_session_id(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("sessionID", "sessionId", "session_id", "id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip() and key != "id":
                return value.strip()
        for key in ("session", "properties", "payload", "data", "info"):
            nested = payload.get(key)
            found = _deep_find_session_id(nested)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _deep_find_session_id(item)
            if found:
                return found
    return ""


def _normalize_event_payload(event_payload: Any) -> tuple[dict[str, Any], str]:
    if isinstance(event_payload, dict) and isinstance(event_payload.get("payload"), dict):
        inner_payload = event_payload.get("payload", {})
        event_type = str(inner_payload.get("type") or "").lower()
        return inner_payload, event_type
    if isinstance(event_payload, dict):
        event_type = str(event_payload.get("type") or "").lower()
        return event_payload, event_type
    return {}, ""


def _classify_part_kind(part_type: str) -> str:
    lowered = str(part_type or "").lower()
    if lowered in {"reasoning", "thinking", "analysis"} or "thought" in lowered:
        return "thought"
    if lowered in {"text", "final", "answer", "output"}:
        return "final"
    return "unknown"


def _rebuild_stream_text(parts: dict[str, str], part_kinds: dict[str, str], target_kind: str) -> str:
    chunks: list[str] = []
    for part_id, value in parts.items():
        if part_kinds.get(part_id) != target_kind:
            continue
        cleaned = str(value).strip()
        if cleaned:
            chunks.append(cleaned)
    return "\n\n".join(chunks).strip()


def _extract_part_snapshot(payload: dict[str, Any], properties: dict[str, Any]) -> tuple[str, str, str]:
    part_id = str(properties.get("partID") or properties.get("partId") or "").strip()
    part_type = ""
    part_text = ""

    part_obj = properties.get("part")
    if not isinstance(part_obj, dict):
        part_obj = payload.get("part") if isinstance(payload.get("part"), dict) else None

    if isinstance(part_obj, dict):
        if not part_id:
            part_id = str(part_obj.get("id") or part_obj.get("partID") or part_obj.get("partId") or "").strip()
        part_type = str(part_obj.get("type") or "").strip()
        if isinstance(part_obj.get("text"), str):
            part_text = str(part_obj.get("text")).strip()

    if not part_text:
        direct_text = properties.get("text")
        if isinstance(direct_text, str) and direct_text.strip():
            part_text = direct_text.strip()
    return part_id, part_type, part_text


def poll_session_stream_update(session_id: str, pending: dict[str, Any]) -> tuple[str, str, bool]:
    stream_thought = ""
    stream_final = ""
    stream_completed = False
    stream_parts: dict[str, str] = pending.setdefault("stream_parts", {})
    stream_part_kinds: dict[str, str] = pending.setdefault("stream_part_kinds", {})
    for event in _read_sse_events_once():
        event_payload = event.get("payload")
        if not isinstance(event_payload, dict):
            continue
        payload, event_type_from_payload = _normalize_event_payload(event_payload)
        if not payload:
            continue
        event_type = event_type_from_payload or str(event.get("event") or "").lower()
        properties = payload.get("properties", {}) if isinstance(payload.get("properties"), dict) else {}
        payload_session_id = (
            str(properties.get("sessionID") or properties.get("sessionId") or "").strip()
            or _deep_find_session_id(payload)
        )
        if payload_session_id and payload_session_id != session_id:
            continue

        message_id = str(properties.get("messageID") or properties.get("messageId") or "").strip()
        if message_id:
            pending["stream_message_id"] = message_id

        if event_type in {"message.part.added", "message.part.updated"}:
            part_id, part_type, part_text = _extract_part_snapshot(payload, properties)
            if part_id:
                classified_kind = _classify_part_kind(part_type)
                if classified_kind != "unknown":
                    stream_part_kinds[part_id] = classified_kind
                if part_text:
                    stream_parts[part_id] = part_text
            stream_thought = _rebuild_stream_text(stream_parts, stream_part_kinds, "thought")
            if not stream_final:
                stream_final = _rebuild_stream_text(stream_parts, stream_part_kinds, "final")
            continue

        # OpenCode stream format: payload.type=message.part.delta, payload.properties.delta=<chunk>
        if event_type == "message.part.delta":
            delta_text = str(properties.get("delta") or "")
            part_id = str(properties.get("partID") or properties.get("partId") or "")
            if delta_text:
                if part_id:
                    stream_parts[part_id] = f"{stream_parts.get(part_id, '')}{delta_text}"
                    if stream_part_kinds.get(part_id) == "thought":
                        stream_thought = _rebuild_stream_text(stream_parts, stream_part_kinds, "thought")
                    elif stream_part_kinds.get(part_id) == "final":
                        stream_final = _rebuild_stream_text(stream_parts, stream_part_kinds, "final")
                else:
                    # Без part_id не можем надежно классифицировать: не смешиваем с мыслями.
                    pending["stream_unclassified_delta"] = f"{pending.get('stream_unclassified_delta', '')}{delta_text}"
            continue

        text_fragments = _extract_text_fragments(payload)
        if not text_fragments:
            if "message.completed" in event_type:
                stream_completed = True
            continue

        for fragment in text_fragments:
            text_value = fragment.get("text", "").strip()
            if not text_value:
                continue
            fragment_kind = fragment.get("kind", "unknown")
            if "message.completed" in event_type:
                stream_completed = True
                if not stream_final:
                    stream_final = text_value
                continue
            if fragment_kind == "thought":
                stream_thought = f"{stream_thought}\n{text_value}".strip() if stream_thought else text_value
                continue
            if fragment_kind == "final":
                if not stream_final:
                    stream_final = text_value
                continue
            if is_intermediate_assistant_text(text_value):
                stream_thought = f"{stream_thought}\n{text_value}".strip() if stream_thought else text_value
            elif not stream_final:
                stream_final = text_value
    return stream_thought, stream_final, stream_completed


def _get_server_assistant_reply(session_id: str, message_id: str, seen_ids: set[str] | None = None) -> tuple[str, str]:
    seen = seen_ids or set()
    if message_id:
        ok, _, data, _ = fetch_json(path=f"/session/{quote(session_id, safe='')}/message/{quote(message_id, safe='')}", method="GET")
        if ok and isinstance(data, dict):
            reply = sanitize_final_answer_text(extract_assistant_text(data))
            if is_valid_final_answer_candidate(reply):
                return reply, message_id

    messages = list_session_messages(session_id, limit=30)
    for payload in reversed(messages):
        current_id = extract_message_id(payload)
        if current_id and current_id in seen:
            continue
        reply = sanitize_final_answer_text(extract_assistant_text(payload))
        if not is_valid_final_answer_candidate(reply):
            continue
        return reply, current_id
    return "", ""


def extract_reply(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    thought_types = {"reasoning", "thinking", "analysis", "thought", "scratchpad"}
    final_types = {"text", "final", "answer", "output", "result"}
    final_chunks: list[str] = []
    fallback_chunks: list[str] = []
    for part in parts:
        if (
            isinstance(part, dict)
            and isinstance(part.get("text"), str)
            and not part.get("ignored")
        ):
            part_type = str(part.get("type", "")).lower().strip()
            text_value = str(part.get("text", ""))
            if part_type in thought_types:
                continue
            if part_type in final_types or not part_type:
                final_chunks.append(text_value)
            else:
                fallback_chunks.append(text_value)
    merged = "".join(final_chunks).strip()
    if merged:
        return merged
    return "".join(fallback_chunks).strip()


def check_health() -> None:
    ok, _, _, _ = fetch_json("/global/health")
    st.session_state.opencode_health_ok = ok
    add_connection_log("OpenCode health", "ok" if ok else "failed")


def get_active_session() -> dict[str, Any] | None:
    active_id = st.session_state.active_session_local_id
    for session in st.session_state.sessions:
        if session["local_id"] == active_id:
            return session
    return None


def create_session(auto: bool = False) -> bool:
    ok, status, data, raw_text = fetch_json(
        path="/session",
        method="POST",
        payload={"title": "Streamlit session"},
    )
    if not ok:
        st.session_state.error_message = (
            f"Ошибка создания сессии (HTTP {status}): {raw_text or 'empty body'}"
        )
        return False

    session_id = (data or {}).get("id")
    if not isinstance(session_id, str) or not session_id.strip():
        st.session_state.error_message = "OpenCode вернул ответ без валидного id сессии."
        return False

    created_at = int(time.time())
    local_id = str(uuid.uuid4())
    model = {
        "local_id": local_id,
        "server_session_id": session_id,
        "title": "Новая сессия",
        "created_at": created_at,
        "messages": [],
    }
    st.session_state.sessions.insert(0, model)
    st.session_state.active_session_local_id = local_id
    st.session_state.error_message = ""
    persist_sessions_to_db()

    if auto:
        st.toast("Сессия создана автоматически", icon="✅")
    return True


def ensure_auto_session() -> None:
    if get_active_session() is not None:
        return
    # Уже есть локальные сессии (из БД), но не выбрана активная — не дергаем OpenCode зря.
    if st.session_state.sessions:
        st.session_state.active_session_local_id = st.session_state.sessions[0]["local_id"]
        st.session_state.error_message = ""
        persist_sessions_to_db()
        return
    create_session(auto=True)


def render_sidebar() -> None:
    with st.sidebar:
        health_icon = "🟢" if st.session_state.opencode_health_ok else "🔴"
        st.markdown(f"### {health_icon} XCA AI")
        st.caption(f"Backend: `{st.session_state.get('runtime_opencode_url', DEFAULT_OPENCODE_URL)}`")
        if ENABLE_SSH_TUNNEL:
            st.caption(
                f"Tunnel: `{AI_SSH_USER}@{AI_SSH_HOST}:{AI_SSH_PORT}` -> "
                f"`127.0.0.1:{AI_OPENCODE_REMOTE_PORT}` -> "
                f"`127.0.0.1:{AI_LOCAL_TUNNEL_PORT}`"
            )
        with st.expander("Диагностика подключения", expanded=False):
            logs: list[str] = st.session_state.get("connection_logs", [])
            if logs:
                st.code("\n".join(logs[-25:]), language="text")
            else:
                st.caption("Логи подключения пока пусты.")
            if st.button("Сбросить подключение (перечитать .env, заново SSH)", key="reset_opencode_net"):
                st.session_state.runtime_opencode_url = ""
                st.session_state.connection_logs = []
                st.session_state.error_message = ""
                st.session_state._force_opencode_url_resolve = True
                try:
                    open_ssh_tunnel.clear()  # type: ignore[attr-defined]
                except Exception:
                    pass
                st.rerun()

        if WEB_AUTH_TOKEN:
            st.markdown("#### Доступ")
            st.text_input("Токен доступа", type="password", key="auth_input")
            if st.button("Войти", use_container_width=True):
                st.session_state.auth_ok = st.session_state.auth_input == WEB_AUTH_TOKEN
                if not st.session_state.auth_ok:
                    st.error("Неверный токен")
                else:
                    st.success("Доступ разрешен")

        st.markdown("#### Сессии")
        if st.button("+ Новая сессия", use_container_width=True):
            if create_session():
                st.rerun()

        if not st.session_state.sessions:
            st.caption("История пока пуста.")

        for session in st.session_state.sessions:
            title = session["title"] or "Новая сессия"
            timestamp = time.strftime("%d.%m %H:%M", time.localtime(session["created_at"]))
            button_label = f"{title} · {timestamp}"
            is_active = session["local_id"] == st.session_state.active_session_local_id
            select_col, delete_col = st.columns([0.84, 0.16])
            with select_col:
                if st.button(
                    button_label,
                    use_container_width=True,
                    type="primary" if is_active else "secondary",
                    key=f"session_btn_{session['local_id']}",
                ):
                    st.session_state.active_session_local_id = session["local_id"]
                    persist_sessions_to_db()
                    st.rerun()
            with delete_col:
                if st.button("🗑", key=f"session_delete_{session['local_id']}", help="Удалить сессию"):
                    delete_session(session["local_id"])
                    st.session_state.error_message = ""
                    if not st.session_state.sessions:
                        ensure_auto_session()
                    st.rerun()

        if st.button("Очистить историю", use_container_width=True):
            st.session_state.sessions = []
            st.session_state.active_session_local_id = None
            st.session_state.error_message = ""
            persist_sessions_to_db()
            ensure_auto_session()
            st.rerun()


def render_messages(active_session: dict[str, Any]) -> None:
    if not active_session["messages"]:
        st.info("Сессия создана автоматически. Напиши сообщение.")
        return

    for idx, message in enumerate(active_session["messages"]):
        message_role = str(message.get("role", "assistant"))
        if message_role == "assistant_thought":
            render_assistant_thought(str(message.get("text", "")), idx)
            continue

        role = "user" if message_role == "user" else "assistant"
        with st.chat_message(role):
            st.write(message["text"])
            if role == "assistant":
                image_info = extract_image_paths_from_text(message["text"])
                for image_path in image_info["existing"]:
                    st.image(str(image_path), use_container_width=True)
                for missing_path in image_info["missing"]:
                    key = str(missing_path)
                    if key not in st.session_state.awaiting_images:
                        st.session_state.awaiting_images[key] = time.time()
                    st.caption(f"Ожидание изображения: {missing_path}")


def _truncate_to_two_lines(text: str) -> tuple[str, bool]:
    lines = [line.rstrip() for line in text.splitlines()]
    if len(lines) <= 2:
        return text, False
    preview = "\n".join(lines[:2]).rstrip()
    return f"{preview}\n...", True


def render_assistant_thought(text: str, idx: int) -> None:
    prepared_text = text.strip()
    if not prepared_text:
        return
    preview, is_collapsible = _truncate_to_two_lines(prepared_text)
    toggle_key = f"assistant_thought_expanded_{idx}"
    if toggle_key not in st.session_state:
        st.session_state[toggle_key] = False

    with st.chat_message("assistant"):
        st.caption("Мысли ИИ")
        if is_collapsible and not st.session_state[toggle_key]:
            render_thought_block(preview)
        else:
            render_thought_block(prepared_text)

        if is_collapsible:
            toggle_label = "Свернуть" if st.session_state[toggle_key] else "Развернуть"
            if st.button(toggle_label, key=f"{toggle_key}_button"):
                st.session_state[toggle_key] = not st.session_state[toggle_key]
                st.rerun()


def extract_image_paths_from_text(text: str) -> dict[str, list[Path]]:
    unix_matches = re.findall(
        r"(/workspace/[^\s\]\)\"']+\.(?:png|jpg|jpeg|webp|gif))",
        text,
        flags=re.IGNORECASE,
    )
    win_matches = re.findall(
        r"([A-Za-z]:\\\\[^\s\]\)\"']+\.(?:png|jpg|jpeg|webp|gif))",
        text,
        flags=re.IGNORECASE,
    )
    matches = unix_matches + win_matches
    found_existing: list[Path] = []
    found_missing: list[Path] = []
    for match in matches:
        normalized = match.strip().strip(".,;:!?)(").strip('"').strip("'")
        normalized = normalized.strip("`")
        normalized = normalized.replace("\\\\", "\\")
        path_obj = Path(normalized)
        if path_obj.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if path_obj.exists() and path_obj.is_file():
            found_existing.append(path_obj)
        else:
            found_missing.append(path_obj)
    return {"existing": found_existing, "missing": found_missing}


def list_session_messages(session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    path = f"/session/{quote(session_id, safe='')}/message"
    if limit is not None:
        path = f"{path}?limit={limit}"
    ok, _, data, _ = fetch_json(
        path=path,
        method="GET",
        timeout_seconds=POLL_REQUEST_TIMEOUT_SECONDS,
    )
    if not ok:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def extract_assistant_text(message_payload: dict[str, Any]) -> str:
    info = message_payload.get("info", {})
    role = str(info.get("role", "")).lower()
    if role and role != "assistant":
        return ""
    return extract_reply(message_payload.get("parts"))


def extract_message_id(message_payload: dict[str, Any]) -> str:
    info = message_payload.get("info", {})
    for key in ("id", "messageID", "messageId"):
        value = info.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def is_data_query(user_message: str) -> bool:
    lowered = user_message.lower()
    data_markers = (
        "анализ",
        "график",
        "сравни",
        "сравнение",
        "топ",
        "выгруз",
        "статус",
        "причин",
        "ресурс",
        "проект",
        "csv",
        "файл",
    )
    return any(marker in lowered for marker in data_markers)


def is_analytics_followup_query(active_session: dict[str, Any], user_message: str) -> bool:
    lowered = user_message.lower().strip()
    followup_markers = (
        "и что",
        "что наш",
        "какой итог",
        "итог",
        "результат",
        "покажи итог",
        "ну и",
        "что получилось",
    )
    if not any(marker in lowered for marker in followup_markers):
        return False

    last_user_texts: list[str] = []
    for message in reversed(active_session.get("messages", [])):
        if message.get("role") == "user":
            last_user_texts.append(str(message.get("text", "")).lower())
        if len(last_user_texts) >= 4:
            break

    return any(is_data_query(text) for text in last_user_texts)


def should_use_sync_path(active_session: dict[str, Any], user_message: str) -> bool:
    # Для стабильного показа stream/мыслей используем единый async-пайплайн.
    # Sync-путь отключен, т.к. он не дает потоковых обновлений.
    return False


def is_intermediate_assistant_text(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return False
    intermediate_regexes = (
        r"\bпроверя(ю|ем|ется)\b",
        r"\bпровер(ю|им)\b",
        r"\bпосмотр(ю|им)\b",
        r"\bизуч(у|им)\b",
        r"\bзапуска(ю|ем)\b",
        r"\bзапущ(у|им)\b",
        r"\bанализир(ую|уем)\b",
        r"\bуточн(ю|им)\b",
        r"\bпопробу(ю|ем)\b",
        r"\bсначала\b",
        r"\bдалее\b",
        r"\bподожд(и|ите)\b",
    )
    final_markers = (
        "самый",
        "топ",
        "итог",
        "результат",
        "всего",
        "статус",
        "проект",
        "данных нет",
        "ошибка",
        "/workspace/analytics/output/",
    )
    if any(marker in lowered for marker in final_markers):
        return False
    return any(re.search(pattern, lowered) for pattern in intermediate_regexes)


def compose_model_payload(session_id: str, user_message: str) -> dict[str, Any]:
    system_parts = [BASE_PERSONA_HINT]
    rules_text = str(st.session_state.get("assistant_rules_text", "")).strip()
    if rules_text:
        system_parts.append(rules_text)
    if is_data_query(user_message) and not bool(st.session_state.data_hint_sent_sessions.get(session_id)):
        st.session_state.data_hint_sent_sessions[session_id] = True
        system_parts.append(KNOWLEDGE_HINT)
    system_text = "\n\n".join(part.strip() for part in system_parts if part.strip())
    return {
        "system": system_text,
        "parts": [{"type": "text", "text": user_message}],
    }


def sanitize_stream_thought_text(raw: str) -> str:
    text = str(raw or "")
    if not text.strip():
        return ""
    cleaned = re.sub(r"\[INTERNAL-ROLE\].*?\[/INTERNAL-ROLE\]", "", text, flags=re.S | re.I)
    cleaned = re.sub(r"\[INTERNAL-KNOWLEDGE-FOR-AGENT\].*?\[/INTERNAL-KNOWLEDGE-FOR-AGENT\]", "", cleaned, flags=re.S | re.I)
    cleaned = re.sub(r"^\s*Запрос пользователя:\s*$", "", cleaned, flags=re.I | re.M)
    cleaned = re.sub(r"\s+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    filtered_lines: list[str] = []
    for line in lines:
        lowered = line.lower()
        if re.search(r"[\u4e00-\u9fff]", line):
            continue
        if lowered.startswith("the user") or lowered.startswith("let me") or lowered.startswith("i should"):
            continue
        if lowered.startswith("user ") or lowered.startswith("assistant "):
            continue
        cyr = len(re.findall(r"[А-Яа-яЁё]", line))
        lat = len(re.findall(r"[A-Za-z]", line))
        if lat > cyr * 2 and cyr < 8:
            continue
        filtered_lines.append(line)
    cleaned = "\n".join(filtered_lines).strip()
    return cleaned


def sanitize_final_answer_text(raw: str) -> str:
    text = str(raw or "")
    if not text.strip():
        return ""
    cleaned = re.sub(r"\[INTERNAL-ROLE\].*?\[/INTERNAL-ROLE\]", "", text, flags=re.S | re.I)
    cleaned = re.sub(r"\[INTERNAL-KNOWLEDGE-FOR-AGENT\].*?\[/INTERNAL-KNOWLEDGE-FOR-AGENT\]", "", cleaned, flags=re.S | re.I)
    cleaned = re.sub(r"^\s*Запрос пользователя:\s*$", "", cleaned, flags=re.I | re.M)
    cleaned = re.sub(r"^\s*Мысли\s*:?.*$", "", cleaned, flags=re.I | re.M)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def is_valid_final_answer_candidate(text: str) -> bool:
    normalized = sanitize_final_answer_text(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    if "[internal-role]" in lowered or "[internal-knowledge-for-agent]" in lowered:
        return False
    if "запрос пользователя:" in lowered:
        return False
    if is_intermediate_assistant_text(normalized):
        return False
    if looks_like_non_final_status_text(normalized):
        return False
    if looks_like_internal_working_text(normalized):
        return False
    return True


def looks_like_non_final_status_text(text: str) -> bool:
    lowered = str(text or "").lower().strip()
    status_markers = (
        "проведу",
        "подготовлю",
        "посмотрю",
        "прочитаю",
        "покажу",
        "построю",
        "сформирую",
        "перестрою",
        "проверю",
        "проверить",
        "сейчас проверю",
        "начну с",
        "выполню",
        "анализирую",
        "уточняю",
        "позвольте",
        "где аналитика",
        "и где",
    )
    if any(marker in lowered for marker in status_markers):
        return True
    # Дополнительный паттерн статусных фраз вида "сначала ... затем ..."
    if re.search(r"\bсначала\b.*\bзатем\b", lowered):
        return True
    return False


def looks_like_internal_working_text(text: str) -> bool:
    lowered = str(text or "").lower()
    internal_markers = (
        "проверю",
        "запущу",
        "посмотрю",
        "начну с",
        "let me",
        "i should",
        "the user",
        "tool",
        ".py",
    )
    return any(marker in lowered for marker in internal_markers)


def list_pending_questions_for_session(session_id: str) -> list[dict[str, Any]]:
    ok, _, data, _ = fetch_json(path="/question", method="GET", timeout_seconds=POLL_REQUEST_TIMEOUT_SECONDS)
    if not ok or not isinstance(data, list):
        return []
    pending: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("sessionID") == session_id:
            if str(item.get("id")) in st.session_state.dismissed_question_ids:
                continue
            pending.append(item)
    return pending


def parse_question_payload(question_request: dict[str, Any]) -> dict[str, Any]:
    def normalize_exec_text(text: str, fallback: str) -> str:
        prepared = re.sub(r"\s+", " ", text or "").strip()
        if not prepared:
            return fallback
        replacements = {
            "python": "данные",
            "скрипт": "отчет",
            "api": "система",
            "json": "данные",
            "код": "расчет",
        }
        lowered = prepared.lower()
        for source, target in replacements.items():
            lowered = lowered.replace(source, target)
        if len(lowered) > 120:
            lowered = lowered[:117].rstrip() + "..."
        return lowered.capitalize()

    q_info = (question_request.get("questions") or [{}])[0] if isinstance(question_request.get("questions"), list) else {}
    question_header = normalize_exec_text(str(q_info.get("header") or ""), "Уточните запрос")
    question_full = normalize_exec_text(str(q_info.get("question") or question_header), question_header)
    options: list[dict[str, str]] = []
    for option in (q_info.get("options") or [])[:4]:
        if not isinstance(option, dict):
            continue
        raw_label = str(option.get("label") or "").strip()
        label = normalize_exec_text(raw_label, "")
        if not label:
            continue
        description = normalize_exec_text(str(option.get("description") or ""), "")
        answer_value = str(option.get("value") or raw_label).strip()
        if not answer_value:
            answer_value = raw_label or label
        options.append({"label": label, "description": description, "answer": answer_value})
    return {"header": question_header, "full": question_full, "options": options}


def reply_question(request_id: str, selected_labels: list[str]) -> bool:
    ok, _, _, _ = fetch_json(
        path=f"/question/{quote(request_id, safe='')}/reply",
        method="POST",
        payload={"answers": [selected_labels]},
        timeout_seconds=QUESTION_REPLY_TIMEOUT_SECONDS,
    )
    return ok


def process_pending_question_reply(active_session: dict[str, Any]) -> bool:
    payload = st.session_state.pending_question_reply
    if not payload:
        return False
    if payload.get("local_session_id") != active_session["local_id"]:
        st.session_state.pending_question_reply = None
        return False

    request_id = str(payload.get("request_id", ""))
    selected_label = str(payload.get("selected_label", ""))
    if not request_id or not selected_label:
        st.session_state.pending_question_reply = None
        return False

    replied = reply_question(request_id, [selected_label])
    if not replied:
        active_session["messages"].append({"role": "assistant", "text": "Не удалось отправить уточнение в OpenCode."})
        persist_sessions_to_db()
        st.session_state.pending_question_reply = None
        return True

    tail_messages = list_session_messages(active_session["server_session_id"], limit=40)
    seen_ids = [extract_message_id(item) for item in tail_messages]
    seen_ids = [x for x in seen_ids if x]
    st.session_state.pending_request = {
        "local_session_id": active_session["local_id"],
        "message": "",
        "started": True,
        "started_at": time.time(),
        "seen_message_ids": seen_ids,
        "mode": "wait",
        "last_message_count": len(tail_messages),
        "stable_polls": 0,
        "candidate_message_id": "",
        "candidate_reply": "",
    }
    st.session_state.pending_question_reply = None
    return True


def queue_model_request(active_session: dict[str, Any], prompt_for_model: str) -> None:
    tail_messages = list_session_messages(active_session["server_session_id"], limit=20)
    seen_ids = [extract_message_id(item) for item in tail_messages]
    seen_ids = [x for x in seen_ids if x]
    sync_mode = should_use_sync_path(active_session, prompt_for_model)
    st.session_state.pending_request = {
        "local_session_id": active_session["local_id"],
        "message": prompt_for_model,
        "started": False,
        "started_at": time.time(),
        "seen_message_ids": seen_ids,
        "mode": "submit",
        "last_message_count": len(tail_messages),
        "stable_polls": 0,
        "candidate_message_id": "",
        "candidate_reply": "",
        "sync_mode": sync_mode,
        "check_questions": not sync_mode,
        "poll_tick": 0,
    }


def send_message(active_session: dict[str, Any], user_text: str) -> None:
    cleaned = user_text.strip()
    if not cleaned:
        st.warning("Пустое сообщение отправлять нельзя.")
        return
    if len(cleaned) > MAX_MESSAGE_LENGTH:
        st.warning(f"Сообщение слишком длинное. Максимум {MAX_MESSAGE_LENGTH} символов.")
        return

    active_session["messages"].append({"role": "user", "text": cleaned})

    if active_session["title"] == "Новая сессия":
        normalized = " ".join(cleaned.split())
        active_session["title"] = normalized[:40] or "Новая сессия"

    persist_sessions_to_db()
    queue_model_request(active_session, cleaned)


def _submit_prompt_async(server_session_id: str, user_message: str) -> tuple[bool, str]:
    payload = compose_model_payload(server_session_id, user_message)
    ok, status, _, raw_text = fetch_json(
        path=f"/session/{quote(server_session_id, safe='')}/prompt_async",
        method="POST",
        payload=payload,
    )
    if ok:
        return True, ""
    return False, f"Ошибка OpenCode (HTTP {status}): {raw_text or 'empty body'}"


def _submit_prompt_sync(server_session_id: str, user_message: str) -> tuple[bool, str]:
    payload = compose_model_payload(server_session_id, user_message)
    ok, status, data, raw_text = fetch_json(
        path=f"/session/{quote(server_session_id, safe='')}/message",
        method="POST",
        payload=payload,
        timeout_seconds=REQUEST_TIMEOUT_SECONDS,
    )
    if not ok:
        return False, f"Ошибка OpenCode (HTTP {status}): {raw_text or 'empty body'}"
    reply_text = extract_reply((data or {}).get("parts")) or "(пустой ответ)"
    return True, reply_text


def process_pending_request() -> bool:
    pending = st.session_state.pending_request
    if not pending:
        return False

    active_session = None
    for session in st.session_state.sessions:
        if session["local_id"] == pending["local_session_id"]:
            active_session = session
            break

    if active_session is None:
        st.session_state.pending_request = None
        return False

    if pending.get("mode") == "submit" and not pending.get("started", False):
        if bool(pending.get("sync_mode", False)):
            with st.chat_message("assistant"):
                st.markdown("Подготавливаю ответ...")
            ok, sync_reply = _submit_prompt_sync(active_session["server_session_id"], pending["message"])
            if not ok:
                active_session["messages"].append({"role": "assistant", "text": sync_reply})
                persist_sessions_to_db()
                st.session_state.pending_request = None
                st.rerun()
                return False
            _append_assistant_message(active_session, sync_reply, pending, "")
            persist_sessions_to_db()
            st.session_state.pending_request = None
            st.rerun()
            return False
        ok, error_text = _submit_prompt_async(active_session["server_session_id"], pending["message"])
        if not ok:
            active_session["messages"].append({"role": "assistant", "text": error_text})
            persist_sessions_to_db()
            st.session_state.pending_request = None
            st.rerun()
            return False
        pending["started"] = True
        pending["started_at"] = time.time()
        pending["mode"] = "wait"

    with st.chat_message("assistant"):
        animation_placeholder = st.empty()
        thought_placeholder = st.empty()
        dots = [".", "..", "..."]
        elapsed = max(0.0, time.time() - float(pending.get("started_at", time.time())))
        dot_idx = int(elapsed / POLL_INTERVAL_SECONDS) % len(dots)
        animation_placeholder.markdown(f"ИИ анализирует{dots[dot_idx]}")

        pending["poll_tick"] = int(pending.get("poll_tick", 0)) + 1
        should_check_questions = bool(pending.get("check_questions", False)) and pending["poll_tick"] % 2 == 0
        if should_check_questions:
            pending_questions = list_pending_questions_for_session(active_session["server_session_id"])
            if pending_questions:
                q = pending_questions[0]
                parsed_question = parse_question_payload(q)
                st.session_state.pending_opencode_question = {
                    "request_id": q.get("id"),
                    "session_id": q.get("sessionID"),
                    "question_text": parsed_question["header"],
                    "question_full_text": parsed_question["full"],
                    "options": parsed_question["options"],
                    "local_session_id": active_session["local_id"],
                }
                st.session_state.pending_request = None
                active_session["messages"].append({"role": "assistant", "text": parsed_question["header"]})
                persist_sessions_to_db()
                st.rerun()
                return False

        stream_thought, stream_final, stream_completed = poll_session_stream_update(active_session["server_session_id"], pending)
        if stream_thought:
            safe_thought = sanitize_stream_thought_text(stream_thought)
            if safe_thought:
                pending["thought_text"] = safe_thought
            elif not str(pending.get("thought_text", "")).strip():
                pending["thought_text"] = "Уточняю бизнес-контекст запроса и формирую итоговый ответ."
            thought_preview_source = format_thought_text(str(pending.get("thought_text", "")))
            preview_text, _ = _truncate_to_two_lines(thought_preview_source.strip())
            with thought_placeholder.container():
                st.caption("Мысли ИИ (стриминг)")
                render_thought_block(preview_text or "...")
        elif not str(pending.get("thought_text", "")).strip():
            with thought_placeholder.container():
                st.caption("Мысли ИИ (стриминг)")
                render_thought_block("Анализирую запрос и формирую итоговый ответ...")

        # Финальный ответ берём только из message API после completion.

        if stream_completed:
            if "completion_seen_at" not in pending:
                pending["completion_seen_at"] = time.time()
            stream_message_id = str(pending.get("stream_message_id", "")).strip()
            seen_ids_completion = set(str(x) for x in pending.get("seen_message_ids", []) if x)
            latest_text, latest_id = _get_server_assistant_reply(
                active_session["server_session_id"],
                stream_message_id,
                seen_ids_completion,
            )
            if latest_text:
                thought_text = str(pending.get("thought_text", "")).strip()
                if thought_text and thought_text.strip() and thought_text.strip() != latest_text.strip():
                    _append_thought_message(active_session, thought_text)
                # В completion-ветке ответ обязателен: не блокируем добавление ранее отмеченным seen-id.
                _append_assistant_message(active_session, latest_text, pending, "")
                persist_sessions_to_db()
                st.session_state.pending_request = None
                st.rerun()
                return False
            # После completion даем серверу время стабилизировать финальный message, не теряем pending.
            completion_elapsed = time.time() - float(pending.get("completion_seen_at", time.time()))
            if completion_elapsed > 12:
                active_session["messages"].append(
                    {
                        "role": "assistant",
                        "text": "Не удалось получить итоговый ответ вовремя. Повтори запрос, я продолжу с текущего контекста.",
                    }
                )
                persist_sessions_to_db()
                st.session_state.pending_request = None
                st.rerun()
                return False

        # Надежный fallback: итог берем только из message API и подтверждаем стабильностью 2 тиков.
        seen_ids_completion = set(str(x) for x in pending.get("seen_message_ids", []) if x)
        latest_text, latest_id = _get_server_assistant_reply(
            active_session["server_session_id"],
            "",
            seen_ids_completion,
        )
        if latest_text:
            previous_candidate_id = str(pending.get("candidate_message_id", ""))
            previous_candidate_text = str(pending.get("candidate_reply", ""))
            if latest_id == previous_candidate_id and latest_text == previous_candidate_text:
                pending["stable_polls"] = int(pending.get("stable_polls", 0)) + 1
            else:
                pending["candidate_message_id"] = latest_id
                pending["candidate_reply"] = latest_text
                pending["stable_polls"] = 1

            stable_polls = int(pending.get("stable_polls", 0))
            completion_seen = "completion_seen_at" in pending
            # Без completion требуем более устойчивое подтверждение, чтобы не принять статус за финал.
            required_stable = 2 if completion_seen else 4
            if stable_polls >= required_stable:
                thought_text = str(pending.get("thought_text", "")).strip()
                if thought_text and thought_text.strip() and thought_text.strip() != latest_text.strip():
                    _append_thought_message(active_session, thought_text)
                _append_assistant_message(active_session, latest_text, pending, latest_id)
                persist_sessions_to_db()
                st.session_state.pending_request = None
                st.rerun()
                return False
        else:
            pending["candidate_message_id"] = ""
            pending["candidate_reply"] = ""
            pending["stable_polls"] = 0

        if time.time() - float(pending.get("started_at", time.time())) > ASYNC_TOTAL_TIMEOUT_SECONDS:
            active_session["messages"].append(
                {
                    "role": "assistant",
                    "text": "Запрос выполняется дольше обычного. Уточни проект или период, чтобы ускорить ответ.",
                }
            )
            persist_sessions_to_db()
            st.session_state.pending_request = None
            st.rerun()
            return False

    return True


def render_opencode_question_controls(active_session: dict[str, Any]) -> None:
    payload = st.session_state.pending_opencode_question
    if not payload:
        return
    if payload.get("local_session_id") != active_session["local_id"]:
        return

    st.caption("Уточните, что показать в отчете")
    full_text = payload.get("question_full_text", "")
    if full_text and full_text != payload.get("question_text", ""):
        st.caption(full_text)
    options = payload.get("options", [])
    radio_options: list[str] = []
    display_to_answer: dict[str, str] = {}
    for idx, option in enumerate(options, start=1):
        label = str(option.get("label", "")).strip()
        if not label:
            continue
        description = str(option.get("description", "")).strip()
        answer = str(option.get("answer", "")).strip() or label
        display = f"{idx}) {label}"
        if description:
            display = f"{display} — {description}"
        radio_options.append(display)
        display_to_answer[display] = answer

    if not radio_options:
        return

    if st.session_state.pending_question_reply and st.session_state.pending_question_reply.get("local_session_id") == active_session["local_id"]:
        st.caption("Отправляю уточнение...")
        return

    st.caption("Выберите вариант:")
    for idx, option_display in enumerate(radio_options):
        reply_label = display_to_answer.get(option_display, "")
        if st.button(option_display, key=f"question_option_{payload.get('request_id')}_{idx}", use_container_width=True):
            request_id = str(payload.get("request_id", ""))
            st.session_state.dismissed_question_ids.add(str(request_id))
            st.session_state.pending_opencode_question = None
            st.session_state.last_selected_clarification = reply_label
            st.session_state.pending_question_reply = {
                "local_session_id": active_session["local_id"],
                "request_id": request_id,
                "selected_label": reply_label,
            }
            st.rerun()
            return


def main(on_back_requested: Any | None = None) -> None:
    st.set_page_config(page_title="XCA AI", page_icon=str(APP_LOGO_PATH), layout="wide")
    apply_xca_theme()
    init_state()
    check_health()
    ensure_auto_session()
    render_sidebar()
    render_xca_branding("XCA AI chat")
    render_back_to_main_menu_button(on_back_requested)

    active_session = get_active_session()
    if active_session is None:
        detail = (st.session_state.get("error_message") or "").strip()
        st.error(
            "Не удалось выбрать или создать сессию."
            + (f" {detail}" if detail else " Проверьте, что OpenCode отвечает на Backend URL, и нажмите «+ Новая сессия».")
        )
        return

    st.caption(f"Session ID: `{active_session['server_session_id']}`")

    if WEB_AUTH_TOKEN and not st.session_state.auth_ok:
        st.warning("Для работы с чатом введи токен в левой панели.")
        return

    if st.session_state.error_message:
        st.error(st.session_state.error_message)
    if st.session_state.last_selected_clarification:
        st.info(f"Выбрано уточнение: {st.session_state.last_selected_clarification}")
    render_loading_status()

    question_reply_progress = process_pending_question_reply(active_session)
    render_messages(active_session)
    render_opencode_question_controls(active_session)
    request_in_progress = process_pending_request()

    question_locked = (
        st.session_state.pending_opencode_question is not None
        and st.session_state.pending_opencode_question.get("local_session_id") == active_session["local_id"]
    )
    prompt = st.chat_input(
        "Напиши сообщение",
        disabled=st.session_state.pending_request is not None or question_locked,
    )
    if prompt:
        send_message(active_session, prompt)
        st.rerun()

    if request_in_progress:
        time.sleep(0.35)
        st.rerun()
    if question_reply_progress:
        st.rerun()

    if st.session_state.awaiting_images:
        now = time.time()
        to_remove: list[str] = []
        for path_str, started_at in st.session_state.awaiting_images.items():
            path_obj = Path(path_str)
            if path_obj.exists() and path_obj.is_file():
                to_remove.append(path_str)
            elif now - float(started_at) > 15:
                to_remove.append(path_str)
        for key in to_remove:
            st.session_state.awaiting_images.pop(key, None)
        if st.session_state.awaiting_images and st.session_state.pending_request is None:
            time.sleep(0.5)
            st.rerun()


if __name__ == "__main__":
    main()
