# Backend Dockerfile — multi-stage build
# Stage 1 (builder): compiles native Python extensions with build-essential
# Stage 2 (dev):     retains toolchain for dev containers (uv sync at startup)
# Stage 3 (runtime): clean image without compiler toolchain for production

# UV source image (override for restricted networks that cannot reach ghcr.io)
ARG UV_IMAGE=harbor.sensetime.com/infra/astral-sh/uv:0.7.20
FROM ${UV_IMAGE} AS uv-source

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM harbor.sensetime.com/infra/python:3.12-slim-bookworm AS builder

ARG NODE_MAJOR=22
ARG APT_MIRROR
ARG UV_INDEX_URL
# Optional extras (comma- or space-separated). Example:
#   docker build --build-arg UV_EXTRAS=postgres,knowledge,redis ...
ARG UV_EXTRAS

# Optionally override apt mirror for restricted networks (e.g. APT_MIRROR=mirrors.aliyun.com)
RUN if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list 2>/dev/null || true; \
    fi

# Install build tools + Node.js (build-essential needed for native Python extensions)
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    gnupg \
    ca-certificates \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install uv (source image overridable via UV_IMAGE build arg)
COPY --from=uv-source /uv /uvx /usr/local/bin/

# Set working directory
WORKDIR /app

# Copy backend source code
COPY backend ./backend
# Bake config at project root (not under backend/) so bind-mounting ./backend
# cannot hide it. Prefer local config.yaml when present; else use example so
# the image boots (config.yaml is gitignored and often absent in CI builds).
COPY config.example.yaml ./config.yaml
RUN --mount=type=bind,source=.,target=/context,ro \
    if [ -f /context/config.yaml ]; then cp /context/config.yaml ./config.yaml; fi
RUN cp ./config.yaml ./backend/config.yaml

# Install dependencies with cache mount.
# `redis` is always installed because Docker Compose defaults the stream bridge
# to Redis (DEER_FLOW_STREAM_BRIDGE_REDIS_URL); it is an optional extra elsewhere
# so slim non-Docker installs do not pull it.
# Split UV_EXTRAS on comma/space into repeated --extra flags (uv rejects "a,b").
RUN --mount=type=cache,target=/root/.cache/uv \
    sh -c 'cd backend && \
    set -f; \
    extras_flags=""; \
    for extra in $(printf "%s" "$UV_EXTRAS" | tr "," " "); do \
        case "$extra" in \
            [!A-Za-z]* | *[!A-Za-z0-9_-]*) \
                echo "UV_EXTRAS entry $extra is invalid (must match [A-Za-z][A-Za-z0-9_-]*)" >&2; \
                exit 1; \
                ;; \
        esac; \
        extras_flags="$extras_flags --extra $extra"; \
    done; \
    UV_INDEX_URL=${UV_INDEX_URL:-https://pypi.org/simple} uv sync --extra redis $extras_flags'

# UTF-8 locale prevents UnicodeEncodeError on Chinese/emoji content in minimal
# containers where locale configuration may be missing and the default encoding is not UTF-8.
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8
ENV DEER_FLOW_PROJECT_ROOT=/app
ENV DEER_FLOW_CONFIG_PATH=/app/config.yaml

# ── Stage 2: Dev ──────────────────────────────────────────────────────────────
# Retains compiler toolchain from builder so startup-time `uv sync` can build
# source distributions in development containers.
FROM builder AS dev

# Install Docker CLI (for DooD: allows starting sandbox containers via host Docker socket)
COPY --from=harbor.sensetime.com/infra/docker:cli /usr/local/bin/docker /usr/local/bin/docker

EXPOSE 8001

CMD ["sh", "-c", "cd backend && PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001"]

# ── Stage 3: Runtime ──────────────────────────────────────────────────────────
# Clean image without build-essential — reduces size (~200 MB) and attack surface.
FROM harbor.sensetime.com/infra/python:3.12-slim-bookworm

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8
ENV DEER_FLOW_PROJECT_ROOT=/app
ENV DEER_FLOW_CONFIG_PATH=/app/config.yaml

# Copy Node.js runtime from builder (provides npx for MCP servers)
COPY --from=builder /usr/bin/node /usr/bin/node
COPY --from=builder /usr/lib/node_modules /usr/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/bin/npx

# Install Docker CLI (for DooD: allows starting sandbox containers via host Docker socket)
COPY --from=harbor.sensetime.com/infra/docker:cli /usr/local/bin/docker /usr/local/bin/docker

# Install uv (source image overridable via UV_IMAGE build arg)
COPY --from=uv-source /uv /uvx /usr/local/bin/

# Set working directory
WORKDIR /app

# Copy backend with pre-built virtualenv + baked config from builder
COPY --from=builder /app/backend ./backend
COPY --from=builder /app/config.yaml ./config.yaml
RUN cp ./config.yaml ./backend/config.yaml

# Expose Gateway API port.
EXPOSE 8001

# Default command (can be overridden in docker-compose)
CMD ["sh", "-c", "cd backend && PYTHONPATH=. uv run --no-sync uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001"]
