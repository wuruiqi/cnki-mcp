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


async def _context_alive(ctx: BrowserContext) -> bool:
    """探测上下文是否真正存活。

    仅访问 `.pages` 属性不可靠：上下文/浏览器已关闭时该属性仍可读取，
    不抛异常（这会导致后续 new_page 报 "context has been closed"）。
    用 `ctx.browser` 的连接态 + 一次轻量的 new_page/close 真实探测。
    """
    try:
        browser = ctx.browser
        if browser is not None and not browser.is_connected():
            return False
        # 真实探测：能开/关一个空白页才算活
        probe = await ctx.new_page()
        await probe.close()
        return True
    except Exception:
        return False


def _clear_singleton_locks() -> None:
    """清理 Chrome 持久化 profile 的单例锁。

    浏览器被强制结束（例如 CNKI 在下载后关掉页面、或进程被 kill）后，
    profile 里常残留 SingletonLock/Cookie/Socket，导致下次 launch 直接失败或挂起。
    """
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = Path(PROFILE_DIR) / name
        try:
            if p.is_symlink() or p.exists():
                p.unlink()
        except Exception:
            pass


async def _launch_context() -> BrowserContext:
    """启动一个持久化浏览器上下文（优先系统 Chrome，失败回退内置 Chromium）。

    ignore_https_errors=True：CNKI 海外入口 www.cnki.net 经腾讯 EdgeOne CDN
    回源，对 SNI=www.cnki.net 误发 *.cdn.myqcloud.com 证书（仅 SNI=oversea.cnki.net
    才返回正确的 *.cnki.net 证书），导致 ERR_CERT_COMMON_NAME_INVALID。
    本工具仅做检索抓取，放行证书校验以容忍 CDN 证书错配 / 本地代理 MITM。
    同时附带 --ignore-certificate-errors 抑制 Chrome 渠道的拦截页。
    """
    assert _playwright is not None
    _clear_singleton_locks()
    # 注意：downloads_path 只是个【临时中转】目录 —— 真实落盘由 download.py 里的
    # httpx 独立请求完成。若直接指向 PDF_DIR，CNKI 关闭浏览器时会留下
    # 一堆 .crdownload 半成品污染成果目录。
    tmp_dl = str(Path(PROFILE_DIR).parent / ".downloads_tmp")
    Path(tmp_dl).mkdir(parents=True, exist_ok=True)
    try:
        return await _playwright.chromium.launch_persistent_context(
            PROFILE_DIR,
            channel="chrome",
            headless=False,
            accept_downloads=True,
            ignore_https_errors=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--ignore-certificate-errors",
            ],
            locale="zh-CN",
            downloads_path=tmp_dl,
        )
    except Exception:
        return await _playwright.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            accept_downloads=True,
            ignore_https_errors=True,
            args=["--ignore-certificate-errors"],
            locale="zh-CN",
            downloads_path=tmp_dl,
        )


async def get_context() -> BrowserContext:
    """获取（或创建）全局浏览器上下文，启动一次后复用；失效则自动重建。"""
    global _playwright, _context

    async with _lock:
        if _context is not None:
            if await _context_alive(_context):
                return _context
            # 旧上下文已死，清理后重建
            try:
                await _context.close()
            except Exception:
                pass
            _context = None

        if _playwright is None:
            _playwright = await async_playwright().start()

        Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)

        _context = await _launch_context()

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

# 机构会话 Cookie 标志（2026-10-01 实测）。
# CARSI / FSSO 校外访问登录后会写入 `_shibsession_*`（Shibboleth 会话）等；
# 只靠首页有没有「机构登录」入口判定，会把这类登录**误判为未登录**。
_CARSI_COOKIE_PREFIX = "_shibsession_"
_SESSION_COOKIE_NAMES = ("Ecp_session", "SID_fsso", "TDC_itoken")
_ORG_COOKIE_NAME = "last_org"          # 值为机构名，如「河南工业大学」

_VERIFY_MARKERS = ("/verify/home", "captcha", "verify")


async def _cookie_login_signals(ctx) -> dict:
    """从 Cookie 里提取机构登录信号（不访问页面，快）。"""
    try:
        cookies = await ctx.cookies()
    except Exception:
        return {"hit": False, "names": [], "org": ""}
    names = [c.get("name", "") for c in cookies]
    carsi = [n for n in names if n.startswith(_CARSI_COOKIE_PREFIX)]
    markers = [n for n in _SESSION_COOKIE_NAMES if n in names]
    org = ""
    for c in cookies:
        if c.get("name") == _ORG_COOKIE_NAME and c.get("value"):
            org = c["value"]
            break
    return {"hit": bool(carsi or markers), "names": carsi + markers, "org": org}


async def check_login_status() -> dict:
    """
    检查 CNKI 机构登录状态（下载权限来自机构登录）。

    多信号判定（2026-10-01 修订）：
      1) **Cookie**：出现 `_shibsession_*`（CARSI / Shibboleth 校外访问）、
         `Ecp_session`、`SID_fsso`、`TDC_itoken` 之一 → 判定有机构会话。
      2) **页面**：访问 `kns.cnki.net` 检索页，若被 302 到 `/verify/home`
         → 是被**人机验证风控**拦截（与"登没登录"是两回事，需人工过验证）。
      3) **可见文字**：不再出现「机构登录」→ 已登录（登录后该入口被机构名替换）。

    ⚠️ 原实现只看 `www.cnki.net` 首页有没有「机构登录」入口，
    对 CARSI / FSSO 这种校外访问登录会**误报未登录**
    （实测：`last_org` 已是「河南工业大学」、`_shibsession_*` 已写入，
    但 www 首页顶部仍保留「机构登录」入口）。

    返回:
        {"logged_in": bool, "detail": str, "org": str, "captcha": bool}
        （org / captcha 为 2026-10-01 新增字段，向后兼容）
    """
    ctx = await get_context()
    sig = await _cookie_login_signals(ctx)
    org = sig["org"]

    page = await ctx.new_page()
    try:
        goto_err = ""
        try:
            await page.goto("https://kns.cnki.net/kns8s/defaultresult/index",
                            wait_until="domcontentloaded", timeout=25_000)
        except Exception as e:  # noqa: BLE001
            goto_err = f"{type(e).__name__}: {e}"
        await asyncio.sleep(2.0)

        try:
            cur = page.url or ""
        except Exception:
            cur = ""
        if any(m in cur.lower() for m in _VERIFY_MARKERS):
            return {
                "logged_in": False, "captcha": True, "org": org,
                "detail": "被 CNKI 人机验证拦截（302 → /verify/home），请先人工过验证",
            }

        try:
            body = await page.evaluate("document.body.innerText") or ""
        except Exception:
            body = ""

        login_entry = any(t in body for t in _LOGGED_OUT_TEXTS)

        # ① Cookie 强信号优先
        if sig["hit"]:
            parts = [f"机构会话 Cookie 命中：{', '.join(sig['names'][:4])}"]
            if org:
                parts.append(f"机构 {org}")
            if login_entry:
                parts.append("页面仍有「机构登录」入口（CARSI 登录常态，不影响下载）")
            return {"logged_in": True, "captcha": False, "org": org,
                    "detail": "；".join(parts)}

        # ② 无 Cookie 信号，再看页面
        if login_entry:
            return {"logged_in": False, "captcha": False, "org": org,
                    "detail": "顶部仍有'机构登录'入口，且无机构会话 Cookie，未登录"}

        if goto_err:
            return {"logged_in": False, "captcha": False, "org": org,
                    "detail": f"页面无法访问且无会话 Cookie：{goto_err}"}

        return {"logged_in": True, "captcha": False, "org": org,
                "detail": "页面无「机构登录」入口，已机构登录"}
    finally:
        try:
            await page.close()
        except Exception:
            pass
