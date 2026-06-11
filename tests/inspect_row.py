"""dump 一条结果行的内部 HTML 结构，定位字段选择器。"""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, "D:/automan/coding/projects/cnki-mcp")

from cnki.browser import get_context, close_context


async def main():
    ctx = await get_context()
    page = await ctx.new_page()
    await page.goto("https://kns.cnki.net/kns8s/", wait_until="domcontentloaded", timeout=25000)
    await page.wait_for_timeout(3500)
    await page.fill("input#txt_search", "粮仓温度监测")
    await page.locator("input.search-btn").first.click()
    await page.wait_for_timeout(5000)

    # dump 第一行 HTML
    print("===== 第一条结果行 outerHTML =====")
    html = await page.eval_on_selector(".result-table-list tbody tr", "el => el.outerHTML")
    print(html[:2000])

    # 解析字段
    print("\n===== 字段候选解析（前3行）=====")
    rows = await page.eval_on_selector_all(
        ".result-table-list tbody tr",
        """els => els.slice(0,3).map(tr => {
            const q = (sel) => { const e=tr.querySelector(sel); return e? e.textContent.trim().slice(0,40):null; };
            const titleA = tr.querySelector('td.name a') || tr.querySelector('a.fz14') || tr.querySelector('.name a');
            return {
                'td.name a': q('td.name a'),
                'a.fz14': q('a.fz14'),
                '.author': q('.author'),
                'td.author': q('td.author'),
                '.source': q('.source'),
                'td.source': q('td.source'),
                '.date': q('.date'),
                'td.date': q('td.date'),
                'title_href': titleA ? titleA.getAttribute('href') : null
            };
        })"""
    )
    for i, r in enumerate(rows):
        print("\n--- 行 {} ---".format(i))
        for k, v in r.items():
            print("  {:14} : {}".format(k, v))

    await page.close()
    await close_context()


if __name__ == "__main__":
    asyncio.run(main())
