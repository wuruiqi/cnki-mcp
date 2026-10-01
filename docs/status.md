# Project Status

## Current Version: v0.2.1

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

### v0.2.1 (2026-10-01)
- **Download chain rewritten** — CNKI's download button is `<a id="pdfDown" target="_blank" href="https://bar.cnki.net/bar/download/order?id=...">`: it opens a new tab, the landing page then navigates to the real file at `https://docdown.cnki.net/docdown/fulltext/download?q=...`, and CNKI's script calls `window.close()` once the download starts. Because a Playwright persistent context exits as soon as its last page closes, the in-browser download was always aborted (`Timeout waiting for event "download"`, then `Download.save_as: Target page, context or browser has been closed`, leaving only `.crdownload` files).
  - New approach: **the browser only resolves the signed URL; the bytes are fetched by `httpx`.**
  - `cnki/download.py`: added `_snapshot_cookie_header()` (snapshots cookies *before* clicking; skips non-ASCII values such as `last_org`, which would make `httpx` raise `UnicodeEncodeError`) and `_http_fetch()` (`trust_env=False` to bypass proxies, follows redirects, validates the `%PDF` magic).
  - The signed `docdown` URL is **single-use** — if the browser actually requests it the token is consumed and `httpx` only receives an HTML error page. So `_do_download()` now intercepts it with `ctx.route(re.compile(r"docdown\.cnki\.net"))` and calls `route.abort()`, keeping the token for `httpx`. A `download`-event fallback is kept.
  - `download_paper()` / `search_papers()`: `page.close()` wrapped in try/except (CNKI often closes the browser mid-flight).
- **Login status detection fixed** — `cnki_login_status()` previously only looked for the "机构登录" entry on the `www.cnki.net` homepage, which **falsely reported logged-out for CARSI / FSSO off-campus logins** (the org name replaces the entry on `kns.cnki.net`, but the `www` homepage still keeps it).
  - Now multi-signal: (1) session cookies `_shibsession_*` / `Ecp_session` / `SID_fsso` / `TDC_itoken`; (2) `/verify/home` redirect detection → reports `captcha: true` (bot-check, not a login problem); (3) absence of the "机构登录" entry. Also returns `org` (read from the `last_org` cookie).
- **Browser context hardening** — `cnki/browser.py`: `_clear_singleton_locks()` removes stale `SingletonLock`/`SingletonCookie`/`SingletonSocket` before launch; downloads are staged in `.downloads_tmp/` instead of the output directory.
- **Zero-result detection** — `cnki/search.py`: distinguishes "reached the result page but zero hits" (`no_result`) from "failed to load" (`fail`).
- Verified on a real batch: 36 Chinese CNKI PDFs (234.7 MB) downloaded successfully.

## Roadmap

| Version | Plan |
|---------|------|
| v0.3.0 | Pagination support (fetch >20 results per sort pass); configurable page-size |
| v0.3.0 | `cnki_preview_metadata_updates` can read PDFs from Zotero storage directly (add `ZOTERO_DATA_DIR` config) |
| v0.3.0 | Thesis database support (CDFD/CMFD) with separate sort parameters |
