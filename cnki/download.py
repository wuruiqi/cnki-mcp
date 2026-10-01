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


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


async def _snapshot_cookie_header(ctx) -> str:
    """把浏览器上下文的 Cookie 快照成可独立复用的 Cookie 头。

    必须在点击下载【之前】调用 —— CNKI 会在下载启动后关闭页面，
    届时整个浏览器上下文可能已销毁，再读 cookie 就来不及了。
    非 ASCII 值（如 last_org 里的中文）直接跳过，避免 HTTP 客户端编码报错。
    """
    try:
        cookies = await ctx.cookies()
    except Exception:
        return ""
    parts = []
    for c in cookies:
        v = c.get("value", "")
        try:
            v.encode("ascii")
        except UnicodeEncodeError:
            continue
        parts.append(f'{c.get("name")}={v}')
    return "; ".join(parts)


async def _http_fetch(url: str, cookie_header: str, referer: str):
    """用独立 HTTP 客户端下载文件，返回 (bytes|None, err|None)。"""
    headers = {
        "User-Agent": _UA,
        "Referer": referer,
        "Accept": "application/pdf,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if cookie_header:
        headers["Cookie"] = cookie_header
    try:
        import httpx  # 延迟导入，避免成为硬依赖
    except ImportError:
        return None, "未安装 httpx（pip install httpx 后重试）"
    try:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=True,
                                     timeout=120, verify=False, headers=headers) as cli:
            resp = await cli.get(url)
            if resp.status_code == 200 and resp.content[:4] == b"%PDF":
                return resp.content, None
            snippet = resp.text[:160].replace("\n", " ") if resp.content else ""
            return None, (f"HTTP {resp.status_code}, magic={resp.content[:8]!r}, "
                          f"final={str(resp.url)[:90]}, body={snippet!r}")
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


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

    # ⚠️ CNKI 下载的真实链路（2026-10-01 实测）：
    #   点击 a#pdfDown（<a target="_blank" href="bar.cnki.net/bar/download/order?id=...">）
    #   → 新标签页落地页 → 真实文件 https://docdown.cnki.net/docdown/fulltext/download?q=...
    #   → 会话结束前 CNKI 脚本会 window.close() 掉页面；
    #     Playwright 的持久化上下文一旦最后一个页面关闭就【整个浏览器进程退出】，
    #     下载被腰斩，磁盘只剩 .crdownload 半成品。
    # ⇒ 浏览器**只负责点出签名 URL**，文件字节交给独立 HTTP 客户端取（不受浏览器退出影响）。
    ctx = page.context
    cookie_header = await _snapshot_cookie_header(ctx)

    captured: Dict = {"url": None, "dl": None}

    # ★ 关键：把浏览器对 docdown.cnki.net 的请求【拦下并中止】。
    # 该签名 URL 是【一次性】的 —— 若让浏览器真的发出去，令牌就被消耗，
    # 我们再拿同一个 URL 去 httpx 取，只会得到一张 HTML 错误页。
    async def _route_handler(route):
        req = route.request
        if "docdown.cnki.net" in req.url:
            if not captured["url"]:
                captured["url"] = req.url
            try:
                await route.abort()
            except Exception:
                pass
        else:
            try:
                await route.continue_()
            except Exception:
                pass

    def _on_download(dl):
        captured["dl"] = dl
        if not captured["url"]:
            captured["url"] = dl.url

    _route_pat = re.compile(r"docdown\.cnki\.net")
    _routed = False
    try:
        await ctx.route(_route_pat, _route_handler)
        _routed = True
    except Exception:
        pass
    ctx.on("download", _on_download)
    try:
        await btn.click()
    except Exception:  # noqa: BLE001
        # 点击后页面可能被站点立刻关闭，属预期行为
        pass

    waited = 0
    while not captured["url"] and waited < min(timeout_ms, 30_000):
        await asyncio.sleep(0.2)
        waited += 200

    try:
        page.remove_listener("download", _on_download)
        ctx.remove_listener("download", _on_download)
    except Exception:
        pass
    if _routed:
        try:
            await ctx.unroute(_route_pat, _route_handler)
        except Exception:
            pass

    err = ""
    # ── 主路径：独立 HTTP 取文件 ──
    if captured["url"]:
        data, err = await _http_fetch(captured["url"], cookie_header, detail_url)
        if data:
            save_path.write_bytes(data)
            return {
                "success": True, "captcha": False,
                "file_path": str(save_path), "file_name": save_path.name,
                "format": fmt,
                "message": f"已保存至 {save_path}（{len(data)} bytes）",
            }
    else:
        err = f"未捕获到下载 URL（{timeout_ms}ms 内）"

    # ── 兜底：download 对象若还活着，试一次 save_as ──
    dl = captured.get("dl")
    if dl is not None:
        try:
            await dl.save_as(str(save_path))
            if save_path.exists() and save_path.stat().st_size > 0:
                return {
                    "success": True, "captcha": False,
                    "file_path": str(save_path), "file_name": save_path.name,
                    "format": fmt,
                    "message": f"已保存至 {save_path}（download 事件兜底）",
                }
        except Exception as e:  # noqa: BLE001
            err = f"{err} / download 兜底亦失败: {e}"

    is_captcha = False
    try:
        is_captcha = await _detect_captcha(page)
    except Exception:
        pass
    return {
        "success": False, "captcha": is_captcha,
        "file_path": "", "file_name": "", "format": fmt,
        "message": f"下载失败{'（验证码）' if is_captcha else ''}: {err}",
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
        # CNKI 下载后常会关掉页面、甚至整个浏览器；此时 close() 会抛 TargetClosedError，
        # 属正常现象，吞掉即可（不该影响已拿到的结果）。
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass


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
