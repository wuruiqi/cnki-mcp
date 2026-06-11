"""
server.py — CNKI MCP 服务器

FastMCP 入口，注册所有 CNKI 工具。
启动命令：
  conda run -n cnki-mcp python server.py
或直接：
  D:\Programs\miniconda3\envs\cnki-mcp\python.exe server.py
"""

import asyncio
import os
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from cnki.browser import check_login_status, get_context, save_cookies, close_context
from cnki.search import search_papers
from cnki.download import download_paper, batch_download
from cnki.zotero import import_papers

mcp = FastMCP("cnki")

PDF_DIR = os.getenv("PDF_DIR", str(Path(__file__).resolve().parent / "downloads"))


# ─────────────────────────────────────────────────────────────
#  1. cnki_login_status — 检查登录状态
# ─────────────────────────────────────────────────────────────

@mcp.tool()
async def cnki_login_status() -> dict:
    """
    检查当前 CNKI 登录状态。

    返回 {"logged_in": bool, "detail": str}。
    若未登录，请调用 cnki_open_login_page 完成机构登录。
    """
    return await check_login_status()


# ─────────────────────────────────────────────────────────────
#  2. cnki_open_login_page — 打开登录页（供用户手动登录）
# ─────────────────────────────────────────────────────────────

@mcp.tool()
async def cnki_open_login_page(wait_seconds: int = 120) -> dict:
    """
    打开 CNKI 机构登录页，等待用户手动完成登录，然后自动保存 Cookie。

    登录流程（手动操作）：
      1. 点击"机构登录"
      2. 点击"校外登录"
      3. 输入学校名称，确定
      4. 输入账号密码，接受条款

    Args:
        wait_seconds: 等待用户完成登录的秒数（默认 120 秒）

    Returns:
        {"opened": bool, "cookies_saved": int, "message": str}
    """
    ctx = await get_context()
    page = await ctx.new_page()
    await page.goto("https://www.cnki.net", wait_until="domcontentloaded", timeout=20_000)
    await page.wait_for_timeout(1500)

    # 尝试自动点击"机构登录"入口
    for sel in ["a:has-text('机构登录')", "a:has-text('登录')", "#loginBtn", ".login-btn"]:
        try:
            if await page.is_visible(sel, timeout=1500):
                await page.click(sel)
                break
        except Exception:
            pass

    # 等待用户操作
    await asyncio.sleep(wait_seconds)

    # 保存 Cookie
    n = await save_cookies(ctx)
    await page.close()

    return {
        "opened": True,
        "cookies_saved": n,
        "message": f"已等待 {wait_seconds} 秒，保存了 {n} 个 CNKI Cookie。如仍未登录请增加等待时间。",
    }


# ─────────────────────────────────────────────────────────────
#  3. cnki_save_cookies — 手动保存当前 Cookie
# ─────────────────────────────────────────────────────────────

@mcp.tool()
async def cnki_save_cookies() -> dict:
    """
    保存当前浏览器上下文中所有 CNKI Cookie 到本地文件。
    下次启动时自动恢复，无需重新登录。

    Returns:
        {"saved": int, "message": str}
    """
    ctx = await get_context()
    n = await save_cookies(ctx)
    return {"saved": n, "message": f"已保存 {n} 个 CNKI Cookie"}


# ─────────────────────────────────────────────────────────────
#  4. cnki_search — 搜索 CNKI 期刊论文
# ─────────────────────────────────────────────────────────────

@mcp.tool()
async def cnki_search(
    query: str,
    year_start: int = 2018,
    year_end: int = 2026,
    max_results: int = 6,
    db_code: str = "CJFD",
) -> dict:
    """
    搜索 CNKI 期刊论文（主题检索）。

    Args:
        query:       检索词，支持空格分隔多词（例如："螺旋推进 散粒体"）
        year_start:  起始年份，默认 2018
        year_end:    结束年份，默认 2026
        max_results: 最多返回论文数，默认 6
        db_code:     数据库代码，CJFD=期刊（默认）/ CDFD=博士论文 / CMFD=硕士论文

    Returns:
        {
          "success": bool,
          "query": str,
          "count": int,
          "papers": [{"title", "authors", "year", "journal", "url"}, ...],
          "message": str
        }
    """
    return await search_papers(
        query=query,
        year_start=year_start,
        year_end=year_end,
        max_results=max_results,
        db_code=db_code,
    )


# ─────────────────────────────────────────────────────────────
#  5. cnki_download_pdf — 下载单篇 PDF/CAJ
# ─────────────────────────────────────────────────────────────

@mcp.tool()
async def cnki_download_pdf(
    detail_url: str,
    title: Optional[str] = None,
) -> dict:
    """
    下载单篇论文的 PDF 或 CAJ 文件。

    Args:
        detail_url: 论文详情页 URL（来自 cnki_search 结果的 url 字段）
        title:      论文标题，用于文件命名（可选）

    Returns:
        {"success": bool, "file_path": str, "format": str, "message": str}
    """
    return await download_paper(detail_url=detail_url, title=title)


# ─────────────────────────────────────────────────────────────
#  6. cnki_import_to_zotero — 将元数据导入 Zotero
# ─────────────────────────────────────────────────────────────

@mcp.tool()
async def cnki_import_to_zotero(papers: List[dict]) -> dict:
    """
    将论文元数据列表导入 Zotero（优先本地 API，失败降级云 API）。

    Args:
        papers: 论文列表，每个对象至少包含：
                {"title": ..., "authors": ..., "year": ..., "journal": ..., "url": ...}
                可选字段 "pdf_path"：本地已下载的 PDF 绝对路径；提供后会通过本地
                Zotero connector 自动上传并关联为子附件（导入 Zotero 存储）。
                （直接使用 cnki_search 返回的 papers 列表即可）

    Returns:
        {"success": bool, "count": int, "attached": int, "method": str, "detail": str}
        method 为 "connector"（本地，含PDF）或 "cloud_api"（降级，仅元数据）
    """
    return await import_papers(papers)


# ─────────────────────────────────────────────────────────────
#  7. cnki_batch — 一键搜索 + 下载 + 导入
# ─────────────────────────────────────────────────────────────

@mcp.tool()
async def cnki_batch(
    query: str,
    year_start: int = 2018,
    year_end: int = 2026,
    max_results: int = 6,
    download_pdf: bool = True,
    import_zotero: bool = True,
    db_code: str = "CJFD",
) -> dict:
    """
    一键完成：搜索 → 可选下载 PDF → 可选导入 Zotero。

    Args:
        query:          检索词（例如："粮仓温度监测 物联网"）
        year_start:     起始年份，默认 2018
        year_end:       结束年份，默认 2026
        max_results:    最多处理论文数，默认 6
        download_pdf:   是否下载 PDF（默认 True）
        import_zotero:  是否导入 Zotero（默认 True）
        db_code:        数据库代码（默认 CJFD=期刊）

    Returns:
        {
          "query": str,
          "search": {...},          # cnki_search 的完整结果
          "download": {...},        # batch_download 的结果（若 download_pdf=True）
          "zotero": {...},          # import_papers 的结果（若 import_zotero=True）
        }
    """
    result: dict = {"query": query}

    # 1. 搜索
    search_result = await search_papers(
        query=query,
        year_start=year_start,
        year_end=year_end,
        max_results=max_results,
        db_code=db_code,
    )
    result["search"] = search_result
    papers = search_result.get("papers", [])

    if not papers:
        result["download"] = {"skipped": True, "reason": "搜索无结果"}
        result["zotero"]   = {"skipped": True, "reason": "搜索无结果"}
        return result

    # 2. 下载 PDF，并把本地路径回填到对应 paper（供 Zotero 关联）
    if download_pdf:
        dl_result = await batch_download(papers)
        result["download"] = dl_result
        for paper, dl in zip(papers, dl_result.get("results", [])):
            if dl.get("success") and dl.get("file_path"):
                paper["pdf_path"] = dl["file_path"]
    else:
        result["download"] = {"skipped": True, "reason": "download_pdf=False"}

    # 3. 导入 Zotero（papers 若带 pdf_path 会自动迁移并关联 PDF）
    if import_zotero:
        z_result = await import_papers(papers)
        result["zotero"] = z_result
    else:
        result["zotero"] = {"skipped": True, "reason": "import_zotero=False"}

    return result


# ─────────────────────────────────────────────────────────────
#  服务器入口
# ─────────────────────────────────────────────────────────────

def main() -> None:
    """控制台入口（pip 安装后 `cnki-mcp` 命令调用）。"""
    import atexit

    def _cleanup():
        try:
            asyncio.get_event_loop().run_until_complete(close_context())
        except Exception:
            pass

    atexit.register(_cleanup)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
