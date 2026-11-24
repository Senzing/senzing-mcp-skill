"""Tests for scripts/build_m365_plugin.py.

Unit tests build from the real package YAML and from copies with one defect
each. Contract tests fetch the live MCP server's tools/list and check the
manifest against the published Teams app manifest JSON schema (network required).
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

PACKAGE = REPO_ROOT / "m365-plugin" / "package.yaml"
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


@pytest.fixture(scope="module")
def tools_file(tmp_path_factory) -> Path:
    """The live tools/list reply, fetched once and saved for offline builds."""
    package, limits = load(PACKAGE), load(LIMITS)
    reply = bmp.fetch_tools(package["connector"]["url"], limits["mcp_protocol_version"], {"name": "test", "version": "0"})
    return write(tmp_path_factory.mktemp("tools") / "tools.json", json.dumps(reply))


@pytest.fixture(scope="module")
def built(tmp_path_factory, tools_file: Path) -> Path:
    return bmp.build(PACKAGE, LIMITS, REPO_ROOT, tmp_path_factory.mktemp("out"), tools_file)


def manifest_of(zip_path: Path) -> dict:
    return json.loads(zipfile.ZipFile(zip_path).read("manifest.json"))


def problems_for(package: dict, limits: dict) -> list[str]:
    frontmatter = bmp.read_frontmatter(REPO_ROOT / package["skill_dir"] / "SKILL.md")
    manifest = bmp.build_manifest(package, limits, bmp.skill_version(frontmatter))
    with pytest.raises(bmp.BuildError) as error:
        bmp.validate(manifest, package, limits, REPO_ROOT, frontmatter)
    return error.value.problems


def write_png(path: Path, rows: list[list[tuple[int, int, int, int]]]) -> Path:
    """Write an 8-bit RGBA PNG (filter type 0) from rows of pixels."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    raw = b"".join(b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in rows)
    header = struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 6, 0, 0, 0)
    path.write_bytes(bmp.PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


# --- the real package -------------------------------------------------------


def test_zip_layout(built: Path, package: dict) -> None:
    names = set(zipfile.ZipFile(built).namelist())
    assert {"manifest.json", "color.png", "outline.png", package["connector"]["tool_file"]} <= names
    assert "skills/senzing-entity-resolution/SKILL.md" in names


def test_app_id_is_stable(built: Path) -> None:
    assert manifest_of(built)["id"] == APP_ID


def test_version_tracks_skill(built: Path, package: dict) -> None:
    version = bmp.skill_version(bmp.read_frontmatter(REPO_ROOT / package["skill_dir"] / "SKILL.md"))
    assert manifest_of(built)["version"] == version
    assert built.name == f"{package['package_name']}-{version}.zip"


def test_manifest_paths_exist(built: Path) -> None:
    archive = zipfile.ZipFile(built)
    manifest = manifest_of(built)
    names = archive.namelist()
    assert set(manifest["icons"].values()) <= set(names)
    connector = manifest["agentConnectors"][0]["toolSource"]["remoteMcpServer"]
    assert connector["mcpToolDescription"]["file"] in names
    assert connector["authorization"] == {"type": "None"}
    folder = manifest["agentSkills"][0]["folder"]
    assert f"{folder.removeprefix('./')}/SKILL.md" in names


def test_tool_file_lists_live_tools(built: Path, package: dict) -> None:
    tools = json.loads(zipfile.ZipFile(built).read(package["connector"]["tool_file"]))["tools"]
    assert tools
    assert all(set(tool) == {"name", "description", "inputSchema"} for tool in tools)


def test_full_description_fills_links(built: Path, package: dict) -> None:
    full = manifest_of(built)["description"]["full"]
    assert "{" not in full
    assert all(url in full for url in package["links"].values())


def test_zip_is_reproducible(built: Path, tools_file: Path, tmp_path: Path) -> None:
    again = bmp.build(PACKAGE, LIMITS, REPO_ROOT, tmp_path, tools_file)
    assert again.read_bytes() == built.read_bytes()


def test_rebuild_replaces_stale_files(tmp_path: Path, tools_file: Path, package: dict) -> None:
    stale = tmp_path / package["package_name"] / "stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("old", encoding="utf-8")
    bmp.build(PACKAGE, LIMITS, REPO_ROOT, tmp_path, tools_file)
    assert not stale.exists()


# --- contract tests (network) ----------------------------------------------


def test_matches_teams_manifest_schema(built: Path) -> None:
    manifest = manifest_of(built)
    with urllib.request.urlopen(manifest["$schema"], timeout=30) as response:
        schema = json.loads(response.read())
    # The published schema has patterns using \p{L}, which Python's re rejects,
    # so jsonschema.validate's metaschema check fails; validate the manifest
    # directly with the draft the schema declares.
    validator = jsonschema.validators.validator_for(schema)(schema)
    assert [error.message for error in validator.iter_errors(manifest)] == []


def test_mcp_post_unreachable() -> None:
    with pytest.raises(bmp.BuildError, match="initialize failed"):
        bmp.mcp_post("http://127.0.0.1:9/mcp", {"method": "initialize"}, "session-1")


# --- validation failures ----------------------------------------------------


def test_real_package_is_valid(package: dict, limits: dict) -> None:
    frontmatter = bmp.read_frontmatter(REPO_ROOT / package["skill_dir"] / "SKILL.md")
    manifest = bmp.build_manifest(package, limits, bmp.skill_version(frontmatter))
    bmp.validate(manifest, package, limits, REPO_ROOT, frontmatter)


def test_text_limits(package: dict, limits: dict) -> None:
    package["name"]["short"] = "x" * 31
    package["description"]["short"] = "y" * 81
    package["developer"]["privacyUrl"] = "http://example.com"
    problems = problems_for(package, limits)
    assert "name.short is 31 chars (max 30)" in problems
    assert "description.short is 81 chars (max 80)" in problems
    assert "developer.privacyUrl must be an https:// URL" in problems


def test_full_description_limit(package: dict, limits: dict) -> None:
    package["description"]["full"].append("z" * 4000)
    assert any(p.startswith("description.full is") and p.endswith("(max 4000)") for p in problems_for(package, limits))


def test_first_mention_must_be_microsoft_copilot(package: dict, limits: dict) -> None:
    package["description"]["short"] = "Copilot help from Microsoft Copilot"
    package["description"]["full"] = ["No mention of the assistant at all."]
    problems = problems_for(package, limits)
    assert "description.short: the first mention of 'Copilot' must be 'Microsoft Copilot'" in problems
    assert "description.full: the first mention of 'Copilot' must be 'Microsoft Copilot'" in problems


def test_identity_patterns(package: dict, limits: dict) -> None:
    package["app_id"] = "not-a-guid"
    package["accent_color"] = "orange"
    problems = problems_for(package, limits)
    assert any(p.startswith("id 'not-a-guid'") for p in problems)
    assert any(p.startswith("accentColor 'orange'") for p in problems)
    manifest = bmp.build_manifest(package, limits, "1.2")
    assert any(p.startswith("version '1.2'") for p in bmp.check_identity(manifest, limits))


def test_skill_name_must_match(package: dict, limits: dict, tmp_path: Path) -> None:
    assert bmp.check_skill({"name": "other", "description": "d"}, tmp_path / "my-skill") == [
        "SKILL.md name 'other' must match directory 'my-skill'"
    ]


def test_unknown_link_placeholder(package: dict, limits: dict) -> None:
    package["description"]["full"].append("See {nowhere}")
    with pytest.raises(bmp.BuildError, match=r"uses \{nowhere\}, which is not under links"):
        bmp.build_manifest(package, limits, "1.0.0")


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


# --- command line -----------------------------------------------------------


def cli_args(package_path: Path, out_dir: Path, *extra: str) -> list[str]:
    return [
        "--package",
        str(package_path),
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
