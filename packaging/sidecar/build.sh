#!/usr/bin/env bash
# Builds the scanner as a PyInstaller --onedir folder (never --onefile: R32).
# Run on Ubuntu 22.04 (glibc 2.35 baseline, R31). Output: <out>/hardengarden-sidecar/
#
# usage: packaging/sidecar/build.sh [OUT_DIR]   (default: dist/sidecar)
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
out="$(realpath -m "${1:-$repo/dist/sidecar}")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cd "$repo/backend"
# Non-editable install, so the packaged knowledge base (kb_docs) is inside site-packages.
uv sync --locked --no-dev --group packaging --no-editable

uv run --no-sync pyinstaller \
  --onedir \
  --noconfirm \
  --clean \
  --name hardengarden-sidecar \
  --distpath "$out" \
  --workpath "$work/build" \
  --specpath "$work" \
  --collect-data hardengarden \
  --collect-all chromadb \
  --copy-metadata hardengarden \
  "$repo/packaging/sidecar/entry.py"

# Restore the normal development environment.
uv sync --locked

echo "scanner bundle: $out/hardengarden-sidecar"
