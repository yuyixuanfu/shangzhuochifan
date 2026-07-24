"""
从 market_engine.py + market_data.py + market_quality.py + market_recipes.py
生成 market_blind.py（盲玩版）

盲玩版把所有源码打包进 base64 编码的字符串里，
运行时解码执行，只暴露 cmd() 和 new_game() 两个接口。
AI 玩家看不到鱼谱、概率、坑点机制，只能靠玩发现。
"""

import base64
import os
import sys

SRC_DIR = os.path.dirname(os.path.abspath(__file__))

# 需要打包的源文件
SOURCE_FILES = [
    "market_data.py",
    "market_quality.py",
    "market_recipes.py",
    "market_engine.py",
]

def build():
    # 读取所有源文件，按顺序拼成一个字符串
    chunks = []
    for fname in SOURCE_FILES:
        path = os.path.join(SRC_DIR, fname)
        if not os.path.exists(path):
            print(f"❌ 找不到 {path}")
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        # 用标记分隔每个文件
        chunks.append(f"# === FILE: {fname} ===\n{code}")

    all_code = "\n\n".join(chunks)
    encoded = base64.b64encode(all_code.encode("utf-8")).decode("ascii")

    # 生成盲玩版
    blind_code = f'''"""
菜市场 · 盲玩版
给 AI 玩的——引擎藏在下面那段编码里，只暴露两个接口：

  market_blind.cmd("指令")   → 返回游戏结果文字
  market_blind.new_game(seed) → 重开一局

AI 不知道有哪些坑、概率多少、暗坑怎么触发，
全靠逛菜场、细看、砍价来发现。

改数值/加内容请改源文件后重新跑 build_blind.py。
"""

import base64 as _b64
import types as _types
import sys as _sys

_BLOB = "{encoded}"

def _load_engine():
    """解码并执行引擎代码，返回模块"""
    code = _b64.b64decode(_BLOB).decode("utf-8")
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
    print(f"   源码: {raw_size:,} 字节 → 盲玩版: {blind_size:,} 字节")

if __name__ == "__main__":
    build()
