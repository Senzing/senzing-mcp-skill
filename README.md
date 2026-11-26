<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/senzing-logo-dark-theme.png">
    <img src="assets/senzing-logo-light-theme.png" alt="Senzing" width="240">
  </picture>
</p>

<h1 align="center">Senzing entity resolution — agent skill</h1>

<p align="center">
  <b>An Agent Skill that teaches AI agents how to use the <a href="https://senzing.com">SENZING® MCP server</a> for entity resolution workflows.</b>
</p>

<p align="center">
  <a href="https://registry.modelcontextprotocol.io/v0/servers/com.senzing%2Fmcp/versions/latest"><img src="https://img.shields.io/badge/MCP_Registry-com.senzing%2Fmcp-F57826?logo=modelcontextprotocol&logoColor=white&style=flat-square&labelColor=0F0D0C" alt="MCP Registry: com.senzing/mcp"></a>
  <img src="https://img.shields.io/badge/Agent_Skill-SKILL.md-F57826?style=flat-square&labelColor=0F0D0C" alt="Agent Skill: SKILL.md">
  <img src="https://img.shields.io/badge/Requires-Senzing_MCP_server-F57826?style=flat-square&labelColor=0F0D0C" alt="Requires: Senzing MCP server">
</p>

<p align="center">
  <a href="#what-it-does">What it does</a> ·
  <a href="#installation">Installation</a> ·
  <a href="#openai-plugin-package">OpenAI plugin</a> ·
  <a href="#microsoft-365-copilot-package">Microsoft 365 Copilot</a> ·
  <a href="#skill-definition">Skill definition</a> ·
  <a href="#privacy">Privacy</a> ·
  <a href="#license">License</a>
</p>

<img src="assets/ember-rule.svg" alt="" width="100%" height="4">

It is a portable, client-agnostic skill — usable from any skill-compatible agent or
marketplace (e.g. [skillsmp.com](https://skillsmp.com),
[agentskills.io](https://agentskills.io)).

## What it does

This skill enables AI agents to:

- **Map source data** to Senzing entity resolution format (CSV, JSON, etc.)
- **Set up the Senzing SDK** with guided install across 5 platforms and 5 languages, including direct package downloads for firewalled environments
- **Generate SDK code** in Python, Java, C#, Rust and TypeScript/Node.js
- **Search documentation** across SDK guides, entity specification, quickstarts, and more
- **Troubleshoot errors** with causes and resolution steps for 450+ error codes
- **Build reporting** with SQL analytics, data marts, dashboards, graph export and entity resolution quality/evaluation metrics
- **Access sample data** from real-world CORD datasets and the Senzing truthset
- **Migrate V3 to V4** with breaking change mappings and flag references
- **Request an evaluation license** — a free 10-day, 250K-record trial

## Installation

The skill requires the Senzing MCP server. Add it to your client:

**Claude Code:**

```bash
claude mcp add --transport http senzing https://mcp.senzing.com/mcp
```

**Claude Desktop / other MCP clients** — add to your MCP config:

```json
{
  "mcpServers": {
    "senzing": {
      "type": "url",
      "url": "https://mcp.senzing.com/mcp"
    }
  }
}
```

**ChatGPT and Codex:** the skill and the MCP server ship together as the
[Senzing plugin in the ChatGPT and Codex plugin directory](https://chatgpt.com/plugins/plugin_asdk_app_6af86f982ca08191b15c32c5c9c485a1).
Open the listing and click **Install plugin**. How the package is built is in
[OpenAI plugin package](#openai-plugin-package).

**Codex, MCP server only:**

```bash
codex mcp add senzing --url https://mcp.senzing.com/mcp
```

## OpenAI plugin package

The package is live in the
[ChatGPT and Codex plugin directory](https://chatgpt.com/plugins/plugin_asdk_app_6af86f982ca08191b15c32c5c9c485a1).

[`scripts/build_openai_plugin.py`](scripts/build_openai_plugin.py) builds the
package for the ChatGPT and Codex plugin directory: a portable Agent Plugins
`plugin.json`, an `mcp.json` pointing at `https://mcp.senzing.com/mcp`, this
skill under `skills/`, and the icon. It reads its listing text, review test
cases and URLs from [`openai-plugin/listing.yaml`](openai-plugin/listing.yaml)
and checks them against the directory submission limits in
[`openai-plugin/limits.yaml`](openai-plugin/limits.yaml). The plugin version is
the skill's `metadata.version`.

The [plugin packages workflow](.github/workflows/plugin-packages.yml) tests and
builds the ZIP on every pull request and push. When a push to `main` carries a
plugin version with no GitHub release yet, it creates release `v<version>` with
the ZIP attached ([`scripts/release_plugin.sh`](scripts/release_plugin.sh)),
so each version sync produces a ready-to-upload ZIP. OpenAI has no upload API,
so the upload itself stays manual. To build locally:

```bash
python -m pip install -r requirements-dev.txt
pytest
python scripts/build_openai_plugin.py --listing openai-plugin/listing.yaml --limits openai-plugin/limits.yaml --repo-root . --out-dir dist
```

Upload the ZIP in the [OpenAI plugin submission portal](https://developers.openai.com/plugins/deploy/submission).
The demo video, reviewer details and country availability are entered there.

## Microsoft 365 Copilot package

[`scripts/build_m365_plugin.py`](scripts/build_m365_plugin.py) builds the
Microsoft 365 / Microsoft Copilot app package. Like the OpenAI plugin (MCP
server plus this skill), it ships the Senzing MCP server as a connector with
every tool and this skill, and adds a declarative agent that routes Senzing
questions to those tools:

| File | Contents |
| --- | --- |
| `manifest.json` | Teams app manifest (v1.28): the MCP connector (`agentConnectors`), this skill (`agentSkills`) and one declarative agent |
| `declarativeAgent.json` | The agent (v1.9): instructions, conversation starters, one action and this skill under `skills/` |
| `ai-plugin.json` | The action (plugin manifest v2.4): one function per MCP tool, run by the anonymous remote MCP server `https://mcp.senzing.com/mcp` |
| `tools/senzing-tools.json` | The connector's MCP tool description: every tool from the live server's `tools/list` |
| `tools/senzing-agent-tools.json` | The agent action's tool description: the same tools minus `excluded_tools`, with `function_descriptions` applied |
| `color.png`, `outline.png` | App icons |

The data lives in YAML: app id, version, names, links and descriptions in
[`m365-plugin/package.yaml`](m365-plugin/package.yaml); the agent's
instructions, starters, plugin fields, excluded tools and per-function
descriptions and capabilities in [`m365-plugin/agent.yaml`](m365-plugin/agent.yaml);
the schemas and Microsoft store validation rules in
[`m365-plugin/limits.yaml`](m365-plugin/limits.yaml). The builder enforces
those rules before writing a ZIP: the app name names no Microsoft product
(`app_name`), every mention of Copilot is "Microsoft Copilot", the outline
icon is white on transparent, the instructions fit in 8,000 characters,
`run_for_functions` lists every included MCP tool, each skill folder in the
agent is `skills/<name>` (no leading `./`; the manifest's
`agentSkills` uses `./skills/<name>`) and holds `SKILL.md`, confirmations
are `AdaptiveCard` or absent, and every tool named in `agent.yaml` is one the
server lists. The tests also validate the three JSON files against their
published schemas.

The app version is `app_version` in `package.yaml`, separate from the skill's
`metadata.version`; the app id must never change. Partner Center needs a higher
version for every package update, so bump `app_version` whenever the package
changes. The ZIP is `senzing-m365-plugin-<app_version>.zip`.

The [plugin packages workflow](.github/workflows/plugin-packages.yml) builds this
ZIP alongside the OpenAI one and attaches it to the same release
`v<skill version>`. A new `app_version` is a new asset there; a changed ZIP with
an unchanged `app_version` only raises a warning. To build locally:

```bash
python scripts/build_m365_plugin.py --package m365-plugin/package.yaml --agent m365-plugin/agent.yaml --limits m365-plugin/limits.yaml --repo-root . --out-dir dist
```

Upload the ZIP in Partner Center under **Marketplace offers → senzing → Packages**.

## Skill definition

See [SKILL.md](senzing-entity-resolution/SKILL.md) for the full skill manifest
including tool reference, workflows, best practices, and entity resolution glossary.

Verified against Senzing MCP server **v1.47.1** (2026-11). The skill's
`version` field tracks the server version it was validated against.

## Privacy

The Senzing MCP server works from pre-fetched documentation. It never connects
to live Senzing instances and never handles PII. Data mapping and analysis
scripts run locally on the client.

The MCP server is provided **AS-IS with no warranty** of merchantability,
fitness, accuracy, or reliability. Do not rely on its output for production
decisions without independent verification, and do not send PII, credentials, or
sensitive data — all tool calls may be logged.

## License

Proprietary — © Senzing. See [LICENSE](LICENSE) and the
[SKILL.md](senzing-entity-resolution/SKILL.md) frontmatter.
