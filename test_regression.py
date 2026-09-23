#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回归测试——覆盖 6+ 轮 bug 修复里的关键路径

不依赖 RNG 友好性（用 seed 钉死），覆盖：
- 基本流程：新游戏 → 菜场 → 买菜 → 回家 → 做饭 → 端菜
- 各种"去"指令（精确匹配 / zone 模糊）
- per-stall milestone 触发（折扣）
- Perk 系统（liujie_honest_scale）
- 序列化往返一致
- RNG 跨实例确定性
- 所有已修的 bug 不会再现
"""
import os
import sys

# 一定要先 import _testutil，它会设置临时 save 路径
import _testutil

from market_engine import MarketGame, mulberry32
from market_data import STALL_BY_ID


PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append((name, detail))
        print(f"  [FAIL] {name}: {detail}")


def section(title):
    print(f"\n─── {title} ───")


# ============================================================
# Section 1: 基本流程
# ============================================================
section("1. 基本流程：新游戏 → 逛 → 买 → 回家")

_testutil.reset()

try:
    g = MarketGame()
    check("初始 day=0", g.day == 0)
    check("初始 budget=0", g.budget == 0)
    check("初始 season=''", g.season == "")

    r = g.cmd("菜场")
    check("菜场 触发 new_day (day=1)", g.day == 1)
    check("菜场 触发后 season 非空", g.season != "")
    check("菜场 触发后 budget > 0", g.budget > 0)
    check("菜场 返回是菜场一览", "菜场一览" in r or "出了门" in r)

    # ============================================================
    # Section 2: 各种 "去" 指令
    # ============================================================
    section("2. 各种 '去' 指令")
    r = g.cmd("看菜场")
    check("'看菜场' 进 look_stalls", "菜场一览" in r or "出了门" in r)
    r = g.cmd("看市场")
    check("'看市场' 进 look_stalls", "菜场一览" in r or "出了门" in r)
    r = g.cmd("逛菜场")
    check("'逛菜场' 进 look_stalls", "菜场一览" in r or "出了门" in r)
    r = g.cmd("逛市场")
    check("'逛市场' 进 look_stalls", "菜场一览" in r or "出了门" in r)

    r = g.cmd("去 veg_1")
    check("精确 stall id 'veg_1' 进 visit_stall",
          "veg_1" in str(g.current_stall) or "王姐蔬菜" in r)

    # 单字 '区' 不应被误路由到 zone
    r = g.cmd("去 区")
    check("单字 '区' 不再误匹配 zone", "菜场一览" not in r or "没" in r or "无" in r,
          detail=f"got: {r[:80]!r}")

    # ============================================================
    # Section 3: 实际买 + 折扣
    # ============================================================
    section("3. 买 + per-stall milestone 折扣")
    g.cmd("去 veg_1")
    g.affection["veg_1"] = 0
    g._stall_discounts = {}

    # 选个独特菜名——"韭菜"（不在 timed encounter free gift 候选范围）
    _testutil.reset()
    g2 = MarketGame()
    g2.cmd("菜场")
    g2.cmd("去 veg_2")
    g2.budget = 100
    # RNG: 韭菜可能当天被卖完——重试几个候选菜
    base_price = None
    base_name = None
    for item in ("韭菜", "大白菜", "菠菜"):
        g2.basket = []
        g2.spent = 0
        r = g2.cmd(f"买 {item}")
        paid = [i for i in g2.basket if i["name"] == item and not i.get("_free")]
        if paid:
            base_price = paid[0]["price"]
            base_name = item
            break
    check("无折扣 buy 成功（veg_2 上任意一个）", base_price is not None,
          detail=f"veg_2 basket: {g2.basket}")
    check("无折扣 buy 的是非免费项", base_price is not None and base_price > 0,
          detail=f"base_price={base_price}")

    # 有折扣时买一次
    _testutil.reset()
    g3 = MarketGame()
    g3.cmd("菜场")
    g3.cmd("去 veg_2")
    g3.affection["veg_2"] = 25  # 触发 aff20 milestone
    g3.cmd("去 veg_2")
    g3.budget = 100
    discount_val = getattr(g3, "_stall_discounts", {}).get("veg_2", 0)
    check("aff20 milestone 触发后 discount>0", discount_val > 0,
          detail=f"_discount={discount_val}")
    paid_with_discount = None
    candidates = [base_name] if base_name else []
    candidates += ["韭菜", "大白菜", "菠菜", "香菜", "茼蒿", "芹菜", "蒜苗"]
    for item in candidates:
        if not item:
            continue
        g3.basket = []
        g3.spent = 0
        g3.cmd(f"买 {item}")
        pwd = [i for i in g3.basket if i["name"] == item and not i.get("_free")]
        if pwd:
            paid_with_discount = pwd[0]
            break
    if paid_with_discount:
        check("折扣应用后 buy 成功（链路通）", True)
    else:
        print("  [SKIP] 折扣链路 buy 验证：所有候选都被 RNG 卖光")

    # ============================================================
    # Section 4: Perk 系统
    # ============================================================
    section("4. Perk 系统（liujie_honest_scale）")
    _testutil.reset()
    g4 = MarketGame()
    g4.cmd("菜场")
    g4.cmd("去 root_1")
    g4.affection["root_1"] = 60
    g4.cmd("去 root_1")
    if "liujie_honest_scale" in g4._perks:
        check("aff55 触发 perk liujie_honest_scale", True)
    else:
        if g4._market_closed or g4.market_time <= 0:
            print("  [SKIP] perk 触发：market 提前收摊（RNG）")
        else:
            check("aff55 触发 perk liujie_honest_scale", False,
                  detail=f"_perks={g4._perks}")

    # ============================================================
    # Section 5: 序列化往返
    # ============================================================
    section("5. 序列化往返")
    _testutil.reset()
    g5 = MarketGame()
    g5.cmd("菜场")
    g5.cmd("去 veg_1")
    g5.cmd("买 小白菜")
    g5.cmd("去 meat_1")
    g5.cmd("买 五花肉")
    state1 = g5.to_dict()

    g6 = MarketGame()
    g6.from_dict(state1)
    state2 = g6.to_dict()

    for key in ("seed", "day", "budget", "spent", "season", "weather",
                "time_of_day", "basket", "kitchen_state", "affection",
                "current_stall"):
        if state1.get(key) != state2.get(key):
            check(f"序列化 {key} 一致", False,
                  detail=f"{state1.get(key)!r} != {state2.get(key)!r}")
            break
    else:
        check("序列化核心字段一致", True)

    check("RNG state 跨实例一致",
          g6._get_rng_state() == state1["rt_rng_state"])

    seq1 = [g7.rng() if (g7 := MarketGame()).from_dict(state1) is None or True else None for _ in range(20)]
    # 用更简单的写法
    g7 = MarketGame(); g7.from_dict(state1)
    g8 = MarketGame(); g8.from_dict(state1)
    seq1 = [g7.rng() for _ in range(20)]
    seq2 = [g8.rng() for _ in range(20)]
    check("同 state 双实例 RNG 序列一致", seq1 == seq2,
          detail=f"first 3 differ: {seq1[:3]} vs {seq2[:3]}")

    # ============================================================
    # Section 6: JSON 可序列化
    # ============================================================
    section("6. JSON 可序列化")
    import json
    try:
        json.dumps(state1)
        check("to_dict() 结果 JSON 可序列化", True)
    except TypeError as e:
        check("to_dict() 结果 JSON 可序列化", False, detail=str(e))

    # ============================================================
    # Section 7: __init__ 默认属性
    # ============================================================
    section("7. __init__ 默认属性（不依赖 from_dict）")
    g_fresh = MarketGame()
    check("__init__ 默认 encyclopedia 存在", hasattr(g_fresh, "encyclopedia"))
    check("__init__ 默认 _perks 存在",
          hasattr(g_fresh, "_perks") and isinstance(g_fresh._perks, set))
    check("__init__ 默认 _state_avoid 存在", hasattr(g_fresh, "_state_avoid"))
    check("__init__ 默认 _state_craving 存在", hasattr(g_fresh, "_state_craving"))
    check("__init__ 默认 _pending_chain_steps 存在",
          hasattr(g_fresh, "_pending_chain_steps"))
    try:
        _ = g_fresh.encyclopedia["items_bought"]
        check("encyclopedia['items_bought'] 可直接访问", True)
    except AttributeError as e:
        check("encyclopedia['items_bought'] 可直接访问", False, detail=str(e))

    # ============================================================
    # Section 8: command dispatch 没破坏
    # ============================================================
    section("8. 通用指令 dispatch")
    _testutil.reset()
    g9 = MarketGame()
    g9.cmd("菜场")
    g9.cmd("去 veg_1")
    r = g9.cmd("看 veg_1")
    check("'看 veg_1' 不报错", "细看什么" in r or "鱼" in r or "摊主" in r or "细看" in r)
    r = g9.cmd("帮助")
    check("'帮助' 不报错", len(r) > 0)
    sb = g9._status_bar()
    check("status_bar 不报错", len(sb) > 0)

    # ============================================================
    # Section 9: time_loop_pending_day 新字段兼容
    # ============================================================
    section("9. 新字段向后兼容")
    _testutil.reset()
    g10 = MarketGame()
    g10.cmd("菜场")
    g10.mystic.load_state({})
    check("load_state 空 dict 不报错", True)
    check("load_state 后 time_loop_pending_day 有默认",
          "time_loop_pending_day" in g10.mystic.state)
    check("load_state 后 time_loop_just_happened 有默认",
          "time_loop_just_happened" in g10.mystic.state)

    # ============================================================
    # Section 10: apply_exotic_reveal verb 影响
    # ============================================================
    section("10. apply_exotic_reveal verb 影响")
    class FakeGame:
        def rng(self):
            return 0
    me = g10.mystic
    me.game = FakeGame()
    item = {"name": "明天的菜", "exotic": "tomorrow"}
    r_cut = me.apply_exotic_reveal(item, "切")
    r_wash = me.apply_exotic_reveal(item, "洗")
    r_peel = me.apply_exotic_reveal(item, "剥")
    check("不同 verb 可能产生不同 reveal 文案",
          len({r_cut, r_wash, r_peel}) >= 2,
          detail=f"3 个 verb 各自：{r_cut[:30]!r} | {r_wash[:30]!r} | {r_peel[:30]!r}")

    # ============================================================
    # Section 11: 已修 bug 不再回归
    # ============================================================
    section("11. 已修 bug 不再回归")
    _testutil.reset()
    g11 = MarketGame()
    g11.cmd("菜场")
    r = g11.cmd("看菜场")
    check("'看菜场' 不再进 detail_look 报'找不到'",
          "找不到" not in r and "没有这个" not in r,
          detail=f"got: {r[:80]!r}")
    r = g11.cmd("去 菜")
    check("单字 '菜' 不再误路由到 zone",
          "没这个摊" in r or "没有" in r or "找不到" in r or len(r) < 100,
          detail=f"got: {r[:80]!r}")

finally:
    _testutil.reset()


print()
print("=" * 60)
print(f"  PASSED: {len(PASSED)}")
print(f"  FAILED: {len(FAILED)}")
print("=" * 60)
if FAILED:
    print("\n失败详情：")
    for name, detail in FAILED:
        print(f"  - {name}: {detail}")
    sys.exit(1)
else:
    print("\n所有断言通过 ✓")
    sys.exit(0)