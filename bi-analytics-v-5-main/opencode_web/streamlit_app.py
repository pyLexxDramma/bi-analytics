"""
OpenCode AI on Streamlit: embedded chat (SSH tunnel to OpenCode backend).

  cd opencode_web
  streamlit run streamlit_app.py
"""

from __future__ import annotations

from ai_chat_app import app

if __name__ == "__main__":
    app()
