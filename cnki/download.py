"""
download.py — CNKI 论文 PDF / CAJ 下载

策略：
1. 打开论文详情页
2. 点击 PDF 或 CAJ 下载按钮，监听下载事件
3. 将文件保存到 PDF_DIR
"""

import os
import re
import asyncio
from pathlib import Path
from typing import Optional, Dict

from .browser import get_context

PDF_DIR = os.getenv("PDF_DIR", str(Path(__file__).resolve().parent.parent / "downloads"))

# 下载按钮选择器（按优先级，2026 实测确认 #pdfDown / #cajDown 可用）
_DL_BUTTON_SELECTORS = [
    "a#pdfDown",            # PDF下载（首选）
    "li.btn-dlpdf a",
    "a#cajDown",            # CAJ下载（兜底）
    "li.btn-dlcaj a",
    "a:has-text('PDF下载')",
    "a:has-text('CAJ下载')",
    "a[href*='bar.cnki.net/bar/download']",
]


def _safe_filename(title: str, suffix: str = ".pdf") -> str:
    """将论文标题转换为安全文件名（去除特殊字符）。"""
    name = re.sub(r'[\\/:*?"<>|]', "_", title)
    name = name.strip().rstrip(".")
    if len(name) > 120:
        name = name[:120]
    return name + suffix


async def download_paper(
    detail_url: str,
    title: Optional[str] = None,
    timeout_ms: int = 60_000,
) -> Dict:
    """
    下载一篇论文的 PDF 或 CAJ 文件。

    Args:
        detail_url: 论文详情页 URL（kns.cnki.net/...）
        title:      论文标题，用于文件命名（可选，为空时用 URL hash 命名）
        timeout_ms: 下载等待超时（毫秒）

    Returns:
        {
          "success": bool,
          "file_path": str,     # 保存路径（成功时）
          "file_name": str,     # 文件名
          "format": str,        # "pdf" 或 "caj"
          "message": str,
        }
    """
    Path(PDF_DIR).mkdir(parents=True, exist_ok=True)
    ctx = await get_context()
    page = await ctx.new_page()

    try:
        # 修正相对 URL
        if not detail_url.startswith("http"):
            detail_url = f"https://kns.cnki.net{detail_url}"

        await page.goto(detail_url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3000)

        # 找下载按钮
        btn = None
        fmt = "pdf"
        for sel in _DL_BUTTON_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    btn = el
                    fmt = "caj" if "caj" in sel.lower() or "CAJ" in (await el.text_content() or "") else "pdf"
                    break
            except Exception:
                pass

        if btn is None:
            page_text = await page.evaluate("document.body.innerText")
            snippet = page_text[:300].replace("\n", " ")
            return {
                "success": False,
                "file_path": "",
                "file_name": "",
                "format": "",
                "message": f"未找到下载按钮。页面文本片段: {snippet!r}",
            }

        # 等待下载事件
        safe_name = _safe_filename(title or f"paper_{hash(detail_url) % 100000}", f".{fmt}")
        save_path = Path(PDF_DIR) / safe_name

        async with page.expect_download(timeout=timeout_ms) as dl_info:
            await btn.click()

        download = await dl_info.value
        await download.save_as(str(save_path))

        if not save_path.exists():
            # 有些下载会用 suggested filename
            alt = Path(PDF_DIR) / (download.suggested_filename or safe_name)
            await download.save_as(str(alt))
            save_path = alt

        return {
            "success": True,
            "file_path": str(save_path),
            "file_name": save_path.name,
            "format": fmt,
            "message": f"已保存至 {save_path}",
        }

    except Exception as e:
        return {
            "success": False,
            "file_path": "",
            "file_name": "",
            "format": "",
            "message": f"下载失败: {e}",
        }
    finally:
        await page.close()


async def batch_download(papers: list, timeout_ms: int = 60_000) -> Dict:
    """
    批量下载论文列表（顺序下载，避免并发触发 CNKI 风控）。

    Args:
        papers: [{"title": ..., "url": ...}, ...] 列表
        timeout_ms: 每篇超时

    Returns:
        {"success_count": int, "fail_count": int, "results": [...]}
    """
    results = []
    for p in papers:
        result = await download_paper(
            detail_url=p.get("url") or p.get("href", ""),
            title=p.get("title"),
            timeout_ms=timeout_ms,
        )
        result["title"] = p.get("title", "")
        results.append(result)
        # 每篇间隔 2 秒，降低风控触发概率
        await asyncio.sleep(2)

    success = [r for r in results if r["success"]]
    return {
        "success_count": len(success),
        "fail_count": len(results) - len(success),
        "results": results,
    }
