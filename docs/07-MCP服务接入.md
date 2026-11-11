# MCP 服务接入

> 一句话：把法律知识库包装成标准 MCP 服务，让 Claude Desktop / Cursor
> 这类 AI 客户端能直接查你的 462 条法条。
>
> 这份文档分两半：**一至二节讲原理**（MCP 是什么、谁启动谁、能放什么），
> **三至四节讲操作**（怎么配、怎么验证）。第一次接触 MCP 从第一节读；
> 只想把它跑起来，直接跳到第三节。

---

## 一、MCP 到底是什么

### 1.1 它解决什么问题

假设没有 MCP。Claude Desktop 想用你的法律库，你得为它写一套对接；
Cursor 想用，再写一套；明天换个客户端，再写一套。

MCP（Model Context Protocol，Anthropic 提出）就是把这套"对接规范"标准化：
**你只实现一次 server，所有支持 MCP 的客户端都能用。**

类比 USB —— 以前每个设备一种接口，有了 USB，插上就能用。
MCP 是 AI 工具领域的 USB 协议。

### 1.2 三个角色，以及"谁启动谁"

这是最容易卡住的地方，先说结论：

> **MCP 客户端不需要你单独启动。客户端就是 Claude Desktop / Cursor 本身。**

```
你打开 Claude Desktop
   ↓ 它读配置文件，发现 mcpServers 里有一条
   ↓ 于是 spawn 一个子进程：python mcp_server.py
   ↓ 通过 stdin/stdout 跟这个子进程说 JSON-RPC
   ↓ 你提问，它判断要查法条 → 发一个 tools/call 帧
   ↓ 你的进程返回条文 → 它组织成回答
   ↓ 你关掉 Claude Desktop，你的进程也跟着退出
```

完整角色图：

```
┌─────────────────────────────────────────┐
│  Host（宿主应用）                        │
│  例：Claude Desktop / Cursor            │
│                                          │
│   ┌───────────────────────────────┐     │
│   │  Client（内置的协议客户端）     │     │  ← 现成的，你不用写
│   └──────────────┬────────────────┘     │
└──────────────────┼──────────────────────┘
                   │ stdio（stdin/stdout 传 JSON-RPC）
                   ▼
        ┌─────────────────────┐
        │  Server              │  ← 你要写的 mcp_server.py
        │  暴露 tools/resources │
        └──────────┬───────────┘
                   │ HTTP / 直连 DB
                   ▼
            FastAPI / MySQL
```

**Host 和 Client 都不用写**，它们是现成产品。你只需要写 Server。

### 1.3 两种传输方式

| | stdio | HTTP（SSE / streamable-http） |
|---|---|---|
| 通信 | 父子进程的 stdin/stdout | 网络请求 |
| 谁启动 server | 客户端 spawn 子进程 | 你自己部署，常驻 |
| 端口 | 不需要 | 需要 |
| 适用 | 本地工具（主流） | 远程服务、多人共用 |
| 本项目 | **用的这个** | 没做 |

stdio 是绝大多数本地场景的选择：不用开端口、不用管鉴权，
客户端启动时顺手把 server 拉起来。

**代价是 stdout 被协议占用** —— 任何 `print` 都会把 JSON-RPC 帧冲坏，
客户端直接报解析错误。所以本项目的日志全部改到了 stderr（见第五节坑 1）。

### 1.4 MCP 里能放什么

协议定义了三类能力，本项目只用了第一类：

| 类型 | 是什么 | 类比 | 本项目 |
|---|---|---|---|
| **Tools** | 模型可以调用的函数，有参数、可能产生副作用 | POST 请求 | ✅ 三个工具 |
| **Resources** | 可读取的数据，由客户端主动加载 | GET 请求 | 未用 |
| **Prompts** | 预置的提示词模板，用户可以选择 | 快捷指令 | 未用 |

为什么只做 Tools：法律问答的核心是"根据问题查条文"，
这是一个带参数的主动行为，天然属于工具。Resources 更适合
"客户端启动时把资料加载进上下文"（比如一份完整的法条文件），
这个场景用不上。

### 1.5 在这个项目里的位置

同样的检索能力，现在有三个入口：

```
                    ┌──────────────────┐
   Vue 前端  ──────►│                  │
   Swagger   ──────►│   FastAPI 主服务  │──► Milvus + MySQL + 智谱
   （/docs）         │   （唯一数据源）   │
                    │                  │
   Claude Desktop ─►│                  │
   Cursor          └────────▲─────────┘
                            │ HTTP
                    ┌───────┴──────────┐
                    │  mcp_server.py   │
                    │  （协议转换层）    │
                    └──────────────────┘
```

**不是复制一套逻辑，是把现有能力换个协议暴露出去。**

### 1.6 启动顺序（三个进程各管一段）

| 进程 | 谁启动 | 什么时候需要 | 生命周期 |
|---|---|---|---|
| MySQL | 系统服务 | 一直 | 常驻 |
| FastAPI（`main.py`） | **你手动** | 语义检索必需 | 常驻 |
| `mcp_server.py` | **客户端自动拉起** | 客户端在用的时候 | 随客户端启停 |

实际操作就两步：

```bash
# 1. 先起后端（MCP 的语义检索要调它）
cd backend && python main.py

# 2. 打开 Claude Desktop / Cursor，它自己会把 mcp_server.py 拉起来
```

**后端不起会怎样**：`get_article` 和 `list_laws` 照样能用（直连 MySQL），
只有 `search_law` 会降级成 MySQL 关键词匹配，并在返回结果里注明一句。

---

## 二、三个工具

| 工具 | 作用 | 走哪条路 | 什么时候用 |
|---|---|---|---|
| `search_law` | 语义检索法条 | HTTP → FastAPI `/api/statutes/semantic` | 用户描述处境，如"老板不给加班费怎么办" |
| `get_article` | 按条号精确查 | 直接查 MySQL | 用户明确说"第几条" |
| `list_laws` | 列出收录的法律 | 直接查 MySQL | 确认某部法律在不在库里 |

工具的描述写在函数的 docstring 里 —— **它就是给模型看的提示词**，
决定了模型什么时候该调哪个工具。所以写得比较细。

### 为什么 `search_law` 要走 HTTP

因为 **Milvus Lite 是单进程独占的**。

MCP 服务由客户端（Claude Desktop）拉起，是独立进程。如果它自己去打开
`storage/milvus_lite/legal_law.db`，会和正在跑的 FastAPI 抢库锁，直接报
`DataDirLockedError`。

所以分工是：语义检索交给主服务代劳，精确查条和清单走 MySQL 直连
（MySQL 支持多连接）。

**好处是后端没启动时，`get_article` 和 `list_laws` 仍然可用**，
只有 `search_law` 会降级成 MySQL 关键词匹配。

---

## 三、配置

### 3.1 前置条件

1. 后端已经跑起来（`python main.py`），语义检索需要它
2. 知道 Python 的绝对路径

**Windows 下查路径**：

```bash
where python
# D:\python\python.exe
```

### 3.2 Claude Desktop

配置文件位置：

```
%APPDATA%\Claude\claude_desktop_config.json
```

在文件里加（**路径必须用双反斜杠**）：

```json
{
  "mcpServers": {
    "legal-kb": {
      "command": "D:\\python\\python.exe",
      "args": [
        "D:\\Project\\project3 法务\\legal-rag-agent\\backend\\mcp_server.py"
      ]
    }
  }
}
```

保存后**完全退出 Claude Desktop 再重开**（不是关窗口，要从托盘退出）。
重开后对话框右下角会出现一个工具图标，点开能看到 `legal-kb` 和三个工具。

### 3.3 Cursor

配置位置：`C:\Users\<你的用户名>\.cursor\mcp.json`

```json
{
  "mcpServers": {
    "legal-kb": {
      "command": "D:\\python\\python.exe",
      "args": [
        "D:\\Project\\project3 法务\\legal-rag-agent\\backend\\mcp_server.py"
      ],
      "env": {}
    }
  }
}
```

Cursor 里在 Chat 面板把模式切成 **Agent**，才能触发工具调用。
设置 → MCP 里能看到 `legal-kb` 显示绿灯就是连上了。

### 3.4 其他客户端

任何支持 MCP 的客户端都用同一套配置：`command` 是 Python 解释器，
`args` 是 `mcp_server.py` 的绝对路径。传输方式是 stdio。

---

## 四、验证

### 4.1 一行命令自检（不用装任何客户端）

项目里带了 `backend/test_mcp.py`，它自己扮演 Client，走完整协议链路：

```bash
cd backend
python test_mcp.py
```

它会依次做四件事：协议握手 → 列工具 → 逐个调用三个工具 → 给结论。

正常输出：

```
════════════════════════════════════════════════════════════════════
MCP 服务自检
════════════════════════════════════════════════════════════════════
✓ 协议握手成功
  服务名  : legal-kb
  协议版本: 2025-11-25
  说明    : 中国法律知识库。收录 32 部法律、462 条法条……

✓ 发现 3 个工具
  · search_law     按语义检索法条，能处理口语化的问题。
  · get_article    按法律名称和条号精确查询条文原文。
  · list_laws      列出知识库里收录的所有法律，以及每部的条数。

────────────────────────────────────────────────────────────────────
调用测试
────────────────────────────────────────────────────────────────────

▸ list_laws  —— 列出劳动法领域的法律
  ✓ 返回 203 字
    共收录 5 部法律：

▸ get_article  —— 按条号精确查（传阿拉伯数字，内部会转中文）
  ✓ 返回 249 字
    《中华人民共和国劳动合同法》第十九条【试用期期限】

▸ search_law  —— 语义检索（需要后端在跑，否则自动降级）
  ✓ 返回 725 字
    检索「老板不给加班费」命中 3 条：

════════════════════════════════════════════════════════════════════
结论：全部通过（3 个工具）
════════════════════════════════════════════════════════════════════
```

**这条路不需要 Claude Desktop，也不需要后端在跑**（`get_article` 和 `list_laws`
直连 MySQL）。改完 `mcp_server.py` 跑一遍，就能确认协议层没坏。

### 4.1.1 如果自检失败

| 现象 | 原因 |
|---|---|
| `缺少依赖：mcp` | 没装，`python -m pip install mcp` |
| 握手超时 | `mcp_server.py` 里有 `print` 写到了 stdout，把协议帧冲坏了 |
| `search_law` 返回「关键词匹配到…」 | 后端没启动，走的是降级路径，属正常 |
| 中文乱码 | 终端编码问题，不影响功能（日志走 stderr） |

### 4.2 在客户端里试

Claude Desktop 里直接说：

> 帮我查一下劳动合同法第十九条怎么规定的

模型会自己调 `get_article`。如果它没调，说明工具描述没被正确加载 ——
检查配置文件的路径是不是写错了。

再试一个不带条号的：

> 公司不给我加班费，法律上怎么规定的

这次应该调 `search_law`。

---

## 五、四个容易踩的坑

### 坑 1：日志写 stdout 会冲坏协议

**stdio 传输用 stdout 传 JSON-RPC 帧**。任何 `print()` 到 stdout 的内容
都会插进协议流里，客户端报"无法解析响应"。

这个项目里 `common/logger.py` 和 `config.py` 的输出都改成 `sys.stderr` 了。
如果你要加调试代码：

```python
print("debug", file=sys.stderr)   # ✅
print("debug")                     # ❌ 会破坏协议
```

### 坑 2：路径要用绝对路径

客户端拉起子进程时，工作目录不一定是 `backend/`。
配置里的 `args` 和 `command` 都写绝对路径，别用相对路径。

### 坑 3：Python 环境要装对依赖

`command` 指向的 Python 必须装了 `mcp` 和项目依赖。
如果系统里有多个 Python（比如 conda 和系统 Python），
写错了解释器路径会报 `ModuleNotFoundError: mcp`。

验证方法：

```bash
D:\python\python.exe -c "import mcp; print(mcp.__version__)"
```

### 坑 4：改了代码要重启客户端

MCP 服务是客户端拉起的子进程，改完 `mcp_server.py` 要重启 Claude Desktop
才会加载新代码。调试阶段这个来回很烦，可以先在命令行用 4.1 的脚本测。

---

## 六、怎么解释这些设计

如果被问到"你用过 MCP 吗"，不要只说"用过"，说清楚分层：

> 用做过。我给自己的法律知识库写了一个 MCP 服务，暴露三个工具：
> 语义检索、按条号精确查、法律清单。
>
> 有个设计上的取舍值得说：MCP 服务是独立进程，如果它直接连 Milvus，
> 会和主服务抢库锁（我用的是嵌入式模式，单进程独占）。所以我把语义检索
> 做成走 HTTP 调主服务，而精确查条和清单直接连 MySQL —— 前者必须经过
> 向量库，后者不需要。
>
> 这样还有个附带好处：后端没启动时，精确查条仍然可用，只有语义检索会降级成
> 关键词匹配。
>
> 我的理解是：**MCP 是协议层，不该往里面塞业务逻辑**。
> 它只负责把现有的 REST 能力翻译成工具调用，检索、重排、切片这些都在后端。

这个回答体现两件事：知道 MCP 是什么，也知道**它该放在哪一层**。

### 追问：那你的 Agent 有 function calling 吗

要能分清这两件事：

| | MCP | Function Calling |
|---|---|---|
| 解决什么 | 让**外部客户端**接入你的能力 | 让**模型**在对话中选择工具 |
| 谁发起 | 客户端（Claude Desktop） | 你的应用 |
| 位置 | 系统边界 | 对话循环内部 |

这个项目的 Web 端没用 function calling，是刻意的：法律场景工具空间很小，
我用一次路由调用（输出 intent + domain）替代了 ReAct 的多轮循环，
端到端固定两次 LLM 调用。MCP 是另一个维度的东西 —— 它不改变主链路，
只是多开了一个入口。

---

## 七、代码在哪

| 文件 | 作用 |
|---|---|
| `backend/mcp_server.py` | MCP 服务本体，三个工具 |
| `backend/service/statute_service.py` | `semantic_search()`，语义检索的业务实现 |
| `backend/api/statute_api.py` | `/api/statutes/semantic` 接口 |
| `backend/common/logger.py` | 日志输出到 stderr（MCP 的要求） |
