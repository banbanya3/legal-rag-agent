# FastAPI 改造：分层结构与代码对照

> **这份文档回答一个问题**：已经有 Flask 版项目，换成 FastAPI 后，
> service 层、dao 层、api 层分别变成什么样？哪些要改，哪些不动？
>
> 配套文档：`05-Flask与FastAPI选型对比.md`（讲"选不选"），本文讲"怎么写"。
>
> 阅读方式：第一、二节看整体，第三节是核心原理，第四节可以当速查表跳着查。

---

## 零、先记住一句话

> **分层不变。变的只有最外面那层"框架适配层"，以及一条异步的传染链。**

很多人以为换框架要重写整个项目，其实不是。判断标准很简单：

**只要一段代码里没有出现 `request`、`jsonify`、`Blueprint`、`Depends`、
`Response` 这类框架名词，它就跟框架无关，一行都不用改。**

按这个标准量一下你的项目：

```
backend/                              共 40 个 .py 文件
├── api/          8 个文件    ← 全部重写（6 个业务模块 + __init__ + deps）
├── service/      8 个文件    ← 只有 agent_service / chat_service 改 async
├── schemas/      （新增）    ← 5 个 Pydantic 模型文件
├── dao/          8 个文件    ← 0 改动
├── rag/          7 个文件    ← 0 改动
├── llm/          3 个文件    ← client.py 加异步方法，prompts.py 不动
├── common/       3 个文件    ← 0 改动（Result 返回 dict，FastAPI 直接能序列化）
├── app.py                    ← 重写成 main.py
├── config.py                 ← 0 改动
└── init_knowledge.py         ← 0 改动
```

**12 个文件要动（9 个重写 + 2 个改签名 + 1 个加方法），28 个文件一行不改，占比 30%。**

> 这里有个反直觉的点：`common/result.py` **不用改**。
> 它只返回 dict，而 FastAPI 原生支持返回 dict。
> 需要去掉 `jsonify()` 的是 `api/` 层的调用处，不是这个类本身。

---

## 一、整体结构对照

### 1.1 目录树：改前 vs 改后

**Flask 版（现在）**

```
backend/
├── app.py                    # 应用工厂 + 错误处理 + 生命周期 + 启动入口
├── config.py
├── init_knowledge.py
│
├── api/                      # 路由层（Blueprint）
│   ├── __init__.py           # register_blueprints(app)
│   ├── deps.py               # flask.g 做请求级 Session
│   ├── chat_api.py           # bp = Blueprint(...)
│   ├── session_api.py
│   ├── statute_api.py
│   ├── knowledge_api.py
│   ├── settings_api.py
│   └── system_api.py
│
├── schemas/                  # ❌ 现在没有这个目录
│
├── service/
├── dao/
├── rag/
├── llm/
└── common/
```

**FastAPI 版（改造后）**

```
backend/
├── main.py                   # 应用实例 + lifespan + 中间件 + 启动入口
├── config.py                 # 不变
├── init_knowledge.py         # 不变
│
├── api/                      # 路由层（APIRouter）
│   ├── __init__.py           # register_routers(app)
│   ├── deps.py               # Depends 做请求级 Session
│   ├── chat_api.py           # router = APIRouter(...)
│   ├── session_api.py
│   ├── statute_api.py
│   ├── knowledge_api.py
│   ├── settings_api.py
│   └── system_api.py
│
├── schemas/                  # ✅ 新增：Pydantic 请求/响应模型
│   ├── __init__.py
│   ├── chat_schema.py        # ChatRequest / ChatResponse / SourceItem
│   ├── session_schema.py
│   ├── statute_schema.py
│   ├── knowledge_schema.py
│   └── settings_schema.py
│
├── service/
├── dao/
├── rag/
├── llm/
└── common/
```

**结构上唯一的"新增"是 `schemas/`**，这是 Pydantic 模型的归属地。
其余变化都是"同位置换写法"。

### 1.2 变化边界图

```
        HTTP 请求
            │
            ▼
┌───────────────────────────────┐
│  api/                    变   │  蓝图 → APIRouter
│                          ████ │  request → 函数参数
│                               │  jsonify → return dict
├───────────────────────────────┤
│  schemas/                新增 │  Pydantic 模型
├───────────────────────────────┤
│  service/            部分变   │  同步函数 → async 函数
│                          ██   │
├───────────────────────────────┤
│  dao/                   不变  │  SQLAlchemy 同步 CRUD
│  rag/                   不变  │  向量检索、切分、重排
│  llm/prompts.py         不变  │  纯字符串
├───────────────────────────────┤
│  llm/client.py       部分变   │  新增异步方法，同步方法保留
│                          ██   │
├───────────────────────────────┤
│  config.py              不变  │
└───────────────────────────────┘
            │
            ▼
      MySQL / Milvus / 智谱 API
```

**越往下越稳定。** 这是好架构的特征 —— 业务逻辑不依赖框架，
所以换框架只需要换"最薄的那层壳"。

---

## 二、逐层拆解

### 2.1 应用入口：`app.py` → `main.py`

#### Flask 版

```python
# backend/app.py
from flask import Flask, jsonify
from flask_cors import CORS

def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

    CORS(app, resources={r"/api/*": {"origins": settings.CORS_ORIGINS}})

    register_blueprints(app)       # 注册 6 个蓝图
    _register_error_handlers(app)  # 全局异常处理
    _register_lifecycle(app)       # before_request 建表 + teardown 关 session

    @app.get("/")
    def index():
        return jsonify(Result.ok({...}))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, threaded=True, use_reloader=False)
```

#### FastAPI 版

```python
# backend/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动/关闭钩子，替代 Flask 的 before_request + teardown_appcontext。"""
    # 启动时执行一次（不是每个请求都执行）
    ensure_database()
    create_tables()
    logger.info("启动自检完成")
    yield
    # 关闭时执行
    logger.info("服务关闭")


app = FastAPI(
    title="法眼 · 法律知识库智能问答系统",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",      # Swagger UI，自动生成
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_routers(app)
register_exception_handlers(app)

@app.get("/")
async def index():
    return Result.ok({...})     # 直接返回 dict，自动转 JSON


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
```

#### 差异对照

| 维度 | Flask | FastAPI |
|---|---|---|
| 应用对象 | `Flask(__name__)` | `FastAPI(...)` |
| 启动钩子 | `@app.before_request`（每个请求都跑，要加 flag 判断） | `lifespan` 上下文管理器（真的只跑一次） |
| 关闭钩子 | `@app.teardown_appcontext` | `lifespan` 里 `yield` 之后 |
| 配置项 | `app.config[...]` 字典 | 构造参数 + `app.state` |
| 启动命令 | `app.run(...)` | `uvicorn main:app` |
| 接口文档 | 无，手写 markdown | `/docs` 自动生成 |

> **`lifespan` 是 FastAPI 结构上最优雅的地方**。Flask 没有"只执行一次的启动钩子"，
> 所以现在的 `app.py` 里用了 `before_request` + `_db_ready` 标志位来模拟，
> 是个 workaround。FastAPI 的 lifespan 是原生支持。

---

### 2.2 路由层：`Blueprint` → `APIRouter`

这是改动最大的地方，但**逻辑几乎是一一对应的**。

#### Flask 版

```python
# api/chat_api.py
from flask import Blueprint, Response, jsonify, request
from api.deps import get_db
from common.result import BizError, Result
from service import chat_service

bp = Blueprint("chat", __name__, url_prefix="/api/chat")


def _read_payload():
    """手动解析 + 手动校验，这是 Flask 版每个接口都要做的事。"""
    body = request.get_json(silent=True) or {}
    session_id = str(body.get("session_id") or "").strip()
    query = str(body.get("query") or "").strip()

    if not session_id:
        raise BizError("session_id 不能为空")
    if not query:
        raise BizError("问题不能为空")
    if len(query) > 2000:
        raise BizError("问题太长了，请控制在 2000 字以内")

    use_rerank = body.get("use_rerank")
    return session_id, query, use_rerank if isinstance(use_rerank, bool) else None


@bp.post("/stream")
def chat_stream():
    session_id, query, use_rerank = _read_payload()   # ← 手动调用校验
    return Response(
        chat_service.sse_stream(session_id, query, use_rerank),
        headers=SSE_HEADERS,
        status=200,
    )


@bp.post("")
def chat_once():
    session_id, query, use_rerank = _read_payload()
    data = chat_service.chat_once(session_id, query, use_rerank)
    return jsonify(Result.ok(data))                   # ← 手动包信封
```

#### FastAPI 版

```python
# api/chat_api.py
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.deps import get_db
from schemas.chat_schema import ChatRequest, ChatResponse
from common.result import Result
from service import chat_service

router = APIRouter(prefix="/api/chat", tags=["对话"])


@router.post("/stream", summary="流式对话（SSE）")
async def chat_stream(payload: ChatRequest):        # ← 自动解析 + 自动校验
    return StreamingResponse(
        chat_service.sse_stream(payload),           # ← 必须是 async generator
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("", response_model=ChatResponse, summary="非流式对话")
async def chat_once(payload: ChatRequest, db: Session = Depends(get_db)):
    data = await chat_service.chat_once(db, payload)
    return Result.ok(data)                          # ← 直接 return，自动转 JSON
```

**`_read_payload()` 这 15 行校验代码整个消失了**，被 Pydantic 模型取代。

#### 对照表

| 概念 | Flask | FastAPI |
|---|---|---|
| 路由对象 | `Blueprint("chat", __name__, url_prefix="/api/chat")` | `APIRouter(prefix="/api/chat", tags=["对话"])` |
| 注册方式 | `app.register_blueprint(bp)` | `app.include_router(router)` |
| 路径参数 | `@bp.get("/<session_id>/messages")` + 函数参数 `session_id` | `@router.get("/{session_id}/messages")` + 类型标注 |
| 查询参数 | `request.args.get("keyword", "")` | `keyword: str = Query(default="")` |
| 请求体 | `request.get_json()` + 手动取值 | Pydantic 模型作为参数 |
| 返回 JSON | `jsonify(...)` | `return dict` |
| 状态码 | `return data, 201` | `@router.post(..., status_code=201)` |
| 文件上传 | `request.files.get("file")` | `file: UploadFile = File(...)` |

> **路径参数语法变了**：Flask 是 `/<name>`，FastAPI 是 `/{name}`。
> 六对尖括号改成六对花括号，别漏。

---

### 2.3 依赖注入：`flask.g` → `Depends`

#### Flask 版：靠 `g` 做请求级单例

```python
# api/deps.py
from flask import g
from sqlalchemy.orm import Session
from dao.db import SessionLocal

def get_db() -> Session:
    if "db" not in g:          # 第一次调用时创建
        g.db = SessionLocal()
    return g.db                # 同一请求内复用

def close_db(exception=None):
    db = g.pop("db", None)     # 请求结束时关闭
    if db is not None:
        db.close()
```

使用时是在函数体里**主动调用**：

```python
@bp.get("/domains")
def domains():
    db = get_db()                    # ← 手动拿
    return jsonify(Result.ok(knowledge_service.domain_overview(db)))
```

#### FastAPI 版：靠 `Depends` 声明式注入

```python
# api/deps.py
from collections.abc import Generator
from sqlalchemy.orm import Session
from dao.db import SessionLocal

def get_db() -> Generator[Session, None, None]:
    """yield 之前是准备，yield 之后是清理 —— FastAPI 会自动在请求结束时执行清理。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

使用时是**在函数签名里声明**：

```python
@router.get("/domains")
async def domains(db: Session = Depends(get_db)):   # ← 声明即注入
    return Result.ok(knowledge_service.domain_overview(db))
```

#### 关键差异（这点最容易搞混）

| | Flask `g` | FastAPI `Depends` |
|---|---|---|
| 谁调用 | **你**在函数体里调用 `get_db()` | **框架**在调用函数前注入 |
| 作用域 | 请求级（`g` 在请求结束时清空） | 请求级（`yield` 之后执行清理） |
| 写法 | 命令式 | 声明式 |
| 可组合 | 否 | 是（依赖可以依赖依赖） |

**`Depends` 的本质不是"依赖注入框架"，只是一个"参数预处理器"**：
框架在调用你的函数前，先调用 `get_db()`，把返回值塞进 `db` 参数。

所以它和 Java Spring 的 `@Autowired` 不是一回事 —— 没有容器、没有 bean 生命周期管理。

#### ⚠️ 一个必须知道的坑

**流式接口不能用 `Depends(get_db)`。**

```python
# ❌ 错误写法
@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, db: Session = Depends(get_db)):
    return StreamingResponse(sse_stream(payload, db), ...)
```

原因：FastAPI 的 `yield` 依赖在**响应开始发送时就退出**了（执行 `finally: db.close()`），
而此时生成器还没开始迭代。生成器里再用 `db` 会报
`This session is in 'prepared' state` 或 `MySQL server has gone away`。

**正确做法和 Flask 版一样**：在生成器内部自己开 session。

```python
# ✅ 正确写法
@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    return StreamingResponse(sse_stream(payload), ...)

async def sse_stream(payload: ChatRequest):
    db = SessionLocal()          # 生成器内部自己开
    try:
        ...
    finally:
        db.close()
```

---

### 2.4 请求校验：手动 if/else → Pydantic

这是 FastAPI 最大的结构收益，**新增了 `schemas/` 这一层**。

#### Flask 版：校验逻辑散落在每个接口里

```python
def _read_payload():
    body = request.get_json(silent=True) or {}
    session_id = str(body.get("session_id") or "").strip()
    if not session_id:
        raise BizError("session_id 不能为空")
    if not query:
        raise BizError("问题不能为空")
    if len(query) > 2000:
        raise BizError("问题太长了...")
    ...
```

**问题**：
- 每个接口都要写一遍类似的代码（6 个文件，20+ 处）
- 类型转换靠手动 `str()`、`int()`
- 校验规则和业务代码混在一起
- 文档要单独手写，容易和代码不同步

#### FastAPI 版：模型即校验 + 即文档

```python
# schemas/chat_schema.py
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64, description="会话 ID")
    query: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    use_rerank: bool = Field(default=True, description="是否开启精排")
```

```python
# api/chat_api.py —— 校验代码完全消失
@router.post("/stream")
async def chat_stream(payload: ChatRequest):
    # 到这里时 payload 已经保证：session_id 非空且 ≤64 字符，
    # query 非空且 ≤2000 字符，use_rerank 是布尔值
    ...
```

**这一份 `ChatRequest` 同时干三件事**：
1. 解析请求体
2. 校验（不通过自动返回 422 + 详细错误）
3. 生成 OpenAPI 文档（`/docs` 里能看到字段说明和示例）

#### Pydantic 能校验的不只是请求体

| 位置 | 写法 |
|---|---|
| 请求体 | 模型类作为参数：`payload: ChatRequest` |
| 查询参数 | `keyword: str = Query(default="", max_length=50)` |
| 路径参数 | `session_id: str = Path(..., min_length=1)` |
| 请求头 | `token: str = Header(...)` |
| 响应体 | `@router.post(..., response_model=ChatResponse)` |

**`response_model` 是个很实用的功能**：它会把返回值按模型过滤。
如果你返回的 dict 里多带了敏感字段（比如 `api_key`），会被自动剔除，不会泄漏到前端。

#### 建议的 schema 划分

```
schemas/
├── chat_schema.py       ChatRequest, ChatResponse, SourceItem
├── session_schema.py    SessionInfo, MessageInfo, RenameRequest
├── statute_schema.py    StatuteItem, StatuteQuery
├── knowledge_schema.py  UploadResult, DomainInfo, RebuildRequest
└── settings_schema.py   LLMSettingIn, LLMSettingOut, TestResult
```

> **一个原则**：请求模型和响应模型分开写（`ChatRequest` / `ChatResponse`），
> 不要用一个模型打天下。响应里往往要多带 `elapsed_ms`、`sources` 这类字段，
> 请求里没有；混用会导致文档难看、校验过松。

---

### 2.5 响应封装：`jsonify` → 直接返回

#### Flask 版

```python
# common/result.py
class Result:
    @staticmethod
    def ok(data=None, message="success") -> dict:
        return {"code": 0, "message": message, "data": data}

# api 里
return jsonify(Result.ok(data))
```

`jsonify` 是必须的 —— Flask 不认识 `dict`，直接 `return dict` 会报错
（Flask 2.2+ 才支持返回 dict，但会走 `json.dumps`，行为和 `jsonify` 有细微差别）。

#### FastAPI 版

```python
# common/result.py —— Result 类完全不用改
class Result:
    @staticmethod
    def ok(data=None, message="success") -> dict:
        return {"code": 0, "message": message, "data": data}

# api 里
return Result.ok(data)      # 直接返回 dict，FastAPI 自动序列化
```

**`Result` 类一行不用改**，只是把 `jsonify()` 去掉。

FastAPI 用 `jsonable_encoder` 处理返回值，支持 dict、list、Pydantic 模型、
datetime、Decimal 等类型，中文默认不转义。

---

### 2.6 异常处理：`errorhandler` → `exception_handler`

#### Flask 版

```python
# app.py
@app.errorhandler(BizError)
def handle_biz_error(exc: BizError):
    return jsonify(Result.fail(exc.message, exc.code)), exc.status

@app.errorhandler(Exception)
def handle_unexpected(exc: Exception):
    logger.exception("未捕获异常")
    return jsonify(Result.fail(f"服务器内部错误：{exc}", 500)), 500
```

#### FastAPI 版

```python
# api/__init__.py 或 main.py
from fastapi import Request
from fastapi.responses import JSONResponse

def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(BizError)
    async def handle_biz_error(request: Request, exc: BizError):
        return JSONResponse(
            status_code=exc.status,
            content=Result.fail(exc.message, exc.code),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        """Pydantic 校验失败默认返回 422 + 一堆结构化数据，
        这里压成一句人话，前端不用改解析逻辑。"""
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(x) for x in first.get("loc", [])[1:])
        return JSONResponse(
            status_code=400,
            content=Result.fail(f"参数 {field} 不合法：{first.get('msg', '')}", 400),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        logger.exception("未捕获异常：%s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=Result.fail(f"服务器内部错误：{type(exc).__name__}", 500),
        )
```

#### 两个差异

1. **签名变了**：多一个 `request` 参数，且用 `JSONResponse` 而不是 `jsonify`。
2. **多了一类要处理**：`RequestValidationError`（Pydantic 校验失败）。

第 2 点是必须处理的 —— 否则前端会收到 FastAPI 默认的 422 结构：

```json
{
  "detail": [
    {"loc": ["body", "query"], "msg": "field required", "type": "value_error.missing"}
  ]
}
```

这和你自己的 `{code, message, data}` 信封不一致，前端拦截器会解析失败。
**加了这个 handler，前端一行不用改。**

---

### 2.7 生命周期：`before_request` + flag → `lifespan`

#### Flask 版的 workaround

```python
@app.before_request
def _ensure_once():
    if getattr(app, "_db_ready", False):   # ← 靠标志位模拟"只执行一次"
        return
    try:
        ensure_database()
        create_tables()
    except Exception as exc:
        logger.error("启动自检失败：%s", exc)
    app._db_ready = True                    # ← 打标记
```

**为什么要这样写**：Flask 没有"启动钩子"。`before_request` 是每个请求都调用的，
所以要用标志位挡一下。而且这个标志位挂在 `app` 对象上，是个 hack。

#### FastAPI 版的 lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # yield 之前 = startup，真的只执行一次
    ensure_database()
    create_tables()
    yield
    # yield 之后 = shutdown
    logger.info("服务关闭，释放资源")
```

干净、语义明确、不用标志位。

#### ⚠️ Milvus Lite 的特殊处理

你的项目里 `app.run(use_reloader=False)` 是因为 Milvus Lite 单进程独占，
reloader 会起两个进程抢锁。

FastAPI 的 `uvicorn.run(..., reload=True)` 有同样的问题。
所以：

```python
uvicorn.run("main:app", reload=False)      # 开发时也别开 reload
```

或者用 Standalone 模式的 Milvus（`MILVUS_URI=http://host:19530`），就没有这个限制。

---

### 2.8 service / dao / rag：改什么，不改什么

这三层是"业务核心"，**绝大部分不动**。

#### dao 层：0 改动

```python
# dao/statute_dao.py —— Flask 和 FastAPI 下完全一样
def find_by_article(db: Session, law_name: str, article_no: str):
    return (
        db.query(StatuteArticle)
        .filter(StatuteArticle.law_name.like(f"%{law_name}%"))
        .filter(StatuteArticle.article_no == article_no)
        .first()
    )
```

它只依赖 `sqlalchemy.orm.Session`，跟 Web 框架没有任何关系。

**不建议为了 FastAPI 把 dao 改成异步**（换成 `asyncmy` / `aiomysql` 驱动）：
- 改造成本高（每个 CRUD 都要 `await`，`session` 生命周期也要重写）
- 收益低（单次查询几毫秒，扔线程池完全够）
- 风险大（异步驱动的连接池、事务行为和同步版有差异）

#### rag 层：0 改动

```python
# rag/retriever.py —— 一样
def retrieve(db, query, domain=None, top_k=8, rerank_n=4, ...):
    ...
```

`retrieve()` 是同步函数，在 FastAPI 里用 `run_in_threadpool` 包一层即可：

```python
hits = await run_in_threadpool(retrieve, db, query, domain=domain, top_k=top_k)
```

#### service 层：改函数签名，改调用方式

原来的同步函数改成 async，内部对同步操作包线程池。

```python
# Flask 版
def retrieve_and_answer(db, cfg, query):
    hits = retrieve(db, query, ...)              # 直接调用
    ...
```

```python
# FastAPI 版
async def retrieve_and_answer(db, cfg, query):
    hits = await run_in_threadpool(retrieve, db, query, ...)   # 包一层
    ...
```

#### llm 层：新增异步方法，保留同步方法

**注意：是"新增"不是"替换"。**

因为 `init_knowledge.py` 建索引时还要用同步版本（它是个脚本，没有事件循环）。
两套并存，各用各的。

```python
class LLMClient:
    # ---- 同步版：给脚本和后台任务用 ----
    def chat(self, messages, ...) -> str: ...

    # ---- 异步版：给 Web 请求用 ----
    async def achat(self, messages, ...) -> str:
        async with httpx.AsyncClient(trust_env=False, timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=...)
            ...
```

---

## 三、最大的结构性变化：异步的"传染性"

这一节是整份文档的核心。**如果只读一节，读这节。**

### 3.1 什么是"函数染色"

异步函数有一条硬规则：

> **`async` 函数只能被 `await`，不能直接调用；
> 而 `await` 只能在 `async` 函数里写。**

于是会形成一条链：

```
async 路由函数
    └─ await async service 函数
            └─ await async llm 函数
                    └─ await httpx.AsyncClient.post()
```

只要链条上有一环是同步的，就必须在那里**切断**（用线程池），
或者把整条链改成异步。

这就是所谓的"函数染色"（function color）：**异步会从入口一路传染到出口**。

### 3.2 这个项目的异步边界划在哪

```
HTTP 请求
    │
    ▼
[async] api 层               ← 全异步
    │
    ▼
[async] service 层           ← 全异步
    │
    ├──► [await] llm.stream_chat()      ← 必须异步（耗时 10—20 秒）
    │         └─► httpx.AsyncClient
    │
    ├──► [run_in_threadpool] retrieve()  ← 切断点 1（耗时 0.3—0.8 秒）
    │         └─► 同步：Milvus + httpx + rerank
    │
    └──► [run_in_threadpool] dao.xxx()   ← 切断点 2（耗时几毫秒）
              └─► 同步：SQLAlchemy + pymysql
```

**判断依据是一条时间线**：

| 操作 | 耗时 | 处理方式 | 理由 |
|---|---|---|---|
| LLM 生成 | 10—20 秒 | **必须异步** | 占整个请求 90% 的时间，扔线程池等于回到 Flask |
| 向量检索 + 重排 | 0.3—0.8 秒 | 线程池 | 占比小，改造成本高（Milvus SDK、rerank 都是同步的） |
| MySQL 查询 | 几毫秒 | 线程池 | 改异步要换驱动，收益几乎为零 |

**一句话原则：异步要花在"等得最久"的地方，不是"所有地方"。**

全链路异步听起来很美，但把 MySQL 驱动换掉、把 Milvus SDK 包成异步，
工作量翻三倍，性能提升不到 5%。不值。

### 3.3 三种处理同步代码的方式

#### 方式一：`run_in_threadpool`（推荐，最常用）

```python
from fastapi.concurrency import run_in_threadpool

# 位置参数
hits = await run_in_threadpool(retrieve, db, query)

# 关键字参数要这样传（run_in_threadpool 只接受位置参数 + **kwargs）
hits = await run_in_threadpool(
    retrieve, db, query, domain="labor", top_k=8, rerank_n=4
)
```

它从 anyio 的线程池取一个线程执行，**不阻塞事件循环**。
默认线程池上限约 40 个，够用。

#### 方式二：在 `def`（非 async）函数里直接写同步代码

```python
@router.get("/health")
def health(db: Session = Depends(get_db)):     # 注意：没有 async
    return Result.ok(system_service.health(db))
```

FastAPI 看到 `def`（不是 `async def`），会自动把它**整个函数**丢到线程池执行。
函数体里的同步代码不用改。

**适用场景**：整个接口都是同步的（比如健康检查、纯 CRUD），
直接写 `def` 最省事。

**不适用场景**：SSE 流式接口 —— 这里有个坑，见下面 3.4。

#### 方式三：换成异步库（成本最高）

```python
# httpx 的异步版本
async with httpx.AsyncClient() as client:
    resp = await client.post(...)
```

只建议用在 **LLM 客户端**这种"耗时占大头"的地方。

### 3.4 ⚠️ SSE 的三种写法，只有一种是对的

```python
# ❌ 写法一：同步生成器 + StreamingResponse
@router.post("/stream")
async def chat_stream(payload: ChatRequest):
    return StreamingResponse(sync_generator(payload), ...)
# 问题：Starlette 会把同步生成器丢进线程池迭代，
#      每个连接占一个线程 —— 和 Flask 一模一样，白改。
```

```python
# ❌ 写法二：async 生成器里消费同步阻塞代码
async def sse_stream(payload):
    for event in agent_service.stream_answer(...):   # ← 同步 for，阻塞整个事件循环
        yield _sse(event)
# 问题：for 循环里的同步迭代器会卡住事件循环，
#      所有并发请求一起卡死 —— 比 Flask 还惨。
```

```python
# ✅ 写法三：async 生成器 + 内部全异步 + 同步部分包线程池
async def sse_stream(payload):
    db = SessionLocal()
    try:
        async for event in agent_service.stream_answer(db, ...):   # ← async for
            yield _sse(event)
    finally:
        db.close()
```

配套地，`agent_service.stream_answer` 也必须改成 `async def` + `yield`：

```python
async def stream_answer(db, cfg, query, ...):
    # 同步操作包线程池
    hits = await run_in_threadpool(retrieve, db, query, ...)

    # 异步流式生成
    async for piece in llm.astream_chat(messages):
        yield {"type": "delta", "text": piece}
```

**这就是为什么迁移工作量是 4—5 小时而不是 1 小时** ——
不是换路由写法，是打通这条异步链。

---

## 四、代码对照速查表

### 4.1 路由与参数

| 需求 | Flask | FastAPI |
|---|---|---|
| 定义路由 | `@bp.get("/x")` | `@router.get("/x")` |
| 路径参数 | `@bp.get("/<id>")` → `def f(id)` | `@router.get("/{id}")` → `def f(id: str)` |
| 查询参数 | `request.args.get("k", "")` | `k: str = Query(default="")` |
| 请求体 | `request.get_json()` | `payload: ChatRequest` |
| 表单 | `request.form["k"]` | `k: str = Form(...)` |
| 文件 | `request.files["f"]` | `f: UploadFile = File(...)` |
| 请求头 | `request.headers.get("X")` | `x: str = Header(default="")` |

### 4.2 响应

| 需求 | Flask | FastAPI |
|---|---|---|
| 返回 JSON | `jsonify(d)` | `return d` |
| 自定义状态码 | `return d, 201` | `@router.post(..., status_code=201)` |
| 流式响应 | `Response(gen, mimetype=...)` | `StreamingResponse(agen, media_type=...)` |
| 文件下载 | `send_file(path)` | `FileResponse(path)` |
| 重定向 | `redirect(url)` | `RedirectResponse(url)` |

### 4.3 应用与中间件

| 需求 | Flask | FastAPI |
|---|---|---|
| 创建应用 | `Flask(__name__)` | `FastAPI(lifespan=...)` |
| 注册路由 | `app.register_blueprint(bp)` | `app.include_router(router)` |
| CORS | `CORS(app, resources={...})` | `app.add_middleware(CORSMiddleware, ...)` |
| 中间件 | `@app.before_request` | `@app.middleware("http")` |
| 异常处理 | `@app.errorhandler(E)` | `@app.exception_handler(E)` |
| 启动钩子 | `before_request` + flag | `lifespan` |
| 请求级对象 | `flask.g` | `Depends` |
| 启动命令 | `python app.py` | `uvicorn main:app` |

### 4.4 获取请求上下文

| 需求 | Flask | FastAPI |
|---|---|---|
| 当前请求 | `from flask import request` 直接 import | `async def f(request: Request)` 作为参数 |
| 当前应用 | `from flask import current_app` | `request.app` |
| 客户端 IP | `request.remote_addr` | `request.client.host` |
| 请求方法 | `request.method` | `request.method` |
| 完整 URL | `request.url` | `str(request.url)` |

> **Flask 用"全局导入"，FastAPI 用"参数传递"**。
> 这是两者哲学差异最直观的体现：Flask 依赖上下文变量（隐式），
> FastAPI 依赖函数参数（显式）。显式的好处是能单测、能被 IDE 补全。

---

## 五、改造顺序：从里到外

异步是"从下往上传染"的，所以改的顺序也必须从下往上。
每一步都能单独测，不要一次改完再跑。

### Step 1：llm/client.py 加异步方法（不动原有的）

```python
async def astream_chat(self, messages, ...) -> AsyncGenerator[str, None]:
    ...
```

**验证**：

```python
import asyncio
async def test():
    async for piece in LLMClient().astream_chat([{"role":"user","content":"你好"}]):
        print(piece, end="")
asyncio.run(test())
```

能打出字就算通过。此时整个 Web 层还没动，项目照常跑。

### Step 2：agent_service 改 async generator

`stream_answer` 从 `def` 改 `async def`，`yield` 保留。
内部 `retrieve()` 包 `run_in_threadpool`。

**验证**：

```python
async def test():
    async for ev in stream_answer(db, cfg, "试用期多久"):
        if ev["type"] == "answer":
            print(ev["answer"][:100])
asyncio.run(test())
```

### Step 3：chat_service 改 async generator

`sse_stream` 改 `async def`，内部 `async for` 消费 `stream_answer`。

**验证**：此时还没有 FastAPI 路由，写个临时脚本打印 SSE 帧即可。

### Step 4：新建 schemas/，写 Pydantic 模型

按 `api/` 下现有接口反推模型。这一步不涉及运行，纯写代码。

### Step 5：重写 api/ 六个文件

对照第 4 节的速查表逐条改。建议一次改一个文件，改完 `curl` 验一下。

### Step 6：重写 main.py，联调

到这一步 Flask 版可以保留在另一个目录（你已经有备份了），
FastAPI 版独立跑，两边对比行为。

---

## 六、六个常见误区

### 误区 1：「FastAPI 必须全异步」

**错。** 用 `def` 定义的路径函数会被自动丢到线程池，不阻塞事件循环。

```python
@router.get("/health")
def health():              # 没有 async，照样正常
    return {"ok": True}
```

**判断标准**：这个接口里有没有需要 `await` 的东西。有就 `async def`，没有就 `def`。

### 误区 2：「`Depends` 是依赖注入框架」

**不准确。** 它只是个"参数预处理器"：框架在调用函数前先调 `get_db()`，
把结果塞进参数。没有容器、没有 bean 生命周期、没有作用域管理。

```python
def get_db():
    db = SessionLocal()
    try:
        yield db          # ← yield 之前是准备，之后是清理
    finally:
        db.close()
```

读懂这个 `yield` 就懂 `Depends` 了。

### 误区 3：「`await` 一个同步函数就行」

**会报错。** `await` 后面必须是 awaitable（协程、Future、Task）。

```python
# ❌ TypeError: object dict can't be used in 'await' expression
result = await retrieve(db, query)

# ✅ 包线程池
result = await run_in_threadpool(retrieve, db, query)
```

### 误区 4：「忘了 `await`，代码不报错但没执行」

这是异步里最阴的 bug：

```python
# ❌ 没有 await —— 协程对象创建了但从未执行，answer 是个 coroutine 对象
answer = llm.achat(messages)
print(answer)          # <coroutine object ...>

# ✅
answer = await llm.achat(messages)
```

Python 会打一条 `RuntimeWarning: coroutine was never awaited`，但很容易被日志淹没。
**排查技巧**：看到输出里出现 `<coroutine object>` 就是漏了 `await`。

### 误区 5：「异步一定比同步快」

**单请求不变快，甚至略慢**（事件循环有调度开销）。

异步的收益在**并发**：Flask 100 个并发要 100 个线程，
FastAPI 100 个并发只要 100 个协程（几 MB 内存）。

所以被问到时说"异步让单个请求更快"是错的，要说"异步让单机承载更多并发连接"。

### 误区 6：「`StreamingResponse` 可以用同步生成器」

**能跑，但等于白改**。Starlette 会把同步生成器丢进线程池迭代，
每个连接占一个线程 —— 和 Flask 的行为一模一样。

必须用 `async def` + `yield` 的异步生成器，且在它内部 `async for`。

---

## 七、改造后的验证清单

按顺序跑，每一行都是能实际执行的检查。

```
□ 1.  python main.py 能起来，日志无异常
□ 2.  浏览器打开 http://127.0.0.1:8000/docs，六个模块的接口都在
□ 3.  curl /api/health 返回 {"code":0,...,"status":"ok"}
□ 4.  curl /api/statutes/laws 返回 32 部法律
□ 5.  前端 npm run dev，页面能加载、会话列表有数据
□ 6.  发一条消息，SSE 能流式吐字（不是等全部完成才出现）
□ 7.  点"停止生成"，已生成内容进了数据库（刷新还在）
□ 8.  psutil 看线程数：10 个并发对话，线程数不该涨 10 个
□ 9.  切成 glm-5.3-flash，确认 reasoning 不外泄、回答是中文
□ 10. backend 停掉，前端能显示"无法连接后端"而不是白屏
```

第 8 条是判断"异步改造是否成功"的关键指标。
如果 10 个并发让线程数涨了 10，说明某处还在用同步生成器，回去查 3.4。

---

## 附：一句话总结每一层

| 层 | 改造要点 | 一句话 |
|---|---|---|
| `main.py` | 重写 | `lifespan` 替代 `before_request` + 标志位 |
| `api/` | 重写 | `Blueprint`→`APIRouter`，`request`→函数参数 |
| `schemas/` | 新增 | Pydantic 模型，一份代码干解析 + 校验 + 文档三件事 |
| `service/` | 改签名 | `def`→`async def`，同步调用包 `run_in_threadpool` |
| `llm/client.py` | 加方法 | 异步版和同步版并存，脚本用同步、Web 用异步 |
| `dao/` | 不动 | SQLAlchemy 与框架无关 |
| `rag/` | 不动 | 检索逻辑与框架无关 |
| `common/result.py` | 不动 | 返回 dict，FastAPI 直接能序列化 |
| `config.py` | 不动 | 纯配置 |
| 前端 | 不动 | 接口路径和 SSE 帧格式保持一致即可 |
