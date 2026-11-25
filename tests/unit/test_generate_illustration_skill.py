"""Deterministic unit tests for the `.agents/skills/generate-illustration` project skill."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / ".agents" / "skills" / "generate-illustration"
SKILL_MD = SKILL_DIR / "SKILL.md"
STYLE_GUIDE_MD = SKILL_DIR / "references" / "style-guide.md"
SCRIPT_PATH = SKILL_DIR / "scripts" / "generate_brew_illustration.py"


def _load_skill_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_brew_illustration", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_skill_files_and_frontmatter_are_present() -> None:
    """Verify SKILL.md frontmatter and referenced files exist for skill discovery."""
    assert SKILL_MD.is_file()
    assert STYLE_GUIDE_MD.is_file()
    assert SCRIPT_PATH.is_file()

    content = SKILL_MD.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    frontmatter = content.split("---\n", 2)[1]
    assert "name: generate-illustration" in frontmatter
    assert "description:" in frontmatter
    assert "Playful Social Club" in content


def test_validate_slug_and_prompt_builder_contracts() -> None:
    """Verify kebab-case slug validation and Playful Social Club prompt assembly."""
    mod = _load_skill_module()

    assert mod.validate_slug("chat-setup-hero") == "chat-setup-hero"
    assert mod.validate_slug("mentor-checkin-2") == "mentor-checkin-2"

    for invalid in ("", "UpperCase", "../escape", "bad_underscore", "two words"):
        with pytest.raises(ValueError, match="Invalid illustration name"):
            mod.validate_slug(invalid)

    with pytest.raises(ValueError, match="at least 12 characters"):
        mod.build_illustration_prompt("too short")

    base_prompt = mod.build_illustration_prompt(
        "Waist-up scene of a friendly mentor and mentee comparing notes"
    )
    assert "Playful Social Club" in base_prompt
    assert "#FFFFFF" in base_prompt
    assert "#EF8B70" in base_prompt
    assert "#DDF3E7" in base_prompt
    assert "#E9DFFC" in base_prompt
    assert "no embedded text or lettering." in base_prompt
    assert "brew." not in base_prompt

    laptop_prompt = mod.build_illustration_prompt(
        "Two peers chatting across an open laptop",
        include_brew_laptop=True,
    )
    assert "lowercase wordmark 'brew.'" in laptop_prompt


def test_print_prompt_only_cli_runs_offline(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify --print-prompt-only outputs the prompt and exits 0 without network calls."""
    mod = _load_skill_module()
    exit_code = mod.main(
        [
            "--name",
            "sample-hero",
            "--scene",
            "Two friendly professionals sharing ideas at a pastel desk",
            "--print-prompt-only",
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Playful Social Club" in out
    assert "Two friendly professionals sharing ideas at a pastel desk." in out


def test_resolve_imagemagick_binaries_falls_back_to_im6_convert_and_identify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify Ubuntu ImageMagick 6 (`convert` + `identify`) is accepted when `magick` is absent."""
    mod = _load_skill_module()
    fake_bins = {"convert": "/usr/bin/convert", "identify": "/usr/bin/identify"}
    monkeypatch.setattr(shutil, "which", lambda name: fake_bins.get(name))
    monkeypatch.setattr(Path, "is_file", lambda self: str(self) in fake_bins.values())

    convert_bin, identify_cmd = mod.resolve_imagemagick_binaries()
    assert convert_bin == "/usr/bin/convert"
    assert identify_cmd == ["/usr/bin/identify"]


def test_from_raw_alpha_cutout_preserves_enclosed_interior_white(tmp_path: Path) -> None:
    """Verify outer #FFFFFF margin becomes transparent while enclosed white speech bubble stays."""
    mod = _load_skill_module()
    convert_bin, identify_cmd = mod.resolve_imagemagick_binaries()

    raw_png = tmp_path / "synthetic-raw.png"
    out_png = tmp_path / "out" / "synthetic-cutout.png"
    preview_png = tmp_path / "out" / "synthetic-preview.png"

    # Draw a 200x140 pure white canvas containing an enclosed coral sticker circle (cx=100,cy=70)
    # and an enclosed pure-white interior speech-bubble box (80,55 -> 120,85).
    subprocess.run(
        [
            convert_bin,
            "-size",
            "200x140",
            "xc:#FFFFFF",
            "-fill",
            "#EF8B70",
            "-draw",
            "circle 100,70 100,25",
            "-fill",
            "#FFFFFF",
            "-draw",
            "rectangle 82,56 118,84",
            str(raw_png),
        ],
        check=True,
        timeout=15,
    )

    exit_code = mod.main(
        [
            "--name",
            "synthetic-cutout",
            "--from-raw",
            str(raw_png),
            "--output",
            str(out_png),
            "--preview-out",
            str(preview_png),
            "--preview-bg",
            "#FFE9DF",
            "--padding",
            "10x10",
        ]
    )
    assert exit_code == 0
    assert out_png.is_file()
    assert preview_png.is_file()

    # Top-left corner (0,0) must have alpha == 0 (transparent), while center pixel (enclosed
    # white speech-bubble interior) must remain opaque white (alpha == 1).
    corner_alpha = subprocess.run(
        [convert_bin, f"{out_png}[1x1+0+0]", "-format", "%[fx:a]", "info:"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    assert float(corner_alpha) == 0.0

    dims = subprocess.run(
        [*identify_cmd, "-format", "%w %h", str(out_png)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.split()
    cx = int(dims[0]) // 2
    cy = int(dims[1]) // 2
    center_rgba = subprocess.run(
        [convert_bin, f"{out_png}[1x1+{cx}+{cy}]", "-format", "%[fx:r] %[fx:a]", "info:"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.split()
    assert float(center_rgba[0]) > 0.98
    assert float(center_rgba[1]) == 1.0
