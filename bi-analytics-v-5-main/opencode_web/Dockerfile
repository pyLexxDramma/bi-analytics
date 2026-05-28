FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git bash python3 python3-pip python3-venv \
  && ln -sf /usr/bin/python3 /usr/bin/python \
  && python3 -m venv /opt/pytools \
  && /opt/pytools/bin/pip install --no-cache-dir --upgrade pip \
  && /opt/pytools/bin/pip install --no-cache-dir pandas matplotlib \
  && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://opencode.ai/install | bash \
  && opencode upgrade 2>/dev/null || true

ENV PATH="/root/.opencode/bin:/opt/pytools/bin:${PATH}"
ENV OPENCODE_PORT=4096
ENV OPENCODE_HOST=127.0.0.1
ENV XCA_WORKSPACE_DIR=/workspace
ENV OPENCODE_CONFIG=/workspace/opencode.json
ENV OPENCODE_DISABLE_DEFAULT_PLUGINS=true

RUN mkdir -p /workspace /var/log

COPY scripts/render_opencode_config.sh /usr/local/bin/render_opencode_config.sh
COPY opencode_entrypoint.sh /usr/local/bin/opencode_entrypoint.sh
COPY scripts/ensure_web_data_db.sh /usr/local/bin/ensure_web_data_db.sh
COPY scripts/diagnose_ai_session.sh /usr/local/bin/diagnose_ai_session.sh
COPY scripts/verify_local_llm.sh /usr/local/bin/verify_local_llm.sh
COPY scripts/redeploy.sh /usr/local/bin/redeploy.sh
COPY scripts/verify_ui_http.sh /usr/local/bin/verify_ui_http.sh
COPY scripts/encode_workspace_slug.sh /usr/local/bin/encode_workspace_slug.sh
COPY scripts/verify_effective_agent.sh /usr/local/bin/verify_effective_agent.sh
COPY scripts/diagnose_duplicate_messages.sh /usr/local/bin/diagnose_duplicate_messages.sh
RUN chmod +x /usr/local/bin/render_opencode_config.sh \
    /usr/local/bin/opencode_entrypoint.sh \
    /usr/local/bin/ensure_web_data_db.sh \
    /usr/local/bin/diagnose_ai_session.sh \
    /usr/local/bin/verify_local_llm.sh \
    /usr/local/bin/redeploy.sh \
    /usr/local/bin/verify_ui_http.sh \
    /usr/local/bin/encode_workspace_slug.sh \
    /usr/local/bin/verify_effective_agent.sh \
    /usr/local/bin/diagnose_duplicate_messages.sh

WORKDIR /workspace
COPY workspace /workspace
COPY AI_ASSISTANT_RULES.md /workspace/AI_ASSISTANT_RULES.md

EXPOSE 4096

CMD ["bash", "-lc", "opencode_entrypoint.sh"]
