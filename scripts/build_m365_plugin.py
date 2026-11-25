#!/usr/bin/env python3
"""Build the Microsoft 365 / Microsoft Copilot app package for this skill.

Reads the package, declarative agent and limits YAML files and writes a Teams
app with three capabilities: the remote MCP server as a connector with every
tool, this skill, and a declarative agent whose action is a plugin with a
function per MCP tool it keeps. The MCP server's live tools/list (or a saved
JSON-RPC reply) becomes the connector's tool description file, and the agent's
filtered copy becomes its action's tool description file and functions. Every document is validated against the Teams app
manifest, declarative agent and plugin rules in the limits file before a
deterministic ZIP is written.

Usage:
    build_m365_plugin.py --package P.yaml --agent A.yaml --limits LIM.yaml --repo-root DIR --out-dir OUT [--tools-file F.json]
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
    write_json,
)

SKILLS_DIR = "skills"
SKILL_FILE = "SKILL.md"
RGBA_8BIT = (8, 6, 0)  # bit depth, color type (RGBA), interlace (none)
RGBA_BYTES = 4
WHITE = b"\xff\xff\xff"


def lookup(document: dict, dotted: str):
    """Return the value at a dotted path such as "name.short" or "items.0.id", or "" if it is missing."""
    value = document
    for part in dotted.split("."):
        match value:
            case list() if int(part) < len(value):
                value = value[int(part)]
            case dict() if part in value:
                value = value[part]
            case _:
                return ""
    return value


# --- manifest ----------------------------------------------------------------


def full_description(package: dict) -> str:
    try:
        return "\n\n".join(paragraph.format(**package["links"]) for paragraph in package["description"]["full"])
    except KeyError as error:
        raise BuildError([f"description.full uses {{{error.args[0]}}}, which is not under links"]) from error


def build_connector(package: dict) -> dict:
    """Return the agentConnectors entry: the Senzing MCP server with every tool."""
    server = package["mcp_server"]
    connector = server["connector"]
    return {
        "id": connector["id"],
        "displayName": connector["displayName"],
        "description": connector["description"],
        "toolSource": {
            "remoteMcpServer": {
                "mcpServerUrl": server["url"],
                "mcpToolDescription": {"file": server["tool_file"]},
                "authorization": {"type": "None"},
            }
        },
    }


def build_manifest(package: dict, agent: dict, limits: dict, version: str) -> dict:
    """Return manifest.json: the MCP connector and the skill, plus the declarative agent."""
    rules = limits["manifest"]
    skill_folder = f"{rules['skill_folder_prefix']}/{Path(package['skill_dir']).name}"
    return {
        "$schema": rules["schema"],
        "manifestVersion": rules["version"],
        "version": version,
        "id": package["app_id"],
        "developer": package["developer"],
        "name": package["name"],
        "description": {"short": package["description"]["short"], "full": full_description(package)},
        "icons": {kind: Path(source).name for kind, source in package["icons"].items()},
        "accentColor": package["accent_color"],
        "agentConnectors": [build_connector(package)],
        "agentSkills": [{"folder": skill_folder}],
        "copilotAgents": {"declarativeAgents": [{"id": agent["id"], "file": limits["agent"]["file"]}]},
    }


def build_agent(package: dict, agent: dict, limits: dict) -> dict:
    """Return declarativeAgent.json: instructions, starters, the plugin action and the skill."""
    rules = limits["agent"]
    return {
        "$schema": rules["schema"],
        "version": rules["version"],
        "name": agent["name"],
        "description": agent["description"],
        "instructions": agent["instructions"],
        "behavior_overrides": {"special_instructions": {"discourage_model_knowledge": agent["discourage_model_knowledge"]}},
        "conversation_starters": agent["conversation_starters"],
        "actions": [{"id": agent["plugin"]["namespace"], "file": limits["plugin"]["file"]}],
        "agent_skills": [{"folder": f"{SKILLS_DIR}/{Path(package['skill_dir']).name}"}],
    }


def agent_tools(agent: dict, tools: dict) -> dict:
    """Return the tool description without the tools the agent excludes."""
    excluded = set(agent["excluded_tools"])
    return {"tools": [tool for tool in tools["tools"] if tool["name"] not in excluded]}


def build_function(agent: dict, tool: dict) -> dict:
    settings = agent["function_capabilities"]
    chosen = settings["overrides"].get(tool["name"], settings["default"])
    capabilities = {"security_info": {"data_handling": chosen["data_handling"]}}
    if "confirmation" in chosen:
        capabilities["confirmation"] = {"type": chosen["confirmation"]}
    description = agent["function_descriptions"].get(tool["name"], tool["description"])
    return {"name": tool["name"], "description": description, "capabilities": capabilities}


def build_plugin(package: dict, agent: dict, limits: dict, tools: dict) -> dict:
    """Return ai-plugin.json: one function per (included) MCP tool, all run by the remote MCP server."""
    rules, server = limits["plugin"], package["mcp_server"]
    return {
        "$schema": rules["schema"],
        "schema_version": rules["version"],
        **agent["plugin"],
        "functions": [build_function(agent, tool) for tool in tools["tools"]],
        "runtimes": [
            {
                "type": "RemoteMCPServer",
                "auth": {"type": "None"},
                "run_for_functions": [tool["name"] for tool in tools["tools"]],
                "spec": {"url": server["url"], "mcp_tool_description": {"file": server["agent_tool_file"]}},
            }
        ],
    }


# --- validation --------------------------------------------------------------


def check_identity(manifest: dict, limits: dict) -> list[str]:
    rules = [("version", "version_pattern"), ("id", "app_id_pattern"), ("accentColor", "accent_color_pattern")]
    return [
        f"{field} {manifest[field]!r} does not match {limits[rule]}"
        for field, rule in rules
        if not re.fullmatch(limits[rule], manifest[field])
    ]


def check_fields(document: dict, rules: dict) -> list[str]:
    """Apply a limits.yaml document section's max_chars, min_items, max_items and https_fields."""
    label = rules["file"]
    problems = [
        f"{label}: {field} is {len(lookup(document, field))} chars (max {maximum})"
        for field, maximum in rules.get("max_chars", {}).items()
        if len(lookup(document, field)) > maximum
    ]
    problems += [
        f"{label}: {field} has {len(lookup(document, field))} items (min {minimum})"
        for field, minimum in rules.get("min_items", {}).items()
        if len(lookup(document, field)) < minimum
    ]
    problems += [
        f"{label}: {field} has {len(lookup(document, field))} items (max {maximum})"
        for field, maximum in rules.get("max_items", {}).items()
        if len(lookup(document, field)) > maximum
    ]
    problems += [
        f"{label}: {field} must be an https:// URL"
        for field in rules.get("https_fields", [])
        if not lookup(document, field).startswith("https://")
    ]
    return problems


def check_mentions(manifest: dict, limits: dict) -> list[str]:
    """Every mention of the term must be part of the full phrase (no mention is fine)."""
    rule = limits["every_mention"]
    return [
        f"{field}: every mention of {rule['term']!r} must be {rule['phrase']!r}"
        for field in rule["fields"]
        if lookup(manifest, field).count(rule["term"]) != lookup(manifest, field).count(rule["phrase"])
    ]


def check_skill_folders(declarative: dict, limits: dict) -> list[str]:
    rules = limits["agent"]
    return [
        f"{rules['file']}: agent_skills folder {skill['folder']!r} must match {rules['skill_folder_pattern']}"
        for skill in declarative["agent_skills"]
        if not re.fullmatch(rules["skill_folder_pattern"], skill["folder"])
    ]


def check_skill_files(declarative: dict, limits: dict, package_dir: Path) -> list[str]:
    return [
        f"{limits['agent']['file']}: agent_skills folder {skill['folder']!r} has no {SKILL_FILE} in the package"
        for skill in declarative["agent_skills"]
        if not (package_dir / skill["folder"] / SKILL_FILE).is_file()
    ]


def check_tool_references(agent: dict, tools: dict, included: dict) -> list[str]:
    """Every tool name in the agent YAML must be a tool the MCP server lists."""
    every = {tool["name"] for tool in tools["tools"]}
    kept = {tool["name"] for tool in included["tools"]}
    problems = [f"excluded_tools: {name} is not an MCP tool" for name in agent["excluded_tools"] if name not in every]
    for section, names in (
        ("function_capabilities.overrides", agent["function_capabilities"]["overrides"]),
        ("function_descriptions", agent["function_descriptions"]),
    ):
        problems += [f"{section}.{name} is not an included MCP tool" for name in names if name not in kept]
    return problems


def check_plugin(plugin: dict, limits: dict) -> list[str]:
    rules = limits["plugin"]
    label, names = rules["file"], [function["name"] for function in plugin["functions"]]
    problems = check_fields(plugin, rules)
    for index, runtime in enumerate(plugin["runtimes"]):
        missing = [name for name in names if name not in runtime["run_for_functions"]]
        if missing:
            problems.append(
                f"{label}: runtimes.{index}.run_for_functions must list every MCP tool (missing {', '.join(missing)})"
            )
    problems += [
        f"{label}: {function['name']} confirmation type {kind!r} must be one of {', '.join(rules['confirmation_types'])}"
        for function in plugin["functions"]
        if (kind := function["capabilities"].get("confirmation", {}).get("type")) is not None
        and kind not in rules["confirmation_types"]
    ]
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


def raise_problems(problems: list[str]) -> None:
    if problems:
        raise BuildError(problems)


def validate(manifest: dict, declarative: dict, package: dict, limits: dict, repo_root: Path, frontmatter: dict) -> None:
    """Check everything that does not need the MCP tools list."""
    raise_problems(
        check_identity(manifest, limits)
        + check_skill(frontmatter, repo_root / package["skill_dir"])
        + check_fields(manifest, limits["manifest"])
        + check_mentions(manifest, limits)
        + check_icons(package, limits, repo_root)
        + check_fields(declarative, limits["agent"])
        + check_skill_folders(declarative, limits)
    )


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
    # MCP annotations (readOnlyHint and the like) mark which tools change state.
    optional = ("annotations",)
    tools = [
        {key: tool[key] for key in keys + optional if key in tool}
        for tool in result.get("tools", [])
        if all(key in tool for key in keys)
    ]
    if not tools or len(tools) != len(result["tools"]):
        raise BuildError([f"tools/list must return tools that all have {', '.join(keys)}"])
    return {"tools": tools}


# --- package -----------------------------------------------------------------


def write_package(
    package: dict, repo_root: Path, package_dir: Path, documents: dict[str, dict], tool_files: dict[str, dict]
) -> None:
    if package_dir.exists():
        shutil.rmtree(package_dir)
    skill_src = repo_root / package["skill_dir"]
    shutil.copytree(skill_src, package_dir / SKILLS_DIR / skill_src.name, ignore=shutil.ignore_patterns(".*"))
    for source in package["icons"].values():
        shutil.copyfile(repo_root / source, package_dir / Path(source).name)
    for name, tools in tool_files.items():
        tool_file = package_dir / name
        tool_file.parent.mkdir(parents=True, exist_ok=True)
        write_json(tool_file, tools)
    for name, document in documents.items():
        write_json(package_dir / name, document)


def load_tools(package: dict, limits: dict, version: str, tools_file: Path | None) -> dict:
    if tools_file is not None:
        return tool_description(json.loads(tools_file.read_text(encoding="utf-8")))
    client = {"name": package["package_name"], "version": version}
    return tool_description(fetch_tools(package["mcp_server"]["url"], limits["mcp_protocol_version"], client))


def build(
    package_path: Path, agent_path: Path, limits_path: Path, repo_root: Path, out_dir: Path, tools_file: Path | None = None
) -> Path:
    package, agent, limits = load_yaml(package_path), load_yaml(agent_path), load_yaml(limits_path)
    frontmatter = read_frontmatter(repo_root / package["skill_dir"] / SKILL_FILE)
    version = package["app_version"]
    manifest = build_manifest(package, agent, limits, version)
    declarative = build_agent(package, agent, limits)
    validate(manifest, declarative, package, limits, repo_root, frontmatter)
    every_tool = load_tools(package, limits, version, tools_file)
    tools = agent_tools(agent, every_tool)
    plugin = build_plugin(package, agent, limits, tools)
    raise_problems(check_tool_references(agent, every_tool, tools) + check_plugin(plugin, limits))
    documents = {limits["manifest"]["file"]: manifest, limits["agent"]["file"]: declarative, limits["plugin"]["file"]: plugin}
    name = package["package_name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    package_dir = out_dir / name
    server = package["mcp_server"]
    if server["tool_file"] == server["agent_tool_file"]:
        raise BuildError(["mcp_server: tool_file (every tool, for the connector) and agent_tool_file must differ"])
    tool_files = {server["tool_file"]: every_tool, server["agent_tool_file"]: tools}
    write_package(package, repo_root, package_dir, documents, tool_files)
    raise_problems(check_skill_files(declarative, limits, package_dir))
    zip_path = out_dir / f"{name}-{version}.zip"
    make_zip(package_dir, zip_path, directories=True)
    return zip_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", type=Path, required=True, help="package YAML")
    parser.add_argument("--agent", type=Path, required=True, help="declarative agent YAML")
    parser.add_argument("--limits", type=Path, required=True, help="manifest, agent and plugin limits YAML")
    parser.add_argument("--repo-root", type=Path, required=True, help="repository root")
    parser.add_argument("--out-dir", type=Path, required=True, help="output directory")
    parser.add_argument("--tools-file", type=Path, help="saved tools/list JSON-RPC reply (default: fetch it live)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        zip_path = build(args.package, args.agent, args.limits, args.repo_root, args.out_dir, args.tools_file)
    except BuildError as error:
        for problem in error.problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    print(zip_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
