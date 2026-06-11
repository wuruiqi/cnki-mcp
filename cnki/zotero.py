"""
zotero.py — 导入文献到 Zotero（含 PDF 自动迁移与关联）

策略（优先级顺序）：
1. Zotero 本地 Connector（localhost:23119）：
   - /connector/saveItems   写入条目元数据
   - /connector/saveAttachment  上传本地 PDF 字节并关联为子附件（导入 Zotero 存储）
   附件是否云同步取决于 Zotero 设置，本地存储不额外占用云配额。
2. Zotero 云 API：本地不可用时降级，仅写元数据（不含 PDF）。

要点：
- httpx 必须 trust_env=False —— 若系统配置了 HTTP 代理，可能拦截 localhost 请求返回 502。
- X-Metadata 头必须纯 ASCII（json.dumps 默认 ensure_ascii=True，中文转 \\uXXXX）。
"""

import os
import json
import uuid
import asyncio
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

ZOTERO_LOCAL_API  = os.getenv("ZOTERO_LOCAL_API", "http://127.0.0.1:23119")
ZOTERO_API_KEY    = os.getenv("ZOTERO_API_KEY", "")
ZOTERO_LIB_ID     = os.getenv("ZOTERO_LIB_ID", "")
ZOTERO_CLOUD_BASE = "https://api.zotero.org"

# PDF 成功关联到 Zotero（已导入其存储）后，是否删除 cnki_pdfs 暂存原件
_DELETE_AFTER_IMPORT = os.getenv("DELETE_PDF_AFTER_IMPORT", "true").strip().lower() in ("1", "true", "yes")

# 本地 connector 请求头
_CONN_HEADERS = {
    "Content-Type": "application/json",
    "X-Zotero-Connector-API-Version": "3",
    "User-Agent": "Mozilla/5.0 cnki-mcp",
}
_CLOUD_HEADERS = {
    "Zotero-API-Key": ZOTERO_API_KEY,
    "Zotero-API-Version": "3",
    "Content-Type": "application/json",
}


# ─── 元数据构造 ──────────────────────────────────────────────

def _build_item(paper: Dict) -> Dict:
    """将 CNKI 搜索结果转换为 Zotero journalArticle 格式。"""
    creators = []
    raw_authors = paper.get("authors", "")
    if raw_authors:
        for name in raw_authors.split(";"):
            name = name.strip()
            if name:
                creators.append({"creatorType": "author", "firstName": "", "lastName": name})

    item: Dict = {
        "itemType": "journalArticle",
        "title": paper.get("title", "").strip(),
        "creators": creators,
        "publicationTitle": paper.get("journal", "").strip(),
        "date": paper.get("year", "").strip(),
        "language": "zh-CN",
        "url": paper.get("url", "").strip(),
        "tags": [{"tag": "CNKI"}, {"tag": "cnki-mcp"}],
    }
    if paper.get("abstract"):
        item["abstractNote"] = paper["abstract"].strip()
    if paper.get("doi"):
        item["DOI"] = paper["doi"].strip()
    if paper.get("keywords"):
        for kw in str(paper["keywords"]).split(";"):
            kw = kw.strip()
            if kw:
                item["tags"].append({"tag": kw})
    return item


# ─── 本地 Connector ──────────────────────────────────────────

async def _connector_available(client: httpx.AsyncClient) -> bool:
    """检测 Zotero connector 是否在线。"""
    try:
        r = await client.post(
            f"{ZOTERO_LOCAL_API}/connector/ping",
            headers=_CONN_HEADERS, content=b"{}",
        )
        return r.status_code == 200
    except Exception:
        return False


async def _save_one_via_connector(client: httpx.AsyncClient, paper: Dict) -> Dict:
    """
    通过 connector 写入单篇条目，并在有本地 PDF 时上传关联。

    返回 {"ok": bool, "attached": bool, "detail": str}
    """
    session_id = str(uuid.uuid4())
    item_id = "item-" + session_id[:8]

    item = _build_item(paper)
    item["id"] = item_id  # connector 会话内的临时 id，供附件关联

    payload = {"sessionID": session_id, "items": [item], "uri": item.get("url") or "https://kns.cnki.net/"}
    r = await client.post(
        f"{ZOTERO_LOCAL_API}/connector/saveItems",
        headers=_CONN_HEADERS,
        content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    if r.status_code not in (200, 201):
        return {"ok": False, "attached": False, "detail": f"saveItems HTTP {r.status_code}: {r.text[:120]}"}

    # 有本地 PDF → 上传并关联
    pdf_path = paper.get("pdf_path")
    if pdf_path and Path(pdf_path).exists():
        await asyncio.sleep(0.3)  # 让父条目先落库
        attached = await _upload_attachment(client, session_id, item_id, pdf_path, item["title"], item.get("url", ""))
        if not attached:
            return {"ok": True, "attached": False, "detail": "已写入，PDF关联失败"}

        # 关联成功（PDF 已导入 Zotero 存储）→ 按需删除暂存原件
        detail = "已写入，PDF已关联"
        if _DELETE_AFTER_IMPORT:
            try:
                Path(pdf_path).unlink()
                detail += "，已清理暂存文件"
            except Exception as e:
                detail += f"，暂存文件删除失败({e})"
        return {"ok": True, "attached": True, "detail": detail}

    return {"ok": True, "attached": False, "detail": "已写入（无本地PDF）"}


async def _upload_attachment(
    client: httpx.AsyncClient,
    session_id: str,
    parent_id: str,
    pdf_path: str,
    title: str,
    source_url: str,
) -> bool:
    """通过 /connector/saveAttachment 上传 PDF 字节并关联到父条目。"""
    try:
        data = Path(pdf_path).read_bytes()
    except Exception:
        return False

    metadata = {
        "id": "attach-" + session_id[:8],
        "url": source_url or "https://kns.cnki.net/",
        "contentType": "application/pdf",
        "title": Path(pdf_path).name,
        "parentItemID": parent_id,
        "sessionID": session_id,
    }
    headers = {
        "Content-Type": "application/pdf",
        "X-Zotero-Connector-API-Version": "3",
        # 头部必须纯 ASCII：ensure_ascii=True 把中文转成 \uXXXX 转义
        "X-Metadata": json.dumps(metadata),
        "User-Agent": "Mozilla/5.0 cnki-mcp",
    }
    try:
        r = await client.post(
            f"{ZOTERO_LOCAL_API}/connector/saveAttachment",
            headers=headers, content=data,
        )
        return r.status_code in (200, 201)
    except Exception:
        return False


async def _import_via_connector(papers: List[Dict]) -> Dict:
    """通过本地 connector 批量导入（含 PDF 关联）。"""
    ok_count = 0
    attached_count = 0
    details = []
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        if not await _connector_available(client):
            return {"success": False, "count": 0, "attached": 0, "method": "connector", "detail": "connector 未就绪"}
        for p in papers:
            res = await _save_one_via_connector(client, p)
            if res["ok"]:
                ok_count += 1
            if res["attached"]:
                attached_count += 1
            details.append(res["detail"])

    return {
        "success": ok_count > 0,
        "count": ok_count,
        "attached": attached_count,
        "method": "connector",
        "detail": f"写入 {ok_count}/{len(papers)} 篇，PDF 关联 {attached_count} 篇",
    }


# ─── 云 API（降级，仅元数据）────────────────────────────────

async def _import_via_cloud_api(papers: List[Dict]) -> Dict:
    """通过 Zotero 云 API 写入元数据（不含 PDF）。"""
    if not ZOTERO_API_KEY or not ZOTERO_LIB_ID:
        return {"success": False, "count": 0, "attached": 0, "method": "cloud_api",
                "detail": "缺少 ZOTERO_API_KEY 或 ZOTERO_LIB_ID"}

    items = [_build_item(p) for p in papers]
    url = f"{ZOTERO_CLOUD_BASE}/users/{ZOTERO_LIB_ID}/items"
    body = json.dumps(items, ensure_ascii=False).encode("utf-8")
    # 云端用默认 trust_env=True，保留系统代理（外网可能需经代理访问 api.zotero.org）。
    # 本地 connector 才需 trust_env=False 绕过代理（见 _import_via_connector）。
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=_CLOUD_HEADERS, content=body)

    if r.status_code in (200, 201):
        n = len(r.json().get("success", {}))
        return {"success": True, "count": n, "attached": 0, "method": "cloud_api",
                "detail": f"云端写入 {n}/{len(items)} 篇（仅元数据，无PDF）"}
    return {"success": False, "count": 0, "attached": 0, "method": "cloud_api",
            "detail": f"HTTP {r.status_code}: {r.text[:200]}"}


# ─── 公共入口 ────────────────────────────────────────────────

async def import_papers(papers: List[Dict]) -> Dict:
    """
    导入论文到 Zotero。

    Args:
        papers: 论文列表。每篇可含可选字段 "pdf_path"（本地已下载的 PDF 路径），
                有则通过本地 connector 上传并关联为子附件。

    Returns:
        {"success": bool, "count": int, "attached": int, "method": str, "detail": str}
    """
    if not papers:
        return {"success": False, "count": 0, "attached": 0, "method": "none", "detail": "没有要导入的论文"}

    # 优先本地 connector（支持 PDF 关联）
    result = await _import_via_connector(papers)
    if result["success"]:
        return result

    # 降级云 API（仅元数据）
    local_err = result["detail"]
    cloud = await _import_via_cloud_api(papers)
    cloud["detail"] = f"本地connector不可用({local_err})，降级云API：{cloud['detail']}"
    return cloud
