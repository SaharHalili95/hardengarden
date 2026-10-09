#!/usr/bin/env python3
"""Smoke test for a packaged HardenGarden scanner (the desktop sidecar or a pipx/uv install).

Standard library only, Python >= 3.10, so it runs on every supported distro's system Python.

    smoke_scanner.py PATH_TO_SCANNER [--expect-noexec-tmp]

Checks, in order:
  1. ``scan --json`` returns 12 results with known statuses.
  2. ``serve --watch-stdin`` prints the handshake; ``/health`` answers; ``/checks`` needs the
     token (401 without, 200 with); closing stdin stops the server.
  3. The vector store works in the packaged build: ``kb ingest`` against a stand-in Ollama
     that serves embeddings, then ``kb search`` (proves chromadb is bundled correctly).
  4. With ``--expect-noexec-tmp``: ``/tmp`` really is mounted noexec, so steps 1-3 passing
     proves the scanner never executes from ``/tmp`` (R32).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATUSES = {"PASS", "FAIL", "WARN", "ERROR", "SKIPPED", "NOT_APPLICABLE"}


def fail(message: str) -> None:
    print(f"FAIL  {message}", flush=True)
    sys.exit(1)


def ok(message: str) -> None:
    print(f"PASS  {message}", flush=True)


def run(scanner: str, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(  # fixed argument list, no shell
        [scanner, *args], capture_output=True, text=True, timeout=120, env=env, check=False
    )
    if result.returncode != 0:
        fail(f"{' '.join(args)} exited {result.returncode}:\n{result.stderr[-2000:]}")
    return result.stdout


def check_scan(scanner: str) -> None:
    report = json.loads(run(scanner, "scan", "--json"))
    results = report["results"]
    if len(results) != 12:
        fail(f"scan --json returned {len(results)} results, expected 12")
    unknown = {r["status"] for r in results} - STATUSES
    if unknown:
        fail(f"unknown statuses {unknown}")
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    ok(f"scan --json: 12 results {counts}, platform {report['platform'].get('pretty_name')!r}")


def http(url: str, token: str | None = None) -> int:
    request = urllib.request.Request(url)  # noqa: S310 - loopback URL built by this script
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - loopback
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


def check_serve(scanner: str) -> None:
    started = time.monotonic()
    process = subprocess.Popen(  # the scanner under test, fixed arguments
        [scanner, "serve", "--watch-stdin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdin is not None
        line = process.stdout.readline()
        handshake = json.loads(line)
        if handshake.get("event") != "ready":
            fail(f"unexpected handshake {line!r}")
        base = f"http://127.0.0.1:{handshake['port']}"
        if http(f"{base}/health") != 200:
            fail("/health did not answer 200")
        if http(f"{base}/checks") != 401:
            fail("/checks without a token was not rejected with 401")
        if http(f"{base}/checks", handshake["token"]) != 200:
            fail("/checks with the token did not answer 200")
        ok(f"serve: ready and healthy after {time.monotonic() - started:.1f} s, token enforced")
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            fail("serve kept running after its stdin was closed")
        ok("serve: exits when the parent closes stdin")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


class _Embeddings(BaseHTTPRequestHandler):
    """Answers Ollama's /api/embed and /api/tags with deterministic vectors (no model)."""

    def log_message(self, *_: object) -> None:
        return

    def _send(self, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # http.server naming
        self._send({"models": [{"name": "nomic-embed-text:latest"}], "version": "smoke"})

    def do_POST(self) -> None:  # http.server naming
        length = int(self.headers.get("Content-Length", "0"))
        texts = json.loads(self.rfile.read(length) or b"{}").get("input", [])
        vectors = [[float(len(t) % 7) + 1.0, float(len(t.split()) % 5) + 1.0] for t in texts]
        self._send({"embeddings": vectors})


def check_vector_store(scanner: str) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Embeddings)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as home:
            data = Path(home) / "data" / "hardengarden"
            data.mkdir(parents=True, mode=0o700)
            url = f"http://127.0.0.1:{server.server_address[1]}"
            (data / "settings.json").write_text(json.dumps({"ollama_url": url}))
            env = dict(os.environ, HOME=home, XDG_DATA_HOME=str(Path(home) / "data"))
            env["XDG_CACHE_HOME"] = str(Path(home) / "cache")
            output = run(scanner, "kb", "ingest", env=env)
            if "Vectors [" not in output:
                fail(f"kb ingest did not build the vector index:\n{output}")
            if not any((data).rglob("*.sqlite3")):
                fail("kb ingest left no vector store on disk")
            search = run(scanner, "kb", "search", "is root login over ssh allowed", env=env)
            if "keyword + vector" not in search or "ssh-root-login#" not in search:
                fail(f"kb search did not find the SSH root login document:\n{search}")
            ok("vector store: kb ingest built the index; vector search finds the right document")
    finally:
        server.shutdown()
        server.server_close()


def check_noexec_tmp() -> None:
    for line in Path("/proc/mounts").read_text().splitlines():
        fields = line.split()
        if len(fields) > 3 and fields[1] == "/tmp":
            if "noexec" in fields[3].split(","):
                ok(f"/tmp is mounted noexec ({fields[3]}); every check above ran under it")
                return
            fail(f"/tmp is mounted without noexec: {fields[3]}")
    fail("/tmp is not a separate mount, so noexec cannot be verified")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scanner", help="path to the packaged scanner executable")
    parser.add_argument("--expect-noexec-tmp", action="store_true")
    args = parser.parse_args()
    if args.expect_noexec_tmp:
        check_noexec_tmp()
    check_scan(args.scanner)
    check_serve(args.scanner)
    check_vector_store(args.scanner)
    print("ALL SMOKE CHECKS PASSED", flush=True)


if __name__ == "__main__":
    main()
