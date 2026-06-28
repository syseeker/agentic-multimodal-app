#!/usr/bin/env bash
# Phase 5 — VSS LVS profile deployment script
# Runs on the CPU Brev instance (no local GPU — remote-all mode)
# See PHASE5_VSS.md for full context and gotchas.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXTERNAL="$REPO_ROOT/external/video-search-and-summarization"
VSS_DOCKER="$EXTERNAL/deploy/docker"
ENV_GEN="$VSS_DOCKER/developer-profiles/dev-profile-lvs/generated.env"
VSS_DATA_DIR="/home/ubuntu/vss-data"

# ── 1. Clone blueprint if not present ────────────────────────────────────────
if [ ! -d "$EXTERNAL" ]; then
  git clone --branch v3.2.0 \
    https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization \
    "$EXTERNAL"
fi

# ── 2. Data directories ───────────────────────────────────────────────────────
mkdir -p "$VSS_DATA_DIR/data_log/"{analytics_cache,calibration_toolkit,elastic/{data,logs},kafka,redis/{data,log}}
mkdir -p "$VSS_DATA_DIR/agent_eval/"{dataset,results}
chmod -R 777 "$VSS_DATA_DIR/data_log" "$VSS_DATA_DIR/agent_eval"

# ── 3. Regenerate resolved.yml (idempotent) ───────────────────────────────────
cd "$VSS_DOCKER"
docker compose --env-file "$ENV_GEN" config 2>/dev/null > resolved.yml
export PATH="$HOME/.local/bin:$PATH"
uv run normalize_resolved_yml.py resolved.yml

# ── 4. Patch resolved.yml — strip GPU requirements for remote-all mode ────────
python3 - <<'EOF'
import yaml
path = 'resolved.yml'
with open(path) as f:
    c = yaml.safe_load(f)
for svc in ['rtvi-vlm', 'sensor-ms', 'streamprocessing-ms']:
    if svc in c.get('services', {}):
        c['services'][svc].pop('runtime', None)
        c['services'][svc].get('deploy', {}).get('resources', {}).get('reservations', {}).pop('devices', None)
with open(path, 'w') as f:
    yaml.dump(c, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
print("resolved.yml patched — GPU requirements removed")
EOF

# ── 5. Stop conflicting containers (VSS owns ES + Redis) ─────────────────────
for c in elasticsearch compose-redis-1; do
  if docker ps -q --filter "name=^/$c$" | grep -q .; then
    docker stop "$c" && docker rm "$c"
    echo "Removed conflicting container: $c"
  fi
done

# ── 6. Deploy ─────────────────────────────────────────────────────────────────
docker compose -f resolved.yml --env-file "$ENV_GEN" -p mdx up -d

# ── 7. Wait for vss-agent health ──────────────────────────────────────────────
echo "Waiting for vss-agent..."
for i in $(seq 1 60); do
  if curl -sf http://localhost:8000/health | grep -q '"isAlive":true'; then
    echo "✅ vss-agent healthy"
    break
  fi
  sleep 5
done

echo ""
echo "Container status:"
docker ps --filter "label=com.docker.compose.project=mdx" \
  --format "{{.Names}}\t{{.Status}}" | sort

echo ""
echo "⚠️  rtvi-vlm and vss-lvs require a GPU instance (RTX PRO 6000 Blackwell)."
echo "   Set RTVI_VLM_URL=http://<GPU_IP>:8018 in generated.env once GPU is available."
