"""查最近导入的 cnki-mcp 条目及 PDF 附件。"""
import io, sys, httpx
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:23119"
c = httpx.Client(timeout=15, trust_env=False)
H = {"Zotero-API-Version": "3"}
r = c.get(BASE + "/api/users/0/items/top", headers=H, params={"tag": "cnki-mcp", "limit": 10, "sort": "dateAdded", "direction": "desc"})
items = r.json()
print("最近 cnki-mcp 条目:", len(items))
for it in items:
    d = it["data"]; m = it["meta"]
    print("\n● [{}] {}".format(d.get("itemType"), d.get("title","")[:38]))
    print("   {} | {} | 子条目:{}".format(d.get("date"), d.get("publicationTitle","")[:20], m.get("numChildren",0)))
    if m.get("numChildren",0) > 0:
        rc = c.get(BASE + "/api/users/0/items/{}/children".format(d["key"]), headers=H)
        for ch in rc.json():
            cd = ch["data"]
            print("   └─ [{}] {} | linkMode={}".format(cd.get("contentType"), (cd.get("filename") or cd.get("title",""))[:40], cd.get("linkMode")))
c.close()
