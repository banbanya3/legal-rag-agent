# schemas 层详解：Pydantic 模型到底在做什么

> 前置认知：FastAPI 的分层和 Flask 一模一样（api / service / dao / rag），
> 只多了一个 `schemas/`。这份文档讲清楚它是什么、写什么、为什么需要它。
>
> 一句话：**schemas 层是"接口契约"的代码化表达** ——
> 把一个接口收什么、返回什么，写成可执行的类型定义，
> 而不是散落在函数体里的 if/else 和注释。

---

## 一、先看它解决什么问题

### 1.1 Flask 版现在的写法

打开 `api/chat_api.py`，接口长这样：

```python
def _read_payload() -> tuple[str, str, bool | None]:
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
```

这 15 行代码做了四件事：**解析 JSON、取字段、类型转换、校验范围**。

它本身没错，但有四个问题：

| 问题 | 具体表现 |
|---|---|
| **重复** | 6 个接口文件、20 多个入参，每个都要写一遍类似的 if/else |
| **散落** | 校验规则在函数体里，和业务逻辑混在一起，改规则要翻代码 |
| **不完整** | 只校验了"非空"和"长度"，没校验类型（传 `{"query": 123}` 会怎样？） |
| **文档另写** | `docs/02-接口文档.md` 是手写的，改代码时经常忘了同步 |

### 1.2 FastAPI 版的写法

```python
# schemas/chat_schema.py
class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    query: str = Field(..., min_length=1, max_length=2000)
    use_rerank: bool = True
```

```python
# api/chat_api.py —— 校验代码全部消失
@router.post("/stream")
async def chat_stream(payload: ChatRequest):
    # 走到这里时，框架已经保证：
    #   payload.session_id 是 1—64 字符的字符串
    #   payload.query      是 1—2000 字符的字符串
    #   payload.use_rerank 是布尔值
    ...
```

**同样是 15 行校验代码，现在变成了 3 行声明，而且顺带解决了上面四个问题。**

---

## 二、schemas 层在请求链路里的位置

```
                    ┌──────────────────────────┐
   浏览器 POST       │  ChatRequest             │
   {"query":"...",  │  ├─ 解析 JSON            │
    "session_id":..}│  ├─ 类型转换             │  ← 入口：把关
   ─────────────────►  ├─ 校验规则             │
                    │  └─ 不通过返回 422       │
                    └──────────┬───────────────┘
                               │ 通过，变成一个对象
                               ▼
                    ┌──────────────────────────┐
                    │  service / dao / rag     │  ← 中间：业务逻辑（不管校验）
                    └──────────┬───────────────┘
                               │ 返回 dict / ORM 对象
                               ▼
                    ┌──────────────────────────┐
   浏览器收到         │  ChatResponse            │
   {"code":0,...}   │  ├─ 按模型过滤字段        │  ← 出口：把关
   ◄─────────────────  ├─ 校验类型              │
                    │  └─ 生成文档              │
                    └──────────────────────────┘
```

**两个把关点：入口（请求）和出口（响应）。**

这也是为什么请求模型和响应模型要分开写 —— 它们守的是两个方向的门。

---

## 三、一个完整的例子：chat_schema.py

这份文件可以直接抄到项目里用。逐行注释。

```python
"""对话相关的请求/响应模型。

命名约定：
  XxxRequest   请求体（前端 → 后端）
  XxxResponse  响应体（后端 → 前端）
  XxxItem      列表里的单项
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ===========================================================================
# 请求模型
# ===========================================================================
class ChatRequest(BaseModel):
    """POST /api/chat 和 /api/chat/stream 的请求体。"""

    session_id: str = Field(
        ...,                    # ... 是 Ellipsis，表示"必填，没有默认值"
        min_length=1,           # 空字符串会被拒绝
        max_length=64,          # 防止超长字符串进数据库
        description="会话唯一标识，前端生成的 s_xxx",
        examples=["s_abc123"],
    )
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,        # 和业务里"问题不能超过 2000 字"对齐
        description="用户问题",
        examples=["试用期最长可以约定多久？"],
    )
    use_rerank: bool = Field(
        default=True,           # 有默认值 → 非必填
        description="是否开启精排，不传则用服务端配置",
    )

    # 允许前端多传字段（比如埋点参数），不报错
    model_config = ConfigDict(extra="ignore")


class DirectChatRequest(BaseModel):
    """直聊模式的请求体（跳过检索，纯模型回答）。"""

    session_id: str = Field(..., min_length=1, max_length=64)
    query: str = Field(..., min_length=1, max_length=2000)
    history_limit: int = Field(
        default=10,
        ge=0,                   # ge = greater or equal，大于等于 0
        le=40,                  # le = less or equal，小于等于 40
        description="携带多少条历史消息",
    )


# ===========================================================================
# 响应模型的子结构
# ===========================================================================
class SourceItem(BaseModel):
    """一条"引用的法条"，对应 retrieval.to_source_payload() 的产出。"""

    title: str = Field(description="展示用标题，如《劳动合同法》第十九条【试用期期限】")
    text: str = Field(description="条文或解读的正文片段")
    score: float | None = Field(
        default=None,
        ge=0.0,                 # 余弦相似度范围 [-1, 1]，这里按业务约束到 [0, 1]
        le=1.0,
        description="向量相似度，前端显示成百分比",
    )
    rerank_score: float | None = Field(
        default=None,
        description="精排分，仅内部排序用，通常不展示",
    )
    law_name: str = ""
    article_no: str = ""
    domain: str = ""
    domain_label: str = ""
    filename: str = ""
    kind: Literal["article", "passage"] = "passage"
    reranked: bool = False
    source: Literal["vector", "expanded", "structured"] = "vector"


class ChatResponse(BaseModel):
    """非流式对话的响应体。"""

    session_id: str
    answer: str
    sources: list[SourceItem] = Field(default_factory=list)
    elapsed_ms: int = Field(default=0, ge=0)


# ===========================================================================
# 流式事件（SSE）
# ===========================================================================
class StreamEvent(BaseModel):
    """SSE 单帧的结构。

    注意：**这个模型不用于 FastAPI 的 response_model**，
    因为 SSE 是手动拼 data: {...}\n\n 的，不走 FastAPI 的序列化。
    写在这里的目的是：① 文档化事件格式；② 单元测试时用来校验帧内容。
    """

    type: Literal["status", "sources", "delta", "answer", "done", "error"]
    stage: str | None = None
    message: str | None = None
    text: str | None = None
    answer: str | None = None
    sources: list[SourceItem] | None = None
    elapsed_ms: int | None = None
    intent: str | None = None
    domain: str | None = None
```

---

## 四、逐行讲清楚几个关键点

### 4.1 为什么写 `str` 就能自动转换

```python
class ChatRequest(BaseModel):
    use_rerank: bool = True
```

前端传 `{"use_rerank": "true"}`（字符串），Pydantic 会**自动转成 `True`**。

前端传 `{"use_rerank": "yes"}` → 报错，因为 `"yes"` 不在 Pydantic 的布尔识别列表里
（它只认 `true/false`、`1/0`、`"yes"/"no"`、`"on"/"off"` 这些）。

**这个行为叫"宽松模式"（lax mode），是 Pydantic v2 的默认值。**
好处是前端不用小心翼翼地传正确类型；坏处是可能掩盖前端 bug ——
如果需要严格模式，用 `StrictBool`。

同理：

```python
class Foo(BaseModel):
    age: int

Foo(age="18")      # ✅ 通过，age 变成 18（int）
Foo(age="十八")     # ❌ 报错
Foo(age=18.6)      # ✅ 通过，变成 18（截断，不四舍五入）
```

### 4.2 `...`（Ellipsis）是什么

```python
session_id: str = Field(...)      # 必填
query: str = Field(default="")    # 非必填，默认空串
```

`...` 在 Python 里是个真实对象（`Ellipsis`），Pydantic 借用它表示"没有默认值，必须传"。

**等价写法**：

```python
session_id: str                   # 也是必填（不写 Field 时）
session_id: str = Field(...)      # 显式必填（要加校验规则时必须这样写）
```

只要你想加 `min_length` 这类约束，就必须用 `Field(...)`。

### 4.3 `Field` 的常用参数

| 参数 | 作用 | 例子 |
|---|---|---|
| `...` / `default` | 必填 / 默认值 | `Field(...)`、`Field(default=10)` |
| `min_length` / `max_length` | 字符串长度 | `Field(..., max_length=2000)` |
| `ge` / `le` | 数值范围（含边界） | `Field(default=8, ge=1, le=30)` |
| `gt` / `lt` | 数值范围（不含边界） | `Field(default=0.1, gt=0)` |
| `pattern` | 正则匹配 | `Field(..., pattern=r"^s_[a-z0-9]+$")` |
| `description` | 文档里显示的说明 | `Field(..., description="会话 ID")` |
| `examples` | 文档里的示例值 | `Field(..., examples=["s_abc"])` |
| `alias` | 别名（前端用驼峰时） | `Field(..., alias="sessionId")` |

**`description` 和 `examples` 不是装饰**：它们会出现在 `/docs` 页面里，
现场演示时打开 Swagger 就能看到每个字段的说明 —— 这是 FastAPI 白送的专业感。

### 4.4 `Literal` 限制取值范围

```python
kind: Literal["article", "passage"] = "passage"
```

只接受这两个值，传 `"chunk"` 会报错。

比 `str` 好在两点：
1. 校验严格，防止下游代码收到预期外的值
2. `/docs` 里会渲染成**下拉选择框**，而不是自由输入框

同样适用于配置类字段：

```python
class LLMSettingIn(BaseModel):
    provider: Literal["zhipu", "deepseek", "qwen", "custom"] = "zhipu"
    model_name: str = Field(..., min_length=1)
```

### 4.5 `default_factory` 而不是 `= []`

```python
# ❌ 危险：可变默认值
class Foo(BaseModel):
    items: list[str] = []

# ✅ 正确
class Foo(BaseModel):
    items: list[str] = Field(default_factory=list)
```

**为什么**：Python 的默认参数在函数定义时求值一次，所有实例共享同一个 list。
一个实例往里 append，另一个实例也会看到 —— 经典的 Python 陷阱。

Pydantic v2 内部其实做了拷贝，`= []` 也能正确工作，但**建议统一用 `default_factory`**：
意图明确，不会让读代码的人犹豫。

---

## 五、请求模型 vs 响应模型：为什么必须分开

这是 schemas 层最重要的设计原则。

### 5.1 反面教材：一个模型打天下

```python
# ❌ 错误示范
class LLMSetting(BaseModel):
    provider: str
    model_name: str
    api_key: str          # 请求时前端传，响应时绝对不能返回
    base_url: str
    temperature: float
```

用这个模型做响应模型，**API Key 会原样返回给浏览器**。

### 5.2 正确做法：拆成 In / Out

```python
class LLMSettingIn(BaseModel):
    """前端保存设置时提交的内容。"""
    provider: Literal["zhipu", "deepseek", "qwen", "custom"] = "zhipu"
    model_name: str = Field(..., min_length=1, max_length=64)
    api_key: str | None = Field(
        default=None,
        description="留空表示沿用已保存的 Key",
    )
    base_url: str = Field(..., min_length=10)
    temperature: float = Field(default=0.1, ge=0.0, le=1.5)
    top_k: int = Field(default=8, ge=1, le=30)
    rerank_n: int = Field(default=4, ge=1, le=10)
    use_rerank: bool = True
    strict_mode: bool = True


class LLMSettingOut(BaseModel):
    """返回给前端的内容 —— 密钥已脱敏，没有 api_key 字段。"""

    provider: str
    model_name: str
    api_key_masked: str = Field(default="", description="脱敏后的 Key，如 c61efd***9GK7")
    has_api_key: bool = False
    base_url: str
    temperature: float
    top_k: int
    rerank_n: int
    use_rerank: bool
    strict_mode: bool
    updated_at: str = ""
```

**两个模型字段不同，这不是冗余，这是安全边界。**

### 5.3 三类字段的归属

| 字段类型 | 请求 In | 响应 Out | 例子 |
|---|---|---|---|
| 用户输入的 | ✅ | ❌ | `api_key`、`query` |
| 服务端生成的 | ❌ | ✅ | `session_id`、`elapsed_ms`、`created_at` |
| 双方都有的 | ✅ | ✅ | `model_name`、`temperature` |

按这张表过一遍，就知道该不该分开。

---

## 六、`response_model` 是一道防泄漏闸门

很多人只把 `response_model` 当成"生成文档用的"，其实它有个更实际的作用：**过滤**。

```python
@router.get("/settings", response_model=LLMSettingOut)
async def read_settings(db: Session = Depends(get_db)):
    cfg = settings_service.get(db)
    return cfg          # ← 假设这个 dict 里意外带上了 api_key
```

FastAPI 会做三件事：

1. **按 `LLMSettingOut` 的字段过滤** —— `api_key` 不在模型里，被丢掉
2. **校验类型** —— 字段类型不匹配会报错（开发期就能发现）
3. **生成文档** —— `/docs` 里显示响应结构

**第 1 点是关键**：即使 service 层不小心把敏感字段带出来了，
只要 `response_model` 里没定义，就不会出现在响应里。

这是一道**兜底防线**，比"记得在 service 里删掉 api_key"可靠得多。

> 类比：`response_model` 相当于前端的 TypeScript 返回值类型 ——
> 它不阻止你返回多余的东西，但它保证"出去的东西符合约定"。

---

## 七、校验失败长什么样

### 7.1 FastAPI 的默认响应（422）

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "query"],
      "msg": "String should have at least 1 character",
      "input": "",
      "ctx": {"min_length": 1}
    }
  ]
}
```

**问题**：这个结构和你的 `{code, message, data}` 信封不一致，
前端 axios 拦截器里的 `if (body.code !== 0)` 会直接跳过，当成成功处理。

### 7.2 必须加一个 handler 转成自己的格式

```python
# main.py 或 api/__init__.py
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    """把 Pydantic 的 422 压成一句人话，保持和业务错误同一个信封。"""
    errors = exc.errors()
    first = errors[0] if errors else {}

    # loc 形如 ("body", "query") 或 ("query", "page")
    # [1:] 是为了跳过 "body"/"query" 这一层，只留字段名
    field = ".".join(str(x) for x in first.get("loc", [])[1:]) or "参数"

    return JSONResponse(
        status_code=400,       # 用 400 而不是 422，和业务错误统一
        content=Result.fail(f"参数 {field} 不合法：{first.get('msg', '')}", 400),
    )
```

**加了这段，前端一行都不用改。**

### 7.3 自定义校验：`field_validator`

内置规则覆盖不到的场景，用校验器：

```python
from pydantic import BaseModel, Field, field_validator


class StatuteQuery(BaseModel):
    keyword: str = Field(default="", max_length=50)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @field_validator("keyword")
    @classmethod
    def strip_keyword(cls, v: str) -> str:
        """去掉首尾空格，避免 " 试用期 " 匹配不到。"""
        return v.strip()

    @field_validator("page_size")
    @classmethod
    def cap_page_size(cls, v: int) -> int:
        """虽然 Field 已经限制了范围，这里演示"超出就取上限"的兜底。"""
        return min(v, 100)
```

> **注意**：校验器只做"格式/范围"这类判断，**不要塞业务逻辑**。
> 比如"这个 session_id 在数据库里存不存在"应该放在 service 层 ——
> 校验层不该碰数据库，否则模型就没法在单测里脱离数据库运行了。

---

## 八、这个项目该怎么划分 schemas

按 api 层的模块一一对应：

```
backend/schemas/
├── __init__.py
├── chat_schema.py        # ChatRequest, DirectChatRequest, ChatResponse, SourceItem
├── session_schema.py     # SessionInfo, MessageInfo, RenameRequest
├── statute_schema.py     # StatuteItem, StatuteQuery, StatuteListResponse
├── knowledge_schema.py   # DomainInfo, FileInfo, RebuildRequest, UploadResult
└── settings_schema.py    # LLMSettingIn, LLMSettingOut, TestRequest, TestResult
```

### 8.1 各文件的具体内容规划

**session_schema.py**

```python
class RenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=60)


class SessionInfo(BaseModel):
    session_id: str
    title: str
    created_at: str
    last_message_at: str | None = None
    message_count: int = 0


class MessageInfo(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    sources: list[SourceItem] = Field(default_factory=list)
    elapsed_ms: int = 0
    created_at: str
```

**statute_schema.py**

```python
class StatuteQuery(BaseModel):
    keyword: str = Field(default="", max_length=50)
    law_name: str = Field(default="", max_length=64)
    domain: str = Field(default="", max_length=32)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class StatuteItem(BaseModel):
    id: int
    law_name: str
    law_short: str
    domain: str
    domain_label: str = ""
    chapter: str = ""
    article_no: str
    heading: str = ""
    content: str
    effective_date: str = ""
    source_file: str = ""


class StatutePage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[StatuteItem]
```

**knowledge_schema.py**

```python
class FileInfo(BaseModel):
    filename: str
    size_kb: float


class DomainInfo(BaseModel):
    domain: str
    label: str
    desc: str
    color: str
    dir: str
    collections: str
    vectors: int = 0
    docs: int = 0
    chunks: int = 0
    articles: int = 0
    statutes: int = 0
    chars: int = 0
    files: list[FileInfo] = Field(default_factory=list)


class RebuildRequest(BaseModel):
    domain: str | None = Field(default=None, description="留空表示全量重建")
    force: bool = Field(default=False, description="true 表示先删集合再重建")
```

**settings_schema.py**（见 5.2 的完整代码）

---

## 九、六个常见坑

### 坑 1：`Optional` 和"有默认值"是两回事

```python
# 三种写法的区别
a: str                                # 必填，且不能是 None
b: str | None                         # 必填，但可以是 null
c: str | None = None                  # 非必填，不传就是 None
d: str = None                         # ❌ 类型和默认值矛盾，Pydantic 会给警告
```

**这个区别很实用**：想表达"这个字段可以不传"，必须给默认值；
只写 `str | None` 的话，前端不传仍然会报错。

### 坑 2：嵌套模型要一层层定义

```python
# ❌ 报错：list 里没指定元素类型，无法校验
class Resp(BaseModel):
    sources: list

# ✅
class Resp(BaseModel):
    sources: list[SourceItem]
```

### 坑 3：ORM 对象转模型要开 `from_attributes`

```python
class SessionInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # ← 关键

    session_id: str
    title: str

# 这样可以：
SessionInfo.model_validate(orm_obj)
```

不加这个配置，只能传 dict，不能传 SQLAlchemy 对象。

**对本项目来说**：dao 层返回的多是 dict（我在 `to_dict()` 里手动转换了），
所以这个配置不是必需的。但如果以后让 dao 直接返回 ORM 对象，就需要它。

### 坑 4：`response_model` 会过滤字段，可能"吃掉"你的数据

```python
@router.get("/x", response_model=Foo)
async def x():
    return {"a": 1, "b": 2, "c": 3}    # Foo 只定义了 a、b
    # 实际返回 {"a": 1, "b": 2}，c 被静默丢弃
```

这个行为**既是保护也是陷阱**：调试时发现"字段莫名其妙没了"，
先检查 `response_model` 有没有漏定义。

### 坑 5：不要在模型里放业务逻辑

```python
# ❌ 错误：模型不该查数据库
class ChatRequest(BaseModel):
    session_id: str

    @field_validator("session_id")
    def check_exists(cls, v):
        if not db.query(ChatSession).get(v):    # 校验层碰了数据库
            raise ValueError("会话不存在")
        return v
```

后果：
- 单测这个模型必须连数据库
- 校验变成 IO 操作，每个请求多一次查询
- 事务边界混乱（校验时开的 session 和业务用的不是同一个）

**正确做法**：格式在模型里校验，存在性在 service 里判断。

### 坑 6：`extra="forbid"` 还是 `"ignore"`

```python
class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")   # 多传的字段直接忽略
    # extra="forbid"  多传字段报错
    # extra="allow"   多传字段保留在 model_extra 里
```

**默认是 `ignore`。** 对前端友好的项目选 `ignore`（前端多传个埋点参数不至于 400），
对内部服务选 `forbid`（严格契约，防止字段名写错却静默通过）。

---

## 十、一句话总结

| 问题 | 答案 |
|---|---|
| schemas 层是什么 | 接口契约的代码化：声明收什么、返回什么 |
| 里面写什么 | Pydantic 的 `BaseModel` 子类，按接口分文件 |
| 为什么要它 | 校验、类型转换、文档、过滤四件事一次解决 |
| 和 service 层什么关系 | schemas 管"形状对不对"，service 管"业务对不对" |
| 一定要用吗 | 用 FastAPI 就一定要 —— 它是框架的原生机制，不用反而别扭 |
| Flask 里有没有对应物 | 没有。Flask 靠手写 if/else + 第三方库（marshmallow），没有统一方案 |

> **最后提醒一句**：schemas 层是"薄"的。一个接口对应一两个模型，
> 加起来几百行，都是声明式代码，没有逻辑。
>
> 如果发现 schemas 文件越写越厚、塞满了 `field_validator`，
> 那说明校验规则写得太复杂了 —— 该考虑把规则挪到 service 层，
> 或者拆接口，而不是继续在模型里堆逻辑。
