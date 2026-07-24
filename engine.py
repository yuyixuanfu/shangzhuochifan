#!/usr/bin/env python3
"""上桌吃饭 — AI可玩版引擎（薄壳）

接口（跟钓鱼游戏/词与物一样）:
  new_game(seed)    → (state, text)   开新局
  cmd(state, inst)  → (state, text)   执行指令
  load_game()       → state | None    从文件读
  save_game(state)  → None            存文件

AI接入方式:
  1. 函数调用: import engine; state = engine.new_game()[0]; state, text = engine.cmd(state, "菜场")
  2. 命令行:   python engine.py "菜场"  (自动读存档、执行、存回)
  3. HTTP API: python engine.py --serve  (Flask, port 8877)
  4. MCP工具:  配合 market_mcp_server.py

特性:
  - 批量指令: "买 番茄;买 鸡蛋 1" 分号串联
  - 状态栏JSON: 每次输出末尾带紧凑状态
  - 确定性PRNG: 同seed同指令=同结果（rng调用进度也存档，跨进程一致）

── 设计 ──────────────────────────────────────────────
本文件只是薄壳：所有游戏逻辑在 market_engine.py 的 MarketGame。
存档往返用 MarketGame.to_dict()/from_dict()——一份逻辑，直接调/命令行/MCP
三条路共用，不再各自维护快照（旧版 _snapshot/_restore 的 dir 全量快照脆弱，
和 MarketGame 自带 save/load 两套打架）。state 就是 to_dict() 的输出，
字段平铺本名（season/weather/basket/...），MCP status 直接读。
"""

import sys, os, io, json, time, logging

# 确保UTF-8输出（Windows终端默认gbk会崩emoji）
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_SAVE_FILE = os.path.join(_HERE, "market_save.json")


def _new_game():
    from market_engine import MarketGame
    return MarketGame()


# ── 状态栏 ──────────────────────────────────────────
def _status_bar(game):
    """紧凑JSON状态栏——让AI知道在哪。"""
    bar = {
        "day": game.day,
        "season": game.season,
        "weather": game.weather,
    }
    if game.kitchen_state is not None:
        bar["phase"] = "厨房"
        if game.kitchen_state.get("dish_name"):
            bar["dish"] = game.kitchen_state["dish_name"]
    elif game.basket:
        bar["phase"] = "买菜"
    else:
        bar["phase"] = "菜场"

    if not game.done:
        bar["budget"] = f"{game.budget - game.spent:.1f}/{game.budget}"
        bar["basket"] = len(game.basket)
        bar["time"] = f"{game.market_time}/{game.market_time_max}"
    else:
        bar["phase"] = "吃完"

    return json.dumps(bar, ensure_ascii=False, separators=(',', ':'))


# ── 核心接口 ────────────────────────────────────────
def new_game(seed=None):
    """开新局。返回 (state_dict, 开场文字)。

    seed 给定时用 seed；否则 MarketGame.new_day 用 time.time()。
    """
    game = _new_game()
    if seed is not None:
        text = game.new_day(seed=seed, force=True)
    else:
        text = game.new_day(force=True)
    # new_day 已经 save 过；这里把状态拍成 state 返回
    state = game.to_dict()
    return state, text


def cmd(state, instruction):
    """执行指令。返回 (新state, 输出文字)。

    支持分号串联: "买 番茄;买 鸡蛋 2" 依次执行
    """
    game = _new_game()
    # 从 state 恢复——和直接调 market_engine.cmd 走同一份 from_dict 逻辑
    game.from_dict(state or {})

    # 处理分号串联
    if ';' in instruction:
        parts = [p.strip() for p in instruction.split(';') if p.strip()]
        texts = []
        for part in parts[:8]:
            texts.append(game.cmd(part))
            if game.done:
                break
        full_text = "\n---\n".join(texts)
    else:
        full_text = game.cmd(instruction)

    # game.cmd 内部每条指令已 save 过（写文件），但 stateless 接口要返回 state
    new_state = game.to_dict()
    status = _status_bar(game)
    output = full_text + "\n" + status
    return new_state, output


_log = logging.getLogger("market_shim")


def load_game():
    """从文件读存档。返回 state_dict 或 None。"""
    if not os.path.exists(_SAVE_FILE):
        return None
    try:
        with open(_SAVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _log.warning("load_game 失败: %s", e)
        return None


def save_game(state):
    """存档到文件。失败时打日志（不抛，避免打断游戏循环）。"""
    try:
        with open(_SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError as e:
        _log.error("save_game 失败: %s", e)


# ── 命令行入口 ──────────────────────────────────────
def main():
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("用法: python engine.py \"指令\"")
        print("  python engine.py new          — 开新局")
        print("  python engine.py 菜场          — 继续游戏")
        print("  python engine.py 买 番茄;买 鸡蛋 — 串联指令")
        print("  python engine.py --serve       — 启动HTTP API")
        return

    arg = sys.argv[1]

    if arg == "--serve":
        _serve()
        return

    instruction = " ".join(sys.argv[1:]).strip()

    if instruction.lower() in ("new", "新局", "new_game"):
        state, text = new_game()
        save_game(state)
        print(text)
        return

    # 读存档
    state = load_game()
    if state is None:
        state, text = new_game()
        save_game(state)
        print(text)
        print("\n（自动开新局。输入 python engine.py \"菜场\" 开始。）")
        return

    # 执行
    new_state, text = cmd(state, instruction)
    save_game(new_state)
    print(text)


# ── HTTP API ────────────────────────────────────────
def _serve():
    """启动Flask HTTP API，给任何AI玩。"""
    try:
        from flask import Flask, jsonify, request
    except ImportError:
        print("需要Flask: pip install flask")
        return

    app = Flask(__name__)
    import threading
    _lock = threading.Lock()
    _games = {}  # session_id → state

    @app.route("/")
    def index():
        return jsonify({
            "game": "上桌吃饭",
            "endpoints": {
                "POST /new": "开新局 (可选 ?seed=123)",
                "POST /cmd": "执行指令 (body: {session, instruction})",
                "GET /state": "查看状态 (query: ?session=xxx)",
            }
        })

    @app.route("/new", methods=["POST"])
    def new():
        with _lock:
            seed = request.args.get("seed", type=int)
            state, text = new_game(seed)
            sid = str(int(time.time() * 1000))
            _games[sid] = state
            while len(_games) > 10:
                oldest = next(iter(_games))
                del _games[oldest]
            return jsonify({"session": sid, "text": text})

    @app.route("/cmd", methods=["POST"])
    def do_cmd():
        body = request.get_json(silent=True) or {}
        sid = body.get("session", "")
        inst = body.get("instruction", "").strip()
        if not sid or sid not in _games:
            return jsonify({"error": "无效session，先POST /new"}), 400
        if not inst:
            return jsonify({"error": "空指令"}), 400
        with _lock:
            state = _games[sid]
            new_state, text = cmd(state, inst)
            _games[sid] = new_state
            return jsonify({"text": text})

    @app.route("/state", methods=["GET"])
    def get_state():
        sid = request.args.get("session", "")
        if not sid or sid not in _games:
            return jsonify({"error": "无效session"}), 400
        return jsonify(_games[sid])

    port = int(os.environ.get("MARKET_PORT", 8877))
    print(f"上桌吃饭 HTTP API — localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
