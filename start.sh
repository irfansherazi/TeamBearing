#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# vQA — Local Startup Script
# ─────────────────────────────────────────────────────────────────
# Usage:
#   ./start.sh          # start backend + frontend
#   ./start.sh --stop   # stop all running vQA processes
# ─────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=5173
LOG_DIR="$SCRIPT_DIR/.logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
VENV="$SCRIPT_DIR/.venv/bin/activate"

# ── Colours ──────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

print_header() {
    echo ""
    echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}║   🔬 vQA — Autonomous Web Agent          ║${NC}"
    echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════╝${NC}"
    echo ""
}

# ── Stop mode ────────────────────────────────────────────────────
if [[ "${1:-}" == "--stop" ]]; then
    echo -e "${YELLOW}Stopping vQA processes...${NC}"
    pkill -f "uvicorn backend.main:app" 2>/dev/null && echo "  ✓ Backend stopped" || echo "  – Backend was not running"
    pkill -f "vite.*$FRONTEND_PORT\|npm run dev" 2>/dev/null && echo "  ✓ Frontend stopped" || echo "  – Frontend was not running"
    echo ""
    exit 0
fi

print_header

mkdir -p "$LOG_DIR"

# Truncate logs on each startup to prevent stale lines from
# accumulating across repeated start.sh runs (which caused
# the 8x duplicate log lines bug).
: > "$BACKEND_LOG"
: > "$FRONTEND_LOG"

# ── Check prerequisites ───────────────────────────────────────────
echo -e "${BOLD}Checking prerequisites...${NC}"

if [[ ! -f "$VENV" ]]; then
    echo -e "${RED}✗ Python venv not found at .venv/${NC}"
    echo "  Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r backend/requirements.txt"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Python venv found"

if [[ ! -d "$SCRIPT_DIR/frontend/node_modules" ]]; then
    echo -e "  ${YELLOW}⚠${NC} node_modules missing — running npm install..."
    cd "$SCRIPT_DIR/frontend" && npm install --silent
    echo -e "  ${GREEN}✓${NC} npm install complete"
fi
echo -e "  ${GREEN}✓${NC} Frontend dependencies ready"

# ── Kill any existing processes on those ports ────────────────────
lsof -ti ":$BACKEND_PORT" | xargs kill -9 2>/dev/null || true
lsof -ti ":$FRONTEND_PORT" | xargs kill -9 2>/dev/null || true

echo ""
echo -e "${BOLD}Starting services...${NC}"

# ── Load .env into shell environment ──────────────────────────────
# Pydantic loads .env for Settings fields, but secrets.py and other
# modules use os.getenv() directly.  Export all vars so they're visible.
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a  # auto-export all variables
    source "$SCRIPT_DIR/.env"
    set +a
    echo -e "  ${GREEN}✓${NC} Loaded .env (${SKIP_SSM:+SKIP_SSM=$SKIP_SSM}${SKIP_SSM:-SKIP_SSM not set})"
fi

# ── Backend ───────────────────────────────────────────────────────
(
    cd "$SCRIPT_DIR"
    source "$VENV"
    uvicorn backend.main:app \
        --host 0.0.0.0 \
        --port "$BACKEND_PORT" \
        --log-level info \
        >> "$BACKEND_LOG" 2>&1
) &
BACKEND_PID=$!

# Wait for backend to be ready
echo -ne "  Starting backend"
for i in {1..20}; do
    sleep 1
    echo -ne "."
    if curl -sf "http://localhost:$BACKEND_PORT/health" > /dev/null 2>&1; then
        break
    fi
    if ! kill -0 $BACKEND_PID 2>/dev/null; then
        echo ""
        echo -e "${RED}✗ Backend crashed. Check logs:${NC}"
        tail -20 "$BACKEND_LOG"
        exit 1
    fi
done
echo ""

# Check what the health endpoint says
HEALTH=$(curl -sf "http://localhost:$BACKEND_PORT/api/health/ready" 2>/dev/null || echo '{"status":"unknown"}')
JIRA_STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('checks',{}).get('jira','unknown'))" 2>/dev/null || echo "unknown")
S3_STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('checks',{}).get('s3','unknown'))" 2>/dev/null || echo "unknown")

echo -e "  ${GREEN}✓${NC} Backend running on http://localhost:$BACKEND_PORT"
if [[ "$JIRA_STATUS" == "connected" ]]; then
    echo -e "      Jira:   ${GREEN}connected${NC}"
else
    echo -e "      Jira:   ${YELLOW}$JIRA_STATUS${NC} (update /vQA/jira/api_token in SSM)"
fi
if [[ "$S3_STATUS" == "connected" ]]; then
    echo -e "      S3:     ${GREEN}connected${NC}"
else
    echo -e "      S3:     ${YELLOW}$S3_STATUS${NC}"
fi

# ── Frontend ──────────────────────────────────────────────────────
(
    cd "$SCRIPT_DIR/frontend"
    npm run dev >> "$FRONTEND_LOG" 2>&1
) &
FRONTEND_PID=$!

# Wait for frontend to be ready
echo -ne "  Starting frontend"
for i in {1..15}; do
    sleep 1
    echo -ne "."
    if grep -q "Local:" "$FRONTEND_LOG" 2>/dev/null; then
        break
    fi
done
echo ""
echo -e "  ${GREEN}✓${NC} Frontend running on http://localhost:$FRONTEND_PORT"

# ── Summary ───────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  vQA is ready!${NC}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}Dashboard:${NC}   http://localhost:$FRONTEND_PORT"
echo -e "  ${BOLD}API Docs:${NC}    http://localhost:$BACKEND_PORT/docs"
echo -e "  ${BOLD}Health:${NC}      http://localhost:$BACKEND_PORT/health"
echo ""
echo -e "  ${BOLD}Logs:${NC}"
echo -e "    Backend:   .logs/backend.log"
echo -e "    Frontend:  .logs/frontend.log"
echo ""
echo -e "  ${YELLOW}Press Ctrl+C to stop both services${NC}"
echo ""

# ── Wait and cleanup on exit ──────────────────────────────────────
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down vQA...${NC}"
    # Kill tail first to prevent further output during shutdown
    kill $TAIL_PID 2>/dev/null || true
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    # Kill child processes too
    pkill -f "uvicorn backend.main:app" 2>/dev/null || true
    pkill -P $FRONTEND_PID 2>/dev/null || true
    echo -e "${GREEN}✓ Stopped${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Keep script alive — tail both logs to show combined output
echo -e "${CYAN}── Live Logs ─────────────────────────────${NC}"
tail -f "$BACKEND_LOG" "$FRONTEND_LOG" 2>/dev/null &
TAIL_PID=$!

wait $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
kill $TAIL_PID 2>/dev/null || true
