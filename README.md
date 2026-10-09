# HardenGarden

**AI-assisted Linux hardening auditor.** *Your system is a garden. HardenGarden finds the weeds.*

> **Project status: Phase 0 (foundation).** The repository, tooling, CI and
> security documents are in place. The scanner, knowledge base, explanations and
> desktop app do **not** exist yet. See [Roadmap](#roadmap).

> HardenGarden is an educational/portfolio security tool. It is not a certified
> compliance scanner and does not replace a professional audit.

## What it will do

Everything in this section is planned, not built. It moves out of this section only
when it exists and is tested.

1. Scan the local Linux machine with **read-only** checks (SSH, firewall, file
   permissions, accounts, updates, kernel settings).
2. Report deterministic findings ("weeds") with severity, evidence and a
   **Garden Health** score. No AI is involved in scoring.
3. Explain each finding in plain language with a **local** LLM (Ollama), grounded
   in an original knowledge base, with citations. It refuses instead of guessing.
4. Show a **vetted remediation script** you may review and run yourself. HardenGarden
   never runs it and never changes your system.
5. Ship as a desktop app (`.deb`, `.AppImage`) and a CLI.

## Security model in one paragraph

Read-only checks. No privilege escalation. No command execution from the UI. The
local API binds to `127.0.0.1` with a per-launch token. No telemetry, no cloud,
no network traffic except to your local Ollama. See
[`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) and [`SECURITY.md`](SECURITY.md).

## Development

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync                      # create the environment from uv.lock
uv run pytest                # tests + coverage
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy                  # strict type checking
uv run bandit -c pyproject.toml -r hardengarden
uv run pre-commit install    # run all of the above before every commit
```

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundation: repo, tooling, CI, threat model | in review |
| 1 | Scanner core, 12 checks, CLI | not started |
| 2 | Knowledge base and retrieval | not started |
| 3 | LLM explanations and remediation templates | not started |
| 4 | Local API | not started |
| 5 | Desktop app | not started |
| 6 | Packaging, signing, release | not started |
| 7 | Documentation and polish | not started |

## License

[Apache-2.0](LICENSE)
