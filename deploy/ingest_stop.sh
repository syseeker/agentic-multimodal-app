#!/usr/bin/env bash
# Stop nv-ingest to free ~10 GB RAM.
# Safe to run at any time after ingestion is complete.
# ingestor-server stays running (needed for workbench uploads and health checks).
docker stop compose-nv-ingest-ms-runtime-1 2>/dev/null \
    && echo "nv-ingest stopped (~10 GB RAM freed)" \
    || echo "nv-ingest was not running"
