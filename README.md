# API 2 Cursor

让 Cursor 通过第三方中转站使用任意 LLM 模型的 API 代理服务。

## 它解决什么问题

Cursor 根据模型名发送不同格式的请求：

| Cursor 模型名风格 | 请求格式 |
|---|---|
| `claude-sonnet-*`、`glm-*` | `/v1/chat/completions` (OpenAI CC) |
| `gpt-*`、`claude-opus-*` | `/v1/responses` (OpenAI Responses) |

而中转站通常只支持 `/v1/chat/completions`、`/v1/messages` 或 `/v1/responses`。

本项目在中间做协议转换，**不管 Cursor 发什么格式，都能正确转发到中转站；不管中转站返回什么格式，都让 Cursor 能正确接收**。

## 架构

可以把这个项目理解成“三种入口协议 + 三种上游后端协议”的协议桥：

```text
Cursor                         API 2 Cursor                           中转站
  │                                 │                                   │
  ├─ /v1/chat/completions ─────→ chat.py ─────┬─ openai 后端 ─────────→ /v1/chat/completions
  │                                            ├─ anthropic 后端 ─────→ /v1/messages
  │                                            └─ responses 后端 ─────→ /v1/responses
  │
  ├─ /v1/responses ────────────→ responses.py ─┬─ openai 后端 ───────→ /v1/chat/completions
  │                                             ├─ anthropic 后端 ───→ /v1/messages
  │                                             └─ responses 后端 ───→ /v1/responses
  │
  └─ /v1/messages ─────────────→ messages.py ─────────────────────────→ /v1/messages
```

其中：
- `chat.py` 负责接住 Cursor 的 Chat Completions 请求，并根据模型映射决定发往哪种后端协议
- `responses.py` 负责接住 Cursor 的 Responses 请求，并在需要时做 `Responses ↔ CC` 或 `Responses ↔ Messages` 桥接
- `messages.py` 负责 Anthropic 原生消息的直通场景

## 快速开始

### Windows 直接运行

PowerShell：

```powershell
cd api2cursor
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# 编辑 .env 填入中转站地址和密钥
python start.py
```

如果仓库里已经有可用的 `.venv`，可以直接执行：

```powershell
cd api2cursor
.\.venv\Scripts\python.exe start.py
```

服务启动后访问 `http://localhost:3029/admin` 进入管理面板。

### macOS 直接运行

Terminal：

```bash
cd api2cursor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入中转站地址和密钥
python start.py
```

服务启动后访问 `http://localhost:3029/admin` 进入管理面板。

> 从 Windows 迁移到 macOS 时，不要复制 Windows 下的 `.venv`，请在 macOS 上重新创建虚拟环境。`.env` 可以复制，但如果里面有 Windows 路径（例如 `NGROK_COMMAND=C:\...`），需要改成 macOS 可用的命令或路径。

默认会自动启动 ngrok 公网隧道。启动后终端会打印：

```text
Cursor Base URL: https://xxxx.ngrok-free.app
公网管理面板: https://xxxx.ngrok-free.app/admin
```

Cursor 无法直接访问 `localhost` 或私人网络地址时，请在 Cursor 中填写这个公网 Base URL。

### Docker 部署

```bash
cd api2cursor
cp .env.example .env
# 编辑 .env；如果容器里没有安装 ngrok，请设置 ENABLE_TUNNEL=false
docker compose up -d
```

服务启动后访问 `http://localhost:3029/admin` 进入管理面板。

## 配置

### 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `PROXY_TARGET_URL` | 上游中转站地址 | `https://api.anthropic.com` |
| `PROXY_API_KEY` | 上游 API 密钥 | |
| `PROXY_PORT` | 服务监听端口 | `3029` |
| `API_TIMEOUT` | 请求超时（秒） | `300` |
| `ACCESS_API_KEY` | 访问鉴权密钥，留空不启用 | |
| `DEBUG` | 兼容旧版调试开关，开启后等价于 `DEBUG_MODE=simple` | `false` |
| `DEBUG_MODE` | 调试模式：`off` / `simple` / `verbose` | `off` |
| `ENABLE_TUNNEL` | 是否自动启动公网隧道 | `true` |
| `TUNNEL_PROVIDER` | 隧道提供方，当前仅支持 `ngrok` | `ngrok` |
| `NGROK_COMMAND` | ngrok 命令路径 | `ngrok` |
| `NGROK_API_URL` | ngrok 本地 agent API 地址 | `http://127.0.0.1:4040/api` |
| `TUNNEL_STARTUP_TIMEOUT` | 等待公网链接创建的超时时间（秒） | `15` |

### 公网隧道

Cursor 可能无法访问 `http://localhost:3029`、`http://127.0.0.1:3029` 或 `192.168.x.x` 这类私人网络地址。本项目默认使用 ngrok 自动创建公网 HTTPS 链接，供 Cursor 访问本地代理。

首次使用前需要安装并登录 ngrok。

Windows 可以从 ngrok 官网下载安装，或使用 winget：

```powershell
winget install ngrok.ngrok
ngrok config add-authtoken <your-ngrok-token>
```

macOS 可以使用 Homebrew：

```bash
brew install ngrok/ngrok/ngrok
ngrok config add-authtoken <your-ngrok-token>
```

公网隧道开启时必须配置 `ACCESS_API_KEY`，否则服务会拒绝启动，避免把代理公开成无鉴权 API。如果只想本地 curl 测试或部署在自己控制的公网服务器上，可以关闭隧道：

```env
ENABLE_TUNNEL=false
```

### 模型映射

在管理面板 (`/admin`) 中配置模型映射：

- **Cursor 模型名** — 在 Cursor 自定义模型中填入的名称
- **上游模型名** — 发送到中转站的实际模型名
- **后端类型** — `openai` (CC 格式) / `anthropic` (Messages 格式) / `responses` (Responses 格式) / `gemini` (Gemini Contents 格式) / `auto` (自动检测)
- **自定义地址/密钥** — 可选，覆盖全局设置，实现分流到不同中转站
- **日志模式** — 可在管理面板全局设置中切换 `off` / `simple` / `verbose`

**示例**：在 Cursor 中添加 `claude-sonnet-4-5-20250929`，映射到上游 `gpt-5.3-codex`，后端选 `openai`。Cursor 会用 CC 格式发送请求，代理直接转发到中转站的 `/v1/chat/completions`。

如果你的中转站只支持 `/v1/responses`，可以把后端类型选成 `responses`。此时代理会把 Cursor 发来的请求转换或透传为 Responses 格式，再发往中转站的 `/v1/responses`。

> **提示**：使用 Claude 风格的模型名（如 `claude-sonnet-4-5-20250929`）可以让 Cursor 显示思考过程（thinking）。

### 调试日志模式

项目支持三档调试模式，可通过环境变量 `DEBUG_MODE` 或管理面板全局设置切换：

- `off` — 关闭调试日志
- `simple` — 仅输出控制台调试日志，不写文件
- `verbose` — 输出控制台调试日志，并写入详细的对话级文件日志

详细日志会写入：

```text
data/conversations/YYYY-MM-DD/{conversation_id}.json
```

特性：
- 同一段多轮对话聚合到同一个文件
- 自动记录 client request、upstream request/response、client response、错误信息
- 流式事件只保留前 12 条和后 12 条，中间部分折叠计数，避免文件膨胀
- 流式 `client_response` 只记录 summary，不重复保存完整事件数组

### 在 Cursor 中配置

1. 打开 Cursor 设置 → Models
2. 添加自定义模型，名称填映射中配置的 Cursor 模型名
3. Override OpenAI Base URL 填启动时打印的 `Cursor Base URL`，例如 `https://xxxx.ngrok-free.app`
4. API Key 填 `ACCESS_API_KEY` 的值

## 项目结构

```text
api2cursor/
├── start.py                    # 启动入口
├── app.py                      # Flask 应用工厂
├── config.py                   # 环境变量配置
├── settings.py                 # 持久化配置管理
├── routes/                     # 路由层：按对外 API 入口拆分
│   ├── chat.py                 #   /v1/chat/completions
│   ├── responses.py            #   /v1/responses
│   ├── messages.py             #   /v1/messages（透传）
│   ├── admin.py                #   管理面板 + API
│   └── common.py               #   路由公共上下文、日志与 SSE 辅助
├── adapters/                   # 适配层：按协议桥接职责拆分
│   ├── cc_anthropic_adapter.py #   Chat Completions ↔ Anthropic Messages
│   ├── openai_compat_fixer.py  #   OpenAI / Chat Completions 兼容修复
│   └── responses_cc_adapter.py #   Responses ↔ Chat Completions + 原生 Responses 流桥接
├── utils/                      # 通用工具层
│   ├── http.py                 #   请求转发、SSE 解析
│   ├── tool_fixer.py           #   工具参数修复
│   └── think_tag.py            #   <think> 标签提取
└── static/                     # 管理面板前端
    ├── admin.html
    ├── admin.css
    └── admin.js
```

## 兼容性修复

代理自动处理以下兼容性问题：

- Cursor 扁平格式 tools → 标准 OpenAI 嵌套格式
- `reasoningContent` → `reasoning_content`
- `<think>` 标签 → `reasoning_content`
- 旧版 `function_call` → 新版 `tool_calls`
- `tool_calls` 缺失 `id` / `index` / `type` 字段补全
- 智能引号 → 普通引号（StrReplace 工具精确匹配修复）
- `file_path` → `path` 字段映射
- `finish_reason` 修正

## 许可证

[MIT](LICENSE)
