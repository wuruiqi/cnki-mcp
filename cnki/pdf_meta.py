"""
pdf_meta.py — 从 CNKI PDF 中提取元数据

使用 PyMuPDF（fitz）提取：
  - 标题（title）   — 优先 PDF info dict；缺失时取首页最大字号文字块
  - 作者（authors） — PDF info dict 的 author 字段
  - 期刊（journal） — PDF info dict 的 subject 字段（部分 CNKI PDF 将期刊名存于此）
  - DOI             — 首页全文正则匹配

PyMuPDF 对中文 CJK 字符的布局还原和文字提取显著优于纯 Python 实现（pypdf），
尤其适合 CNKI 论文 PDF 的标题/作者区域解析。
"""

import re
from pathlib import Path
from typing import Dict, List

# PyMuPDF（安装包名 pymupdf，导入名 fitz）
try:
    import fitz  # type: ignore
    _FITZ_OK = True
except ImportError:
    _FITZ_OK = False


# DOI 正则：支持 "doi: 10.xxxx/...", "DOI:", "https://doi.org/..." 等写法
_DOI_RE = re.compile(
    r'(?:doi|DOI|https?://doi\.org/)[\s:]*'
    r'(10\.\d{4,}/[^\s,;。，；\]）)\n]+)',
    re.IGNORECASE,
)


def extract_pdf_metadata(pdf_path: str) -> Dict[str, str]:
    """
    提取 PDF 内嵌元数据。

    优先读取 PDF info dict（title / author / subject）；
    若 title 缺失，则在首页按字号排序找最大字号文字块作为备用。
    DOI 从首页全文正则匹配。

    Args:
        pdf_path: PDF 文件本地路径

    Returns:
        {"title": str, "authors": str, "journal": str, "doi": str}
        所有字段均为字符串，未能提取时为空字符串。
    """
    result: Dict[str, str] = {"title": "", "authors": "", "journal": "", "doi": ""}

    if not _FITZ_OK or not Path(pdf_path).exists():
        return result

    doc = None
    try:
        doc = fitz.open(pdf_path)

        # ── PDF info dict ─────────────────────────────────────────
        meta = doc.metadata or {}
        result["title"]   = (meta.get("title")   or "").strip()
        result["authors"] = (meta.get("author")  or "").strip()
        result["journal"] = (meta.get("subject") or "").strip()

        # ── 首页文本（DOI + 备用标题）────────────────────────────
        if doc.page_count > 0:
            page = doc[0]
            plain_text = page.get_text("text") or ""

            # DOI
            m = _DOI_RE.search(plain_text)
            if m:
                result["doi"] = m.group(1).rstrip(".,;。，；")

            # 备用标题：首页最大字号的非空文字块
            if not result["title"]:
                result["title"] = _largest_font_text(page)

    except Exception:
        pass
    finally:
        if doc is not None:
            doc.close()

    return result


def _largest_font_text(page) -> str:
    """
    在给定页面中，按 span 字号降序找到最大字号的连续文字，作为候选标题。
    跳过长度 < 4 或全为英数符号的 span（通常是页眉页码等噪声）。
    """
    try:
        # 收集所有 text span 及其字号
        spans: List[Dict] = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:  # 0 = text block
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = (span.get("text") or "").strip()
                    size = span.get("size", 0)
                    if text and len(text) >= 4:
                        spans.append({"text": text, "size": size, "y": span["origin"][1]})

        if not spans:
            return ""

        # 找最大字号
        max_size = max(s["size"] for s in spans)
        # 收集所有与最大字号相同（或差距 ≤ 1pt）的 span，按 y 坐标排序拼合
        title_parts = sorted(
            [s for s in spans if abs(s["size"] - max_size) <= 1.0],
            key=lambda s: s["y"],
        )
        title = "".join(s["text"] for s in title_parts).strip()
        return title[:200]

    except Exception:
        return ""


def compare_metadata(paper: Dict, pdf_meta: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    """
    比较 CNKI 搜索元数据与 PDF 提取元数据之间的差异。

    Args:
        paper:    来自 CNKI 搜索结果（或 Zotero）的论文字典
        pdf_meta: 由 extract_pdf_metadata 返回的 PDF 元数据

    Returns:
        差异字典，格式：{"field": {"current": ..., "from_pdf": ...}}
        仅包含 PDF 中有值且与现有值不同的字段。
    """
    diffs: Dict[str, Dict[str, str]] = {}

    for paper_key, pdf_key in [("title", "title"), ("authors", "authors"),
                                ("journal", "journal"), ("doi", "doi")]:
        current  = (paper.get(paper_key) or "").strip()
        from_pdf = (pdf_meta.get(pdf_key) or "").strip()
        if from_pdf and current != from_pdf:
            diffs[paper_key] = {"current": current, "from_pdf": from_pdf}

    return diffs
