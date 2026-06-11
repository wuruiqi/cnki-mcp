"""搜索 → 打开首篇详情页 → dump 下载按钮结构。"""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, "D:/automan/coding/projects/cnki-mcp")

from cnki.browser import get_context, close_context
from cnki.search import search_papers


async def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "粮仓温度监测"
    r = await search_papers(query=query, max_results=2)
    if not r["papers"]:
        print("搜索无结果")
        await close_context()
        return
    paper = r["papers"][0]
    print("详情页:", paper["title"])
    print("URL:", paper["url"][:100])

    ctx = await get_context()
    page = await ctx.new_page()
    await page.goto(paper["url"], wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(4000)

    print("\n落地 URL:", page.url)
    print("Title:", await page.title())

    # dump 所有下载相关链接/按钮
    print("\n===== 下载相关元素 =====")
    items = await page.eval_on_selector_all(
        "a, button, li",
        """els => els.filter(e => {
            const t=(e.textContent||'').trim();
            return (t.includes('下载')||t.includes('PDF')||t.includes('CAJ')||t.includes('全文'))
                   && t.length<20;
        }).slice(0,25).map(e => ({
            tag:e.tagName, id:e.id, cls:e.className,
            txt:(e.textContent||'').trim(),
            href:e.getAttribute('href')
        }))"""
    )
    for o in items:
        print("  ", o)

    # 常见下载按钮选择器存在性
    print("\n===== 候选选择器命中 =====")
    for sel in ["#pdfDown", "#cajDown", "a.btn-dlpdf", "a.btn-dlcaj",
                "li.btn-dl a", ".operate-btn a", "#downloadlink a",
                "a[href*='download']", "a[href*='Download']",
                ".operate-save", ".btn-down"]:
        try:
            cnt = await page.locator(sel).count()
            if cnt:
                print("  ✓ {} -> {}".format(sel, cnt))
        except Exception:
            pass

    await page.close()
    await close_context()


if __name__ == "__main__":
    asyncio.run(main())
