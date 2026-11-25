"""Architectural boundary tests: layers, bounded contexts and where frameworks may appear.

The backend is organised as four layers (domain, application, agents and infrastructure, API),
each split by bounded context. These tests read import statements with ``ast`` so the structure
cannot erode unnoticed.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "app"

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
    "app.composition",
    "app.api",
    "app.agent",
)
FORBIDDEN_APPLICATION_INTERNAL_PREFIXES = (
    "app.infrastructure",
    "app.composition",
    "app.api",
    "app.agent",
)
FORBIDDEN_AGENT_AND_TOOLS_PREFIXES = (
    "fastapi",
    "google.cloud",
)

# A domain context may import contexts that come before it in this list, never after.
DOMAIN_CONTEXT_ORDER = ("shared", "identity", "contacts", "meetings", "memory", "briefs")

# Where each framework may be imported. Paths are relative to ``app/``; a trailing slash
# means the whole package.
FRAMEWORK_HOMES: dict[str, tuple[str, ...]] = {
    "fastapi": ("api/", "fast_api_app.py", "app_utils/"),
    "google.cloud": ("infrastructure/", "composition/builders.py"),
    "google.adk": (
        "agent.py",
        "agents/",
        "api/app_factory.py",
        "app_utils/",
        "infrastructure/sessions.py",
        "infrastructure/observability.py",
    ),
    "google.genai": ("agents/",),
}

# Scripted stand-ins for models and identity providers. Only the composition root wires
# them in. The identity package reads the static local developer tokens from there.
STUB_IMPORTERS = ("composition/", "infrastructure/stubs/", "infrastructure/identity/")

# Flat modules that were split into packages. They must not come back.
RETIRED_MODULES = (
    "app/domain/models.py",
    "app/domain/ports.py",
    "app/domain/types.py",
    "app/domain/shared/diagnostics.py",
    "app/application/brief_workflow.py",
    "app/application/services.py",
    "app/infrastructure/fakes.py",
    "app/infrastructure/firestore_repositories.py",
    "app/tools",
    "app/plugins",
    "app/api/v1.py",
    "app/api/schemas.py",
)


def _python_files(*relative_dirs: str) -> list[Path]:
    files: list[Path] = []
    for relative in relative_dirs:
        target = REPO_ROOT / relative
        files.extend([target] if target.is_file() else sorted(target.rglob("*.py")))
    return files


def _imported_modules(py_file: Path) -> list[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _imported_names(py_file: Path) -> list[tuple[str, str]]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    return [
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    ]


def _is_within(py_file: Path, homes: tuple[str, ...]) -> bool:
    relative = py_file.relative_to(APP_ROOT).as_posix()
    return any(
        relative.startswith(home) if home.endswith("/") else relative == home for home in homes
    )


def test_domain_and_application_layers_have_no_framework_or_cloud_imports() -> None:
    for layer in ("domain", "application"):
        py_files = _python_files(f"app/{layer}")
        assert py_files, f"Expected Python modules in app/{layer}"

        for py_file in py_files:
            for mod in _imported_modules(py_file):
                assert not mod.startswith(FORBIDDEN_EXTERNAL_PREFIXES), (
                    f"Forbidden import '{mod}' found in {py_file.relative_to(REPO_ROOT)}"
                )


def test_domain_and_application_inward_dependency_direction() -> None:
    for py_file in _python_files("app/domain"):
        for mod in _imported_modules(py_file):
            assert not mod.startswith(FORBIDDEN_DOMAIN_INTERNAL_PREFIXES), (
                f"Outer-layer import '{mod}' found in {py_file.relative_to(REPO_ROOT)}"
            )

    for py_file in _python_files("app/application"):
        for mod in _imported_modules(py_file):
            assert not mod.startswith(FORBIDDEN_APPLICATION_INTERNAL_PREFIXES), (
                f"Outer-layer import '{mod}' found in {py_file.relative_to(REPO_ROOT)}"
            )


def test_domain_contexts_depend_in_one_direction() -> None:
    context_dirs = {path.name for path in (APP_ROOT / "domain").iterdir() if path.is_dir()}
    context_dirs.discard("__pycache__")
    assert context_dirs == set(DOMAIN_CONTEXT_ORDER)

    rank = {name: index for index, name in enumerate(DOMAIN_CONTEXT_ORDER)}
    for py_file in _python_files("app/domain"):
        own_context = py_file.relative_to(APP_ROOT / "domain").parts[0]
        if own_context not in rank:
            continue
        for mod in _imported_modules(py_file):
            if not mod.startswith("app.domain."):
                continue
            imported_context = mod.split(".")[2]
            assert rank[imported_context] <= rank[own_context], (
                f"{py_file.relative_to(REPO_ROOT)} ({own_context}) imports the later "
                f"context '{imported_context}' via '{mod}'"
            )


def test_agents_package_does_not_import_fastapi_or_raw_cloud_clients() -> None:
    target_files = _python_files("app/agent.py", "app/agents")
    assert len(target_files) > 10
    for py_file in target_files:
        for mod in _imported_modules(py_file):
            assert not mod.startswith(FORBIDDEN_AGENT_AND_TOOLS_PREFIXES), (
                f"Forbidden direct transport/cloud import '{mod}' in "
                f"{py_file.relative_to(REPO_ROOT)}"
            )


def test_each_framework_is_imported_only_from_its_home() -> None:
    for py_file in _python_files("app"):
        for mod in _imported_modules(py_file):
            for framework, homes in FRAMEWORK_HOMES.items():
                if mod == framework or mod.startswith(f"{framework}."):
                    assert _is_within(py_file, homes), (
                        f"'{mod}' imported in {py_file.relative_to(REPO_ROOT)}; "
                        f"'{framework}' is only allowed in {homes}"
                    )


def test_scripted_stubs_are_wired_only_by_the_composition_root() -> None:
    for py_file in _python_files("app"):
        for mod in _imported_modules(py_file):
            if mod.startswith("app.infrastructure.stubs"):
                assert _is_within(py_file, STUB_IMPORTERS), (
                    f"{py_file.relative_to(REPO_ROOT)} imports the stub module '{mod}'"
                )


def test_no_module_imports_a_private_name_from_another_module() -> None:
    for py_file in _python_files("app"):
        for module, name in _imported_names(py_file):
            if module.startswith("app."):
                assert not (name.startswith("_") and not name.startswith("__")), (
                    f"{py_file.relative_to(REPO_ROOT)} imports private name "
                    f"'{name}' from '{module}'"
                )


def test_retired_flat_modules_do_not_come_back() -> None:
    for relative in RETIRED_MODULES:
        assert not (REPO_ROOT / relative).exists(), f"{relative} was split and must stay removed"


def test_ports_and_repositories_do_not_introduce_generic_repository_framework() -> None:
    py_files = [
        *sorted((APP_ROOT / "domain").rglob("ports.py")),
        *_python_files("app/infrastructure/inmemory", "app/infrastructure/firestore"),
    ]
    repository_classes = 0
    for py_file in py_files:
        rel_path = py_file.relative_to(REPO_ROOT)
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and "Repository" in node.name:
                repository_classes += 1
                assert not node.type_params, (
                    f"Generic repository class '{node.name}' is forbidden in {rel_path}"
                )
                for base in node.bases:
                    base_src = ast.unparse(base)
                    assert "Generic[" not in base_src, (
                        f"Generic repository base '{base_src}' is forbidden in {rel_path}"
                    )
    # Guard against this check passing because it looked at files with no repositories.
    assert repository_classes >= 20
