# SSH tunnel setup for local Streamlit -> remote OpenCode

## 1) Configure `.env`

Set:

- `ENABLE_SSH_TUNNEL=true`
- `AI_SSH_HOST=<server_ip>`
- `AI_SSH_PORT=<ssh_port>`
- `AI_SSH_USER=<ssh_user>`
- `AI_SSH_PASSWORD=<ssh_password>`
- `AI_OPENCODE_REMOTE_PORT=<opencode_port_on_server>`
- `AI_LOCAL_TUNNEL_PORT=4096` (or another free local port)

## 2) How to find OpenCode port on server

Run on AI server:

```bash
ss -lntp | rg opencode
```

Or check compose/env values:

```bash
rg "OPENCODE_PORT|opencode serve|--port" docker-compose.yml Dockerfile* entrypoint.sh .env
```

Typical default is `4096`.

## 3) Start locally

```bash
pip install -r requirements.web.txt
streamlit run streamlit_app.py --server.port 8501
```

When `ENABLE_SSH_TUNNEL=true`, app auto-opens SSH tunnel and uses:

`http://127.0.0.1:<AI_LOCAL_TUNNEL_PORT>`

as OpenCode backend.
