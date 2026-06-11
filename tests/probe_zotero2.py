"""绕过代理探测 Zotero 端点，并判断版本/local API 是否启用。"""
import io
import sys
import socket
import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:23119"


def probe(client, method, path, headers=None, body=None, note=""):
    try:
        if method == "GET":
            r = client.get(BASE + path, headers=headers)
        else:
            r = client.post(BASE + path, headers=headers, content=body)
        txt = r.text[:250].replace("\n", " ")
        print("  [{}] {} {} -> {}  {}".format(method, path, note, r.status_code, txt))
        return r
    except Exception as e:
        print("  [{}] {} {} -> 异常: {}".format(method, path, note, e))
        return None


# 先看原始 socket 能否连上（彻底排除代理）
print("===== 0. 原始 TCP 连接测试 =====")
try:
    s = socket.create_connection(("127.0.0.1", 23119), timeout=4)
    s.sendall(b"GET /connector/ping HTTP/1.1\r\nHost: 127.0.0.1:23119\r\nX-Zotero-Connector-API-Version: 3\r\nConnection: close\r\n\r\n")
    data = s.recv(2048)
    s.close()
    print("  原始响应:", repr(data[:300]))
except Exception as e:
    print("  TCP 失败:", e)

# trust_env=False 彻底禁用代理
print("\n===== 1. httpx (trust_env=False, 无代理) =====")
with httpx.Client(timeout=5, trust_env=False) as c:
    conn_headers = {"Content-Type": "application/json", "X-Zotero-Connector-API-Version": "3"}
    probe(c, "GET", "/connector/ping", conn_headers, None, "ping")
    probe(c, "POST", "/connector/ping", conn_headers, b"{}", "ping-POST")
    api_headers = {"Zotero-API-Version": "3"}
    probe(c, "GET", "/api/", api_headers, None, "api根")
    probe(c, "GET", "/api/users/0/collections?limit=3", api_headers, None, "collections")

print("\n完成")
