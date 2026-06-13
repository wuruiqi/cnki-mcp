"""
离线单元测试 —— 只测不依赖网络/登录的纯函数与常量。

运行：
  pytest tests/test_unit.py -v
（需真实 CNKI/Zotero 的集成测试不在此文件，CI 仅跑本文件。）
"""

from cnki.download import _safe_filename
from cnki.zotero import _build_item, filter_new_papers
from cnki.pdf_meta import compare_metadata, extract_pdf_metadata
from cnki import search as search_mod


# ─── download._safe_filename ────────────────────────────────

def test_safe_filename_appends_suffix():
    assert _safe_filename("粮仓温度监测").endswith(".pdf")
    assert _safe_filename("abc", ".caj").endswith(".caj")


def test_safe_filename_strips_illegal_chars():
    out = _safe_filename('a/b:c*d?e"f<g>h|i')
    for ch in '/\\:*?"<>|':
        assert ch not in out[:-4]  # 后缀前不含非法字符


def test_safe_filename_truncates_long_title():
    long = "标" * 300
    out = _safe_filename(long)
    assert len(out) <= 124  # 120 + ".pdf"


# ─── zotero._build_item ─────────────────────────────────────

def test_build_item_basic_fields():
    item = _build_item({"title": "测试标题", "journal": "测试期刊", "year": "2024", "url": "http://x"})
    assert item["itemType"] == "journalArticle"
    assert item["title"] == "测试标题"
    assert item["publicationTitle"] == "测试期刊"
    assert item["date"] == "2024"


def test_build_item_splits_authors():
    item = _build_item({"title": "t", "authors": "张三;李四;王五"})
    assert len(item["creators"]) == 3
    assert item["creators"][0]["lastName"] == "张三"
    assert item["creators"][0]["creatorType"] == "author"


def test_build_item_has_cnki_tags():
    tags = [t["tag"] for t in _build_item({"title": "t"})["tags"]]
    assert "CNKI" in tags
    assert "cnki-mcp" in tags


def test_build_item_empty_authors_no_creators():
    assert _build_item({"title": "t", "authors": ""})["creators"] == []


# ─── zotero.filter_new_papers ───────────────────────────────

def test_filter_new_papers_removes_existing():
    papers = [
        {"title": "已有论文 A"},
        {"title": "新论文 B"},
        {"title": "已有论文 C"},
    ]
    existing = {"已有论文a", "已有论文c"}  # 归一化后去掉空格、小写
    result = filter_new_papers(papers, existing)
    assert result["removed"] == 2
    assert len(result["new"]) == 1
    assert result["new"][0]["title"] == "新论文 B"


def test_filter_new_papers_empty_existing():
    papers = [{"title": "A"}, {"title": "B"}]
    result = filter_new_papers(papers, set())
    assert result["removed"] == 0
    assert len(result["new"]) == 2


# ─── pdf_meta.compare_metadata ──────────────────────────────

def test_compare_metadata_detects_diff():
    paper = {"title": "旧标题", "authors": "张三", "doi": "", "journal": "期刊A"}
    pdf   = {"title": "新标题", "authors": "张三", "doi": "10.1234/abc", "journal": "期刊A"}
    diffs = compare_metadata(paper, pdf)
    assert "title" in diffs
    assert diffs["title"]["current"] == "旧标题"
    assert diffs["title"]["from_pdf"] == "新标题"
    assert "doi" in diffs
    assert "authors" not in diffs   # 相同，不计入差异
    assert "journal" not in diffs   # 相同，不计入差异


def test_compare_metadata_no_diff():
    paper = {"title": "标题", "authors": "作者", "doi": "10.x/y", "journal": "J"}
    pdf   = {"title": "标题", "authors": "作者", "doi": "10.x/y", "journal": "J"}
    assert compare_metadata(paper, pdf) == {}


def test_compare_metadata_pdf_empty_ignored():
    paper = {"title": "标题", "authors": "作者"}
    pdf   = {"title": "", "authors": ""}   # PDF 中无值，不应产生差异
    assert compare_metadata(paper, pdf) == {}


# ─── pdf_meta.extract_pdf_metadata（无 PDF 文件时安全返回）──

def test_extract_pdf_metadata_missing_file():
    result = extract_pdf_metadata("/nonexistent/path/file.pdf")
    assert result == {"title": "", "authors": "", "journal": "", "doi": ""}


# ─── search 选择器常量完整性 ────────────────────────────────

def test_search_row_selectors_present():
    assert len(search_mod._ROW_SELECTORS) > 0


def test_search_field_selectors_keys():
    for key in ("title", "year", "journal", "authors", "citations"):
        assert key in search_mod._FIELD_SELECTORS
        assert len(search_mod._FIELD_SELECTORS[key]) > 0


def test_search_sort_selectors_keys():
    assert "citations" in search_mod._SORT_SELECTORS
    assert "time" in search_mod._SORT_SELECTORS
    for selectors in search_mod._SORT_SELECTORS.values():
        assert len(selectors) > 0


def test_dedup_by_title_removes_duplicates():
    list1 = [{"title": "论文 A"}, {"title": "论文 B"}]
    list2 = [{"title": "论文 A"}, {"title": "论文 C"}]  # "论文 A" 重复
    merged = search_mod._dedup_by_title([list1, list2])
    titles = [p["title"] for p in merged]
    assert titles.count("论文 A") == 1
    assert len(merged) == 3


def test_filter_by_year_limits_count():
    papers = [{"year": str(y)} for y in range(2020, 2030)]
    result = search_mod._filter_by_year(papers, 2020, 2025, 3)
    assert len(result) == 3
    for p in result:
        assert 2020 <= int(p["year"]) <= 2025


def test_filter_by_year_fallback_when_all_filtered():
    papers = [{"year": "2010"}, {"year": "2011"}]
    # 全部超出范围时退回原始前 N 篇
    result = search_mod._filter_by_year(papers, 2020, 2025, 5)
    assert result == papers
