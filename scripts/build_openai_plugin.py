#!/usr/bin/env python3
"""Build the OpenAI plugin package (ChatGPT and Codex directory) for this skill.

Reads the listing and limits YAML files, validates them against the OpenAI
plugin directory submission rules, and writes a portable Agent Plugins package
(plugin.json, mcp.json, skills/, assets/) plus a deterministic ZIP.

Usage:
    build_openai_plugin.py --listing L.yaml --limits LIM.yaml --repo-root DIR --out-dir OUT
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import sys
import zipfile
from pathlib import Path

import yaml

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class BuildError(Exception):
    """Raised when the listing fails validation; carries every problem found."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise BuildError([f"{path}: expected a YAML mapping"])
    return data


def read_frontmatter(skill_md: Path) -> dict:
    """Return the YAML frontmatter of a SKILL.md file."""
    text = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if match is None:
        raise BuildError([f"{skill_md}: missing YAML frontmatter"])
    data = yaml.safe_load(match.group(1))
    if not isinstance(data, dict):
        raise BuildError([f"{skill_md}: frontmatter is not a mapping"])
    return data


def skill_version(frontmatter: dict) -> str:
    metadata = frontmatter.get("metadata")
    version = metadata.get("version") if isinstance(metadata, dict) else None
    if not isinstance(version, str):
        raise BuildError(["SKILL.md: metadata.version is missing"])
    return version


def relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first: str, second: str) -> float:
    high, low = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if not header.startswith(PNG_SIGNATURE) or header[12:16] != b"IHDR":
        raise BuildError([f"{path}: not a PNG file (only PNG icons are supported)"])
    return struct.unpack(">II", header[16:24])


def check_text_limits(interface: dict, limits: dict) -> list[str]:
    problems = [f"interface.{key} is required" for key in limits["interface_required"] if not interface.get(key)]
    for key, maximum in limits["interface_max_chars"].items():
        value = interface.get(key, "")
        if len(value) > maximum:
            problems.append(f"interface.{key} is {len(value)} chars (max {maximum})")
    problems += [
        f"interface.{key} must be an https:// URL"
        for key in limits["https_fields"]
        if not str(interface.get(key, "")).startswith("https://")
    ]
    return problems


def check_list_limits(name: str, values: list, rule: dict) -> list[str]:
    problems = []
    if len(values) > rule["max_items"]:
        problems.append(f"interface.{name} has {len(values)} items (max {rule['max_items']})")
    problems += [
        f"interface.{name} item exceeds {rule['max_chars']} chars: {value!r}"
        for value in values
        if len(value) > rule["max_chars"]
    ]
    if len(set(values)) != len(values):
        problems.append(f"interface.{name} items must be unique")
    return problems


def check_brand_colors(interface: dict, limits: dict) -> list[str]:
    problems = []
    for key, rule in limits["brand_colors"].items():
        color = interface.get(key)
        match color:
            case None:
                continue
            case str() if re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                ratio = contrast_ratio(color, rule["background"])
                if ratio < rule["min_ratio"]:
                    problems.append(f"interface.{key} {color} contrast {ratio:.2f} < {rule['min_ratio']}")
            case _:
                problems.append(f"interface.{key} must be #RRGGBB")
    return problems


def check_icons(listing: dict, limits: dict, repo_root: Path) -> list[str]:
    problems = []
    assets = listing.get("assets", {})
    rule = limits["icon"]
    for key in limits["icon_fields"]:
        package_path = listing["interface"].get(key)
        source = assets.get(package_path)
        if source is None:
            problems.append(f"interface.{key} {package_path!r} is not listed under assets")
            continue
        path = repo_root / source
        width, height = png_size(path)
        if width != height or not rule["min_px"] <= width <= rule["max_px"]:
            problems.append(f"{source}: icon must be square, {rule['min_px']}-{rule['max_px']} px (is {width}x{height})")
        if path.stat().st_size > rule["max_bytes"]:
            problems.append(f"{source}: icon exceeds {rule['max_bytes']} bytes")
    return problems


def check_review(review: dict, limits: dict) -> list[str]:
    problems = []
    cases = review.get("test_cases", {})
    for kind, rule in limits["review_cases"].items():
        entries = cases.get(kind, [])
        if len(entries) != rule["count"]:
            problems.append(f"review.test_cases.{kind} has {len(entries)} cases (need {rule['count']})")
        for index, entry in enumerate(entries):
            missing = [field for field in rule["required"] if not entry.get(field)]
            if missing:
                problems.append(f"review.test_cases.{kind}[{index}] missing {', '.join(missing)}")
    return problems


def check_identity(listing: dict, limits: dict, version: str) -> list[str]:
    manifest = listing["manifest"]
    name = manifest.get("name", "")
    problems = []
    if len(name) > limits["name_max_chars"] or not re.fullmatch(limits["name_pattern"], name):
        problems.append(f"manifest.name {name!r} must be lowercase letters, numbers and single hyphens")
    if not re.fullmatch(limits["version_pattern"], version):
        problems.append(f"version {version!r} is not MAJOR.MINOR.PATCH")
    if len(manifest.get("description", "")) > limits["manifest_description_max_chars"]:
        problems.append("manifest.description is too long")
    return problems


def check_skill(frontmatter: dict, skill_dir: Path) -> list[str]:
    problems = [f"SKILL.md: {key} is required" for key in ("name", "description") if not frontmatter.get(key)]
    if frontmatter.get("name") and frontmatter["name"] != skill_dir.name:
        problems.append(f"SKILL.md name {frontmatter['name']!r} must match directory {skill_dir.name!r}")
    return problems


def validate(listing: dict, limits: dict, repo_root: Path, frontmatter: dict, version: str) -> None:
    interface = listing["interface"]
    problems = (
        check_identity(listing, limits, version)
        + check_skill(frontmatter, repo_root / listing["skill_dir"])
        + check_text_limits(interface, limits)
        + check_list_limits("capabilities", interface.get("capabilities", []), limits["capabilities"])
        + check_list_limits("defaultPrompt", interface.get("defaultPrompt", []), limits["default_prompt"])
        + check_brand_colors(interface, limits)
        + check_icons(listing, limits, repo_root)
        + check_review(listing.get("review", {}), limits)
    )
    if problems:
        raise BuildError(problems)


def build_manifest(listing: dict, limits: dict, version: str) -> dict:
    openai = {"interface": listing["interface"]}
    for key in ("review", "publication"):
        if listing.get(key):
            openai[key] = listing[key]
    return {
        "$schema": limits["plugin_schema"],
        **listing["manifest"],
        "version": version,
        "extensions": {"com.openai": openai},
    }


def build_mcp(listing: dict, limits: dict) -> dict:
    server = listing["mcp"]
    return {
        "$schema": limits["mcp_schema"],
        "mcpServers": {server["server_name"]: {"type": server["type"], "url": server["url"]}},
    }


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_package(listing: dict, limits: dict, repo_root: Path, package_dir: Path, version: str) -> None:
    if package_dir.exists():
        shutil.rmtree(package_dir)
    skill_src = repo_root / listing["skill_dir"]
    shutil.copytree(skill_src, package_dir / "skills" / skill_src.name, ignore=shutil.ignore_patterns(".*"))
    for package_path, source in listing.get("assets", {}).items():
        target = package_dir / package_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo_root / source, target)
    for name in listing.get("extra_files", []):
        shutil.copyfile(repo_root / name, package_dir / Path(name).name)
    write_json(package_dir / "plugin.json", build_manifest(listing, limits, version))
    write_json(package_dir / "mcp.json", build_mcp(listing, limits))


def make_zip(package_dir: Path, zip_path: Path) -> None:
    """Write a byte-reproducible ZIP with plugin.json at its root."""
    files = sorted(p for p in package_dir.rglob("*") if p.is_file())
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(package_dir).as_posix(), ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())


def build(listing_path: Path, limits_path: Path, repo_root: Path, out_dir: Path) -> Path:
    listing = load_yaml(listing_path)
    limits = load_yaml(limits_path)
    frontmatter = read_frontmatter(repo_root / listing["skill_dir"] / "SKILL.md")
    version = skill_version(frontmatter)
    validate(listing, limits, repo_root, frontmatter, version)
    name = listing["manifest"]["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    package_dir = out_dir / name
    write_package(listing, limits, repo_root, package_dir, version)
    zip_path = out_dir / f"{name}-openai-plugin-{version}.zip"
    make_zip(package_dir, zip_path)
    return zip_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--listing", type=Path, required=True, help="listing YAML")
    parser.add_argument("--limits", type=Path, required=True, help="submission limits YAML")
    parser.add_argument("--repo-root", type=Path, required=True, help="repository root")
    parser.add_argument("--out-dir", type=Path, required=True, help="output directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        zip_path = build(args.listing, args.limits, args.repo_root, args.out_dir)
    except BuildError as error:
        for problem in error.problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    print(zip_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
