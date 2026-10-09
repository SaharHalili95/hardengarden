#!/usr/bin/env bash
# Installs a pinned Trivy release after verifying it. Trivy's own release channel was
# compromised in March 2026 (CVE-2026-33634: v0.69.4 and force-pushed trivy-action tags), so
# this never uses the action and never trusts a download on its checksum alone:
#   1. the checksums file must carry a valid Sigstore signature from Trivy's release workflow
#   2. the tarball must match that checksums file
# Requires cosign on PATH (sigstore/cosign-installer). usage: install_trivy.sh DEST_DIR
set -euo pipefail

version="0.75.0"
dest="${1:?usage: install_trivy.sh DEST_DIR}"
base="https://github.com/aquasecurity/trivy/releases/download/v${version}"
tarball="trivy_${version}_Linux-64bit.tar.gz"
sums="trivy_${version}_checksums.txt"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cd "$work"
for file in "$tarball" "$sums" "$sums.sigstore.json"; do
  curl -sSfLO "$base/$file"
done
cosign verify-blob "$sums" \
  --bundle "$sums.sigstore.json" \
  --certificate-identity "https://github.com/aquasecurity/trivy/.github/workflows/reusable-release.yaml@refs/tags/v${version}" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
grep " ${tarball}\$" "$sums" | sha256sum -c -
mkdir -p "$dest"
tar -xzf "$tarball" -C "$dest" trivy
"$dest/trivy" --version
