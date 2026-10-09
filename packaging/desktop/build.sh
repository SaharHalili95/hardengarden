#!/usr/bin/env bash
# Builds the desktop packages (.deb and .AppImage) around a prebuilt scanner bundle.
# Run on Ubuntu 22.04 (glibc 2.35 baseline, R31) with the Tauri system libraries installed.
#
# usage: packaging/desktop/build.sh SCANNER_DIR [OUT_DIR]
#   SCANNER_DIR  the PyInstaller --onedir folder from packaging/sidecar/build.sh
#   OUT_DIR      where the .deb and .AppImage are copied (default: dist/desktop)
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
scanner="$(realpath "${1:?usage: build.sh SCANNER_DIR [OUT_DIR]}")"
out="$(realpath -m "${2:-$repo/dist/desktop}")"

if [[ ! -x "$scanner/hardengarden-sidecar" ]]; then
  echo "error: $scanner/hardengarden-sidecar is missing or not executable" >&2
  exit 1
fi

resource="$repo/desktop/src-tauri/binaries/hardengarden-sidecar"
rm -rf "$resource"
mkdir -p "$(dirname "$resource")"
cp -a "$scanner" "$resource"

# The AppImage runtime (the small loader at the start of every AppImage) is pinned to a
# tagged release and verified, instead of whatever "continuous" build exists at build time.
# The hash was recorded when the pin was chosen (ADR-021).
runtime_tag="20251108"
runtime_sha256="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
curl -sSfL -o "$work/runtime-x86_64" \
  "https://github.com/AppImage/type2-runtime/releases/download/${runtime_tag}/runtime-x86_64"
echo "${runtime_sha256}  $work/runtime-x86_64" | sha256sum -c -
export LDAI_RUNTIME_FILE="$work/runtime-x86_64"

cd "$repo/desktop"
pnpm install --frozen-lockfile
# AppImage tooling is itself an AppImage; containers and CI runners have no FUSE.
APPIMAGE_EXTRACT_AND_RUN=1 pnpm tauri build --bundles deb appimage

version="$(node -p "require('./src-tauri/tauri.conf.json').version")"
bundle=src-tauri/target/release/bundle
mkdir -p "$out"

# Tauri names the Debian package after the product name in kebab case ("harden-garden").
# Repack it under the project's name; contents and dependencies are unchanged.
dpkg-deb -R "$bundle/deb/HardenGarden_${version}_amd64.deb" "$work/pkg"
sed -i 's/^Package: .*/Package: hardengarden/' "$work/pkg/DEBIAN/control"
dpkg-deb --root-owner-group -Zxz -b "$work/pkg" "$out/hardengarden_${version}_amd64.deb"

cp -v "$bundle/appimage/HardenGarden_${version}_amd64.AppImage" \
  "$out/hardengarden_${version}_x86_64.AppImage"
cp -v src-tauri/target/release/hardengarden-desktop "$out/"
