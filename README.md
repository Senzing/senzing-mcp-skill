# Senzing Entity Resolution — Agent Skill

An [Agent Skill](https://agentskills.io) that teaches AI agents how to use the
[Senzing](https://senzing.com) MCP server for entity resolution workflows.

## What It Does

This skill enables AI agents to:

- **Map source data** to Senzing entity resolution format (CSV, JSON, etc.)
- **Set up the Senzing SDK** with guided install across 5 platforms and 4 languages, including direct package downloads for firewalled environments
- **Generate SDK code** in Python, Java, C#, Rust, and TypeScript/Node.js
- **Search documentation** across SDK guides, entity specification, quickstarts, and more
- **Troubleshoot errors** with causes and resolution steps for 456 error codes
- **Build reporting** with SQL analytics, data marts, dashboards, and graph export
- **Access sample data** from real-world CORD datasets for evaluation
- **Migrate V3 to V4** with breaking change mappings and flag references

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

## Privacy

The Senzing MCP server works from pre-fetched documentation. It never connects
to live Senzing instances and never handles PII. Data mapping and analysis
scripts run locally on the client.

## License

Proprietary — see [SKILL.md](senzing-entity-resolution/SKILL.md) frontmatter.
