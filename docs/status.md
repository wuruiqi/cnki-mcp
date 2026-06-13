# Project Status

## Current Version: v0.2.0

## Delivered Features

### v0.1.0 (2026-06-13)
- `cnki_login_status` — check CNKI institution login state
- `cnki_open_login_page` — open login page for manual institution login, auto-save cookies
- `cnki_save_cookies` — persist cookies to disk
- `cnki_search` — search CNKI journal articles by keyword (relevance order, with citation count)
- `cnki_download_pdf` — download a single PDF/CAJ
- `cnki_import_to_zotero` — import metadata list into Zotero (local connector + cloud API fallback)
- `cnki_batch` — one-click: search → download → Zotero import

### v0.2.0 (2026-06-13)
- **Multi-sort search** (`cnki_batch`): separate top-N by publication time and citation count; results merged and deduplicated by title
- **Two-level deduplication**: (1) internal merge of two sorted lists; (2) skip papers already in Zotero library (`check_zotero_dup`)
- **Citation count** extracted from CNKI result rows (`td.quote`), stored in each paper object
- **PDF metadata extraction** via PyMuPDF (fitz): reads PDF info dict + font-size-aware title extraction + DOI regex from page text
- **`cnki_preview_metadata_updates`**: extract PDF metadata and return structured diff table
- **`cnki_apply_metadata_updates`**: PATCH confirmed diffs to Zotero via cloud API (requires `ZOTERO_API_KEY` + `ZOTERO_LIB_ID`)
- **CAPTCHA handling**: randomized download interval (6–12 s); auto-pauses on CAPTCHA detection, waits up to 120 s for user to solve slider in browser, then auto-retries
- New helper modules: `cnki/pdf_meta.py`
- New helper functions in `cnki/zotero.py`: `get_existing_titles`, `filter_new_papers`, `find_zotero_item_by_title`, `update_zotero_item`
- Unit test coverage: 19 tests (up from 9)

## Roadmap

| Version | Plan |
|---------|------|
| v0.3.0 | Pagination support (fetch >20 results per sort pass); configurable page-size |
| v0.3.0 | `cnki_preview_metadata_updates` can read PDFs from Zotero storage directly (add `ZOTERO_DATA_DIR` config) |
| v0.3.0 | Thesis database support (CDFD/CMFD) with separate sort parameters |
