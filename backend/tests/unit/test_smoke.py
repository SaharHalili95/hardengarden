"""Phase 0 smoke test: the package imports and exposes a valid version."""

import re

import hardengarden

# PEP 440 public version (release segment plus optional pre/post/dev parts).
_PEP440 = re.compile(r"^\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?$")


def test_package_imports() -> None:
    assert hardengarden.__name__ == "hardengarden"


def test_version_is_pep440() -> None:
    assert _PEP440.fullmatch(hardengarden.__version__)


def test_public_api_is_explicit() -> None:
    assert hardengarden.__all__ == ["__version__"]
