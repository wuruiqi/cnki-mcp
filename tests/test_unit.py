"""
离线单元测试 —— 只测不依赖网络/登录的纯函数与常量。

运行：
  pytest tests/test_unit.py -v
（需真实 CNKI/Zotero 的集成测试不在此文件，CI 仅跑本文件。）
"""

import asyncio
import os
import subprocess
from pathlib import Path

from cnki.download import _safe_filename
from cnki.zotero import _build_item, filter_new_papers
from cnki.pdf_meta import compare_metadata, extract_pdf_metadata
from cnki import search as search_mod
from cnki import browser as browser_mod


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


# ─── browser profile 认领与死实例清理 ────────────────────────

def test_pid_alive_self():
    assert browser_mod._pid_alive(os.getpid())


def test_pid_alive_dead_process():
    p = subprocess.Popen(["true"])
    p.wait()
    assert not browser_mod._pid_alive(p.pid)


def test_cleanup_dead_instances(tmp_path):
    # 死进程的 profile 目录应被清理；活进程与非数字目录保留
    p = subprocess.Popen(["true"])
    p.wait()
    dead = tmp_path / str(p.pid)
    dead.mkdir()
    alive = tmp_path / str(os.getpid())
    alive.mkdir()
    named = tmp_path / "notanumber"
    named.mkdir()

    browser_mod._cleanup_dead_instances(tmp_path)

    assert not dead.exists()
    assert alive.exists()
    assert named.exists()


def test_instance_profile_is_pid_scoped(tmp_path):
    profile = browser_mod._instance_profile(tmp_path / "base")
    assert profile.name == str(os.getpid())
    assert profile.is_dir()


def test_claim_profile_reuses_after_release(tmp_path, monkeypatch):
    # 认领 → 释放 → 再认领：应始终拿回共享 base profile
    if browser_mod.fcntl is None:
        return  # 非 POSIX 无 fcntl，跳过
    base = tmp_path / "prof"
    monkeypatch.setattr(browser_mod, "PROFILE_DIR", str(base))
    browser_mod._release_profile_lock()
    try:
        assert browser_mod._claim_profile() == base
        browser_mod._release_profile_lock()
        assert browser_mod._claim_profile() == base
    finally:
        browser_mod._release_profile_lock()


def test_claim_profile_conflict_falls_back_to_instance(tmp_path, monkeypatch):
    # 另一"进程"（另一 fd）持有 base 锁时，必须让路到独立实例目录
    if browser_mod.fcntl is None:
        return  # 非 POSIX 无 fcntl，跳过
    import fcntl as _fcntl

    base = tmp_path / "prof"
    base.mkdir()
    monkeypatch.setattr(browser_mod, "PROFILE_DIR", str(base))
    browser_mod._release_profile_lock()

    lock_path = Path(str(base) + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
    try:
        got = browser_mod._claim_profile()
        assert got != base
        assert got.name == str(os.getpid())
        assert str(got).endswith(".instances/" + str(os.getpid()))
    finally:
        _fcntl.flock(fd, _fcntl.LOCK_UN)
        os.close(fd)
        browser_mod._release_profile_lock()


# ─── get_context 崩溃自愈（IPC 探活） ─────────────────────────

async def _async_return(value):
    return value


class _FakeCtx:
    """模拟 BrowserContext：alive=False 时 cookies() 抛出（Chrome 已崩溃）。"""

    def __init__(self, alive: bool):
        self.alive = alive
        self.closed = False

    async def cookies(self):
        if not self.alive:
            raise RuntimeError("Target page, context or browser has been closed")
        return []

    async def close(self):
        self.closed = True

    def on(self, *_args, **_kwargs):
        pass


def test_get_context_rebuilds_after_browser_crash(tmp_path, monkeypatch):
    # 死 context：cookies() 探活失败 → 必须丢弃并重建，而不是继续返回
    dead = _FakeCtx(alive=False)
    fresh = _FakeCtx(alive=True)
    monkeypatch.setattr(browser_mod, "_context", dead)
    monkeypatch.setattr(browser_mod, "_playwright", object())  # 跳过真实启动
    monkeypatch.setattr(browser_mod, "_claim_profile", lambda: tmp_path)
    monkeypatch.setattr(browser_mod, "_launch_persistent",
                        lambda _p: _async_return(fresh))
    monkeypatch.setattr(browser_mod, "load_cookies", lambda _c: _async_return(None))

    got = asyncio.run(browser_mod.get_context())
    assert got is fresh
    assert dead.closed          # 死 context 已被关闭清理


def test_get_context_reuses_live_context(tmp_path, monkeypatch):
    # 活 context：探活成功 → 直接复用，不重启
    live = _FakeCtx(alive=True)

    def _fail_launch(_p):
        raise AssertionError("活 context 不应触发重启")

    monkeypatch.setattr(browser_mod, "_context", live)
    monkeypatch.setattr(browser_mod, "_launch_persistent", _fail_launch)

    got = asyncio.run(browser_mod.get_context())
    assert got is live
    assert not live.closed
