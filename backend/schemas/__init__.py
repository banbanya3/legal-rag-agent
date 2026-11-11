"""Pydantic 请求/响应模型。

按 api 层的模块一一对应：
    chat_schema      对话
    session_schema   会话与消息
    statute_schema   法条检索
    knowledge_schema 知识库管理
    settings_schema  模型设置
    system_schema    健康检查与统计

约定：
    XxxRequest  请求体（前端 → 后端）
    XxxResponse 响应体（后端 → 前端）
    XxxItem     列表里的单项

请求和响应分开写，不要用一个模型打天下 —— 响应里往往要带
elapsed_ms、sources 这类服务端字段，而请求里可能有 api_key 这种
绝不能回传的字段。
"""
