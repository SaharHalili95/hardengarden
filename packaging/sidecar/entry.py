"""Entry point that PyInstaller freezes into the desktop app's scanner (hardengarden-sidecar).

It is the full ``hardengarden`` CLI, so the packaged scanner also answers ``scan --json``.
"""

from hardengarden.cli import app

if __name__ == "__main__":
    app(prog_name="hardengarden")
