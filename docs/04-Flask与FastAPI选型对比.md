# Flask 与 FastAPI 选型对比（含迁移指引）

> 用途：技术选型笔记 + 后续迁移到 FastAPI 时的操作手册。
>
> 一句话结论：**从工程角度推荐 FastAPI，但当前项目保留 Flask 不返工** ——  
> 差距不在「能用不能用」，在「SSE 的并发模型」和「追问的深度」。
>
> 第五节的迁移指引是给我自己以后照着做的：哪些文件要改、哪些一行不用动、工作量怎么估。

---

## 一、先记住三个判断

1. **框架不决定项目上限，但决定提问者往哪问。**  
   用 Django 讲出深度能拿 offer，用 FastAPI 堆技术但讲不清检索链路照样被刷。
2. **这个项目的技术特征是「长连接 + 长时间等待」**（SSE 一次挂 10—30 秒），  
   这一点让 FastAPI 的异步从"锦上添花"变成"架构匹配度"。
3. **Flask 不是减分项，前提是你能说出它的天花板在哪。**  
   答"Flask 简单"= 没做过技术判断；答"我知道它 SSE 上每连接占一个线程，  
   要演进就换 ASGI" = 有判断力。

---

## 二、本质差异：WSGI vs ASGI

所有表面差异都源于这一个底层区别。

### 2.1 两个协议

|              | WSGI                                   | ASGI                                  |
| ------------ | -------------------------------------- | ------------------------------------- |
| 全称           | Web Server Gateway Interface（PEP 3333） | Asynchronous Server Gateway Interface |
| 调用模型         | 同步函数，一次调用处理一个请求                        | 异步协程，事件循环调度                           |
| 连接模型         | 一个请求占一个线程/进程，直到响应结束                    | 一个协程，等待 IO 时让出控制权                     |
| 支持 WebSocket | ❌                                      | ✅                                     |
| 生命周期事件       | 无标准（靠 before/after 钩子）                 | ✅ lifespan（startup/shutdown）          |
| 代表框架         | Flask、Django（3.0 前）                    | FastAPI、Starlette、Django（3.0+ 部分）     |

**关键差别在于「等待」怎么处理。**

一次 LLM 问答要等 10 秒。这 10 秒里 CPU 什么都不干，纯等网络。

- **WSGI**：线程 A 被这个请求占着，干等。想接第二个用户？再开线程 B。  
  100 个并发 = 100 个线程常驻（每个线程默认 8MB 栈空间）。
- **ASGI**：协程 A 在 `await` 处挂起，事件循环转头处理协程 B、C、D。  
  100 个并发 = 100 个协程，几 MB 内存全搞定。

这就是为什么**流式 LLM 应用天然适合异步** —— 它的时间几乎全花在等模型吐字上。

### 2.2 两个容易搞错的点

**❌ 误区一：Flask 不支持 async**

Flask 2.0+ 支持 `async def` 视图，但底层仍是 WSGI，靠 `asgiref` 做桥接：  
每个 async 请求仍然占一个线程，只是线程里的代码换成了 `asyncio.run()`。  
**并发模型没变**，所以这个特性对 SSE 并发没有实质帮助。

**❌ 误区二：FastAPI 必须全异步**

FastAPI 里用 `def`（不是 `async def`）定义的路径函数，会被自动丢到线程池执行  
（`run_in_threadpool`），**不会阻塞事件循环**。

这意味着：现有同步 SQLAlchemy 代码可以原样搬过去，不用改成 async 驱动。  
但线程池默认上限约 40 个（anyio 的默认配置），超过就排队。

> 这一点对迁移很关键 —— 见第五节。

---

## 三、逐项对比

| 维度     | Flask                              | FastAPI                        | 对本项目的影响          |
| ------ | ---------------------------------- | ------------------------------ | ---------------- |
| 并发模型   | 同步，1 请求 1 线程                       | 异步，事件循环                        | ⭐ 核心差异，SSE 直接受影响 |
| SSE 实现 | `Response(generator)` + 线程         | `StreamingResponse(async_gen)` | ⭐ 迁移必改           |
| 参数校验   | 手写 if/else，或 marshmallow           | Pydantic 模型，自动 422             | 中                |
| 依赖注入   | `flask.g` + teardown 钩子            | `Depends()` + yield 依赖         | 中                |
| 接口文档   | 手写 / flasgger / apispec            | 内置 OpenAPI，`/docs` 直接打开        | ⭐ 现场演示更直观         |
| 请求体解析  | `request.get_json()`               | 自动反序列化成模型对象                    | 小                |
| 中间件    | `before_request` / `after_request` | `@app.middleware("http")`      | 小                |
| 错误处理   | `@app.errorhandler`                | `@app.exception_handler`       | 小                |
| 生态成熟度  | 极成熟，教程满地                           | 成熟，但中文资料少一些                    | 小                |
| 上手成本   | 低，一天能写                             | 中，要懂 async/await               | 小                |
| 求职市场   | 传统企业 / 外包 / 中小厂                    | AI 应用 / 创业公司 / 新项目             | 取决于目标岗位          |
| 典型追问   | 并发怎么办、为什么不用 async                  | async 里混同步会怎样、Depends 原理       | ⭐ 见第六节           |

---

## 四、对本项目的具体影响

### 4.1 Flask 版的 SSE 长什么样

```python
# api/chat_api.py
@bp.post("/stream")
def chat_stream():
    session_id, query, use_rerank = _read_payload()
    return Response(
        chat_service.sse_stream(session_id, query, use_rerank),
        headers=SSE_HEADERS,
        status=200,
    )

# service/chat_service.py —— 同步生成器
def sse_stream(session_id, query, use_rerank=None):
    db = SessionLocal()          # 自己在生成器里开 session
    try:
        for event in agent_service.stream_answer(db, cfg, query, ...):
            yield _sse(event)
    finally:
        db.close()
```

跑在 `app.run(threaded=True)` 下：**每个连接一个线程**。  
演示 1—2 个用户没问题，10 个并发就是 10 个线程同时挂着等 LLM。

### 4.2 FastAPI 版会变成什么样

```python
# api/chat_api.py
@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, db: Session = Depends(get_db)):
    return StreamingResponse(
        sse_stream(payload, db),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )

# service/chat_service.py —— 异步生成器
async def sse_stream(payload, db):
    async for event in agent_service.stream_answer(db, payload.query, ...):
        yield _sse(event)
```

**但这里有个陷阱** —— 见 4.3。

### 4.3 ⚠️ 只换路由 = 白改

如果 `agent_service.stream_answer` 还是同步生成器、`llm.stream_chat` 还是  
`httpx.Client`（同步），那 FastAPI 里的 async generator 会在 `for` 循环里  
直接消费同步阻塞代码 —— **整个事件循环被卡住**，比 Flask 还惨。

Flask 至少是"一个线程卡住"，FastAPI 是"所有请求一起卡住"。

所以要拿到异步的收益，必须把 **LLM 客户端也改成异步**：

```python
# llm/client.py 需要新增
async def astream_chat(self, messages, ...) -> AsyncGenerator[str, None]:
    async with httpx.AsyncClient(trust_env=False, timeout=timeout) as client:
        async with client.stream("POST", url, json=payload, headers=...) as resp:
            async for line in resp.aiter_lines():
                ...
                yield piece
```

**这是迁移工作量的真实来源。** 我上次说"1—2 小时只改 api 层"，那个评估是错的，  
在这里修正：**3—5 小时**，主要花在异步 LLM 客户端和链路联调上。

### 4.4 哪些能不动

| 层                          | 要不要改     | 说明                                            |
| -------------------------- | -------- | --------------------------------------------- |
| `config.py`                | ❌ 不改     | 纯配置                                           |
| `dao/models.py`            | ❌ 不改     | SQLAlchemy ORM，与框架无关                          |
| `dao/*_dao.py`             | ❌ 不改     | 同步 CRUD，FastAPI 可以跑同步                         |
| `rag/*.py`                 | ⚠️ 部分    | 检索是同步的，用 `run_in_threadpool` 包一层即可            |
| `llm/prompts.py`           | ❌ 不改     | 纯字符串                                          |
| `llm/client.py`            | ✅ **要改** | 新增异步版本，这是关键                                   |
| `service/agent_service.py` | ✅ 要改     | `stream_answer` 改 async generator             |
| `service/chat_service.py`  | ✅ 要改     | `sse_stream` 改 async generator                |
| `service/` 其余              | ⚠️ 小改    | 同步 service 调用改 `await run_in_threadpool(...)` |
| `api/*.py`                 | ✅ 要重写    | 6 个文件                                         |
| `common/result.py`         | ⚠️ 小改    | `jsonify` 改成直接 `return dict`                  |
| `app.py`                   | ✅ 要重写    | 应用工厂 + lifespan + CORS                        |
| `init_knowledge.py`        | ❌ 不改     | 纯脚本，与 Web 框架无关                                |
| 前端                         | ❌ 不改     | 接口路径和 SSE 格式保持一致即可                            |

---

## 五、迁移指引（Flask → FastAPI）

### 5.1 工作量评估

| 阶段     | 内容                                         | 预估          |
| ------ | ------------------------------------------ | ----------- |
| 1      | `llm/client.py` 加 `achat` / `astream_chat` | 1 h         |
| 2      | `agent_service` 改 async generator          | 1 h         |
| 3      | `chat_service` 改 async generator（含断线保存）    | 0.5 h       |
| 4      | `api/` 六个文件重写（路由 + 依赖 + 异常）                | 1.5 h       |
| 5      | `app.py` + 启动方式 + 联调                       | 0.5—1 h     |
| **合计** |                                            | **4.5—5 h** |

### 5.2 分步操作

**Step 1：先加异步客户端，不动别的**

在 `llm/client.py` 里新增方法，保留原有同步方法（`init_knowledge.py` 还要用）。  
这样第一步就能单独测试：`python -c "asyncio.run(client.astream_chat(...))"`。

**Step 2：改 agent_service**

`stream_answer` 从 `def` + `yield` 改成 `async def` + `yield`。  
内部调用检索的地方包一层：

```python
hits = await run_in_threadpool(retrieve, db, query, ...)
```

**Step 3：改 chat_service**

同步的 `SessionLocal()` 保留，不要换成 async engine ——  
SQLAlchemy 的 async 需要 `asyncmy` 或 `aiomysql` 驱动，改造成本高、收益低。  
用 `run_in_threadpool` 跑同步 DB 操作即可。

**Step 4：重写 api 层**

对照表：

| Flask                          | FastAPI                            |
| ------------------------------ | ---------------------------------- |
| `Blueprint(url_prefix="/api")` | `APIRouter(prefix="/api")`         |
| `@bp.get("/x")`                | `@router.get("/x")`                |
| `request.args.get("k")`        | `k: str = Query(default="")`       |
| `request.get_json()`           | Pydantic 模型作为参数                    |
| `jsonify(Result.ok(d))`        | `return Result.ok(d)`（dict 自动序列化）  |
| `@app.errorhandler(BizError)`  | `@app.exception_handler(BizError)` |
| `before_request` 建库            | `@asynccontextmanager lifespan`    |
| `Response(gen)`                | `StreamingResponse(async_gen)`     |

**Step 5：注意这几个坑**

1. **`Depends(get_db)` 在流式响应里会提前关闭**  
   FastAPI 的 yield 依赖在响应开始发送后就退出。所以 SSE 接口不要用  
   `Depends(get_db)`，在生成器内部自己开 session —— 和 Flask 版的处理思路一样。
2. **`StreamingResponse` 必须用 `async def` 生成器**  
   用同步生成器也能跑，但 Starlette 会把它丢进线程池迭代，  
   又回到"一个连接一个线程"，等于白改。
3. **CORS 对 SSE 的处理**  
   `CORSMiddleware` 要显式 `expose_headers`，否则前端拿不到某些响应头。
4. **`use_reloader` 的坑变成 `--reload`**  
   uvicorn 的 reload 也是起两个进程，Milvus Lite 依然会抢锁。  
   开发时用 `uvicorn app:app --reload`，但重建索引前要停掉。

### 5.3 迁移后的验证清单

- [ ] `/docs` 能打开，六个模块的接口都在
- [ ] SSE 首字延迟和 Flask 版持平（异步不该变慢）
- [ ] 并发 10 个对话，线程数不涨（用 `psutil` 看）
- [ ] 断线保存仍生效（点停止生成，内容进了数据库）
- [ ] 推理模型的 reasoning 过滤仍然有效
- [ ] `init_knowledge.py --build` 不受影响（它不走 Web 层）

---

## 六、常见问题

### 6.1 被问「为什么用 Flask」

> 这个项目我用 Flask，但我认真评估过 FastAPI。
>
> 选 Flask 有两个原因：一是目标岗位的技术栈以 Flask/Django 为主，来了能直接上手；  
> 二是这个项目的 IO 瓶颈不在框架 —— 主要在 LLM 生成（10—20 秒）和向量检索  
> （几十毫秒），同步模型配线程池完全够用。
>
> 但我知道它的天花板：SSE 每个连接占一个线程，并发上到几十就要换方案。  
> 真要上生产我有两条路 —— gunicorn + gevent 做协程化，或者换 FastAPI 用原生 ASGI。
>
> 如果重做，我会选 FastAPI。因为 LLM 应用的长连接特性天然适合异步，  
> 这不是框架偏好，是架构匹配度。

### 6.2 被问「Flask 怎么实现流式输出」

> `Response` 包一个生成器，`mimetype` 设 `text/event-stream`。
>
> 有个必须处理的坑：Flask 的请求上下文在视图函数 return 之后就回收了，  
> 而流式响应是 return 之后才开始吐数据。所以生成器内部不能用视图注入的 db session，  
> 得自己开一个，在 finally 里关掉。不处理会在生成到一半时报  
> `MySQL server has gone away`。

### 6.3 被问「并发高了怎么办」

> 分两层看。
>
> 应用层：Flask 用 gunicorn + gevent worker，把同步代码协程化，  
> 单机能撑几百个并发连接。
>
> 架构层：SSE 的本质问题是「长连接占资源」，Redis Pub/Sub 加一层消息中转，  
> 把"请求-响应"解耦成"提交任务 + 订阅结果"，连接数就不再和用户数强绑定。
>
> 但如果一开始就预期高并发，我会直接用 FastAPI，不用先踩一遍再改。

### 6.4 反过来：如果你用了 FastAPI 会被问什么

准备好这三个，答不上来会很尴尬：

| 追问                                              | 要点                                                                          |
| ----------------------------------------------- | --------------------------------------------------------------------------- |
| `async def` 里调同步 MySQL 驱动会怎样？                   | 阻塞事件循环，所有请求一起卡死。要用 `run_in_threadpool` 或 async 驱动                           |
| `Depends` 的依赖是每次请求新建吗？                          | 普通函数默认每次请求调用；`yield` 依赖在响应结束后清理；`lru_cache` 或 `Depends(use_cache=True)` 可缓存 |
| 为什么 `StreamingResponse` 里不能用 `Depends(get_db)`？ | 依赖在响应开始时就退出，session 被关，生成器里再用会报错                                            |



---

## 七、决策清单

按顺序问自己：

1. **目标岗位的 JD 里写的是哪个？**  
   写 FastAPI → 直接选 FastAPI，别纠结。
2. **项目有没有长连接（SSE / WebSocket / 大文件下载）？**  
   有 → 技术上 FastAPI 更合适。没有 → 差异不大，选熟的那个。
3. **你对 asyncio 的理解到什么程度？**  
   只会"加 async 就快了" → 先用 Flask，别在讨论中暴露短板。  
   能讲清事件循环、阻塞、`run_in_threadpool` → FastAPI 是明显优势。
4. **时间够不够？**  
   够（≥1 天）→ 可以迁。不够 → 保留现状，把解释准备好，收益 80% 已经拿到了。

---

## 附：本项目当前状态

| 项      | 值                                            |
| ------ | -------------------------------------------- |
| 框架     | Flask 3.x + flask-cors                       |
| 运行方式   | `app.run(threaded=True, use_reloader=False)` |
| 分层     | api / service / dao / rag / llm / common     |
| 代码量    | 后端约 4700 行 Python                            |
| 迁移状态   | 未迁移，本文档为迁移前评估                                |
| 迁移触发条件 | 目标岗位明确要求 FastAPI，或需要真实高并发演示                  |
