"""Tests for scripts/build_openai_plugin.py.

Unit tests build from the real listing and from copies with one defect each.
Contract tests check the output against the published Agent Plugins JSON
schemas and the live MCP server's tool list (network required).
"""

from __future__ import annotations

import copy
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

import jsonschema
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_openai_plugin as bop  # noqa: E402

LISTING = REPO_ROOT / "openai-plugin" / "listing.yaml"
LIMITS = REPO_ROOT / "openai-plugin" / "limits.yaml"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    return bop.build(LISTING, LIMITS, REPO_ROOT, tmp_path_factory.mktemp("out"))


@pytest.fixture
def listing() -> dict:
    return load(LISTING)


@pytest.fixture(scope="module")
def limits() -> dict:
    return load(LIMITS)


def problems_for(listing: dict, limits: dict) -> list[str]:
    frontmatter = bop.read_frontmatter(REPO_ROOT / listing["skill_dir"] / "SKILL.md")
    version = bop.skill_version(frontmatter)
    with pytest.raises(bop.BuildError) as error:
        bop.validate(listing, limits, REPO_ROOT, frontmatter, version)
    return error.value.problems


# --- the real package -------------------------------------------------------


def test_zip_layout(built: Path) -> None:
    names = set(zipfile.ZipFile(built).namelist())
    assert {"plugin.json", "mcp.json", "LICENSE", "assets/icon.png"} <= names
    assert "skills/senzing-entity-resolution/SKILL.md" in names
    assert not any(n.startswith(("hooks/", ".app.json", ".codex-plugin/")) for n in names)


def test_version_tracks_skill(built: Path, listing: dict) -> None:
    frontmatter = bop.read_frontmatter(REPO_ROOT / listing["skill_dir"] / "SKILL.md")
    version = bop.skill_version(frontmatter)
    manifest = json.loads(zipfile.ZipFile(built).read("plugin.json"))
    assert manifest["version"] == version
    assert built.name == f"{listing['manifest']['name']}-openai-plugin-{version}.zip"


def test_zip_is_reproducible(built: Path, tmp_path: Path) -> None:
    again = bop.build(LISTING, LIMITS, REPO_ROOT, tmp_path)
    assert again.read_bytes() == built.read_bytes()


def test_rebuild_replaces_stale_files(tmp_path: Path, listing: dict) -> None:
    stale = tmp_path / listing["manifest"]["name"] / "stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("old", encoding="utf-8")
    bop.build(LISTING, LIMITS, REPO_ROOT, tmp_path)
    assert not stale.exists()


def test_manifest_paths_exist(built: Path) -> None:
    archive = zipfile.ZipFile(built)
    interface = json.loads(archive.read("plugin.json"))["extensions"]["com.openai"]["interface"]
    for key in ("logo", "composerIcon"):
        assert interface[key].startswith("./")
        assert interface[key][2:] in archive.namelist()


# --- contract tests (network) ----------------------------------------------


def fetch_json(url: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


@pytest.mark.parametrize("member", ["plugin.json", "mcp.json"])
def test_matches_agent_plugins_schema(built: Path, member: str) -> None:
    document = json.loads(zipfile.ZipFile(built).read(member))
    jsonschema.validate(document, fetch_json(document["$schema"]))


def test_review_tools_exist_on_live_server(built: Path) -> None:
    archive = zipfile.ZipFile(built)
    server = next(iter(json.loads(archive.read("mcp.json"))["mcpServers"].values()))
    reply = fetch_json(server["url"], {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    live = {tool["name"] for tool in reply["result"]["tools"]}
    cases = json.loads(archive.read("plugin.json"))["extensions"]["com.openai"]["review"]["test_cases"]
    wanted = {name.strip() for case in cases["positive"] for name in case["tools_triggered"].split(",")}
    assert wanted <= live, f"unknown tools: {wanted - live}"


# --- validation failures ----------------------------------------------------


def test_text_limits(listing: dict, limits: dict) -> None:
    listing["interface"]["displayName"] = "x" * 31
    listing["interface"]["supportURL"] = "http://example.com"
    del listing["interface"]["category"]
    problems = problems_for(listing, limits)
    assert any("displayName is 31 chars" in p for p in problems)
    assert any("supportURL must be an https" in p for p in problems)
    assert any("category is required" in p for p in problems)


def test_list_limits(listing: dict, limits: dict) -> None:
    listing["interface"]["defaultPrompt"] = ["a", "a", "b", "c" * 129]
    problems = problems_for(listing, limits)
    assert any("defaultPrompt has 4 items" in p for p in problems)
    assert any("defaultPrompt item exceeds 128" in p for p in problems)
    assert any("defaultPrompt items must be unique" in p for p in problems)


def test_brand_colors(listing: dict, limits: dict) -> None:
    listing["interface"]["brandColor"] = "#FFFF00"
    listing["interface"]["brandColorDark"] = "orange"
    problems = problems_for(listing, limits)
    assert any(p.startswith("interface.brandColor #FFFF00 contrast") for p in problems)
    assert any("brandColorDark must be #RRGGBB" in p for p in problems)


def test_brand_colors_optional(listing: dict, limits: dict) -> None:
    del listing["interface"]["brandColor"]
    del listing["interface"]["brandColorDark"]
    assert bop.check_brand_colors(listing["interface"], limits) == []


def test_contrast_ratio_known_values() -> None:
    assert bop.contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert bop.contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0)


def test_icon_not_in_assets(listing: dict, limits: dict) -> None:
    listing["interface"]["logo"] = "./assets/missing.png"
    assert any("'./assets/missing.png' is not listed under assets" in p for p in problems_for(listing, limits))


def test_icon_must_be_square(listing: dict, limits: dict) -> None:
    listing["assets"]["./assets/icon.png"] = "assets/senzing-logo-light-theme.png"
    assert any("icon must be square" in p for p in problems_for(listing, limits))


def test_icon_too_large(listing: dict, limits: dict) -> None:
    small = copy.deepcopy(limits)
    small["icon"]["max_bytes"] = 10
    assert any("icon exceeds 10 bytes" in p for p in problems_for(listing, small))


def test_icon_must_be_png(listing: dict, limits: dict) -> None:
    listing["assets"]["./assets/icon.png"] = "assets/ember-rule.svg"
    assert any("not a PNG file" in p for p in problems_for(listing, limits))


def test_review_case_counts_and_fields(listing: dict, limits: dict) -> None:
    cases = listing["review"]["test_cases"]
    cases["positive"].pop()
    del cases["negative"][0]["prompt"]
    problems = problems_for(listing, limits)
    assert any("positive has 4 cases (need 5)" in p for p in problems)
    assert any("negative[0] missing prompt" in p for p in problems)


def test_identity(listing: dict, limits: dict) -> None:
    listing["manifest"]["name"] = "Senzing--Plugin"
    listing["manifest"]["description"] = "x" * 4001
    problems = bop.check_identity(listing, limits, "1.2")
    assert any("manifest.name 'Senzing--Plugin'" in p for p in problems)
    assert any("version '1.2' is not MAJOR.MINOR.PATCH" in p for p in problems)
    assert any("manifest.description is too long" in p for p in problems)


def test_skill_frontmatter_checks(tmp_path: Path) -> None:
    skill = tmp_path / "my-skill"
    assert bop.check_skill({"name": "other", "description": "d"}, skill) == [
        "SKILL.md name 'other' must match directory 'my-skill'"
    ]
    assert bop.check_skill({}, skill) == ["SKILL.md: name is required", "SKILL.md: description is required"]


# --- file parsing -----------------------------------------------------------


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_frontmatter_missing(tmp_path: Path) -> None:
    with pytest.raises(bop.BuildError, match="missing YAML frontmatter"):
        bop.read_frontmatter(write(tmp_path / "SKILL.md", "no frontmatter\n"))


def test_frontmatter_not_mapping(tmp_path: Path) -> None:
    with pytest.raises(bop.BuildError, match="not a mapping"):
        bop.read_frontmatter(write(tmp_path / "SKILL.md", "---\n- a\n---\nbody\n"))


def test_skill_version_missing() -> None:
    with pytest.raises(bop.BuildError, match="metadata.version is missing"):
        bop.skill_version({"metadata": {}})
    with pytest.raises(bop.BuildError, match="metadata.version is missing"):
        bop.skill_version({})


def test_load_yaml_not_mapping(tmp_path: Path) -> None:
    with pytest.raises(bop.BuildError, match="expected a YAML mapping"):
        bop.load_yaml(write(tmp_path / "x.yaml", "- a\n"))


# --- command line -----------------------------------------------------------


def cli_args(listing_path: Path, out_dir: Path) -> list[str]:
    return ["--listing", str(listing_path), "--limits", str(LIMITS), "--repo-root", str(REPO_ROOT), "--out-dir", str(out_dir)]


def test_main_success(tmp_path: Path, capsys) -> None:
    assert bop.main(cli_args(LISTING, tmp_path)) == 0
    assert capsys.readouterr().out.strip().endswith(".zip")


def test_main_reports_every_problem(tmp_path: Path, listing: dict, capsys) -> None:
    listing["interface"]["displayName"] = "x" * 31
    listing["interface"]["shortDescription"] = "y" * 31
    bad = tmp_path / "listing.yaml"
    bad.write_text(yaml.safe_dump(listing), encoding="utf-8")
    assert bop.main(cli_args(bad, tmp_path / "out")) == 1
    errors = capsys.readouterr().err
    assert "displayName is 31 chars" in errors
    assert "shortDescription is 31 chars" in errors
    assert not (tmp_path / "out").exists()


def test_main_uses_sys_argv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["build_openai_plugin.py", *cli_args(LISTING, tmp_path)])
    assert bop.main() == 0
