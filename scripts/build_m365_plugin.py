#!/usr/bin/env python3
"""Build the Microsoft 365 / Microsoft Copilot app package for this skill.

Reads the package and limits YAML files, validates them against the Teams
app manifest and Microsoft 365 certification rules, fetches the MCP server's
live tools/list (or reads a saved JSON-RPC reply) for the connector's tool
description file, and writes the package plus a deterministic ZIP.

Usage:
    build_m365_plugin.py --package P.yaml --limits LIM.yaml --repo-root DIR --out-dir OUT [--tools-file F.json]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import sys
import urllib.error
import urllib.request
import zlib
from pathlib import Path

from build_openai_plugin import (
    PNG_SIGNATURE,
    BuildError,
    check_skill,
    load_yaml,
    make_zip,
    png_size,
    read_frontmatter,
    skill_version,
    write_json,
)

RGBA_8BIT = (8, 6, 0)  # bit depth, color type (RGBA), interlace (none)
RGBA_BYTES = 4
WHITE = b"\xff\xff\xff"


def lookup(document: dict, dotted: str):
    """Return the value at a dotted path such as "name.short" or "items.0.id"."""
    value = document
    for part in dotted.split("."):
        value = value[int(part)] if isinstance(value, list) else value.get(part, "")
    return value


# --- manifest ----------------------------------------------------------------


def full_description(package: dict) -> str:
    try:
        return "\n\n".join(paragraph.format(**package["links"]) for paragraph in package["description"]["full"])
    except KeyError as error:
        raise BuildError([f"description.full uses {{{error.args[0]}}}, which is not under links"]) from error


def build_manifest(package: dict, limits: dict, version: str) -> dict:
    connector = package["connector"]
    skill_name = Path(package["skill_dir"]).name
    return {
        "$schema": limits["schema"],
        "manifestVersion": limits["manifest_version"],
        "version": version,
        "id": package["app_id"],
        "developer": package["developer"],
        "name": package["name"],
        "description": {"short": package["description"]["short"], "full": full_description(package)},
        "icons": {kind: Path(source).name for kind, source in package["icons"].items()},
        "accentColor": package["accent_color"],
        "agentConnectors": [
            {
                "id": connector["id"],
                "displayName": connector["displayName"],
                "description": connector["description"],
                "toolSource": {
                    "remoteMcpServer": {
                        "mcpServerUrl": connector["url"],
                        "mcpToolDescription": {"file": connector["tool_file"]},
                        "authorization": {"type": "None"},
                    }
                },
            }
        ],
        "agentSkills": [{"folder": f"./skills/{skill_name}"}],
    }


# --- validation --------------------------------------------------------------


def check_identity(manifest: dict, limits: dict) -> list[str]:
    rules = [("version", "version_pattern"), ("id", "app_id_pattern"), ("accentColor", "accent_color_pattern")]
    return [
        f"{field} {manifest[field]!r} does not match {limits[rule]}"
        for field, rule in rules
        if not re.fullmatch(limits[rule], manifest[field])
    ]


def check_text(manifest: dict, limits: dict) -> list[str]:
    problems = [
        f"{field} is {len(lookup(manifest, field))} chars (max {maximum})"
        for field, maximum in limits["max_chars"].items()
        if len(lookup(manifest, field)) > maximum
    ]
    problems += [
        f"{field} must be an https:// URL"
        for field in limits["https_fields"]
        if not lookup(manifest, field).startswith("https://")
    ]
    rule = limits["first_mention"]
    for field in rule["fields"]:
        text = lookup(manifest, field)
        first = text.find(rule["term"])
        if text.find(rule["phrase"]) != first - rule["phrase"].index(rule["term"]):
            problems.append(f"{field}: the first mention of {rule['term']!r} must be {rule['phrase']!r}")
    return problems


def predictor(kind: int, left: int, up: int, up_left: int) -> int:
    """PNG filter predictor (https://www.w3.org/TR/png/#9Filter-types)."""
    match kind:
        case 0:
            return 0
        case 1:
            return left
        case 2:
            return up
        case 3:
            return (left + up) // 2
        case 4:
            estimate = left + up - up_left
            distances = [abs(estimate - left), abs(estimate - up), abs(estimate - up_left)]
            return (left, up, up_left)[distances.index(min(distances))]
        case _:
            raise BuildError([f"unknown PNG filter type {kind}"])


def unfilter(raw: bytes, stride: int, height: int, bpp: int) -> list[bytearray]:
    rows: list[bytearray] = []
    previous = bytearray(stride)
    for start in range(0, height * (stride + 1), stride + 1):
        kind, line = raw[start], bytearray(raw[start + 1 : start + 1 + stride])
        for i in range(stride):
            left = line[i - bpp] if i >= bpp else 0
            up_left = previous[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + predictor(kind, left, previous[i], up_left)) & 0xFF
        rows.append(line)
        previous = line
    return rows


def png_rgba_pixels(path: Path) -> list[bytes]:
    """Decode an 8-bit RGBA, non-interlaced PNG into a list of RGBA pixels."""
    data = path.read_bytes()
    width, height = png_size(path)
    if tuple(data[24:26]) + (data[28],) != RGBA_8BIT:
        raise BuildError([f"{path}: must be an 8-bit RGBA, non-interlaced PNG"])
    idat, offset = b"", len(PNG_SIGNATURE)
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        if data[offset + 4 : offset + 8] == b"IDAT":
            idat += data[offset + 8 : offset + 8 + length]
        offset += length + 12
    rows = unfilter(zlib.decompress(idat), width * RGBA_BYTES, height, RGBA_BYTES)
    return [bytes(row[i : i + RGBA_BYTES]) for row in rows for i in range(0, len(row), RGBA_BYTES)]


def check_white_on_transparent(path: Path) -> list[str]:
    pixels = png_rgba_pixels(path)
    problems = []
    colored = sum(1 for pixel in pixels if pixel[3] and pixel[:3] != WHITE)
    if colored:
        problems.append(f"{path}: {colored} visible pixels are not white")
    if not any(pixel[3] == 0 for pixel in pixels):
        problems.append(f"{path}: has no transparent pixels")
    return problems


def check_icons(package: dict, limits: dict, repo_root: Path) -> list[str]:
    problems = []
    for kind, rule in limits["icons"].items():
        path = repo_root / package["icons"][kind]
        size = png_size(path)
        if size != (rule["width"], rule["height"]):
            problems.append(f"{kind} icon {path} is {size[0]}x{size[1]} (needs {rule['width']}x{rule['height']})")
        elif rule.get("white_on_transparent"):
            problems += check_white_on_transparent(path)
    return problems


def validate(manifest: dict, package: dict, limits: dict, repo_root: Path, frontmatter: dict) -> None:
    problems = (
        check_identity(manifest, limits)
        + check_skill(frontmatter, repo_root / package["skill_dir"])
        + check_text(manifest, limits)
        + check_icons(package, limits, repo_root)
    )
    if problems:
        raise BuildError(problems)


# --- MCP tools/list ----------------------------------------------------------


def parse_rpc_body(content_type: str, text: str) -> dict | None:
    """Return the JSON-RPC response in a JSON or text/event-stream body."""
    if not text.strip():
        return None
    if not content_type.startswith("text/event-stream"):
        return json.loads(text)
    messages = [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]
    return next((message for message in reversed(messages) if "id" in message), None)


def mcp_post(url: str, body: dict, session: str | None) -> tuple[dict | None, str | None]:
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session:
        headers["Mcp-Session-Id"] = session
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            reply = parse_rpc_body(response.headers.get("Content-Type", ""), response.read().decode("utf-8"))
            return reply, response.headers.get("Mcp-Session-Id", session)
    except urllib.error.URLError as error:
        raise BuildError([f"{url}: {body['method']} failed: {error}"]) from error


def fetch_tools(url: str, protocol_version: str, client: dict) -> dict:
    """Run the streamable HTTP handshake and return the tools/list JSON-RPC reply."""
    initialize = {"protocolVersion": protocol_version, "capabilities": {}, "clientInfo": client}
    _, session = mcp_post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": initialize}, None)
    _, session = mcp_post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
    reply, _ = mcp_post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session)
    return reply or {}


def tool_description(reply: dict) -> dict:
    """Turn a tools/list JSON-RPC reply into the connector's tool description file."""
    if "error" in reply or "result" not in reply:
        raise BuildError([f"tools/list failed: {reply.get('error', reply)}"])
    result = reply["result"]
    if result.get("nextCursor"):
        raise BuildError(["tools/list is paginated; only a single page is supported"])
    keys = ("name", "description", "inputSchema")
    tools = [{key: tool[key] for key in keys} for tool in result.get("tools", []) if all(key in tool for key in keys)]
    if not tools or len(tools) != len(result["tools"]):
        raise BuildError([f"tools/list must return tools that all have {', '.join(keys)}"])
    return {"tools": tools}


# --- package -----------------------------------------------------------------


def write_package(package: dict, limits: dict, repo_root: Path, package_dir: Path, manifest: dict, tools: dict) -> None:
    if package_dir.exists():
        shutil.rmtree(package_dir)
    skill_src = repo_root / package["skill_dir"]
    shutil.copytree(skill_src, package_dir / "skills" / skill_src.name, ignore=shutil.ignore_patterns(".*"))
    for source in package["icons"].values():
        shutil.copyfile(repo_root / source, package_dir / Path(source).name)
    tool_file = package_dir / package["connector"]["tool_file"]
    tool_file.parent.mkdir(parents=True, exist_ok=True)
    write_json(tool_file, tools)
    write_json(package_dir / limits["manifest_file"], manifest)


def load_tools(package: dict, limits: dict, version: str, tools_file: Path | None) -> dict:
    if tools_file is not None:
        return tool_description(json.loads(tools_file.read_text(encoding="utf-8")))
    client = {"name": package["package_name"], "version": version}
    return tool_description(fetch_tools(package["connector"]["url"], limits["mcp_protocol_version"], client))


def build(package_path: Path, limits_path: Path, repo_root: Path, out_dir: Path, tools_file: Path | None = None) -> Path:
    package = load_yaml(package_path)
    limits = load_yaml(limits_path)
    frontmatter = read_frontmatter(repo_root / package["skill_dir"] / "SKILL.md")
    version = skill_version(frontmatter)
    manifest = build_manifest(package, limits, version)
    validate(manifest, package, limits, repo_root, frontmatter)
    tools = load_tools(package, limits, version, tools_file)
    name = package["package_name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    package_dir = out_dir / name
    write_package(package, limits, repo_root, package_dir, manifest, tools)
    zip_path = out_dir / f"{name}-{version}.zip"
    make_zip(package_dir, zip_path)
    return zip_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", type=Path, required=True, help="package YAML")
    parser.add_argument("--limits", type=Path, required=True, help="manifest and certification limits YAML")
    parser.add_argument("--repo-root", type=Path, required=True, help="repository root")
    parser.add_argument("--out-dir", type=Path, required=True, help="output directory")
    parser.add_argument("--tools-file", type=Path, help="saved tools/list JSON-RPC reply (default: fetch it live)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        zip_path = build(args.package, args.limits, args.repo_root, args.out_dir, args.tools_file)
    except BuildError as error:
        for problem in error.problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    print(zip_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
