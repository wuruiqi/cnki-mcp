# cnki-mcp — CNKI 文献检索 MCP 服务器

## 项目概述
将 CNKI（中国知网）检索、PDF 下载、Zotero 导入功能封装为 MCP 工具，供 Claude 等 AI 助手调用。

## 运行环境
- Python **3.10+**（建议使用独立虚拟环境）
- 启动命令：`python server.py`（或 pip 安装后 `cnki-mcp`）

## 项目结构
```
cnki-mcp/
├── server.py          # MCP 服务器入口（FastMCP；main() 供 cnki-mcp 命令调用）
├── pyproject.toml     # 打包配置（pip/uvx 安装，console 入口 cnki-mcp）
├── cnki/
│   ├── __init__.py
│   ├── browser.py     # 浏览器会话管理（Playwright，Cookie 持久化）
│   ├── search.py      # CNKI 搜索（表单交互：填 #txt_search 点 .search-btn）
│   ├── download.py    # PDF/CAJ 下载（点 #pdfDown / #cajDown 触发 download）
│   └── zotero.py      # Zotero 导入（本地 connector + 云 API 兜底）
├── tests/             # 测试 + 诊断脚本（inspect_*/probe_*）
├── .env.example       # 配置模板（复制为 .env 后填写；.env 不提交）
└── requirements.txt
```

## MCP 工具列表
| 工具 | 说明 |
|------|------|
| `cnki_login_status` | 检查当前登录状态 |
| `cnki_open_login_page` | 打开登录页，供用户手动完成机构登录 |
| `cnki_save_cookies` | 登录后保存 Cookie（下次自动恢复） |
| `cnki_search` | 按关键词搜索 CNKI 期刊论文 |
| `cnki_download_pdf` | 下载单篇 PDF |
| `cnki_batch` | 批量搜索 + 下载 + 导入 Zotero |
| `cnki_import_to_zotero` | 将元数据列表导入 Zotero |

## 重要规范
- **Playwright 用异步 API**（`playwright.async_api`），与 MCP async 兼容
- 浏览器默认 `headless=False`，用户可见
- Cookie 存储于 `COOKIE_FILE`（默认项目根目录 `.cnki_cookies.json`）
- PDF 暂存于 `PDF_DIR`（默认 `./downloads`，可在 .env 覆盖）
- Zotero 优先用本地 connector（端口 23119，含 PDF 关联），失败则降级云 API（仅元数据）

## Zotero 本地导入机制（2026 实测，关键）
- **访问本地端口用 `httpx(trust_env=False)`**：若系统配置了 HTTP 代理，可能把
  localhost 请求也代理出去（典型表现：返回 502）。`trust_env=False` 绕过代理直连本地端口。
- `/api/*` 本地 API **只读**（POST 返回 "Endpoint does not support method"，DELETE 返回 501），
  只能用来查询/验证，**不能写入**。
- **写入走 connector**：
  1. `POST /connector/saveItems` `{sessionID, items:[{...,"id":"x"}], uri}` 建父条目（返回 201 空体）
  2. `POST /connector/saveAttachment` 上传 PDF 字节关联：
     - body = PDF 原始字节，`Content-Type: application/pdf`
     - `X-Metadata` 头 = ASCII JSON（**必须 `json.dumps(ensure_ascii=True)`**，中文转 \\uXXXX，
       否则 HTTP 头非 ASCII 报错），含 `sessionID`(同上) + `parentItemID`(=父条目的 id)
  - 成功后 PDF 以 `linkMode=imported_url` 导入 Zotero 存储（是否云同步由 Zotero 设置决定）。
- 探测脚本：`tests/probe_zotero2.py`(端点)、`tests/probe_connector.py`(写元数据)、
  `tests/probe_attach2.py`(传附件)、`tests/check_recent.py`(验证)。

## 注册到 .mcp.json
```json
"cnki": { "type": "stdio", "command": "cnki-mcp" }
```
（pip 安装后用 `cnki-mcp` 命令；源码方式则 `"command": "python", "args": ["/abs/path/server.py"]`）

## 2026 实测要点（CNKI 改版后，调试时优先核对）
- **检索必须走表单**：旧版 `SKey`/`dbcode` GET 参数已失效（落到空检索页或 404）。
  正确流程：打开 `https://kns.cnki.net/kns8s/` → 填 `input#txt_search` → 点 `input.search-btn`
  → 跳转 `kns8s/search?kw=...&korder=SU` 结果页。
- **结果行选择器**：`.result-table-list tbody tr`；字段 `td.name a`(标题/href)、
  `td.author`(作者)、`td.source`(期刊)、`td.date`(日期 YYYY-MM-DD)。
- **登录判定**：只看可见文字里有无"机构登录"（机构登录成功后被机构名替换）。
  "个人登录"是独立的个人账号登录，机构登录后仍在，**不能**当未登录信号。
- **下载按钮**：`a#pdfDown`(PDF) / `a#cajDown`(CAJ)，href 指向 `bar.cnki.net/bar/download/order`，
  点击触发浏览器 download 事件。
- **诊断脚本**：`tests/inspect_*.py`（search/form/row/detail/page）可单独运行 dump 实时 DOM，
  选择器失配时先跑它们重新定位。

## 已知限制
- **PDF 自动关联需 Zotero 桌面端运行**（走本地 connector）。Zotero 未开时降级云 API，
  只写元数据、不带 PDF。
- PDF 关联后 Zotero 存了自己的副本（`imported_url`）。默认会**自动删除**
  `PDF_DIR` 里的暂存原件（`DELETE_PDF_AFTER_IMPORT=false` 可关闭保留）。
  仅在「成功关联」后才删，关联失败或无 PDF 不动文件。
- 搜索的"学术期刊"类型限定为 best-effort，总库结果可能混入学位论文。
