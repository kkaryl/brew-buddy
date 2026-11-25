"""Generate and post-process Brew 'Playful Social Club' illustrations into transparent PNGs."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ILLUSTRATIONS_DIR = REPO_ROOT / "web" / "src" / "assets" / "illustrations"

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PADDING_RE = re.compile(r"^\d{1,3}x\d{1,3}$")

STYLE_PREAMBLE = (
    "A premium modern flat-vector 2D editorial illustration in a Playful Social Club style, "
    "centered horizontally on a pure uniform solid flat white (#FFFFFF) outer canvas with clean "
    "generous white margins on all four edges (no vignette, no paper texture, no gradient on the "
    "outer margin). "
)

STYLE_MOTIFS_AND_GUARDRAILS = (
    "Characters have friendly hand-drawn flat-vector shapes, smooth rounded contours, slight "
    "playful asymmetry, warm skin tones, dark cocoa-brown hair, and minimal facial features with "
    "tiny curved smiles, small dot or gentle arc eyes, and subtle rosy cheeks. Behind the main "
    "subject are overlapping soft pastel mint (#DDF3E7) and soft lavender (#E9DFFC) circular "
    "shapes, a crisp white rounded speech bubble containing three dark-plum (#302731) circular "
    "dots, and small coral-orange (#EF8B70) radiating excitement strokes. The entire grouped "
    "composition is enclosed by a clean white sticker-cutout silhouette halo against the pure "
    "solid white (#FFFFFF) outer canvas. Clean 2D flat-vector editorial art, restrained shading, "
    "minimal dark-plum outlines, strictly no coffee cups or mugs, no 3D rendering, no "
    "photorealism, no anime, no emoji art, and no embedded text or lettering"
)

BREW_LAPTOP_CLAUSE = (
    " except for an open pale ivory (#FFF9F2) laptop in the foreground displaying only a tiny "
    "crisp dark-plum (#302731) lowercase wordmark 'brew.' where the period dot '.' is "
    "coral-orange (#EF8B70)."
)


@dataclass(frozen=True)
class IllustrationJobConfig:
    """Validated parameters for generating and post-processing a Brew illustration."""

    name: str
    scene: str | None
    output_path: Path
    from_raw_path: Path | None
    raw_save_path: Path | None
    preview_out_path: Path | None
    preview_bg: str
    fuzz_percent: int
    padding: str
    model: str
    location: str
    include_brew_laptop: bool
    print_prompt_only: bool


def validate_slug(slug: str) -> str:
    """Ensure the illustration asset name is a safe kebab-case identifier."""
    cleaned = slug.strip()
    if not _SLUG_RE.match(cleaned):
        raise ValueError(
            f"Invalid illustration name '{slug}'. "
            "Use lowercase kebab-case (e.g. 'chat-setup-hero')."
        )
    return cleaned


def build_illustration_prompt(scene: str, *, include_brew_laptop: bool = False) -> str:
    """Wrap a scene brief in Brew's canonical Playful Social Club style prompt."""
    cleaned_scene = " ".join(scene.strip().split())
    if len(cleaned_scene) < 12:
        raise ValueError("Scene description must be at least 12 characters.")
    if not cleaned_scene.endswith("."):
        cleaned_scene = f"{cleaned_scene}."

    ending = BREW_LAPTOP_CLAUSE if include_brew_laptop else "."
    return f"{STYLE_PREAMBLE}{cleaned_scene} {STYLE_MOTIFS_AND_GUARDRAILS}{ending}"


def generate_raw_image_bytes(
    *,
    prompt: str,
    project: str,
    location: str,
    model: str,
) -> bytes:
    """Call Google Cloud Vertex AI Gemini image generation and return raw PNG bytes."""
    from google import genai
    from google.genai import types

    client = genai.Client(
        vertexai=True,
        project=project,
        location=location,
        http_options=types.HttpOptions(timeout=60_000),
    )
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
        ),
    )
    for candidate in response.candidates or []:
        if not candidate.content:
            continue
        for part in candidate.content.parts or []:
            if part.inline_data and part.inline_data.data:
                return bytes(part.inline_data.data)

    raise RuntimeError(f"Model '{model}' returned no image bytes.")


def resolve_imagemagick_binaries() -> tuple[str, list[str]]:
    """Resolve ImageMagick 7 (`magick`) or ImageMagick 6 (`convert` + `identify`) binaries."""
    magick_bin = shutil.which("magick") or (
        "/usr/bin/magick" if Path("/usr/bin/magick").is_file() else None
    )
    if magick_bin is not None:
        return magick_bin, [magick_bin, "identify"]

    convert_bin = shutil.which("convert") or (
        "/usr/bin/convert" if Path("/usr/bin/convert").is_file() else None
    )
    identify_bin = shutil.which("identify") or (
        "/usr/bin/identify" if Path("/usr/bin/identify").is_file() else None
    )
    if convert_bin is not None and identify_bin is not None:
        return convert_bin, [identify_bin]

    raise RuntimeError(
        "ImageMagick ('magick' or 'convert'/'identify') is required for "
        "outer-margin alpha extraction."
    )


def extract_transparent_cutout_png(
    *,
    raw_path: Path,
    output_path: Path,
    fuzz_percent: int = 4,
    padding: str = "24x18",
    preview_out_path: Path | None = None,
    preview_bg: str = "#FFE9DF",
) -> str:
    """Flood-fill outer white margin to alpha transparent, trim, pad, and optimize PNG."""
    convert_bin, identify_cmd = resolve_imagemagick_binaries()
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw image file not found: {raw_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Add a 4px pure-white perimeter first so (0,0) flood-fill wraps 360 degrees around the
    # outer canvas without ever touching enclosed interior whites (speech bubbles, laptop, teeth).
    # `-floodfill +0+0 #FFFFFF` sets alpha=0 in both ImageMagick 6 (`convert`) and 7 (`magick`).
    cutout_cmd = [
        convert_bin,
        str(raw_path),
        "-bordercolor",
        "#FFFFFF",
        "-border",
        "4x4",
        "-alpha",
        "set",
        "-fuzz",
        f"{fuzz_percent}%",
        "-fill",
        "none",
        "-floodfill",
        "+0+0",
        "#FFFFFF",
        "-trim",
        "+repage",
        "-bordercolor",
        "none",
        "-border",
        padding,
        "-strip",
        "-define",
        "png:compression-level=9",
        str(output_path),
    ]
    subprocess.run(cutout_cmd, check=True, timeout=30)

    if preview_out_path is not None:
        preview_out_path.parent.mkdir(parents=True, exist_ok=True)
        preview_cmd = [
            convert_bin,
            str(output_path),
            "-background",
            preview_bg,
            "-alpha",
            "remove",
            "-alpha",
            "off",
            str(preview_out_path),
        ]
        subprocess.run(preview_cmd, check=True, timeout=30)

    identify = subprocess.run(
        [*identify_cmd, str(output_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return identify.stdout.strip()


def parse_cli_args(argv: list[str] | None = None) -> IllustrationJobConfig:
    """Parse and validate CLI flags into an IllustrationJobConfig."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate a Brew 'Playful Social Club' editorial illustration and extract a "
            "clean alpha-transparent PNG."
        )
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Kebab-case asset slug (e.g. 'chat-setup-hero' or 'mentorship-checkin').",
    )
    parser.add_argument(
        "--scene",
        default=None,
        help="Scene description (characters, poses, props). Required unless --from-raw is set.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Destination PNG path (defaults to web/src/assets/illustrations/<name>.png).",
    )
    parser.add_argument(
        "--from-raw",
        default=None,
        help="Skip model call and run transparent cutout extraction on an existing raw PNG.",
    )
    parser.add_argument(
        "--save-raw",
        default=None,
        help="Optional scratch path to preserve the uncropped raw model PNG.",
    )
    parser.add_argument(
        "--preview-out",
        default=None,
        help="Optional scratch path to render an edge-check preview over --preview-bg.",
    )
    parser.add_argument(
        "--preview-bg",
        default="#FFE9DF",
        help="Hex color for --preview-out edge verification (default: #FFE9DF).",
    )
    parser.add_argument(
        "--fuzz-percent",
        type=int,
        default=4,
        help="ImageMagick flood-fill fuzz tolerance percentage 1..15 (default: 4).",
    )
    parser.add_argument(
        "--padding",
        default="24x18",
        help="Transparent WxH pixel border around trimmed cutout (default: 24x18).",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash-image",
        help="Vertex AI image generation model ID (default: gemini-2.5-flash-image).",
    )
    parser.add_argument(
        "--location",
        default="global",
        help="Vertex AI location for the image model (default: global).",
    )
    parser.add_argument(
        "--include-brew-laptop",
        action="store_true",
        help="Allow the lowercase 'brew.' coral-dot wordmark on a foreground laptop prop.",
    )
    parser.add_argument(
        "--print-prompt-only",
        action="store_true",
        help="Print the assembled Playful Social Club prompt and exit without generating.",
    )

    ns = parser.parse_args(argv)
    slug = validate_slug(str(ns.name))

    if ns.from_raw is None and not ns.scene:
        parser.error("--scene is required unless --from-raw is provided.")
    if not (1 <= int(ns.fuzz_percent) <= 15):
        parser.error("--fuzz-percent must be between 1 and 15.")
    if not _HEX_COLOR_RE.match(str(ns.preview_bg)):
        parser.error("--preview-bg must be a 6-digit hex color like '#FFE9DF'.")
    if not _PADDING_RE.match(str(ns.padding)):
        parser.error("--padding must match '<width>x<height>', e.g. '24x18'.")

    output_path = (
        Path(ns.output).resolve() if ns.output else (DEFAULT_ILLUSTRATIONS_DIR / f"{slug}.png")
    )

    return IllustrationJobConfig(
        name=slug,
        scene=str(ns.scene) if ns.scene is not None else None,
        output_path=output_path,
        from_raw_path=Path(ns.from_raw).resolve() if ns.from_raw else None,
        raw_save_path=Path(ns.save_raw).resolve() if ns.save_raw else None,
        preview_out_path=Path(ns.preview_out).resolve() if ns.preview_out else None,
        preview_bg=str(ns.preview_bg),
        fuzz_percent=int(ns.fuzz_percent),
        padding=str(ns.padding),
        model=str(ns.model),
        location=str(ns.location),
        include_brew_laptop=bool(ns.include_brew_laptop),
        print_prompt_only=bool(ns.print_prompt_only),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for generating and extracting a Brew editorial illustration."""
    config = parse_cli_args(argv)

    if config.print_prompt_only:
        assert config.scene is not None
        prompt = build_illustration_prompt(
            config.scene,
            include_brew_laptop=config.include_brew_laptop,
        )
        sys.stdout.write(f"{prompt}\n")
        return 0

    temp_raw_cleanup: Path | None = None
    try:
        if config.from_raw_path is not None:
            raw_source = config.from_raw_path
        else:
            assert config.scene is not None
            if str(REPO_ROOT) not in sys.path:
                sys.path.insert(0, str(REPO_ROOT))
            from app.config import AppSettings

            settings = AppSettings()
            if not settings.google_cloud_project:
                raise RuntimeError(
                    "GOOGLE_CLOUD_PROJECT is not set in .env or environment variables."
                )

            prompt = build_illustration_prompt(
                config.scene,
                include_brew_laptop=config.include_brew_laptop,
            )
            raw_bytes = generate_raw_image_bytes(
                prompt=prompt,
                project=settings.google_cloud_project,
                location=config.location,
                model=config.model,
            )
            raw_source = config.raw_save_path or config.output_path.with_suffix(".raw.tmp.png")
            if config.raw_save_path is None:
                temp_raw_cleanup = raw_source
            raw_source.parent.mkdir(parents=True, exist_ok=True)
            raw_source.write_bytes(raw_bytes)

        summary = extract_transparent_cutout_png(
            raw_path=raw_source,
            output_path=config.output_path,
            fuzz_percent=config.fuzz_percent,
            padding=config.padding,
            preview_out_path=config.preview_out_path,
            preview_bg=config.preview_bg,
        )
        sys.stdout.write(f"Saved transparent illustration: {summary}\n")
        if config.preview_out_path is not None:
            sys.stdout.write(f"Saved edge-check preview: {config.preview_out_path}\n")
        return 0
    finally:
        if temp_raw_cleanup is not None and temp_raw_cleanup.exists():
            temp_raw_cleanup.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
