#!/usr/bin/env bash
# Runs distro_smoke.sh for one distro image: install + tests, then noexec /tmp re-test.
#
# usage: packaging/tests/run_distro_matrix.sh IMAGE ARTIFACTS_DIR
#   e.g. packaging/tests/run_distro_matrix.sh debian:12 dist/release
# Extra `docker run` options (e.g. proxy settings) can be passed in $DOCKER_RUN_OPTS.
set -euo pipefail

image="${1:?usage: run_distro_matrix.sh IMAGE ARTIFACTS_DIR}"
artifacts="$(realpath "${2:?usage: run_distro_matrix.sh IMAGE ARTIFACTS_DIR}")"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
name="hg-smoke-$(echo "$image" | tr -c 'a-z0-9' '-')$$"
uv_bin="$(command -v uv || true)"

mounts=(-v "$artifacts:/artifacts:ro" -v "$repo:/repo:ro")
if [[ -n "$uv_bin" ]]; then mounts+=(-v "$uv_bin:/usr/local/bin/uv:ro"); fi
# shellcheck disable=SC2206 # word splitting of extra options is intended
extra=(${DOCKER_RUN_OPTS:-})

cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; docker rmi -f "$name:installed" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run --name "$name" "${extra[@]}" "${mounts[@]}" "$image" \
  bash /repo/packaging/tests/distro_smoke.sh install
docker commit "$name" "$name:installed" >/dev/null
docker run --rm "${extra[@]}" "${mounts[@]}" --tmpfs /tmp:rw,noexec,nosuid "$name:installed" \
  bash /repo/packaging/tests/distro_smoke.sh noexec
