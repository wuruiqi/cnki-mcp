"""
server.py — CNKI MCP 服务器

FastMCP 入口，注册所有 CNKI 工具。
启动命令：
  python server.py
（pip 安装后亦可直接用 `cnki-mcp` 命令启动）
"""

import asyncio
import os
import re
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from cnki.browser import check_login_status, get_context, save_cookies, close_context
from cnki.search import search_papers, search_multi_sort
from cnki.download import download_paper, batch_download
from cnki.zotero import (
    import_papers,
    get_existing_titles,
    filter_new_papers,
    find_zotero_item_by_title,
    update_zotero_item,
)
from cnki.pdf_meta import extract_pdf_metadata, compare_metadata

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
    搜索 CNKI 期刊论文（主题检索，按相关度）。

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
          "papers": [{"title", "authors", "year", "journal", "citations", "url"}, ...],
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
    captcha_wait: int = 120,
) -> dict:
    """
    下载单篇论文的 PDF 或 CAJ 文件。

    触发 CNKI 人机验证时，浏览器窗口保持打开，控制台打印提示，
    等待用户在浏览器中手动完成验证后自动重试。

    Args:
        detail_url:   论文详情页 URL（来自 cnki_search 结果的 url 字段）
        title:        论文标题，用于文件命名（可选）
        captcha_wait: 等待用户完成验证码的最长秒数，默认 120；0 = 不等待直接跳过

    Returns:
        {"success": bool, "captcha": bool, "file_path": str, "format": str, "message": str}
    """
    return await download_paper(detail_url=detail_url, title=title, captcha_wait=captcha_wait)


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
#  7. cnki_batch — 一键搜索 + 排序 + 去重 + 下载 + 导入
# ─────────────────────────────────────────────────────────────

@mcp.tool()
async def cnki_batch(
    query: str,
    year_start: int = 2018,
    year_end: int = 2026,
    top_n_by_time: int = 50,
    top_n_by_citations: int = 50,
    download_pdf: bool = True,
    import_zotero: bool = True,
    check_zotero_dup: bool = True,
    db_code: str = "CJFD",
    download_interval_min: float = 6.0,
    download_interval_max: float = 12.0,
    captcha_wait: int = 120,
) -> dict:
    """
    一键完成：搜索 → 多排序 → 去重 → 可选下载 PDF → 可选导入 Zotero。

    排序策略：
      - 分别按「发表时间」和「引用量」排序，各取前 N 篇，合并去重后得到工作集。
      - top_n_by_time=0 则跳过时间排序；top_n_by_citations=0 则跳过引用排序。
      - 两者均为 0 时退化为按相关度取前 50 篇。

    去重策略：
      1. 两种排序结果之间按标题去重（内部合并）。
      2. 若 check_zotero_dup=True，与 Zotero 已有文献对比，跳过已存在的条目。

    下载风控策略：
      - 两篇之间随机等待 download_interval_min～download_interval_max 秒（默认 6-12 秒）。
      - 触发 CNKI 人机验证时，自动暂停并在控制台提示用户在浏览器中手动完成验证，
        等待最多 captcha_wait 秒后自动重试当前文件。
      - 验证后额外延长等待（= download_interval_max × 2），保证服务端冷却。

    元数据预览（仅当 download_pdf=True 时触发）：
      下载 PDF 后自动提取 PDF 元数据，与 CNKI 搜索元数据比对；
      存在差异时将差异写入结果 metadata_preview 字段，
      可调用 cnki_apply_metadata_updates 确认后更新 Zotero 条目。

    Args:
        query:                  检索词（例如："粮仓温度监测 物联网"）
        year_start:             起始年份，默认 2018
        year_end:               结束年份，默认 2026
        top_n_by_time:          按发表时间取前 N 篇，默认 50（0 = 禁用）
        top_n_by_citations:     按引用量取前 N 篇，默认 50（0 = 禁用）
        download_pdf:           是否下载 PDF，默认 True
        import_zotero:          是否导入 Zotero，默认 True
        check_zotero_dup:       是否跳过 Zotero 中已有文献，默认 True
        db_code:                数据库代码（默认 CJFD=期刊）
        download_interval_min:  两篇之间最小间隔秒数，默认 6.0
        download_interval_max:  两篇之间最大间隔秒数，默认 12.0
        captcha_wait:           验证码等待上限秒数，默认 120；0 = 不等待直接跳过

    Returns:
        {
          "query": str,
          "search": {...},           # search_multi_sort 完整结果
          "zotero_dedup": {...},     # 与 Zotero 去重统计（若启用）
          "download": {...},         # batch_download 结果（若启用）
          "metadata_preview": [...], # PDF 与 CNKI 元数据差异列表（若有差异）
          "metadata_note": str,      # 提示用户调用更新工具的说明（若有差异）
          "zotero": {...},           # import_papers 结果（若启用）
        }
    """
    result: dict = {"query": query}

    # 1. 搜索（带多排序 + 内部去重）
    search_result = await search_multi_sort(
        query=query,
        year_start=year_start,
        year_end=year_end,
        top_n_by_time=top_n_by_time,
        top_n_by_citations=top_n_by_citations,
        db_code=db_code,
    )
    result["search"] = search_result
    papers = search_result.get("papers", [])

    if not papers:
        result["message"] = "搜索无结果"
        return result

    # 2. 与 Zotero 已有文献去重
    if check_zotero_dup:
        existing = await get_existing_titles()
        dedup_info = filter_new_papers(papers, existing)
        papers = dedup_info["new"]
        result["zotero_dedup"] = {
            "before": dedup_info["removed"] + len(papers),
            "after": len(papers),
            "removed": dedup_info["removed"],
            "skipped_titles": dedup_info["skipped"],
        }
        if not papers:
            result["message"] = "搜索到的论文已全部在 Zotero 库中，无新增文献"
            return result

    # 3. 下载 PDF
    if download_pdf:
        dl_result = await batch_download(
            papers,
            min_delay=download_interval_min,
            max_delay=download_interval_max,
            captcha_wait=captcha_wait,
        )
        result["download"] = dl_result
        for paper, dl in zip(papers, dl_result.get("results", [])):
            if dl.get("success") and dl.get("file_path"):
                paper["pdf_path"] = dl["file_path"]
    else:
        result["download"] = {"skipped": True, "reason": "download_pdf=False"}

    # 4. 提取 PDF 元数据，生成对比预览
    metadata_preview = []
    for paper in papers:
        if paper.get("pdf_path") and Path(paper["pdf_path"]).exists():
            pdf_meta = extract_pdf_metadata(paper["pdf_path"])
            diffs = compare_metadata(paper, pdf_meta)
            if diffs:
                metadata_preview.append({
                    "title":    paper.get("title", ""),
                    "url":      paper.get("url", ""),
                    "pdf_path": paper.get("pdf_path", ""),
                    "diffs":    diffs,
                })

    if metadata_preview:
        result["metadata_preview"] = metadata_preview
        result["metadata_note"] = (
            f"发现 {len(metadata_preview)} 篇论文的 PDF 元数据与 CNKI 搜索元数据存在差异，"
            "可调用 cnki_apply_metadata_updates 选择性更新 Zotero 条目。"
        )

    # 5. 导入 Zotero
    if import_zotero:
        z_result = await import_papers(papers)
        result["zotero"] = z_result
    else:
        result["zotero"] = {"skipped": True, "reason": "import_zotero=False"}

    return result


# ─────────────────────────────────────────────────────────────
#  8. cnki_preview_metadata_updates — 提取并对比 PDF 元数据
# ─────────────────────────────────────────────────────────────

@mcp.tool()
async def cnki_preview_metadata_updates(
    papers: List[dict],
) -> dict:
    """
    对指定论文列表提取 PDF 元数据，与 CNKI 搜索元数据比对，返回差异对比表。

    通常配合 cnki_batch 使用：将 cnki_batch 返回结果中的 metadata_preview
    或带有 pdf_path 字段的 papers 列表传入此工具，即可获得完整对比表。

    若 PDF 已被删除（DELETE_PDF_AFTER_IMPORT=true 时默认删除），
    请将 DELETE_PDF_AFTER_IMPORT 设为 false 后重新执行批量操作，
    或直接使用 cnki_batch 结果中自动生成的 metadata_preview。

    Args:
        papers: 论文列表，每项须包含 "pdf_path"（本地 PDF 路径），
                以及当前元数据字段（"title"、"authors"、"journal"、"doi"、"url"）。

    Returns:
        {
          "success": bool,
          "comparisons": [
            {
              "title":   str,          # 当前 Zotero/CNKI 标题
              "url":     str,          # CNKI 链接（用于 apply 时定位条目）
              "pdf_path": str,
              "diffs": {
                "title":   {"current": ..., "from_pdf": ...},  # 仅含有差异的字段
                "authors": {...},
                "journal": {...},
                "doi":     {...},
              }
            }, ...
          ],
          "no_diff_count": int,        # 元数据一致的篇数
          "message": str,
        }
    """
    if not papers:
        return {"success": False, "comparisons": [], "no_diff_count": 0,
                "message": "未传入论文列表"}

    comparisons = []
    no_diff = 0

    for paper in papers:
        pdf_path = paper.get("pdf_path", "")
        if not pdf_path or not Path(pdf_path).exists():
            continue
        pdf_meta = extract_pdf_metadata(pdf_path)
        diffs = compare_metadata(paper, pdf_meta)
        if diffs:
            comparisons.append({
                "title":    paper.get("title", ""),
                "url":      paper.get("url", ""),
                "pdf_path": pdf_path,
                "diffs":    diffs,
            })
        else:
            no_diff += 1

    if not comparisons and no_diff == 0:
        return {"success": False, "comparisons": [], "no_diff_count": 0,
                "message": "没有找到可读取的 PDF 文件（路径不存在或未传入 pdf_path）"}

    return {
        "success": True,
        "comparisons": comparisons,
        "no_diff_count": no_diff,
        "message": (
            f"共检查 {len(comparisons) + no_diff} 篇，"
            f"发现 {len(comparisons)} 篇存在元数据差异，"
            f"{no_diff} 篇元数据一致。"
            + ("" if comparisons else "")
        ),
    }


# ─────────────────────────────────────────────────────────────
#  9. cnki_apply_metadata_updates — 将确认的差异更新到 Zotero
# ─────────────────────────────────────────────────────────────

@mcp.tool()
async def cnki_apply_metadata_updates(
    updates: List[dict],
) -> dict:
    """
    将用户确认的元数据差异应用到 Zotero 对应条目。

    每条 update 包含「定位信息」（title 或 url，用于在 Zotero 中查找条目）
    以及「待更新字段」，工具会通过 Zotero 云 API 执行 PATCH 更新。

    ⚠ 此操作不可撤销，请在 cnki_preview_metadata_updates 确认差异后再调用。
    ⚠ 需要在 .env 中配置 ZOTERO_API_KEY 和 ZOTERO_LIB_ID。

    Args:
        updates: 列表，每项格式：
            {
              "title":   str,          # 用于在 Zotero 中定位条目（与 CNKI 原始标题一致）
              "url":     str,          # （可选）CNKI 链接，辅助定位
              "fields":  {             # 要更新的字段（只填需要修改的项）
                "title":   str,        # 修正后的标题
                "authors": str,        # 修正后的作者（分号分隔）
                "journal": str,        # 修正后的期刊名
                "doi":     str,        # 补充的 DOI
              }
            }

    Returns:
        {
          "success_count": int,
          "fail_count": int,
          "results": [{"title": str, "success": bool, "detail": str}, ...]
        }
    """
    if not updates:
        return {"success_count": 0, "fail_count": 0, "results": [],
                "message": "未传入更新列表"}

    results = []

    for upd in updates:
        title  = upd.get("title", "")
        fields = upd.get("fields", {})

        if not title or not fields:
            results.append({"title": title, "success": False,
                            "detail": "缺少 title 或 fields 字段，已跳过"})
            continue

        # 在 Zotero 中查找条目
        item = await find_zotero_item_by_title(title)
        if not item:
            results.append({"title": title, "success": False,
                            "detail": "在 Zotero 中未找到匹配条目（需配置 ZOTERO_API_KEY / ZOTERO_LIB_ID）"})
            continue

        item_key = item.get("key", "")
        version  = item.get("version", 0)

        # 转换字段格式
        zotero_fields: dict = {}
        if "title" in fields:
            zotero_fields["title"] = fields["title"]
        if "journal" in fields:
            zotero_fields["publicationTitle"] = fields["journal"]
        if "doi" in fields:
            zotero_fields["DOI"] = fields["doi"]
        if "authors" in fields:
            creators = []
            for name in fields["authors"].split(";"):
                name = name.strip()
                if name:
                    creators.append({"creatorType": "author", "firstName": "", "lastName": name})
            zotero_fields["creators"] = creators

        if not zotero_fields:
            results.append({"title": title, "success": False,
                            "detail": "fields 中无可识别的字段（支持: title/authors/journal/doi）"})
            continue

        res = await update_zotero_item(item_key, version, zotero_fields)
        results.append({"title": title, "success": res["success"], "detail": res["detail"]})

    ok  = sum(1 for r in results if r["success"])
    bad = len(results) - ok

    return {
        "success_count": ok,
        "fail_count": bad,
        "results": results,
        "message": f"更新完成：成功 {ok} 条，失败 {bad} 条",
    }


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
