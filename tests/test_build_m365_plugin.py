"""Tests for scripts/build_m365_plugin.py.

Unit tests build from the real package, agent and limits YAML and from copies
with one defect each. Contract tests fetch the live MCP server's tools/list and
check manifest.json, declarativeAgent.json and ai-plugin.json against their
published JSON schemas (network required).
"""

from __future__ import annotations

import json
import struct
import sys
import urllib.request
import zipfile
import zlib
from pathlib import Path

import jsonschema
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_m365_plugin as bmp  # noqa: E402
from build_openai_plugin import ZIP_EPOCH  # noqa: E402

PACKAGE = REPO_ROOT / "m365-plugin" / "package.yaml"
AGENT = REPO_ROOT / "m365-plugin" / "agent.yaml"
LIMITS = REPO_ROOT / "m365-plugin" / "limits.yaml"
# Partner Center and Teams tie app updates to this id; it must never change.
APP_ID = "c47a1241-83c4-459f-9e91-09f7f36de642"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def limits() -> dict:
    return load(LIMITS)


@pytest.fixture
def package() -> dict:
    return load(PACKAGE)


@pytest.fixture
def agent() -> dict:
    return load(AGENT)


@pytest.fixture(scope="module")
def tools_file(tmp_path_factory) -> Path:
    """The live tools/list reply, fetched once and saved for offline builds."""
    package, limits = load(PACKAGE), load(LIMITS)
    reply = bmp.fetch_tools(package["mcp_server"]["url"], limits["mcp_protocol_version"], {"name": "test", "version": "0"})
    return write(tmp_path_factory.mktemp("tools") / "tools.json", json.dumps(reply))


@pytest.fixture(scope="module")
def every_tool(tools_file: Path) -> dict:
    return bmp.tool_description(json.loads(tools_file.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def built(tmp_path_factory, tools_file: Path) -> Path:
    return bmp.build(PACKAGE, AGENT, LIMITS, REPO_ROOT, tmp_path_factory.mktemp("out"), tools_file)


def member(zip_path: Path, kind: str) -> dict:
    """Return a JSON document from the ZIP by its limits.yaml section (manifest, agent, plugin)."""
    return json.loads(zipfile.ZipFile(zip_path).read(load(LIMITS)[kind]["file"]))


def manifest_of(zip_path: Path) -> dict:
    return member(zip_path, "manifest")


def problems_for(package: dict, limits: dict, agent: dict | None = None) -> list[str]:
    agent = agent or load(AGENT)
    frontmatter = bmp.read_frontmatter(REPO_ROOT / package["skill_dir"] / "SKILL.md")
    manifest = bmp.build_manifest(package, agent, limits, package["app_version"])
    declarative = bmp.build_agent(package, agent, limits)
    with pytest.raises(bmp.BuildError) as error:
        bmp.validate(manifest, declarative, package, limits, REPO_ROOT, frontmatter)
    return error.value.problems


def plugin_problems(agent: dict, limits: dict, every_tool: dict) -> list[str]:
    tools = bmp.agent_tools(agent, every_tool)
    plugin = bmp.build_plugin(load(PACKAGE), agent, limits, tools)
    return bmp.check_tool_references(agent, every_tool, tools) + bmp.check_plugin(plugin, limits)


def write_png(path: Path, rows: list[list[tuple[int, int, int, int]]]) -> Path:
    """Write an 8-bit RGBA PNG (filter type 0) from rows of pixels."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    raw = b"".join(b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in rows)
    header = struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 6, 0, 0, 0)
    path.write_bytes(bmp.PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


# --- the real package -------------------------------------------------------


def test_zip_layout(built: Path, package: dict, limits: dict) -> None:
    names = zipfile.ZipFile(built).namelist()
    documents = {limits[kind]["file"] for kind in ("manifest", "agent", "plugin")}
    server = package["mcp_server"]
    assert documents | {"color.png", "outline.png", server["tool_file"], server["agent_tool_file"]} <= set(names)
    assert "skills/senzing-entity-resolution/SKILL.md" in names


def test_zip_lists_directories_first(built: Path) -> None:
    infos = zipfile.ZipFile(built).infolist()
    folders = [info.filename for info in infos if info.is_dir()]
    assert folders == ["skills/", "skills/senzing-entity-resolution/", "tools/"]
    assert [info.filename for info in infos[: len(folders)]] == folders
    assert all(info.file_size == 0 and info.date_time == ZIP_EPOCH for info in infos[: len(folders)])


def test_app_id_is_stable(built: Path) -> None:
    assert manifest_of(built)["id"] == APP_ID


def test_version_is_app_version(built: Path, package: dict) -> None:
    version = package["app_version"]
    assert manifest_of(built)["version"] == version
    assert built.name == f"{package['package_name']}-{version}.zip"


def test_manifest_has_mcp_connector_with_every_tool(built: Path, package: dict, limits: dict, every_tool: dict) -> None:
    manifest, names = manifest_of(built), zipfile.ZipFile(built).namelist()
    server = package["mcp_server"]
    [connector] = manifest["agentConnectors"]
    assert connector["id"] == server["connector"]["id"]
    assert connector["toolSource"]["remoteMcpServer"] == {
        "mcpServerUrl": server["url"],
        "mcpToolDescription": {"file": server["tool_file"]},
        "authorization": {"type": "None"},
    }
    connector_tools = json.loads(zipfile.ZipFile(built).read(server["tool_file"]))["tools"]
    assert connector_tools == every_tool["tools"]
    assert "analyze_record" in [tool["name"] for tool in connector_tools]
    [skill] = manifest["agentSkills"]
    assert skill == {"folder": f"{limits['manifest']['skill_folder_prefix']}/senzing-entity-resolution"}
    assert f"{skill['folder'].removeprefix('./')}/SKILL.md" in names


def test_manifest_declares_one_agent(built: Path, limits: dict) -> None:
    manifest = manifest_of(built)
    assert manifest["copilotAgents"] == {"declarativeAgents": [{"id": "senzing", "file": limits["agent"]["file"]}]}
    assert set(manifest["icons"].values()) <= set(zipfile.ZipFile(built).namelist())


def test_agent_paths_exist(built: Path, limits: dict) -> None:
    names = zipfile.ZipFile(built).namelist()
    declarative = member(built, "agent")
    assert declarative["actions"] == [{"id": "senzing", "file": limits["plugin"]["file"]}]
    assert declarative["agent_skills"] == [{"folder": "skills/senzing-entity-resolution"}]
    assert f"{declarative['agent_skills'][0]['folder']}/SKILL.md" in names
    assert declarative["behavior_overrides"] == {"special_instructions": {"discourage_model_knowledge": True}}


def test_instructions_route_to_tools(built: Path) -> None:
    instructions = member(built, "agent")["instructions"]
    assert len(instructions) <= 8000
    assert "get_capabilities is only for questions that no tool listed above fits" in instructions
    assert "CORD" not in instructions and "truth set" not in instructions


def test_plugin_functions_match_tool_file(built: Path, package: dict, agent: dict) -> None:
    plugin = member(built, "plugin")
    tools = json.loads(zipfile.ZipFile(built).read(package["mcp_server"]["agent_tool_file"]))["tools"]
    names = [tool["name"] for tool in tools]
    assert names and [function["name"] for function in plugin["functions"]] == names
    assert set(agent["excluded_tools"]).isdisjoint(names)
    runtime = plugin["runtimes"][0]
    assert runtime["type"] == "RemoteMCPServer" and runtime["auth"] == {"type": "None"}
    assert runtime["run_for_functions"] == names
    server = package["mcp_server"]
    assert runtime["spec"] == {"url": server["url"], "mcp_tool_description": {"file": server["agent_tool_file"]}}
    assert all(
        {"name", "description", "inputSchema"} <= set(tool) <= {"name", "description", "inputSchema", "annotations"}
        for tool in tools
    )


def test_function_overrides(built: Path, agent: dict) -> None:
    functions = {function["name"]: function for function in member(built, "plugin")["functions"]}
    assert "analyze_record" not in functions
    assert functions["get_capabilities"]["description"] == agent["function_descriptions"]["get_capabilities"]
    assert "first" not in functions["get_capabilities"]["description"]
    assert functions["submit_feedback"]["capabilities"]["confirmation"] == {"type": "AdaptiveCard"}
    assert [name for name, function in functions.items() if "confirmation" in function["capabilities"]] == ["submit_feedback"]
    assert functions["search_docs"]["capabilities"] == {"security_info": {"data_handling": ["GetPublicData"]}}


def test_full_description_fills_links(built: Path, package: dict) -> None:
    full = manifest_of(built)["description"]["full"]
    assert "{" not in full
    assert all(url in full for url in package["links"].values())


def test_zip_is_reproducible(built: Path, tools_file: Path, tmp_path: Path) -> None:
    again = bmp.build(PACKAGE, AGENT, LIMITS, REPO_ROOT, tmp_path, tools_file)
    assert again.read_bytes() == built.read_bytes()


def test_rebuild_replaces_stale_files(tmp_path: Path, tools_file: Path, package: dict) -> None:
    stale = tmp_path / package["package_name"] / "stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("old", encoding="utf-8")
    bmp.build(PACKAGE, AGENT, LIMITS, REPO_ROOT, tmp_path, tools_file)
    assert not stale.exists()


# --- contract tests (network) ----------------------------------------------


@pytest.mark.parametrize("kind", ["manifest", "agent", "plugin"])
def test_matches_published_schema(built: Path, kind: str) -> None:
    document = member(built, kind)
    with urllib.request.urlopen(document["$schema"], timeout=30) as response:
        schema = json.loads(response.read())
    # The Teams schema has patterns using \p{L}, which Python's re rejects, so
    # jsonschema.validate's metaschema check fails; validate each document
    # directly with the draft its schema declares.
    validator = jsonschema.validators.validator_for(schema)(schema)
    assert [error.message for error in validator.iter_errors(document)] == []


def test_mcp_post_unreachable() -> None:
    with pytest.raises(bmp.BuildError, match="initialize failed"):
        bmp.mcp_post("http://127.0.0.1:9/mcp", {"method": "initialize"}, "session-1")


# --- validation failures ----------------------------------------------------


def test_real_package_is_valid(package: dict, agent: dict, limits: dict, every_tool: dict) -> None:
    frontmatter = bmp.read_frontmatter(REPO_ROOT / package["skill_dir"] / "SKILL.md")
    manifest = bmp.build_manifest(package, agent, limits, package["app_version"])
    bmp.validate(manifest, bmp.build_agent(package, agent, limits), package, limits, REPO_ROOT, frontmatter)
    assert plugin_problems(agent, limits, every_tool) == []


def test_text_limits(package: dict, limits: dict) -> None:
    package["name"]["short"] = "x" * 31
    package["description"]["short"] = "y" * 81
    package["developer"]["privacyUrl"] = "http://example.com"
    problems = problems_for(package, limits)
    assert "manifest.json: name.short is 31 chars (max 30)" in problems
    assert "manifest.json: description.short is 81 chars (max 80)" in problems
    assert "manifest.json: developer.privacyUrl must be an https:// URL" in problems


def test_full_description_limit(package: dict, limits: dict) -> None:
    package["description"]["full"].append("z" * 4000)
    problems = problems_for(package, limits)
    assert any(p.startswith("manifest.json: description.full is") and p.endswith("(max 4000)") for p in problems)


def test_every_mention_must_be_microsoft_copilot(package: dict, limits: dict) -> None:
    package["description"]["short"] = "Copilot help from Microsoft Copilot"
    package["description"]["full"].append("Microsoft Copilot is first here, but Copilot alone follows.")
    problems = problems_for(package, limits)
    assert "description.short: every mention of 'Copilot' must be 'Microsoft Copilot'" in problems
    assert "description.full: every mention of 'Copilot' must be 'Microsoft Copilot'" in problems


def test_no_mention_of_copilot_is_fine(package: dict, limits: dict) -> None:
    package["description"]["short"] = "Entity resolution help"
    package["description"]["full"] = ["No mention of the assistant at all."]
    manifest = bmp.build_manifest(package, load(AGENT), limits, package["app_version"])
    assert bmp.check_mentions(manifest, limits) == []


def test_identity_patterns(package: dict, limits: dict) -> None:
    package["app_id"] = "not-a-guid"
    package["accent_color"] = "orange"
    package["app_version"] = "1.2"
    problems = problems_for(package, limits)
    assert any(p.startswith("id 'not-a-guid'") for p in problems)
    assert any(p.startswith("accentColor 'orange'") for p in problems)
    assert any(p.startswith("version '1.2'") for p in problems)


def test_skill_name_must_match(package: dict, limits: dict, tmp_path: Path) -> None:
    assert bmp.check_skill({"name": "other", "description": "d"}, tmp_path / "my-skill") == [
        "SKILL.md name 'other' must match directory 'my-skill'"
    ]


def test_unknown_link_placeholder(package: dict, agent: dict, limits: dict) -> None:
    package["description"]["full"].append("See {nowhere}")
    with pytest.raises(bmp.BuildError, match=r"uses \{nowhere\}, which is not under links"):
        bmp.build_manifest(package, agent, limits, "1.0.0")


# --- declarative agent and plugin rules (Teams sideload / store validation) --


def test_agent_limits(package: dict, agent: dict, limits: dict) -> None:
    agent["instructions"] = "i" * 8001
    agent["conversation_starters"] *= 3
    problems = problems_for(package, limits, agent)
    assert "declarativeAgent.json: instructions is 8001 chars (max 8000)" in problems
    assert "declarativeAgent.json: conversation_starters has 15 items (max 12)" in problems


def test_agent_skill_and_agent_counts(package: dict, agent: dict, limits: dict) -> None:
    declarative = bmp.build_agent(package, agent, limits)
    declarative["agent_skills"] *= 9
    declarative["conversation_starters"] = []
    assert bmp.check_fields(declarative, limits["agent"]) == [
        "declarativeAgent.json: conversation_starters has 0 items (min 1)",
        "declarativeAgent.json: agent_skills has 9 items (max 8)",
    ]
    manifest = bmp.build_manifest(package, agent, limits, package["app_version"])
    manifest["copilotAgents"]["declarativeAgents"] *= 2
    assert bmp.check_fields(manifest, limits["manifest"]) == [
        "manifest.json: copilotAgents.declarativeAgents has 2 items (max 1)"
    ]


@pytest.mark.parametrize("capability", ["agentConnectors", "agentSkills", "copilotAgents"])
def test_manifest_must_keep_connector_skill_and_agent(package: dict, agent: dict, limits: dict, capability: str) -> None:
    manifest = bmp.build_manifest(package, agent, limits, package["app_version"])
    assert bmp.check_fields(manifest, limits["manifest"]) == []
    del manifest[capability]
    field = "copilotAgents.declarativeAgents" if capability == "copilotAgents" else capability
    assert f"manifest.json: {field} has 0 items (min 1)" in bmp.check_fields(manifest, limits["manifest"])


@pytest.mark.parametrize("folder", ["./skills/senzing-entity-resolution", "senzing-entity-resolution", "skills/a/b"])
def test_skill_folder_must_be_skills_name(package: dict, agent: dict, limits: dict, folder: str) -> None:
    declarative = bmp.build_agent(package, agent, limits)
    declarative["agent_skills"] = [{"folder": folder}]
    assert bmp.check_skill_folders(declarative, limits) == [
        f"declarativeAgent.json: agent_skills folder {folder!r} must match {limits['agent']['skill_folder_pattern']}"
    ]


def test_skill_folder_needs_skill_md(package: dict, agent: dict, limits: dict, tmp_path: Path) -> None:
    declarative = bmp.build_agent(package, agent, limits)
    assert bmp.check_skill_files(declarative, limits, tmp_path) == [
        "declarativeAgent.json: agent_skills folder 'skills/senzing-entity-resolution' has no SKILL.md in the package"
    ]


def test_run_for_functions_must_list_every_tool(package: dict, agent: dict, limits: dict, every_tool: dict) -> None:
    plugin = bmp.build_plugin(package, agent, limits, bmp.agent_tools(agent, every_tool))
    plugin["runtimes"][0]["run_for_functions"] = plugin["runtimes"][0]["run_for_functions"][1:]
    first = plugin["functions"][0]["name"]
    assert bmp.check_plugin(plugin, limits) == [
        f"ai-plugin.json: runtimes.0.run_for_functions must list every MCP tool (missing {first})"
    ]


def test_plugin_needs_a_function(agent: dict, limits: dict, every_tool: dict) -> None:
    agent["excluded_tools"] = [tool["name"] for tool in every_tool["tools"]]
    agent["function_capabilities"]["overrides"] = {}
    agent["function_descriptions"] = {}
    assert plugin_problems(agent, limits, every_tool) == ["ai-plugin.json: functions has 0 items (min 1)"]


def test_confirmation_must_be_adaptive_card(agent: dict, limits: dict, every_tool: dict) -> None:
    agent["function_capabilities"]["overrides"]["submit_feedback"]["confirmation"] = "None"
    assert plugin_problems(agent, limits, every_tool) == [
        "ai-plugin.json: submit_feedback confirmation type 'None' must be one of AdaptiveCard"
    ]


def test_plugin_urls_must_be_https(package: dict, agent: dict, limits: dict, every_tool: dict) -> None:
    agent["plugin"]["privacy_policy_url"] = "http://example.com"
    assert plugin_problems(agent, limits, every_tool) == ["ai-plugin.json: privacy_policy_url must be an https:// URL"]


def test_tool_names_must_exist(agent: dict, limits: dict, every_tool: dict) -> None:
    agent["excluded_tools"] = ["analyze_record", "no_such_tool"]
    agent["function_descriptions"]["analyze_record"] = "excluded, so not a function"
    agent["function_capabilities"]["overrides"]["renamed_tool"] = {"data_handling": ["GetPublicData"]}
    assert plugin_problems(agent, limits, every_tool) == [
        "excluded_tools: no_such_tool is not an MCP tool",
        "function_capabilities.overrides.renamed_tool is not an included MCP tool",
        "function_descriptions.analyze_record is not an included MCP tool",
    ]


def test_build_reports_plugin_problems(tmp_path: Path, tools_file: Path, agent: dict) -> None:
    agent["excluded_tools"] = ["no_such_tool"]
    bad = write(tmp_path / "agent.yaml", yaml.safe_dump(agent, allow_unicode=True))
    with pytest.raises(bmp.BuildError, match="excluded_tools: no_such_tool is not an MCP tool"):
        bmp.build(PACKAGE, bad, LIMITS, REPO_ROOT, tmp_path / "out", tools_file)
    assert not (tmp_path / "out").exists()


def test_build_refuses_one_tool_file_for_connector_and_agent(tmp_path: Path, tools_file: Path, package: dict) -> None:
    package["mcp_server"]["agent_tool_file"] = package["mcp_server"]["tool_file"]
    bad = write(tmp_path / "package.yaml", yaml.safe_dump(package, allow_unicode=True))
    with pytest.raises(bmp.BuildError, match="tool_file .* and agent_tool_file must differ"):
        bmp.build(bad, AGENT, LIMITS, REPO_ROOT, tmp_path / "out", tools_file)


def test_icon_wrong_size(package: dict, limits: dict) -> None:
    package["icons"]["color"], package["icons"]["outline"] = package["icons"]["outline"], package["icons"]["color"]
    problems = problems_for(package, limits)
    assert any(p.startswith("color icon") and p.endswith("is 32x32 (needs 192x192)") for p in problems)
    assert any(p.startswith("outline icon") and p.endswith("is 192x192 (needs 32x32)") for p in problems)


def test_icon_must_be_png(package: dict, limits: dict) -> None:
    package["icons"]["color"] = "assets/ember-rule.svg"
    assert any("not a PNG file" in p for p in problems_for(package, limits))


def test_outline_must_be_rgba(tmp_path: Path, limits: dict) -> None:
    rgb = tmp_path / "rgb.png"
    data = bytearray((REPO_ROOT / "m365-plugin" / "icons" / "outline.png").read_bytes())
    data[25] = 2  # color type RGB
    rgb.write_bytes(bytes(data))
    with pytest.raises(bmp.BuildError, match="must be an 8-bit RGBA, non-interlaced PNG"):
        bmp.check_white_on_transparent(rgb)


def test_outline_must_be_white(tmp_path: Path) -> None:
    clear, white, orange = (0, 0, 0, 0), (255, 255, 255, 255), (245, 120, 38, 255)
    path = write_png(tmp_path / "o.png", [[clear, white], [orange, orange]])
    assert bmp.check_white_on_transparent(path) == [f"{path}: 2 visible pixels are not white"]


def test_outline_must_be_transparent(tmp_path: Path) -> None:
    white = (255, 255, 255, 255)
    path = write_png(tmp_path / "o.png", [[white, white]])
    assert bmp.check_white_on_transparent(path) == [f"{path}: has no transparent pixels"]


def test_outline_decodes(tmp_path: Path) -> None:
    pixels = [[(0, 0, 0, 0), (255, 255, 255, 128)], [(255, 255, 255, 255), (1, 2, 3, 0)]]
    path = write_png(tmp_path / "o.png", pixels)
    assert bmp.png_rgba_pixels(path) == [bytes(p) for row in pixels for p in row]


def test_png_predictors() -> None:
    assert [bmp.predictor(kind, 10, 20, 5) for kind in range(4)] == [0, 10, 20, 15]
    assert bmp.predictor(4, 10, 20, 5) == 20  # estimate 25: closest to up
    assert bmp.predictor(4, 20, 10, 5) == 20  # estimate 25: closest to left
    assert bmp.predictor(4, 10, 12, 30) == 10  # estimate -8: closest to left
    assert bmp.predictor(4, 50, 10, 40) == 10  # estimate 20: closest to up
    assert bmp.predictor(4, 0, 0, 1) == 0  # tie between left and up: left wins
    assert bmp.predictor(4, 100, 0, 49) == 49  # estimate 51: closest to up_left
    with pytest.raises(bmp.BuildError, match="unknown PNG filter type 5"):
        bmp.predictor(5, 0, 0, 0)


# --- tools/list parsing -----------------------------------------------------


TOOL = {"name": "search_docs", "description": "Search", "inputSchema": {"type": "object"}, "title": "Search docs"}


def test_tool_description_keeps_manifest_fields() -> None:
    reply = {"jsonrpc": "2.0", "id": 2, "result": {"tools": [TOOL]}}
    assert bmp.tool_description(reply) == {"tools": [{k: TOOL[k] for k in ("name", "description", "inputSchema")}]}


def test_tool_description_keeps_annotations() -> None:
    tool = TOOL | {"annotations": {"readOnlyHint": False}}
    reply = {"jsonrpc": "2.0", "id": 2, "result": {"tools": [tool]}}
    [kept] = bmp.tool_description(reply)["tools"]
    assert kept["annotations"] == {"readOnlyHint": False} and "title" not in kept


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ({"error": {"code": -32601}}, "tools/list failed"),
        ({}, "tools/list failed"),
        ({"result": {"tools": [TOOL], "nextCursor": "2"}}, "paginated"),
        ({"result": {"tools": []}}, "must return tools"),
        ({"result": {"tools": [TOOL, {"name": "x"}]}}, "must return tools"),
    ],
)
def test_tool_description_rejects(reply: dict, message: str) -> None:
    with pytest.raises(bmp.BuildError, match=message):
        bmp.tool_description(reply)


def test_parse_rpc_body() -> None:
    assert bmp.parse_rpc_body("application/json", "") is None
    assert bmp.parse_rpc_body("application/json", '{"id": 1}') == {"id": 1}
    stream = 'event: message\ndata: {"method": "notifications/progress"}\n\ndata: {"id": 2, "result": {}}\n\n'
    assert bmp.parse_rpc_body("text/event-stream", stream) == {"id": 2, "result": {}}
    assert bmp.parse_rpc_body("text/event-stream", 'data: {"method": "ping"}\n') is None


def test_lookup() -> None:
    document = {"a": [{"b": "x"}]}
    assert bmp.lookup(document, "a.0.b") == "x"
    assert bmp.lookup(document, "missing") == ""
    assert bmp.lookup(document, "a.1.b") == ""
    assert bmp.lookup(document, "a.0.b.c") == ""


# --- command line -----------------------------------------------------------


def cli_args(package_path: Path, out_dir: Path, *extra: str) -> list[str]:
    return [
        "--package",
        str(package_path),
        "--agent",
        str(AGENT),
        "--limits",
        str(LIMITS),
        "--repo-root",
        str(REPO_ROOT),
        "--out-dir",
        str(out_dir),
        *extra,
    ]


def test_main_fetches_tools_live(tmp_path: Path, capsys) -> None:
    assert bmp.main(cli_args(PACKAGE, tmp_path)) == 0
    assert capsys.readouterr().out.strip().endswith(".zip")


def test_main_reports_every_problem(tmp_path: Path, package: dict, capsys) -> None:
    package["name"]["short"] = "x" * 31
    package["accent_color"] = "orange"
    bad = write(tmp_path / "package.yaml", yaml.safe_dump(package, allow_unicode=True))
    assert bmp.main(cli_args(bad, tmp_path / "out")) == 1
    errors = capsys.readouterr().err
    assert "name.short is 31 chars" in errors
    assert "accentColor 'orange'" in errors
    assert not (tmp_path / "out").exists()


def test_main_uses_sys_argv(tmp_path: Path, tools_file: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["build_m365_plugin.py", *cli_args(PACKAGE, tmp_path, "--tools-file", str(tools_file))])
    assert bmp.main() == 0
