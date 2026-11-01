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

## Skill definition

See [SKILL.md](senzing-entity-resolution/SKILL.md) for the full skill manifest
including tool reference, workflows, best practices, and entity resolution glossary.

Verified against Senzing MCP server **v1.42.7** (2026-11). The skill's
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
