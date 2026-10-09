"""Starts the API for the desktop app (the Tauri sidecar entry point).

Protocol with the parent process:
1. The server binds 127.0.0.1 on a random free port (R8) and generates a fresh token.
2. It prints ONE JSON line to stdout: ``{"event": "ready", "port": N, "token": "..."}``.
   The token travels only over this private pipe; it is never logged or written to disk.
3. With ``--watch-stdin`` it shuts down when stdin closes, so it never outlives the app.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path

import uvicorn

from .app import ApiState, create_app
from .security import configure_logging, new_token, require_loopback, validate_dev_origin

HOST = "127.0.0.1"


def bind_socket(host: str = HOST) -> socket.socket:
    require_loopback(host)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, 0))
    sock.listen(64)
    sock.set_inheritable(False)
    return sock


def _watch_stdin(server: uvicorn.Server) -> None:
    def wait() -> None:
        try:
            while sys.stdin.read(4096):
                pass
        except (OSError, ValueError):
            pass
        server.should_exit = True

    threading.Thread(target=wait, daemon=True, name="stdin-watch").start()


def serve(
    *,
    root: Path = Path("/"),
    dev_origins: tuple[str, ...] = (),
    watch_stdin: bool = False,
    host: str = HOST,
) -> None:
    sock = bind_socket(host)
    state = ApiState(
        token=new_token(),
        scan_root=root,
        dev_origins=tuple(validate_dev_origin(o) for o in dev_origins),
    )
    configure_logging(sys.stderr)
    config = uvicorn.Config(
        create_app(state), log_config=None, access_log=False, lifespan="off", server_header=False
    )
    server = uvicorn.Server(config)
    if watch_stdin:
        _watch_stdin(server)
    port = sock.getsockname()[1]
    sys.stdout.write(json.dumps({"event": "ready", "port": port, "token": state.token}) + "\n")
    sys.stdout.flush()
    server.run(sockets=[sock])
