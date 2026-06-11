"""
test_search.py — 搜索模块基本测试

注意：这些测试需要 CNKI 登录状态，运行前请确保：
1. CNKI 已登录（Cookie 已保存）
2. 校园网 VPN 已连接
3. conda 环境为 cnki-mcp

运行：
  conda run -n cnki-mcp python -m pytest tests/ -v
"""

import asyncio
import pytest
from cnki.search import _build_search_urls, search_papers


# ─── 纯逻辑测试（无网络） ────────────────────────────────────

def test_build_search_urls_count():
    urls = _build_search_urls("螺旋推进", 2018, 2026, "CJFD")
    assert len(urls) == 5


def test_build_search_urls_contains_query():
    urls = _build_search_urls("粮仓监测", 2020, 2026, "CJFD")
    # 关键词应出现在所有 URL 中（URL 编码后）
    for url in urls:
        assert "cnki.net" in url


def test_build_search_urls_db_code():
    urls = _build_search_urls("测试", 2020, 2026, "CDFD")
    # 博士论文数据库代码应出现在 URL 中
    assert any("CDFD" in u for u in urls)


# ─── 集成测试（需要网络 + 登录） ────────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_returns_structure():
    """验证 search_papers 返回正确的数据结构（不验证内容）。"""
    result = await search_papers(query="粮仓温度", max_results=3)
    assert "success" in result
    assert "query" in result
    assert "count" in result
    assert "papers" in result
    assert "message" in result
    assert isinstance(result["papers"], list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_paper_fields():
    """验证每篇论文有必要字段。"""
    result = await search_papers(query="粮情检测", max_results=2)
    if result["success"] and result["papers"]:
        for paper in result["papers"]:
            assert "title" in paper
            assert "url" in paper
            assert len(paper["title"]) > 0
