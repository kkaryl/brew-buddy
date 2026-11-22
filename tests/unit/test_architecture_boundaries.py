"""Architectural boundary tests enforcing domain and application layer independence."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_PREFIXES = (
    "fastapi",
    "google.adk",
    "google.cloud",
    "google.genai",
    "a2a",
    "uvicorn",
)


def _imported_modules(py_file: Path) -> list[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_domain_and_application_layers_have_no_framework_or_cloud_imports() -> None:
    for layer in ("domain", "application"):
        layer_dir = REPO_ROOT / "app" / layer
        py_files = list(layer_dir.rglob("*.py"))
        assert py_files, f"Expected Python modules in {layer_dir}"

        for py_file in py_files:
            for mod in _imported_modules(py_file):
                assert not mod.startswith(FORBIDDEN_PREFIXES), (
                    f"Forbidden import '{mod}' found in {py_file.relative_to(REPO_ROOT)}"
                )
