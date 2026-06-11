"""测试通过 Zotero 本地 API 创建条目 + 上传 PDF 附件的完整流程。"""
import io
import sys
import json
import hashlib
import os
import time
import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:23119"
LIB = "0"  # 本地 API 用 0 指代当前用户库
PDF = os.environ.get("TEST_PDF", "")  # 设为本地任意 PDF 的绝对路径以测试附件上传

c = httpx.Client(timeout=15, trust_env=False)


def post_json(path, payload, headers=None):
    h = {"Zotero-API-Version": "3", "Content-Type": "application/json"}
    if headers:
        h.update(headers)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    r = c.post(BASE + path, headers=h, content=body)
    return r


# ── 1. 创建父条目 ──
print("===== 1. 创建父条目 =====")
parent = {
    "itemType": "journalArticle",
    "title": "【测试】粮仓PDF附件关联验证",
    "creators": [{"creatorType": "author", "firstName": "", "lastName": "张文静"}],
    "publicationTitle": "粮食与饲料工业",
    "date": "2024",
    "tags": [{"tag": "cnki-mcp-test"}],
}
r = post_json("/api/users/{}/items".format(LIB), [parent])
print("状态:", r.status_code)
print("原始响应:", r.text[:600])
if r.status_code >= 400:
    sys.exit("父条目创建失败，先解决这个再继续")
resp = r.json()
print(json.dumps(resp, ensure_ascii=False)[:400])
parent_key = resp["successful"]["0"]["key"] if "successful" in resp else resp["success"]["0"]
print("父条目 key:", parent_key)

# ── 2. 创建子附件条目（imported_file）──
print("\n===== 2. 创建附件条目 =====")
filename = os.path.basename(PDF)
attach = {
    "itemType": "attachment",
    "linkMode": "imported_file",
    "parentItem": parent_key,
    "title": filename,
    "filename": filename,
    "contentType": "application/pdf",
}
r = post_json("/api/users/{}/items".format(LIB), [attach])
print("状态:", r.status_code)
resp = r.json()
print(json.dumps(resp, ensure_ascii=False)[:400])
attach_key = resp["successful"]["0"]["key"] if "successful" in resp else resp["success"]["0"]
print("附件 key:", attach_key)

# ── 3. 文件上传授权 ──
print("\n===== 3. 文件上传授权 =====")
data = open(PDF, "rb").read()
md5 = hashlib.md5(data).hexdigest()
filesize = len(data)
mtime = int(os.path.getmtime(PDF) * 1000)
print("md5={} size={} mtime={}".format(md5, filesize, mtime))

form = "md5={}&filename={}&filesize={}&mtime={}".format(md5, httpx.QueryParams({"f": filename})['f'], filesize, mtime)
# 用标准表单编码
from urllib.parse import urlencode
form = urlencode({"md5": md5, "filename": filename, "filesize": filesize, "mtime": mtime})
r = c.post(
    BASE + "/api/users/{}/items/{}/file".format(LIB, attach_key),
    headers={"Zotero-API-Version": "3", "Content-Type": "application/x-www-form-urlencoded", "If-None-Match": "*"},
    content=form.encode("utf-8"),
)
print("授权状态:", r.status_code)
print("授权响应:", r.text[:400])

c.close()
