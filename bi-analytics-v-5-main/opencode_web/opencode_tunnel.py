"""SSH-tunnel to OpenCode and /global/health check."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv
from sshtunnel import SSHTunnelForwarder

logging.getLogger("paramiko").setLevel(logging.WARNING)
logging.getLogger("sshtunnel").setLevel(logging.ERROR)

_ENV_PATH = Path(__file__).resolve().parent / ".env"
_SECRET_KEYS = (
    "ENABLE_SSH_TUNNEL",
    "AI_SSH_HOST",
    "AI_SSH_PORT",
    "AI_SSH_USER",
    "AI_SSH_PASSWORD",
    "AI_OPENCODE_REMOTE_PORT",
    "AI_LOCAL_TUNNEL_PORT",
    "OPENCODE_URL",
    "OPENCODE_PUBLIC_UI_BASE",
    "XCA_WORKSPACE_DIR",
    "AI_ASSISTANT_RULES_PATH",
)

_SSH_TUNNEL_STATE_KEY = "ssh_tunnel_forwarder"
_SSH_TUNNEL_LOCK = threading.Lock()
HEALTH_PATH = "/global/health"
_URL_CACHE_SECONDS = 3.0

DEFAULT_OPENCODE_URL = "http://127.0.0.1:4096"
ENABLE_SSH_TUNNEL = False
AI_SSH_HOST = ""
AI_SSH_PORT = 22
AI_SSH_USER = ""
AI_SSH_PASSWORD = ""
AI_OPENCODE_REMOTE_PORT = 4096
AI_LOCAL_TUNNEL_PORT = 0


def _cfg_bool(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _cfg_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        return int(raw)
    except ValueError:
        return default


def _hydrate_env() -> None:
    load_dotenv(dotenv_path=_ENV_PATH, override=True, encoding="utf-8-sig")
    try:
        secrets = st.secrets
        for key in _SECRET_KEYS:
            if key in secrets:
                os.environ.setdefault(key, str(secrets[key]))
        if "opencode" in secrets:
            nested = secrets["opencode"]
            for key in _SECRET_KEYS:
                if key in nested:
                    os.environ.setdefault(key, str(nested[key]))
    except Exception:
        pass


def _refresh_config() -> None:
    global DEFAULT_OPENCODE_URL, ENABLE_SSH_TUNNEL, AI_SSH_HOST, AI_SSH_PORT
    global AI_SSH_USER, AI_SSH_PASSWORD, AI_OPENCODE_REMOTE_PORT, AI_LOCAL_TUNNEL_PORT
    _hydrate_env()
    DEFAULT_OPENCODE_URL = os.getenv("OPENCODE_URL", "http://127.0.0.1:4096").rstrip("/")
    ENABLE_SSH_TUNNEL = _cfg_bool("ENABLE_SSH_TUNNEL")
    AI_SSH_HOST = os.getenv("AI_SSH_HOST", "").strip()
    AI_SSH_PORT = _cfg_int("AI_SSH_PORT", 22)
    AI_SSH_USER = os.getenv("AI_SSH_USER", "").strip()
    AI_SSH_PASSWORD = os.getenv("AI_SSH_PASSWORD", "").strip()
    AI_OPENCODE_REMOTE_PORT = _cfg_int("AI_OPENCODE_REMOTE_PORT", 4096)
    AI_LOCAL_TUNNEL_PORT = _cfg_int("AI_LOCAL_TUNNEL_PORT", 0)


_refresh_config()


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


def _probe_opencode_http(local_port: int) -> bool:
    try:
        response = requests.get(
            f"http://127.0.0.1:{local_port}{HEALTH_PATH}",
            timeout=(2.0, 4.0),
        )
        return response.status_code < 500
    except requests.RequestException:
        return False


def _is_ssh_transport_alive(forwarder: SSHTunnelForwarder) -> bool:
    transport = getattr(forwarder, "_transport", None)
    if transport is None:
        return True
    try:
        return bool(transport.is_active())
    except Exception:
        return False


def _is_ssh_tunnel_healthy(
    forwarder: SSHTunnelForwarder | None,
    *,
    skip_http_probe: bool = False,
) -> bool:
    if forwarder is None:
        return False
    if not bool(getattr(forwarder, "is_active", False)):
        return False
    if not _is_ssh_transport_alive(forwarder):
        return False
    local_port = int(getattr(forwarder, "local_bind_port", 0) or 0)
    if local_port <= 0:
        return False
    if skip_http_probe:
        return True
    now = time.time()
    last_probe = float(st.session_state.get("_ssh_http_probe_at", 0.0))
    if now - last_probe < _URL_CACHE_SECONDS:
        return bool(st.session_state.get("_ssh_http_probe_ok", False))
    ok = _probe_opencode_http(local_port)
    st.session_state._ssh_http_probe_at = now
    st.session_state._ssh_http_probe_ok = ok
    return ok


def stop_ssh_tunnel() -> None:
    with _SSH_TUNNEL_LOCK:
        forwarder: SSHTunnelForwarder | None = st.session_state.pop(_SSH_TUNNEL_STATE_KEY, None)
        if forwarder is None:
            st.session_state.runtime_opencode_url = ""
            return
        try:
            forwarder.stop()
            add_connection_log("SSH tunnel: stopped", "session reset")
        except Exception as exc:
            add_connection_log("SSH tunnel: stop error", str(exc))
        st.session_state.runtime_opencode_url = ""


def _create_ssh_tunnel() -> SSHTunnelForwarder:
    if not ENABLE_SSH_TUNNEL:
        raise RuntimeError("ENABLE_SSH_TUNNEL=false")
    missing = [
        name
        for name, value in {
            "AI_SSH_HOST": AI_SSH_HOST,
            "AI_SSH_USER": AI_SSH_USER,
            "AI_SSH_PASSWORD": AI_SSH_PASSWORD,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

    add_connection_log(
        "SSH tunnel: connecting",
        f"{AI_SSH_USER}@{AI_SSH_HOST}:{AI_SSH_PORT} -> 127.0.0.1:{AI_OPENCODE_REMOTE_PORT}",
    )
    local_candidates = [AI_LOCAL_TUNNEL_PORT] if AI_LOCAL_TUNNEL_PORT > 0 else []
    local_candidates.append(0)
    last_exc: Exception | None = None
    for local_port in local_candidates:
        forwarder = SSHTunnelForwarder(
            ssh_address_or_host=(AI_SSH_HOST, AI_SSH_PORT),
            ssh_username=AI_SSH_USER,
            ssh_password=AI_SSH_PASSWORD,
            remote_bind_address=("127.0.0.1", AI_OPENCODE_REMOTE_PORT),
            local_bind_address=("127.0.0.1", local_port),
            set_keepalive=30.0,
        )
        try:
            forwarder.start()
        except Exception as exc:
            last_exc = exc
            if local_port != 0:
                add_connection_log("SSH tunnel: fixed port busy, retry dynamic", str(exc))
                continue
            if "DSSKey" in str(exc):
                add_connection_log("SSH dependency error", "install paramiko<4")
            add_connection_log("SSH tunnel: failed", str(exc))
            raise
        if not _is_ssh_tunnel_healthy(forwarder):
            try:
                forwarder.stop()
            except Exception:
                pass
            last_exc = RuntimeError("Tunnel up but OpenCode health check failed on server")
            if local_port != 0:
                add_connection_log("SSH tunnel: health failed on fixed port, retry dynamic", "")
                continue
            raise last_exc
        add_connection_log(
            "SSH tunnel: connected",
            f"local 127.0.0.1:{forwarder.local_bind_port}",
        )
        return forwarder
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Failed to open SSH tunnel")


def ensure_ssh_tunnel(*, force_reconnect: bool = False) -> SSHTunnelForwarder:
    with _SSH_TUNNEL_LOCK:
        forwarder: SSHTunnelForwarder | None = st.session_state.get(_SSH_TUNNEL_STATE_KEY)
        if not force_reconnect and _is_ssh_tunnel_healthy(forwarder):
            return forwarder
        stale = st.session_state.pop(_SSH_TUNNEL_STATE_KEY, None)
        if stale is not None:
            try:
                stale.stop()
            except Exception:
                pass
        forwarder = _create_ssh_tunnel()
        st.session_state[_SSH_TUNNEL_STATE_KEY] = forwarder
        return forwarder


def resolve_opencode_url(*, force: bool = False) -> str:
    if not ENABLE_SSH_TUNNEL:
        url = DEFAULT_OPENCODE_URL
        st.session_state.runtime_opencode_url = url
        return url

    now = time.time()
    cached = str(st.session_state.get("runtime_opencode_url", "")).strip()
    resolved_at = float(st.session_state.get("_opencode_url_resolved_at", 0.0))
    if not force and cached and now - resolved_at < _URL_CACHE_SECONDS:
        forwarder = st.session_state.get(_SSH_TUNNEL_STATE_KEY)
        if _is_ssh_tunnel_healthy(forwarder, skip_http_probe=True):
            return cached

    tunnel = ensure_ssh_tunnel(force_reconnect=force)
    url = f"http://127.0.0.1:{tunnel.local_bind_port}"
    st.session_state.runtime_opencode_url = url
    st.session_state._opencode_url_resolved_at = now
    return url


def get_opencode_base_url() -> str:
    if ENABLE_SSH_TUNNEL:
        forwarder: SSHTunnelForwarder | None = st.session_state.get(_SSH_TUNNEL_STATE_KEY)
        if forwarder is not None and bool(getattr(forwarder, "is_active", False)):
            port = int(getattr(forwarder, "local_bind_port", 0) or AI_LOCAL_TUNNEL_PORT or 4096)
            return f"http://127.0.0.1:{port}"
        cached = str(st.session_state.get("runtime_opencode_url", "")).strip()
        if cached:
            return cached
        if AI_LOCAL_TUNNEL_PORT > 0:
            return f"http://127.0.0.1:{AI_LOCAL_TUNNEL_PORT}"
        return DEFAULT_OPENCODE_URL
    return DEFAULT_OPENCODE_URL


def get_opencode_browser_url() -> str:
    from opencode_ui_url import build_xca_ui_url, normalize_opencode_browser_url

    public_base = os.getenv("OPENCODE_PUBLIC_UI_BASE", "").strip()
    if public_base:
        return normalize_opencode_browser_url(build_xca_ui_url(public_base))
    return normalize_opencode_browser_url(build_xca_ui_url(get_opencode_base_url()))


def check_opencode_health(opencode_url: str) -> tuple[bool, str]:
    try:
        response = requests.get(f"{opencode_url}{HEALTH_PATH}", timeout=(2.0, 6.0))
        if response.status_code < 500:
            try:
                payload = response.json()
                version = str(payload.get("version", "")).strip()
            except ValueError:
                version = ""
            return True, version
        return False, f"HTTP {response.status_code}"
    except requests.RequestException as exc:
        return False, str(exc)


def bootstrap_backend() -> None:
    _refresh_config()
    init_tunnel_state()
    st.session_state.tunnel_error = ""
    if ENABLE_SSH_TUNNEL:
        try:
            if not str(st.session_state.get("runtime_opencode_url", "")).strip():
                resolve_opencode_url()
                add_connection_log("Backend URL resolved", st.session_state.runtime_opencode_url)
            else:
                resolve_opencode_url()
        except Exception as exc:
            st.session_state.runtime_opencode_url = ""
            st.session_state.tunnel_error = f"SSH tunnel error: {exc}"
            add_connection_log("Backend URL resolve failed", str(exc))
            st.session_state.opencode_health_ok = False
            return
    elif not st.session_state.runtime_opencode_url:
        st.session_state.runtime_opencode_url = DEFAULT_OPENCODE_URL

    ok, detail = check_opencode_health(get_opencode_base_url())
    st.session_state.opencode_health_ok = ok
    st.session_state.opencode_version = detail if ok else ""
    if not ok and not st.session_state.tunnel_error:
        st.session_state.tunnel_error = detail
    if ok:
        st.session_state.tunnel_error = ""
        add_connection_log("OpenCode health", "ok")


def init_tunnel_state() -> None:
    if "runtime_opencode_url" not in st.session_state:
        st.session_state.runtime_opencode_url = ""
    if "opencode_health_ok" not in st.session_state:
        st.session_state.opencode_health_ok = False
    if "opencode_version" not in st.session_state:
        st.session_state.opencode_version = ""
    if "tunnel_error" not in st.session_state:
        st.session_state.tunnel_error = ""
    if "connection_logs" not in st.session_state:
        st.session_state.connection_logs = []
