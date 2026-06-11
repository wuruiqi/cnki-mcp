"""删除带 cnki-mcp-test 标签的测试条目。本地 /api 若不支持 DELETE 则提示手动删除。"""
import io
import sys
import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:23119"
c = httpx.Client(timeout=15, trust_env=False)
H = {"Zotero-API-Version": "3"}

r = c.get(BASE + "/api/users/0/items", headers=H, params={"tag": "cnki-mcp-test", "limit": 50})
items = r.json()
print("待清理测试条目:", len(items))
for it in items:
    key = it["data"]["key"]
    ver = it["version"]
    rd = c.delete(BASE + "/api/users/0/items/{}".format(key),
                  headers={"Zotero-API-Version": "3", "If-Unmodified-Since-Version": str(ver)})
    print("  DELETE {} -> {} {}".format(key, rd.status_code, rd.text[:80]))

c.close()
