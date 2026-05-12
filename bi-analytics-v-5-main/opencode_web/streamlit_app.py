import streamlit as st

from ai_chat_app import APP_LOGO_PATH, apply_xca_theme, main as render_ai_chat, render_xca_branding


CHAT_VIEW_STATE_KEY = "show_ai_chat"


def open_ai_chat() -> None:
    st.session_state[CHAT_VIEW_STATE_KEY] = True


def back_to_main_menu() -> None:
    st.session_state[CHAT_VIEW_STATE_KEY] = False


def render_main_menu() -> None:
    st.set_page_config(page_title="XCA AI", page_icon=str(APP_LOGO_PATH), layout="wide")
    apply_xca_theme()
    render_xca_branding("XCA AI")
    st.subheader("Главное меню")
    st.write("Выберите действие:")
    if st.button("Открыть чат с ИИ", key="open_ai_chat", use_container_width=True):
        open_ai_chat()
        st.rerun()


def app() -> None:
    if CHAT_VIEW_STATE_KEY not in st.session_state:
        st.session_state[CHAT_VIEW_STATE_KEY] = False
    if st.session_state[CHAT_VIEW_STATE_KEY]:
        render_ai_chat(on_back_requested=back_to_main_menu)
        return
    render_main_menu()

if __name__ == "__main__":
    app()
