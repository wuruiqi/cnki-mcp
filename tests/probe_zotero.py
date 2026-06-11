"""探测 Zotero 本地 API / Connector 端点，确定可用的导入与附件方式。"""
import io
import sys
import json
import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://localhost:23119"


def probe(method, path, headers=None, body=None, note=""):
    url = BASE + path
    try:
        with httpx.Client(timeout=5) as c:
            if method == "GET":
                r = c.get(url, headers=headers)
            else:
                r = c.post(url, headers=headers, content=body)
        txt = r.text[:200].replace("\n", " ")
        print("  [{}] {} {} -> {}  {}".format(method, path, note, r.status_code, txt))
        return r
    except Exception as e:
        print("  [{}] {} {} -> 异常: {}".format(method, path, note, e))
        return None


print("===== 1. Connector 端点（浏览器插件协议）=====")
conn_headers = {
    "Content-Type": "application/json",
    "X-Zotero-Connector-API-Version": "3",
    "User-Agent": "Mozilla/5.0 Zotero-Connector",
}
probe("POST", "/connector/ping", conn_headers, b"{}", "ping")
probe("GET", "/connector/ping", conn_headers, None, "ping-GET")
# 获取当前选中的 collection / library 信息
probe("POST", "/connector/getSelectedCollection", conn_headers, b"{}", "选中收藏夹")

print("\n===== 2. Zotero 7 本地 API（/api，模拟 web API）=====")
api_headers = {"Zotero-API-Version": "3"}
r = probe("GET", "/api/", api_headers, None, "根")
# 用户库 ID
r = probe("GET", "/api/users/0/collections?limit=3", api_headers, None, "collections")
probe("GET", "/api/users/0/items?limit=1", api_headers, None, "items")

print("\n===== 完成 =====")
