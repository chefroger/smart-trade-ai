# Security Policy

## HERMES_YOLO_MODE

Smart Trade AI 在启动时通过 `trade/bootstrap.py` 自动设置 `HERMES_YOLO_MODE=true`。
AI Agent 工具调用（文件读写、终端命令等）**无需人工审批**。

### Why

The target users are international trade salespeople who cannot evaluate whether
an AI tool call is safe. Prompting them for approval on every action would make
the product unusable.

### Mitigations

1. **Network isolation**: Bind to `127.0.0.1` only. Do not expose to LAN/WAN. 该限制**可以**通过设置环境变量 `TRADE_ALLOW_REMOTE_UI=1` 显式解除（`trade/app.py:_remote_ui_allowed()`）；解除后任何能访问该端口的设备都能取得 session token 并调用全部 API，**会降低安全性**。
2. **Session token**: 32 字节 url-safe 随机 token（`secrets.token_urlsafe(32)`），`secrets.compare_digest` 时序安全比较。注入前端 HTML，所有 API 需携带。
3. **Session-company binding**: 首次请求自动绑定 session 到 company_id，跨公司操作返回 403。切换需通过显式端点。
4. **CDN SRI**: 前端外部脚本（marked.js、DOMPurify）有 integrity 哈希校验。
5. **SSRF 防护**: `osint/constants.py::_is_private_host()` 统一拦截 8 个内网/保留 IP 段（RFC1918、loopback、link-local、multicast）。`http_get()` 和 `detect_tech_stack()` 共享复用，无重复实现。
6. **PID 三层校验**: 重启时 psutil（强制依赖）验证 cmdline + exe 路径比对 + pid 文件 0600 权限。macOS 无 /proc 也无 psutil 时信任自己的 PID 文件做兜底。
7. **系统端点限流**: `/system/update`、`/system/restart`、`/system/backup`、`/skills/update` 均限制 5 req/min per token，防止脚本循环触发 GitHub API 限流或 pip 配额耗尽。
8. **X-Confirm-Delete**: 删除公司需要确认 header。
9. **SQL 全参数化**: 所有查询使用 `?` 占位符，无 f-string 拼接。
10. **路径穿越防护**: slug/root_path/文件名均校验 `..`、`/`、NUL。
11. **API Key safety**: Store in `~/.hermes/.env` with `chmod 600`.
12. **Regular backups**: Back up `~/.trade/` and desktop work directories.
13. **Least privilege**: Run as a regular user, never as root.

### If you find a vulnerability

Please open a GitHub Issue with:
- Steps to reproduce
- Affected version
- Impact assessment

We do not currently run a bug bounty program.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.6.x   | ✅ Active |
| 0.5.x   | ⚠️ Security fixes only |
| < 0.5   | ❌ Unsupported |

## 法律与合规声明

### 第三方服务使用风险

本软件集成了以下第三方工具，使用前请注意相关条款：

**holehe（邮箱平台注册检测）**
- `email_intel.py` 通过 holehe 检测邮箱在 120+ 网站的注册情况
- GitHub、LinkedIn、Twitter 等平台的服务条款（ToS）通常禁止自动化查询
- 建议：仅对单个业务联系人做背调，不要用于大规模批量查询
- 如被平台检测到异常流量，可能面临封号或法律风险

**OFAC/UN/EU 制裁名单查询**
- `osint/sanctions.py` 从 ofac.treasury.gov 等政府网站下载制裁数据
- 美国政府数据属于 Public Domain，无版权问题
- 制裁名单结果仅供参考，不构成法律意见
- 建议拒绝与制裁名单上的实体交易，必要时咨询法律部门

**WHOIS / DNS 查询**
- `osint/whois.py` 和 `osint/email_verify.py` 使用 IETF 标准协议
- 部分 WHOIS 服务器（如 .cn）禁止自动化查询，请合理控制频率
- DNS 查询使用公共 DNS 服务器（8.8.8.8 / 1.1.1.1），受各服务商 ToS 约束

### 许可证兼容性

| 组件 | 许可证 | 兼容性 |
|------|--------|:------:|
| Smart Trade AI | AGPL-3.0-only | — |
| Hermes Agent | MIT | ✅ 完全兼容 |
| FastAPI / uvicorn / beautifulsoup4 | MIT / BSD | ✅ 完全兼容 |
| PyMuPDF | AGPL | ⚠️ pip install 使用无传染风险；PyInstaller 打包分发时需评估 |
| openpyxl / python-docx / python-pptx | MIT | ✅ 完全兼容 |

### 数据合规

- 所有用户数据存储在本地（`~/.trade/`），不上传任何云端服务器
- LLM API 调用仅发送用户提问内容，不传输客户身份信息
- 建议定期备份后从 `~/.hermes/.env` 移除不再使用的 API Key

## Reporting

Email: <lauroge@gmail.com>
