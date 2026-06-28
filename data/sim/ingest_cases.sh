#!/usr/bin/env bash
# Ingest synthetic case text files into RAG Blueprint (multimodal_data collection)
# Uses {case_id}_{filename} to avoid document key collision — ingestor uses filename as key.
set -euo pipefail

CASES_DIR="$(cd "$(dirname "$0")/../cases" && pwd)"
INGESTOR_URL="${INGESTOR_URL:-http://localhost:8082}"
COLLECTION="${COLLECTION:-multimodal_data}"

total_files=0
total_cases=0
failed=0

for case_dir in "$CASES_DIR"/*/; do
    [ -d "$case_dir" ] || continue
    case_id=$(basename "$case_dir")
    txt_files=()
    while IFS= read -r f; do txt_files+=("$f"); done < <(find "$case_dir" -maxdepth 1 -name "*.txt" -type f | sort)
    [ ${#txt_files[@]} -eq 0 ] && continue

    echo "Ingesting case $case_id (${#txt_files[@]} files)..."
    total_cases=$((total_cases + 1))

    for txt_file in "${txt_files[@]}"; do
        filename=$(basename "$txt_file")
        # Prefix case_id to avoid filename collision in collection
        # (RAG ingestor uses the uploaded filename as the document key)
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
            echo "  FAILED: $unique_name — $response"
            failed=$((failed + 1))
        fi
    done
done

echo ""
echo "=== Ingestion complete ==="
echo "Cases: $total_cases | Files: $total_files | Failed: $failed"
[ "$failed" -gt 0 ] && exit 1 || exit 0
