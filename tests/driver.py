"""
交互式测试驱动 —— 直接调用底层 async 函数，与 MCP 工具同一套代码路径。

用法:
  python tests/driver.py status        # 检查登录状态
  python tests/driver.py login [秒]    # 打开登录页等待手动登录（默认 150 秒）
  python tests/driver.py search "关键词"
  python tests/driver.py download "<url>" "<标题>"
  python tests/driver.py batch "关键词"
"""
import asyncio
import io
import json
import os
import sys

# 强制 UTF-8 输出，避免 Windows 控制台中文乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cnki.browser import check_login_status, get_context, save_cookies, close_context
from cnki.search import search_papers
from cnki.download import download_paper
from cnki.zotero import import_papers


def show(label, obj):
    print("\n===== {} =====".format(label))
    print(json.dumps(obj, ensure_ascii=False, indent=2))


async def cmd_status():
    show("登录状态", await check_login_status())


async def cmd_login(seconds):
    ctx = await get_context()
    page = await ctx.new_page()
    await page.goto("https://www.cnki.net", wait_until="domcontentloaded", timeout=20000)
    print("浏览器已打开 CNKI 首页。请手动完成机构登录（{} 秒内）...".format(seconds))
    print("流程: 机构登录 → 校外登录 → 输入学校 → 账号密码 → 接受条款")
    await asyncio.sleep(seconds)
    n = await save_cookies(ctx)
    await page.close()
    print("已保存 {} 个 CNKI Cookie".format(n))
    show("登录后状态", await check_login_status())


async def cmd_search(query):
    show("搜索结果", await search_papers(query=query, max_results=3))


async def cmd_download(url, title):
    show("下载结果", await download_paper(detail_url=url, title=title))


async def cmd_batch(query):
    r = await search_papers(query=query, max_results=2)
    show("batch-搜索", r)
    papers = r.get("papers", [])
    if papers:
        dl = await download_paper(detail_url=papers[0]["url"], title=papers[0]["title"])
        show("batch-下载首篇", dl)
        if dl.get("success") and dl.get("file_path"):
            papers[0]["pdf_path"] = dl["file_path"]
        z = await import_papers(papers)
        show("batch-导入Zotero", z)


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    op = sys.argv[1]
    try:
        if op == "status":
            await cmd_status()
        elif op == "login":
            secs = int(sys.argv[2]) if len(sys.argv) > 2 else 150
            await cmd_login(secs)
        elif op == "search":
            await cmd_search(sys.argv[2])
        elif op == "download":
            await cmd_download(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
        elif op == "batch":
            await cmd_batch(sys.argv[2])
        else:
            print("未知命令: {}".format(op))
    finally:
        await close_context()


if __name__ == "__main__":
    asyncio.run(main())
