"""
fetch_3dgs.py — 3D 高斯泼溅文献批量检索与导入 Zotero

使用方法：
  cd D:\automan\coding\projects\cnki-mcp
  python sandbox/fetch_3dgs.py

流程：
  1. 检查 CNKI 登录状态
  2. 搜索两个关键词，双排序取前 N 篇
  3. 过滤：排除粮食/特定应用领域，保留理论研究
  4. 在 Zotero 创建收藏夹"3D高斯泼溅文献"
  5. 下载 PDF，导入 Zotero（含收藏夹关联）
"""

import asyncio
import sys
import os
from pathlib import Path

# Windows 终端强制 UTF-8 输出，避免 GBK 编码报错
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 路径 & 环境 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from cnki.browser import check_login_status, get_context
from cnki.search import search_multi_sort, _dedup_by_title
from cnki.download import batch_download
from cnki.zotero import (
    import_papers, get_existing_titles, filter_new_papers,
    create_zotero_collection,
)

# ── 参数 ─────────────────────────────────────────────────────
KEYWORDS    = ["3D高斯泼溅", "3D高斯溅射"]
YEAR_START  = 2023          # 3DGS 正式发表于 2023 年
YEAR_END    = 2026
TOP_N       = 30            # 每关键词每排序方向各取 30 篇

COLLECTION_NAME = "3D高斯泼溅文献"
PAPER_TAG       = "3D高斯泼溅"

# ── 过滤规则 ──────────────────────────────────────────────────
# 排除列表：粮食/食品/农业/医学/驾驶等与 3DGS 核心理论无关的应用领域
EXCLUDE_TERMS = [
    "粮仓", "粮食", "粮情", "储粮", "谷物", "小麦", "水稻", "玉米",
    "粮库", "仓储", "粮温", "种子",
    "医学影像", "医疗", "CT重建", "MRI", "内窥镜", "皮肤病",
    "无人驾驶", "自动驾驶",
    "遥感影像", "卫星影像",
]


def classify(paper: dict) -> tuple[bool, str]:
    """
    返回 (是否下载, 原因说明)。
    排除规则优先；其余全部保留（搜索词已足够精准）。
    """
    title = paper.get("title", "")
    for term in EXCLUDE_TERMS:
        if term in title:
            return False, f"排除域({term})"
    return True, "保留"


# ── 主流程 ────────────────────────────────────────────────────

async def main():
    sep = "=" * 65
    print(sep)
    print("  3D 高斯泼溅 CNKI 文献检索 & Zotero 导入")
    print(sep)

    # ── 1. 登录检查 ───────────────────────────────────────────
    print("\n[1/5] 检查 CNKI 登录状态…")
    status = await check_login_status()
    print(f"      {'[OK] 已登录' if status.get('logged_in') else '[FAIL] 未登录'}  {status.get('detail','')}")
    if not status.get("logged_in"):
        print("\n      [WARN]  请在弹出的浏览器中完成机构登录（约 120 秒）…")
        ctx = await get_context()
        page = await ctx.new_page()
        await page.goto("https://www.cnki.net", wait_until="domcontentloaded")
        await asyncio.sleep(120)
        await page.close()
        status2 = await check_login_status()
        if not status2.get("logged_in"):
            print("      仍未登录，退出。")
            return

    # ── 2. 搜索两个关键词 ─────────────────────────────────────
    print(f"\n[2/5] 搜索关键词（{YEAR_START}-{YEAR_END}，每词每排序各取 {TOP_N} 篇）…")
    raw_lists = []
    for kw in KEYWORDS:
        print(f"      [SEARCH] {kw} …", end=" ", flush=True)
        res = await search_multi_sort(
            query=kw,
            year_start=YEAR_START,
            year_end=YEAR_END,
            top_n_by_time=TOP_N,
            top_n_by_citations=TOP_N,
        )
        papers = res.get("papers", [])
        raw_lists.append(papers)
        print(f"{res.get('message','')}")

    # 两关键词合并去重
    combined = _dedup_by_title(raw_lists)
    print(f"\n      两关键词合并去重后：{len(combined)} 篇")

    # ── 3. 过滤 ───────────────────────────────────────────────
    print(f"\n[3/5] 过滤论文…")
    keep, skip = [], []
    for p in combined:
        ok, reason = classify(p)
        if ok:
            keep.append(p)
        else:
            skip.append((p["title"][:50], reason))

    print(f"      保留 {len(keep)} 篇 / 排除 {len(skip)} 篇")
    if skip:
        for t, r in skip:
            print(f"        ✗ [{r}] {t}")

    # 按引用量降序展示保留列表
    keep_sorted = sorted(keep, key=lambda p: p.get("citations", 0), reverse=True)
    print(f"\n      ─── 待处理论文列表（按引用量排序）───")
    print(f"      {'#':>3} {'年份':>4} {'引用':>5}  标题")
    print("      " + "-" * 60)
    for i, p in enumerate(keep_sorted, 1):
        print(f"      {i:3d}. [{p.get('year','?')}] {p.get('citations',0):5d}  {p.get('title','')[:50]}")

    if not keep_sorted:
        print("      无可用论文，退出。")
        return

    # ── 4. Zotero 查重 & 收藏夹 ──────────────────────────────
    print(f"\n[4/5] Zotero 去重 & 创建收藏夹…")
    existing = await get_existing_titles()
    dedup    = filter_new_papers(keep_sorted, existing)
    new_papers = dedup["new"]
    print(f"      Zotero 中已有 {dedup['removed']} 篇，新增：{len(new_papers)} 篇")
    if dedup["skipped"]:
        for t in dedup["skipped"]:
            print(f"        ↩ 已有：{t[:55]}")

    if not new_papers:
        print("      所有文献已在 Zotero 中，无需操作。")
        return

    # 创建收藏夹
    col_key = await create_zotero_collection(COLLECTION_NAME)
    if col_key:
        print(f"      [OK] Zotero 收藏夹「{COLLECTION_NAME}」key={col_key}")
    else:
        print(f"      [WARN]  收藏夹创建失败（需配置 ZOTERO_API_KEY + ZOTERO_LIB_ID）")
        print(f"         文献将以标签「{PAPER_TAG}」标记，请在 Zotero 手动整理。")

    # 设置每篇论文的收藏夹 key 和自定义 tag
    for p in new_papers:
        if col_key:
            p["_collection_key"] = col_key
        p["tags"] = [{"tag": PAPER_TAG}]

    # ── 5. 下载 PDF & 导入 Zotero ────────────────────────────
    print(f"\n[5/5] 下载 PDF & 导入 Zotero（共 {len(new_papers)} 篇）…")
    print(f"      下载间隔：6-12 秒（随机），验证码等待上限：120 秒")
    dl_result = await batch_download(new_papers, min_delay=6.0, max_delay=12.0, captcha_wait=120)
    ok_dl  = dl_result["success_count"]
    fail_dl = dl_result["fail_count"]
    print(f"      下载完成：成功 {ok_dl} / 失败 {fail_dl}")

    for paper, dl in zip(new_papers, dl_result.get("results", [])):
        if dl.get("success") and dl.get("file_path"):
            paper["pdf_path"] = dl["file_path"]
            print(f"        [OK] {paper['title'][:50]}")
        else:
            print(f"        [FAIL] {paper['title'][:50]}  ({dl.get('message','')[:60]})")

    print("\n      导入 Zotero…")
    z_result = await import_papers(new_papers)
    print(f"      {z_result.get('detail','')}")
    print(f"      method={z_result.get('method','')}  "
          f"写入={z_result.get('count',0)}  PDF关联={z_result.get('attached',0)}")

    # ── 汇总 ──────────────────────────────────────────────────
    print(f"\n{sep}")
    print(f"  完成！搜索 {len(combined)} → 过滤 {len(keep_sorted)} → "
          f"新增 {len(new_papers)} 篇导入 Zotero")
    if col_key:
        print(f"  收藏夹「{COLLECTION_NAME}」已创建（key={col_key}）")
    else:
        print(f"  请在 Zotero 中按标签「{PAPER_TAG}」筛选并手动加入收藏夹")
    print(sep)


if __name__ == "__main__":
    asyncio.run(main())
