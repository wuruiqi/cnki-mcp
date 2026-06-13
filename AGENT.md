# cnki-mcp — Agent Overview

MCP server wrapping CNKI (China National Knowledge Infrastructure) literature search, PDF download, and Zotero import as callable tools.
Compatible with Claude Code, Codex, OpenClaw, Cursor, and any stdio MCP client.

## Architecture

```
cnki-mcp/
├── server.py          # FastMCP entry point; all @mcp.tool() definitions (9 tools)
├── cnki/
│   ├── browser.py     # Browser session management (Playwright async, cookie persistence)
│   ├── search.py      # CNKI search: form interaction, multi-sort, dedup utilities
│   ├── download.py    # PDF/CAJ download (click #pdfDown / #cajDown → download event)
│   ├── zotero.py      # Zotero import (local connector port 23119 + cloud API fallback)
│   │                  #   also: existing-title query, item search, item PATCH update
│   └── pdf_meta.py    # PDF metadata extraction via PyMuPDF (fitz)
├── tests/             # Unit tests + diagnostic scripts (inspect_* / probe_*)
├── pyproject.toml     # Entry-point: cnki-mcp → server:main
└── .env.example       # Config template
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `cnki_login_status` | Check current CNKI institution login state |
| `cnki_open_login_page` | Open login page for manual institution login |
| `cnki_save_cookies` | Save cookies after login (auto-restored next session) |
| `cnki_search` | Search CNKI journal articles by keyword (relevance order) |
| `cnki_download_pdf` | Download a single PDF/CAJ |
| `cnki_import_to_zotero` | Import metadata list into Zotero |
| `cnki_batch` | Batch: multi-sort search → dedup → download → Zotero import |
| `cnki_preview_metadata_updates` | Extract PDF metadata and generate diff table vs current data |
| `cnki_apply_metadata_updates` | Apply user-confirmed diffs to Zotero items (cloud API PATCH) |

### cnki_batch — Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `top_n_by_time` | 50 | Take top-N papers sorted by publication time (0 = disable) |
| `top_n_by_citations` | 50 | Take top-N papers sorted by citation count (0 = disable) |
| `check_zotero_dup` | True | Skip papers already present in Zotero library |
| `download_pdf` | True | Download PDFs |
| `import_zotero` | True | Import to Zotero |
| `download_interval_min` | 6.0 | Minimum seconds between downloads (anti-rate-limit) |
| `download_interval_max` | 12.0 | Maximum seconds between downloads (randomized) |
| `captcha_wait` | 120 | Seconds to wait for user to solve CAPTCHA; 0 = skip |

When both sort modes are active, the two lists are merged and deduplicated by title before proceeding.

### cnki_download_pdf — Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `detail_url` | — | Paper detail page URL (from `cnki_search` result) |
| `title` | None | Paper title for filename (optional) |
| `captcha_wait` | 120 | Seconds to wait for user to solve CAPTCHA; 0 = skip |

### cnki_apply_metadata_updates — Update Format

```json
[
  {
    "title": "existing Zotero title (used for lookup)",
    "fields": {
      "title":   "corrected title",
      "authors": "Author1; Author2",
      "journal": "corrected journal",
      "doi":     "10.xxxx/yyyy"
    }
  }
]
```

Requires `ZOTERO_API_KEY` and `ZOTERO_LIB_ID` in `.env`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ZOTERO_LOCAL_API` | `http://127.0.0.1:23119` | Zotero local connector address |
| `ZOTERO_API_KEY` | — | Zotero Web API key (cloud fallback + metadata updates) |
| `ZOTERO_LIB_ID` | — | Numeric Zotero library/user ID |
| `COOKIE_FILE` | `.cnki_cookies.json` | Cookie persistence path |
| `PDF_DIR` | `./downloads` | PDF temporary storage |
| `PROFILE_DIR` | `./.browser_profile` | Browser persistent profile |
| `DELETE_PDF_AFTER_IMPORT` | `true` | Delete temp PDF after successful Zotero import |

Set `DELETE_PDF_AFTER_IMPORT=false` when you want to run `cnki_preview_metadata_updates` after import.

## Dependencies

`mcp[cli]>=1.27.0`, `playwright>=1.44.0`, `httpx>=0.27.0`, `pydantic>=2.0.0`, `python-dotenv>=1.0.0`, `pymupdf>=1.24.0`

Python **3.10+** required.

## First-time Setup

```bash
pip install -e .
playwright install chromium
cp .env.example .env    # fill in ZOTERO_API_KEY and ZOTERO_LIB_ID
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
  "mcpServers": {
    "cnki": {
      "type": "stdio",
      "command": "python",
      "args": ["D:/path/to/cnki-mcp/server.py"]
    }
  }
}
```

## Typical Workflow

```
cnki_login_status          → check if logged in
cnki_open_login_page       → manual institution login (if needed)
cnki_batch "螺旋推进 散粒体"  → search + sort + dedup + download + Zotero import
                             result contains metadata_preview if PDF diffs found
cnki_preview_metadata_updates  → review diff table (if PDFs still on disk)
cnki_apply_metadata_updates    → apply confirmed corrections to Zotero
```

## Known Limitations

- CNKI shows ~20 results per page; `top_n > 20` gets fewer results until pagination support is added.
- PDF auto-attachment to Zotero requires Zotero desktop running (local connector). Falls back to cloud API (metadata only) when Zotero is closed.
- `cnki_apply_metadata_updates` requires cloud API credentials (`ZOTERO_API_KEY` + `ZOTERO_LIB_ID`).
- CNKI search is limited to journal articles (best-effort); thesis results may appear.
- PyMuPDF title extraction accuracy depends on PDF quality; scanned-only PDFs may return empty title.
- CNKI CAPTCHA: browser window must remain visible (`headless=False`). When CAPTCHA appears the download pauses and prints a prompt — solve the slider verification in the browser window to continue.
