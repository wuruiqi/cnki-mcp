"""
browser.py — 浏览器会话管理

负责：
- 启动/复用一个持久化 Playwright 浏览器上下文
- Cookie 保存与恢复（CNKI 登录状态持久化）
- CNKI 登录状态检测
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Playwright,
)
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

# 默认路径相对项目根目录，便于移植；可用 .env 覆盖为绝对路径
PROFILE_DIR  = os.getenv("PROFILE_DIR",  str(_ROOT / ".browser_profile"))
COOKIE_FILE  = os.getenv("COOKIE_FILE",  str(_ROOT / ".cnki_cookies.json"))

# 模块级单例
_playwright: Optional[Playwright]      = None
_context:    Optional[BrowserContext]  = None
_lock = asyncio.Lock()


async def get_context() -> BrowserContext:
    """获取（或创建）全局浏览器上下文，启动一次后复用。"""
    global _playwright, _context

    async with _lock:
        if _context is not None:
            try:
                # .pages 是属性（非协程），可正常访问即视为上下文有效
                _ = _context.pages
                return _context
            except Exception:
                _context = None

        if _playwright is None:
            _playwright = await async_playwright().start()

        Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)

        # 优先系统 Chrome；失败则用 Playwright 内置 Chromium
        try:
            _context = await _playwright.chromium.launch_persistent_context(
                PROFILE_DIR,
                channel="chrome",
                headless=False,
                accept_downloads=True,
                args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
                locale="zh-CN",
                downloads_path=os.getenv("PDF_DIR", str(_ROOT / "downloads")),
            )
        except Exception:
            _context = await _playwright.chromium.launch_persistent_context(
                PROFILE_DIR,
                headless=False,
                accept_downloads=True,
                locale="zh-CN",
                downloads_path=os.getenv("PDF_DIR", str(_ROOT / "downloads")),
            )

        # 恢复 Cookie
        await load_cookies(_context)

        # 静默忽略弹窗
        _context.on("page", lambda p: p.on("dialog", lambda d: asyncio.ensure_future(d.dismiss())))

        return _context


async def close_context():
    """关闭浏览器（服务器退出时调用）。"""
    global _playwright, _context
    if _context:
        await save_cookies(_context)
        await _context.close()
        _context = None
    if _playwright:
        await _playwright.stop()
        _playwright = None


# ─── Cookie 管理 ────────────────────────────────────────────

async def save_cookies(context: BrowserContext) -> int:
    """保存当前上下文中所有 CNKI 相关 Cookie 到文件。"""
    all_cookies = await context.cookies()
    cnki_cookies = [
        c for c in all_cookies
        if "cnki" in c.get("domain", "").lower()
    ]
    Path(COOKIE_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(cnki_cookies, f, ensure_ascii=False, indent=2)
    return len(cnki_cookies)


async def load_cookies(context: BrowserContext) -> int:
    """从文件恢复 Cookie 到浏览器上下文。"""
    if not Path(COOKIE_FILE).exists():
        return 0
    try:
        with open(COOKIE_FILE, encoding="utf-8") as f:
            cookies = json.load(f)
        if cookies:
            await context.add_cookies(cookies)
        return len(cookies)
    except Exception:
        return 0


# ─── 登录状态检测 ────────────────────────────────────────────

# 未登录时顶部可见的文字标志（2026 实测）。
# 注意：机构登录成功后，"机构登录"会被机构名替换，innerText 中不再出现；
# 而"个人登录"是另一套独立的个人账号登录，机构登录后仍可见 —— 不能作为未登录信号。
_LOGGED_OUT_TEXTS = ["机构登录"]


async def check_login_status() -> dict:
    """
    检查 CNKI 机构登录状态（下载权限来自机构登录）。

    判定逻辑（2026 实测）：
      - 可见文字中出现"机构登录" → 未登录
      - 否则视为已机构登录（登录后该入口被机构名替换）

    返回:
        {"logged_in": bool, "detail": str}
    """
    ctx = await get_context()
    page = await ctx.new_page()
    try:
        await page.goto("https://www.cnki.net", wait_until="domcontentloaded", timeout=20_000)
        await page.wait_for_timeout(2500)

        # innerText 只含可见文字，隐藏的登录弹窗不计入
        try:
            body_text = await page.evaluate("document.body.innerText")
        except Exception:
            body_text = ""

        login_entries = [t for t in _LOGGED_OUT_TEXTS if t in body_text]
        if login_entries:
            return {"logged_in": False, "detail": f"顶部仍有'机构登录'入口，未登录"}

        # 已登录：尝试提取机构名（"机构登录"右侧/替换位置的文字）
        return {"logged_in": True, "detail": "未发现'机构登录'入口，已机构登录"}
    finally:
        await page.close()
