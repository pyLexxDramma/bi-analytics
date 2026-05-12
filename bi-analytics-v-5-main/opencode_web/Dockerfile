FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    bash \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Node.js 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs

# Создаём пользователя
RUN useradd -m -s /bin/bash appuser \
    && echo "appuser ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/appuser \
    && chmod 0440 /etc/sudoers.d/appuser

USER appuser
WORKDIR /home/appuser

# Устанавливаем OpenCode (официальный скрипт)
RUN curl -fsSL https://opencode.ai/install | bash

# Добавляем opencode в PATH
ENV PATH="/home/appuser/.opencode/bin:$PATH"

# Копируем файлы веба
COPY --chown=appuser:appuser package.json server.js ./
COPY --chown=appuser:appuser public/ ./public/

# Устанавливаем зависимости Node
RUN npm install

# Копируем entrypoint
COPY --chown=appuser:appuser entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 4096 4098

ENTRYPOINT ["./entrypoint.sh"]