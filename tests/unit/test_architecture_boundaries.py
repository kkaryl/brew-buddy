"""Architectural boundary tests enforcing domain and application layer independence."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_EXTERNAL_PREFIXES = (
    "fastapi",
    "google.adk",
    "google.cloud",
    "google.genai",
    "a2a",
    "uvicorn",
)
FORBIDDEN_DOMAIN_INTERNAL_PREFIXES = (
    "app.application",
    "app.infrastructure",
    "app.api",
    "app.agent",
    "app.tools",
)
FORBIDDEN_APPLICATION_INTERNAL_PREFIXES = (
    "app.infrastructure",
    "app.api",
    "app.agent",
    "app.tools",
    "app.plugins",
)
FORBIDDEN_AGENT_AND_TOOLS_PREFIXES = (
    "fastapi",
    "google.cloud",
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
                assert not mod.startswith(FORBIDDEN_EXTERNAL_PREFIXES), (
                    f"Forbidden import '{mod}' found in {py_file.relative_to(REPO_ROOT)}"
                )


def test_domain_and_application_inward_dependency_direction() -> None:
    domain_files = list((REPO_ROOT / "app" / "domain").rglob("*.py"))
    for py_file in domain_files:
        for mod in _imported_modules(py_file):
            assert not mod.startswith(FORBIDDEN_DOMAIN_INTERNAL_PREFIXES), (
                f"Outer-layer import '{mod}' found in {py_file.relative_to(REPO_ROOT)}"
            )

    app_files = list((REPO_ROOT / "app" / "application").rglob("*.py"))
    for py_file in app_files:
        for mod in _imported_modules(py_file):
            assert not mod.startswith(FORBIDDEN_APPLICATION_INTERNAL_PREFIXES), (
                f"Outer-layer import '{mod}' found in {py_file.relative_to(REPO_ROOT)}"
            )


def test_agent_tools_and_plugins_do_not_import_fastapi_or_raw_cloud_clients() -> None:
    target_files = [
        REPO_ROOT / "app" / "agent.py",
        REPO_ROOT / "app" / "infrastructure" / "adk_brief_coach.py",
        *list((REPO_ROOT / "app" / "tools").rglob("*.py")),
        *list((REPO_ROOT / "app" / "plugins").rglob("*.py")),
    ]
    for py_file in target_files:
        for mod in _imported_modules(py_file):
            assert not mod.startswith(FORBIDDEN_AGENT_AND_TOOLS_PREFIXES), (
                f"Forbidden direct transport/cloud import '{mod}' in "
                f"{py_file.relative_to(REPO_ROOT)}"
            )


def test_ports_and_fakes_do_not_introduce_generic_repository_framework() -> None:
    for rel_path in (
        "app/domain/ports.py",
        "app/infrastructure/fakes.py",
        "app/infrastructure/firestore_repositories.py",
    ):
        py_file = REPO_ROOT / rel_path
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and "Repository" in node.name:
                assert not node.type_params, (
                    f"Generic repository class '{node.name}' is forbidden in {rel_path}"
                )
                for base in node.bases:
                    base_src = ast.unparse(base)
                    assert "Generic[" not in base_src, (
                        f"Generic repository base '{base_src}' is forbidden in {rel_path}"
                    )
