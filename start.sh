#!/usr/bin/env bash
# DeerFlow 本地开发启动（无需 nginx）
#
# 用法:
#   ./start.sh                  # 启动 Gateway + Frontend
#   ./start.sh --skip-install   # 跳过依赖安装
#   ./start.sh --stop           # 停止服务
#
# 访问: http://localhost:3000
# API 由 Next.js 代理到 Gateway :8001

set -eo pipefail

REPO_ROOT="$(builtin cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
cd "$REPO_ROOT"

[ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] && {
    echo "Usage: $0 [--skip-install] [--stop]"
    echo "  → http://localhost:3000  (no nginx required)"
    exit 0
}

[ "${1:-}" = "--skip-install" ] && _skip_install=true || _skip_install=false

if [ "${1:-}" = "--stop" ]; then
    exec "$REPO_ROOT/scripts/serve.sh" --stop
fi

echo "DeerFlow (no nginx) → http://localhost:3000"
echo "Gateway API         → http://localhost:8001"
echo ""

# serve.sh always starts nginx; run gateway + frontend only.
if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
    set +a
fi

_kill_port() {
    local pid
    pid=$(lsof -ti :"$1" 2>/dev/null) || true
    [ -n "$pid" ] && kill -9 $pid 2>/dev/null || true
}

cleanup() {
    trap - INT TERM
    echo ""
    echo "Stopping..."
    pkill -f "uvicorn app.gateway.app:app" 2>/dev/null || true
    pkill -f "next dev" 2>/dev/null || true
    exit 0
}

if ! $_skip_install; then
    echo "Installing dependencies..."
    _extras=$(python3 "$REPO_ROOT/scripts/detect_uv_extras.py" 2>/dev/null || true)
    # shellcheck disable=SC2086
    (cd "$REPO_ROOT/backend" && uv sync --all-packages $_extras)
    (cd "$REPO_ROOT/frontend" && pnpm install --frozen-lockfile 2>/dev/null || pnpm install)
fi

mkdir -p "$REPO_ROOT/logs"
trap cleanup INT TERM

_kill_port 8001
_kill_port 3000

echo "Starting Gateway..."
(cd "$REPO_ROOT/backend" && PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload \
    > "$REPO_ROOT/logs/gateway.log" 2>&1) &
"$REPO_ROOT/scripts/wait-for-port.sh" 8001 30 Gateway || { tail -20 "$REPO_ROOT/logs/gateway.log"; exit 1; }

echo "Starting Frontend..."
(cd "$REPO_ROOT/frontend" && pnpm dev > "$REPO_ROOT/logs/frontend.log" 2>&1) &
"$REPO_ROOT/scripts/wait-for-port.sh" 3000 120 Frontend || { tail -20 "$REPO_ROOT/logs/frontend.log"; exit 1; }

echo ""
echo "✓ DeerFlow is running"
echo "  UI:  http://localhost:3000"
echo "  API: http://localhost:8001"
echo "  Logs: logs/{gateway,frontend}.log"
echo "  Stop: ./start.sh --stop"
echo ""
wait
