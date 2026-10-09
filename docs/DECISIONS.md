# Architecture Decision Log

Short ADR-style records. New runtime dependencies MUST be justified here
(docs/REQUIREMENTS.md section 2): why needed, alternatives considered, license, maintenance status.

Format: **ADR-NNN — Title** · Date · Status · Context · Decision · Consequences.

---

## ADR-001 — Fixed technology stack

- **Date:** 2026-10-09 · **Status:** Accepted (docs/REQUIREMENTS.md section 2)
- **Context:** The stack was fixed up front to keep scope and review effort bounded.
- **Decision:** Python 3.12 + uv, Typer, FastAPI/Pydantic v2/Uvicorn, ChromaDB, Ollama,
  Tauri v2 + React 18 + TypeScript + Vite, PyInstaller `--onedir` sidecar, GitHub Actions.
  Each library is added only in the phase that first uses it (R29), with its own ADR.
- **Consequences:** No substitutions without a new ADR.

## ADR-002 — Scope decisions taken before Phase 0

- **Date:** 2026-10-09 · **Status:** Accepted
- **Decisions:**
  1. Development needs Docker (container tests) and, for the AI features, Ollama.
  2. Repository `SaharHalili95/hardengarden`, **public from day one**, so that CodeQL,
     branch protection and Private Vulnerability Reporting are available on the free plan.
  3. Vulnerability reports go through GitHub Private Vulnerability Reporting (see `SECURITY.md`).
  4. The Ollama URL is **loopback only**. Accepted hosts: `127.0.0.1`, `localhost`, `::1`.
     Anything else is rejected with a clear validation error. This enforces R7.
  5. Model downloads are allowed: the app calls Ollama's local `/api/pull` only after an
     explicit click (R37), and Ollama performs the download. Recorded as an accepted
     egress in `THREAT_MODEL.md`.
  6. CI uses a stubbed LLM on every PR. An optional manual `workflow_dispatch` job runs the
     real evaluation with `qwen2.5:1.5b-instruct` (public-repo runners have 16 GB RAM).
     `qwen2.5:7b-instruct` evaluations stay manual and are run before a release.
  7. No PyPI publication for now; `pipx install` uses the wheel attached to the GitHub Release.
  8. Root-only checks without root return `SKIPPED` (`insufficient_privileges`). CLI and UI
     show "Run with sudo for full coverage", and the coverage % reflects the skipped checks.
  9. The R5 forbidden-pattern test is AST-based. Ruff's flake8-bandit (`S`) rules and
     bandit both run in CI as additional layers.

## ADR-003 — Development tooling and build backend

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Phase 0 needs a buildable package and the quality toolchain from section 2.
- **Decision:**
  - **Build backend: hatchling** (MIT, PyPA project, actively maintained). Build-time only;
    it is not installed at runtime. Alternatives: setuptools (more config surface),
    uv's own build backend (newer, less mature at the time of writing).
  - **Dev dependency group** (not shipped): ruff, mypy, pytest, pytest-cov, bandit,
    pip-audit, pre-commit. All are named in section 2 except pre-commit, which Phase 0
    requires for "pre-commit hooks".
  - Pre-commit runs the Python tools as **local hooks through `uv run`**, so hook versions
    always equal the versions in `uv.lock` and in CI.
  - **gitleaks** runs in CI as the official release binary, verified against its published
    SHA-256 checksum, rather than `gitleaks-action` (which needs a license key for
    organization accounts and adds a third-party action to the trust chain).
  - Coverage: a project-wide floor of 85 % in `pyproject.toml`; the stricter per-package
    gates (core/checks ≥ 90 %, api ≥ 85 %) are enforced in the phases that create those
    packages. Thresholds are never lowered (R22).
- **Consequences:** No runtime dependencies exist after Phase 0.
