# Contributing

Thanks for helping. HardenGarden is a security tool, so the bar is: read-only, tested, and
explained. Please read [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) (the project rules) and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) first.

Security problems: do not open an issue. Use private reporting as described in
[`SECURITY.md`](SECURITY.md).

## Ground rules

- **Checks are read-only.** No writes, no service restarts, no installs, no privilege
  escalation. Files are read through `SystemView`; commands only through `CommandRunner`'s
  allowlist.
- **Findings and scores never depend on the AI model.**
- **Remediation is a reviewed template**, one per check, idempotent, `set -euo pipefail`,
  dry run unless `HG_APPLY=1`, backing up every file it edits.
- **Knowledge-base documents are original writing** with public references. Never copy text
  from CIS Benchmarks or other licensed standards, and never invent CVE, CIS or man-page IDs.
- **No suppressions without a reason.** `# noqa`, `# type: ignore`, `# nosec` and
  `eslint-disable` need an inline justification.
- **New runtime dependencies** need an entry in [`docs/DECISIONS.md`](docs/DECISIONS.md): why,
  alternatives, licence, maintenance.
- **Tests are never weakened** to make a build pass.

## Set up

Python (scanner, CLI, API):

```sh
cd backend
uv sync
uv run pre-commit install
uv run pytest
```

Desktop app: Node 22 with corepack, Rust (the version in
`desktop/src-tauri/rust-toolchain.toml`) and the Tauri system libraries. On Ubuntu or Debian:

```sh
sudo apt install libwebkit2gtk-4.1-dev build-essential file libxdo-dev libssl-dev \
  libayatana-appindicator3-dev librsvg2-dev
cd desktop
corepack enable
pnpm install --frozen-lockfile
```

Release builds put the frozen scanner in `desktop/src-tauri/binaries/hardengarden-sidecar/`.
For development, create that folder empty and point the app at your checkout's scanner:

```sh
mkdir -p src-tauri/binaries/hardengarden-sidecar
HARDENGARDEN_SIDECAR="$PWD/../backend/.venv/bin/hardengarden" pnpm tauri dev
```

## Before you open a pull request

These are the same checks CI runs:

```sh
# backend/
uv run ruff check . ../packaging ../docs/tools
uv run ruff format --check . ../packaging ../docs/tools
uv run mypy && uv run mypy --strict ../packaging ../docs/tools
uv run pytest
uv run bandit -c pyproject.toml -r hardengarden

# desktop/
pnpm typecheck && pnpm lint && pnpm format:check && pnpm test && pnpm test:e2e
cd src-tauri && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test

# repository root
python3 docs/tools/check_links.py
python3 docs/tools/readme_commands.py --list
```

- One logical change per commit, [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `test:`, `docs:`, `ci:`, `chore:`, `build:`).
- New checks need: metadata, a knowledge-base document, a remediation template (or a reason
  why there is none), fixture scenarios for PASS, FAIL and an edge case, golden questions for
  retrieval, and a regenerated [`docs/CHECKS.md`](docs/CHECKS.md)
  (`uv run hardengarden checks --markdown > ../docs/CHECKS.md`).
- Every shell block in the README needs a `readme-test` marker: `run`, or `skip` with a reason.

## Releases

1. Bump the version in `backend/hardengarden/__init__.py`, `desktop/package.json`,
   `desktop/src-tauri/Cargo.toml` and `desktop/src-tauri/tauri.conf.json`
   (`python3 packaging/check_versions.py` must pass), and update the OpenAPI snapshot.
2. Merge to `main` with CI green.
3. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.

The [release workflow](.github/workflows/release.yml) builds on Ubuntu 22.04, tests the
packages on Ubuntu 22.04, 24.04 and Debian 12, runs Trivy, writes an SBOM and checksums,
signs everything with Sigstore, and publishes a pre-release. To build locally on Ubuntu 22.04:

```sh
packaging/sidecar/build.sh dist/sidecar
packaging/desktop/build.sh dist/sidecar/hardengarden-sidecar dist/desktop
packaging/check_glibc.sh dist/sidecar dist/desktop/hardengarden-desktop
```
