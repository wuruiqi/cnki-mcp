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
import re
import uuid
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Set

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

    # 合并默认 tag 与 paper 自带 tag
    default_tags = [{"tag": "CNKI"}, {"tag": "cnki-mcp"}]
    extra_tags = paper.get("tags", [])
    merged_tags = {t["tag"]: t for t in (default_tags + extra_tags)}.values()

    item: Dict = {
        "itemType": "journalArticle",
        "title": paper.get("title", "").strip(),
        "creators": creators,
        "publicationTitle": paper.get("journal", "").strip(),
        "date": paper.get("year", "").strip(),
        "language": "zh-CN",
        "url": paper.get("url", "").strip(),
        "tags": list(merged_tags),
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
    # 收藏夹：_collection_key 是内部字段，不是论文元数据
    if paper.get("_collection_key"):
        item["collections"] = [paper["_collection_key"]]
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


# ─── Zotero 查重 ─────────────────────────────────────────────

async def get_existing_titles() -> Set[str]:
    """
    从 Zotero 获取已有期刊文章的标题集合（归一化），用于导入前去重。

    优先本地 API，失败时降级云 API。若两者均不可用返回空集合（不阻断导入流程）。
    标题归一化方式：去掉空白字符后转小写。
    """
    titles: Set[str] = set()

    def _normalize(t: str) -> str:
        return re.sub(r"\s+", "", t).lower()

    def _collect(items: list) -> None:
        for item in items:
            t = item.get("data", {}).get("title", "")
            if t:
                titles.add(_normalize(t))

    # 本地 API（只读，无需认证）
    if ZOTERO_LIB_ID:
        try:
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                r = await client.get(
                    f"{ZOTERO_LOCAL_API}/api/users/{ZOTERO_LIB_ID}/items",
                    headers={"Zotero-API-Version": "3"},
                    params={"itemType": "journalArticle", "limit": 500},
                )
                if r.status_code == 200:
                    _collect(r.json())
                    return titles
        except Exception:
            pass

    # 云 API 降级
    if ZOTERO_API_KEY and ZOTERO_LIB_ID:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    f"{ZOTERO_CLOUD_BASE}/users/{ZOTERO_LIB_ID}/items",
                    headers=_CLOUD_HEADERS,
                    params={"itemType": "journalArticle", "limit": 500},
                )
                if r.status_code == 200:
                    _collect(r.json())
        except Exception:
            pass

    return titles


def filter_new_papers(papers: List[Dict], existing_titles: Set[str]) -> Dict:
    """
    从 papers 中过滤掉已在 Zotero 库中的文献。

    Returns:
        {"new": List[Dict], "skipped": List[str], "removed": int}
    """
    def _norm(t: str) -> str:
        return re.sub(r"\s+", "", t).lower()

    new_papers: List[Dict] = []
    skipped: List[str] = []

    for p in papers:
        key = _norm(p.get("title", ""))
        if key and key in existing_titles:
            skipped.append(p.get("title", ""))
        else:
            new_papers.append(p)

    return {
        "new": new_papers,
        "skipped": skipped,
        "removed": len(skipped),
    }


# ─── Zotero 元数据更新 ───────────────────────────────────────

async def find_zotero_item_by_title(title: str) -> Optional[Dict]:
    """
    通过标题在 Zotero 云 API 中搜索条目，返回第一个匹配结果（含 key 和 version）。
    依赖 ZOTERO_API_KEY 和 ZOTERO_LIB_ID。
    """
    if not ZOTERO_API_KEY or not ZOTERO_LIB_ID:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{ZOTERO_CLOUD_BASE}/users/{ZOTERO_LIB_ID}/items",
                headers=_CLOUD_HEADERS,
                params={"q": title, "itemType": "journalArticle", "limit": 5},
            )
            if r.status_code == 200:
                items = r.json()
                if items:
                    return items[0]
    except Exception:
        pass
    return None


async def create_zotero_collection(name: str, parent_key: Optional[str] = None) -> Optional[str]:
    """
    在 Zotero 库中创建收藏夹，返回新收藏夹 key。
    依赖云 API（需 ZOTERO_API_KEY + ZOTERO_LIB_ID）。
    若同名收藏夹已存在则返回其 key；凭据缺失返回 None。
    """
    if not ZOTERO_API_KEY or not ZOTERO_LIB_ID:
        return None

    payload: Dict = {"name": name, "parentCollection": parent_key or False}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{ZOTERO_CLOUD_BASE}/users/{ZOTERO_LIB_ID}/collections",
                headers=_CLOUD_HEADERS,
                content=json.dumps([payload]).encode("utf-8"),
            )
        if r.status_code in (200, 201):
            keys = list(r.json().get("success", {}).values())
            return keys[0] if keys else None
        if r.status_code == 409:
            return await _find_collection_key(name)
    except Exception:
        pass
    return None


async def _find_collection_key(name: str) -> Optional[str]:
    """在 Zotero 收藏夹列表中查找同名收藏夹，返回其 key。"""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{ZOTERO_CLOUD_BASE}/users/{ZOTERO_LIB_ID}/collections",
                headers=_CLOUD_HEADERS,
                params={"limit": 100},
            )
        if r.status_code == 200:
            for col in r.json():
                if col.get("data", {}).get("name") == name:
                    return col.get("key")
    except Exception:
        pass
    return None


async def update_zotero_item(item_key: str, version: int, fields: Dict) -> Dict:
    """
    通过 Zotero 云 API PATCH 更新已有条目的元数据字段。

    Args:
        item_key: Zotero 条目 key（8 位字母数字）
        version:  条目当前版本号（乐观锁，防并发冲突）
        fields:   要更新的字段字典，如 {"title": ..., "DOI": ..., "creators": [...]}

    Returns:
        {"success": bool, "detail": str}
    """
    if not ZOTERO_API_KEY or not ZOTERO_LIB_ID:
        return {"success": False, "detail": "缺少 ZOTERO_API_KEY 或 ZOTERO_LIB_ID，无法更新"}

    url = f"{ZOTERO_CLOUD_BASE}/users/{ZOTERO_LIB_ID}/items/{item_key}"
    headers = {
        **_CLOUD_HEADERS,
        "If-Unmodified-Since-Version": str(version),
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.patch(
                url,
                headers=headers,
                content=json.dumps(fields, ensure_ascii=False).encode("utf-8"),
            )
        if r.status_code == 204:
            return {"success": True, "detail": f"条目 {item_key} 已更新"}
        if r.status_code == 412:
            return {"success": False, "detail": f"版本冲突（条目已被修改），请重新获取版本号后重试"}
        return {"success": False, "detail": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"success": False, "detail": f"请求失败: {e}"}
