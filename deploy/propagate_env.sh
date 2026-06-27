#!/usr/bin/env bash
# Propagate shared secrets from the SINGLE project .env (source of truth) into a
# component's own .env. NVIDIA components each read their own deploy/.env, so we
# keep one project .env and distribute the shared keys to each — fill the key once.
#
#   deploy/propagate_env.sh external/aiq/deploy/.env
set -euo pipefail
ROOT_ENV="$(cd "$(dirname "$0")/.." && pwd)/.env"
TARGET="${1:?usage: propagate_env.sh <component .env path>}"

[ -f "$ROOT_ENV" ] || { echo "missing $ROOT_ENV (cp .env.example .env and fill it)"; exit 1; }
[ -f "$TARGET" ] || touch "$TARGET"

# Shared keys distributed to every component (extend as new components are added).
for KEY in NVIDIA_API_KEY NGC_API_KEY HF_TOKEN; do
  VAL="$(grep -E "^${KEY}=" "$ROOT_ENV" | tail -1 | cut -d= -f2-)"
  [ -z "$VAL" ] && continue              # skip blanks; don't clobber with empty
  if grep -qE "^${KEY}=" "$TARGET"; then
    sed -i "s|^${KEY}=.*|${KEY}=${VAL}|" "$TARGET"
  else
    echo "${KEY}=${VAL}" >> "$TARGET"
  fi
done
echo "propagated shared keys (values not printed) -> $TARGET"
