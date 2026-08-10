#!/usr/bin/env bash
# Phase 3 — Data Simulation (sim-case-text)
# Deploys: data-designer install, generate, package, ingest into RAG Blueprint
# Proof: deploy/PHASE3_DATA_SIM.md
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Phase 3: Data Simulation (sim-case-text) ==="
echo "Repo root: $REPO_ROOT"

# ── 1. Load NVIDIA_API_KEY from root .env ─────────────────────────────────────
ENV_FILE="$REPO_ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env not found at $ENV_FILE"
    echo "Run propagate_env.sh first."
    exit 1
fi
# SECURITY: never print key value
NVIDIA_API_KEY_VALUE=$(grep '^NVIDIA_API_KEY=' "$ENV_FILE" | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]')
if [ -z "$NVIDIA_API_KEY_VALUE" ]; then
    echo "ERROR: NVIDIA_API_KEY not found or empty in .env"
    exit 1
fi
export NVIDIA_API_KEY="$NVIDIA_API_KEY_VALUE"
echo "✓ NVIDIA_API_KEY loaded (length=${#NVIDIA_API_KEY_VALUE})"
unset NVIDIA_API_KEY_VALUE

# ── 2. data-designer — ONLY needed to GENERATE cases from scratch. ────────────
# The 20 case folders' text is committed to the repo, so a normal quickstart just
# ingests them (Step 6). Skip data-designer entirely when cases already exist —
# this also sidesteps PEP 668 (Ubuntu 24.04 / Py3.12 refuses system `pip install`).
if find "$REPO_ROOT/data/cases" -maxdepth 1 -type d -name 'SC-*' 2>/dev/null | grep -q .; then
    echo "✓ Case folders already present — skipping data-designer install + generation."
else
    # No cases yet: install data-designer into a dedicated venv (PEP 668-safe; matches
    # the data-designer skill guidance to use a virtualenv), then generate below.
    DD_VENV="${DD_VENV:-$HOME/.venv-datadesigner}"
    export PATH="$DD_VENV/bin:$HOME/.local/bin:$PATH"
    if ! command -v data-designer &>/dev/null; then
        echo "Installing data-designer into $DD_VENV ..."
        [ -d "$DD_VENV" ] || python3 -m venv "$DD_VENV"
        "$DD_VENV/bin/pip" install --quiet --upgrade pip
        "$DD_VENV/bin/pip" install --quiet data-designer
    fi
    DATA_DESIGNER_VERSION=$(data-designer --version 2>/dev/null || echo "unknown")
    echo "✓ data-designer $DATA_DESIGNER_VERSION"

# ── 3. Verify model aliases are reachable ─────────────────────────────────────
echo "Checking model aliases..."
if ! data-designer agent state model-aliases 2>/dev/null | grep -q "nvidia-text"; then
    echo "ERROR: nvidia-text model alias not available."
    echo "Check: data-designer agent state model-aliases"
    exit 1
fi
echo "✓ nvidia-text alias available"

# ── 4. Generate synthetic forensic cases ─────────────────────────────────────
NUM_RECORDS="${NUM_RECORDS:-2}"
DATASET_NAME="forensic_cases_sg"
ARTIFACT_DIR="$REPO_ROOT/data/sim/artifacts"
PARQUET_PATH="$ARTIFACT_DIR/${DATASET_NAME}/parquet-files/batch_00000.parquet"

if [ -f "$PARQUET_PATH" ]; then
    echo "Parquet already exists at $PARQUET_PATH — skipping generation."
    echo "To regenerate: rm -rf $ARTIFACT_DIR/$DATASET_NAME && re-run this script."
else
    echo "Generating $NUM_RECORDS synthetic forensic cases..."
    data-designer create "$REPO_ROOT/data/sim/forensic_cases.py" \
        --num-records "$NUM_RECORDS" \
        --dataset-name "$DATASET_NAME" \
        --artifact-path "$ARTIFACT_DIR"
    echo "✓ Generation complete: $PARQUET_PATH"
fi

fi   # end of "generate cases only when none exist" guard (Step 2)

# ── 5. Package parquet into per-case folders ──────────────────────────────────
CASES_DIR="$REPO_ROOT/data/cases"
CASE_COUNT=$(ls -d "$CASES_DIR"/SC-*/ 2>/dev/null | wc -l || echo 0)

if [ "$CASE_COUNT" -gt 0 ]; then
    echo "Case folders already exist ($CASE_COUNT cases) — skipping packaging."
    echo "To repackage: rm -rf $CASES_DIR && re-run this script."
else
    echo "Packaging cases into $CASES_DIR/..."
    # pandas required for parquet read
    python3 -m pip install --user --quiet pandas pyarrow 2>/dev/null || true
    python3 "$REPO_ROOT/data/sim/parquet_to_cases.py"
    echo "✓ Case folders created"
fi

# ── 6. Ingest into RAG Blueprint ─────────────────────────────────────────────
INGESTOR_URL="${INGESTOR_URL:-http://localhost:8082}"
RAG_URL="${RAG_URL:-http://localhost:8081}"
COLLECTION="${COLLECTION:-multimodal_data}"

echo ""
echo "Ingesting case documents into RAG Blueprint ($INGESTOR_URL, collection=$COLLECTION)..."

# On aarch64 (GB10), VSS deploys Cosmos Reason2 locally (~94 GB unified memory).
# nv-ingest's Ray pipeline can't coexist with it — Ray OOM-kills its workers.
# Stop the VLM, restart nv-ingest so Ray initialises cleanly, then restore after ingest.
_VLM_CTR="nvidia-cosmos-reason2-8b"
_NV_INGEST_CTR_NAME="${NV_INGEST_CTR:-compose-nv-ingest-ms-runtime-1}"
_VLM_WAS_RUNNING=false
if [ "$(uname -m)" = aarch64 ] && docker ps -q --filter "name=^/${_VLM_CTR}$" | grep -q .; then
    echo "  aarch64: stopping ${_VLM_CTR} to free unified memory for nv-ingest Ray..."
    docker stop "$_VLM_CTR" >/dev/null
    _VLM_WAS_RUNNING=true
    echo "  restarting nv-ingest so Ray initialises with freed memory..."
    docker restart "$_NV_INGEST_CTR_NAME" >/dev/null
    echo -n "  waiting for nv-ingest to become healthy..."
    for _i in $(seq 1 30); do
        if docker inspect "$_NV_INGEST_CTR_NAME" --format '{{.State.Health.Status}}' 2>/dev/null | grep -q healthy; then
            echo " ready ✓"; break
        fi
        sleep 5; echo -n "."
    done
    echo ""
fi
# ── Prerequisite: verify VSS owns Elasticsearch before ingesting ──────────────
# QUICKSTART order is 1→2→5→3→4→6→7→8. Phase 5 deploys VSS which takes ownership
# of Elasticsearch (mdx project). If phase 3 runs before phase 5, documents land in
# RAG Blueprint's temporary ES — which phase 5 wipes on deploy. All ingest is lost.
# Detect this by checking whether the 'elasticsearch' container belongs to the mdx project.
ES_PROJECT=$(docker inspect elasticsearch --format '{{index .Config.Labels "com.docker.compose.project"}}' 2>/dev/null || echo "none")
if [ "$ES_PROJECT" = "mdx" ]; then
    echo "✓ Elasticsearch owned by VSS (mdx project) — correct"
elif [ "$ES_PROJECT" = "none" ]; then
    echo "WARNING: elasticsearch container not found — ingestor may use a different ES backend."
else
    echo ""
    echo "WARNING: elasticsearch is owned by project '${ES_PROJECT}', not 'mdx' (VSS)."
    echo "  Phase 5 (VSS) should run before Phase 3 — VSS takes ownership of Elasticsearch."
    echo "  If you proceed now, Phase 5 will wipe this ES index when it deploys and"
    echo "  you will need to re-run Phase 3. Recommended order: 1→2→5→3→4→6→7→8."
    echo ""
    read -r -p "  Proceed anyway? [y/N]: " _confirm
    case "$_confirm" in
        [yY]*) echo "  Proceeding (remember to re-run Phase 3 after Phase 5)." ;;
        *) echo "  Aborted. Run Phase 5 first: bash deploy/phase5_vss.sh"; exit 1 ;;
    esac
fi

# Health check — retry, don't fail on the first miss.
# phase5_vss.sh --force-recreate's ingestor-server right before this runs, so a cold
# check races its startup. A single attempt made a still-booting ingestor look dead.
echo -n "  Waiting for ingestor at ${INGESTOR_URL} (up to 150s)"
_ING_OK=false
for _i in $(seq 1 30); do
    if curl -sf "${INGESTOR_URL}/health" &>/dev/null; then _ING_OK=true; echo " up ✓"; break; fi
    sleep 5; echo -n "."
done
echo ""
if [ "$_ING_OK" != true ]; then
    echo "ERROR: RAG Blueprint ingestor not reachable at $INGESTOR_URL after 150s"
    echo "  Container state:"
    docker ps -a --filter name=ingestor-server --format '    {{.Names}}: {{.Status}} ({{.Image}})' 2>/dev/null || true
    echo "  If the image tag ends in -arm64 on an x86 host, phase5 pinned the wrong arch:"
    echo "    docker rm -f ingestor-server rag-server && bash deploy/phase2_rag.sh"
    echo "  Otherwise check: docker logs ingestor-server --tail 30"
    exit 1
fi
echo "✓ Ingestor health check passed"


# ── nv-ingest Redis connectivity check ────────────────────────────────────────
# After phase5, VSS replaces the RAG-owned redis container with its own.
# nv-ingest's compose file has MESSAGE_CLIENT_HOST=redis hardcoded (not a variable)
# so our reconnection env-var override is silently ignored — nv-ingest still tries
# to resolve hostname 'redis' on the nvidia-rag network, which no longer exists.
# Fix: patch /etc/hosts inside nv-ingest to make 'redis' resolve to the host eth0 IP
# (where VSS's Redis is listening on port 6379 with network_mode: host).
# This is idempotent — skipped if 'redis' already resolves correctly.
NV_INGEST_CTR="${NV_INGEST_CTR:-compose-nv-ingest-ms-runtime-1}"
if docker ps -q --filter "name=^/${NV_INGEST_CTR}$" | grep -q .; then
    # Use Python (always available in nv-ingest) to test Redis connectivity.
    # redis-cli is NOT installed in the nv-ingest container.
    _redis_ok() {
      docker exec "$NV_INGEST_CTR" python3 -c \
        "import socket,sys; s=socket.socket(); s.settimeout(3); s.connect(('redis',6379)); s.close(); print('OK')" \
        2>/dev/null | grep -q OK
    }
    if ! _redis_ok; then
        echo "  nv-ingest: 'redis' hostname unreachable — patching /etc/hosts..."
        # nv-ingest is on the nvidia-rag bridge network. Docker iptables may block
        # bridge→eth0 (10.148.0.x) routing. Try in order:
        #   1. Bridge gateway (172.19.0.1) — same subnet as nv-ingest, always reachable
        #   2. eth0 IP — fallback if bridge gateway doesn't have Redis
        BRIDGE_GW="$(docker network inspect nvidia-rag --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null)"
        ETH0_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')"
        REDIS_TARGET=""
        for _ip in "$BRIDGE_GW" "$ETH0_IP"; do
          [ -z "$_ip" ] && continue
          if docker exec "$NV_INGEST_CTR" python3 -c \
              "import socket,sys; s=socket.socket(); s.settimeout(3); s.connect(('${_ip}',6379)); s.close()" \
              2>/dev/null; then
            REDIS_TARGET="$_ip"; break
          fi
        done
        if [ -z "$REDIS_TARGET" ]; then
          echo "  WARNING: nv-ingest cannot reach Redis at any tried IP — ingestion may fail"
        else
          # sed -i fails on Docker's /etc/hosts bind mount — use cat > to overwrite in place.
          docker exec "$NV_INGEST_CTR" \
            sh -c "grep -v '[[:space:]]redis\$' /etc/hosts > /tmp/hosts.new && cat /tmp/hosts.new > /etc/hosts && echo '${REDIS_TARGET} redis' >> /etc/hosts"
          _redis_ok && echo "  ✓ nv-ingest now reaches Redis at ${REDIS_TARGET}:6379" || \
            echo "  WARNING: hosts patched to ${REDIS_TARGET} but socket test still failing"
        fi
    else
        echo "  ✓ nv-ingest Redis connectivity OK"
    fi
fi

# Ensure the target collection exists — the ingestor does NOT auto-create it, and
# POST /v1/documents fails with "Collection ... does not exist" otherwise. Idempotent.
#
# IMPORTANT (fresh-instance): use the SINGULAR /v1/collection (CreateCollectionRequest
# object body), NOT the array-form /v1/collections. On a fresh Elasticsearch, the
# array-form creates only the document index; it does NOT create the global
# `metadata_schema` index that the ingestor's get_metadata_schema() reads on EVERY
# ingest. Without it, every POST /v1/documents fails with:
#   NotFoundError(404, 'index_not_found_exception', 'no such index [metadata_schema]')
# The singular endpoint (with metadata_schema:[]) initializes that index. Idempotent.
echo "Ensuring collection '${COLLECTION}' exists (initializes metadata_schema index)..."
curl -sf -X POST "${INGESTOR_URL}/v1/collection" \
    -H 'Content-Type: application/json' \
    -d "{\"collection_name\":\"${COLLECTION}\",\"metadata_schema\":[]}" >/dev/null 2>&1 \
    && echo "✓ Collection '${COLLECTION}' ready (metadata_schema initialized)" \
    || echo "  (collection create returned non-zero — assuming it already exists)"

total_files=0
total_cases=0
failed=0

# CASE_LIMIT: max cases to ingest (default: all). Override inline:
#   CASE_LIMIT=5 bash deploy/phase3_data_sim.sh
CASE_LIMIT="${CASE_LIMIT:-0}"
[ "$CASE_LIMIT" -gt 0 ] && echo "CASE_LIMIT=${CASE_LIMIT} — ingesting first ${CASE_LIMIT} cases only"

for case_dir in "$CASES_DIR"/*/; do
    [ -d "$case_dir" ] || continue
    [ "$CASE_LIMIT" -gt 0 ] && [ "$total_cases" -ge "$CASE_LIMIT" ] && break
    case_id=$(basename "$case_dir")
    txt_files=()
    while IFS= read -r f; do txt_files+=("$f"); done < <(find "$case_dir" -maxdepth 1 -name "*.txt" -type f | sort)
    [ ${#txt_files[@]} -eq 0 ] && continue

    echo "Case $case_id (${#txt_files[@]} files)..."
    total_cases=$((total_cases + 1))

    for txt_file in "${txt_files[@]}"; do
        filename=$(basename "$txt_file")
        # Use case_id prefix to avoid filename collision in collection
        # (RAG ingestor uses filename as document key)
        unique_name="${case_id}_${filename}"
        tmp_file="/tmp/${unique_name}"
        cp "$txt_file" "$tmp_file"

        response=$(curl -sf -X POST "${INGESTOR_URL}/v1/documents" \
            -F "documents=@${tmp_file};type=text/plain" \
            -F "data={\"collection_name\":\"${COLLECTION}\",\"blocking\":true}" \
            2>&1) || {
                echo "  FAILED (curl error): $unique_name"
                failed=$((failed + 1))
                rm -f "$tmp_file"
                continue
            }
        rm -f "$tmp_file"

        # Success detection: the ingestor response has NO top-level `status` field.
        # A successful upload looks like:
        #   {"message":"Document upload job successfully completed.",
        #    "documents_completed":1,"failed_documents":[],"validation_errors":[]}
        # So key off documents_completed / message / empty failed_documents — NOT `status`
        # (the old `d.get('status')` check returned 'unknown' and mislabeled every success).
        result=$(echo "$response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print('fail'); sys.exit()
msg = (d.get('message') or '').lower()
done = d.get('documents_completed', 0) or 0
failed_docs = d.get('failed_documents') or []
verrs = d.get('validation_errors') or []
# 'already exists' surfaces in failed_documents[].error_message on re-runs, not msg.
exists_all = bool(failed_docs) and all(
    'already exists' in (f.get('error_message', '') or '').lower() for f in failed_docs)
if (done >= 1 or 'successfully completed' in msg) and not failed_docs and not verrs:
    print('success')
elif (exists_all or 'already exists' in msg) and not verrs:
    print('exists')
else:
    print('fail')
" 2>/dev/null || echo fail)
        if [ "$result" = "success" ]; then
            echo "  ✓ $unique_name"
            total_files=$((total_files + 1))
        elif [ "$result" = "exists" ]; then
            echo "  (skip) $unique_name — already in collection"
            total_files=$((total_files + 1))
        else
            echo "  FAILED: $unique_name — $response"
            failed=$((failed + 1))
        fi
    done
done

echo ""
echo "=== Ingestion summary ==="
echo "Cases: $total_cases | Files ingested: $total_files | Failed: $failed"

if [ "$failed" -gt 0 ]; then
    echo "ERROR: $failed file(s) failed to ingest."
    echo "  Common causes: nv-ingest Redis unreachable, ES not ready, ingestor OOM."
    echo "  Re-run this script to retry failed files (idempotent — skips already-ingested)."
    exit 1
fi

# ── Post-ingest smoke test: verify documents are actually searchable ───────────
# Ingestor returning "completed" proves the API accepted the file, not that ES indexed it.
# Query rag-server directly to confirm at least one document is retrievable.
echo ""
echo "Post-ingest smoke test (querying rag-server to verify documents are searchable)..."
echo "  Note: nv-ingest embeds documents asynchronously after the ingestor queues them."
echo "  Retrying up to 5 times (every 30s) to allow embedding pipeline to catch up..."
if curl -sf "${RAG_URL}/health" &>/dev/null; then
    SMOKE_PASSED=false
    for _attempt in 1 2 3 4 5; do
        SEARCH_RESULT=$(curl -sf -X POST "${RAG_URL}/v1/search" \
            -H 'Content-Type: application/json' \
            -d "{\"query\":\"Singapore forensic case suspect\",\"collection_name\":\"${COLLECTION}\",\"top_k\":1}" \
            2>/dev/null || echo "")
        HAS_RESULTS=$(echo "$SEARCH_RESULT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    hits = d.get('chunks', d.get('results', d.get('documents', [])))
    print('yes' if hits else 'no')
except: print('no')
" 2>/dev/null || echo "no")
        if [ "$HAS_RESULTS" = "yes" ]; then
            SMOKE_PASSED=true
            echo "✓ Smoke test passed (attempt ${_attempt}) — documents are searchable in RAG"
            break
        fi
        echo "  [attempt ${_attempt}/5] no results yet — waiting 30s for nv-ingest embedding pipeline..."
        sleep 30
    done
    if [ "$SMOKE_PASSED" = "false" ]; then
        echo "ERROR: Smoke test FAILED after 5 attempts — rag-server returns no results."
        echo "  Diagnostics:"
        echo "    docker logs compose-nv-ingest-ms-runtime-1 | tail -20"
        echo "    curl http://localhost:9200/${COLLECTION}/_count   # ES doc count"
        echo "  Common causes: nv-ingest Redis unreachable, OOM, or wrong collection name."
        exit 1
    fi
else
    echo "  (rag-server not reachable at $RAG_URL — skipping smoke test)"
fi

echo ""
echo "=== Phase 3 gate verification ==="
echo "Run this query to verify end-to-end:"
echo ""
echo '  curl -sf -X POST http://localhost:8100/generate \'
echo '    -H "Content-Type: application/json" \'
echo '    -d '"'"'{"query":"List all case IDs and their case types in the database"}'"'"' | python3 -m json.tool'
echo ""
echo "Expected: Sherlock returns a list of SC-2024-XXXXXXXX case IDs with types and citations."
echo ""
echo "Phase 3 proof: deploy/PHASE3_DATA_SIM.md"

# Restore Cosmos Reason2 if we stopped it for nv-ingest
if [ "$_VLM_WAS_RUNNING" = true ]; then
    echo "  Restarting ${_VLM_CTR} (VSS VLM)..."
    docker start "$_VLM_CTR" >/dev/null
    echo "  ${_VLM_CTR} restarted ✓ (allow ~2 min to become healthy)"
fi

echo "=== Phase 3 sim-case-text complete ==="
