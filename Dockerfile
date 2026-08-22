# syntax=docker/dockerfile:1.6

FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY backend/ ./backend/
COPY kemory/ ./kemory/
COPY kemory_cli/ ./kemory_cli/
COPY scripts/ ./scripts/

ARG INSTALL_LOCAL_EMBEDDINGS=false
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    if [ "$INSTALL_LOCAL_EMBEDDINGS" = "true" ]; then \
        /opt/venv/bin/pip install --no-cache-dir '.[backend,platform,local-embeddings,cli]'; \
    else \
        /opt/venv/bin/pip install --no-cache-dir '.[backend,platform,cli]'; \
    fi

FROM python:3.11-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 kemory \
    && useradd --system --create-home --uid 1001 --gid 1001 kemory \
    && mkdir -p /app/.community \
    && chown 1001:1001 /app/.community

COPY --from=builder /opt/venv /opt/venv
COPY backend/ ./backend/
COPY kemory/ ./kemory/
COPY kemory_cli/ ./kemory_cli/
# Community administration utilities are documented for docker compose exec.
COPY scripts/ ./scripts/
COPY alembic.ini ./alembic.ini
COPY prompts/ ./prompts/

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

USER kemory

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/ready || exit 1

ENV WORKERS=2
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers ${WORKERS}"]
