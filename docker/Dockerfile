# ──────────────────────────────────────────────────────────────────
# vQA — Multi-Stage Dockerfile
# ──────────────────────────────────────────────────────────────────
#
# This Dockerfile builds the complete vQA container with:
#   - Python 3.12 runtime
#   - Playwright Chromium browser
#   - Xvfb virtual display (interactive mode)
#   - x11vnc + noVNC (live browser streaming)
#   - FastAPI backend (uvicorn)
#   - Supervisord process manager
#
# Build:
#   docker build -t vqa:latest -f docker/Dockerfile .
#
# Run (interactive mode):
#   docker compose -f docker/docker-compose.yml up
#
# Run (headless / CI mode):
#   docker compose -f docker/docker-compose.ci.yml up
# ──────────────────────────────────────────────────────────────────

# ═══════════════════════════════════════════════════════════════════
# Stage 1: Python dependencies
# ═══════════════════════════════════════════════════════════════════

FROM python:3.12-slim AS deps

WORKDIR /app

# Install system dependencies required by Playwright and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Playwright Chromium dependencies
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libxshmfence1 \
    # Interactive mode dependencies
    xvfb \
    x11vnc \
    supervisor \
    # noVNC for browser streaming
    novnc \
    websockify \
    # Utilities
    curl \
    gnupg \
    # ffmpeg: MP4 frame extraction for Jira video attachment analysis (TASK-122)
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22 LTS (required by npx playwright test and generateStorageStates.mjs)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Install Playwright Chromium browser
RUN playwright install chromium || playwright install chromium || playwright install chromium


# ═══════════════════════════════════════════════════════════════════
# Stage 2: Application
# ═══════════════════════════════════════════════════════════════════

FROM deps AS app

WORKDIR /app

# Copy application source code
COPY backend/ /app/backend/

# Copy Playwright test index + test files (needed by /api/playwright/tests endpoint).
# Storage states (pre-authenticated sessions for test accounts) are included in the image
# for ECS/Fargate compatibility. They contain test account cookies, NOT production credentials.
# If sessions expire, regenerate via POST /playwright/storage/generate.
COPY playwright/playwright_index.json /app/playwright/playwright_index.json
COPY playwright/tsconfig.json /app/playwright/tsconfig.json
COPY playwright/tests/ /app/playwright/tests/
COPY playwright/fixtures/ /app/playwright/fixtures/
COPY playwright/utils/ /app/playwright/utils/
COPY playwright/storage/ /app/playwright/storage/

# Copy root package.json and playwright.config.ts so `npx playwright test` works.
# playwright.config.ts must be at the project root; package.json provides @playwright/test.
COPY package.json package-lock.json /app/
COPY playwright.config.ts /app/playwright.config.ts

# Install Node.js dependencies (provides @playwright/test / npx playwright)
RUN npm ci --prefix /app

# Install Playwright Chromium for the Node.js @playwright/test package.
# npm ci may resolve a different @playwright/test patch than the Python Playwright
# pip install resolved, so the two browser revisions can diverge. Running
# playwright install here ensures the Node.js version's browser is always present.
RUN cd /app && npx playwright install chromium

# Copy supervisord configuration
COPY docker/supervisord.conf /etc/supervisor/conf.d/vqa.conf

# Create directories for runtime artifacts
# /app/recordings  — video recordings (mount a volume to persist across restarts)
# /app/screenshots — on-failure screenshots
# /tmp/vqa-videos  — transient working dir for in-progress recordings
# /app/playwright/test-results — Playwright trace + test output
RUN mkdir -p /app/recordings /app/screenshots /tmp/vqa-videos /app/playwright/test-results

# ── Open-file limit ───────────────────────────────────────────────
# Each parallel Chromium instance opens ~200 file descriptors.
# The Docker default (1024) is exhausted with 4+ browsers.
# Raise the limit via docker-compose ulimits or the ECS task definition:
#   ulimits:
#     nofile:
#       soft: 65536
#       hard: 65536

# ── Environment defaults ─────────────────────────────────────────
# These can be overridden via docker-compose.yml or -e flags.
# Secrets (passwords, tokens) should NEVER have defaults here.
#
# Parallel-execution knobs:
#   VQA_SUITE_WORKERS — max concurrent Playwright subprocess workers.
#     Formula: floor(available_memory_gb / 0.6).  Default=2 is safe for
#     a 3 GB container.  Increase with memory limits in the compose file.
#   VQA_HEADLESS — set to '1' for parallel runs.  Headed mode (0) shares
#     a single Xvfb display (:99) and is NOT safe for parallel execution.
#
# ── FARGATE / ECS NOTE ────────────────────────────────────────────
# docker-compose `shm_size` is IGNORED by ECS/Fargate.  Each Chromium
# tab uses /dev/shm for GPU memory; the kernel default is only 64 MB
# and causes crashes under parallel load.  Set shm_size in the ECS task
# definition via the `linuxParameters.sharedMemorySize` field (in MiB):
#   "linuxParameters": { "sharedMemorySize": 1024 }
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    VQA_MODE=interactive \
    API_PORT=8000 \
    NOVNC_PORT=6080 \
    LOG_LEVEL=INFO \
    DISPLAY=:99 \
    VQA_SUITE_WORKERS=2 \
    VQA_HEADLESS=0

# ── Expose ports ──────────────────────────────────────────────────
# 8000 = FastAPI backend
# 6080 = noVNC WebSocket proxy (interactive mode)
EXPOSE 8000 6080

# ── Health check ──────────────────────────────────────────────────
# Uses /health (liveness probe) — lightweight, no external calls.
# For deep connectivity checks, use /health/ready from load balancer.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ── Graceful shutdown ──────────────────────────────────────────────
# SIGTERM triggers uvicorn's graceful shutdown → lifespan teardown
# → _drain_all_managers → clean browser closure.
STOPSIGNAL SIGTERM

# ── Entrypoint ────────────────────────────────────────────────────
# Supervisord manages all processes:
#   - Xvfb (virtual display)
#   - x11vnc → websockify → noVNC (browser streaming)
#   - uvicorn (FastAPI backend)
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/vqa.conf"]
