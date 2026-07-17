# Senzing Entity Resolution — Agent Skill

An **Agent Skill** that teaches AI agents how to use the
[Senzing](https://senzing.com) MCP server for entity resolution workflows. It is
a portable, client-agnostic skill — usable from any skill-compatible agent or
marketplace (e.g. [skillsmp.com](https://skillsmp.com),
[agentskills.io](https://agentskills.io)).

## What It Does

This skill enables AI agents to:

- **Map source data** to Senzing entity resolution format (CSV, JSON, etc.)
- **Set up the Senzing SDK** with guided install across 5 platforms and 5 languages, including direct package downloads for firewalled environments
- **Generate SDK code** in Python, Java, C#, Rust, and TypeScript/Node.js
- **Search documentation** across SDK guides, entity specification, quickstarts, and more
- **Troubleshoot errors** with causes and resolution steps for 456 error codes
- **Build reporting** with SQL analytics, data marts, dashboards, graph export, and ER quality/evaluation metrics
- **Access sample data** from real-world CORD datasets and the Senzing truthset
- **Migrate V3 to V4** with breaking change mappings and flag references
- **Request an evaluation license** — a free 10-day, 250K-record trial

## Installation

The skill requires the Senzing MCP server. Add it to your client:

**Claude Code:**

```bash
claude mcp add --transport http senzing https://mcp.senzing.com/mcp
```

**Claude Desktop / Other MCP Clients** — add to your MCP config:

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

## Skill Definition

See [SKILL.md](senzing-entity-resolution/SKILL.md) for the full skill manifest
including tool reference, workflows, best practices, and entity resolution glossary.

Verified against Senzing MCP server **v1.28.8** (2026-07). The skill's
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
