#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# vQA — Container Entrypoint
# ──────────────────────────────────────────────────────────────────
#
# Renders docker/supervisord.conf.template → /etc/supervisor/conf.d/vqa.conf
# by expanding per-session display slot stanzas for N=1..MAX_CONCURRENT_SESSIONS.
#
# Architecture Notes (ADR-15):
#   Templated supervisord.conf keeps MAX_CONCURRENT_SESSIONS as the single
#   source of truth for slot count.  Hand-maintaining a 24-block static file
#   would be error-prone and inflexible.
#
# Port formula:
#   Xvfb display : N
#   x11vnc rfbport : 5900 + N
#   websockify port : 6080 + N   (slot 1 → port 6081)
#
# Usage (Dockerfile CMD):
#   CMD ["/app/docker/entrypoint.sh"]
#
# Environment variables read:
#   MAX_CONCURRENT_SESSIONS  (default: 4)
#   VQA_NGINX_MAP_PATH       (default: /var/run/vqa/sessions.map)
# ──────────────────────────────────────────────────────────────────

set -euo pipefail

MAX_CONCURRENT_SESSIONS="${MAX_CONCURRENT_SESSIONS:-4}"
TEMPLATE_PATH="/app/docker/supervisord.conf.template"
OUTPUT_PATH="/etc/supervisor/conf.d/vqa.conf"
MAP_DIR="${VQA_NGINX_MAP_PATH:-/var/run/vqa/sessions.map}"
MAP_DIR="$(dirname "${MAP_DIR}")"

echo "[entrypoint] MAX_CONCURRENT_SESSIONS=${MAX_CONCURRENT_SESSIONS}"

# ──────────────────────────────────────────────────────────────────
# Ensure runtime directories exist
# ──────────────────────────────────────────────────────────────────
mkdir -p "${MAP_DIR}"

# ──────────────────────────────────────────────────────────────────
# Generate per-session slot stanzas
# ──────────────────────────────────────────────────────────────────
SLOT_PROGRAMS=""

for N in $(seq 1 "${MAX_CONCURRENT_SESSIONS}"); do
    VNC_PORT=$((6080 + N))
    RFB_PORT=$((5900 + N))
    SLOT_PROGRAMS="${SLOT_PROGRAMS}
[program:xvfb_${N}]
command=/usr/bin/Xvfb :${N} -screen 0 1920x1080x24 +extension GLX
priority=100
autostart=false
autorestart=false
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
startsecs=2

[program:x11vnc_${N}]
command=/usr/bin/x11vnc -display :${N} -nopw -forever -shared -rfbport ${RFB_PORT}
priority=101
autostart=false
autorestart=false
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
startsecs=2
environment=DISPLAY=\":${N}\"

[program:websockify_${N}]
command=/usr/bin/websockify --web=/usr/share/novnc/ ${VNC_PORT} localhost:${RFB_PORT}
priority=102
autostart=false
autorestart=false
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
startsecs=2
"
done

# ──────────────────────────────────────────────────────────────────
# Render the template: replace {{SESSION_SLOT_PROGRAMS}} placeholder
# ──────────────────────────────────────────────────────────────────
if [ ! -f "${TEMPLATE_PATH}" ]; then
    echo "[entrypoint] WARNING: template not found at ${TEMPLATE_PATH} — using existing conf"
else
    # Use Python for reliable multi-line replacement (avoids sed escaping issues)
    python3 - <<'PYEOF'
import os, sys

template_path = "/app/docker/supervisord.conf.template"
output_path = "/etc/supervisor/conf.d/vqa.conf"
slot_programs = os.environ.get("_VQA_SLOT_PROGRAMS", "")

with open(template_path) as f:
    content = f.read()

# Replace the placeholder comment block with the generated slot stanzas
content = content.replace("; {{SESSION_SLOT_PROGRAMS}}", slot_programs)

os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, "w") as f:
    f.write(content)

print(f"[entrypoint] Rendered {template_path} → {output_path}", file=sys.stderr)
PYEOF
fi

export _VQA_SLOT_PROGRAMS="${SLOT_PROGRAMS}"

echo "[entrypoint] Launching supervisord..."
exec /usr/bin/supervisord -c "${OUTPUT_PATH}"
