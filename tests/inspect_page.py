"""
诊断脚本 —— dump CNKI 搜索/详情页的真实结构，用于定位正确选择器。

用法:
  python tests/inspect_page.py search "关键词"   # 诊断搜索结果页
  python tests/inspect_page.py home              # 诊断首页（登录标志）
  python tests/inspect_page.py url "<任意url>"   # 诊断任意页面
"""
import asyncio
import io
import sys
from urllib.parse import quote

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, "D:/automan/coding/projects/cnki-mcp")

from cnki.browser import get_context, close_context


async def dump_page(page, note=""):
    print("\n----- 落地页面 {} -----".format(note))
    print("URL  : {}".format(page.url))
    print("Title: {}".format(await page.title()))

    # frame 列表
    frames = page.frames
    print("Frames: {} 个".format(len(frames)))
    for f in frames:
        if f.url and f.url != page.url:
            print("   - frame: {}".format(f.url[:100]))

    # 统计常见容器是否存在
    candidate_selectors = [
        "table", "tbody tr", ".result-table-list", "#gridTable",
        ".brief-list", ".result-item", ".pagerTitleCell", ".result-count",
        "input#txt_search", "input.search-input", "input[name='kw']",
        ".search-box input", "#txt_SearchText", ".nodata", ".no-result",
    ]
    print("候选容器存在性:")
    for sel in candidate_selectors:
        try:
            count = await page.locator(sel).count()
            if count > 0:
                print("   ✓ {} -> {} 个".format(sel, count))
        except Exception as e:
            print("   ! {} 报错 {}".format(sel, e))

    # body 文本前 400 字
    try:
        text = await page.evaluate("document.body.innerText")
        print("body 文本片段: {!r}".format(text[:400].replace("\n", " ")))
    except Exception as e:
        print("取 body 文本失败: {}".format(e))


async def inspect_search(query):
    ctx = await get_context()
    page = await ctx.new_page()
    kw = quote(query)
    urls = [
        ("kns8s-CJFD", "https://kns.cnki.net/kns8s/defaultresult/index?dbcode=CJFD&SKey={}&sopt=2".format(kw)),
        ("kns8s-simple", "https://kns.cnki.net/kns8s/simple/defaultresult/index?dbPrefix=CJFDLAST&kw={}".format(kw)),
        ("kns8-CJFD", "https://kns.cnki.net/kns8/defaultresult/index?dbcode=CJFD&SKey={}&sopt=2".format(kw)),
        ("首页", "https://kns.cnki.net/"),
    ]
    for note, url in urls:
        try:
            print("\n========== 尝试 {} ==========".format(note))
            print("请求: {}".format(url))
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(4000)
            await dump_page(page, note)
        except Exception as e:
            print("导航失败: {}".format(e))
    await page.close()


async def inspect_home():
    ctx = await get_context()
    page = await ctx.new_page()
    await page.goto("https://www.cnki.net", wait_until="domcontentloaded", timeout=25000)
    await page.wait_for_timeout(3000)
    await dump_page(page, "首页")
    # dump 所有含"登录"的元素
    print("\n含'登录'文字的元素:")
    try:
        items = await page.eval_on_selector_all(
            "a, button, span, div",
            """els => els.filter(e => e.textContent && e.textContent.trim().length < 12 && e.textContent.includes('登录'))
                       .slice(0,10).map(e => ({tag:e.tagName, cls:e.className, id:e.id, txt:e.textContent.trim()}))"""
        )
        for it in items:
            print("   {}".format(it))
    except Exception as e:
        print("   失败: {}".format(e))
    await page.close()


async def inspect_url(url):
    ctx = await get_context()
    page = await ctx.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=25000)
    await page.wait_for_timeout(4000)
    await dump_page(page, "自定义")
    await page.close()


async def main():
    op = sys.argv[1] if len(sys.argv) > 1 else "home"
    try:
        if op == "search":
            await inspect_search(sys.argv[2])
        elif op == "home":
            await inspect_home()
        elif op == "url":
            await inspect_url(sys.argv[2])
    finally:
        await close_context()


if __name__ == "__main__":
    asyncio.run(main())
