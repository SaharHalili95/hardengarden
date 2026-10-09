"""Keeps the chromadb audit exceptions true (ADR-012).

The four open chromadb advisories (GHSA-f4j7-r4q5-qw2c, GHSA-36p7-vc44-83pf,
GHSA-xph7-9rjv-w5fr, GHSA-2wm9-hf6c-p5cr) all live in chromadb's HTTP *server* (its
/api/v2 collection endpoints, server-side embedding functions loaded with trust_remote_code,
and the multi-tenant RBAC provider). HardenGarden uses chromadb only as an embedded library.
This test fails the build if that ever changes.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "hardengarden"
STORE_MODULE = PACKAGE / "rag" / "store.py"

FORBIDDEN_ATTRIBUTES = {
    "HttpClient",
    "AsyncHttpClient",
    "CloudClient",
    "AdminClient",
    "Client",  # chromadb.Client(...) can be configured as an HTTP client
    "server",
    "embedding_functions",
    "utils",
}


def _chroma_references(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("chromadb"):
            found.extend(f"from {node.module} import {a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            found.extend(f"import {a.name}" for a in node.names if a.name.startswith("chromadb"))
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "chromadb"
        ):
            found.append(f"chromadb.{node.attr}")
    return found


def test_chromadb_is_used_only_in_the_store_module() -> None:
    for path in PACKAGE.rglob("*.py"):
        refs = _chroma_references(ast.parse(path.read_text()))
        if path != STORE_MODULE:
            assert refs == [], path


def test_store_uses_only_the_embedded_persistent_client() -> None:
    refs = _chroma_references(ast.parse(STORE_MODULE.read_text()))
    assert set(refs) == {
        "import chromadb",
        "from chromadb.config import Settings",
        "chromadb.PersistentClient",
    }
    assert not {r.split(".")[-1] for r in refs} & FORBIDDEN_ATTRIBUTES


def test_collections_never_get_an_embedding_function_or_remote_code() -> None:
    source = STORE_MODULE.read_text()
    assert "embedding_function=None" in source
    assert "trust_remote_code" not in source
    assert "anonymized_telemetry=False" in source
