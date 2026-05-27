"""
Лаунчер OpenCode AI: SSH-туннель на localhost:4096 и открытие Web UI в /workspace.

  cd opencode_only
  streamlit run streamlit_app.py
"""

from __future__ import annotations

import webbrowser
from pathlib import Path

import streamlit as st

from opencode_tunnel import (
    AI_LOCAL_TUNNEL_PORT,
    AI_OPENCODE_REMOTE_PORT,
    AI_SSH_HOST,
    AI_SSH_PORT,
    AI_SSH_USER,
    ENABLE_SSH_TUNNEL,
    bootstrap_backend,
    get_opencode_base_url,
    get_opencode_browser_url,
    stop_ssh_tunnel,
)
from opencode_ui_url import DEFAULT_XCA_WORKSPACE

APP_DIR = Path(__file__).resolve().parent
LOGO_PATH = APP_DIR / "logo.svg"

XCA_CSS = """
<style>
.stApp { background: #141414; color: #f2f2f2; }
[data-testid="stSidebar"] { background: #202020; }
div.stButton > button {
  background: #2a2a2a;
  color: #f2f2f2;
  border: 1px solid #3a3a3a;
}
</style>
"""


def render_header() -> None:
    st.title("OpenCode AI")


def render_connection_status(browser_url: str) -> None:
    health_icon = "🟢" if st.session_state.get("opencode_health_ok") else "🔴"
    st.markdown(f"### {health_icon} Подключение к OpenCode AI")

    if ENABLE_SSH_TUNNEL:
        st.caption(
            f"SSH: `{AI_SSH_USER}@{AI_SSH_HOST}:{AI_SSH_PORT}` → "
            f"сервер `127.0.0.1:{AI_OPENCODE_REMOTE_PORT}` → "
            f"ПК `127.0.0.1:{AI_LOCAL_TUNNEL_PORT}`"
        )
    else:
        st.caption("SSH выключен — прямой URL из `.env`")

    st.markdown(f"**Web UI:** `{browser_url}`")
    st.caption(f"Рабочая директория на сервере: `{DEFAULT_XCA_WORKSPACE}`")

    version = str(st.session_state.get("opencode_version", "")).strip()
    if version:
        st.caption(f"Версия сервера: `{version}`")

    err = str(st.session_state.get("tunnel_error", "")).strip()
    if err:
        st.error(err)
    elif st.session_state.get("opencode_health_ok"):
        st.success("Туннель активен. Кнопка ниже откроет OpenCode Web UI в /workspace.")
    else:
        st.warning("Сервер пока не отвечает. Проверьте Docker на сервере или нажмите «Переподключить SSH».")


def render_main_menu(browser_url: str) -> None:
    st.subheader("Главное меню")
    st.write(
        "Streamlit держит SSH-туннель. **OpenCode AI** откроется в каталоге "
        f"`{DEFAULT_XCA_WORKSPACE}` (маршрут OpenCode: `{browser_url}`). "
        "Не используйте `/` или `/Lw/session` — это корень ФС `/`, UI зависает."
    )

    disabled = not bool(st.session_state.get("opencode_health_ok"))
    if st.button(
        "Открыть OpenCode AI",
        type="primary",
        use_container_width=True,
        disabled=disabled,
        help=f"Откроет UI в {DEFAULT_XCA_WORKSPACE} (base64url slug в URL)",
    ):
        webbrowser.open(browser_url)
        st.toast("Открыто: OpenCode AI", icon="🌐")

    st.link_button(
        "Открыть OpenCode AI (ссылка)",
        browser_url,
        use_container_width=True,
        disabled=disabled,
    )

    if st.button("Переподключить SSH", use_container_width=True):
        stop_ssh_tunnel()
        st.session_state.runtime_opencode_url = ""
        st.rerun()

    with st.expander("Диагностика подключения"):
        st.caption(f"Health: `{get_opencode_base_url()}/global/health`")
        backend = str(st.session_state.get("runtime_opencode_url", "")).strip()
        if backend:
            st.caption(f"Backend API: `{backend}`")
        logs: list[str] = st.session_state.get("connection_logs", [])
        if logs:
            st.code("\n".join(logs[-25:]), language="text")
        else:
            st.caption("Логи подключения пока пусты.")
        st.caption("Проблемы с UI: выполните `bash scripts/redeploy.sh` на сервере.")


def app() -> None:
    st.set_page_config(
        page_title="OpenCode AI",
        page_icon=str(LOGO_PATH) if LOGO_PATH.exists() else None,
        layout="wide",
    )
    st.markdown(XCA_CSS, unsafe_allow_html=True)

    bootstrap_backend()
    browser_url = get_opencode_browser_url()

    render_header()
    render_connection_status(browser_url)
    render_main_menu(browser_url)


if __name__ == "__main__":
    app()
