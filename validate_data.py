"""
上桌 · 数据校验
检查所有交叉引用，启动前跑一遍就知道哪里对不上。
python validate_data.py
"""

import sys

def validate():
    from market_data import (
        VEGGIES, STALLS, WANDERING_STALLS, STORY_BEATS, CHOICE_CHAINS,
        AFFECTION_MILESTONES, SECRET_AREAS, STALL_RELATIONS, TIMED_ENCOUNTERS,
        HIDDEN_RECIPES, KITCHEN_ACCIDENTS, CUTTING_TRAP,
        MARKET_DISASTERS, KEEP_DAYS, YIELD_PCT, FRAGILE_LEVEL,
        STALL_BY_ID, ITEM_STALL_INDEX,
    )
    # TODO: market_data 里没有 RECIPE_DISCOVERIES（v1.0 起就一直缺失），
    # 等数据层补上对应字段后再恢复下方的校验块。
    from market_recipes import RECIPES

    errors = []
    warns = []

    # ── 1. 摊位ID ──
    stall_ids = {s["id"] for s in STALLS}
    wander_ids = {w["id"] for w in WANDERING_STALLS}
    all_stall_ids = stall_ids | wander_ids

    # STALL_BY_ID 一致性
    for sid in STALL_BY_ID:
        if sid not in all_stall_ids:
            errors.append(f"STALL_BY_ID 有未定义的摊位: {sid}")

    # ── 2. 食材引用 ──
    KITCHEN_STAPLES = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱", "葱", "姜", "蒜"}
    FISH_ALIASES = {"鱼"}  # 别名，不需要在VEGGIES里

    def check_item(name, source):
        if name in KITCHEN_STAPLES or name in FISH_ALIASES:
            return  # 厨房常备和别名不算错
        if name not in VEGGIES:
            errors.append(f"{source}: 食材「{name}」不在 VEGGIES 里")

    # RECIPES
    for rname, rdata in RECIPES.items():
        for ing in rdata.get("ingredients", []):
            check_item(ing, f"菜谱「{rname}」")

    # HIDDEN_RECIPES
    for rname, rdata in HIDDEN_RECIPES.items():
        for ing in rdata.get("ingredients", []):
            check_item(ing, f"隐藏菜谱「{rname}」")

    # RECIPE_DISCOVERIES — 见上方 TODO，等数据补回后恢复
    # for disc in RECIPE_DISCOVERIES:
    #     for item in disc.get("items", set()):
    #         check_item(item, f"配方发现「{disc.get('hint','?')[:20]}」")

    # CUTTING_TRAP
    for name in CUTTING_TRAP:
        if name not in VEGGIES:
            errors.append(f"CUTTING_TRAP: 食材「{name}」不在 VEGGIES 里（死代码）")

    # KITCHEN_ACCIDENTS - trigger keywords don't need to be items, skip

    # ── 3. 摊位ID引用 ──
    def check_stall(sid, source):
        if sid not in all_stall_ids:
            errors.append(f"{source}: 摊位「{sid}」不存在")

    # AFFECTION_MILESTONES
    for ms in AFFECTION_MILESTONES:
        check_stall(ms["stall"], f"里程碑「{ms['id']}」")

    # STORY_BEATS
    for story_id, beats in STORY_BEATS.items():
        for beat in beats:
            sid = beat.get("stall")
            if sid:
                check_stall(sid, f"故事「{beat['id']}」")

    # CHOICE_CHAINS
    for chain_id, chain in CHOICE_CHAINS.items():
        for step in chain.get("steps", []):
            sid = step.get("trigger", {}).get("stall")
            if sid:
                check_stall(sid, f"选择链「{step['id']}」")

    # STALL_RELATIONS
    for rel in STALL_RELATIONS:
        check_stall(rel["a"], f"摊主关系「{rel.get('relation','?')}」a")
        check_stall(rel["b"], f"摊主关系「{rel.get('relation','?')}」b")

    # TIMED_ENCOUNTERS
    for te in TIMED_ENCOUNTERS:
        sid = te.get("condition", {}).get("stall")
        if sid:
            check_stall(sid, f"限时奇遇「{te['id']}」")

    # ── 4. 灾害分类 ──
    veggie_cats = {v.get("cat", "") for v in VEGGIES.values()}
    for d in MARKET_DISASTERS:
        for cat in d.get("effects", {}).get("closed_cats", []):
            if cat not in veggie_cats:
                errors.append(f"灾害「{d['id']}」closed_cats 里的「{cat}」不在 VEGGIES 分类中")

    # ── 5. sells格式 ──
    for stall in STALLS:
        sells = stall.get("sells", [])
        if isinstance(sells, dict):
            # 流动摊的dict格式——检查每季的食材
            for season, items in sells.items():
                for item in items:
                    if item not in VEGGIES:
                        errors.append(f"摊位「{stall['id']}」sells.{season} 里的「{item}」不在 VEGGIES")
        elif isinstance(sells, list):
            for item in sells:
                if item not in VEGGIES:
                    errors.append(f"摊位「{stall['id']}」sells 里的「{item}」不在 VEGGIES")
        else:
            errors.append(f"摊位「{stall['id']}」sells 类型异常: {type(sells)}")

    for ws in WANDERING_STALLS:
        sells = ws.get("sells", [])
        if isinstance(sells, dict):
            for season, items in sells.items():
                for item in items:
                    if item not in VEGGIES:
                        errors.append(f"流动摊「{ws['id']}」sells.{season} 里的「{item}」不在 VEGGIES")
        elif isinstance(sells, list):
            for item in sells:
                if item not in VEGGIES:
                    errors.append(f"流动摊「{ws['id']}」sells 里的「{item}」不在 VEGGIES")

    # ── 6. 补全数据缺失（警告） ──
    all_item_names = set(VEGGIES.keys())
    for name in all_item_names:
        if name not in KEEP_DAYS:
            warns.append(f"KEEP_DAYS 缺: {name}")
        if name not in YIELD_PCT:
            warns.append(f"YIELD_PCT 缺: {name}")
        if name not in FRAGILE_LEVEL:
            warns.append(f"FRAGILE_LEVEL 缺: {name}")

    # ── 7. ITEM_STALL_INDEX 一致性 ──
    for item_name, stall_refs in ITEM_STALL_INDEX.items():
        if item_name not in VEGGIES:
            warns.append(f"ITEM_STALL_INDEX 引用不存在的食材: {item_name}")
        stall_list = stall_refs if isinstance(stall_refs, list) else [stall_refs]
        for sid in stall_list:
            if sid not in all_stall_ids:
                warns.append(f"ITEM_STALL_INDEX 引用不存在的摊位: {sid}")

    # ── 报告 ──
    print(f"=== 上桌数据校验 ===")
    print(f"食材: {len(VEGGIES)} | 摊位: {len(stall_ids)}+{len(wander_ids)}流动 | 故事线: {len(STORY_BEATS)}")
    print()

    if errors:
        print(f"[ERR] {len(errors)} 个错误：")
        for e in errors:
            print(f"  - {e}")
    else:
        print("[OK] 0 错误")

    if warns:
        print(f"\n[WARN] {len(warns)} 个警告（缺数据，会用默认值）：")
        # 去重
        seen = set()
        for w in warns:
            key = w.split(": ")[0] + ": " + w.split(": ")[1] if ": " in w else w
            if key not in seen:
                seen.add(key)
                print(f"  • {w}")

    return len(errors)


if __name__ == "__main__":
    n = validate()
    sys.exit(n)
