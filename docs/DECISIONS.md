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

## ADR-004 — One branch and one merge commit per phase

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** HardenGarden is built in phases (`docs/REQUIREMENTS.md` section 6), each with a
  gate.
- **Decision:** Every phase is developed on its own branch (`phase-N-name`) and merged into
  `main` with a `--no-ff` merge commit once its full test, lint and security suite passes, so
  each phase stays reviewable on its own. Gate items that need infrastructure not available
  yet (a published release, real AI models) are recorded as open, never as passed.

## ADR-005 — Runtime dependency: pydantic (v2)

- **Date:** 2026-10-09 · **Status:** Accepted (named in docs/REQUIREMENTS.md section 2)
- **Why:** The check/result/report contracts (section 5.1) are Pydantic models, which give
  validation, frozen objects and a JSON schema for the API in Phase 4.
- **Alternatives:** dataclasses + hand-written validation (more code, no schema), attrs.
- **License / maintenance:** MIT; very actively maintained (pydantic-core in Rust, wheels for
  all target platforms). Pulled in: `pydantic-core`, `annotated-types`, `typing-extensions`,
  `typing-inspection` (all MIT/PSF).

## ADR-006 — Runtime dependency: typer

- **Date:** 2026-10-09 · **Status:** Accepted (named in docs/REQUIREMENTS.md section 2)
- **Why:** The CLI (`scan`, `checks`, later `explain`, `kb`, `serve`).
- **Alternatives:** argparse (stdlib; considered, but section 2 fixes Typer). `typer-slim`
  is now only an alias of `typer`, so it does not reduce dependencies.
- **License / maintenance:** MIT; actively maintained. It no longer depends on `click`. Pulled in:
  `rich` (MIT) for help rendering, `shellingham` (ISC), `annotated-doc`
  (MIT). HardenGarden's own output uses plain `typer.style`, not rich markup.

## ADR-007 — Python 3.12 is the minimum, including for the CLI fallback (R34)

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** R34 asks for `pipx install hardengarden` on Ubuntu 22.04, Ubuntu 24.04 and
  Debian 12. Their system Pythons are 3.10, 3.12 and 3.11, while section 2 fixes 3.12 and
  section 5.1 uses `StrEnum` (3.11+).
- **Decision:** Keep `requires-python >= 3.12`. The documented fallback on 22.04 and Debian 12
  installs a 3.12 interpreter through uv (`uv tool install <wheel>`, or `pipx install
  --python "$(uv python find 3.12)" <wheel>`). Phase 6 tests exactly these commands.
- **Consequences:** No downgrade of the codebase to 3.10 syntax. This is a deliberate
  reading of R34: the CLI needs Python 3.12, which uv provides where the system lacks it.

## ADR-008 — Scanner design choices (Phase 1)

- **Date:** 2026-10-09 · **Status:** Accepted
- **Commands are an enum, not argv.** `CommandRunner.run()` takes a `Command` member; each
  maps to a constant absolute binary list and constant arguments. Binaries must be
  root-owned and not group/world-writable. Only three commands exist: `sshd -T`,
  `ufw status`, `nft list ruleset`. Everything else is read from files.
- **Commands only describe the live host.** When `--root` is not `/`, a `NullRunner` is used
  and checks fall back to configuration files.
- **Listening sockets come from `/proc/net/*`** through `SystemView`, not from `ss`, so
  HG-NET-001 needs no subprocess and no root and is fully testable with fixtures.
- **`requires_root` is enforced only on the live host.** Scanning a `--root` tree as a normal
  user still evaluates root-only checks, because the files are readable there.
- **Fixture ownership.** Git cannot store owners or most mode bits, so each fixture scenario
  has a `meta.json` (mode, uid, gid, unreadable). A test-only `SystemView` subclass applies
  it; production code has no knowledge of it.
- **Severities** (the requirements list the checks but not their severities):
  CRITICAL for SSH-003, FS-001, ACC-001; HIGH for SSH-001, SSH-002, FW-001, FS-002;
  MEDIUM for NET-001, FS-003, ACC-002, UPD-001, KRN-001.
- **Expected listeners** for HG-NET-001: tcp/22 (SSH), udp/68 and udp/546 (DHCP clients).
  Anything else on a non-loopback address is a WARN.

## ADR-009 — Runtime dependency: chromadb

- **Date:** 2026-10-09 · **Status:** Accepted (named in docs/REQUIREMENTS.md section 2), with concerns
- **Why:** Local persistent vector store for knowledge-base and man-page embeddings.
- **Alternatives:** sqlite-vec, hnswlib, plain NumPy cosine search (all far lighter for ~60
  chunks). Not used because section 2 fixes ChromaDB.
- **License / maintenance:** Apache-2.0; actively maintained (1.x, Rust core).
- **Concerns, recorded honestly:** chromadb 1.5.9 pulls in ~470 MB of transitive packages
  (onnxruntime, grpcio, kubernetes client, opentelemetry SDK and exporter, tokenizers). This
  inflates the PyInstaller sidecar (Phase 6) and the supply-chain surface (SC-1).
- **Telemetry (R7):** In 1.5.9 its product telemetry class is a no-op and the OTel endpoint is
  empty by default. HardenGarden still sets `anonymized_telemetry=False`. A test records every
  `socket.connect` during ingest and query and asserts there are none, and ingest/search were
  verified inside a network namespace with networking fully disabled.
- **Possible follow-up:** if the sidecar size matters, ADR-011's lexical retriever plus a
  NumPy cosine search over the stored embeddings would remove chromadb entirely.

## ADR-010 — Runtime dependency: PyYAML (+ dev: types-PyYAML)

- **Date:** 2026-10-09 · **Status:** Accepted
- **Why:** The golden evaluation sets are YAML (the spec names `golden.yaml`), and
  `hardengarden kb eval` reads them. Only `yaml.safe_load` is used (R5 test enforces this).
- **Alternatives:** JSON golden files (would deviate from the spec's file name).
- **License / maintenance:** MIT; maintained. Already present transitively via chromadb, so it
  adds no new code to the install; declaring it explicitly avoids relying on a transitive pin.

## ADR-011 — Retrieval design: hybrid ranking, deterministic answerability

- **Date:** 2026-10-09 · **Status:** Accepted
- **Ranking:** BM25 over all chunks (stdlib only), fused with vector similarity by reciprocal
  rank fusion when `nomic-embed-text` embeddings exist. Without Ollama, ranking is BM25 only.
- **Answerability (R13):** the IDF-weighted share of the question's terms found in either of
  the two best-ranked sources. Terms unknown to the whole knowledge base weigh the most, so
  off-topic questions score low. Below the threshold (default **0.30**, configurable) the
  answer is the fixed refusal. The signal is deterministic and identical with and without
  Ollama, so the refusal path is fully tested in CI.
- **How the threshold was chosen:** on `golden.yaml`, answerable questions scored ≥ 0.33 and
  negatives ≤ 0.25 with top-2 coverage; 0.30 sits in the gap. Because that is tuning on the
  evaluation set, a separate `holdout.yaml` was written **after** fixing the threshold and is
  reported as-is (Recall@5 0.92, rejection 1.00). The margin is small; more paraphrased
  questions from real users would be the best next improvement.
- **Chunking:** one chunk per `##` section; IDs are `<doc>#<section-slug>`, independent of
  content and position. Ingestion re-embeds only chunks whose content or embedding model
  changed (fingerprint), and removes chunks that disappeared.
- **Man pages (R19):** read at runtime from `/usr/share/man` through `SystemView`, gzip
  decompression capped at 2 MiB, stored only in the user's data directory (0600).
