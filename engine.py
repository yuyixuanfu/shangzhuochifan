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

import sys, os, io, json, time, logging, threading, uuid

# 确保UTF-8输出（Windows终端默认gbk会崩emoji）
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_SAVE_FILE = os.environ.get("MARKET_SAVE_FILE") or os.path.join(_HERE, "market_save.json")


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

    return json.dumps(bar, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


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


class LoadResult:
    """三态加载结果：ok / missing / corrupt。"""
    def __init__(self, status, state=None, error=None):
        self.status = status   # "ok" | "missing" | "corrupt"
        self.state = state
        self.error = error


def load_game():
    """从文件读存档。返回 LoadResult（区分 ok/missing/io/corrupt）。"""
    if not os.path.exists(_SAVE_FILE):
        return LoadResult("missing")
    try:
        with open(_SAVE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # P1-7：顶层不是 dict（如 [1,2]）不算 ok——真值会害 from_dict 崩，
        # 假值会被 `state or {}` 吞成新档静默丢弃
        if not isinstance(data, dict):
            raise ValueError(f"存档根节点类型错误: {type(data).__name__}")
        return LoadResult("ok", data)
    except (json.JSONDecodeError, ValueError) as e:
        _log.warning("load_game 存档损坏: %s", e)
        return LoadResult("corrupt", error=str(e))
    except OSError as e:
        # P1-3：IO 错误（杀毒/索引锁、权限抖动）不是损坏——按 corrupt 处理
        # 会把正常存档改名覆盖，玩家进度被无谓重置
        _log.error("load_game IO错误: %s", e)
        return LoadResult("io", error=str(e))


def save_game(state):
    """原子写存档。失败时打日志（不抛，避免打断游戏循环）。"""
    # P1-6：tmp 名带 pid+线程id——固定 .tmp 会被并发/多进程写入者互相换走，
    # 半成品混杂后 os.replace 原子提升的就是脏数据
    tmp = f"{_SAVE_FILE}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(tmp, _SAVE_FILE)
    except (OSError, TypeError, ValueError) as e:
        _log.error("save_game 失败: %s", e)
        try:
            os.remove(tmp)
        except OSError:
            pass


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
    result = load_game()
    if result.status == "missing":
        state, text = new_game()
        save_game(state)
        print(text)
        print("\n（自动开新局。输入 python engine.py \"菜场\" 开始。）")
        return
    elif result.status == "io":
        # P1-3：临时 IO 错误（锁/权限）不是损坏——直接中止，不动文件
        print(f"存档读取失败（IO 错误，未动文件）：{result.error}")
        return
    elif result.status == "corrupt":
        # 损坏档不覆盖——备份成功才继续，备份失败就中止保住唯一副本（P0-3）
        backup = _SAVE_FILE + ".corrupt"
        if os.path.exists(_SAVE_FILE):
            try:
                os.replace(_SAVE_FILE, backup)
            except OSError as e:
                print(f"存档损坏，且备份到 {backup} 失败：{e}。已中止，原档未动。")
                return
        print(f"存档损坏，已备份到 {backup}")
        state, text = new_game()
        save_game(state)
        print(text)
        return

    state = result.state
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

    # P0-2：HTTP 多会话各自在内存持 state，若仍让 MarketGame 内部落盘，
    # 两个 session（或 HTTP 与 CLI）交替执行会互相覆盖 market_save.json——
    # 进程级禁用内部落盘，进度只存在 _games 里
    os.environ["MARKET_SAVE_DISABLE"] = "1"

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
            # P1-5：毫秒时间戳同毫秒会撞号（后者静默覆盖前者），且单调可猜——
            # 换 uuid4
            sid = uuid.uuid4().hex
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
        if not inst:
            return jsonify({"error": "空指令"}), 400
        with _lock:
            # P1-4：校验和取值必须在同一把锁内——校验在锁外时，另一线程的
            # /new 可能在校验与取值之间淘汰该 sid，_games[sid] 直接 KeyError
            state = _games.get(sid) if sid else None
            if state is None:
                return jsonify({"error": "无效session，先POST /new"}), 400
            new_state, text = cmd(state, inst)
            _games[sid] = new_state
            return jsonify({"text": text})

    @app.route("/state", methods=["GET"])
    def get_state():
        sid = request.args.get("session", "")
        # P1-4：锁内取快照，防止与淘汰并发时 KeyError / 返回撕裂状态
        with _lock:
            state = _games.get(sid) if sid else None
        if state is None:
            return jsonify({"error": "无效session"}), 400
        return jsonify(state)

    port = int(os.environ.get("MARKET_PORT", 8877))
    print(f"上桌吃饭 HTTP API — localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
