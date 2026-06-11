"""dump CNKI 检索框与检索按钮结构，定位表单交互选择器。"""
import asyncio
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cnki.browser import get_context, close_context


async def main():
    ctx = await get_context()
    page = await ctx.new_page()
    # 高级检索/普通检索入口
    await page.goto("https://kns.cnki.net/kns8s/", wait_until="domcontentloaded", timeout=25000)
    await page.wait_for_timeout(4000)

    print("URL:", page.url)
    print("Title:", await page.title())

    # 所有 input
    print("\n===== 所有可见 input =====")
    inputs = await page.eval_on_selector_all(
        "input",
        """els => els.map(e => ({
            id:e.id, name:e.name, cls:e.className, type:e.type,
            ph:e.placeholder, vis:!!(e.offsetWidth||e.offsetHeight)
        })).filter(o => o.vis)"""
    )
    for o in inputs:
        print("  ", o)

    # 检索按钮候选
    print("\n===== 含'检索'/搜索按钮 =====")
    btns = await page.eval_on_selector_all(
        "button, input[type='button'], input[type='submit'], a, .search-btn, [class*='search']",
        """els => els.filter(e => {
            const t=(e.textContent||e.value||'').trim();
            return (t.includes('检索')||t.includes('搜索')||(e.className||'').includes('search-btn'))
                   && t.length<10 && (e.offsetWidth||e.offsetHeight);
        }).slice(0,15).map(e => ({tag:e.tagName, id:e.id, cls:e.className, txt:(e.textContent||e.value||'').trim()}))"""
    )
    for o in btns:
        print("  ", o)

    # 尝试实际交互：输入并点检索，看是否到结果页
    print("\n===== 实测：输入关键词并点检索 =====")
    try:
        await page.fill("input#txt_search", "粮仓温度监测")
        print("已填入关键词")
        # 找检索按钮点击
        clicked = False
        for sel in ["input.search-btn", ".search-btn", "button.search-btn",
                    "input[value='检索']", ".search-p .search-btn",
                    "#ModuleSearch input[type='button']"]:
            try:
                if await page.locator(sel).count() > 0:
                    await page.locator(sel).first.click()
                    print("点击了按钮:", sel)
                    clicked = True
                    break
            except Exception as e:
                print("  点击 {} 失败: {}".format(sel, e))
        if not clicked:
            print("未找到检索按钮，尝试回车")
            await page.press("input#txt_search", "Enter")
        await page.wait_for_timeout(5000)
        print("点击后 URL:", page.url)
        print("点击后 Title:", await page.title())
        # 结果容器
        for sel in [".result-table-list", "#gridTable", "tbody tr", ".result-table-list tbody tr",
                    "table.result-table-list", ".gridTable"]:
            cnt = await page.locator(sel).count()
            if cnt:
                print("  结果容器 ✓ {} -> {}".format(sel, cnt))
        body = await page.evaluate("document.body.innerText")
        print("结果页 body 片段:", repr(body[:300].replace("\n", " ")))
    except Exception as e:
        print("交互失败:", e)

    await page.close()
    await close_context()


if __name__ == "__main__":
    asyncio.run(main())
