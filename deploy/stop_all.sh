#!/usr/bin/env bash
# Stop and fully clean every stack this project deploys, so the phase chain can be
# re-run from a known-empty state. Follows the shutdown/teardown procedures in:
#   ~/skills/skills/aiq-deploy/references/shutdown.md
#   ~/skills/skills/rag-blueprint/references/shutdown.md
#   ~/skills/skills/vss-deploy-profile/references/teardown.md
#
# WARNING — destructive. Removes containers AND named volumes (-v):
#   - Postgres job history (AI-Q)
#   - Elasticsearch + SeaweedFS ingested documents (RAG blueprint)
#   - VSS's on-disk data dir AND model/NIM weight caches (dev-profile.sh's own
#     teardown has no cache-preserving mode — this is what phase5_vss.sh's `up`
#     already runs internally before every deploy, exposed here standalone).
#     Expect a multi-GB re-download and the "up to 30 min first boot" wait on the
#     next `phase5_vss.sh` run.
set -uo pipefail  # not -e: keep going even if a stack was never started

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARCH="$(uname -m)"

echo "=== Stopping RAG Blueprint (rag-server, ingestor-server, nv-ingest, redis, vectordb) ==="
RAG_DIR="${REPO_ROOT}/external/rag"
if [ -d "$RAG_DIR" ]; then
  cd "$RAG_DIR"
  # Mirror phase2_rag.sh's arch-conditional override files so `down` resolves the
  # same merged config that `up` used (Cross-Arch Rule — see .claude/CLAUDE.md).
  ING_OVR=(); SRV_OVR=()
  if [ "$ARCH" = aarch64 ]; then
    export TAG=2.6.0-arm64
    ING_OVR=(-f "${REPO_ROOT}/deploy/compose.ingestor.arm64.override.yaml")
    SRV_OVR=(-f "${REPO_ROOT}/deploy/compose.rag-server.arm64.override.yaml")
  else
    ING_OVR=(-f "${REPO_ROOT}/deploy/compose.ingestor.override.yaml")
  fi
  docker compose -f deploy/compose/docker-compose-rag-server.yaml "${SRV_OVR[@]}" down -v --remove-orphans
  docker compose -f deploy/compose/docker-compose-ingestor-server.yaml "${ING_OVR[@]}" down -v --remove-orphans
  docker compose -f deploy/compose/vectordb.yaml down -v --remove-orphans
else
  echo "  (external/rag not present — skipping)"
fi

echo ""
echo "=== Stopping VSS (mdx project — containers, network, ALL volumes incl. model caches) ==="
VSS_DIR="${REPO_ROOT}/external/vss-3.2.0"
if [ -d "$VSS_DIR" ]; then
  ( cd "$VSS_DIR" && deploy/docker/scripts/dev-profile.sh down )
else
  echo "  (external/vss-3.2.0 not present — skipping)"
fi

echo ""
echo "=== Stopping AI-Q (amms-aiq-agent, amms-aiq-postgres) ==="
AIQ_DIR="${REPO_ROOT}/external/aiq"
if [ -d "$AIQ_DIR" ]; then
  cd "$AIQ_DIR/deploy/compose"
  docker compose -p amms --env-file ../.env -f docker-compose.yaml \
    -f "${REPO_ROOT}/deploy/compose.amms.override.yaml" down -v --remove-orphans
else
  echo "  (external/aiq not present — skipping)"
fi

echo ""
echo "=== Sweeping dangling volumes left by any of the above ==="
dangling=$(docker volume ls -q -f dangling=true)
[ -n "$dangling" ] && echo "$dangling" | xargs docker volume rm || echo "  (none)"

echo ""
echo "=== Remaining containers (expect empty, or only unrelated ones) ==="
docker ps -a --format 'table {{.Names}}\t{{.Status}}'
echo ""
echo "=== Clean. Re-run the phase chain from phase1_aiq.sh to redeploy from scratch. ==="
