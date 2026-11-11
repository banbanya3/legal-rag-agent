"""MCP 服务自检脚本：用 Python 扮演 Client，直接跟 server 说 JSON-RPC。

用途：不装 Claude Desktop / Cursor 也能验证 MCP 服务是否正常。

用法：

    cd backend
    python test_mcp.py

它做的事：

    1. 以子进程方式启动 mcp_server.py（和真实客户端一样）
    2. 建立 stdio 连接，做协议握手
    3. 列出所有工具
    4. 依次调用三个工具，打印结果

为什么要有这个脚本：

    MCP 的调试比普通 HTTP 麻烦 —— 它的通信走 stdin/stdout，
    你在终端里手动敲 JSON 很容易把协议帧写坏。
    这个脚本把"扮演客户端"这件事封装好了，改代码后跑一遍就知道有没有问题。

注意：
    - 不需要后端在跑（get_article / list_laws 直连 MySQL）
    - 只有 search_law 会调后端，后端没起时它会自动降级成关键词检索
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent

try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except ImportError:
    print("缺少依赖：mcp")
    print("安装： python -m pip install mcp")
    sys.exit(1)


def _line(char: str = "─", width: int = 68) -> str:
    return char * width


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(BACKEND_DIR / "mcp_server.py")],
        cwd=str(BACKEND_DIR),          # server 里用的是相对路径，必须指定工作目录
    )

    print(_line("═"))
    print("MCP 服务自检")
    print(_line("═"))

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            # ---------- 1. 握手 ----------
            info = await session.initialize()
            print("✓ 协议握手成功")
            print(f"  服务名  : {info.server_info.name}")
            print(f"  协议版本: {info.protocol_version}")
            if info.instructions:
                first = info.instructions.strip().splitlines()[0]
                print(f"  说明    : {first[:60]}")

            # ---------- 2. 工具清单 ----------
            tools = (await session.list_tools()).tools
            print(f"\n✓ 发现 {len(tools)} 个工具")
            for tool in tools:
                desc = (tool.description or "").strip().splitlines()
                # 每个工具的 docstring 第一行就是给模型看的功能说明
                print(f"  · {tool.name:14} {desc[0][:50] if desc else ''}")

            # ---------- 3. 逐个调用 ----------
            print(f"\n{_line()}")
            print("调用测试")
            print(_line())

            cases = [
                ("list_laws", {"domain": "labor"}, "列出劳动法领域的法律"),
                ("get_article", {"law_name": "劳动合同法", "article_no": "19"},
                 "按条号精确查（传阿拉伯数字，内部会转中文）"),
                ("search_law", {"query": "老板不给加班费", "top_k": 3},
                 "语义检索（需要后端在跑，否则自动降级）"),
            ]

            failures = 0
            for name, args, note in cases:
                print(f"\n▸ {name}  —— {note}")
                try:
                    result = await session.call_tool(name, args)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ✗ 调用失败：{type(exc).__name__}: {exc}")
                    failures += 1
                    continue

                text = "\n".join(
                    block.text for block in result.content if hasattr(block, "text")
                )
                if getattr(result, "isError", False):
                    print(f"  ✗ 工具返回错误：{text[:200]}")
                    failures += 1
                    continue

                preview = text.strip().splitlines()
                print(f"  ✓ 返回 {len(text)} 字")
                for line in preview[:3]:
                    print(f"    {line[:64]}")

            # ---------- 4. 结论 ----------
            print(f"\n{_line('═')}")
            if failures == 0:
                print(f"结论：全部通过（{len(cases)} 个工具）")
                print("下一步：按 docs/08-MCP服务接入.md 第 3 节配到 Claude Desktop / Cursor")
            else:
                print(f"结论：{failures} 个工具失败，检查上面的报错")
            print(_line("═"))
            return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
