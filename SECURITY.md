# Security Policy

HardenGarden is a security tool, so we take vulnerabilities in it seriously.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub Private Vulnerability Reporting:
<https://github.com/SaharHalili95/hardengarden/security/advisories/new>

Please include:

- the affected version or commit,
- the distribution and version you ran it on,
- steps to reproduce, and
- the impact you believe it has.

## What to expect

This is a single-maintainer project. Best-effort targets:

| Step | Target |
|---|---|
| Acknowledge the report | within 7 days |
| Initial assessment | within 14 days |
| Fix or mitigation for confirmed HIGH/CRITICAL issues | as fast as practical, normally within 30 days |

You will be credited in the advisory unless you ask not to be.

## Supported versions

HardenGarden has not had a stable release yet. Only the latest commit on `main`
and the latest pre-release receive fixes.

## In scope

Anything that breaks a promise in the project's security model, for example:

- a check or any other code path that **writes to, or changes**, the scanned system;
- the application **executing** a remediation script, or escalating privileges;
- the local API being reachable from anything other than `127.0.0.1`, or usable without its token;
- **network egress** to anything other than the local Ollama endpoint;
- sensitive evidence (password hashes, keys, tokens) appearing in logs, caches or LLM prompts;
- **prompt injection** from scanned content that changes findings, scores or shown commands;
- supply-chain issues in released artifacts (signatures, SBOM, checksums).

## Out of scope

- Findings produced by HardenGarden about *your own* system. Those are the product working as designed.
- Vulnerabilities in Ollama, the models, or the operating system itself. Please report those upstream.
- The quality of LLM explanations, unless it causes one of the in-scope problems above.

HardenGarden is an educational/portfolio security tool. It is not a certified
compliance scanner and does not replace a professional audit.
