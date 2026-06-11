"""查询 Zotero 最近条目及附件，验证写入与 PDF 关联。"""
import io
import sys
import json
import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:23119"
c = httpx.Client(timeout=15, trust_env=False)
H = {"Zotero-API-Version": "3"}

# 按标签筛测试条目
r = c.get(BASE + "/api/users/0/items", headers=H, params={"tag": "cnki-mcp-test", "limit": 20})
items = r.json()
print("找到带 cnki-mcp-test 标签的条目:", len(items))
for it in items:
    d = it["data"]
    print("\n● [{}] {}".format(d.get("itemType"), d.get("title", "")[:40]))
    print("   key:", d["key"], " 子条目数:", it["meta"].get("numChildren", 0))
    # 查子附件
    if it["meta"].get("numChildren", 0) > 0:
        rc = c.get(BASE + "/api/users/0/items/{}/children".format(d["key"]), headers=H)
        for ch in rc.json():
            cd = ch["data"]
            print("   └─ 附件: [{}] {} | linkMode={} | filename={}".format(
                cd.get("contentType"), cd.get("title", "")[:30],
                cd.get("linkMode"), cd.get("filename")))

c.close()
