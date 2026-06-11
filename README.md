# cnki-mcp

> 把中国知网（CNKI）的**文献检索 → PDF 下载 → 导入 Zotero（自动迁移并关联 PDF）**封装成 MCP 工具，供 Claude 等 AI 助手一键调用。

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant search CNKI (China National Knowledge Infrastructure), download article PDFs, and import them into Zotero with the PDF automatically attached.

## ✨ 功能

- **检索** CNKI 学术期刊/学位论文（表单交互，绕开失效的 URL 参数检索）
- **下载** 单篇或批量 PDF/CAJ 到本地
- **导入 Zotero**：优先本地 connector（`localhost:23119`），把 PDF 直接上传并关联为子附件；Zotero 未运行时降级云 API（仅元数据）
- **登录态持久化**：Cookie 保存/恢复，几小时内免重复登录
- **一键批量**：`cnki_batch` 串起 检索→下载→导入→清理暂存

## 🧰 MCP 工具

| 工具 | 说明 |
|------|------|
| `cnki_login_status` | 检查机构登录状态 |
| `cnki_open_login_page` | 打开登录页，等待手动完成机构登录并保存 Cookie |
| `cnki_save_cookies` | 手动保存当前 Cookie |
| `cnki_search` | 按关键词检索期刊论文 |
| `cnki_download_pdf` | 下载单篇 PDF/CAJ |
| `cnki_import_to_zotero` | 把元数据列表导入 Zotero（可带 `pdf_path` 自动关联 PDF） |
| `cnki_batch` | 一键：检索 → 下载 → 导入 Zotero |

## 📦 环境要求

- Python **3.10+**（MCP SDK 要求）
- [Playwright](https://playwright.dev/python/) + 系统 Chrome（或内置 Chromium）
- 有效的 CNKI 机构访问权限（校园网/VPN/机构账号）
- 可选：Zotero 7+ 桌面端（用于 PDF 自动关联）

## 🚀 安装

```bash
git clone https://github.com/<your-account>/cnki-mcp.git
cd cnki-mcp
pip install -r requirements.txt
python -m playwright install chromium   # 若无系统 Chrome
cp .env.example .env                     # 按需修改配置
```

### 注册到 MCP 客户端

以 Claude Code 的 `.mcp.json` 为例：

```json
{
  "mcpServers": {
    "cnki": {
      "type": "stdio",
      "command": "python",
      "args": ["/abs/path/to/cnki-mcp/server.py"]
    }
  }
}
```

## ⚙️ 配置（.env）

所有项均可选，路径默认相对项目根目录。详见 [.env.example](.env.example)。

| 变量 | 默认 | 说明 |
|------|------|------|
| `ZOTERO_LOCAL_API` | `http://127.0.0.1:23119` | Zotero 本地 connector 地址 |
| `ZOTERO_API_KEY` / `ZOTERO_LIB_ID` | — | 仅离线降级到云 API 时需要 |
| `PDF_DIR` | `./downloads` | PDF 暂存目录 |
| `PROFILE_DIR` | `./.browser_profile` | 浏览器持久化目录 |
| `COOKIE_FILE` | `./.cnki_cookies.json` | Cookie 存储文件 |
| `DELETE_PDF_AFTER_IMPORT` | `true` | 成功关联 Zotero 后删除暂存 PDF |

## 📖 使用流程

1. `cnki_login_status` 查登录态；未登录则 `cnki_open_login_page`，在弹出的浏览器里完成机构登录（机构登录 → 校外登录 → 学校 → 账号密码 → 接受条款），脚本自动存 Cookie。
2. `cnki_search "粮情监测 物联网"` 检索。
3. `cnki_batch "粮情监测 物联网"` 一键检索+下载+导入 Zotero。

## ⚠️ 说明与限制

- **PDF 自动关联需 Zotero 桌面端在运行**（走本地 connector）；未运行则降级为仅写元数据。
- 若系统装了本地代理（如 `127.0.0.1:1080`），访问 Zotero 本地端口需绕过代理 —— 本项目已用 `httpx(trust_env=False)` 处理。
- 仅供个人学习研究用途，请遵守 CNKI 服务条款与所在机构的使用规定。

## 🛠 开发

诊断脚本见 [`tests/`](tests/)（`inspect_*` / `probe_*`）：CNKI 改版导致选择器失配时，运行它们 dump 实时 DOM 重新定位。实测要点记录在 [CLAUDE.md](CLAUDE.md)。

## License

[MIT](LICENSE)
