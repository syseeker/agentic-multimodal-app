#!/usr/bin/env bash
# Phase 8 — Case Workbench deploy script
# Run from repo root: bash deploy/phase8_workbench.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Phase 8: Case Workbench ==="

# 1. Build Docker image (includes Svelte npm build via node:20 stage)
echo "[1/4] Building workbench Docker image (npm build inside container)..."
docker compose -p amms -f deploy/compose.workbench.yaml build workbench
echo "      Image: amms-workbench:latest"

# 2. Start workbench container
echo "[2/4] Starting workbench container..."
docker compose -p amms -f deploy/compose.workbench.yaml up -d
echo "      Container: amms-workbench"

# 3. Wait for health
echo "[3/4] Waiting for workbench to be ready..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8200/api/health &>/dev/null; then
    echo "      Healthy after ~${i}s"
    break
  fi
  sleep 3
done

# 4. Verify
echo "[4/4] Verification:"
HEALTH=$(curl -sf http://localhost:8200/api/health 2>/dev/null || echo '{}')
echo "      /api/health → $HEALTH"
CASES=$(curl -sf http://localhost:8200/api/cases 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{len(d)} cases')" 2>/dev/null || echo "error")
echo "      /api/cases  → $CASES"

echo ""
echo "=== Workbench ready ==="
echo "  API:      http://localhost:8200/api"
echo "  API docs: http://localhost:8200/api/docs"
if [ -d "$REPO_ROOT/ui/dist" ]; then
  echo "  UI:       http://localhost:8200  (built SPA)"
else
  echo "  UI dev:   cd ui && npm run dev  → http://localhost:5173"
fi
