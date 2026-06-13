# cnki-mcp — Agent Overview

MCP server wrapping CNKI (China National Knowledge Infrastructure) literature search, PDF download, and Zotero import as callable tools.
Compatible with Claude Code, Codex, OpenClaw, Cursor, and any stdio MCP client.

## Architecture

```
cnki-mcp/
├── server.py          # FastMCP entry point; all @mcp.tool() definitions
├── cnki/
│   ├── browser.py     # Browser session management (Playwright async, cookie persistence)
│   ├── search.py      # CNKI search (form interaction: fill #txt_search, click .search-btn)
│   ├── download.py    # PDF/CAJ download (click #pdfDown / #cajDown → download event)
│   └── zotero.py      # Zotero import (local connector port 23119 + cloud API fallback)
├── tests/             # Unit tests + diagnostic scripts (inspect_* / probe_*)
├── pyproject.toml     # Entry-point: cnki-mcp → server:main
└── .env.example       # Config template
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `cnki_login_status` | Check current login state |
| `cnki_open_login_page` | Open login page for manual institution login |
| `cnki_save_cookies` | Save cookies after login (auto-restored next session) |
| `cnki_search` | Search CNKI journal articles by keyword |
| `cnki_download_pdf` | Download a single PDF |
| `cnki_batch` | Batch search + download + import to Zotero |
| `cnki_import_to_zotero` | Import metadata list into Zotero |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ZOTERO_API_KEY` | — | Zotero Web API key (cloud fallback) |
| `ZOTERO_LIBRARY_ID` | — | Numeric library ID |
| `ZOTERO_LIBRARY_TYPE` | `user` | `user` or `group` |
| `COOKIE_FILE` | `.cnki_cookies.json` | Cookie persistence path |
| `PDF_DIR` | `./downloads` | PDF temporary storage |
| `DELETE_PDF_AFTER_IMPORT` | `true` | Delete temp PDF after successful Zotero import |

## Dependencies

`mcp[cli]>=1.27.0`, `playwright>=1.44.0`, `httpx>=0.27.0`, `pydantic>=2.0.0`, `python-dotenv>=1.0.0`

Python 3.10+ required.

## First-time Setup

```bash
pip install -e .
playwright install chromium
cp .env.example .env    # fill in ZOTERO_API_KEY and ZOTERO_LIBRARY_ID

# Create _local/ directory for dev notes
mkdir _local
```

Create `_local/status.md` with the template from this file's "Developer Status Template" section:

```markdown
## Current Version: vX.Y.Z
## Last Doc Review: YYYY-MM-DD
## Recently Completed
## In Progress
## Next Steps
## Known Issues
## Docs to Update
```

## Register in MCP Client

```json
{
  "mcpServers": {
    "cnki": {
      "type": "stdio",
      "command": "cnki-mcp"
    }
  }
}
```

Or from source:
```json
{
  "cnki": {
    "type": "stdio",
    "command": "python",
    "args": ["D:/path/to/cnki-mcp/server.py"]
  }
}
```

## Known Limitations

- PDF auto-attachment to Zotero requires the Zotero desktop app running (local connector). When Zotero is closed, falls back to cloud API (metadata only, no PDF).
- CNKI search is limited to journal articles (best-effort); thesis results may appear.
- Playwright browser must be installed separately (`playwright install chromium`).
