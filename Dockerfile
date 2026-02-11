# ==============================================================================
# Axnmihn AI Assistant Backend
# Multi-stage build: builder → runtime → research
# ==============================================================================

# --- Stage 1: Builder (compile deps + native C++ module) ---
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake g++ && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install Python dependencies
COPY backend/requirements.txt requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Build native C++ module (optional, speeds up decay/graph ops)
COPY backend/native/ native/
RUN pip install --no-cache-dir --prefix=/install ./native/ || \
    echo "WARN: Native module build failed, falling back to pure Python"

# --- Stage 2: Runtime (backend + mcp) ---
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 ffmpeg curl && \
    rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -r axnmihn && useradd -r -g axnmihn -m axnmihn

# Copy installed packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy source
COPY backend/ backend/
COPY pyproject.toml .

# Create runtime directories
RUN mkdir -p data/sqlite data/chroma_db data/tmp logs storage/research/inbox \
    storage/research/artifacts storage/cron/reports scripts && \
    chown -R axnmihn:axnmihn /app

USER axnmihn

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:${PORT}/health/quick || exit 1

CMD ["python", "-m", "backend.app"]

# --- Stage 3: Research (runtime + playwright + chromium) ---
FROM runtime AS research

USER root

RUN pip install --no-cache-dir playwright && \
    playwright install --with-deps chromium && \
    chown -R axnmihn:axnmihn /home/axnmihn

USER axnmihn

ENV PORT=8766

EXPOSE 8766

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:${PORT}/health || exit 1

CMD ["python", "-m", "backend.protocols.mcp.research_server", "sse", "8766"]
