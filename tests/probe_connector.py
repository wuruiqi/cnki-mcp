"""测试 connector API 写入条目 + 附件的可行路径。"""
import io
import sys
import json
import uuid
import os
import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:23119"
PDF = r"D:\qq\zotero\cnki_pdfs\基于动态高分辨图像的粮仓玉米温度变化监测方法.pdf"

c = httpx.Client(timeout=30, trust_env=False)
H = {
    "Content-Type": "application/json",
    "X-Zotero-Connector-API-Version": "3",
    "User-Agent": "Mozilla/5.0",
}


def save_items(items, session_id, uri="https://kns.cnki.net/"):
    payload = {"sessionID": session_id, "items": items, "uri": uri}
    r = c.post(BASE + "/connector/saveItems", headers=H,
               content=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return r


# ── 测试 A：纯元数据写入 ──
print("===== A. connector 纯元数据写入 =====")
sid_a = str(uuid.uuid4())
item_a = {
    "itemType": "journalArticle",
    "title": "【测试A】connector纯元数据写入",
    "creators": [{"creatorType": "author", "firstName": "", "lastName": "测试作者"}],
    "publicationTitle": "测试期刊",
    "date": "2024",
    "tags": [{"tag": "cnki-mcp-test"}],
}
r = save_items([item_a], sid_a)
print("状态:", r.status_code)
print("响应:", r.text[:500])

# ── 测试 B：带 file:/// 本地附件 ──
print("\n===== B. connector + file:/// 本地附件 =====")
sid_b = str(uuid.uuid4())
file_uri = "file:///" + PDF.replace("\\", "/")
print("file URI:", file_uri)
item_b = {
    "itemType": "journalArticle",
    "title": "【测试B】connector带本地PDF附件",
    "creators": [{"creatorType": "author", "firstName": "", "lastName": "张文静"}],
    "publicationTitle": "粮食与饲料工业",
    "date": "2024",
    "tags": [{"tag": "cnki-mcp-test"}],
    "attachments": [{
        "title": "全文PDF",
        "mimeType": "application/pdf",
        "url": file_uri,
        "snapshot": False,
    }],
}
r = save_items([item_b], sid_b)
print("状态:", r.status_code)
print("响应:", r.text[:500])

c.close()
print("\n>>> 请在 Zotero 中查看是否出现测试A/B 条目，B 是否带 PDF 附件")
