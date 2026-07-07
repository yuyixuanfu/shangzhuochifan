#!/usr/bin/env python3
"""买菜游戏 MCP Server

让任何支持MCP的AI客户端直接玩买菜游戏。

启动方式:
  # stdio 模式（Claude Code / Claude Desktop）
  python market_mcp_server.py

  # SSE 模式（Kelivo / Cherry Studio / 其他HTTP客户端）
  python market_mcp_server.py --sse --port 8878

在Claude Code的.mcp.json中添加:
  {
    "mcpServers": {
      "market": {
        "command": "python",
        "args": ["market_mcp_server.py"]
      }
    }
  }

在Kelivo等SSE客户端中配置:
  URL: http://localhost:8878/sse

工具:
  new_game  — 开新局
  play      — 执行指令
  status    — 查看当前状态
"""

import sys
import os
import io

# UTF-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 确保引擎目录在path里
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from mcp.server import Server
from mcp.types import Tool, TextContent

import engine

app = Server("market-game")


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="new_game",
            description=(
                "开一局新的买菜游戏。返回开场文字和状态。可选指定seed保证结果可复现。\n\n"
                "重要：开完新局后，你要把场景内容用自然语言讲给人类听——像讲故事一样。"
                "然后问人类想做什么。不要自己替人做决定。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "seed": {
                        "type": "integer",
                        "description": "随机种子，相同seed=相同菜场。不填则随机。",
                    }
                },
            },
        ),
        Tool(
            name="play",
            description=(
                "执行买菜游戏指令。自动读存档、执行、存回。支持分号串联多条指令：'买 番茄;买 鸡蛋'。\n\n"
                "常见指令：菜场/逛/看/买/砍价/细看/回家/做菜/做法/加盐/出锅/她说/取罐 等。神秘时空日头部会提示「去 mystic_xxx」进异宾摊，用「答 你的话」回答换食材。\n\n"
                "核心规则：不要自己做决定。讲给人类听当前场景，等他们说买什么、做什么菜。"
                "你可以建议（比如'今天番茄看起来不错'），但最终选择权在人类。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "游戏指令，如'菜场'、'买 番茄 2斤'、'砍价 便宜点'、'回家'、'做法 番茄切块，鸡蛋打散先炒盛出，再炒番茄出汁放回蛋，加盐出锅'",
                    }
                },
                "required": ["instruction"],
            },
        ),
        Tool(
            name="status",
            description="查看当前游戏状态：天数、季节、天气、预算、菜篮、厨房进度等。不消耗游戏内时间。",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@app.call_tool()
async def call_tool(name, arguments):
    if name == "new_game":
        seed = arguments.get("seed")
        state, text = engine.new_game(seed)
        engine.save_game(state)
        return [TextContent(type="text", text=text)]

    elif name == "play":
        instruction = arguments.get("instruction", "").strip()
        if not instruction:
            return [TextContent(type="text", text="空指令。试试'菜场'、'买 番茄'、'回家'。")]

        # 读存档
        state = engine.load_game()
        if state is None:
            state, text = engine.new_game()
            engine.save_game(state)
            return [
                TextContent(
                    type="text",
                    text=f"没有存档，已自动开新局。\n\n{text}",
                )
            ]

        # 执行
        new_state, output = engine.cmd(state, instruction)
        engine.save_game(new_state)
        return [TextContent(type="text", text=output)]

    elif name == "status":
        state = engine.load_game()
        if state is None:
            return [TextContent(type="text", text="没有存档。用new_game开一局。")]

        day = state.get("day", "?")
        season = state.get("season", "?")
        weather = state.get("weather", "?")
        budget = state.get("budget", 0)
        spent = state.get("spent", 0)
        market_time = state.get("market_time", 0)
        market_time_max = state.get("market_time_max", 0)
        done = state.get("done", False)
        basket = state.get("basket", [])
        kitchen = state.get("_kitchen_state")

        lines = [
            f"第{day}天 | {season} | {weather}",
            f"预算: {budget - spent:.1f}/{budget}元",
            f"时间: {market_time}/{market_time_max}",
        ]

        if done:
            lines.append("状态: 已吃完")
        elif kitchen is not None:
            dish = kitchen.get("dish_name", "???")
            steps_done = len(kitchen.get("completed_steps", []))
            lines.append(f"状态: 厨房 | 做{dish} | 已完成{steps_done}步")
        elif basket:
            lines.append(f"状态: 买菜中 | 菜篮{len(basket)}样")
        else:
            lines.append("状态: 菜场")

        if basket:
            items = []
            for b in basket:
                bname = b.get("name", "?")
                qty = b.get("qty", 0)
                unit = b.get("unit", "")
                quality = b.get("quality_label", "")
                items.append(f"  {bname} {qty}{unit} ({quality})")
            lines.append("菜篮:")
            lines.extend(items)

        fridge = state.get("fridge", [])
        if fridge:
            lines.append(f"冰箱: {len(fridge)}样")

        return [TextContent(type="text", text="\n".join(lines))]

    return [TextContent(type="text", text=f"未知工具: {name}")]


def run_stdio():
    """stdio模式（默认，Claude Code / Claude Desktop用）"""
    from mcp.server.stdio import stdio_server
    import asyncio

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(main())


def run_sse(port=8878):
    """SSE模式（Kelivo / Cherry Studio / 其他HTTP MCP客户端用）"""
    try:
        from mcp.server.sse import SseServerTransport
    except ImportError:
        print("需要 starlette 和 uvicorn：pip install starlette uvicorn")
        sys.exit(1)

    try:
        from starlette.applications import Starlette
        from starlette.routing import Route
        import uvicorn
    except ImportError:
        print("需要 starlette 和 uvicorn：pip install starlette uvicorn")
        sys.exit(1)

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await app.run(
                streams[0], streams[1], app.create_initialization_options()
            )

    async def handle_messages(request):
        await sse.handle_post_message(request._receive, request._send)

    starlette_app = Starlette(
        debug=False,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages/", endpoint=handle_messages, methods=["POST"]),
        ],
    )

    print(f"买菜游戏 MCP SSE Server → http://localhost:{port}/sse")
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="买菜游戏 MCP Server")
    parser.add_argument("--sse", action="store_true", help="使用SSE模式（HTTP）代替stdio")
    parser.add_argument("--port", type=int, default=8878, help="SSE模式端口（默认8878）")
    args = parser.parse_args()

    if args.sse:
        run_sse(args.port)
    else:
        run_stdio()
