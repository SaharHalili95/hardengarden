#!/usr/bin/env bash
# Release smoke tests, run as root inside a clean distro container (ubuntu:22.04, ubuntu:24.04,
# debian:12). Expects the release artifacts in /artifacts and this repository at /repo.
#
#   distro_smoke.sh install   install the .deb and test tools; test the .deb, pipx, GUI, AppImage
#   distro_smoke.sh noexec    re-test both scanners with /tmp mounted noexec (R32); run this in
#                             a second container started from the first one's committed image
#                             with: --tmpfs /tmp:rw,noexec,nosuid
set -euo pipefail

ARTIFACTS=/artifacts
SMOKE=/repo/packaging/tests/smoke_scanner.py
SCANNER=/usr/lib/HardenGarden/sidecar/hardengarden-sidecar
PIPX_SCANNER=/root/.local/bin/hardengarden
export PIPX_HOME=/root/.local/share/pipx PIPX_BIN_DIR=/root/.local/bin
export DEBIAN_FRONTEND=noninteractive

say() { printf '\n== %s\n' "$*"; }
die() { echo "FAIL  $*" >&2; exit 1; }

one() {
  local pattern="$1" matches
  mapfile -t matches < <(compgen -G "$ARTIFACTS/$pattern" || true)
  [[ ${#matches[@]} -eq 1 ]] || die "expected one $pattern in $ARTIFACTS"
  printf '%s' "${matches[0]}"
}

distro() { sed -n 's/^PRETTY_NAME="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' /etc/os-release; }

install_all() {
  say "Install on $(distro), glibc $(ldd --version | head -n 1 | awk '{print $NF}')"
  local deb wheel
  deb="$(one 'hardengarden_*_amd64.deb')"
  wheel="$(one 'hardengarden-*-py3-none-any.whl')"
  apt-get update -qq
  # The .deb pulls its declared dependencies (R33); the rest are test tools only.
  apt-get install -y -qq "$deb" python3 pipx xvfb xauth imagemagick procps >/dev/null
  dpkg -s hardengarden | grep -E '^(Version|Depends):'
  dpkg -s hardengarden | grep -q '^Depends:.*libwebkit2gtk-4.1-0' || die "Depends lacks webkit"
  dpkg -s hardengarden | grep -q '^Depends:.*libgtk-3-0' || die "Depends lacks GTK"

  say "pipx install of the release wheel (R34)"
  local python=python3
  if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))'; then
    # This distro's Python is older than 3.12; uv provides a 3.12 interpreter for pipx.
    command -v uv >/dev/null || die "uv is required on $(distro) to provide Python 3.12"
    uv python install 3.12 >/dev/null
    python="$(uv python find 3.12)"
  fi
  pipx install --python "$python" "$wheel"
  "$PIPX_SCANNER" --version
}

test_scanners() {
  say "Packaged scanner from the .deb"
  python3 "$SMOKE" "$SCANNER" "$@"
  say "Scanner installed with pipx"
  python3 "$SMOKE" "$PIPX_SCANNER" "$@"
}

# Starts the desktop app under Xvfb and checks what it reports and what it draws.
#   gui_smoke NAME EXPECT COMMAND...    EXPECT: "ready" or "failed"
gui_smoke() {
  local name="$1" expect="$2"
  shift 2
  local log="/root/gui-$name.log" shot="/root/gui-$name.png" app status colors
  Xvfb :99 -screen 0 1280x860x24 -nolisten tcp >/dev/null 2>&1 &
  local xvfb=$!
  sleep 2
  # Own process group, so stopping it also stops an AppImage's child process.
  DISPLAY=:99 setsid "$@" >"$log" 2>&1 &
  app=$!
  status=""
  for _ in $(seq 1 60); do
    if grep -q 'hardengarden-desktop: scanner ready' "$log"; then status=ready; break; fi
    if grep -q 'hardengarden-desktop: scanner failed' "$log"; then status=failed; break; fi
    kill -0 "$app" 2>/dev/null || break
    sleep 1
  done
  sleep 4 # let the window paint
  DISPLAY=:99 import -window root "$shot" || true
  colors="$(convert "$shot" -format '%k' info: 2>/dev/null || echo 0)"
  kill -TERM -- "-$app" 2>/dev/null || true
  wait "$app" 2>/dev/null || true
  kill "$xvfb" 2>/dev/null || true
  wait "$xvfb" 2>/dev/null || true
  sleep 2
  if pgrep -f 'hardengarden-sidecar serve' >/dev/null; then
    die "$name: the scanner kept running after the app exited"
  fi
  if [[ "$status" != "$expect" ]]; then
    tail -n 30 "$log" >&2
    die "$name: expected the app to report '$expect', got '${status:-nothing}'"
  fi
  # A blank window is one or two colours; the rendered UI has text, plants and borders.
  ((colors > 50)) || die "$name: the window looks blank ($colors colours)"
  echo "PASS  $name: app reported '$status' and drew a non-blank window ($colors colours)"
}

test_gui() {
  # WebKitGTK's own sandbox needs user namespaces, which unprivileged containers lack. This
  # switch is for the headless smoke test only; the shipped app never sets it.
  export WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1
  local broken=/root/broken-scanner appimage
  printf '#!/bin/sh\necho "simulated start-up crash" >&2\nexit 3\n' >"$broken"
  chmod +x "$broken"

  say "Desktop app from the .deb under Xvfb"
  gui_smoke deb-ready ready /usr/bin/hardengarden-desktop
  # R35: a broken scanner must produce the error screen, never a blank window or a hang.
  HARDENGARDEN_SIDECAR="$broken" gui_smoke deb-broken-scanner failed /usr/bin/hardengarden-desktop

  say "AppImage under Xvfb"
  appimage="$(one 'hardengarden_*_x86_64.AppImage')"
  cp "$appimage" /root/app.AppImage
  chmod +x /root/app.AppImage
  # No FUSE in containers: the AppImage extracts itself instead of mounting.
  export APPIMAGE_EXTRACT_AND_RUN=1
  gui_smoke appimage-ready ready /root/app.AppImage
  HARDENGARDEN_SIDECAR="$broken" gui_smoke appimage-broken-scanner failed /root/app.AppImage
  unset APPIMAGE_EXTRACT_AND_RUN
}

check_appimage_has_no_glibc() {
  say "AppImage bundles everything except glibc (R33)"
  local dir
  dir="$(mktemp -d)"
  (cd "$dir" && /root/app.AppImage --appimage-extract >/dev/null)
  if find "$dir/squashfs-root" \( -name 'libc.so*' -o -name 'ld-linux*' \) | grep -q .; then
    die "the AppImage contains glibc"
  fi
  echo "PASS  no libc.so / ld-linux inside the AppImage"
  rm -rf "$dir"
}

case "${1:-}" in
  install)
    install_all
    test_scanners
    test_gui
    check_appimage_has_no_glibc
    ;;
  noexec)
    say "noexec /tmp on $(distro) (R32)"
    test_scanners --expect-noexec-tmp
    ;;
  *)
    echo "usage: distro_smoke.sh install|noexec" >&2
    exit 2
    ;;
esac
say "ALL CHECKS PASSED on $(distro)"
