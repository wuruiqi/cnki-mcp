"""
离线单元测试 —— 只测不依赖网络/登录的纯函数与常量。

运行：
  pytest tests/test_unit.py -v
（需真实 CNKI/Zotero 的集成测试不在此文件，CI 仅跑本文件。）
"""

from cnki.download import _safe_filename
from cnki.zotero import _build_item
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


# ─── search 选择器常量完整性 ────────────────────────────────

def test_search_row_selectors_present():
    assert len(search_mod._ROW_SELECTORS) > 0


def test_search_field_selectors_keys():
    for key in ("title", "year", "journal", "authors"):
        assert key in search_mod._FIELD_SELECTORS
        assert len(search_mod._FIELD_SELECTORS[key]) > 0
