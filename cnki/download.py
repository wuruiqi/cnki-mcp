"""
download.py — CNKI 论文 PDF / CAJ 下载

策略：
1. 打开论文详情页
2. 检测页面是否有验证码（下载前 + 点击后）
3. 若有验证码且 captcha_wait > 0：在浏览器中等待用户手动完成，超时后跳过
4. 点击 PDF 或 CAJ 下载按钮，监听下载事件
5. 将文件保存到 PDF_DIR

批量下载采用随机化间隔（默认 6-12 秒），降低触发 CNKI 风控的概率。
"""

import os
import re
import asyncio
import random
from pathlib import Path
from typing import Optional, Dict, Tuple

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

# 验证码/人机验证的 DOM 选择器（CNKI 常用的阿里云盾 / 自研滑块）
_CAPTCHA_SELECTORS = [
    "#nc_1_wrapper",          # 阿里云盾 NVC 滑块
    ".nc-container",
    ".verify-wrap",
    ".verify-bar-area",
    ".slidercaptcha",
    "#captchaBox",
    ".captcha-box",
    "iframe[src*='captcha']",
]

# 验证码页面常见文字
_CAPTCHA_TEXT_MARKERS = [
    "请拖动滑块",
    "请完成安全验证",
    "人机验证",
    "滑动完成拼图",
    "异常访问",
    "访问频次较高",
    "请输入验证码",
]


def _safe_filename(title: str, suffix: str = ".pdf") -> str:
    """将论文标题转换为安全文件名（去除特殊字符）。"""
    name = re.sub(r'[\\/:*?"<>|]', "_", title)
    name = name.strip().rstrip(".")
    if len(name) > 120:
        name = name[:120]
    return name + suffix


# ─── 验证码检测与处理 ────────────────────────────────────────

async def _detect_captcha(page) -> bool:
    """检测当前页面是否出现了 CNKI 验证码/人机验证。"""
    # URL 特征
    try:
        url = page.url.lower()
        if any(k in url for k in ("captcha", "verify", "/403", "robot")):
            return True
    except Exception:
        pass

    # DOM 选择器
    for sel in _CAPTCHA_SELECTORS:
        try:
            if await page.locator(sel).count() > 0:
                return True
        except Exception:
            pass

    # 页面文字
    try:
        text = await page.evaluate("document.body.innerText") or ""
        if any(kw in text for kw in _CAPTCHA_TEXT_MARKERS):
            return True
    except Exception:
        pass

    return False


async def _wait_for_captcha(page, wait_seconds: int = 120) -> bool:
    """
    检测到验证码后，在控制台提示用户，轮询等待直至验证码消失。

    浏览器窗口（headless=False）保持打开，用户直接在浏览器中完成滑块/图形验证。

    Returns:
        True  — 验证码已消失，可继续下载
        False — 等待超时，验证码仍在
    """
    print(f"\n{'='*60}")
    print("[CAPTCHA] CNKI 人机验证 — 请在浏览器窗口中手动完成验证！")
    print(f"          等待上限：{wait_seconds} 秒")
    print(f"{'='*60}")

    for elapsed in range(0, wait_seconds, 3):
        await asyncio.sleep(3)
        still_captcha = await _detect_captcha(page)
        if not still_captcha:
            print("[CAPTCHA] 验证完成，恢复下载。\n")
            await asyncio.sleep(1)  # 额外缓冲，让服务端确认验证状态
            return True
        remaining = wait_seconds - elapsed - 3
        if remaining > 0 and remaining % 15 == 0:
            print(f"[CAPTCHA] 等待中… 剩余约 {remaining} 秒")

    print(f"[CAPTCHA] 等待超时（{wait_seconds} 秒），跳过当前文件。\n")
    return False


# ─── 下载按钮查找 ────────────────────────────────────────────

async def _find_download_btn(page) -> Tuple[Optional[object], str]:
    """
    在页面上查找下载按钮，返回 (element, format_str)。
    format_str 为 'pdf' 或 'caj'。
    """
    for sel in _DL_BUTTON_SELECTORS:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                text = await el.text_content() or ""
                fmt = "caj" if ("caj" in sel.lower() or "CAJ" in text) else "pdf"
                return el, fmt
        except Exception:
            pass
    return None, "pdf"


# ─── 核心下载（单次尝试） ────────────────────────────────────

async def _do_download(page, detail_url: str, title: Optional[str], timeout_ms: int) -> Dict:
    """
    在已打开的 page 上完成一次完整的下载尝试（导航→找按钮→点击→等待下载事件）。
    不关闭 page（由调用方管理）。
    """
    Path(PDF_DIR).mkdir(parents=True, exist_ok=True)

    if not detail_url.startswith("http"):
        detail_url = f"https://kns.cnki.net{detail_url}"

    await page.goto(detail_url, wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_timeout(3000)

    # 导航后先检测验证码
    if await _detect_captcha(page):
        return {
            "success": False, "captcha": True,
            "file_path": "", "file_name": "", "format": "",
            "message": "页面有验证码（导航后），请手动处理",
        }

    btn, fmt = await _find_download_btn(page)
    if btn is None:
        snippet = (await page.evaluate("document.body.innerText") or "")[:200].replace("\n", " ")
        return {
            "success": False, "captcha": False,
            "file_path": "", "file_name": "", "format": "",
            "message": f"未找到下载按钮。页面片段: {snippet!r}",
        }

    safe_name = _safe_filename(title or f"paper_{hash(detail_url) % 100_000}", f".{fmt}")
    save_path = Path(PDF_DIR) / safe_name

    try:
        async with page.expect_download(timeout=timeout_ms) as dl_info:
            await btn.click()
        download = await dl_info.value
        await download.save_as(str(save_path))

        if not save_path.exists():
            alt = Path(PDF_DIR) / (download.suggested_filename or safe_name)
            await download.save_as(str(alt))
            save_path = alt

        return {
            "success": True, "captcha": False,
            "file_path": str(save_path),
            "file_name": save_path.name,
            "format": fmt,
            "message": f"已保存至 {save_path}",
        }

    except Exception as e:
        # 点击后检测验证码
        is_captcha = await _detect_captcha(page)
        return {
            "success": False, "captcha": is_captcha,
            "file_path": "", "file_name": "", "format": fmt,
            "message": f"下载失败{'（验证码）' if is_captcha else ''}: {e}",
        }


# ─── 公共接口 ────────────────────────────────────────────────

async def download_paper(
    detail_url: str,
    title: Optional[str] = None,
    timeout_ms: int = 60_000,
    captcha_wait: int = 120,
) -> Dict:
    """
    下载一篇论文的 PDF 或 CAJ 文件。

    验证码处理策略：
    - 若下载过程中（导航后或点击按钮后）检测到人机验证，
      自动暂停并在控制台提示用户在浏览器窗口中手动完成验证。
    - 验证通过后自动重新导航并重试一次。
    - captcha_wait=0 可关闭等待，直接返回失败。

    Args:
        detail_url:   论文详情页 URL
        title:        论文标题（用于文件命名）
        timeout_ms:   下载等待超时（毫秒）
        captcha_wait: 验证码等待上限（秒），0 = 不等待直接跳过

    Returns:
        {
          "success": bool,
          "captcha": bool,      # 是否触发了验证码
          "file_path": str,
          "file_name": str,
          "format": str,        # "pdf" 或 "caj"
          "message": str,
        }
    """
    ctx = await get_context()
    page = await ctx.new_page()
    try:
        result = await _do_download(page, detail_url, title, timeout_ms)

        # 触发了验证码 → 等待用户处理 → 重试一次
        if result.get("captcha") and captcha_wait > 0:
            solved = await _wait_for_captcha(page, captcha_wait)
            if solved:
                result = await _do_download(page, detail_url, title, timeout_ms)
                if not result["success"]:
                    result["message"] = "验证通过后重试: " + result["message"]

        return result

    except Exception as e:
        return {
            "success": False, "captcha": False,
            "file_path": "", "file_name": "", "format": "",
            "message": f"下载失败: {e}",
        }
    finally:
        await page.close()


async def batch_download(
    papers: list,
    timeout_ms: int = 60_000,
    min_delay: float = 6.0,
    max_delay: float = 12.0,
    captcha_wait: int = 120,
) -> Dict:
    """
    批量下载论文列表（顺序下载，随机化间隔，内置验证码等待）。

    Args:
        papers:       [{"title": ..., "url": ...}, ...] 列表
        timeout_ms:   每篇下载超时（毫秒）
        min_delay:    两篇之间最小间隔秒数（默认 6 秒）
        max_delay:    两篇之间最大间隔秒数（默认 12 秒）
        captcha_wait: 检测到验证码时最长等待秒数（默认 120 秒，0 = 跳过）

    Returns:
        {"success_count": int, "fail_count": int, "captcha_count": int, "results": [...]}
    """
    results = []
    for i, p in enumerate(papers):
        result = await download_paper(
            detail_url=p.get("url") or p.get("href", ""),
            title=p.get("title"),
            timeout_ms=timeout_ms,
            captcha_wait=captcha_wait,
        )
        result["title"] = p.get("title", "")
        results.append(result)

        if i < len(papers) - 1:
            # 验证码后额外加长间隔，给服务端充分冷却时间
            if result.get("captcha"):
                delay = max_delay * 2
            else:
                delay = random.uniform(min_delay, max_delay)
            await asyncio.sleep(delay)

    success    = [r for r in results if r["success"]]
    captcha_ct = sum(1 for r in results if r.get("captcha"))
    return {
        "success_count": len(success),
        "fail_count":    len(results) - len(success),
        "captcha_count": captcha_ct,
        "results":       results,
    }
