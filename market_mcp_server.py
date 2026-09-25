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
import asyncio
import contextlib
import threading

# UTF-8 — 用 reconfigure 原地改编码，避免重新赋值 sys.stdout
# （reassign 会让已缓存 stdout 引用的库输出错乱）
def _ensure_utf8(stream):
    if stream.encoding and stream.encoding.lower().replace('-', '') == 'utf8':
        return
    try:
        stream.reconfigure(encoding='utf-8', errors='replace')  # Py3.7+
    except (AttributeError, ValueError):
        # stream 不支持 reconfigure（如被替换过）时回退到老办法
        import io
        wrapper = io.TextIOWrapper(stream.buffer, encoding='utf-8', errors='replace')
        if stream is sys.stdout:
            sys.stdout = wrapper
        else:
            sys.stderr = wrapper

_ensure_utf8(sys.stdout)
_ensure_utf8(sys.stderr)

# 确保引擎目录在path里
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from mcp.server import Server
from mcp.types import Tool, TextContent

import engine

app = Server("market-game")

# P1-17：存档的 load→cmd→save 是跨进程共享的读-改-写窗口，必须整体串行化。
# 进程内锁防本进程并发；文件锁防 stdio 模式下每个客户端一个进程共写同一存档
_save_lock = threading.Lock()


@contextlib.contextmanager
def _save_file_lock():
    """跨进程文件锁。Windows 用 msvcrt，Unix 用 fcntl；取不到锁时打告警
    继续（不阻塞业务），与仓库其他锁降级口径一致。"""
    lock_path = engine._SAVE_FILE + ".lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                locked = True
            except OSError as e:
                print(f"[WARN] 存档文件锁获取失败，降级继续: {e}", file=sys.stderr)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
            locked = True
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def _do_new_game(seed):
    with _save_lock, _save_file_lock():
        state, text = engine.new_game(seed)
        engine.save_game(state)
    return text


def _do_play(instruction):
    with _save_lock, _save_file_lock():
        # P0-α3：load_game 返回 LoadResult 三态对象（.status/.state/.error），
        # 既不是 dict 也永远不会是 None——旧代码 `if state is None` 恒假，
        # 有档时把 LoadResult 塞进 engine.cmd 直接崩
        result = engine.load_game()
        if result.status == "missing":
            state, text = engine.new_game()
            engine.save_game(state)
            return f"没有存档，已自动开新局。\n\n{text}"
        if result.status == "corrupt":
            # 与 engine.main 同一口径：损坏档不覆盖，留给用户处理
            return f"存档损坏，未覆盖（{result.error}）。可用 new_game 开新局。"
        if result.status == "io":
            return f"存档读取失败（IO 错误，未动文件）：{result.error}"
        new_state, output = engine.cmd(result.state, instruction)
        engine.save_game(new_state)
    return output


def _do_status():
    with _save_lock, _save_file_lock():
        result = engine.load_game()
        if result.status == "missing":
            return "没有存档。用new_game开一局。"
        if result.status != "ok":
            return f"存档不可读（{result.status}）：{result.error or ''}"
        state = result.state

        day = state.get("day", "?")
        season = state.get("season", "?")
        weather = state.get("weather", "?")
        budget = state.get("budget", 0)
        spent = state.get("spent", 0)
        market_time = state.get("market_time", 0)
        market_time_max = state.get("market_time_max", 0)
        done = state.get("done", False)
        basket = state.get("basket", [])
        kitchen = state.get("kitchen_state")

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

        return "\n".join(lines)


@app.call_tool()
async def call_tool(name, arguments):
    # P1-20：arguments 是协议可选字段，客户端合法地不带时为 None
    arguments = arguments or {}

    if name == "new_game":
        seed = arguments.get("seed")
        # P1-18：同步引擎 IO 不进事件循环，放线程池；锁随工作移入线程
        text = await asyncio.to_thread(_do_new_game, seed)
        return [TextContent(type="text", text=text)]

    elif name == "play":
        instruction = arguments.get("instruction", "").strip()
        if not instruction:
            return [TextContent(type="text", text="空指令。试试'菜场'、'买 番茄'、'回家'。")]
        output = await asyncio.to_thread(_do_play, instruction)
        return [TextContent(type="text", text=output)]

    elif name == "status":
        text = await asyncio.to_thread(_do_status)
        return [TextContent(type="text", text=text)]

    return [TextContent(type="text", text=f"未知工具: {name}")]


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


def run_stdio():
    """stdio模式（默认，Claude Code / Claude Desktop用）"""
    from mcp.server.stdio import stdio_server
    import asyncio

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(main())


def run_sse(port=8878, host="127.0.0.1"):
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

    # P1-21：改用原始 ASGI 签名 (scope, receive, send)——不再依赖 Starlette
    # Request 的私有属性 _send/_receive（升级即断）
    async def handle_sse(scope, receive, send):
        async with sse.connect_sse(scope, receive, send) as streams:
            await app.run(
                streams[0], streams[1], app.create_initialization_options()
            )

    async def handle_messages(scope, receive, send):
        await sse.handle_post_message(scope, receive, send)

    class _AsgiEndpoint:
        """把 (scope, receive, send) 处理器包成 Route 可用的 ASGI 应用
        （非函数对象时 Starlette 直接当 ASGI app 用，不再包 request_response）。"""
        def __init__(self, handler):
            self._handler = handler

        async def __call__(self, scope, receive, send):
            await self._handler(scope, receive, send)

    starlette_app = Starlette(
        debug=False,
        routes=[
            Route("/sse", endpoint=_AsgiEndpoint(handle_sse), methods=["GET"]),
            Route("/messages/", endpoint=_AsgiEndpoint(handle_messages), methods=["POST"]),
        ],
    )

    print(f"买菜游戏 MCP SSE Server → http://{host}:{port}/sse")
    uvicorn.run(starlette_app, host=host, port=port)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="买菜游戏 MCP Server")
    parser.add_argument("--sse", action="store_true", help="使用SSE模式（HTTP）代替stdio")
    parser.add_argument("--port", type=int, default=8878, help="SSE模式端口（默认8878）")
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="SSE 监听地址（默认 127.0.0.1）。P1-19：改 0.0.0.0 会把无认证的"
             "游戏接口暴露给局域网/公网，任何能连上的人都能读写本机存档，慎用。",
    )
    args = parser.parse_args()

    if args.sse:
        run_sse(args.port, args.host)
    else:
        run_stdio()
