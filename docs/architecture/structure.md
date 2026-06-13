# Project Structure

```
cnki-mcp/
├── server.py          # FastMCP entry point; all 9 @mcp.tool() definitions
├── cnki/
│   ��── __init__.py
│   ├── browser.py     # Browser session (Playwright async, cookie persistence)
│   ├── search.py      # CNKI search via form interaction; multi-sort; dedup helpers
│   ├── download.py    # PDF/CAJ download via browser download event
│   ├── zotero.py      # Zotero: local connector import + cloud API fallback
│   │                  #   query existing titles, find/patch items (cloud API)
│   └── pdf_meta.py    # PDF metadata extraction via PyMuPDF (fitz)
├── tests/
│   ├── test_unit.py           # Unit tests (19 cases, offline)
│   ├── inspect_*.py           # DOM inspection scripts (search/form/row/detail/page)
│   └── probe_*.py             # Zotero connector probing scripts
├── docs/
│   ├── status.md              # Public project status & roadmap
│   └── architecture/
��       └── structure.md       # This file
├── _local/                    # Internal dev notes (not committed)
│   ├── status.md              # Current session dev status
│   ├── dev-log.md             # Chronological changelog
│   └── bugs.md                # Known issues & fixes
├── pyproject.toml
├── requirements.txt
├── AGENT.md                   # Public MCP architecture & tool reference
├── CLAUDE.md                  # Internal dev notes (2026 gotchas, diagnostics)
└── .env.example               # Config template
```

## Core File Responsibilities

| File | Responsibility |
|------|----------------|
| `server.py` | MCP tool definitions; orchestrates cnki/ modules |
| `cnki/browser.py` | Launch/close Playwright browser; persist CNKI cookies |
| `cnki/search.py` | Navigate kns.cnki.net, fill form, parse rows; sort/dedup helpers |
| `cnki/download.py` | Locate and click download button; capture download event |
| `cnki/zotero.py` | POST to local connector (`saveItems` + `saveAttachment`); cloud API fallback; query/patch items |
| `cnki/pdf_meta.py` | Open PDF with fitz; read info dict + font-size title extraction + DOI regex |

## Module Dependencies

```
server.py
  ├── cnki/browser.py     (session lifecycle)
  ├── cnki/search.py      (depends on browser.py)
  ├── cnki/download.py    (depends on browser.py)
  ├── cnki/zotero.py      (independent; uses httpx)
  └── cnki/pdf_meta.py    (independent; uses fitz/pymupdf)
```

## Key Data Flow — cnki_batch

```
search_multi_sort()
  ├── _try_navigate_search()      → open results page
  ├── _click_sort("citations")    → CNKI UI sort, extract top_n_by_citations
  ├── _click_sort("time")         → CNKI UI sort, extract top_n_by_time
  └── _dedup_by_title()           → merged list

get_existing_titles()             → Zotero local/cloud API
filter_new_papers()               → remove already-imported papers

batch_download()                  → sequential PDF download

extract_pdf_metadata() ×N        → PyMuPDF: info dict + font-size title + DOI
compare_metadata()    ×N         → diff vs CNKI search metadata
                                 → metadata_preview in result

import_papers()                  → local connector saveItems + saveAttachment
                                 → cloud API fallback
```

## Sort Strategy

CNKI result pages support UI-level sort (citation count, publication date).
`_click_sort()` tries known selectors (e.g. `a:has-text('被引量')`).
If no button is found, client-side fallback sorts by the `citations`/`year` fields already extracted from the result rows.

## Deduplication Strategy

1. **Internal**: `_dedup_by_title()` normalises titles (strip whitespace + lowercase) and returns the union of two sorted lists with no duplicates.
2. **Zotero**: `get_existing_titles()` queries the Zotero library (local API → cloud API fallback); `filter_new_papers()` removes matching entries.
