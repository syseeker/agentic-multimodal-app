#!/usr/bin/env bash
# Phase 2 — deploy RAG Blueprint (NVIDIA-hosted NIMs, Elasticsearch) and wire it as
# AI-Q's FRAG substrate, into the harmonized "amms" stack. Idempotent.
#
# Skills (source of truth): rag-blueprint (deploy.md, deploy/docker-nvidia-hosted.md)
# + aiq-deploy/references/frag.md. Requires Phase 1 (amms-aiq-agent) already up.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAG_DIR="$ROOT/external/rag"
AIQ_DIR="$ROOT/external/aiq"
OVERRIDE="$ROOT/deploy/compose.amms.override.yaml"
RAG_REF="${RAG_REF:-v2.6.0}"
PROJECT="${COMPOSE_PROJECT_NAME:-amms}"
KEY="$(grep -E '^NVIDIA_API_KEY=.+' "$ROOT/.env" | tail -1 | cut -d= -f2-)"
[ -n "$KEY" ] || { echo "NVIDIA_API_KEY missing in $ROOT/.env"; exit 2; }

# 1. clone RAG-BP fresh (do not touch other projects) + checkout skill-matching tag
[ -d "$RAG_DIR/.git" ] || git clone https://github.com/NVIDIA-AI-Blueprints/rag.git "$RAG_DIR"
cd "$RAG_DIR"; git fetch --depth 1 origin tag "$RAG_REF" >/dev/null 2>&1 || true
git checkout "$RAG_REF" >/dev/null 2>&1 || true

# 2. [docker-nvidia-hosted.md] authenticate to nvcr.io for image pulls
echo "$KEY" | docker login nvcr.io -u '$oauthtoken' --password-stdin >/dev/null

# 3. [docker-nvidia-hosted.md] cloud env (nvdev.env references ${NGC_API_KEY})
export NGC_API_KEY="$KEY"
# shellcheck disable=SC1091
source deploy/compose/nvdev.env

# 4. bring up vectordb (Elasticsearch default) -> ingestor -> rag-server, project amms
docker compose -p "$PROJECT" -f deploy/compose/vectordb.yaml up -d
docker compose -p "$PROJECT" -f deploy/compose/docker-compose-ingestor-server.yaml up -d
docker compose -p "$PROJECT" -f deploy/compose/docker-compose-rag-server.yaml up -d

# 5. [docker-nvidia-hosted.md] health (dependency checks)
curl --retry 40 --retry-delay 3 --retry-all-errors -sf "http://localhost:8081/v1/health?check_dependencies=true" >/dev/null \
  && echo "rag-server=healthy" || { echo "rag-server NOT healthy"; exit 3; }
curl --retry 20 --retry-delay 3 --retry-all-errors -sf "http://localhost:8082/v1/health?check_dependencies=true" >/dev/null \
  && echo "ingestor=healthy" || { echo "ingestor NOT healthy"; exit 3; }

# 6. [frag.md/configs.md] wire AI-Q to FRAG: set config + RAG URLs, recreate, connect net
python3 - "$AIQ_DIR/deploy/.env" <<'PY'
import sys; from pathlib import Path
p=Path(sys.argv[1])
up={"BACKEND_CONFIG":"/app/configs/config_web_frag.yml",
    "RAG_SERVER_URL":"http://rag-server:8081","RAG_INGEST_URL":"http://ingestor-server:8082"}
lines=p.read_text().splitlines(); seen=set(); out=[]
for ln in lines:
    s=ln.strip()
    if s and not s.startswith("#") and "=" in s and s.split("=",1)[0].strip() in up:
        k=s.split("=",1)[0].strip(); out.append(f"{k}={up[k]}"); seen.add(k); continue
    out.append(ln)
for k,v in up.items():
    if k not in seen: out.append(f"{k}={v}")
p.write_text("\n".join(out)+"\n"); print("AI-Q .env set to FRAG")
PY
cd "$AIQ_DIR/deploy/compose"
BUILD_TARGET=release docker compose -p "$PROJECT" --env-file ../.env \
  -f docker-compose.yaml -f "$OVERRIDE" up -d aiq-agent
docker network connect nvidia-rag "${PROJECT}-aiq-agent" 2>/dev/null \
  && echo "connected ${PROJECT}-aiq-agent -> nvidia-rag" || echo "(network already connected)"

# 7. [frag.md/validation.md] validate
curl --retry 30 --retry-delay 3 --retry-all-errors -sf "http://localhost:${AIQ_PORT:-8100}/health" >/dev/null \
  && echo "aiq-agent=healthy (FRAG)" || { echo "aiq-agent NOT healthy"; exit 4; }
docker exec "${PROJECT}-aiq-agent" python3 -c "import urllib.request as u; \
print('rag-server', u.urlopen('http://rag-server:8081/v1/health',timeout=8).status); \
print('ingestor-server', u.urlopen('http://ingestor-server:8082/v1/health',timeout=8).status)"
echo "Phase 2 complete: RAG-BP (ES, hosted NIMs) wired as AI-Q FRAG."
