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
    # P1-31：add 前查重——STALL_BY_ID 是字典推导，重复 id 时后者静默覆盖前者，
    # 这是引用检查查不到的最典型数据错误
    stall_ids = set()
    for s in STALLS:
        sid = s.get("id")
        if not sid:
            errors.append(f"STALLS 条目缺 id: {s.get('name', '?')}")
            continue
        if sid in stall_ids:
            errors.append(f"STALLS 重复 id: {sid}（后者覆盖前者）")
        stall_ids.add(sid)
    wander_ids = set()
    for w in WANDERING_STALLS:
        wid = w.get("id")
        if not wid:
            errors.append(f"WANDERING_STALLS 条目缺 id: {w.get('name', '?')}")
            continue
        if wid in wander_ids:
            errors.append(f"WANDERING_STALLS 重复 id: {wid}（后者覆盖前者）")
        wander_ids.add(wid)
    all_stall_ids = stall_ids | wander_ids

    # MARKET_DISASTERS 的 id 存在性（P0-10：与摊位检查对齐，
    # 否则第 4 节直接 d['id'] 下标会在脏数据上崩）
    for d in MARKET_DISASTERS:
        if not d.get("id"):
            errors.append(f"MARKET_DISASTERS 条目缺 id: {d.get('name', '?')}")

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
        ms_id = ms.get("id", "?")
        ms_stall = ms.get("stall")
        if not ms_stall:
            errors.append(f"里程碑「{ms_id}」缺 stall 字段")
            continue
        check_stall(ms_stall, f"里程碑「{ms_id}」")

    # STORY_BEATS
    for story_id, beats in STORY_BEATS.items():
        for beat in beats:
            sid = beat.get("stall")
            bid = beat.get("id", "?")
            if sid:
                check_stall(sid, f"故事「{bid}」")

    # CHOICE_CHAINS
    for chain_id, chain in CHOICE_CHAINS.items():
        for step in chain.get("steps", []):
            trigger = step.get("trigger") or {}
            sid = trigger.get("stall")
            step_id = step.get("id", "?")
            if sid:
                check_stall(sid, f"选择链「{step_id}」")

    # STALL_RELATIONS
    for i, rel in enumerate(STALL_RELATIONS):
        rel_name = rel.get("relation", "?")
        a = rel.get("a")
        b = rel.get("b")
        if not a or not b:
            errors.append(f"STALL_RELATIONS[{i}] 缺 a/b: {rel_name}")
            continue
        check_stall(a, f"摊主关系「{rel_name}」a")
        check_stall(b, f"摊主关系「{rel_name}」b")

    # TIMED_ENCOUNTERS
    for te in TIMED_ENCOUNTERS:
        te_id = te.get("id", "?")
        condition = te.get("condition") or {}
        sid = condition.get("stall")
        if sid:
            check_stall(sid, f"限时奇遇「{te_id}」")

    # ── 4. 灾害分类 ──
    veggie_cats = {v.get("cat", "") for v in VEGGIES.values()}
    for d in MARKET_DISASTERS:
        for cat in d.get("effects", {}).get("closed_cats", []):
            if cat not in veggie_cats:
                # P0-10：.get('id','?')——脏数据来了也要把报告打完整
                errors.append(f"灾害「{d.get('id', '?')}」closed_cats 里的「{cat}」不在 VEGGIES 分类中")

    # ── 5. sells格式 ──
    def _check_sells_items(owner_label, sells):
        """摊位 sells 的统一校验：dict（按季）/list/其他类型。"""
        if isinstance(sells, dict):
            for season, items in sells.items():
                # 值必须是可迭代的集合类型——误写成字符串会按字符逐个比对出垃圾错误
                if not isinstance(items, (list, tuple, set)):
                    errors.append(f"{owner_label} sells.{season} 类型异常: {type(items)}（应为列表）")
                    continue
                for item in items:
                    if item not in VEGGIES:
                        errors.append(f"{owner_label} sells.{season} 里的「{item}」不在 VEGGIES")
        elif isinstance(sells, list):
            for item in sells:
                if item not in VEGGIES:
                    errors.append(f"{owner_label} sells 里的「{item}」不在 VEGGIES")
        else:
            errors.append(f"{owner_label} sells 类型异常: {type(sells)}")

    for stall in STALLS:
        _check_sells_items(f"摊位「{stall.get('id', '?')}」", stall.get("sells", []))

    for ws in WANDERING_STALLS:
        # P1-33：与 STALLS 分支对齐——补 else 类型异常兜底，脏数据不再漏检
        _check_sells_items(f"流动摊「{ws.get('id', '?')}」", ws.get("sells", []))

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
    # P1-30：SECRET_AREAS 的 id 与专属食材也是合法引用——market_data 构建
    # ITEM_STALL_INDEX 时收录了秘境摊，不纳入合法集会把真数据报成假警告，
    # WARN 通道被假阳性灌满后真正的缺数据警告反而没人看了
    secret_ids = set(SECRET_AREAS.keys()) if isinstance(SECRET_AREAS, dict) else set()
    legal_stall_ids = all_stall_ids | secret_ids
    secret_items = set()
    if isinstance(SECRET_AREAS, dict):
        for s in SECRET_AREAS.values():
            sells = s.get("sells", []) if isinstance(s, dict) else []
            if isinstance(sells, list):
                secret_items.update(sells)

    for item_name, stall_refs in ITEM_STALL_INDEX.items():
        if item_name not in VEGGIES and item_name not in secret_items:
            warns.append(f"ITEM_STALL_INDEX 引用不存在的食材: {item_name}")
        stall_list = stall_refs if isinstance(stall_refs, list) else [stall_refs]
        for sid in stall_list:
            if sid not in legal_stall_ids:
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
        # 按类别前缀去重（P1-34：原写法把整条消息拼回 key，永远不命中，
        # 去重实际不生效；多条目消息还会被 ": " 截断误合并）
        seen = set()
        for w in warns:
            key = w.split(":")[0].strip()
            if key not in seen:
                seen.add(key)
                print(f"  • {w}")

    return len(errors)


if __name__ == "__main__":
    n = validate()
    # P1-32：退出码布尔化——POSIX 只保留低 8 位，错误数恰好 256/512…
    # 时 sys.exit(n) 会回绕成 0，CI 会把校验失败误判为通过
    sys.exit(1 if n > 0 else 0)
