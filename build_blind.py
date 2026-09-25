"""
从 market_engine.py + market_data.py + market_quality.py + market_recipes.py
生成 market_blind.py（盲玩版）

盲玩版把所有源码打包进 base64 编码的字符串里，
运行时解码执行，只暴露 cmd() 和 new_game() 两个接口。
AI 玩家看不到鱼谱、概率、坑点机制，只能靠玩发现。

注意（P1-2）：内嵌的 _SHA256 只能发现偶发损坏（截断/编码错误），
防误改不防篡改——摘要和内容在同一份文件里，能改内容的人也能同步改摘要。
需要防篡改时应用外部摘要或签名。

改数值/加内容请改源文件后重新跑 build_blind.py；
用 --check 校验 market_blind.py 是否落后于源文件（落后时非零退出）。
"""

import base64
import hashlib
import os
import re
import sys

SRC_DIR = os.path.dirname(os.path.abspath(__file__))

# 需要打包的源文件
SOURCE_FILES = [
    "market_data.py",
    "market_quality.py",
    "market_recipes.py",
    "market_engine.py",
]

# P0-1：这些模块会被打进同一个命名空间（按上面顺序 exec），
# 它们之间的 import 必须剥离——否则盲版单独部署时首次 import 即崩，
# 或带源部署时加载明文模块、盲玩隔离失效
_PACKED = "|".join(re.escape(m[:-3]) for m in SOURCE_FILES)  # m[:-3] 去掉 ".py"
_RE_FROM = re.compile(rf"\s*from\s+({_PACKED})\s+import\b")
_RE_IMPORT = re.compile(rf"\s*import\s+({_PACKED})\b")
_RE_EXCEPT = re.compile(r"\s*except\s+ImportError\s*:")


def _strip_packed_imports(code, fname=""):
    """剥离被打包模块之间的 import 语句。

    两种形态：
    1. 裸 from/import（含多行括号）——整段删除：同命名空间下名字已由
       前置文件定义，重新 import 是 no-op，但走真实 import 会崩/漏明文。
    2. try: from <packed> import X / except ImportError: X = <默认>——
       形态上只留默认赋值。已核实 RECIPE_DISCOVERIES/DAY_END_EVENTS
       在 market_data 里没有定义，正常模式走的就是 ImportError 兜底，
       所以无条件取兜底值语义完全一致。遇到不认识的形状直接报错退出，
       不静默产出坏包。
    """
    out = []
    lines = code.splitlines(True)
    i = 0
    while i < len(lines):
        line = lines[i]
        if _RE_FROM.match(line) or _RE_IMPORT.match(line):
            if _RE_FROM.match(line):
                # try 包裹形态：try: 行 + from 行（+续行）+ except ImportError: + 默认赋值
                prev = out[-1].strip() if out else ""
                if prev == "try:":
                    try_line = out.pop()  # 去掉 try:
                    try_indent = re.match(r"[ \t]*", try_line).group(0)
                    out.append("# [blind-build] 剥离被打包模块的 try-import，保留兜底值（P0-1）\n")
                    i += 1
                    # 跳过 from 行及其括号续行
                    depth = line.count("(") - line.count(")")
                    while depth > 0:
                        i += 1
                        if i >= len(lines):
                            print(f"❌ {fname}: 未闭合的 from-import 续行")
                            sys.exit(1)
                        depth += lines[i].count("(") - lines[i].count(")")
                    if i >= len(lines) or not _RE_EXCEPT.match(lines[i]):
                        print(f"❌ {fname}: try-import 剥离后未找到 except ImportError:（行 {i+1}）")
                        sys.exit(1)
                    i += 1  # 消费 except 行
                    # except 体保留，但整体去掉"相对 try: 的那一层缩进"——
                    # try:/except: 已剥掉，残留缩进会成为孤儿 IndentationError
                    body_strip = None
                    while i < len(lines):
                        nxt = lines[i]
                        if nxt.strip() == "":
                            out.append(nxt)
                            i += 1
                            continue
                        ind = re.match(r"[ \t]*", nxt).group(0)
                        if body_strip is None:
                            body_strip = len(ind) - len(try_indent)
                            if body_strip <= 0:
                                print(f"❌ {fname}: except 体缩进异常（行 {i+1}）")
                                sys.exit(1)
                        if nxt[:body_strip].strip() == "" and len(nxt) >= body_strip:
                            out.append(nxt[body_strip:])
                        else:
                            break
                        i += 1
                    continue
                # 裸 from-import（可能多行括号）——整段删除
                depth = line.count("(") - line.count(")")
                i += 1
                while depth > 0:
                    if i >= len(lines):
                        print(f"❌ {fname}: 未闭合的 from-import 续行")
                        sys.exit(1)
                    depth += lines[i].count("(") - lines[i].count(")")
                    i += 1
                continue
            # 裸 import <packed> ...——整行删除
            i += 1
            continue
        out.append(line)
        i += 1
    return "".join(out)


def _collect_code():
    """读取源文件、剥离打包模块间 import、拼接——build 和 --check 共用，
    保证两边算出的摘要口径一致。"""
    chunks = []
    for fname in SOURCE_FILES:
        path = os.path.join(SRC_DIR, fname)
        if not os.path.exists(path):
            print(f"❌ 找不到 {path}")
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        code = _strip_packed_imports(code, fname)
        # 用标记分隔每个文件
        chunks.append(f"# === FILE: {fname} ===\n{code}")
    return "\n\n".join(chunks)


def build():
    all_code = _collect_code()
    code_bytes = all_code.encode("utf-8")
    digest = hashlib.sha256(code_bytes).hexdigest()
    encoded = base64.b64encode(code_bytes).decode("ascii")

    # 生成盲玩版
    blind_code = f'''"""
菜市场 · 盲玩版
给 AI 玩的——引擎藏在下面那段编码里，只暴露两个接口：

  market_blind.cmd("指令")   → 返回游戏结果文字
  market_blind.new_game(seed) → 重开一局

AI 不知道有哪些坑、概率多少、暗坑怎么触发，
全靠逛菜场、细看、砍价来发现。

改数值/加内容请改源文件后重新跑 build_blind.py。
用 python build_blind.py --check 可校验本文件是否落后于源文件。

完整性校验说明（P1-2）：_SHA256 只能发现偶发损坏（截断/编码错误），
防误改不防篡改——摘要就在同一份文件里，能改 _BLOB 的人也能同步改摘要。
"""

import base64 as _b64
import hashlib as _hashlib
import types as _types
import sys as _sys

_BLOB = "{encoded}"
_SHA256 = "{digest}"

def _load_engine():
    """解码并执行引擎代码，返回模块（带完整性校验）"""
    code_bytes = _b64.b64decode(_BLOB, validate=True)
    actual = _hashlib.sha256(code_bytes).hexdigest()
    if actual != _SHA256:
        raise RuntimeError(f"market_blind 完整性校验失败: expected {{_SHA256}}, got {{actual}}")
    code = code_bytes.decode("utf-8")
    mod = _types.ModuleType("market_engine_internal")
    exec(compile(code, "market_engine_internal", "exec"), mod.__dict__)
    return mod

_mod = None

def _get_mod():
    global _mod
    if _mod is None:
        _mod = _load_engine()
    return _mod

def cmd(instruction):
    """主指令入口，跟原版一样"""
    return _get_mod().cmd(instruction)

def new_game(seed=0x9E3779B9):
    """重开一局"""
    return _get_mod().new_game(seed)

# 兼容 import market_blind; market_blind.cmd("help")
'''

    out_path = os.path.join(SRC_DIR, "market_blind.py")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(blind_code)

    # 统计
    raw_size = len(all_code.encode("utf-8"))
    blind_size = os.path.getsize(out_path)
    print(f"[OK] 生成 market_blind.py")
    print(f"   源码: {raw_size:,} 字节 -> 盲玩版: {blind_size:,} 字节")
    print(f"   SHA-256: {digest}")

def check():
    """P1-1：产物新鲜度校验——重算源文件摘要，与产物内嵌 _SHA256 比对。"""
    out_path = os.path.join(SRC_DIR, "market_blind.py")
    if not os.path.exists(out_path):
        print(f"❌ 找不到 {out_path}")
        return 1
    with open(out_path, "r", encoding="utf-8") as f:
        m = re.search(r'^_SHA256 = "([0-9a-f]{64})"$', f.read(), re.M)
    if not m:
        print("❌ 产物内没有 _SHA256 标记（构建太旧），视为过期。")
        return 1
    embedded = m.group(1)
    current = hashlib.sha256(_collect_code().encode("utf-8")).hexdigest()
    if current != embedded:
        print(f"❌ market_blind.py 落后于源文件，请重跑 build_blind.py")
        print(f"   产物: {embedded}")
        print(f"   当前: {current}")
        return 1
    print("[OK] market_blind.py 与源文件同步。")
    return 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    build()
