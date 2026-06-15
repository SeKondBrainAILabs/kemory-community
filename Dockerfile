# syntax=docker/dockerfile:1.6

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# P2 #15: pyproject.toml is the single source of truth for deps.
# Two-step install — first deps via pip from pyproject, then app code.
# `--no-deps` on the second step prevents re-resolving (already done).
COPY pyproject.toml README.md ./
COPY backend/ ./backend/
COPY kemory/ ./kemory/
COPY kemory_cli/ ./kemory_cli/
COPY scripts/ ./scripts/
# INSTALL_LOCAL_EMBEDDINGS controls whether the in-process FastEmbed/ONNX
# model is baked in. Community Docker sets this true so the stack has no
# external embedding service dependency.
ARG INSTALL_LOCAL_EMBEDDINGS=false
RUN <<'EOF'
set -eu
pip install --upgrade pip

if [ "$INSTALL_LOCAL_EMBEDDINGS" = "true" ]; then
    echo "Installing WITH local-embeddings extra (FastEmbed/ONNX model)"
    pip install --no-cache-dir '.[backend,platform,local-embeddings]'
else
    echo "Installing slim (no in-process model; uses core-embedding-service)"
    pip install --no-cache-dir '.[backend,platform]'
fi
EOF
# Alembic config lives at the project root; init_db() runs `alembic upgrade head`
# on startup in platform mode (S9N-3073) and needs this file to be present.
# Without it, migrations 002 (MV2 unified schema) through 005 (hybrid vector
# search) silently fail to apply and the API 500s on /api/v1/namespaces.
COPY alembic.ini ./alembic.ini
# prompts/ ships the versioned kemory_brief read by brief_service at pair
# claim and via MCP prompts/get. Without it the claim endpoint 500s on
# FileNotFoundError — see the pair-flow incident on 2026-05-16.
COPY prompts/ ./prompts/

# Set Python path
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Health check
# P1 #7: probe /health/ready, not /health/live. Liveness asks "is the
# process alive"; readiness asks "is the service ready to accept traffic"
# — i.e., DB + Redis reachable, migrations applied. Probing /live here
# would say "healthy" while the first request 500s on a cold DB pool.
# k8s manifests already split readinessProbe (=/health/ready) from
# livenessProbe (=/health/live); aligning the Docker HEALTHCHECK keeps
# `docker ps` consistent with what the orchestrator sees.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/ready || exit 1

# Run the application.
# WORKERS defaults to 2 (sane for a 2-vCPU pod). At deploy time set
# WORKERS=$((2 * $(nproc))) to scale with host cores. Single-process
# (WORKERS=1) was the old default — see codebase review P0 #3.
ENV WORKERS=2
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers ${WORKERS}"]
