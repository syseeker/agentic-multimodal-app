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

# ── 2. Ensure data-designer is installed ─────────────────────────────────────
export PATH="$HOME/.local/bin:$PATH"
if ! command -v data-designer &>/dev/null; then
    echo "Installing data-designer..."
    if command -v pip &>/dev/null; then
        pip install --quiet data-designer
    elif command -v pip3 &>/dev/null; then
        pip3 install --quiet data-designer
    else
        # bootstrap pip if neither exists
        python3 <(curl -fsSL https://bootstrap.pypa.io/get-pip.py) --user --quiet
        python3 -m pip install --user --quiet data-designer
    fi
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
NUM_RECORDS="${NUM_RECORDS:-20}"
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
COLLECTION="${COLLECTION:-multimodal_data}"

echo ""
echo "Ingesting case documents into RAG Blueprint ($INGESTOR_URL, collection=$COLLECTION)..."

# Health check
if ! curl -sf "${INGESTOR_URL}/health" &>/dev/null; then
    echo "ERROR: RAG Blueprint ingestor not reachable at $INGESTOR_URL"
    echo "Ensure amms-rag stack is running: docker compose -p amms -f external/rag/deploy/compose/docker-compose-rag-server.yaml up -d"
    exit 1
fi
echo "✓ Ingestor health check passed"

total_files=0
total_cases=0
failed=0

for case_dir in "$CASES_DIR"/*/; do
    [ -d "$case_dir" ] || continue
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
            -F "file=@${tmp_file};type=text/plain" \
            -F "data={\"collection_name\":\"${COLLECTION}\",\"blocking\":true}" \
            2>&1) || {
                echo "  FAILED (curl error): $unique_name"
                failed=$((failed + 1))
                rm -f "$tmp_file"
                continue
            }
        rm -f "$tmp_file"

        status=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status', d.get('task_status', 'unknown')))" 2>/dev/null || echo "unknown")
        if echo "$status" | grep -qi "success\|complet\|ok"; then
            echo "  ✓ $unique_name"
            total_files=$((total_files + 1))
        elif echo "$response" | grep -qi "already exists"; then
            echo "  (skip) $unique_name — already in collection"
            total_files=$((total_files + 1))
        else
            echo "  FAILED: $unique_name — $status — $response"
            failed=$((failed + 1))
        fi
    done
done

echo ""
echo "=== Ingestion summary ==="
echo "Cases: $total_cases | Files ingested: $total_files | Failed: $failed"

if [ "$failed" -gt 0 ]; then
    echo "WARNING: $failed file(s) failed to ingest. Re-run to retry."
    exit 1
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
echo "=== Phase 3 sim-case-text complete ==="
