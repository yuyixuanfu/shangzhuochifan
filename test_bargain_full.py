#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""bargain / mystery chain / hidden recipe 完整流程测试"""
import _testutil
from market_engine import MarketGame
from market_data import STALL_BY_ID


def check(name, cond, detail=""):
    if cond:
        print(f"  [OK] {name}")
    else:
        print(f"  [FAIL] {name}: {detail}")


def section(t):
    print(f"\n─── {t} ───")


# ============================================================
section("bargain 完整流程: 先砍后买 vs 直接买 价格差异")
# ============================================================
prices_no_bargain = []
prices_with_bargain = []

for i in range(5):
    _testutil.reset()
    g = MarketGame()
    g.cmd("菜场")
    g.cmd("去 veg_1")
    g.budget = 100
    # 直接买
    g.cmd("买 小白菜")
    paid = [it for it in g.basket if it["name"] == "小白菜" and not it.get("_free")]
    if paid:
        prices_no_bargain.append(paid[0]["price"])

    _testutil.reset()
    g = MarketGame()
    g.cmd("菜场")
    g.cmd("去 veg_1")
    g.budget = 100
    # 砍价后买
    g.cmd("便宜点")
    g.cmd("买 小白菜")
    paid = [it for it in g.basket if it["name"] == "小白菜" and not it.get("_free")]
    if paid:
        prices_with_bargain.append(paid[0]["price"])

print(f"  no bargain prices: {prices_no_bargain}")
print(f"  with bargain prices: {prices_with_bargain}")
check("5 轮 bargain 跑通（价格记录）", len(prices_no_bargain) >= 3 and len(prices_with_bargain) >= 3)


# ============================================================
section("多次砍价 streak 累积")
# ============================================================
_testutil.reset()
g = MarketGame()
g.cmd("菜场")
g.cmd("去 meat_1")
g.budget = 100
initial_streak = g.stats["bargain_streak"]
# 多次砍价
for _ in range(3):
    g.cmd("便宜点")
check("多次砍价后 stats.bargain_streak 是 int",
      isinstance(g.stats["bargain_streak"], int),
      detail=f"streak={g.stats['bargain_streak']}")


# ============================================================
section("mystic: 3 hidden chains 触发条件")
# ============================================================
_testutil.reset()
g = MarketGame()
# 模拟 7 连买同摊（dream_7visits chain）
for _ in range(8):
    g.mystic.update_visit_streak("veg_1")

# 检查 chain 触发状态
check("update_visit_streak 累计 consec_count",
      g.mystic.state.get("consec_count", 0) >= 7,
      detail=f"consec_count={g.mystic.state.get('consec_count')}")


# ============================================================
section("hidden recipe 解锁")
# ============================================================
_testutil.reset()
g = MarketGame()
g.cmd("菜场")
# 直接 set 隐藏菜谱解锁
g.unlocked_hidden_recipes.add("老吴私房菌菇煲")
g.save()
# 重建 g2 验证
g2 = MarketGame()
g2.from_dict(g.to_dict())
check("hidden recipe 跨 save/load 保留",
      "老吴私房菌菇煲" in g2.unlocked_hidden_recipes)


# ============================================================
section("bargain: 减价指令触发价格调整")
# ============================================================
_testutil.reset()
g = MarketGame()
g.cmd("菜场")
g.cmd("去 veg_1")
# 多次砍价，记录状态变化
states = []
for _ in range(5):
    r = g.cmd("便宜点")
    states.append((g.budget, g.spent, len(g.basket)))
print(f"  bargain states: {states}")
# bargain 不应该花任何钱（只是讨价还价过程）
check("5 次砍价后 budget 不变", all(s[0] == states[0][0] for s in states))


# ============================================================
section("cooking_log 累积")
# ============================================================
_testutil.reset()
g = MarketGame()
g.cmd("菜场")
g.cmd("去 veg_1")
g.budget = 100
g.cmd("买 小白菜")
g.cmd("买 大白菜")
g.cmd("回家")
g.cmd("洗 小白菜")
g.cmd("切 小白菜")
g.cmd("加 盐")
g.cmd("出锅")
g.cmd("端")
check("cooking_log 有 step 记录",
      len(g.cooking_log) > 0,
      detail=f"log: {g.cooking_log[:3]}")


# ============================================================
section("bad_input: 不认识的 cmd 不崩")
# ============================================================
_testutil.reset()
g = MarketGame()
g.cmd("菜场")
# 一堆乱码
bad_inputs = [
    "abcdefg", "中文乱码测试", "123", "@#$%",
    "kill the player", "drop table saves",
    "==", "===test===", "<script>alert(1)</script>",
    "\x00\x01", " " * 20,
]
for inp in bad_inputs:
    r = g.cmd(inp)
    if not isinstance(r, str):
        check(f"bad input {inp[:20]!r}", False)
        break
else:
    check("所有 bad input 不崩", True)


# ============================================================
section("milestone reward 多种类型")
# ============================================================
# per-stall milestone 触发后看 reward 是否落到位
# aff20 → discount
# aff50 → free_item or recipe
# aff75 → secret, item, perk etc
_testutil.reset()
g = MarketGame()
g.cmd("菜场")
g.cmd("去 veg_1")
g.affection["veg_1"] = 80  # 一次过 3 个 milestone
g.cmd("去 veg_1")  # fire all
# 应该 discount + free_item + recipe
discount = getattr(g, "_stall_discounts", {}).get("veg_1", 0)
check("aff80 milestone discount 设上", discount > 0,
      detail=f"discount={discount}")
# basket 应有 free_item (香菜) + recipe 解锁
free_items = [it for it in g.basket if it.get("_free")]
check("aff80 milestone free_item 触发",
      any(it["name"] == "香菜" for it in free_items),
      detail=f"free_items: {free_items}")
check("aff80 milestone 王姐家腌雪里蕻 解锁",
      "王姐家腌雪里蕻" in g.unlocked_hidden_recipes,
      detail=f"unlocked: {g.unlocked_hidden_recipes}")


print("\n=== bargain / chain / milestone 完成 ===")