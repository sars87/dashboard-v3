#!/usr/bin/env bash
# Compatibility wrapper: use the hardened dashboard-v3 deployment flow.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/deploy-v3" "$@"
