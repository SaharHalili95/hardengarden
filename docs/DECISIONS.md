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

## ADR-012 — Open chromadb advisories: accepted as unreachable

- **Date:** 2026-10-09 · **Status:** Accepted, to be revisited
- **Context:** pip-audit reports four advisories against chromadb 1.5.9 (the latest release),
  none with a fixed version: GHSA-f4j7-r4q5-qw2c / CVE-2026-45829 and GHSA-36p7-vc44-83pf /
  CVE-2026-45833 (code injection via `trust_remote_code` model loading through the server's
  `/api/v2/.../collections` endpoints), GHSA-xph7-9rjv-w5fr / CVE-2026-45831 and
  GHSA-2wm9-hf6c-p5cr / CVE-2026-45830 (cross-tenant authorization in the server's RBAC).
- **Analysis:** all four are in chromadb's HTTP server. HardenGarden imports chromadb only in
  `rag/store.py`, uses only the embedded `PersistentClient`, never starts the chromadb
  server, never uses its embedding functions (`embedding_function=None`) and never passes
  `trust_remote_code`. The local store is in a 0700 directory owned by the user.
- **Decision:** keep chromadb (section 2 forbids substituting it), ignore exactly these four
  IDs in pip-audit (and in Trivy in Phase 6), and enforce the embedded-only usage with
  `tests/security/test_chroma_usage.py`. Any other advisory still fails the build.
- **Conflict to resolve:** this collides with the Phase 6 gate "zero HIGH/CRITICAL findings"
  read literally. Options: (a) accept these documented exceptions;
  (b) replace chromadb with a small NumPy cosine store behind the existing `VectorStore`
  interface (≈80 lines, removes ~470 MB of dependencies and all four advisories);
  (c) wait for an upstream fix. Preferred: (b), on the roadmap.

## ADR-013 — Grounded generation and output safety

- **Date:** 2026-10-09 · **Status:** Accepted
- **Order of gates:** (1) retrieval answerability, refused before any model call (R13);
  (2) R39 free-memory guard; (3) generation with temperature 0, fixed seed, bounded
  `num_predict`, the fixed system prompt in `rag/prompts/system.txt` (R14); (4) final
  answer must cite at least one retrieved passage id, invented ids are removed, an answer
  with no valid citation is replaced by a fixed message (R13).
- **Prompt structure (R15):** system-derived evidence goes only inside
  `<untrusted_system_data>`; angle brackets in it become U+2039/U+203A and `[kb:` is
  defused, so it can neither close its block nor forge citations. Evidence minimization
  already drops config comments, so most injected text never reaches the model.
- **Output (R12, R15):** the same sanitizer runs line by line on the live stream and on the
  final answer: code fences and shell-looking lines become a fixed placeholder, inline
  commands are removed, URLs and markdown links are removed, HTML tags are stripped.
- **R38:** a watchdog timer enforces the hard timeout; Cancel shuts the socket down from any
  thread, so a read blocked on a slow model returns immediately (tested over real HTTP).
- **Explanations** use all passages of the check's own knowledge-base document instead of a
  search, so they never depend on retrieval luck. Answers are cached per (check, KB version,
  model, evidence hash) as 0600 files (R30a); only grounded answers are cached.

## ADR-014 — Remediation template contract

- **Date:** 2026-10-09 · **Status:** Accepted
- Every template: `set -euo pipefail`; dry run unless `HG_APPLY=1`; refuses to run without
  root; backs up edited files as `<file>.hardengarden-bak.<timestamp>`; idempotent; prints
  each change; validates before committing (`sshd -t` + `sshd -T`, `visudo -c`) and rolls
  back on failure; lock-out guards (no root-SSH self-lockout, no password-auth disable
  without an authorized key, no NOPASSWD removal for a user without a password) that can be
  overridden only with `HG_FORCE=1`. No downloads, no recursive deletes, no `eval`.
- SSH settings go into `/etc/ssh/sshd_config.d/00-hardengarden.conf`, which is read first,
  so its values win under OpenSSH's first-value rule; without `Include`, the main file is
  edited in place.
- **Deliberate deviation:** HG-ACC-001's template contains an extra UID-0 account
  (lock, expire, nologin) but never deletes it or changes its UID, because both are
  destructive and need a human investigation. The re-scan therefore reports WARN
  ("contained"), not PASS. The check reads only the lock flag and expiry date from
  `/etc/shadow`, never the hash.

## ADR-015 — Hardware tiers and model catalog

- **Date:** 2026-10-09 · **Status:** Accepted; model sizes still to be verified
- Tier boundaries use MemTotal at 15.0 / 7.5 / 3.5 GiB, because a nominal 16/8/4 GB machine
  reports slightly less than its nominal size.
- Download sizes in `rag/models.py` (4.7 GB, 1.9 GB, 0.99 GB, 0.27 GB) have not yet been
  verified against ollama.com. They must be checked against
  https://ollama.com/library/qwen2.5/tags before release. During a download the exact byte
  count reported by Ollama is shown.
- AI states add **Model not downloaded** to the five states named in the spec; the UI needs
  it to offer the download dialog.

## ADR-016 — Runtime dependencies: fastapi and uvicorn

- **Date:** 2026-10-09 · **Status:** Accepted (named in docs/REQUIREMENTS.md section 2)
- **Why:** The local API the desktop app talks to. Plain `uvicorn` (not `[standard]`) is
  declared; chromadb already pulls the extras transitively.
- **License / maintenance:** both BSD-3/MIT and actively maintained. FastAPI brings Starlette
  and `opentelemetry-api` (API only, no exporter is configured, so nothing is sent).
- **Dev only:** `httpx` and `httpx2` for test clients. Starlette 1.7 deprecates `httpx` in
  its TestClient in favour of `httpx2` (pydantic/httpx2, BSD-3), and the test suite treats
  warnings as errors.

## ADR-017 — Local API design

- **Date:** 2026-10-09 · **Status:** Accepted
- **Sidecar protocol:** the server binds 127.0.0.1:0 itself (no port race), generates a
  per-launch token (`secrets.token_urlsafe(32)`), and prints one JSON line
  `{"event":"ready","port":N,"token":"..."}` on stdout. The token never touches disk or logs.
  With `--watch-stdin` it exits when the parent closes the pipe, so it never outlives the app.
- **Defence in depth, outermost first:** Host header must be loopback (DNS rebinding) →
  request bodies read and capped at 64 KiB (413) → per-route token buckets (429) → CORS
  limited to the Tauri origins (plus `--dev-origin`, loopback http only) → access log (method,
  path, status, duration; never headers or bodies, redacted JSON) → bearer token on every
  route except `/health`.
- **No browsable schema:** `/docs`, `/redoc` and `/openapi.json` are disabled; the schema
  is still generated and snapshot-tested.
- **Streaming:** `/explain`, `/chat` and `/ai/pull` return NDJSON. The blocking work runs in a
  worker thread; when the client disconnects (the UI's Stop button) the generation or download
  is cancelled immediately.
- **Endpoints beyond the six named in Phase 4**, needed by Phase 5 screens: `GET
  /remediation/{id}` (script as text), `GET /ai/status`, `POST /ai/pull` (body must contain
  `"consent": true`), `GET/PUT /settings` (validated, loopback-only Ollama URL), `POST
  /kb/ingest`. None reads a client-chosen path or runs a client-chosen command (R8).
- **Fixed in this phase:** postponed annotations broke FastAPI's dependency resolution
  (auth became a query parameter); the stream sanitizer was line-buffered, so one-paragraph
  answers did not stream (now streams within a line, with safe cut points).

## ADR-018 — Desktop UI toolchain and runtime dependencies

- **Date:** 2026-10-09 · **Status:** Accepted
- **Package manager: pnpm** (pinned through `packageManager`, enabled with corepack). npm's
  installer crashed on this lockfile in the build environment; pnpm also gives a strict,
  non-hoisted `node_modules`, and `.npmrc` sets `ignore-scripts=true` so no dependency runs
  install scripts. CI installs with `--frozen-lockfile` and runs `pnpm audit`.
- **React 18.3.1, not 19:** Section 2 fixes React 18; Dependabot ignores React majors.
- **TypeScript 5.9.3, not 7:** typescript-eslint 8 does not support TypeScript 7 yet. Revisit
  when it does.
- **Runtime dependencies** (everything else is dev-only tooling):
  - `react`, `react-dom` (MIT, Meta, active): the UI framework fixed by Section 2.
  - `@tauri-apps/api` (Apache-2.0/MIT, Tauri, active): the only way the UI can call the shell
    (`backend_status`). Alternative: none; required by Tauri v2.
  - `@tauri-apps/plugin-clipboard-manager` (Apache-2.0/MIT, Tauri, active): the "Copy script"
    button. `navigator.clipboard` is unreliable in WebKitGTK without a user-gesture permission
    model; the plugin is limited to write-text by the capability file.
  - `@fontsource-variable/recursive` (font: SIL OFL 1.1; package MIT, active): the font is
    bundled into the app so the UI never loads remote fonts (R7). Alternative: system fonts;
    rejected for the design reasons in ADR-020.
- **Rust:** `tauri`, `tauri-build`, `tauri-plugin-clipboard-manager` (Apache-2.0/MIT, active),
  `serde`, `serde_json` (MIT/Apache-2.0, active). The shell uses only the standard library
  for the process lifecycle and the health check (no HTTP client crate). The toolchain is
  pinned in `src-tauri/rust-toolchain.toml`.
- **`@tauri-apps/cli`** is a dev dependency so the build uses a locked CLI version.

## ADR-019 — Sidecar packaging and the desktop capability

- **Date:** 2026-10-09 · **Status:** Accepted
- **Problem:** Tauri's `externalBin` sidecar mechanism expects one executable file, which only
  PyInstaller `--onefile` produces. R32 forbids `--onefile` (it self-extracts into `/tmp`).
- **Decision:** the PyInstaller `--onedir` folder is shipped as a bundle **resource**
  (`binaries/hardengarden-sidecar/` → `sidecar/`) and started by the Rust shell with
  `std::process::Command` (fixed path, fixed arguments `serve --watch-stdin`, no shell).
- **Capability:** the webview gets exactly one permission, `clipboard-manager:allow-write-text`.
  It gets no `shell` permission at all: the webview cannot start, stop or talk to processes;
  only the Rust side starts the scanner. This is stricter than "sidecar + clipboard write" in
  Phase 5, because the sidecar permission would let compromised UI code spawn it with other
  arguments.
- **Lifecycle (R35):** handshake line on stdout → `/health` polled over loopback → `Ready`
  with port and token. Any failure within 15 s (cannot start, exit code, bad handshake, no
  healthy answer) becomes `Failed` with the last 40 stderr lines, which the UI shows with the
  `uv`/`pipx` fallback. After start, a watcher reports a crash the same way. On exit the shell
  closes the scanner's stdin (the scanner exits on EOF) and kills it after 3 s if needed; if the
  shell itself is killed, the closed pipe still stops the scanner (verified: no orphan process
  after SIGTERM).
- **`HARDENGARDEN_SIDECAR`** overrides the scanner path. It exists for the Phase 6 failure test.
  Anyone able to set this variable for the user's session can already run code as that user,
  so it adds no privilege (threat model DS-3).

## ADR-020 — Desktop design system ("garden survey")

- **Date:** 2026-10-09 · **Status:** Accepted
- The UI is modelled on a field survey of a garden bed: each check is a plant in the bed, and
  the plant's form carries its status, so status never depends on colour alone (WCAG 1.4.1):
  sprout = PASS, thistle = FAIL ("Weed"), drooping = WARN ("Needs care"), seed = SKIPPED
  ("Not checked"), withered = ERROR, dashed soil = NOT_APPLICABLE. Each glyph is paired with
  its word wherever it appears.
- **Palette** (light / dark tokens in `src/styles.css`): lichen `#e9eee6` background, leaf-paper
  `#f7f9f4` surfaces, moss `#1f2b22` text, thistle `#8b2f6f` for failures, pollen `#6f5300` for
  warnings, fern `#2b6537` for healthy. Contrast is checked by axe in both schemes in the E2E
  suite (zero serious violations).
- **Type:** one family, Recursive (variable), bundled locally. Its casual axis is used for
  headings, its linear form for body text and its monospace axis for evidence and scripts.
- **Strict CSP without `'unsafe-inline'`:** no inline styles anywhere; components use classes.
