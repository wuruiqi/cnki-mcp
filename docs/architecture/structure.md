# Project Structure

```
cnki-mcp/
├── server.py          # FastMCP entry point; all @mcp.tool() definitions
├── cnki/
│   ├── __init__.py
│   ├── browser.py     # Browser session (Playwright async, cookie persistence)
│   ├── search.py      # CNKI search via form interaction
│   ├── download.py    # PDF/CAJ download via browser download event
│   └── zotero.py      # Zotero import: local connector + cloud API fallback
├── tests/
│   ├── test_unit.py           # Unit tests
│   ├── inspect_*.py           # DOM inspection scripts (search/form/row/detail/page)
│   └── probe_*.py             # Zotero connector probing scripts
├── pyproject.toml
├── AGENT.md
└── docs/
```

## Core File Responsibilities

| File | Responsibility |
|------|----------------|
| `server.py` | MCP tool definitions; delegates to cnki/ modules |
| `cnki/browser.py` | Launch/close Playwright browser; persist cookies to COOKIE_FILE |
| `cnki/search.py` | Navigate to kns.cnki.net, fill form, parse result rows |
| `cnki/download.py` | Locate and click download button; capture download event |
| `cnki/zotero.py` | POST to local connector (saveItems + saveAttachment); fallback to web API |

## Module Dependencies

```
server.py
  ├── cnki/browser.py   (session lifecycle)
  ├── cnki/search.py    (depends on browser.py)
  ├── cnki/download.py  (depends on browser.py)
  └── cnki/zotero.py    (independent; uses httpx)
```
