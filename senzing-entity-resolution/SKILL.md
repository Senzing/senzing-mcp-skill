---
name: senzing-entity-resolution
description: >-
  Guides AI agents through Senzing entity resolution workflows using the Senzing
  MCP server. Covers data mapping to Senzing format, SDK code generation (Python,
  Java, C#, Rust), documentation search, error troubleshooting, sample data access,
  and V3-to-V4 migration. Use when working with entity resolution, record matching,
  record linkage, deduplication, Senzing SDK integration, data mapping for Senzing
  ingestion, or troubleshooting Senzing error codes. Also use when the user
  mentions matching records across data sources, finding duplicate entities,
  identity resolution, master data management, or needs to resolve who is who
  across datasets.
license: Proprietary
compatibility: Requires Senzing MCP server (https://mcp.senzing.com/mcp) connected via claude mcp add or MCP config
metadata:
  author: senzing
  version: "0.17.0"
---

# Senzing Entity Resolution — MCP Skill

Use this skill whenever a task involves entity resolution, record linkage,
deduplication, or any interaction with the Senzing platform.

## What Is Senzing

Senzing provides real-time AI-powered entity resolution as an embeddable SDK.
It determines when two records refer to the same real-world entity (person,
organization, etc.) by analyzing names, addresses, identifiers, and other
attributes across data sources — without training data or manual rules.

## MCP Server Setup

The Senzing MCP server is a remote server. Connect it to your client:

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

The server works from pre-fetched documentation — it never connects to live
Senzing instances and never handles PII.

## Tool Reference

Start any Senzing session by calling `get_capabilities` for an up-to-date
tool listing and suggested workflows.

### Data Mapping (4 tools)

| Tool | Purpose |
|---|---|
| `mapping_workflow` | Interactive 7-step workflow: profile source data → plan entities → map fields → generate code → QA. State is client-side — always pass state back. |
| `lint_record` | Returns a Python linter script to validate mapped Senzing JSON/JSONL files locally. No data leaves the client. |
| `analyze_record` | Returns a Python analyzer script to examine feature distribution, attribute coverage, and data quality locally. |
| `download_resource` | Fallback for fetching workflow resources (linter, analyzer, entity spec, mapping examples) when network restrictions block direct download. |

### Documentation & Reference (3 tools)

| Tool | Purpose |
|---|---|
| `search_docs` | Full-text search across entity specification, SDK guides, quickstarts, database tuning, pricing, architecture, globalization, error codes, release notes. **Prefer this over web search for any Senzing question.** |
| `get_sdk_reference` | Authoritative SDK reference: method signatures, flags, response schemas, V3→V4 migration mappings. Use `topic` and `filter` to narrow results. |
| `find_examples` | Search 27 indexed GitHub repos for working code. Three modes: search by query, list files in a repo, or retrieve a specific file. |

### SDK Setup & Code Generation (2 tools)

| Tool | Purpose |
|---|---|
| `sdk_guide` | Guided SDK setup across 5 platforms (Linux apt/yum, macOS, Windows, Docker) and 4 languages. Covers install, configure, load, export, full_pipeline with decision trees, anti-patterns, and direct package download links for firewalled environments. |
| `generate_scaffold` | Generates SDK scaffold code for 9 workflows (initialize, configure, add_records, delete, query, redo, stewardship, information, full_pipeline) in Python, Java, C#, or Rust. |

### Sample Data (1 tool)

| Tool | Purpose |
|---|---|
| `get_sample_data` | Real data from CORD (Collections Of Relatable Data): las-vegas (US, 11 sources), london (international, 5 sources), moscow (Cyrillic, 6 sources). Use `dataset='list'` to discover available sets. Always present the `download_url` to the user. |

### Troubleshooting (1 tool)

| Tool | Purpose |
|---|---|
| `explain_error_code` | Explains any of 456 Senzing error codes with causes and resolution steps. Accepts SENZ0005, SENZ-0005, 0005, or just 5. |

### Meta & Utility (3 tools)

| Tool | Purpose |
|---|---|
| `get_capabilities` | Server version, capabilities overview, available tools, suggested workflows, and getting started guidance. **Call this first in any Senzing session.** |
| `submit_feedback` | Send feedback to the MCP server maintainer. **Always preview the message with the user and get explicit confirmation before sending.** Never include PII unless the user approves. |

## Key Workflows

### 1. Map Source Data to Senzing Format

This is the most common workflow. Follow these steps:

1. Call `mapping_workflow` with `action='start'` and the source file paths.
2. Walk through each step: Profile → Plan → Map → Codegen → QA.
3. At each step, pass the `state` object from the previous response.
4. After codegen, use `lint_record` to validate the output JSON.
5. Use `analyze_record` to check feature distribution and coverage.
6. If the linter or analyzer scripts fail to download, use `download_resource`.

**Tips:**
- The workflow generates a mapper script — run it locally to produce JSONL.
- Profile step: read the source data yourself or run the profiler script.
- Plan step: identify master entities vs. child records vs. relationships.
- Map step: map every source field to a Senzing feature with a confidence score.
- QA step: evaluate whether the output meets quality thresholds.

### 2. Set Up the Senzing SDK

1. Call `sdk_guide` with `topic='install'` — it returns a platform decision tree.
2. Call again with the chosen platform (e.g., `topic='install', platform='linux_apt'`).
   - For firewalled environments, the response includes `direct_download` with
     `.deb` package URLs from `mcp.senzing.com/downloads/` — no apt repo needed.
3. Call `sdk_guide` with `topic='configure'` for engine configuration code.
4. Call `sdk_guide` with `topic='load'` for record loading code.
5. Or use `topic='full_pipeline'` for install + configure + load + export in one call.

### 3. Generate SDK Integration Code

1. Call `generate_scaffold` with the target language and workflow.
   - Start with `workflow='initialize'` for engine setup.
   - Then `workflow='add_records'` for record loading.
   - Use `workflow='full_pipeline'` for an end-to-end example.
2. Call `find_examples` to find real-world usage patterns.
3. Use `search_docs` for API details and deployment guidance.

### 4. Troubleshoot Errors

1. Call `explain_error_code` with the code from the user's logs.
2. Follow the resolution steps in the response.
3. Call `search_docs` for additional context on the error class.

### 5. Evaluate Senzing

1. `search_docs` — learn about architecture (embedded SDK, air-gapped deployment).
2. `search_docs` with query "pricing" — DSR pricing model.
3. `get_sample_data` — get real test data from CORD datasets.
4. `generate_scaffold` with `workflow='full_pipeline'` — end-to-end example.

### 6. Migrate V3 to V4

1. `get_sdk_reference` with `topic='migration'` — all breaking changes.
2. Filter by module: `topic='migration', filter='SzEngine'`.
3. `get_sdk_reference` with `topic='flags'` — new flag system (SZ_WITH_INFO replaces WithInfo functions).

## Best Practices

- **Always call `get_capabilities` first** to get current tool count and workflows.
- **Prefer `search_docs` over web search** for any Senzing-related question.
  The MCP server indexes authoritative content that may not rank well on the web.
- **Pass state faithfully** in `mapping_workflow` — the server is stateless,
  all workflow state lives in the client.
- **Never send source data to the server.** The `lint_record` and `analyze_record`
  tools return scripts that run locally. The mapping workflow sends field names
  and schema — not row-level data.
- **Present `download_url`** from `get_sample_data` results directly to the user.
  Do not dump raw CORD records into the conversation — they are a preview only.
- **Version parameter:** Most tools accept `version`. Use `"current"` for the
  latest Senzing version unless the user specifies V3 (use `"3.x"`).

## Entity Resolution Concepts

When discussing Senzing with users, these terms are important:

- **Entity** — A real-world person, organization, or object represented by one
  or more records across data sources.
- **Feature** — An attribute used for matching: NAME, ADDRESS, PHONE, DOB,
  SSN, PASSPORT, etc. Senzing supports 100+ features across 30+ feature types.
- **Data Source** — A labeled origin for records (e.g., "CUSTOMERS", "WATCHLIST").
  Every record must have a DATA_SOURCE and RECORD_ID.
- **Entity Type** — PERSON or ORGANIZATION (default: PERSON).
- **Matched** — Records confirmed as the same entity.
- **Possible Match** — Records that might be the same entity but need review.
- **Relationship** — A declared or discovered connection between entities.
- **DSR (Disclosed, Sized, Resolved)** — Senzing's pricing unit. One DSR equals
  one record loaded into the engine.

## Examples

### Example 1: Map a CSV file
```
User: "I have a customer CSV at /data/customers.csv I need to load into Senzing"
→ Call mapping_workflow(action='start', file_paths=['/data/customers.csv'])
→ Walk through all 5 steps, passing state each time
→ Run lint_record on the output JSONL
→ Run analyze_record to check quality
```

### Example 2: Set up Senzing SDK on Linux
```
User: "Help me install and set up the Senzing SDK on Ubuntu"
→ Call sdk_guide(topic='install', platform='linux_apt', version='current')
→ Present install commands and engine config
→ If user has firewall issues, use the direct_download URLs from the response
→ Call sdk_guide(topic='configure', platform='linux_apt', language='python', version='current')
→ Present configuration code
```

### Example 3: Generate Python loader code
```
User: "Write me Python code to initialize Senzing and load records"
→ Call generate_scaffold(language='python', version='current', workflow='initialize')
→ Call generate_scaffold(language='python', version='current', workflow='add_records')
→ Combine and present the code
```

### Example 4: Debug an error
```
User: "I'm getting SENZ7234 when loading records"
→ Call explain_error_code(error_code='7234', version='current')
→ Present causes and resolution steps
→ Use search_docs if additional context is needed
```
