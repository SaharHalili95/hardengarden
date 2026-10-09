# HardenGarden — Requirements

This document defines what HardenGarden is, the technology it uses, the rules every change
must follow, and the phases it is built in. Rules are numbered (R1–R39) and referenced from
code, tests and `docs/DECISIONS.md`. Decisions that interpret or deviate from a rule are
recorded as ADRs.

---

## 1. Product definition

**Name:** HardenGarden (brand) — `hardengarden` (repo, Python package, CLI, binaries).
**Tagline:** AI-assisted Linux hardening auditor. *Your system is a garden — HardenGarden finds the weeds.*

**What it does**
1. Scans the local Linux machine with a set of **read-only** security checks (SSH, firewall, permissions, updates, kernel settings, accounts).
2. Produces deterministic findings ("weeds") with severity, evidence and a "Garden Health" score.
3. Uses a **local RAG pipeline** (ChromaDB + Ollama) to explain each finding in plain language, grounded in a curated knowledge base, with citations.
4. Shows a **vetted remediation script** per finding that the *user* may copy and run. The app itself never changes the system.
5. Ships as a **downloadable desktop app** (`.deb` and `.AppImage`) plus a CLI.

**Non-goals (do NOT build)**
- No automatic remediation, no "fix it for me" button that executes commands.
- No remote scanning of other hosts, no network scanning, no agents on other machines.
- No cloud services, no accounts, no telemetry, no analytics, no auto-update phoning home.
- No claim of being a certified compliance tool (CIS/STIG/etc.).

**Supported platforms:** Ubuntu 22.04, Ubuntu 24.04, Debian 12. On any other distro the app must run, but mark platform-specific checks as `NOT_APPLICABLE` and show a clear "unsupported platform" notice.

---

## 2. Fixed technology stack (do not substitute)

| Layer | Choice |
|---|---|
| Language (backend) | Python 3.12 |
| Packaging / env | `uv` with a committed lockfile |
| CLI | Typer |
| API | FastAPI + Pydantic v2 + Uvicorn |
| Vector store | ChromaDB (local persistent, embedded mode) |
| LLM runtime | Ollama, local only. Default chat model `qwen2.5:7b-instruct`, embeddings `nomic-embed-text`. Model names configurable. |
| Desktop | Tauri v2 + React 18 + TypeScript (strict) + Vite |
| Backend in desktop | Backend bundled as a Tauri **sidecar** binary (PyInstaller **`--onedir` mode only**, see R31–R33), started/stopped by the app |
| Python quality | ruff (lint + format), mypy `--strict`, pytest, pytest-cov, bandit, pip-audit |
| Shell quality | shellcheck on every shipped shell script |
| Frontend quality | ESLint, Prettier, Vitest, Playwright (against the web build) |
| CI/CD | GitHub Actions, CodeQL, Trivy (fs scan), Syft (SBOM), Dependabot |
| License | Apache-2.0 |

Adding **any** new runtime dependency requires a one-paragraph justification in `docs/DECISIONS.md` (why needed, alternatives considered, license, maintenance status). Prefer the standard library.

---

## 3. Rules

Rules use MUST / MUST NOT. Every rule applies in every phase.

### 3.1 System safety
- **R1.** All checks MUST be **read-only**. No check may write, delete, chmod, chown, restart, install, or modify anything on the host.
- **R2.** The application MUST NOT execute remediation commands. Remediation is displayed text only.
- **R3.** The application MUST NOT escalate privileges (no `sudo`, `pkexec`, `su`, setuid). If a check needs root and the process is not root, the result is `SKIPPED` with reason `insufficient_privileges`. The user may choose to run the CLI with `sudo` themselves; the GUI never asks for or stores a password.
- **R4.** Subprocess calls MUST use: a fixed argument list, `shell=False`, an absolute binary path resolved from an allowlist, a timeout (≤10s), and captured output. Any binary not on the allowlist is forbidden.
- **R5.** Forbidden everywhere: `shell=True`, `os.system`, `eval`, `exec`, `pickle`/`marshal` on untrusted data, `yaml.load` without SafeLoader, string-built shell commands, `subprocess` with user-controlled arguments.
- **R6.** File reads MUST go through a single `SystemView` abstraction with a configurable root path (default `/`), size limits (≤1 MB per file), and no symlink following outside the root. This is also what makes checks testable.

### 3.2 Data & privacy
- **R7.** Zero network egress except to the local Ollama endpoint (`127.0.0.1` only). No telemetry, no crash reporting, no remote fonts/CDNs/images in the UI.
- **R8.** The API MUST bind to `127.0.0.1` only, on a random free port, and require a random per-launch bearer token (≥32 bytes from `secrets`). Strict CORS (only the Tauri origin). No API endpoint exposes arbitrary file reads or command execution.
- **R9.** Evidence collected from the system (file snippets, usernames, ports) is sensitive. It MUST be minimized (only what proves the finding), redacted in logs (hashes, passwords, keys, tokens never logged or stored), and never leave the machine.
- **R10.** No secrets in the repo, ever. `.gitignore` and a secret-scanning step in CI (gitleaks) are mandatory from Phase 0.

### 3.3 AI / RAG reliability
- **R11.** Check results, severities and the Garden Health score MUST be **100% deterministic** and computed without the LLM. The LLM only explains.
- **R12.** Remediation scripts MUST come from **vetted, version-controlled templates** (`backend/hardengarden/remediation/templates/`), one per check, reviewed by tests (shellcheck + snapshot). The LLM MUST NOT generate commands that are presented as runnable.
- **R13.** Every LLM answer MUST be grounded: it cites the knowledge-base chunk IDs it used. If retrieval confidence is below the configured threshold, the answer is a fixed "Not enough information in the knowledge base" message — never a guess.
- **R14.** Generation settings: temperature 0, bounded max tokens, fixed system prompt stored in the repo.
- **R15.** **Prompt-injection defense:** any text that originates from the scanned system (config contents, banners, hostnames, file names) is untrusted DATA. It MUST be passed to the LLM inside clearly delimited data blocks, with the system prompt stating it is not instructions. LLM output is rendered as text only (no HTML injection, no markdown links to arbitrary URLs, never executed).
- **R16.** If Ollama is not installed or not running, the app MUST still work fully for scanning, scoring and remediation templates; only the "Explain"/chat features show a clear, actionable message.
- **R17.** Never invent identifiers. No made-up CVE numbers, CIS control numbers, or man-page sections. HardenGarden uses its own IDs (`HG-SSH-001`). External references are URLs to public sources that were actually consulted.

### 3.4 Legal / IP
- **R18.** Do NOT copy text from CIS Benchmarks or any licensed standard into the repo. Knowledge-base documents in `knowledge/` MUST be original writing, each with a "References" list of public URLs (e.g. official distro docs, OpenSSH manual, kernel docs).
- **R19.** Local man pages may be ingested **at runtime from the user's own system** into the local vector store. They MUST NOT be committed to the repo or redistributed in packages.

### 3.5 Engineering process
- **R20.** Work **phase by phase** (Section 6). A phase starts only after the previous phase's gate has passed.
- **R21.** At the end of every phase, the full test + lint + security suite runs and the results are recorded.
- **R22.** Never delete, skip, weaken, or `xfail` a test to make a build pass. Never lower a coverage threshold. A failing test means the code is wrong until proven otherwise.
- **R23.** No `TODO`, `FIXME`, placeholder functions, `pass`-only bodies, fake data presented as real, or "mock implementation for now" in shipped code. If something is out of scope for the phase, it does not exist yet — it is not stubbed.
- **R24.** `# noqa`, `# type: ignore`, `# nosec`, `eslint-disable` are allowed only with an inline justification comment, and each one is reviewed in the pull request that adds it.
- **R25.** Git: one logical change per commit, Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `ci:`, `chore:`), a branch per phase (`phase-N-short-name`) merged via PR with CI green. Never force-push to `main`. Never commit generated build artifacts.
- **R26.** This document changes only through a reviewed pull request that explains why. Rules are never relaxed silently in code.
- **R27.** An unclear requirement is clarified (and recorded in `docs/DECISIONS.md`) before it is implemented. A wrong assumption that costs a rewrite is worse than a question.

### 3.6 Cost discipline
- **R28.** Local models only; no paid APIs.
- **R29.** Smallest change that fully satisfies the phase. Do not rewrite working files, do not regenerate whole files to change a few lines, do not add frameworks "for later".
- **R30.** CI must stay within the GitHub free tier: cache dependencies, run heavy jobs (packaging, Trivy, CodeQL) only on PRs to `main` and on tags.
- **R30a.** Cache LLM explanations locally, keyed by (check_id, KB version hash, model name, evidence hash). A repeated "Explain" must not call the model again.

### 3.7 Portability (packaging & sidecar)
- **R31.** **glibc baseline:** all native binaries (PyInstaller sidecar and the Tauri app) MUST be built inside an **Ubuntu 22.04** environment (glibc 2.35, the oldest supported target), never on a newer one. Binaries built on newer glibc fail on older distros. Record the build glibc version in the release notes.
- **R32.** PyInstaller MUST use **`--onedir`**, never `--onefile`. Reason: `--onefile` self-extracts into `/tmp`, and hardened systems mount `/tmp` with `noexec`. A hardening tool that breaks on hardened systems is unacceptable.
- **R33.** The `.deb` MUST declare its real runtime dependencies (e.g. `libwebkit2gtk-4.1-0`, `libgtk-3-0`) in `Depends:`. The AppImage bundles everything except glibc. Do not bundle or vendor glibc.
- **R34.** The CLI MUST also be installable without the desktop app via `pipx install hardengarden` (pure-Python path, no native build), as a fallback when the desktop package fails on a given distro.
- **R35.** If the sidecar fails to start (crash, missing lib, port conflict, health check timeout of 15s), the app MUST show a specific error with the sidecar's last log lines and the `pipx` fallback instructions. It must never hang on a blank window.

### 3.8 Hardware tiers (local LLM)
- **R36.** On first launch, and in Settings, detect available RAM, CPU cores and GPU (via Ollama's own info when available) **without root**, and pick a model tier:

  | Available RAM | Chat model | Notes |
  |---|---|---|
  | ≥ 16 GB | `qwen2.5:7b-instruct` | default, best quality |
  | 8–16 GB | `qwen2.5:3b-instruct` | |
  | 4–8 GB | `qwen2.5:1.5b-instruct` | show "reduced quality" badge |
  | < 4 GB or no Ollama | AI disabled | scanning, score and templates still fully work (R16) |

  The embedding model (`nomic-embed-text`, ~275 MB) is the same in all tiers so the vector store never needs re-indexing when the tier changes. The user can override the tier in Settings, with a warning.
- **R37.** NEVER download a model automatically. Show model name and download size, and require an explicit click. Downloads are handled by Ollama (`ollama pull`), with progress and cancel.
- **R38.** Generation MUST stream tokens to the UI, have a hard timeout (default 120 s, configurable), and a working Cancel button. A slow model must never freeze the UI or block a scan.
- **R39.** Before each generation, check free RAM. If it is below the model's requirement, do not start; show "Not enough free memory for model X — close apps or switch to a smaller model".

---

## 4. Repository structure (must match)

```
hardengarden/
├── README.md
├── LICENSE                       # Apache-2.0
├── SECURITY.md                   # vuln reporting policy
├── docs/
│   ├── ARCHITECTURE.md
│   ├── THREAT_MODEL.md
│   ├── DECISIONS.md              # ADR-style log
│   ├── REQUIREMENTS.md           # this document
│   └── CHECKS.md                 # generated table of all checks
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── hardengarden/
│   │   ├── core/                 # SystemView, CommandRunner, models, scoring
│   │   ├── checks/               # one module per category
│   │   ├── remediation/templates/
│   │   ├── rag/                  # ingest, retrieve, generate, prompts/
│   │   ├── api/                  # FastAPI app
│   │   └── cli.py
│   └── tests/
│       ├── fixtures/systems/     # fake filesystem roots per scenario
│       ├── unit/ integration/ security/ rag_eval/
├── knowledge/                    # original KB docs (markdown, one per topic)
├── desktop/                      # Tauri + React app
└── .github/
    ├── workflows/ (ci.yml, release.yml, codeql.yml)
    └── dependabot.yml
```

---

## 5. Core design contracts

### 5.1 Check model
```python
class Severity(StrEnum): CRITICAL, HIGH, MEDIUM, LOW, INFO
class Status(StrEnum):   PASS, FAIL, WARN, ERROR, SKIPPED, NOT_APPLICABLE

class CheckMeta(BaseModel):          # static, declared per check
    id: str            # e.g. "HG-SSH-001", unique, stable forever
    title: str
    category: str      # ssh | firewall | filesystem | accounts | updates | kernel | logging
    severity: Severity
    rationale: str     # 1–3 sentences, original text
    requires_root: bool
    platforms: list[str]
    kb_doc: str        # path in knowledge/
    remediation_template: str | None

class CheckResult(BaseModel):
    check_id: str
    status: Status
    evidence: list[str]   # minimized + redacted, max 10 items
    reason: str | None    # for SKIPPED / ERROR / NOT_APPLICABLE
    duration_ms: int
```
- Every check is a pure function of (`SystemView`, `CommandRunner`, `Platform`) → `CheckResult`.
- A crashing check returns `ERROR` with a safe message; it never crashes the scan.

### 5.2 Garden Health score (deterministic)
- Weights: CRITICAL 10, HIGH 6, MEDIUM 3, LOW 1, INFO 0.
- Score = 100 × (1 − (Σ weight(FAIL) + 0.5 × Σ weight(WARN)) ÷ Σ weight(applicable checks)). Clamp to 0–100, round to an integer. If the denominator is 0, the score is `null` (shown as "Not enough data"), never 100.
- `SKIPPED`, `ERROR`, `NOT_APPLICABLE` are excluded from the denominator and reported separately ("coverage").
- The formula lives in one function with exhaustive unit tests.

### 5.3 Initial check set (Phase 1 scope — exactly these 12)
| ID | Check |
|---|---|
| HG-SSH-001 | SSH root login disabled (`PermitRootLogin`) |
| HG-SSH-002 | SSH password authentication disabled |
| HG-SSH-003 | SSH empty passwords disallowed |
| HG-FW-001 | Host firewall active (ufw or nftables ruleset present) |
| HG-NET-001 | Listening services on non-loopback interfaces (inventory, WARN if any unexpected) |
| HG-FS-001 | `/etc/shadow` permissions and owner |
| HG-FS-002 | `/etc/passwd` and `/etc/group` permissions |
| HG-FS-003 | World-writable files under `/etc` |
| HG-ACC-001 | Accounts with UID 0 other than root |
| HG-ACC-002 | `NOPASSWD` entries in sudoers |
| HG-UPD-001 | Automatic security updates enabled (unattended-upgrades) |
| HG-KRN-001 | ASLR enabled (`kernel.randomize_va_space = 2`) |

`sshd` config parsing MUST handle `Include` directives, `Match` blocks (report as WARN "conditional override"), comments, case-insensitivity, and the OpenSSH "first value wins" rule. Use `sshd -T` when available and permitted; fall back to file parsing.

---

## 6. Phases, deliverables, tests and gates

Each phase lists: **Deliverables → Required tests → Gate (must all be true)**.

### Phase 0 — Foundation
**Deliverables:** repo skeleton (Section 4), LICENSE, SECURITY.md, README skeleton, `docs/THREAT_MODEL.md` (STRIDE table covering: local attacker, malicious config content → prompt injection, malicious KB doc, API exposure, supply chain, privilege misuse), `docs/DECISIONS.md`, uv project, ruff/mypy/pytest/bandit/pip-audit config, pre-commit hooks, `ci.yml` (lint, type-check, tests, bandit, pip-audit, gitleaks), Dependabot.
**Required tests:** a smoke test that imports the package; CI runs green on an empty-but-valid project.
**Gate:** CI green · threat model reviewed in the report · zero warnings from ruff/mypy/bandit.

### Phase 1 — Scanner core + 12 checks + CLI
**Deliverables:** `SystemView`, `CommandRunner` (allowlist + timeouts), platform detection, the 12 checks, scoring, `hardengarden scan [--json] [--root PATH]`, `docs/CHECKS.md` generated from metadata.
**Required tests:**
- Fixture filesystems per scenario (`hardened/`, `default_ubuntu_2404/`, `misconfigured/`, `edge_cases/`) — every check tested for PASS, FAIL, and at least one edge case (missing file, unreadable file, include loop, malformed config).
- `CommandRunner` tests: rejects non-allowlisted binaries, enforces timeout, never uses a shell.
- Security tests: a static test that greps the codebase and fails on any R5 pattern; symlink-escape test for `SystemView`.
- Scoring: table-driven tests incl. all-skipped, all-pass, all-fail.
- Read-only guarantee: run the full scan against a fixture root inside a read-only mount / with write-blocking monkeypatch; assert zero write attempts.
**Gate:** coverage ≥ 90% for `core/` and `checks/` · all security tests pass · `hardengarden scan` works on a real Ubuntu 24.04 VM/container (paste sanitized output in the report).

### Phase 2 — Knowledge base + retrieval
**Deliverables:** one original KB doc per check in `knowledge/` (What it is · Why it matters · How attackers abuse it · How to verify · How to fix · References), ingestion pipeline (chunking with stable chunk IDs + doc version hash), optional runtime ingestion of local man pages (R19), retrieval API with score threshold.
**Required tests:**
- `rag_eval/golden.yaml`: ≥ 40 question → expected-doc pairs (≥ 3 per check + negative questions with no answer).
- Metrics: Recall@5 ≥ 0.90 on answerable questions; ≥ 0.95 of negative questions fall below the threshold.
- Ingestion is idempotent (re-ingest = no duplicates), deterministic chunk IDs.
- Linter test: every check has a KB doc, every KB doc has ≥ 1 reference URL, no doc exceeds size limits.
**Gate:** metrics met and printed in the report · ingestion < 60 s on a laptop CPU.

### Phase 3 — Explanation (LLM) + remediation templates
**Deliverables:** system prompt file, generation module (R13–R16), `hardengarden explain HG-SSH-001`, one remediation template per FAIL-able check (idempotent, uses `set -euo pipefail`, backs up any file before editing, prints what it changes, no destructive defaults).
**Required tests:**
- shellcheck passes on all templates; snapshot tests of rendered templates.
- Templates executed **only inside disposable Docker containers** in CI against the `misconfigured` scenario → re-scan shows the check now PASS (proves the fix works) and the container still boots SSH (proves it did not lock the user out).
- Grounding tests with a stubbed LLM: citations required, refusal path below threshold, Ollama-down path (R16).
- Prompt-injection tests: fixture configs containing "ignore previous instructions…" — output must not follow them and must not contain commands outside templates.
- Live smoke test (manual, documented in the report): 3 real explanations with `qwen2.5:7b-instruct`.
- **Tier tests (R36–R39):** tier selection table-driven over simulated RAM values; low-memory guard blocks generation; timeout and cancel actually stop the request; no model download without explicit consent.
- **Small-model evaluation:** run the grounding/refusal tests with **both** `qwen2.5:7b-instruct` and `qwen2.5:1.5b-instruct`. Citation rate and refusal behavior must meet the same bar on both; if the 1.5B model fails, report it and propose a fix (do not silently lower the bar).
- Cache test (R30a): second identical "Explain" makes zero model calls.
**Gate:** all of the above green · no LLM-generated command shown as runnable anywhere.

### Phase 4 — Local API
**Deliverables:** FastAPI app: `POST /scan`, `GET /results/{id}`, `GET /checks`, `POST /explain`, `POST /chat`, `GET /health`. Token auth, loopback bind, strict CORS, request size limits, rate limiting, structured logging with redaction.
**Required tests:** auth required on every route (except `/health`), wrong token → 401, non-loopback bind impossible via config, CORS rejection test, oversize request → 413, OpenAPI schema snapshot, redaction test on logs.
**Gate:** coverage ≥ 85% for `api/` · bandit clean · security test suite green.

### Phase 5 — Desktop app
**Deliverables:** Tauri v2 app with screens: Dashboard (Garden Health gauge + coverage), Weeds list (filter by severity/category), Weed detail (evidence, Explain, remediation template with Copy button and a clear "Review before running" warning), Chat (grounded, shows citations), Settings (Ollama URL/models, re-ingest KB). Sidecar lifecycle (start, health-check, stop on exit). Garden theme, accessible (WCAG AA contrast, keyboard navigation), dark/light.
**Security requirements:** strict CSP (no remote origins, no `unsafe-eval`), Tauri capability allowlist (only sidecar + clipboard write), no `dangerouslySetInnerHTML`, LLM text rendered as plain text.
**UI for hardware/AI states:** an "AI status" indicator (Ready · Reduced quality · Not enough memory · Ollama not installed · Disabled) with a one-click explanation of what to do; model download dialog with size, progress and cancel; streaming answers with a Stop button.
**Required tests:** Vitest component tests for every screen and every AI status state; Playwright E2E against the web build with a mocked API (scan → view weed → explain → copy); CSP test; a11y check (axe) with zero serious violations.
**Gate:** all tests green · manual run on Ubuntu 24.04 documented with screenshots.

### Phase 6 — Packaging, supply chain, release
**Deliverables:** `release.yml` on tag `v*`: build sidecar (PyInstaller), build `.deb` + `.AppImage`, generate SBOM (Syft, SPDX), SHA-256 checksums, sign artifacts (Sigstore/cosign keyless via GitHub OIDC), Trivy scan with build failing on HIGH/CRITICAL, CodeQL workflow, GitHub Release with notes from Conventional Commits.
**Required tests:**
- **Distro matrix:** install the `.deb` in clean `ubuntu:22.04`, `ubuntu:24.04` and `debian:12` containers; in each, the sidecar starts, `/health` responds, and `hardengarden scan --json` succeeds.
- AppImage headless smoke test (Xvfb) on the same three distros.
- **`noexec /tmp` test:** run the sidecar with `/tmp` mounted `noexec` — it must work (proves R32).
- **glibc check:** CI step that inspects the built binaries (`objdump -T` / `ldd`) and fails if any symbol requires glibc > 2.35.
- `pipx install` of the built wheel works on all three distros (R34).
- Sidecar failure test: break the sidecar on purpose → the app shows the R35 error screen, not a blank window.
- Checksum + signature verification step in CI.
**Gate:** a `v0.1.0` pre-release exists with verified signatures, SBOM, and zero HIGH/CRITICAL findings.

### Phase 7 — Documentation & portfolio polish
**Deliverables:** README (what/why, 30-sec demo GIF, install, usage, architecture diagram, security model summary, honest limitations, roadmap), `ARCHITECTURE.md`, final `THREAT_MODEL.md`, `CHECKS.md`, CONTRIBUTING.md, badges (CI, CodeQL, license, release).
**Required tests:** link checker on docs; README commands executed in CI.
README MUST include a **System requirements** table: minimum (scanner only: any supported distro, 1 GB RAM) and per AI tier (RAM, disk for model, expected answer time on CPU vs GPU, measured — not guessed — on the dev machine and stated as such).
**Gate:** a reviewer can install and run it from the README alone in < 5 minutes.

---

## 7. Definition of Done (whole project)
- All phase gates passed.
- `main` is protected, CI green, no open HIGH/CRITICAL alerts (Dependabot, CodeQL, Trivy).
- Every feature in the README exists and is tested. Nothing in the README is aspirational unless it is under "Roadmap".
- README states clearly: *HardenGarden is an educational/portfolio security tool. It is not a certified compliance scanner and does not replace a professional audit.*

---
