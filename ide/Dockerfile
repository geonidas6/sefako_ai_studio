FROM ghcr.io/coder/code-server:latest

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      openssh-client \
      nodejs \
      npm \
    && npm install -g @openai/codex opencode-ai@1.17.9 \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

ENV SHELL=/bin/bash
ENV PATH=/usr/local/bin:${PATH}

RUN mkdir -p /projects \
    && chown -R coder:coder /projects

USER coder

WORKDIR /projects

CMD ["--bind-addr", "0.0.0.0:8080", "--auth", "password", "/projects"]
