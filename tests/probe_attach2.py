"""测试 connector 二进制附件上传：PDF 字节入 body，元数据入 X-Metadata 头。"""
import io
import sys
import json
import uuid
import os
import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:23119"
PDF = os.environ.get("TEST_PDF", "")  # 设为本地任意 PDF 的绝对路径以测试附件上传

c = httpx.Client(timeout=60, trust_env=False)
CH = {"Content-Type": "application/json", "X-Zotero-Connector-API-Version": "3", "User-Agent": "Mozilla/5.0"}

sid = str(uuid.uuid4())

# 1. 建父条目
print("===== 1. saveItems 建父条目 (sessionID={}) =====".format(sid[:8]))
item = {
    "itemType": "journalArticle",
    "title": "【测试C】二进制附件上传",
    "creators": [{"creatorType": "author", "firstName": "", "lastName": "张文静"}],
    "publicationTitle": "粮食与饲料工业",
    "date": "2024",
    "tags": [{"tag": "cnki-mcp-test"}],
    "id": "ITEM_C_1",
}
payload = {"sessionID": sid, "items": [item], "uri": "https://kns.cnki.net/"}
r = c.post(BASE + "/connector/saveItems", headers=CH,
           content=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
print("saveItems 状态:", r.status_code)

# 2. 上传 PDF 二进制
print("\n===== 2. saveAttachment 上传 PDF 字节 =====")
data = open(PDF, "rb").read()
print("PDF 大小:", len(data))
metadata = {
    "id": "ATTACH_C_1",
    "url": "https://kns.cnki.net/test.pdf",
    "contentType": "application/pdf",
    "title": os.path.basename(PDF),
    "parentItemID": "ITEM_C_1",
    "sessionID": sid,
}
for endpoint in ["/connector/saveAttachment", "/connector/saveStandaloneAttachment"]:
    print("\n--- 尝试 {} ---".format(endpoint))
    headers = {
        "Content-Type": "application/pdf",
        "X-Zotero-Connector-API-Version": "3",
        "X-Metadata": json.dumps(metadata),  # ensure_ascii=True → 头部纯 ASCII
        "User-Agent": "Mozilla/5.0",
    }
    try:
        r = c.post(BASE + endpoint, headers=headers, content=data)
        print("状态:", r.status_code, "响应:", r.text[:300])
    except Exception as e:
        print("异常:", e)

c.close()
