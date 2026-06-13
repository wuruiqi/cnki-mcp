# cnki-mcp

[![CI](https://github.com/wuruiqi/cnki-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/wuruiqi/cnki-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)

> 把中国知网（CNKI）的**文献检索 → 双排序去重 → PDF 下载 → 导入 Zotero（含 PDF 自动关联）→ 元数据核对更新**封装成 MCP 工具，供 Claude 等 AI 助手一键调用。

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant search CNKI, download article PDFs, and import them into Zotero — with built-in deduplication, citation-based sorting, and PDF metadata reconciliation.

## ✨ 功能

- **多维排序检索**：分别按「发表时间」和「引用量」取前 N 篇，合并去重后作为工作集
- **两级去重**：(1) 两种排序结果间按标题去重；(2) 与 Zotero 已有文献对比，跳过已存在条目
- **引用量采集**：检索结果中自动提取每篇论文的引用次数（CNKI `td.quote`）
- **下载** 单篇或批量 PDF/CAJ 到本地
- **导入 Zotero**：优先本地 connector（`localhost:23119`），PDF 直接上传并关联为子附件；Zotero 未运行时降级云 API（仅元数据）
- **元数据核对与更新**：通过 PyMuPDF 提取 PDF 内嵌元数据（标题/作者/DOI），与 Zotero 条目比对生成差异表，用户确认后一键 PATCH 更新
- **登录态持久化**：Cookie 保存/恢复，几小时内免重复登录

## 🧰 MCP 工具

| 工具 | 说明 |
|------|------|
| `cnki_login_status` | 检查机构登录状态 |
| `cnki_open_login_page` | 打开登录页，等待手动完成机构登录并保存 Cookie |
| `cnki_save_cookies` | 手动保存当前 Cookie |
| `cnki_search` | 按关键词检索期刊论文（相关度排序，含引用量） |
| `cnki_download_pdf` | 下载单篇 PDF/CAJ |
| `cnki_import_to_zotero` | 把元数据列表导入 Zotero（可带 `pdf_path` 自动关联 PDF） |
| `cnki_batch` | 一键：多排序检索 → 去重 → 下载 → 导入 Zotero → 元数据差异预览 |
| `cnki_preview_metadata_updates` | 对指定 PDF 列表提取元数据，生成与现有数据的差异对比表 |
| `cnki_apply_metadata_updates` | 将用户确认的差异 PATCH 更新到 Zotero 条目 |

### cnki_batch 主要参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `top_n_by_time` | 50 | 按发表时间取前 N 篇（0 = 禁用此排序） |
| `top_n_by_citations` | 50 | 按引用量取前 N 篇（0 = 禁用此排序） |
| `check_zotero_dup` | True | 跳过 Zotero 中已有的文献 |
| `download_pdf` | True | 是否下载 PDF |
| `import_zotero` | True | 是否导入 Zotero |
| `download_interval_min` | 6.0 | 两篇之间最小间隔（秒），防风控 |
| `download_interval_max` | 12.0 | 两篇之间最大间隔（秒），随机化 |
| `captcha_wait` | 120 | 等待用户完成验证码的最长秒数；0 = 跳过 |

## 📦 环境要求

- Python **3.10+**（MCP SDK 要求）
- [Playwright](https://playwright.dev/python/) + 系统 Chrome（或内置 Chromium）
- 有效的 CNKI 机构访问权限（校园网/VPN/机构账号）
- 可选：Zotero 7+ 桌面端（用于 PDF 自动关联）
- 可选：Zotero API Key + Library ID（用于 Zotero 查重、元数据更新）

## 🚀 安装

### 方式 A：pip 安装（推荐，提供 `cnki-mcp` 命令）

```bash
pip install git+https://github.com/wuruiqi/cnki-mcp.git
python -m playwright install chromium   # 若无系统 Chrome
```

### 方式 B：克隆源码

```bash
git clone https://github.com/wuruiqi/cnki-mcp.git
cd cnki-mcp
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env                     # 按需修改配置
```

### 注册到 MCP 客户端

**pip 安装后**（最简洁）：

```json
{
  "mcpServers": {
    "cnki": { "type": "stdio", "command": "cnki-mcp" }
  }
}
```

**克隆源码方式**：

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

所有项均可选。详见 [.env.example](.env.example)。

| 变量 | 默认 | 说明 |
|------|------|------|
| `ZOTERO_LOCAL_API` | `http://127.0.0.1:23119` | Zotero 本地 connector 地址 |
| `ZOTERO_API_KEY` | — | Zotero Web API Key（Zotero 查重 + 元数据更新需要） |
| `ZOTERO_LIB_ID` | — | Zotero 用户/库 ID（同上） |
| `PDF_DIR` | `./downloads` | PDF 暂存目录 |
| `PROFILE_DIR` | `./.browser_profile` | 浏览器持久化目录 |
| `COOKIE_FILE` | `./.cnki_cookies.json` | Cookie 存储文件 |
| `DELETE_PDF_AFTER_IMPORT` | `true` | 成功关联 Zotero 后删除暂存 PDF |

> **提示**：若需在导入后用 `cnki_preview_metadata_updates` 核对 PDF 元数据，请先将 `DELETE_PDF_AFTER_IMPORT=false`，或直接使用 `cnki_batch` 返回结果中自动生成的 `metadata_preview`。

## 📖 典型使用流程

```
1. cnki_login_status              → 检查登录态
2. cnki_open_login_page           → 机构登录（如需）
3. cnki_batch "螺旋推进 散粒体"    → 检索+排序+去重+下载+导入
   ↳ 返回 metadata_preview        → 查看 PDF 与 CNKI 元数据差异
4. cnki_apply_metadata_updates    → 确认后更新 Zotero 条目
```

## ⚠️ 说明与限制

- **PDF 自动关联需 Zotero 桌面端在运行**；未运行则降级为仅写元数据。
- **`cnki_apply_metadata_updates` 需要 Zotero 云 API**（在 `.env` 中配置 `ZOTERO_API_KEY` + `ZOTERO_LIB_ID`）。
- CNKI 每页约显示 20 条，`top_n > 20` 时实际返回数量受限（分页支持规划中）。
- 若系统配置了 HTTP 代理，访问 Zotero 本地端口已通过 `httpx(trust_env=False)` 处理。
- **CNKI 验证码（CAPTCHA）**：批量下载时如触发人机验证，下载将自动暂停并在控制台打印提示，请在保持打开的浏览器窗口中手动完成滑块验证后继续（等待上限 `captcha_wait` 秒，默认 120 秒）。浏览器须保持可见（`headless=False`，默认已满足）。
- 仅供个人学习研究用途，请遵守 CNKI 服务条款与所在机构的使用规定。

## 🛠 开发

```bash
pytest tests/test_unit.py -v    # 离线单元测试（19 个用例）
```

诊断脚本见 [`tests/`](tests/)（`inspect_*` 检查 DOM 选择器，`probe_*` 测试 Zotero 端点）。
实测要点与 2026 改版适配记录见 [CLAUDE.md](CLAUDE.md)。

## License

[MIT](LICENSE)
