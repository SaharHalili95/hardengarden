"""Static R5 guard: fails on any forbidden construct anywhere in shipped Python code.

AST-based (ADR-002 item 9), so words such as "execute" in prose or
identifiers do not cause false positives, while real calls cannot hide behind formatting.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "hardengarden"
RUNNER_MODULE = PACKAGE / "core" / "runner.py"

FORBIDDEN_CALLS = {
    "eval", "exec", "compile", "__import__",
    "os.system", "os.popen", "os.execl", "os.execle", "os.execlp", "os.execlpe", "os.execv",
    "os.execve", "os.execvp", "os.execvpe", "os.spawnl", "os.spawnle", "os.spawnlp",
    "os.spawnlpe", "os.spawnv", "os.spawnve", "os.spawnvp", "os.spawnvpe", "os.posix_spawn",
    "os.posix_spawnp", "os.fork", "os.forkpty",
    "pickle.load", "pickle.loads", "marshal.load", "marshal.loads", "shelve.open",
    "yaml.load", "yaml.unsafe_load", "yaml.full_load",
    "pty.spawn", "commands.getoutput",
}  # fmt: skip
FORBIDDEN_IMPORTS = {"pickle", "marshal", "shelve", "commands", "pty"}
SUBPROCESS_FUNCS = {
    "run",
    "Popen",
    "call",
    "check_call",
    "check_output",
    "getoutput",
    "getstatusoutput",
}


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    what: str


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def scan_source(source: str, filename: str, *, allow_subprocess: bool) -> list[Violation]:
    tree = ast.parse(source, filename=filename)
    found: list[Violation] = []

    def add(node: ast.AST, what: str) -> None:
        found.append(Violation(filename, getattr(node, "lineno", 0), what))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_IMPORTS:
                    add(node, f"import {alias.name}")
                if root == "subprocess" and not allow_subprocess:
                    add(node, "subprocess outside core/runner.py")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in FORBIDDEN_IMPORTS:
                add(node, f"from {node.module} import ...")
            if root == "subprocess" and not allow_subprocess:
                add(node, "subprocess outside core/runner.py")
            if root == "os":
                for alias in node.names:
                    if f"os.{alias.name}" in FORBIDDEN_CALLS:
                        add(node, f"from os import {alias.name}")
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name in FORBIDDEN_CALLS:
                if name == "yaml.load" and any(
                    kw.arg == "Loader" and "SafeLoader" in _dotted(kw.value) for kw in node.keywords
                ):
                    continue
                add(node, f"call to {name}()")
            for kw in node.keywords:
                if kw.arg == "shell" and not (
                    isinstance(kw.value, ast.Constant) and kw.value.value is False
                ):
                    add(node, "shell= is not the literal False")
            if name.startswith("subprocess.") and name.split(".")[-1] in SUBPROCESS_FUNCS:
                if not allow_subprocess:
                    add(node, f"{name}() outside core/runner.py")
                elif not any(
                    kw.arg == "shell"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is False
                    for kw in node.keywords
                ):
                    add(node, f"{name}() without explicit shell=False")
                elif node.args and isinstance(
                    node.args[0], (ast.Constant, ast.JoinedStr, ast.BinOp)
                ):
                    add(node, f"{name}() with a string-built command")
    return found


def _package_files() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def test_package_has_no_forbidden_patterns() -> None:
    violations: list[Violation] = []
    for path in _package_files():
        violations += scan_source(
            path.read_text(), str(path.relative_to(PACKAGE)), allow_subprocess=path == RUNNER_MODULE
        )
    assert violations == []


def test_scanner_covers_the_whole_package() -> None:
    files = _package_files()
    assert RUNNER_MODULE in files
    assert len(files) >= 10


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        ("import os\nos.system('id')", "call to os.system()"),
        ("eval('1')", "call to eval()"),
        ("exec('x=1')", "call to exec()"),
        ("import pickle", "import pickle"),
        ("from marshal import loads", "from marshal import ..."),
        ("import yaml\nyaml.load(s)", "call to yaml.load()"),
        ("from os import system", "from os import system"),
        ("import subprocess", "subprocess outside core/runner.py"),
        ("import subprocess\nsubprocess.run(['x'], shell=True)", "shell= is not the literal False"),
    ],
)
def test_detects_forbidden_constructs(snippet: str, expected: str) -> None:
    whats = [v.what for v in scan_source(snippet, "t.py", allow_subprocess=False)]
    assert expected in whats


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        (
            "import subprocess\nsubprocess.run(['/bin/x'])",
            "subprocess.run() without explicit shell=False",
        ),
        (
            "import subprocess\nsubprocess.run('ls -l', shell=False)",
            "subprocess.run() with a string-built command",
        ),
        (
            "import subprocess\nsubprocess.run(f'ls {x}', shell=False)",
            "subprocess.run() with a string-built command",
        ),
    ],
)
def test_runner_module_rules(snippet: str, expected: str) -> None:
    whats = [v.what for v in scan_source(snippet, "runner.py", allow_subprocess=True)]
    assert expected in whats


@pytest.mark.parametrize(
    "snippet",
    [
        "def execute(): return 'executes eval of nothing'",
        "import yaml\nyaml.load(s, Loader=yaml.SafeLoader)",
        "import yaml\nyaml.safe_load(s)",
        "x = {'shell': True}",
    ],
)
def test_no_false_positives(snippet: str) -> None:
    assert scan_source(snippet, "t.py", allow_subprocess=False) == []
