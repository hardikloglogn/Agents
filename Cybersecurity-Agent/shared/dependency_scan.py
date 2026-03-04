from __future__ import annotations

from pathlib import Path
from typing import Iterable

CANONICAL_MANIFEST_TYPES = [
    "requirements.txt",
    "package.json",
    "pom.xml",
    "build.gradle",
    "pubspec.yaml",
]

_ALIAS_TO_CANONICAL: dict[str, str] = {
    name: name for name in CANONICAL_MANIFEST_TYPES
}
_ALIAS_TO_CANONICAL.update(
    {
        "txt": "requirements.txt",
        "requirements": "requirements.txt",
        "pip": "requirements.txt",
        "json": "package.json",
        "packagejson": "package.json",
        "npm": "package.json",
        "xml": "pom.xml",
        "pom": "pom.xml",
        "gradle": "build.gradle",
        "buildgradle": "build.gradle",
        "pubspec": "pubspec.yaml",
        "yaml": "pubspec.yaml",
        "yml": "pubspec.yaml",
    }
)


def supported_manifest_types() -> list[str]:
    return CANONICAL_MANIFEST_TYPES.copy()


def canonicalize_manifest_type(file_type: str | None, filename: str | None = None) -> str | None:
    """Return a supported manifest type given a hint or filename."""

    if file_type:
        normalized = file_type.strip().lower()
        if normalized in CANONICAL_MANIFEST_TYPES:
            return normalized
        alias = normalized.lstrip(".")
        if alias in _ALIAS_TO_CANONICAL:
            return _ALIAS_TO_CANONICAL[alias]

    if filename:
        key = Path(filename).name.lower()
        if key in CANONICAL_MANIFEST_TYPES:
            return key
        suffix = Path(filename).suffix.lower().lstrip(".")
        if suffix in _ALIAS_TO_CANONICAL:
            return _ALIAS_TO_CANONICAL[suffix]

    return None

