"""
browser.py — 浏览器会话管理

负责：
- 启动/复用一个持久化 Playwright 浏览器上下文
- 跨进程 profile 隔离（flock + 按进程独立 profile，防止多实例互抢导致 Chrome 崩溃）
- 孤儿 Chrome 回收（启动失败时清理残留进程与 Singleton 锁后重试）
- Cookie 保存与恢复（CNKI 登录状态持久化，原子写入）
- CNKI 登录状态检测
"""

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Playwright,
)
from dotenv import load_dotenv

try:
    import fcntl
except ImportError:  # Windows 无 fcntl，始终使用独立 profile
    fcntl = None  # type: ignore[assignment]

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

# 默认路径相对项目根目录，便于移植；可用 .env 覆盖为绝对路径
PROFILE_DIR  = os.getenv("PROFILE_DIR",  str(_ROOT / ".browser_profile"))
COOKIE_FILE  = os.getenv("COOKIE_FILE",  str(_ROOT / ".cnki_cookies.json"))

# 模块级单例
_playwright: Optional[Playwright]      = None
_context:    Optional[BrowserContext]  = None
_lock = asyncio.Lock()

# 跨进程 profile 认领状态（仅在持有 _lock 时读写）
_profile_lock_fd: Optional[int] = None   # flock 文件描述符；None = 未持有
_active_profile:  Optional[Path] = None  # 当前实例实际使用的 profile 目录


# ─── profile 认领（跨进程互斥） ──────────────────────────────

def _pid_alive(pid: int) -> bool:
    """判断进程是否存活（含权限不足但仍存在的情况）。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _cleanup_dead_instances(instances_dir: Path) -> None:
    """清理实例目录中属于已死进程的 profile（pid 作为目录名）。"""
    try:
        children = list(instances_dir.iterdir())
    except OSError:
        return
    for child in children:
        if not child.name.isdigit():
            continue
        pid = int(child.name)
        if pid == os.getpid() or _pid_alive(pid):
            continue
        shutil.rmtree(child, ignore_errors=True)


def _chrome_using_profile(profile: Path) -> bool:
    """检测是否有存活的 Chrome 进程正在使用该 profile。"""
    # 不带前导 "--"：pgrep 把 pattern 当操作数，同时仍能精确子串匹配
    pattern = f"user-data-dir={profile}"
    try:
        proc = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return False
    if proc.returncode != 0:
        return False
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.isdigit() or int(line) == os.getpid():
            continue
        # pgrep 是正则匹配，再用 ps 精确核对参数，避免误杀
        try:
            out = subprocess.run(
                ["ps", "-p", line, "-o", "command="],
                capture_output=True, text=True, timeout=5,
            ).stdout
        except Exception:
            continue
        if f"--user-data-dir={profile}" in out:
            return True
    return False


async def _kill_orphan_chrome(profile: Path) -> int:
    """
    结束使用该 profile 的残留（孤儿）Chrome 进程。

    仅匹配 --user-data-dir 精确等于该自动化 profile 的进程，
    不影响用户日常使用的 Chrome。返回结束的进程数。
    """
    pattern = f"user-data-dir={profile}"
    try:
        proc = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return 0
    if proc.returncode != 0:
        return 0

    killed = 0
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.isdigit() or int(line) == os.getpid():
            continue
        try:
            out = subprocess.run(
                ["ps", "-p", line, "-o", "command="],
                capture_output=True, text=True, timeout=5,
            ).stdout
        except Exception:
            continue
        if f"--user-data-dir={profile}" not in out:
            continue
        try:
            os.kill(int(line), 15)  # SIGTERM，让 Chrome 优雅退出
            killed += 1
        except OSError:
            pass

    if killed:
        for _ in range(20):
            if not _chrome_using_profile(profile):
                break
            await asyncio.sleep(0.25)
        # 仍未退出的强制结束
        if _chrome_using_profile(profile):
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line.isdigit() and int(line) != os.getpid():
                    try:
                        os.kill(int(line), 9)  # SIGKILL
                    except OSError:
                        pass
    return killed


def _remove_singleton_files(profile: Path) -> None:
    """移除陈旧的 Singleton 锁文件（须在确认无存活 Chrome 后调用）。"""
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        p = profile / name
        try:
            p.unlink()
        except OSError:
            pass


def _instance_profile(base: Path) -> Path:
    """返回本进程独立的 profile 目录：<base>.instances/<pid>，并清理死进程遗留。"""
    instances_dir = Path(str(base) + ".instances")
    instances_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_dead_instances(instances_dir)
    profile = instances_dir / str(os.getpid())
    profile.mkdir(parents=True, exist_ok=True)
    return profile


def _claim_profile() -> Path:
    """
    认领要使用的 profile 目录（须在持有 _lock 时调用）。

    策略：
    1. 已认领过 → 复用（同进程重建 context 不重复加锁）。
    2. 对共享 base profile 加非阻塞 flock：
       - 成功且无旧代码实例的 Chrome 占用 → 使用 base（保留既有登录态）。
       - 失败（被其他实例持有）或发现无锁 Chrome 占用（旧版本实例）→ 使用独立实例目录。
    3. 无 fcntl（Windows）→ 始终使用独立实例目录。
    """
    global _profile_lock_fd, _active_profile

    if _active_profile is not None:
        return _active_profile

    base = Path(PROFILE_DIR)
    base.mkdir(parents=True, exist_ok=True)

    if fcntl is None:
        _active_profile = _instance_profile(base)
        return _active_profile

    lock_path = Path(str(base) + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # 被另一实例持有 → 用独立 profile
        os.close(fd)
        _active_profile = _instance_profile(base)
        return _active_profile

    # 持有锁。若发现未持锁的 Chrome 正占用 base（旧版本实例），
    # 说明对方不遵守 flock，让路到独立 profile。
    if _chrome_using_profile(base):
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)
        _active_profile = _instance_profile(base)
        return _active_profile

    _profile_lock_fd = fd
    _active_profile = base
    return base


def _release_profile_lock() -> None:
    """释放跨进程 profile 锁（在 close_context 中调用）。"""
    global _profile_lock_fd, _active_profile
    if _profile_lock_fd is not None and fcntl is not None:
        try:
            fcntl.flock(_profile_lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(_profile_lock_fd)
        except OSError:
            pass
    _profile_lock_fd = None
    _active_profile = None


# ─── 浏览器启动（含孤儿回收重试） ────────────────────────────

async def _launch_persistent(profile: Path) -> BrowserContext:
    """
    在指定 profile 上启动持久化上下文。

    - 优先系统 Chrome（channel="chrome"），失败回退 Playwright 内置 Chromium。
    - 首轮失败后清理孤儿 Chrome 与陈旧 Singleton 锁，再重试一轮
      （修复"上一个实例被强杀后 Chrome 残留 / 锁残留"导致的启动即崩溃）。
    """
    downloads_path = os.getenv("PDF_DIR", str(_ROOT / "downloads"))
    launch_args = ["--disable-blink-features=AutomationControlled", "--no-first-run"]

    async def _try(use_channel: bool) -> BrowserContext:
        assert _playwright is not None
        if use_channel:
            return await _playwright.chromium.launch_persistent_context(
                str(profile),
                channel="chrome",
                headless=False,
                accept_downloads=True,
                args=launch_args,
                locale="zh-CN",
                downloads_path=downloads_path,
            )
        return await _playwright.chromium.launch_persistent_context(
            str(profile),
            headless=False,
            accept_downloads=True,
            args=launch_args,
            locale="zh-CN",
            downloads_path=downloads_path,
        )

    last_error: Optional[Exception] = None
    chrome_error: Optional[Exception] = None

    for attempt in range(2):
        for use_channel in (True, False):  # 系统 Chrome → 内置 Chromium 兜底
            try:
                return await _try(use_channel)
            except Exception as e:
                last_error = e
                if use_channel:
                    chrome_error = e

        if attempt == 0:
            # 首轮失败：疑似孤儿 Chrome / 陈旧锁 → 清理后重试
            killed = await _kill_orphan_chrome(profile)
            if killed:
                _remove_singleton_files(profile)
                await asyncio.sleep(1.0)

    # 内置 Chromium 未安装时报错无意义，优先抛系统 Chrome 的真实错误
    if chrome_error is not None and last_error is not None and (
        "Executable doesn't exist" in str(last_error)
    ):
        raise chrome_error
    raise last_error if last_error is not None else RuntimeError("浏览器启动失败")


# ─── 公共入口 ────────────────────────────────────────────────

async def _discard_dead_context() -> None:
    """丢弃崩溃/断开的死 context。

    不释放 profile 锁：同一进程随后重建时 _claim_profile() 会复用
    _active_profile，继续使用原 profile（保留登录态）。
    """
    global _context
    ctx, _context = _context, None
    if ctx is not None:
        try:
            await asyncio.wait_for(ctx.close(), timeout=5)
        except Exception:
            pass


async def get_context() -> BrowserContext:
    """获取（或创建）全局浏览器上下文，启动一次后复用。"""
    global _playwright, _context

    async with _lock:
        if _context is not None:
            # 真实 IPC 探活：.pages 是本地属性（不发协议消息），
            # Chrome 中途崩溃时死 context 仍"可访问"，必须用会往返浏览器的调用。
            try:
                await asyncio.wait_for(_context.cookies(), timeout=5)
                return _context
            except Exception:
                # 崩溃/断开 → 丢弃死 context，走下方重建
                await _discard_dead_context()

        if _playwright is None:
            _playwright = await async_playwright().start()

        profile = _claim_profile()

        _context = await _launch_persistent(profile)

        # 恢复 Cookie
        await load_cookies(_context)

        # 静默忽略弹窗
        _context.on("page", lambda p: p.on("dialog", lambda d: asyncio.ensure_future(d.dismiss())))

        return _context


async def close_context():
    """关闭浏览器并释放 profile 锁（服务器退出时调用）。"""
    global _playwright, _context
    if _context:
        try:
            await save_cookies(_context)
        except Exception:
            pass
        try:
            await _context.close()
        except Exception:
            pass
        _context = None
    if _playwright:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None
    _release_profile_lock()


# ─── Cookie 管理 ────────────────────────────────────────────

async def save_cookies(context: BrowserContext) -> int:
    """保存当前上下文中所有 CNKI 相关 Cookie 到文件（原子写入，防多实例写坏）。"""
    all_cookies = await context.cookies()
    cnki_cookies = [
        c for c in all_cookies
        if "cnki" in c.get("domain", "").lower()
    ]
    target = Path(COOKIE_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(target) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cnki_cookies, f, ensure_ascii=False, indent=2)
    os.replace(tmp, target)
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
            return {"logged_in": False, "detail": "顶部仍有'机构登录'入口，未登录"}

        # 已登录：尝试提取机构名（"机构登录"右侧/替换位置的文字）
        return {"logged_in": True, "detail": "未发现'机构登录'入口，已机构登录"}
    finally:
        await page.close()
