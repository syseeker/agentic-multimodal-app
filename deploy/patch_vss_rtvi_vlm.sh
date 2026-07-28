#!/usr/bin/env bash
# Apply patches to vss-rtvi-vlm container after Phase 5 re-deploy.
# These patches fix two VSS 3.2.1 bugs with Cosmos Reason2-8B:
#   1. Model name mismatch (nvidia/cosmos-reason2-8b vs nim_nvidia_cosmos-reason2-8b_hf-1208)
#   2. VIOS URL resolution (name-based 400 → UUID-based temp_files fallback)
#
# Run after phase5_vss.sh completes:
#   bash deploy/patch_vss_rtvi_vlm.sh
#
# See .claude/context/implementation-learnings.md → "VSS rtvi-vlm Container Patches"
set -euo pipefail

echo "=== Patching vss-rtvi-vlm (VSS 3.2.1 LVS bug fixes) ==="

CTR="vss-rtvi-vlm"
if ! docker ps -q --filter "name=^/${CTR}$" | grep -q .; then
    echo "ERROR: ${CTR} is not running. Run Phase 5 first."
    exit 1
fi

# ── Patch 1: rtvi_vlm_server.py — accept model name aliases ──────────────────
echo "Patch 1: rtvi_vlm_server.py — normalize model name..."
docker exec "$CTR" python3 - <<'PYEOF'
path = '/opt/nvidia/rtvi/rtvi/server/rtvi_vlm_server.py'
with open(path) as f:
    src = f.read()

# Check if already patched
if 'Accept friendly name aliases' in src or 'normalize to actual model id' in src:
    print("  Already patched — skipping")
else:
    old1 = '''        if vlm_query.model != model_info.id:
            raise ServiceException(f"No such model '{vlm_query.model}'", "BadParameters", 400)'''
    new1 = '''        # Accept friendly name aliases (e.g. nvidia/cosmos-reason2-8b) for nim_ format
        vlm_query.model = model_info.id'''

    old2 = '''            if request_body.model != model_info.id:
                raise ServiceException(
                    f"No such model '{request_body.model}'", "BadParameters", 400
                )'''
    new2 = '''            request_body.model = model_info.id  # normalize to actual model id'''

    if old1 in src and old2 in src:
        src = src.replace(old1, new1).replace(old2, new2)
        with open(path, 'w') as f:
            f.write(src)
        print("  ✓ Patched both model validation checks")
    else:
        print("  WARNING: patterns not found — check if line numbers shifted in this image version")
PYEOF

# ── Patch 2: asset_manager.py — VIOS URL fallback via UUID ───────────────────
echo "Patch 2: asset_manager.py — VIOS URL resolution fallback..."
docker exec "$CTR" python3 - <<'PYEOF'
import json as _json
path = '/opt/nvidia/rtvi/rtvi/utils/asset_manager.py'
with open(path) as f:
    src = f.read()

if 'VIOS 400 on name-based URL' in src:
    print("  Already patched — skipping")
else:
    old = '''                if response.status != 200:
                    logger.info("Failed to download file from URL. HTTP status %d", response.status)'''
    new = '''                if response.status == 400 and "/vst/api/v1/storage/file/" in current_url and "/url" not in current_url:
                    logger.info("VIOS 400 on name-based URL, resolving via UUID endpoint: %s", current_url)
                    try:
                        from urllib.parse import urlparse as _up
                        parsed = _up(current_url)
                        vios_base = f"{parsed.scheme}://{parsed.netloc}"
                        tl_url = f"{vios_base}/vst/api/v1/storage/timelines"
                        import json as _json, aiohttp as _ah
                        async with _ah.ClientSession() as ts_sess:
                            async with ts_sess.get(tl_url) as tl_resp:
                                tl_data = _json.loads(await tl_resp.text())
                        for file_uuid, entries in tl_data.items():
                            if entries:
                                ent = entries[0]
                                url_ep = (f"{vios_base}/vst/api/v1/storage/file/{file_uuid}/url"
                                          f"?startTime={ent['startTime']}&endTime={ent['endTime']}&blocking=true&disableAudio=true")
                                async with _ah.ClientSession() as u_sess:
                                    async with u_sess.get(url_ep) as u_resp:
                                        u_data = _json.loads(await u_resp.text())
                                video_url = u_data.get("videoUrl", "")
                                if video_url:
                                    current_url = video_url.replace("172.31.33.197", parsed.hostname)
                                    logger.info("Resolved VIOS URL via UUID %s: %s", file_uuid[:8], current_url)
                                    await response.release()
                                    await session.close()
                                    continue
                    except Exception as vios_e:
                        logger.warning("VIOS UUID lookup failed: %s", vios_e)
                if response.status != 200:
                    logger.info("Failed to download file from URL. HTTP status %d", response.status)'''

    if old in src:
        src = src.replace(old, new)
        with open(path, 'w') as f:
            f.write(src)
        print("  ✓ Patched VIOS URL resolution fallback")
    else:
        print("  WARNING: pattern not found — already patched or line numbers shifted")
PYEOF

# ── Restart to apply patches ──────────────────────────────────────────────────
echo ""
echo "Restarting vss-rtvi-vlm to apply patches..."
docker restart "$CTR"
echo -n "Waiting for healthy..."
for i in $(seq 1 36); do
    STATUS=$(docker inspect "$CTR" --format '{{.State.Health.Status}}' 2>/dev/null)
    [ "$STATUS" = "healthy" ] && echo " ✅ healthy" && break
    sleep 5; echo -n "."
done

echo ""
echo "=== VSS rtvi-vlm patches applied ==="
echo "  Video analysis now works with Cosmos Reason2-8B (locally cached)."
echo "  Re-register any videos lost during Phase 5 re-deploy:"
echo "    rm data/cases/<id>/<video_stem>_analysis.txt"
echo "    uv run data/video/process_video.py --case-id <id>"
