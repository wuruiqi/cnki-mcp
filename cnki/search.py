"""
search.py — CNKI 文献检索

策略：表单交互检索（2026 验证可用）。
  1. 打开 kns8s 首页
  2. 在 #txt_search 填关键词，点 .search-btn
  3. 跳转到结果页，解析 .result-table-list 表格

注：CNKI 旧版 SKey GET 参数已失效，必须走表单提交。
"""

import asyncio
import re
from typing import List, Dict, Optional

from .browser import get_context

# 检索入口页
_SEARCH_HOME = "https://kns.cnki.net/kns8s/"

# 检索框 / 检索按钮选择器
_INPUT_SELECTORS = ["input#txt_search", "input.search-input", "input[name='kw']"]
_BUTTON_SELECTORS = ["input.search-btn", ".search-btn", "button.search-btn"]

# 结果页有结果时的标志选择器
_RESULT_MARKERS = [
    ".result-table-list",
    "#gridTable",
    ".brief-list",
]

# 结果行选择器（按优先级）
_ROW_SELECTORS = [
    ".result-table-list tbody tr",
    "#gridTable tbody tr",
    "table.result-table-list tr",
]

# 字段选择器（已在 2026 实测确认）
_FIELD_SELECTORS: Dict[str, List[str]] = {
    "title":     ["td.name a", "a.fz14", ".name a"],
    "year":      ["td.date", ".date"],
    "journal":   ["td.source", ".source"],
    "authors":   ["td.author", ".author"],
    "citations": ["td.quote", ".quote", "td.cited", ".cited"],
}

# 数据库标签页（按 db_code 限定文献类型）
_DB_TAB_TEXT = {
    "CJFD": "学术期刊",
    "CDFD": "博士",
    "CMFD": "硕士",
}

# 排序按钮选择器
_SORT_SELECTORS: Dict[str, List[str]] = {
    "citations": [
        "a:has-text('被引量')",
        "a:has-text('被引')",
        "li a:has-text('被引')",
        ".sort-list a:has-text('被引')",
    ],
    "time": [
        "a:has-text('发表时间')",
        "li a:has-text('发表时间')",
        ".sort-list a:has-text('时间')",
        "a:has-text('时间')",
    ],
}


async def _fill_and_search(page, query: str) -> bool:
    """在检索框输入关键词并提交，返回是否到达结果页。"""
    # 填检索框
    filled = False
    for sel in _INPUT_SELECTORS:
        try:
            if await page.locator(sel).count() > 0:
                await page.fill(sel, query)
                filled = True
                break
        except Exception:
            pass
    if not filled:
        return False

    # 点检索按钮（失败则回车兜底）
    clicked = False
    for sel in _BUTTON_SELECTORS:
        try:
            if await page.locator(sel).count() > 0:
                await page.locator(sel).first.click()
                clicked = True
                break
        except Exception:
            pass
    if not clicked:
        try:
            await page.press(_INPUT_SELECTORS[0], "Enter")
        except Exception:
            return False

    # 等结果容器出现
    await page.wait_for_timeout(4500)
    for marker in _RESULT_MARKERS:
        try:
            if await page.locator(marker).count() > 0:
                return True
        except Exception:
            pass
    return False


async def _restrict_to_db(page, db: str) -> None:
    """点击对应文献类型标签页（如"学术期刊"），缩小结果范围。失败则忽略。"""
    label = _DB_TAB_TEXT.get(db)
    if not label:
        return
    try:
        tab = page.locator("a:has-text('{}')".format(label)).first
        if await tab.count() > 0 and await tab.is_visible():
            await tab.click()
            await page.wait_for_timeout(3000)
    except Exception:
        pass


async def _try_navigate_search(page, query: str, year_start: int, year_end: int, db: str) -> bool:
    """打开检索首页并提交检索，返回是否成功到达结果页。"""
    try:
        await page.goto(_SEARCH_HOME, wait_until="domcontentloaded", timeout=25_000)
        await page.wait_for_timeout(3500)
    except Exception:
        return False

    reached = await _fill_and_search(page, query)
    if not reached:
        return False

    # 限定文献类型（期刊/学位论文）
    await _restrict_to_db(page, db)
    return True


async def _click_sort(page, sort_by: str) -> bool:
    """点击排序按钮（'citations' 或 'time'），等待结果重新加载。返回是否成功点击。"""
    for sel in _SORT_SELECTORS.get(sort_by, []):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible(timeout=2000):
                await loc.click()
                await page.wait_for_timeout(4000)
                return True
        except Exception:
            pass
    return False


async def _extract_rows(page, max_count: int) -> List[Dict]:
    """从当前结果页提取论文列表（含引用量）。"""

    async def first_text(row, selectors: List[str]) -> str:
        for sel in selectors:
            try:
                el = await row.query_selector(sel)
                if el:
                    text = (await el.text_content() or "").strip()
                    if text:
                        return text
            except Exception:
                pass
        return ""

    papers = []

    for row_sel in _ROW_SELECTORS:
        rows = await page.query_selector_all(row_sel)
        if not rows:
            continue

        for row in rows:
            if len(papers) >= max_count:
                break
            try:
                # 标题（必须有）
                title_el = None
                for sel in _FIELD_SELECTORS["title"]:
                    title_el = await row.query_selector(sel)
                    if title_el:
                        break
                if not title_el:
                    continue

                title = (await title_el.text_content() or "").strip()
                if not title or len(title) < 4:
                    continue

                href  = (await title_el.get_attribute("href") or "").strip()
                year      = await first_text(row, _FIELD_SELECTORS["year"])
                journal   = await first_text(row, _FIELD_SELECTORS["journal"])
                authors   = await first_text(row, _FIELD_SELECTORS["authors"])
                cite_text = await first_text(row, _FIELD_SELECTORS["citations"])

                # 年份：只保留 4 位数字
                m = re.search(r"\d{4}", year)
                year = m.group() if m else ""

                # 引用量：提取数字
                cm = re.search(r"\d+", cite_text)
                citations = int(cm.group()) if cm else 0

                papers.append({
                    "title":     title,
                    "href":      href,
                    "year":      year,
                    "journal":   journal,
                    "authors":   authors,
                    "citations": citations,
                    "url":       href if href.startswith("http") else f"https://kns.cnki.net{href}",
                })
            except Exception:
                pass

        if papers:
            break  # 第一个有效选择器命中后停止

    return papers


def _filter_by_year(papers: List[Dict], year_start: int, year_end: int, max_n: int) -> List[Dict]:
    """过滤年份范围，最多返回 max_n 篇；若过滤后为空则退回不过滤的前 max_n 篇。"""
    filtered = []
    for p in papers:
        y = p.get("year", "")
        if y.isdigit() and not (year_start <= int(y) <= year_end):
            continue
        filtered.append(p)
        if len(filtered) >= max_n:
            break
    return filtered if filtered else papers[:max_n]


def _dedup_by_title(lists: List[List[Dict]]) -> List[Dict]:
    """将多个论文列表合并去重（按标题归一化后判断）。"""
    seen = set()
    result = []
    for papers in lists:
        for p in papers:
            key = re.sub(r"\s+", "", p.get("title", "")).lower()
            if key and key not in seen:
                seen.add(key)
                result.append(p)
    return result


async def search_papers(
    query: str,
    year_start: int = 2018,
    year_end: int = 2026,
    max_results: int = 6,
    db_code: str = "CJFD",
) -> Dict:
    """
    搜索 CNKI 期刊论文（按相关度）。

    Args:
        query:       检索词（主题检索，支持空格分隔多词）
        year_start:  起始年份
        year_end:    结束年份
        max_results: 最多返回论文数
        db_code:     数据库代码（CJFD=期刊, CDFD=博士论文, CMFD=硕士论文）

    Returns:
        {
          "success": bool,
          "query": str,
          "count": int,
          "papers": [{"title", "authors", "year", "journal", "citations", "url", "href"}, ...]
          "message": str
        }
    """
    ctx = await get_context()
    page = await ctx.new_page()
    try:
        reached = await _try_navigate_search(page, query, year_start, year_end, db_code)

        if not reached:
            return {
                "success": False,
                "query": query,
                "count": 0,
                "papers": [],
                "message": (
                    "未能到达搜索结果页。可能原因：\n"
                    "1. 未登录 CNKI —— 请先调用 cnki_open_login_page 完成登录\n"
                    "2. 网络不通 —— 请确认校园网 VPN 已连接\n"
                    "3. CNKI URL 格式已变更"
                ),
            }

        # 多取一些再按年份过滤
        raw = await _extract_rows(page, max_results * 4)
        papers = _filter_by_year(raw, year_start, year_end, max_results)

        return {
            "success": True,
            "query": query,
            "count": len(papers),
            "papers": papers,
            "message": f"找到 {len(papers)} 篇（原始 {len(raw)} 篇，年份 {year_start}-{year_end}），URL: {page.url[:80]}",
        }
    finally:
        await page.close()


async def search_multi_sort(
    query: str,
    year_start: int = 2018,
    year_end: int = 2026,
    top_n_by_time: int = 50,
    top_n_by_citations: int = 50,
    db_code: str = "CJFD",
) -> Dict:
    """
    搜索 CNKI 论文，分别按发表时间和引用量排序取前 N 篇，合并去重后返回。

    Args:
        query:              检索词
        year_start:         起始年份
        year_end:           结束年份
        top_n_by_time:      按发表时间取前 N 篇（0 = 禁用此排序）
        top_n_by_citations: 按引用量取前 N 篇（0 = 禁用此排序）
        db_code:            数据库代码

    Returns:
        {
          "success": bool,
          "papers": [...],            # 合并去重后列表
          "by_time_count": int,
          "by_citations_count": int,
          "total_after_dedup": int,
          "sort_used": {"time": bool, "citations": bool},  # 是否成功使用 CNKI 排序
          "message": str,
        }
    """
    ctx = await get_context()
    page = await ctx.new_page()
    try:
        reached = await _try_navigate_search(page, query, year_start, year_end, db_code)
        if not reached:
            return {
                "success": False,
                "papers": [],
                "by_time_count": 0,
                "by_citations_count": 0,
                "total_after_dedup": 0,
                "sort_used": {"time": False, "citations": False},
                "message": (
                    "未能到达搜索结果页。可能原因：\n"
                    "1. 未登录 CNKI —— 请先调用 cnki_open_login_page 完成登录\n"
                    "2. 网络不通 —— 请确认校园网 VPN 已连接\n"
                    "3. CNKI URL 格式已变更"
                ),
            }

        by_citations: List[Dict] = []
        by_time:      List[Dict] = []
        sort_used = {"time": False, "citations": False}

        # ── 按引用量排序 ──────────────────────────────────────────
        if top_n_by_citations > 0:
            clicked = await _click_sort(page, "citations")
            sort_used["citations"] = clicked
            raw = await _extract_rows(page, top_n_by_citations * 3)
            filtered = _filter_by_year(raw, year_start, year_end, top_n_by_citations)
            if not clicked:
                # 客户端兜底排序：按 citations 字段降序
                filtered = sorted(filtered, key=lambda p: p.get("citations", 0), reverse=True)
            by_citations = filtered[:top_n_by_citations]

        # ── 按发表时间排序 ────────────────────────────────────────
        if top_n_by_time > 0:
            clicked = await _click_sort(page, "time")
            sort_used["time"] = clicked
            raw = await _extract_rows(page, top_n_by_time * 3)
            filtered = _filter_by_year(raw, year_start, year_end, top_n_by_time)
            if not clicked:
                # 客户端兜底排序：按年份降序
                filtered = sorted(
                    filtered,
                    key=lambda p: int(p.get("year") or "0"),
                    reverse=True,
                )
            by_time = filtered[:top_n_by_time]

        # ── 两项均未请求时，按相关度取前 50 ──────────────────────
        if top_n_by_citations == 0 and top_n_by_time == 0:
            raw = await _extract_rows(page, 150)
            by_time = _filter_by_year(raw, year_start, year_end, 50)

        # ── 合并去重 ──────────────────────────────────────────────
        papers = _dedup_by_title([by_citations, by_time])

        parts = []
        if top_n_by_citations > 0:
            parts.append(f"引用量前{len(by_citations)}篇")
        if top_n_by_time > 0:
            parts.append(f"时间前{len(by_time)}篇")

        return {
            "success": True,
            "papers": papers,
            "by_time_count": len(by_time),
            "by_citations_count": len(by_citations),
            "total_after_dedup": len(papers),
            "sort_used": sort_used,
            "message": (
                f"搜索成功：{'、'.join(parts) if parts else '相关度前50篇'}，"
                f"合并去重后共 {len(papers)} 篇"
            ),
        }
    finally:
        await page.close()
