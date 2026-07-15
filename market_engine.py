"""
菜市场 · 给 AI 玩的一顿饭游戏
引擎核心

一局 = 一顿饭：roll预算 → 逛菜场 → 买 → 做菜 → 端上桌 → 老婆吃
存档跨局：冰箱里的东西留着，熟客关系留着
"""

import json
import os
import random
import re
import time

# ---- 全局配置 ----
COMPACT_MODE = False  # True=省token精简模式，False=沉浸模式
DAYS_PER_SEASON = 7   # 每季天数

from market_data import (
    SEASONS, VEGGIES, STALLS, CAT_MESSAGES,
    BARGAIN_LINES, COOK_VERBS, WIFE_REACTIONS,
    WANDERING_STALLS, MARKET_EVENTS, BARGAIN_STRATEGIES, BARGAIN_BACKFIRE,
    KITCHEN_ACCIDENTS, ACHIEVEMENTS,
    ZONE_AMBIENCE, SEASON_AMBIENCE, STALL_JARGON, WEIGHT_TRICKS, STALL_RELATIONS,
    ZONE_NAV, TIME_OF_DAY, EXTRA_EVENTS,
    KEEP_DAYS, YIELD_PCT, UNIT_TRICKS, BUNDLE_TRICKS, MISLEADING_COMPARE,
    FALSE_INTEL, OWNER_REVERSE_TALK, STALL_STORIES,
    SKILL_TREE, REGULAR_TIERS,
    NPC_PROFILES, AFFECTION_STAGES, get_affection_stage,
    OWNER_TRAITS, STORY_BEATS,
    STALL_BY_ID, ITEM_STALL_INDEX,
    FRAGILE_LEVEL, WEIGHT_TRICK_TYPE, CUTTING_TRAP, PREP_SKILLS,
    QUALITY_WEIGHT_TABLE,
    WIFE_PALATE,
    COOK_STAGES, ITEM_SENSE_CAT, POT_SOUNDS, POT_SMELLS,
    SOLD_OUT_CONFIG, WEATHER_EFFECTS, JOURNEY_TEXT,
    RARE_FINDS, RARE_FIND_RARITY, SERVE_DRAMA,
    SECRET_AREAS, AFFECTION_MILESTONES, HIDDEN_RECIPES, TIMED_ENCOUNTERS,
    HELP_EVENTS,
    REPUTATION_DIMS, CHOICE_CHAINS, CLUE_FRAGMENTS, CLUE_COMBOS, ENDINGS,
    KITCHEN_ACCIDENTS, COOKING_MOOD, COOK_STEP_FEEDBACK,
    OWNER_MEMORY_TEMPLATES, CROSS_STALL_MEMORY_TEMPLATES,
    PLAYER_SKILLS,
    MARKET_DISASTERS,
    ITEM_SENSE_PREP,
    VENDOR_STORYLINES,
    SOLAR_TERMS, SOLAR_TERM_EVENTS,
)
from market_quality import QUALITY_DESC, TRAP_TRUTH
from market_recipes import RECIPES

# 以下可能在market_data里没有定义，给空默认
try:
    from market_data import RECIPE_DISCOVERIES
except ImportError:
    RECIPE_DISCOVERIES = []

try:
    from market_data import DAY_END_EVENTS
except ImportError:
    DAY_END_EVENTS = []

# 神秘时空层（可选——缺文件不崩）
try:
    from mystic_engine import MysticLayer
    from mystic_data import MYSTIC_STALL_IDS
except ImportError:
    MysticLayer = None
    MYSTIC_STALL_IDS = []

def _save_dir():
    """获取存档目录——兼容exec环境"""
    try:
        d = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        d = os.getcwd()
    return d

SAVE_FILE = os.path.join(_save_dir(), "market_save.json")

# 厨房默认有的调味品（不用买）
KITCHEN_DEFAULTS = [
    {"name": "大葱", "quality": "ok", "qty": 1},
    {"name": "姜", "quality": "ok", "qty": 1},
    {"name": "蒜", "quality": "ok", "qty": 1},
    {"name": "盐", "quality": "ok", "qty": 1},
    {"name": "酱油", "quality": "ok", "qty": 1},
    {"name": "醋", "quality": "ok", "qty": 1},
    {"name": "糖", "quality": "ok", "qty": 1},
    {"name": "料酒", "quality": "ok", "qty": 1},
    {"name": "淀粉", "quality": "ok", "qty": 1},
    {"name": "油", "quality": "ok", "qty": 1},
    {"name": "水", "quality": "ok", "qty": 1},
]

# ---- PRNG (跟钓鱼游戏一样，确定性) ----

def mulberry32(seed):
    def _next():
        nonlocal seed
        seed = (seed + 0x6D2B79F5) & 0xFFFFFFFF
        t = seed
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t = (t ^ (t >> 15)) & 0xFFFFFFFF
        return t
    return _next


class MarketGame:
    def __init__(self):
        self.rng = mulberry32(0)
        self.seed = 0
        self.day = 0
        self.season = ""
        self.weather = "晴"
        self.budget = 0        # 本局预算
        self.spent = 0         # 已花
        self.fridge = []       # 冰箱内容 [{name, quality, qty}]
        self.basket = []       # 本局买的 [{name, quality, qty, price, stall, owner}]
        self.visit_count = {}  # stall_id → 次数（熟客）
        self.kitchen_state = None  # 做菜状态
        self.cooking_log = []  # 做菜步骤记录
        self.plate = None      # 端上桌的菜
        self.turn = 0          # 本局回合
        self.done = False      # 本局结束
        self.current_stall = None  # 当前逛的摊
        self.current_zone = None   # 当前逛的分区
        self.time_of_day = "上午"  # 时段：早市/上午/散市
        self.market_time = 0     # 菜场剩余时间
        self.market_time_max = 0
        self._market_closed = False
        self.no_weight_trick = False  # L5市场检查：当天禁分量坑
        self.inspected_items = {}  # L4细看过的菜：name→{quality, found_flaw}
        self.cook_history = {}    # 菜名→做过的次数（手艺成长）
        self.achievements = []    # 已解锁的成就id
        self.affection = {}       # stall_id → 好感度(0-100)，跨天保存
        self.story_progress = []  # 已触发的故事片段id，跨天保存
        self.wife_state = ""      # 你告诉他的状态，空=正常
        self.reputation = {"kind": 0, "generous": 0, "honest": 0, "regular": 0}  # 声望
        self.chain_flags = set()  # 选择链标记
        self.chain_done = set()   # 已触发的选择链步骤id
        self.found_clues = set()  # 已发现的线索碎片id
        self.unlocked_combos = set()  # 已解锁的线索组合
        self.ending = None        # 当前结局id
        self.palate = {           # 他记住的你的口味——初始空白，慢慢学
            "dislikes": {},       # 不吃：菜名→原因
            "loves": {},          # 爱吃：菜名→描述
            "fears": {},          # 怕：菜名→描述
            "texture": {},        # 口感：食材→偏好
        }
        self.stats = {           # 统计数据（成就判定用）
            "bargain_streak": 0,      # 砍价连续成功
            "bargain_fail_streak": 0, # 砍价连续失败
            "good_buy_streak": 0,     # 连续买好菜
            "bad_buy_streak": 0,      # 连续买差菜
            "terrible_dishes": 0,     # terrible品相的菜数
            "unique_dishes": set(),   # 做过的不同菜名
            "unique_days": set(),     # 做过饭的不同天数
        }
        # new_day() 会重置这些，但 save() 可能在 new_day 之前被调
        self.unlocked_skills = []
        self.inspect_counts = {
            "绿叶": 0, "根茎": 0, "瓜果": 0, "豆类": 0,
            "菌菇": 0, "豆制品": 0, "肉": 0, "鱼": 0, "蛋": 0, "调味": 0,
            "scale": 0,
        }
        self.closed_stalls = set()
        self.sold_out = {}
        self._owner_daily = {}
        self._today_disaster = None
        self._disaster_price_mod = 1.0
        self._disaster_quality_mod = 0
        self._disaster_bargain_bonus = 0
        self._season_stall_items = {}
        self._stall_item_cache = {}
        self._rare_boost_today = False
        self._neighbor_conflict = False
        self._roof_leaking = False
        self._max_carry = 5
        self._last_stall = None
        self._season_day = 1
        self._season_ending = False
        self._journey_text = ""
        self._journey_shown = False
        self._today_solar_term = None  # 当天节气事件
        self.storyline_state = {}  # {vendor_name: {"arc": arc_name, "day": day_num}}
        # 神秘时空层
        self.mystic = MysticLayer(self) if MysticLayer else None
        self.in_mystic = False
        self.savings = 0  # 攒钱罐——昨天剩的一半存进来，跨天保存

    # ---- 存档 ----

    SAVE_VERSION = 10

    @staticmethod
    def _set_to_list(obj):
        """递归把set转list，确保JSON可序列化。"""
        if isinstance(obj, set):
            return sorted(obj, key=str)
        if isinstance(obj, dict):
            return {k: MarketGame._set_to_list(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [MarketGame._set_to_list(x) for x in obj]
        return obj

    @staticmethod
    def _restore_sets_in_ks(obj):
        """kitchen_state里的set字段还原。处理两种格式：list和{'__t':'set','v':list}。"""
        _SET_KEYS = {"completed_steps", "completed_optional", "_on_board", "discovered_recipes"}
        if isinstance(obj, dict):
            # __t标记格式
            if obj.get('__t') == 'set':
                return set(obj.get('v', []))
            result = {}
            for k, v in obj.items():
                if k in _SET_KEYS:
                    if isinstance(v, list):
                        result[k] = set(v)
                    elif isinstance(v, dict) and v.get('__t') == 'set':
                        result[k] = set(v.get('v', []))
                    else:
                        result[k] = MarketGame._restore_sets_in_ks(v)
                else:
                    result[k] = MarketGame._restore_sets_in_ks(v)
            return result
        if isinstance(obj, list):
            return [MarketGame._restore_sets_in_ks(x) for x in obj]
        return obj

    # ---- rng 状态持久化 ----
    # mulberry32 是闭包：nonlocal seed 是它的内部状态。
    # 存这个内部 seed = 存调用进度；load 用 mulberry32(state) 重建闭包即可接续。
    # 否则每次新进程 load 都回到 mulberry32(seed) 起点，同一天菜价/品质/事件对不上。
    def _get_rng_state(self):
        try:
            return self.rng.__closure__[0].cell_contents
        except (IndexError, AttributeError):
            return None

    def _set_rng_state(self, state):
        if state is not None:
            self.rng = mulberry32(state)

    def _trace_day(self, old_day, reason):
        """day 变更追踪——写 stderr，帮定位"天数莫名跳变"。
        正常只有 new_day 推进1天、mystic 时间循环回退1天会触发。
        若日志里出现别的调用栈→就是 ghost bug。"""
        import sys, traceback
        caller = traceback.format_stack()[-2].strip().split("\n")[0]
        print(f"[day-trace] {old_day}→{self.day} ({reason}) from {caller}", file=sys.stderr)

    def to_dict(self):
        """把当前状态导出成可JSON的dict——save和engine.py共用这一份逻辑。"""
        # basket: 去掉actual_yield（预处理副作用，load时重新算）
        basket_clean = []
        for item in self.basket:
            item2 = {k: v for k, v in item.items() if k != "actual_yield"}
            basket_clean.append(item2)

        # kitchen_state: set→list（递归）
        ks_serialized = self._set_to_list(self.kitchen_state) if self.kitchen_state else None

        data = {
            "save_version": self.SAVE_VERSION,
            "seed": self.seed,
            "day": self.day,
            "fridge": self.fridge,
            "basket": basket_clean,
            "kitchen_state": ks_serialized,
            "done": self.done,
            "current_stall": self.current_stall,
            "current_zone": self.current_zone,
            "market_time": self.market_time,
            "market_time_max": self.market_time_max,
            "market_closed": self._market_closed,
            "closed_stalls": list(self.closed_stalls),
            "sold_out": {k: list(v) for k, v in self.sold_out.items()},
            "budget": self.budget,
            "spent": self.spent,
            "visit_count": self.visit_count,
            "cook_history": self.cook_history,
            "achievements": self.achievements,
            "stats_bargain_streak": self.stats["bargain_streak"],
            "stats_bargain_fail_streak": self.stats["bargain_fail_streak"],
            "stats_good_buy_streak": self.stats["good_buy_streak"],
            "stats_bad_buy_streak": self.stats["bad_buy_streak"],
            "stats_terrible_dishes": self.stats["terrible_dishes"],
            "stats_unique_dishes": list(self.stats["unique_dishes"]),
            "stats_unique_days": list(self.stats["unique_days"]),
            "unlocked_skills": self.unlocked_skills,
            "inspect_counts": self.inspect_counts,
            "affection": self.affection,
            "story_progress": self.story_progress,
            "wife_state": self.wife_state,
            "palate": self.palate,
            "state_avoid": getattr(self, '_state_avoid', []),
            "state_craving": getattr(self, '_state_craving', []),
            "encyclopedia_items": list(getattr(self, 'encyclopedia', {}).get("items_bought", set())),
            "encyclopedia_rare": list(getattr(self, 'encyclopedia', {}).get("rare_found", set())),
            "encyclopedia_recipes": list(getattr(self, 'encyclopedia', {}).get("recipes_unlocked", set())),
            "encyclopedia_areas": list(getattr(self, 'encyclopedia', {}).get("areas_found", set())),
            "encyclopedia_milestones": list(getattr(self, 'encyclopedia', {}).get("milestones_triggered", set())),
            "encyclopedia_encounters": list(getattr(self, 'encyclopedia', {}).get("encounters_triggered", set())),
            "unlocked_secrets": list(getattr(self, "unlocked_secrets", set())),
            "unlocked_milestones": list(getattr(self, "unlocked_milestones", set())),
            "unlocked_hidden_recipes": list(getattr(self, "unlocked_hidden_recipes", set())),
            "perks": list(getattr(self, "_perks", set())),
            "reputation": getattr(self, "reputation", {"kind": 0, "generous": 0, "honest": 0, "regular": 0}),
            "chain_flags": list(getattr(self, "chain_flags", set())),
            "chain_done": list(getattr(self, "chain_done", set())),
            "found_clues": list(getattr(self, "found_clues", set())),
            "unlocked_combos": list(getattr(self, "unlocked_combos", set())),
            "ending": getattr(self, "ending", None),
            "owner_memory": getattr(self, "owner_memory", {}),
            "player_skills": getattr(self, "player_skills", {"刀工": 0, "火候": 0, "识货": 0}),
            "dish_feedback": getattr(self, "dish_feedback", {}),
            "dish_history": getattr(self, "dish_history", {}),
            "rt_storyline_state": getattr(self, "storyline_state", {}),
            "rt_solar_term": getattr(self, '_today_solar_term', None),
            "savings": getattr(self, "savings", 0),
            "mystic_state": (self.mystic.state_for_save() if self.mystic else None),
            "rt_rng_state": self._get_rng_state(),
            "_last_opened_day": getattr(self, "_last_opened_day", None),
        }
        return data

    def save(self):
        data = self.to_dict()
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self):
        if os.path.exists(SAVE_FILE):
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
        return self.from_dict(data)

    def from_dict(self, data):
        """从dict装回self——load和engine.py共用这一份逻辑。
        data可以是{}（新档）/旧版本dict/当前版本dict。"""
        # 版本迁移
        version = data.get("save_version", 1)
        if version < 2:
            # v1→v2: 新增 unlocked_skills / inspect_counts
            data.setdefault("unlocked_skills", [])
            data.setdefault("inspect_counts", {
                "绿叶": 0, "根茎": 0, "瓜果": 0, "豆类": 0,
                "菌菇": 0, "豆制品": 0, "肉": 0, "鱼": 0, "蛋": 0, "调味": 0,
                "scale": 0,
            })
            data["save_version"] = 2
        if version < 3:
            # v2→v3: 新增 affection + story_progress
            data.setdefault("affection", {})
            data.setdefault("story_progress", [])
            data["save_version"] = 3
        if version < 4:
            # v3→v4: 新增 wife_state + palate
            data.setdefault("wife_state", "")
            data.setdefault("palate", {"dislikes": {}, "loves": {}, "fears": {}, "texture": {}})
            data.setdefault("state_avoid", [])
            data.setdefault("state_craving", [])
            data["save_version"] = 4
        if version < 5:
            # v4→v5: 无新增存档字段，只是引擎内部用item_state替代raw/done_items
            data["save_version"] = 5
        if version < 6:
            # v5→v6: 新增 reputation + choice_chain + clue + ending
            data.setdefault("reputation", {"kind": 0, "generous": 0, "honest": 0, "regular": 0})
            data.setdefault("chain_flags", [])
            data.setdefault("chain_done", [])
            data.setdefault("found_clues", [])
            data.setdefault("unlocked_combos", [])
            data.setdefault("ending", None)
            data["save_version"] = 6
        if version < 7:
            # v6→v7: 新增 owner_memory（摊主跨天记忆）
            data.setdefault("owner_memory", {})
            data["save_version"] = 7
        if version < 8:
            # v7→v8: 新增 player_skills（玩家技能成长）
            data.setdefault("player_skills", {"刀工": 0, "火候": 0, "识货": 0})
            data["save_version"] = 8
        if version < 9:
            # v8→v9: basket/kitchen_state/done + 每日状态纳入存档
            data.setdefault("basket", [])
            data.setdefault("kitchen_state", None)
            data.setdefault("done", False)
            data.setdefault("current_stall", None)
            data.setdefault("current_zone", None)
            data.setdefault("market_time", 0)
            data.setdefault("market_time_max", 0)
            data.setdefault("market_closed", False)
            data.setdefault("closed_stalls", [])
            data.setdefault("sold_out", {})
            data.setdefault("budget", 0)
            data.setdefault("spent", 0)
            # stats里的冗余字段清掉——只保留纯统计
            data["save_version"] = 9
        if version < 10:
            # v9→v10: rng 调用进度持久化（rt_rng_state）
            data.setdefault("rt_rng_state", None)
            data["save_version"] = 10
        self.seed = data.get("seed", 0)
        # 恢复 rng 调用进度——有存档则接续闭包内部状态，否则用 seed 起
        # （None 时不能用 _set_rng_state——那是 no-op，会留 __init__ 的 mulberry32(0)）
        _rng_state = data.get("rt_rng_state")
        if _rng_state is not None:
            self._set_rng_state(_rng_state)
        else:
            self.rng = mulberry32(self.seed)
        self.day = data.get("day", 0)
        self._last_opened_day = data.get("_last_opened_day", None)
        self.fridge = data.get("fridge", [])
        self.basket = data.get("basket", [])
        # kitchen_state: list→set 还原
        ks_raw = data.get("kitchen_state")
        self.kitchen_state = self._restore_sets_in_ks(ks_raw) if ks_raw else None
        self.done = data.get("done", False)
        self.current_stall = data.get("current_stall")
        self.current_zone = data.get("current_zone")
        self.market_time = data.get("market_time", 0)
        self.market_time_max = data.get("market_time_max", 0)
        self._market_closed = data.get("market_closed", False)
        self.closed_stalls = set(data.get("closed_stalls", []))
        self.sold_out = {k: set(v) for k, v in data.get("sold_out", {}).items()}
        self.budget = data.get("budget", 0)
        self.spent = data.get("spent", 0)
        self.visit_count = data.get("visit_count", {})
        self.cook_history = data.get("cook_history", {})
        self.achievements = data.get("achievements", [])
        self.stats = {
            "bargain_streak": data.get("stats_bargain_streak", 0),
            "bargain_fail_streak": data.get("stats_bargain_fail_streak", 0),
            "good_buy_streak": data.get("stats_good_buy_streak", 0),
            "bad_buy_streak": data.get("stats_bad_buy_streak", 0),
            "terrible_dishes": data.get("stats_terrible_dishes", 0),
            "unique_dishes": set(data.get("stats_unique_dishes", [])),
            "unique_days": set(data.get("stats_unique_days", [])),
        }
        # 这 4 个 save 存了、迁移 setdefault 了，但以前 load 没读回——跨进程全丢
        # （affection/story_progress 是跨天持久的好感和剧情，丢了等于白玩；阿枭 P0）
        self.unlocked_skills = data.get("unlocked_skills", [])
        self.inspect_counts = data.get("inspect_counts", {
            "绿叶": 0, "根茎": 0, "瓜果": 0, "豆类": 0,
            "菌菇": 0, "豆制品": 0, "肉": 0, "鱼": 0, "蛋": 0, "调味": 0,
            "scale": 0,
        })
        self.affection = data.get("affection", {})
        self.story_progress = data.get("story_progress", [])
        self.wife_state = data.get("wife_state", "")
        self.palate = data.get("palate", {"dislikes": {}, "loves": {}, "fears": {}, "texture": {}})
        self._state_avoid = data.get("state_avoid", [])
        self._state_craving = data.get("state_craving", [])
        self.encyclopedia = {
            "items_bought": set(data.get("encyclopedia_items", [])),
            "rare_found": set(data.get("encyclopedia_rare", [])),
            "recipes_unlocked": set(data.get("encyclopedia_recipes", [])),
            "areas_found": set(data.get("encyclopedia_areas", [])),
            "milestones_triggered": set(data.get("encyclopedia_milestones", [])),
            "encounters_triggered": set(data.get("encyclopedia_encounters", [])),
        }
        self.unlocked_secrets = set(data.get("unlocked_secrets", []))
        self.unlocked_milestones = set(data.get("unlocked_milestones", []))
        self.unlocked_hidden_recipes = set(data.get("unlocked_hidden_recipes", []))
        self._perks = set(data.get("perks", []))
        self.reputation = data.get("reputation", {"kind": 0, "generous": 0, "honest": 0, "regular": 0})
        self.chain_flags = set(data.get("chain_flags", []))
        self.chain_done = set(data.get("chain_done", []))
        self.found_clues = set(data.get("found_clues", []))
        self.unlocked_combos = set(data.get("unlocked_combos", []))
        self.ending = data.get("ending", None)
        # owner_memory: {stall_id: [{"day":N, "type":"helped", "detail":"搬鱼箱"}, ...]} 最多5条
        self.owner_memory = data.get("owner_memory", {})
        self.player_skills = data.get("player_skills", {"刀工": 0, "火候": 0, "识货": 0})
        # dish_feedback: {菜名: [{day, text, appearance}]} 她吃过的反应
        self.dish_feedback = data.get("dish_feedback", {})
        # dish_history: {菜名: [{day, appearance}]} 每次做菜的品相记录
        self.dish_history = data.get("dish_history", {})
        self.storyline_state = data.get("rt_storyline_state", {})
        self._today_solar_term = data.get("rt_solar_term", None)
        self.savings = data.get("savings", 0)
        if self.mystic:
            self.mystic.load_state(data.get("mystic_state") or {})
        return True

    # ---- 新一局 ----

    def new_day(self, seed=None, force=False):
        """开始新的一局（一顿饭）

        force=True 时跳过"今天已开局"防呆——给「新局 明天/强制」用。
        """
        self.load()  # 先读存档
        if seed is not None:
            self.seed = seed
        else:
            self.seed = int(time.time()) & 0xFFFFFFFF
        self.rng = mulberry32(self.seed)

        # ── 防呆：今天的局还没做完就不许再开新一天，免得反复调 new_day 跳天 ──
        # _last_opened_day 记上次开局定型后的 day。若它等于当前 day 且上局未结束，
        # 说明这天的饭还没端上桌又来开新局——拒绝，把存档原样读回。
        if (getattr(self, "_last_opened_day", None) == self.day
                and not self.done and not force):
            self.load()  # 撤掉刚 mulberry32 的重置，恢复存档 rng
            return (f"⏳ 今天（第{self.day}天）的局已经开过了，还没做完。"
                    f"继续做完用「做/快做/端」，开明天用「新局 明天」强制。")

        _prev_day = self.day  # 神秘时空时间循环需知昨天、结转需知是否第一局
        self.day += 1
        self._trace_day(_prev_day, "new_day推进")
        self.turn = 0
        # 神秘时空：时间循环回退——若昨天在异市做了标记交易，回退1天
        if self.mystic:
            loop_back, self._time_loop_narrative = self.mystic.maybe_time_loop(_prev_day)
            if loop_back:
                self.day -= 1  # 回退1天
                self._trace_day(_prev_day + 1, "mystic时间循环回退")
        # 记录今天开局定型后的 day——给下回 new_day 防呆用
        self._last_opened_day = self.day
        # 上局没做完——买的菜存进冰箱（保鲜0天的扔了）
        if not self.done and self.basket:
            for item in self.basket:
                keep = KEEP_DAYS.get(item["name"], 3)
                if keep > 0:
                    fitem = {"name": item["name"], "quality": item["quality"], "qty": item.get("qty", 1), "keep_days": keep}
                    if item.get("exotic"):  # 神秘时空exotic标记跨天保留
                        fitem["exotic"] = item["exotic"]
                    self.fridge.append(fitem)
        self.done = False
        self.basket = []
        self.cooking_log = []
        self.plate = None
        self.kitchen_state = None

        # ── 冰箱过期 ──
        expired = []  # [{name, quality, was_days}]
        kept = []
        for item in self.fridge:
            kd = item.get("keep_days", 3)
            kd -= 1
            item["keep_days"] = kd
            if kd <= 0:
                expired.append({"name": item["name"], "quality": item.get("quality", "ok"), "was_days": kd + 1})
            else:
                kept.append(item)
        self.fridge = kept

        # 季节——按天数推进，每季7天
        si = ((self.day - 1) // DAYS_PER_SEASON) % 4
        self.season = SEASONS[si]
        self._season_day = ((self.day - 1) % DAYS_PER_SEASON) + 1  # 本季第几天
        self._season_ending = self._season_day >= DAYS_PER_SEASON - 1  # 最后2天

        # roll 天气
        w = self.rng() % 10
        if w < 6:
            self.weather = "晴"
        elif w < 8:
            self.weather = "阴"
        else:
            self.weather = "雨"

        # ── 结转 + 攒钱罐 ──
        # 昨天剩的钱：一半结转到今天预算，另一半进攒钱罐（「取罐」取出）
        # 只有真有"昨天"（prev_day>=1）才结转——第一局别凭空发钱
        if _prev_day >= 1:
            leftover = max(0, round(self.budget - self.spent, 1))
            carry = round(leftover / 2, 1)
            jar_add = round(leftover - carry, 1)
            self.savings = round(self.savings + jar_add, 1)
        else:
            leftover = carry = jar_add = 0
        _savings_before = self.savings

        # roll 预算 (8~28)——紧巴巴，买不起好菜才是常态
        self.budget = 8 + (self.rng() % 21) + carry
        self.spent = 0
        self._carry_hint = carry
        self._jar_before = _savings_before

        # roll 时段
        t = self.rng() % 10
        if t < 3:
            self.time_of_day = "早市"
        elif t < 8:
            self.time_of_day = "上午"
        else:
            self.time_of_day = "散市"

        # ── 菜场时间 ──
        time_by_tod = {"早市": 8, "上午": 5, "散市": 3}
        self.market_time = time_by_tod.get(self.time_of_day, 5)
        if self.weather == "雨":
            self.market_time = max(2, self.market_time - 1)
        self.market_time_max = self.market_time
        self._market_closed = False
        self._rare_boost_today = False

        # L4/L5状态重置
        self.no_weight_trick = False
        self.inspected_items = {}
        self.current_zone = None
        self._neighbor_conflict = False
        self._roof_leaking = False
        self._max_carry = 5             # 携带上限
        self._last_stall = None         # 上次逛的摊（增量输出）
        self._stall_item_cache = {}     # 当前摊位菜品缓存
        self._season_stall_items = {}   # 每摊当季菜品预缓存
        for stall in STALLS:
            self._season_stall_items[stall["id"]] = self._stall_season_items(stall)
        # ── 天气效果 ──
        wfx = WEATHER_EFFECTS.get(self.weather, WEATHER_EFFECTS["晴"])
        self._max_carry = max(3, 5 + wfx["carry_mod"])
        self._weather_price_mod = wfx["price_mod"]

        # ── 缺货roll ──
        soc = SOLD_OUT_CONFIG
        time_m = soc["time_mod"].get(self.time_of_day, 1.0)
        weather_m = soc["weather_mod"].get(self.weather, 1.0)
        self.sold_out = {}
        self.closed_stalls = set()
        for stall in STALLS:
            sid = stall["id"]
            if (self.rng() % 10000) / 10000 < wfx["stall_close"]:
                self.closed_stalls.add(sid)
                continue
            out = set()
            items = self._season_stall_items.get(sid, [])
            for vname in items:
                cat = VEGGIES[vname]["cat"]
                cat_m = soc["cat_mod"].get(cat, 1.0)
                chance = soc["base_chance"] * time_m * weather_m * cat_m
                if (self.rng() % 10000) / 10000 < chance:
                    out.add(vname)
            available = [v for v in items if v not in out]
            if not available and items:
                out.discard(items[int(self.rng() * len(items)) % len(items)])
            if out:
                self.sold_out[sid] = out

        pool = JOURNEY_TEXT.get(self.weather, JOURNEY_TEXT["晴"])
        self._journey_text = pool[int(self.rng() * len(pool)) % len(pool)]
        self._journey_shown = False

        self.unlocked_skills = []       # 已解锁技能id
        self.inspect_counts = {         # 细看次数统计
            "绿叶": 0, "根茎": 0, "瓜果": 0, "豆类": 0,
            "菌菇": 0, "豆制品": 0, "肉": 0, "鱼": 0, "蛋": 0, "调味": 0,
            "scale": 0,
        }

        # 好感度日衰减——不来就忘一点，但老交情衰减慢
        for sid in list(self.affection.keys()):
            old = self.affection[sid]
            if old > 0:
                decay = 1 if old < 50 else 0.5 if old < 79 else 0.2
                self.affection[sid] = max(0, old - decay)

        # 每日状态roll——每个摊主今天的心情/状态不一样
        self._owner_daily = {}
        self._daily_chat_gain = set()  # 重置每日聊天好感冷却
        self._storyline_effects = {}   # 重置连续剧情当日效果
        for stall in STALLS:
            sid = stall["id"]
            r = (self.rng() % 100) / 100
            if r < 0.50:
                self._owner_daily[sid] = "normal"      # 正常
            elif r < 0.65:
                self._owner_daily[sid] = "good"         # 心情好
            elif r < 0.78:
                self._owner_daily[sid] = "bad"          # 心情差
            elif r < 0.90:
                self._owner_daily[sid] = "distracted"   # 分心了
            else:
                self._owner_daily[sid] = "unwell"       # 不舒服

        # 你的状态不roll——你告诉他才对
        # wife_state 从存档里读，不是替你决定的

        # ── 天灾人祸 ──
        self._today_disaster = None
        self._disaster_price_mod = 1.0
        self._disaster_quality_mod = 0
        self._disaster_bargain_bonus = 0
        for d in MARKET_DISASTERS:
            if self.day < d.get("min_day", 0):
                continue
            # 天气限制
            if d.get("weather") and d["weather"] != self.weather:
                continue
            if (self.rng() % 100) / 100 < d["trigger_chance"]:
                self._today_disaster = d
                fx = d.get("effects", {})
                self._disaster_price_mod = fx.get("price_mod", 1.0)
                self._disaster_quality_mod = fx.get("quality_mod", 0)
                self._disaster_bargain_bonus = fx.get("bargain_bonus", 0)
                # 时间压力
                if fx.get("time_pressure"):
                    self.market_time = max(2, self.market_time - fx["time_pressure"])
                    self.market_time_max = self.market_time
                # 关闭的摊位类别
                closed_cats = fx.get("closed_cats", [])
                if closed_cats:
                    for stall in STALLS:
                        # 用摊位卖的菜的类别匹配，不是用id前缀
                        stall_cats = set(VEGGIES.get(v, {}).get("cat", "") for v in stall.get("sells", []))
                        if stall_cats & set(closed_cats):
                            self.closed_stalls.add(stall["id"])
                # 摊主缺席
                absent_count = fx.get("absent_count", 0)
                if absent_count > 0:
                    open_stalls = [s["id"] for s in STALLS if s["id"] not in self.closed_stalls]
                    for _ in range(min(absent_count, len(open_stalls) - 3)):  # 至少留3家
                        idx = self.rng() % len(open_stalls)
                        self.closed_stalls.add(open_stalls[idx])
                        open_stalls.pop(idx)
                break  # 每天最多一个灾难

        # ── 推进连续剧情 ──
        for vendor in list(self.storyline_state.keys()):
            state = self.storyline_state[vendor]
            state["day"] += 1
            storyline = next((s for s in VENDOR_STORYLINES if s["vendor"] == vendor and s["arc"] == state["arc"]), None)
            if storyline and state["day"] > len(storyline["days"]):
                del self.storyline_state[vendor]

        # ── 节气事件 ──
        # 先清昨天的节气修饰符——_solar_* 用 hasattr 守卫读，若不清，
        # 同进程连开新局时昨天的会残留下一天（跨进程因不存档本会自清，这里补上同进程这条）。
        for _attr in ("_solar_price_mod_all", "_solar_bargain_bonus",
                      "_solar_quality_mod", "_solar_rare_mult",
                      "_solar_price_mod", "_solar_quality_boost"):
            if hasattr(self, _attr):
                delattr(self, _attr)
        self._today_solar_term = self._check_solar_term()
        if self._today_solar_term:
            self._apply_solar_term_effects(self._today_solar_term)

        # ── 神秘时空层 ──
        if self.mystic:
            # 上局结束先清当日标记，再加进度（雨天+2/散市+1）
            self.mystic.end_of_day_clear()
            delta = 1
            if self.weather == "雨":
                delta += 2
            if self.time_of_day == "散市":
                delta += 1
            self.mystic.tick_progress(delta)
            if self.mystic.check_trigger():
                self.mystic.on_day_start()
            self.in_mystic = self.mystic.state["in_mystic"]
            self._mystic_chain_hints = self.mystic.check_mystic_chains()
        else:
            self._mystic_chain_hints = []

        self.save()
        return self._day_header(expired)

    def _day_header(self, expired=None):
        lines = []
        season_day = getattr(self, '_season_day', 1)
        lines.append(f"第{self.day}天 · {self.season}（{season_day}/{DAYS_PER_SEASON}） · {self.weather} · {self.time_of_day}")
        # 季节环境
        season_env = SEASON_AMBIENCE.get(self.season, {})
        env_line = season_env.get(self.weather, season_env.get("晴", ""))
        if env_line:
            lines.append(env_line)
        # 季节倒计时——最后2天提醒
        if getattr(self, '_season_ending', False):
            next_season = SEASONS[(SEASONS.index(self.season) + 1) % 4] if self.season in SEASONS else self.season
            leaving = [name for name, v in VEGGIES.items()
                       if v["season"].get(self.season, "no") == "in"
                       and v["season"].get(next_season, "no") == "no"
                       and not v.get("_secret")]
            if leaving:
                lines.append(f"⏳ {self.season}快过了！{leaving[0]}等下季就没了，要买趁早。")
        # 时段环境——规则隐身
        tod = TIME_OF_DAY.get(self.time_of_day, {})
        tod_desc = tod.get("desc", "")
        if tod_desc:
            lines.append(tod_desc)
        # 神秘时空日提示
        if self.mystic:
            mystic_hint = self.mystic.day_header_hint()
            if mystic_hint:
                lines.append(mystic_hint)
        # 时间循环回退叙事
        if getattr(self, '_time_loop_narrative', None):
            lines.append("")
            lines.append(self._time_loop_narrative)
            self.mystic.consume_time_loop_flag()
        # 隐藏任务线解锁提示
        for h in getattr(self, '_mystic_chain_hints', []) or []:
            lines.append("")
            lines.append(h)
        lines.append(f"菜钱：{self.budget}元")
        # 攒钱罐/结转提示
        carry = getattr(self, '_carry_hint', 0)
        jar_now = self.savings
        if carry > 0 and jar_now > 0:
            lines.append(f"  （昨天剩的一半{carry}元结转，另一半进攒钱罐；罐里现在{jar_now}元，用「取罐」取出）")
        elif carry > 0:
            lines.append(f"  （昨天剩的{carry}元结转过来了）")
        elif jar_now > 0:
            lines.append(f"  （攒钱罐里有{jar_now}元，用「取罐」取出）")
        # 天灾人祸
        if self._today_disaster:
            d = self._today_disaster
            descs = d.get("desc", [])
            if descs:
                lines.append("")
                lines.append(descs[self.rng() % len(descs)])
            tip = d.get("tip", "")
            if tip:
                lines.append(f"⚡ {tip}")
        # 节气
        if self._today_solar_term:
            lines.append("")
            lines.append(f"🌿 {self._today_solar_term['text']}")
        # 你告诉过他的状态——他记着呢
        if self.wife_state:
            lines.append(self.wife_state)
        # 口味记忆——他记得的
        known = self.palate_known_count()
        if known > 0:
            lines.append(f"（记住了{known}个口味偏好）")
        if expired:
            lines.append("")
            lines.append("🗑 冰箱过期——")
            for exp in expired:
                q_str = {"great": "优品", "good": "不错", "ok": "一般", "bad": "不太好"}.get(exp["quality"], "")
                q_note = f"（{q_str}）" if q_str else ""
                lines.append(f"  ✗ {exp['name']}{q_note}，放了{exp['was_days']}天，坏了")
        if self.fridge:
            fridge_parts = []
            for item in self.fridge:
                kd = item.get("keep_days", 3)
                warn = "⚠" if kd <= 1 else ""
                fridge_parts.append(f"{item['name']}{warn}({kd}天)")
            lines.append(f"冰箱：{'、'.join(fridge_parts)}")
        lines.append("")
        lines.append("你站在菜场门口。")
        lines.append("")
        lines.append("📖 " + self._status_bar())
        return "\n".join(lines)

    # ---- 节气系统 ----

    def _check_solar_term(self):
        """用真实日期查今天是否是节气日，返回事件dict或None"""
        now = time.localtime()
        month, day = now.tm_mon, now.tm_mday
        for m, d, name in SOLAR_TERMS:
            if m == month and d == day:
                return SOLAR_TERM_EVENTS.get(name)
        return None

    def _apply_solar_term_effects(self, event):
        """应用节气效果到当天状态"""
        fx = event.get("effect", {})
        # 免费物品
        if "item" in fx:
            item_name = fx["item"]
            quality = fx.get("quality", "ok")
            stall_id = fx.get("stall", "")
            self.basket.append({
                "name": item_name,
                "quality": quality,
                "qty": 1,
                "price": 0,
                "stall": stall_id,
                "owner": STALL_BY_ID.get(stall_id, {}).get("owner", ""),
                "_free": True,
            })
            if hasattr(self, 'encyclopedia'):
                self.encyclopedia["items_bought"].add(item_name)
        # 某类食材品质提升
        if "quality_boost" in fx:
            cat = fx["quality_boost"]
            if not hasattr(self, '_solar_quality_boost'):
                self._solar_quality_boost = {}
            self._solar_quality_boost[cat] = self._solar_quality_boost.get(cat, 0) + 1
        # 特定摊主加好感
        if "affection" in fx:
            for sid, val in fx["affection"].items():
                old = self.affection.get(sid, 0)
                self.affection[sid] = min(100, old + val)
        # 所有认识摊主加好感
        if "affection_all" in fx:
            for sid in list(self.affection.keys()):
                self.affection[sid] = min(100, self.affection[sid] + fx["affection_all"])
        # 特定摊主价格修正
        if "price_mod" in fx and "stall" in fx:
            if not hasattr(self, '_solar_price_mod'):
                self._solar_price_mod = {}
            self._solar_price_mod[fx["stall"]] = fx["price_mod"]
        # 所有摊主价格修正
        if "price_mod_all" in fx:
            self._solar_price_mod_all = fx["price_mod_all"]
        # 砍价奖励
        if "bargain_bonus" in fx:
            self._solar_bargain_bonus = fx["bargain_bonus"]
        # 品质修正
        if "quality_mod" in fx:
            self._solar_quality_mod = fx["quality_mod"]
        # 稀有发现概率倍率
        if "rare_chance" in fx:
            self._solar_rare_mult = fx["rare_chance"]

    # ---- 逛菜场 ----

    def look_stalls(self):
        """看菜场有哪些摊"""
        lines = []
        lines.append("菜场一览：")
        lines.append("")
        if not self._journey_shown:
            lines.append(self._journey_text)
            lines.append("")
            self._journey_shown = True
        for s in STALLS:
            sid = s["id"]
            cat_emoji = self._cat_emoji(s)
            # 当季有几种菜
            available = self._stall_season_items(s)
            count = len(available)
            if hasattr(self, 'closed_stalls') and sid in self.closed_stalls:
                lines.append(f"  ✕ {s['name']} — 今天没出摊")
                continue
            so_count = len(self.sold_out.get(sid, set())) if hasattr(self, 'sold_out') else 0
            sold_out_note = f" 缺{so_count}种" if so_count else ""
            familiar = ""
            vc = self.visit_count.get(s["id"], 0)
            if vc >= 3:
                familiar = " [熟客]"
            elif vc >= 1:
                familiar = " [来过]"
            lines.append(f"  {cat_emoji} {s['name']}［{sid}］（{s['owner']}·{s['personality']}）{familiar} — {count}种{sold_out_note}")

        # 流动奇遇摊位
        for ws in WANDERING_STALLS:
            if (self.rng() % 100) / 100 < ws["appear_chance"]:
                # 时令限定要检查季节
                if "sells" in ws and isinstance(ws["sells"], dict):
                    season_items = ws["sells"].get(self.season, [])
                    if not season_items:
                        continue
                lines.append(f"  🌟 {ws['name']}（{ws['owner']}）— 限时！")

        # 神秘时空：异宾摊出现
        if self.mystic:
            mystic_hint = self.mystic.look_stalls_hint()
            if mystic_hint:
                lines.append(mystic_hint)

        new_secrets = self._check_secret_unlocks()
        for area in new_secrets:
            lines.append("")
            lines.append(f"🔓 {area['unlock_text']}")
            lines.append(f"   新地点解锁：{area['name']}！用「去 {area['id']}」进入。")
        for aid in self.unlocked_secrets:
            area = SECRET_AREAS[aid]
            already_shown = any(a["id"] == aid for a in new_secrets)
            if not already_shown:
                lines.append(f"  🚪 {area['name']}（{area['owner']}）— {len(area['sells'])}种")

        lines.append("")
        lines.append("用「去 摊位id」逛某个摊，如：去 veg_1")
        lines.append("用「去 wander_」逛流动摊")
        lines.append("📖 " + self._status_bar())
        return "\n".join(lines)

    # ---- 连续剧情 ----

    def _check_storyline(self, stall_id):
        """检查当前摊主的连续剧情，返回剧情文本或None"""
        stall = self._find_stall(stall_id)
        if not stall:
            return None
        vendor = stall["owner"]

        # 已有进行中的剧情——显示当天内容
        if vendor in self.storyline_state:
            state = self.storyline_state[vendor]
            storyline = next((s for s in VENDOR_STORYLINES if s["vendor"] == vendor and s["arc"] == state["arc"]), None)
            if storyline:
                day_idx = state["day"] - 1
                if 0 <= day_idx < len(storyline["days"]):
                    day_data = storyline["days"][day_idx]
                    text = day_data["text"]
                    # 应用当天效果
                    effect = day_data.get("effect", {})
                    if effect.get("affection"):
                        self._change_affection(stall_id, effect["affection"])
                    # 非affection效果存为临时标记，买/砍价时读取
                    if effect.get("price_mod") or effect.get("quality_mod") or effect.get("bargain_mod"):
                        if not hasattr(self, '_storyline_effects'):
                            self._storyline_effects = {}
                        self._storyline_effects[stall_id] = {
                            "price_mod": effect.get("price_mod", 1.0),
                            "quality_mod": effect.get("quality_mod", 0),
                            "bargain_mod": effect.get("bargain_mod", 1.0),
                        }
                    return text
            return None

        # 没有进行中的剧情——随机触发新剧情（第一天不触发，概率15%）
        if self.day < 2:
            return None
        if (self.rng() % 100) / 100 >= 0.15:
            return None
        # 找该摊主的剧情
        candidates = [s for s in VENDOR_STORYLINES if s["stall"] == stall_id]
        if not candidates:
            return None
        chosen = candidates[self.rng() % len(candidates)]
        self.storyline_state[vendor] = {"arc": chosen["arc"], "day": 1}
        day_data = chosen["days"][0]
        text = day_data["text"]
        effect = day_data.get("effect", {})
        if effect.get("affection"):
            self._change_affection(stall_id, effect["affection"])
        if effect.get("price_mod") or effect.get("quality_mod") or effect.get("bargain_mod"):
            if not hasattr(self, '_storyline_effects'):
                self._storyline_effects = {}
            self._storyline_effects[stall_id] = {
                "price_mod": effect.get("price_mod", 1.0),
                "quality_mod": effect.get("quality_mod", 0),
                "bargain_mod": effect.get("bargain_mod", 1.0),
            }
        return text

    def visit_stall(self, stall_id):
        """逛某个摊，看有什么菜"""
        if self._market_closed:
            return "⏰ 散场了！摊主都在收，来不及了。赶紧「回家」吧。"
        if stall_id in self.closed_stalls:
            stall = self._find_stall(stall_id)
            owner = stall["owner"] if stall else "摊主"
            return f"今天{owner}没出摊。下次再来吧。"
        # 神秘时空：异宾摊走 mystic 层
        if stall_id in MYSTIC_STALL_IDS and self.mystic:
            return self.mystic.visit_mystic_stall(stall_id)
        if stall_id in SECRET_AREAS:
            return self._visit_secret_area(stall_id)
        stall = self._find_stall(stall_id)
        if not stall:
            # 检查是不是流动摊
            stall = self._find_wandering_stall(stall_id)
            if not stall:
                return f"没有这个摊。用「菜场」看所有摊。"

        self.current_stall = stall_id  # 记住当前摊

        # ── 消耗时间 ──
        self._tick_time(1)

        # ── 好感里程碑 ──
        milestone_lines = []
        for ms in self._check_milestones(stall_id):
            milestone_lines.append(f"🔓 {ms['trigger_text']}")
            reward = ms.get("reward", {})
            if "recipe" in reward:
                rname = reward["recipe"]
                milestone_lines.append(f"   获得隐藏菜谱：{rname}！")

        # ── 限时奇遇 ──
        encounter_lines = []
        basket_before = len(self.basket)
        for te in self._check_timed_encounters():
            encounter_lines.append(f"✨ {te['text']}")
            reward = te.get("reward", {})
            if reward.get("rare_boost"):
                encounter_lines.append("   （今天更容易遇到稀有好东西了。）")
            if reward.get("random_quality_item") or reward.get("free_quality_item"):
                # 取这次奇遇新增的物品（不是basket[-1]，可能被后续奇遇覆盖）
                new_items = self.basket[basket_before:]
                basket_before = len(self.basket)
                if new_items:
                    encounter_lines.append(f"   获得了：{new_items[-1]['name']}")

        # 增量输出——同摊二次进入只给变化
        is_revisit = (self._last_stall == stall_id)
        self._last_stall = stall_id

        # 更新来访
        self.visit_count[stall_id] = self.visit_count.get(stall_id, 0) + 1
        vc = self.visit_count[stall_id]
        is_regular = vc >= 3
        regular_tier = self._get_regular_tier(stall_id)

        # 增量模式：同摊二次进入
        if is_revisit and not COMPACT_MODE:
            # 还是预缓存（可能有新事件影响）
            available = self._season_stall_items.get(stall_id, self._stall_season_items(stall))
            self._stall_item_cache = {}
            for vname in available:
                v = VEGGIES[vname]
                self._stall_item_cache[vname] = {
                    "price": self._calc_price(vname, v),
                    "quality": self._calc_quality(vname, v),
                }
            money_left = round(self.budget - self.spent, 1)
            revisits = [
                f"又转回了{stall['name']}。{stall['owner']}看见你：哟，又来了？",
                f"溜达一圈又回到{stall['name']}。{stall['owner']}冲你点了点头。",
                f"{stall['name']}还是那几样，{stall['owner']}正给菜喷水，见你回来笑了笑。",
            ]
            result = f"{revisits[self.rng() % len(revisits)]}"
            # 里程碑和奇遇在revisit时也要显示（副作用已在上面生效）
            if milestone_lines:
                result += "\n" + "\n".join(milestone_lines)
            if encounter_lines:
                result += "\n" + "\n".join(encounter_lines)
            result += f"\n💰 剩余：{money_left}元\n📖 " + self._status_bar()
            return result

        lines = []

        # 好感度——后续多处使用
        affection = self._get_affection(stall_id)
        stage_name, stage_key = get_affection_stage(affection)

        # 每日状态描写——好感度够了才看得出来
        daily_state = getattr(self, '_owner_daily', {}).get(stall_id, "normal")
        if affection >= 10 and daily_state != "normal":
            traits = OWNER_TRAITS.get(stall_id, {})
            state_key = f"daily_{daily_state}"
            state_text = traits.get(state_key, "")
            if state_text:
                lines.append(state_text)

        # 随机事件
        event_text = self._maybe_market_event()
        if event_text:
            lines.append(event_text)
            lines.append("")
        # 摊主招呼——好感度驱动，越熟越暖
        if stage_key == "close":
            greets = [
                f"{stall['owner']}看见你就笑了：你来了！今天有好东西，就等你呢。",
                f"{stall['owner']}：嘿！来了啊。我给你留了点好的。",
            ]
            lines.append(greets[self.rng() % len(greets)])
        elif stage_key == "friend":
            greets = [
                f"{stall['owner']}：来了来了，今天要点啥？",
                f"{stall['owner']}冲你点了点头：又来了？",
            ]
            lines.append(greets[self.rng() % len(greets)])
        elif stage_key == "familiar":
            lines.append(f"{stall['owner']}：来了？看看吧。")
        else:
            lines.append(f"{stall['owner']}：{stall.get('catchphrase', '看看吧。')}")

        # 跨天记忆——逛摊时摊主可能提一句以前的事（概率低，不像聊天那么自然）
        if affection >= 20:
            recalls = self._get_memory_recall(stall_id)
            if recalls and (self.rng() % 100) / 100 < 0.3:
                lines.append("")
                lines.append(recalls[0])

        # 故事碎片——碎碎地漏，像真实偶遇
        story_text = self._maybe_story_beat(stall_id)
        if story_text:
            lines.append("")
            lines.append(story_text)

        # 连续剧情——跨天的摊主故事弧
        storyline_text = self._check_storyline(stall_id)
        if storyline_text:
            lines.append("")
            lines.append(storyline_text)

        # 摊主间互动——你看到了摊主之间发生的事
        interaction = self._maybe_stall_interaction(stall_id)
        if interaction:
            lines.append("")
            lines.append(interaction)

        # 选择链——带选择的事件
        chain_steps = self._check_choice_chains(stall_id)
        self._pending_chain_step = None  # 清除上次pending
        for step in chain_steps:
            chain = None
            for cid, c in CHOICE_CHAINS.items():
                if any(s["id"] == step["id"] for s in c["steps"]):
                    chain = c
                    break
            step['_chain_title'] = chain["title"] if chain else "事件"
            lines.append("")
            lines.append(self._format_choice_chain(step))
            # 保存有选择的步骤，等玩家回应
            if step.get("choices"):
                self._pending_chain_step = step

        # 线索碎片——偶尔发现
        clues = self._maybe_find_clue(stall_id, "visit")
        for clue in clues:
            if clue.get("is_combo"):
                lines.append("")
                lines.append(f"🔮 线索拼合——{clue['name']}")
                lines.append(clue["desc"])
            else:
                lines.append("")
                lines.append(f"🔎 你注意到——{clue['name']}")
                lines.append(clue["desc"])

        # 性格怪癖——偶尔露一下（紧凑模式跳过）
        traits = OWNER_TRAITS.get(stall_id, {})
        quirks = traits.get("quirks", [])
        if not COMPACT_MODE and quirks and (self.rng() % 100) / 100 < 0.12:
            lines.append(quirks[self.rng() % len(quirks)])

        # 猫
        if stall.get("has_cat"):
            cat_msg = CAT_MESSAGES[self.rng() % len(CAT_MESSAGES)]
            lines.append(f"🐟 {cat_msg}")

        # 摊主故事——随熟客度展开
        stories = STALL_STORIES.get(stall_id, [])
        for threshold, story in stories:
            if vc >= threshold and (vc == threshold or (self.rng() % 100) / 100 < 0.3):
                lines.append(f"💬 {story}")
                break  # 每次最多一条故事

        # 路人假情报——生客偶尔碰到（紧凑模式跳过）
        if not COMPACT_MODE and not is_regular and (self.rng() % 100) / 100 < 0.15:
            intel = FALSE_INTEL[self.rng() % len(FALSE_INTEL)]
            lines.append(f"👥 {intel['says']}")

        # 摊主反话——算计型/实在型偶尔说（紧凑模式跳过）
        personality = stall.get("personality", "实在")
        reverse_talks = OWNER_REVERSE_TALK.get(personality, [])
        if not COMPACT_MODE and reverse_talks and (self.rng() % 100) / 100 < 0.10:
            rt = reverse_talks[self.rng() % len(reverse_talks)]
            lines.append(f"{stall['owner']}：{rt['says']}")

        # 捆绑销售诱惑——算计型摊主偶尔推销
        self._current_bundle = None
        if personality == "算计" and (self.rng() % 100) / 100 < 0.20:
            for bt in BUNDLE_TRICKS:
                if bt["buy"] in stall.get("sells", []):
                    lines.append(f"{stall['owner']}：{bt['says']}")
                    self._current_bundle = bt
                    break

        # 比价误导——偶尔摊主主动比价
        if not is_regular and (self.rng() % 100) / 100 < 0.12:
            mc = MISLEADING_COMPARE[self.rng() % len(MISLEADING_COMPARE)]
            lines.append(f"{stall['owner']}：{mc['says']}")

        # 分区环境描写——紧凑模式跳过
        if not COMPACT_MODE:
            sells_list = stall["sells"] if isinstance(stall.get("sells"), list) else []
            stall_cat = VEGGIES.get(sells_list[0], {}).get("cat", "") if sells_list else ""
            zone_descs = ZONE_AMBIENCE.get(stall_cat, [])
            if zone_descs:
                lines.append(zone_descs[self.rng() % len(zone_descs)])

        # 行话——摊主可能说一句带潜台词的话（紧凑模式跳过）
        if not COMPACT_MODE and not is_regular and (self.rng() % 100) / 100 < 0.25:
            jargon = STALL_JARGON[self.rng() % len(STALL_JARGON)]
            lines.append(f"{stall['owner']}：{jargon['says']}")

        # 分量坑——买菜时可能触发（市场检查期间不触发）
        self._current_weight_trick = None
        if not self.no_weight_trick and not is_regular and (self.rng() % 100) / 100 < 0.15:
            self._current_weight_trick = WEIGHT_TRICKS[self.rng() % len(WEIGHT_TRICKS)]

        lines.append("")
        lines.append(f"─── {stall['name']} ───")
        if milestone_lines:
            for ml in milestone_lines:
                lines.append(ml)
            lines.append("")
        if encounter_lines:
            for el in encounter_lines:
                lines.append(el)
            lines.append("")
        tw = self._time_warning()
        if tw:
            lines.append(tw)

        # 展示当季可买的菜——一次性预缓存品质/价格
        available = self._season_stall_items.get(stall_id, self._stall_season_items(stall))
        self._stall_item_cache = {}
        for vname in available:
            v = VEGGIES[vname]
            self._stall_item_cache[vname] = {
                "price": self._calc_price(vname, v),
                "quality": self._calc_quality(vname, v),
            }
        stall_sold_out = self.sold_out.get(stall_id, set()) if hasattr(self, 'sold_out') else set()
        if not available:
            lines.append("今天没什么当季的菜。")
        else:
            for vname in available:
                if vname in stall_sold_out:
                    continue
                v = VEGGIES[vname]
                cached = self._stall_item_cache[vname]
                price = cached["price"]
                # 展示价格含天气加价，和实际购买一致
                wpmod = getattr(self, '_weather_price_mod', 1.0)
                if wpmod > 1.0:
                    price = round(price * wpmod, 1)
                quality = cached["quality"]

                if COMPACT_MODE:
                    # 紧凑模式：菜名+价格+品质符号+一词提示
                    q_map = {"great": "★鲜", "good": "○好", "ok": "△行", "bad": "✗差", "trap": "?疑"}
                    q_icon = q_map.get(quality, "△行")
                    lines.append(f"  {vname} {price}元/{v['unit']} {q_icon}")
                else:
                    # 沉浸模式：完整品质描述
                    hints = v["fresh_hint"]
                    if vname in QUALITY_DESC and quality in ("great", "good", "ok", "bad", "trap"):
                        skill_reveals_trap = False
                        for sid in self.unlocked_skills:
                            sk = SKILL_TREE.get(sid, {})
                            eff = sk.get("effect", {})
                            if eff.get("cat") == v.get("cat") and eff.get("trap_reveal"):
                                skill_reveals_trap = True
                                break
                        # 识货25+也能看出trap
                        if not skill_reveals_trap and self.player_skills.get("识货", 0) >= 25:
                            skill_reveals_trap = True
                        if quality == "trap" and not skill_reveals_trap:
                            hint = QUALITY_DESC[vname][0]  # 优品描述（迷惑）
                        else:
                            qidx = {"great": 0, "good": 1, "ok": 2, "bad": 3, "trap": 4}[quality]
                            hint = QUALITY_DESC[vname][qidx]
                    else:
                        hint = hints.get(quality, hints.get("good", "一般"))
                    # 熟客能看到更多提示
                    if is_regular and quality == "bad":
                        hint += f" ← {stall['owner']}悄悄说：这批不太好，你换那个。"
                    elif is_regular and quality == "trap" and vname in TRAP_TRUTH:
                        hint += f" ← {stall['owner']}犹豫了一下：这批……你回家记得仔细看看。"
                    # 识货50+自动显示品质等级
                    q_tag = ""
                    if self.player_skills.get("识货", 0) >= 50:
                        q_labels = {"great": "【优】", "good": "【良】", "ok": "", "bad": "【差】", "trap": "【⚠坑】"}
                        q_tag = q_labels.get(quality, "")
                    # 季节快过标签
                    season_tag = ""
                    if getattr(self, '_season_ending', False):
                        next_season = SEASONS[(SEASONS.index(self.season) + 1) % 4] if self.season in SEASONS else self.season
                        if v["season"].get(next_season, "no") == "no" and v["season"].get(self.season, "no") == "in":
                            season_tag = " ⏳"
                    lines.append(f"  {vname}{season_tag} · {price}元/{v['unit']} · {hint}{q_tag}")
                    # 想着你——记得她的口味，看到菜会想起她
                    thought = self._palate_thought(vname)
                    if thought:
                        lines.append(f"    ↳ {thought}")
                    state_warn = self._palate_state_avoid(vname)
                    if state_warn:
                        lines.append(f"    ↳ {state_warn}")

        money_left = round(self.budget - self.spent, 1)
        lines.append("")
        lines.append(f"💰 剩余：{money_left}元")
        if stall_sold_out:
            lines.append(f"✕ 卖完了：{'、'.join(stall_sold_out)}")
        rare_line = self._maybe_rare_find(stall)
        if rare_line:
            lines.append("")
            lines.append(rare_line)
        help_line = self._maybe_help_event(stall)
        if help_line:
            lines.append("")
            lines.append(help_line)

        # 阶段2：携带磕碰——篮子里有易碎品时，逛新摊可能碰坏
        if self.basket:
            for item in self.basket:
                frag = FRAGILE_LEVEL.get(item["name"], 1)
                if frag >= 3 and (self.rng() % 100) / 100 < 0.15:
                    # 极脆品磕碰（同一物品只降一次）
                    if not item.get("_bumped"):
                        old_q = item["quality"]
                        item["quality"] = "ok" if old_q in ("great", "good") else "bad"
                        item["_bumped"] = True
                        lines.append(f"⚠ 路过挤了一下，{item['name']}碰了——角上碎了一点。")
                elif frag >= 2 and (self.rng() % 100) / 100 < 0.05:
                    if item["quality"] == "great" and not item.get("_bumped"):
                        item["quality"] = "good"
                        item["_bumped"] = True
                        lines.append(f"（{item['name']}蹭了一下，问题不大。）")

        lines.append("")
        if not COMPACT_MODE:
            lines.append("「买 菜名 [数量]」购买，「砍价 菜名 [话术]」砍价（话术影响成功率）")
        lines.append("📖 " + self._status_bar())
        journey_line = ""
        if not getattr(self, '_journey_shown', True) and hasattr(self, '_journey_text'):
            journey_line = self._journey_text + "\n"
            self._journey_shown = True
        result = journey_line + "\n".join(lines) if journey_line else "\n".join(lines)
        return result

    # ---- L2 分区导航 ----

    def visit_zone(self, zone_name):
        """逛某个分区——L2信息层，品质水位+价格梯度+摊位列表"""
        if self._market_closed:
            return "⏰ 菜场收摊了。「回家」吧。"
        self._tick_time(1)
        zone = ZONE_NAV.get(zone_name)
        if not zone:
            # 尝试模糊匹配
            for zn in ZONE_NAV:
                if zone_name in zn or zn in zone_name:
                    zone = ZONE_NAV[zn]
                    zone_name = zn
                    break
        if not zone:
            return f"没有这个分区。试试：{', '.join(ZONE_NAV.keys())}"

        self.current_zone = zone_name

        lines = []
        lines.append(f"─── {zone_name} ───")

        # 分区环境描写
        envs = zone["env"]
        lines.append(envs[self.rng() % len(envs)])
        lines.append("")

        # 分区情报提示——熟客才看得到后半句
        quality_hint = zone.get("quality_hint", "")
        price_hint = zone.get("price_hint", "")
        lines.append(quality_hint)
        lines.append(price_hint)
        lines.append("")

        # 分区里的摊位
        lines.append("摊位：")
        for sid in zone["stalls"]:
            s = self._find_stall(sid)
            if s:
                vc = self.visit_count.get(sid, 0)
                familiar = ""
                if vc >= 3:
                    familiar = " [老主顾]"
                elif vc >= 1:
                    familiar = " [来过]"
                available = self._season_stall_items.get(sid, self._stall_season_items(s))
                lines.append(f"  {s['name']}（{s['owner']}·{s['personality']}）{familiar} — {len(available)}种")

        lines.append("")
        lines.append("用「去 摊位id」逛某个摊。")
        lines.append("📖 " + self._status_bar())
        return "\n".join(lines)

    # ---- 买 ----

    def buy(self, item_name, qty=1, stall_id=None):
        """买某样菜"""
        if self._market_closed:
            return "⏰ 菜场已经收摊了，买不了了。「回家」吧。"
        # qty格式化：1.0→1, 0.5→0.5
        def _fq(q):
            return str(int(q)) if q == int(q) else str(q)
        # 稀有食材
        if hasattr(self, '_pending_rare') and self._pending_rare and self._pending_rare["name"] == item_name:
            return self._buy_rare()
        if item_name not in VEGGIES:
            return f"没有「{item_name}」这种菜。"

        # 携带上限——默认5样，买了袋子+3
        max_carry = getattr(self, '_max_carry', 5)
        if len(self.basket) >= max_carry:
            return f"手上拿不下了（{len(self.basket)}样）。先「回家」放下，或者花1元买个塑料袋加3格。"

        v = VEGGIES[item_name]

        # 检查当季有没有
        season_status = v["season"].get(self.season, "no")
        if season_status == "no":
            return f"「{item_name}」这个季节没有。"

        # 缺货检查
        check_stall = stall_id or self.current_stall
        if check_stall and hasattr(self, 'sold_out'):
            if item_name in self.sold_out.get(check_stall, set()):
                return f"「{item_name}」卖完了。来晚了。"

        # 找卖这个菜的摊
        if stall_id:
            stall = self._find_stall(stall_id)
        elif self.current_stall:
            stall = self._find_stall(self.current_stall)
            # 当前摊不卖这个——不能凭空从别的摊买，得先去
            if stall and item_name not in stall.get("sells", []):
                other = self._find_stall_selling(item_name)
                if other:
                    return f"这个摊不卖{item_name}。去{other['name']}（{other['id']}）看看？"
                return f"今天没看到卖{item_name}的摊。"
        else:
            stall = self._find_stall_selling(item_name)
        if not stall:
            return f"今天没有摊子卖「{item_name}」。"

        # 检查是否已经主动买过（赠送的不挡）
        if any(b["name"] == item_name and not b.get("_free") for b in self.basket):
            return f"「{item_name}」已经买了，在篮子里。"

        # 优先从缓存取，没有则现场算
        cached = self._stall_item_cache.get(item_name)
        if cached:
            base_price = cached["price"]
            quality = cached["quality"]
        else:
            base_price = self._calc_price(item_name, v)
            quality = self._calc_quality(item_name, v)
        price = base_price * qty
        wpmod = getattr(self, '_weather_price_mod', 1.0)
        if wpmod > 1.0:
            price = round(price * wpmod, 1)
        money_left = round(self.budget - self.spent, 1)

        # 熟客价——3级便宜10%
        regular_tier = self._get_regular_tier(stall["id"])
        if regular_tier >= 3:
            price = round(price * 0.9, 1)

        # 4级=赊账——预算不够也能买
        can_owe = regular_tier >= 3  # 3级熟人=赊账（门槛从4级降到3级）

        if price > money_left and not can_owe:
            return f"钱不够。{item_name}{_fq(qty)}{v['unit']}要{price}元，你只剩{money_left}元。"

        # 赊账提醒——钱不够但熟客可以赊
        if price > money_left and can_owe:
            pass  # 下面买了之后再提醒

        # 各种坑的费用——基于原始price算，避免复利叠加
        base_price = price  # 保存原始价格，所有trick基于此计算
        weight_extra = 0
        if regular_tier < 4 and "scale_sense" not in self.unlocked_skills:
            if hasattr(self, '_current_weight_trick') and self._current_weight_trick:
                trick = self._current_weight_trick
                weight_extra = round(base_price * trick["extra_cost_pct"], 1)
                self._current_weight_trick = None  # 只触发一次
        else:
            self._current_weight_trick = None

        # 单位陷阱——基于base_price算
        unit_extra = 0
        unit_trick_hit = None
        for ut in UNIT_TRICKS:
            if ut["item"] == item_name and regular_tier < 1 and (self.rng() % 100) / 100 < 0.2:
                unit_extra = round(base_price * (ut["multiplier"] - 1), 1)
                unit_trick_hit = ut
                break

        # 总价 = 原价 + 各种额外费用
        price = base_price + weight_extra + unit_extra

        self.spent = round(self.spent + price, 1)
        self.basket.append({
            "name": item_name,
            "quality": quality,
            "qty": qty,
            "price": round(price, 1),
            "stall": stall["id"],
            "owner": stall["owner"],
        })
        self.encyclopedia["items_bought"].add(item_name)

        # 赊账提醒
        owe_hint = ""
        if self.budget - self.spent < 0:
            owing = round(self.spent - self.budget, 1)
            owe_hint = f"⚠ 超预算了，欠{owing}元。"
            # 神秘时空：赊账计数（异界收账人任务线用）
            if self.mystic and can_owe:
                self.mystic.state["unpaid_count"] = self.mystic.state.get("unpaid_count", 0) + 1
        # 统计——买好菜/坏菜
        if quality in ("great", "good"):
            self.stats["good_buy_streak"] += 1
            self.stats["bad_buy_streak"] = 0
        elif quality in ("bad", "trap"):
            self.stats["bad_buy_streak"] += 1
            self.stats["good_buy_streak"] = 0
        else:
            self.stats["bad_buy_streak"] = 0

        # 摊主反应
        owner_line = self._owner_buy_reaction(stall, item_name, is_regular=self.visit_count.get(stall["id"], 0) >= 3)

        lines = []
        lines.append(f"买了 {item_name} {_fq(qty)}{v['unit']}，{price}元。")
        if weight_extra > 0:
            lines.append(f"（{trick['hint']}，比预期多花了{weight_extra}元。）")
        if unit_extra > 0:
            lines.append(f"⚠ {unit_trick_hit['hint']}。实际{price}元。")

        # 出成率提示——低出成率的菜提醒一下
        yield_pct = YIELD_PCT.get(item_name, 100)
        if yield_pct < 60:
            lines.append(f"（{item_name}出成率{yield_pct}%，去了废料能用的不多。）")

        # 阶段1：毛重损耗——带泥/带水/带壳/厚包装
        wt = WEIGHT_TRICK_TYPE.get(item_name)
        if wt and regular_tier < 1:
            # 算计型摊主概率更高
            personality = stall.get("personality", "实在")
            trick_chance = 0.4 if personality == "算计" else 0.15
            if (self.rng() % 100) / 100 < trick_chance:
                extra_pct = wt["extra_pct"]
                extra_cost = round(price * extra_pct / 100, 1)
                self.spent = round(self.spent + extra_cost, 1)
                self.basket[-1]["price"] = price + extra_cost
                self.basket[-1]["weight_trick_type"] = wt["type"]
                self.basket[-1]["weight_trick_extra"] = extra_pct
                lines.append(f"（{wt['hint']}，约多花了{extra_cost}元。）")
                # 熟客2级以上会提醒
                regular_tier = self._get_regular_tier(stall["id"])
                if regular_tier >= 2:
                    lines.append(f"  ← {stall['owner']}犹豫了下：要不我帮你去去{wt['type']}再称？")

        lines.append(f"{stall['owner']}：{owner_line}")

        # 捆绑销售——买了对应菜时触发
        if hasattr(self, '_current_bundle') and self._current_bundle:
            bt = self._current_bundle
            if bt["buy"] == item_name and qty >= bt["qty"]:
                free_name = bt["free"]
                if free_name not in [b["name"] for b in self.basket]:
                    self.basket.append({"name": free_name, "quality": bt["free_quality"],
                                        "qty": 1, "price": 0, "stall": stall["id"], "owner": stall["owner"], "_free": True})
                    lines.append(f"{stall['owner']}：{bt['says']} → 送了{free_name}！")
                    if bt["free_quality"] in ("bad", "trap"):
                        lines.append(f"（{bt['catch']}）")
            self._current_bundle = None

        # 熟客送葱
        if self.visit_count.get(stall["id"], 0) >= 3 and "大葱" not in [b["name"] for b in self.basket]:
            if self.rng() % 3 == 0:
                lines.append(f"{stall['owner']}：给你搭根葱！")
                self.basket.append({"name": "大葱", "quality": "good", "qty": 1, "price": 0, "stall": stall["id"], "owner": stall["owner"], "_free": True})

        # 好感度——买东西涨
        profile = NPC_PROFILES.get(stall["id"])
        if profile:
            gain = profile["affection_gain"].get("buy", 1)
            # 雨天来的客人，摊主更感激
            if self.weather == "雨":
                gain += profile["affection_gain"].get("rain_visit", 0)
            stage_msg = self._change_affection(stall["id"], gain)
            if stage_msg:
                lines.append(stage_msg)
        # 声望——买东西=熟客+大方
        self._mod_reputation("regular", 1)
        self._mod_reputation("generous", 1)

        # 识货技能——每次买东西涨
        skill_msg = self._grow_skill("识货", PLAYER_SKILLS["识货"]["grow_buy"])

        # 细看计数——买东西也算接触过这类菜
        cat = v.get("cat", "")
        if cat in self.inspect_counts:
            self.inspect_counts[cat] = self.inspect_counts.get(cat, 0) + 1
        # 检查技能解锁
        new_skill = self._check_skill_unlock()
        if new_skill:
            lines.append(f"🎯 解锁技能：{new_skill}")

        # 跨天记忆——买东西
        if price >= self.budget * 0.3:
            self._add_owner_memory(stall["id"], "bought_expensive", item_name)
        if self.weather == "雨":
            self._add_owner_memory(stall["id"], "rain_visit")

        # 赊账提醒
        if owe_hint:
            lines.append(owe_hint)

        # 识货升级提示
        if skill_msg:
            lines.append(skill_msg)

        lines.append("📖 " + self._status_bar())
        return "\n".join(lines)

    # ---- 砍价 ----

    def bargain(self, item_name, stall_id=None, tactic=None):
        """砍价——支持自由话术"""
        if self._market_closed:
            return "⏰ 菜场收摊了，砍不了了。「回家」吧。"
        if item_name not in VEGGIES:
            return f"没有「{item_name}」这种菜。"

        v = VEGGIES[item_name]
        season_status = v["season"].get(self.season, "no")
        if season_status == "no":
            return f"「{item_name}」这个季节没有。"

        if any(b["name"] == item_name for b in self.basket):
            return f"你已经买了「{item_name}」，不用再砍了。"

        if stall_id:
            stall = self._find_stall(stall_id)
        elif self.current_stall:
            stall = self._find_stall(self.current_stall)
            if stall and item_name not in stall.get("sells", []):
                stall = self._find_stall_selling(item_name)
        else:
            stall = self._find_stall_selling(item_name)
        if not stall:
            return f"今天没有摊子卖「{item_name}」。"

        cached = self._stall_item_cache.get(item_name)
        if cached:
            price = cached["price"]
        else:
            price = self._calc_price(item_name, v)
        personality = stall.get("personality", "实在")
        is_regular = self.visit_count.get(stall.get("id", ""), 0) >= 3

        # 砍价成功率
        base_chance = 0.4
        if is_regular:
            base_chance += 0.25
        if self.weather == "雨":
            base_chance -= 0.15
        # 性格修正
        p_mod = {"爽快": 0.15, "实在": 0, "算计": -0.05, "话唠": 0.05, "死硬": -0.2}
        base_chance += p_mod.get(personality, 0)

        # 时段修正——散市好砍
        tod = TIME_OF_DAY.get(self.time_of_day, {})
        base_chance += tod.get("bargain_mod", 0)

        # 每日状态修正——心情好容易砍，心情差难砍
        daily_state = getattr(self, '_owner_daily', {}).get(stall.get("id", ""), "normal")
        mood_mod = {"good": 0.15, "bad": -0.20, "distracted": 0.10, "unwell": -0.10, "normal": 0}
        base_chance += mood_mod.get(daily_state, 0)

        # L4筹码——细看发现瑕疵，砍价更容易
        inspected = self.inspected_items.get(item_name)
        if inspected and inspected.get("found_flaw"):
            base_chance += 0.25  # 有实锤证据，大幅加成

        # L5邻摊冲突——当前摊主心情差，砍价难
        if getattr(self, '_neighbor_conflict', False):
            base_chance -= 0.15

        # 摊主关系网影响——常买A摊，B摊给脸色
        stall_id = stall.get("id", "")
        for rel in STALL_RELATIONS:
            if rel["a"] == stall_id or rel["b"] == stall_id:
                other_id = rel["b"] if rel["a"] == stall_id else rel["a"]
                other_visits = self.visit_count.get(other_id, 0)
                if rel["relation"] == "不对付" and other_visits >= 3:
                    base_chance -= 0.15  # 常买对家，这家不好砍
                elif rel["relation"] == "竞争" and other_visits >= 2:
                    base_chance += 0.10  # 竞争关系，更愿意让价抢客
                elif rel["relation"] in ("熟人", "亲戚", "邻居"):
                    # 提熟人名字加分
                    if tactic and any(other_id.split("_")[0] in tactic for _ in [1]):
                        base_chance += 0.08

        # 跨天记忆影响砍价——帮了对头的人，这家更难砍；帮了朋友，这家好说话
        if hasattr(self, 'owner_memory'):
            for mem in self.owner_memory.get(stall_id, []):
                if not mem["type"].startswith("cross_"):
                    continue
                relation = mem.get("relation", "")
                days_ago = self.day - mem.get("day", self.day)
                if days_ago > 5:
                    continue
                decay = max(0.3, 1.0 - days_ago * 0.14)
                if relation in ("不对付",):
                    base_chance -= 0.10 * decay  # 你帮了她的对头，不想给你便宜
                elif relation in ("熟人", "亲戚", "邻居"):
                    base_chance += 0.05 * decay  # 你帮了她的朋友，给你面子

        # 天灾人祸——砍价修正
        if hasattr(self, '_disaster_bargain_bonus') and self._disaster_bargain_bonus:
            base_chance += self._disaster_bargain_bonus

        # 连续剧情——当日砍价修正
        if hasattr(self, '_storyline_effects') and stall_id in self._storyline_effects:
            sl_bm = self._storyline_effects[stall_id].get("bargain_mod", 1.0)
            if sl_bm < 1.0:
                base_chance += (1.0 - sl_bm) * 0.5  # 0.9 → +0.05
            elif sl_bm > 1.0:
                base_chance -= (sl_bm - 1.0) * 0.5  # 1.2 → -0.10

        # 节气——砍价修正
        if hasattr(self, '_solar_bargain_bonus'):
            base_chance += self._solar_bargain_bonus

        # 策略修正——AI的话术影响成功率（只取最强匹配的一个策略）
        if tactic:
            for strat_id, strat in BARGAIN_STRATEGIES.items():
                for kw in strat["keywords"]:
                    if kw in tactic:
                        base_chance += strat["success_bonus"]
                        # 算计型特别吃"装走"这套
                        if strat_id == "装走" and personality == "算计":
                            base_chance += 0.15
                        # 死硬型不吃装走
                        if strat_id == "装走" and personality == "死硬":
                            base_chance -= 0.10
                        break
                else:
                    continue
                break  # 匹配到一个策略就停，不叠加

        # 砍价太离谱直接翻车
        if tactic and any(w in tactic for w in ["白送", "免费", "一分钱", "一毛"]):
            backfire = BARGAIN_BACKFIRE[self.rng() % len(BARGAIN_BACKFIRE)]
            return f"{stall.get('owner', '摊主')}：{backfire}"

        roll = (self.rng() % 100) / 100

        lines = []
        # 砍价耗时间
        self._tick_time(1)
        if roll < base_chance:
            # 砍价成功
            discount = round(price * (0.1 + (self.rng() % 25) / 100), 1)
            new_price = round(price - discount, 1)
            if new_price < 0.5:
                new_price = max(0.5, round(price * 0.8, 1))

            pool = BARGAIN_LINES[personality]["accept"]
            line = pool[self.rng() % len(pool)]

            quality = cached["quality"] if cached else self._calc_quality(item_name, v)
            # 砍太狠可能给差的
            if discount > price * 0.3 and quality in ("great", "good"):
                quality = "trap"  # 表面看不出，实际差

            money_left = round(self.budget - self.spent, 1)
            if new_price > money_left:
                lines.append(f"{stall['owner']}：{line}（{new_price}元）——但你钱不够。")
            else:
                self.spent = round(self.spent + new_price, 1)
                self.basket.append({
                    "name": item_name,
                    "quality": quality,
                    "qty": 1,
                    "price": round(new_price, 1),
                    "stall": stall["id"],
                    "owner": stall["owner"],
                })
                lines.append(f"砍价成功！{item_name} {new_price}元（原价{price}元）。")
                lines.append(f"{stall['owner']}：{line}")
                # 统计
                self.stats["bargain_streak"] += 1
                self.stats["bargain_fail_streak"] = 0
                new_ach = self._check_achievements()
                if new_ach:
                    lines.append(f"🏆 解锁成就：{new_ach}")
                # 好感度——砍价成功降一点
                profile = NPC_PROFILES.get(stall["id"])
                if profile:
                    loss = profile["affection_gain"].get("bargain", -1)
                    stage_msg = self._change_affection(stall["id"], loss)
                    if stage_msg:
                        lines.append(stage_msg)
                # 声望——砍价成功=精明
                self._mod_reputation("generous", -1)
                # 记忆——砍价狠
                self._add_owner_memory(stall["id"], "bought_cheap", item_name)
        else:
            # 砍价失败
            pool = BARGAIN_LINES[personality]["reject"]
            line = pool[self.rng() % len(pool)]
            lines.append(f"{stall['owner']}：{line}")
            lines.append(f"{item_name}还是{price}元。")
            # 统计
            self.stats["bargain_fail_streak"] += 1
            self.stats["bargain_streak"] = 0
            new_ach = self._check_achievements()
            if new_ach:
                lines.append(f"🏆 解锁成就：{new_ach}")

        lines.append("📖 " + self._status_bar())
        return "\n".join(lines)

    # ---- 厨房 ----

    def go_home(self):
        """回家做饭"""
        # 已经在厨房——不覆盖kitchen_state
        if self.kitchen_state is not None:
            return "已经在厨房了。想做什么菜？「做 菜名」开始。"
        if not self.basket and not self.fridge:
            if self.weather == "雨":
                return "淋着雨走回家，两手空空。冰箱也是空的。今天没法做饭。"
            elif self.season == "冬":
                return "冻着手走回家，什么都没买。冰箱也是空的。今天没法做饭。"
            else:
                return "你两手空空回家了。冰箱也是空的。今天没法做饭。"

        lines = []
        # ── 回家的路 ──
        carry = len(self.basket)
        if self.weather == "雨":
            if carry >= 4:
                lines.append("撑着伞，两只手拎满了菜，袋子勒得手指发白。雨顺着伞骨往下淌，裤脚全湿了。走快点。")
            else:
                lines.append("一手撑伞一手拎菜，雨斜着飘，鞋踩进两个水坑。到了楼道口甩了甩伞上的水。")
        elif self.season == "冬" and self.weather != "晴":
            lines.append("冷风往领口里钻，拎着的菜越来越沉。进了楼道才觉得手缓过来。")
        elif self.season == "夏" and self.weather == "晴":
            if carry >= 4:
                lines.append("太阳晒得人发晕，袋子越来越重。菜叶开始打蔫，得赶紧回去。")
            else:
                lines.append("热得冒汗，塑料袋贴着手指。进门第一件事——把菜放灶台上，开窗。")
        else:
            if carry >= 4:
                lines.append("两只手都拎满了，袋子勒得发红。上楼的时候换了一次手。")
            elif carry >= 2:
                lines.append("拎着菜走回家，袋子晃来晃去。到了门口换了只手掏钥匙。")
            else:
                lines.append("拎着一袋子菜走回家。")
        lines.append("")

        # ── 进厨房 ──
        kitchen_enter = {
            "晴": "灶台在窗边，光照进来，案板上有层薄灰。水龙头拧开，水哗哗冲了一下。",
            "阴": "厨房暗沉沉的，开了灯。水龙头放了一会才出凉水。案板擦干净，准备开干。",
            "雨": "厨房窗户上全是雨点，灰蒙蒙的。水龙头拧开，凉水下冲着手上的菜泥。",
        }
        lines.append(kitchen_enter.get(self.weather, "进了厨房，开了灯。"))
        lines.append("")

        # 阶段3：预处理出成率——摘黄叶/去皮/去壳
        prep_lines = []
        self._yield_cache = {}  # name→actual_yield，不污染basket
        for item in self.basket:
            yp = YIELD_PCT.get(item["name"], 100)
            if yp < 80:
                # 品质越差出成率越低
                actual_yield = yp
                if item["quality"] in ("bad", "trap"):
                    actual_yield = max(yp - 20, 20)
                elif item["quality"] == "ok":
                    actual_yield = max(yp - 10, 30)
                self._yield_cache[item["name"]] = actual_yield
                # 找对应的损耗描述
                cat = VEGGIES.get(item["name"], {}).get("cat", "")
                if cat == "绿叶":
                    prep_lines.append(f"摘完黄叶、切掉老根，{item['name']}剩了大半，出成率约{actual_yield}%")
                elif cat == "根茎":
                    prep_lines.append(f"削完皮、切掉头尾，{item['name']}能用的约{actual_yield}%")
                elif cat == "鱼":
                    prep_lines.append(f"去鳞去鳃去内脏，{item['name']}净肉约{actual_yield}%")
                elif cat in ("豆类",):
                    prep_lines.append(f"剥完壳，{item['name']}能用的约{actual_yield}%")
                else:
                    prep_lines.append(f"处理完废料，{item['name']}出成率约{actual_yield}%")
        if prep_lines:
            lines.append("── 预处理 ──")
            for pl in prep_lines:
                lines.append(f"  {pl}")
            lines.append("")

        # 合并冰箱和买的
        all_items = list(self.fridge) + list(self.basket) + KITCHEN_DEFAULTS
        lines.append("手头有的：")
        for item in all_items:
            q_str = {"great": "极好", "good": "新鲜", "ok": "一般", "bad": "不太行", "trap": "看着行"}.get(item["quality"], "一般")
            lines.append(f"  {item['name']} {item.get('qty',1)}份（{q_str}）")
        lines.append("  厨房常备：葱姜蒜·盐酱油醋糖·料酒淀粉·油·水")

        lines.append("")
        # ── 菜谱提示——根据手头食材匹配 ──
        all_names = {item["name"] for item in all_items}
        suggestions = []
        for rname, rdata in RECIPES.items():
            ings = rdata.get("ingredients", [])
            if not ings:
                continue  # 任意蔬菜/蛋类菜谱跳过，太多
            if all(ing in all_names for ing in ings):
                suggestions.append(rname)
        # 也匹配隐藏菜谱（已解锁的）
        for rname in self.unlocked_hidden_recipes:
            if rname in HIDDEN_RECIPES:
                ings = HIDDEN_RECIPES[rname].get("ingredients", [])
                if ings and all(ing in all_names for ing in ings):
                    suggestions.append(f"📜{rname}")
        if suggestions:
            lines.append(f"可以试试：{'、'.join(suggestions[:6])}")
            lines.append("")

        lines.append("想做什么菜？两种做法——")
        lines.append("快做：「做法 番茄切块，鸡蛋打散先炒盛出，炒番茄出汁放回蛋，加盐出锅」")
        lines.append("细做：「做 番茄炒蛋」然后一步一步写步骤，每步看锅里变化")
        lines.append("快做省力，细做更稳。出状况时两种都会暂停问你。")
        lines.append("📖 " + self._status_bar())

        # 初始化厨房状态
        self.kitchen_state = {
            "dish_name": None,
            "steps": [],
            "pot_temp": 0,       # 0=冷, 1=温, 2=热, 3=很热
            "pot_contents": [],   # 锅里有什么
            "heat": 0,           # 0=关, 1=小, 2=中, 3=大
            "seasoning": [],     # 已加的调料
            "burned": False,
            "item_state": {},    # {name: doneness 0-100}，替代raw/done_items
            "quality_score": 0,  # 累计品质分
            "recipe": None,      # 当前菜谱骨架
            "completed_steps": set(),  # 已完成的步骤id
            "completed_optional": set(),  # 已完成的可选步骤id
            "completed_dishes": [],  # 已盛出的菜 [{name, items, score}]
            "_on_board": set(),      # 案板上的食材
            "held_items": [],        # 盛出的菜品（未入completed_dishes）
            "_salt_count": 0,        # 盐计数
        }
        return "\n".join(lines)

    def start_dish(self, dish_name):
        """开始做某道菜——匹配菜谱，检查食材"""
        if not self.kitchen_state:
            return "还没进厨房。先用「回家」。"
        ks = self.kitchen_state
        if self.done:
            return "今天的饭已经做完了。「新局」开始明天。"

        # 匹配菜谱
        recipe = RECIPES.get(dish_name)
        hidden = None
        if dish_name in HIDDEN_RECIPES:
            if dish_name in self.unlocked_hidden_recipes:
                hidden = HIDDEN_RECIPES[dish_name]
                recipe = hidden
            else:
                return f"你不会做「{dish_name}」。也许某天会有人教你。"

        # 如果之前锅里还有东西（上一道菜没盛出来），先提示
        _seasoning = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱"}
        cookable_in_pot = [n for n in ks.get("pot_contents", []) if n not in _seasoning]

        ks["dish_name"] = dish_name
        ks["recipe"] = recipe
        ks["completed_steps"] = set()
        ks["completed_optional"] = set()
        ks["quality_score"] = 0
        ks["burned"] = False
        ks["_salt_count"] = 0

        lines = []
        lines.append(f"开始做{dish_name}。")

        # 检查必需食材
        if recipe:
            all_items = list(self.fridge) + list(self.basket) + KITCHEN_DEFAULTS
            all_names = {item["name"] for item in all_items}
            missing = [ing for ing in recipe["ingredients"] if ing not in all_names]
            if missing:
                lines.append(f"⚠ 缺食材：{'、'.join(missing)}")
            # 列出菜谱必需步骤
            lines.append(f"步骤：{' → '.join(s['name'] for s in recipe['required'])}")
            if recipe.get("optional"):
                lines.append(f"加分项：{'、'.join(s['name'] for s in recipe['optional'])}")
        else:
            lines.append(f"（没有预设菜谱，自由发挥——引擎会判断每步操作。）")

        if cookable_in_pot:
            lines.append(f"锅里还有：{'、'.join(cookable_in_pot)}。先「盛出」再做下一道？")

        lines.append("")
        lines.append("写下一步操作。")
        lines.append("📖 " + self._status_bar())
        return "\n".join(lines)

    def _quick_cook(self, approach_text):
        """一句话做法——引擎自动推步骤，只在关键时刻暂停"""
        if not self.kitchen_state:
            return "还没进厨房。先用「回家」。"
        if self.done:
            return "今天的饭已经做完了。「新局」开始明天。"
        if not approach_text:
            return "怎么做？「做法 番茄切块炒出汁，鸡蛋打散先炒再放回去，加盐出锅」"

        ks = self.kitchen_state
        # 快做模式也设菜名——先从食材推测，后续recipe发现会覆盖
        if not ks.get("dish_name"):
            all_items = list(self.fridge) + list(self.basket) + KITCHEN_DEFAULTS
            all_names = {item["name"] for item in all_items}
            best_match = None
            best_score = 0
            for rname, rdata in RECIPES.items():
                ingredients = rdata.get("ingredients", [])
                if not ingredients:
                    # 任意蔬菜类菜谱——从菜谱名提取2字以上的关键词
                    # "蒜蓉炒时蔬" → ["蒜蓉", "时蔬", "蒜蓉炒"]
                    recipe_keys = [rname[i:i+2] for i in range(len(rname)-1) if len(rname[i:i+2]) >= 2]
                    recipe_keys = [k for k in recipe_keys if k not in ("炒时", "时蔬")]
                    key_match = any(k in approach_text for k in recipe_keys)
                    if key_match:
                        score = 100  # 做法文本提到菜谱关键词，给最高分
                    else:
                        continue
                else:
                    # 有具体食材的菜谱。
                    # 食材是硬证据，菜名关键词是软提示——
                    # 否则"先炒蛋盛出"会因含"炒蛋"两字被错认成"韭菜炒蛋"（家机撞过）。
                    # 做法/手头共同构成"可用食材"
                    usable = all_names | {ing for ing in ingredients if ing in approach_text}
                    ing_hit = sum(1 for ing in ingredients if ing in usable)
                    # 菜名证据：整名出现在做法里=强(玩家明说要做这道)；2字滑窗=弱
                    recipe_keys = [rname[i:i+2] for i in range(len(rname)-1)]
                    if rname in approach_text:
                        name_score = 100
                    elif any(k in approach_text for k in recipe_keys):
                        name_score = 50
                    else:
                        name_score = 0
                    # 综合分：食材覆盖为主，菜名为辅
                    ing_score = int(ing_hit / max(1, len(ingredients)) * 100)
                    score = max(ing_score, name_score)
                    # 菜名弱命中(50)但食材一个都没对上——不能认，否则纯靠"炒蛋"撞名
                    if name_score == 50 and ing_hit == 0:
                        score = 0
                if score > best_score:
                    best_score = score
                    best_match = rname
            if best_match and best_score >= len(RECIPES[best_match].get("ingredients", [])) - 1:
                ks["dish_name"] = best_match
                ks["recipe"] = RECIPES[best_match]
                ks.setdefault("completed_steps", set())
                ks.setdefault("completed_optional", set())
            else:
                ks["dish_name"] = approach_text[:10] + "…" if len(approach_text) > 10 else approach_text
        _seasoning = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱"}

        # 解析做法里的步骤——用句号/逗号/然后/接着/最后 分割
        # 注意：不用"再"和"先"分割——"先炒蛋再放回去"是一整步
        import re
        parts = re.split(r'[。，、；]|然后|接着|最后', approach_text)
        parts = [p.strip() for p in parts if p.strip()]

        if not parts:
            parts = [approach_text]

        # 逐步执行，收集反馈
        all_feedback = []
        hit_moment = False  # 是否遇到需要决策的厨房时刻

        for i, step in enumerate(parts):
            # 补全动词——如果只有食材名没动词，默认"切/下锅"
            step_full = step
            if not any(v in step for v in COOK_VERBS):
                # 纯食材名——根据上下文推断
                if i == 0:
                    step_full = f"切{step}"
                elif any(v in p for p in parts[:i] for v in ["热锅", "倒油", "烧油"]):
                    step_full = f"下{step}"
                else:
                    step_full = f"炒{step}"

            # 补全食材——步骤没提具体食材名时，加上还没入锅的
            # 只补玩家主动买的主料，不补 KITCHEN_DEFAULTS（葱姜蒜是调味，玩家提了才下）
            ks = self.kitchen_state
            if ks:
                _seasoning_names = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱", "葱", "姜", "蒜"}
                _kitchen_default_names = {d["name"] for d in KITCHEN_DEFAULTS}
                main_items = [item for item in (list(self.fridge) + list(self.basket))
                              if item["name"] not in _seasoning_names
                              and item["name"] not in _kitchen_default_names]
                mentioned = {item["name"] for item in main_items if item["name"] in step_full}
                in_pot = set(ks.get("pot_contents") or [])
                on_board = ks.get("_on_board") or set()
                unhandled = [item["name"] for item in main_items
                            if item["name"] not in mentioned
                            and item["name"] not in in_pot
                            and item["name"] not in on_board]
                if unhandled and any(v in step_full for v in ["炒", "煮", "炖", "煎", "炸", "烧", "蒸", "焖"]):
                    # 在第一个烹饪动词前插入食材，而不是替换动词字符
                    insert_pos = -1
                    for verb in ["炒", "煮", "炖", "煎", "炸", "烧", "蒸", "焖"]:
                        idx = step_full.find(verb)
                        if idx >= 0 and (insert_pos < 0 or idx < insert_pos):
                            insert_pos = idx
                    if insert_pos >= 0:
                        # 在动词后面插入食材名
                        verb_char = step_full[insert_pos]
                        step_full = step_full[:insert_pos+1] + "、".join(unhandled) + step_full[insert_pos+1:]

            # 调用cook_step
            result = self.cook_step(step_full)
            all_feedback.append(result)

            # 检查是否遇到厨房时刻需要暂停
            if "🔔" in result:
                hit_moment = True
                break  # 停在关键时刻

            # 检查是否糊了——紧急暂停
            if "糊了" in result or "快糊" in result:
                hit_moment = True
                break

        # 如果全部步骤执行完了没停，检查是否该出锅
        combined = "\n".join(all_feedback)
        if not hit_moment and not self.done:
            # 检查熟度——大部分食材在sweet区间就提示可以出锅
            cookable = {n: d for n, d in (ks.get("item_state") or {}).items()
                        if n not in _seasoning and d > 0}
            if cookable:
                avg_doneness = sum(cookable.values()) / len(cookable)
                if avg_doneness >= 40:
                    combined += "\n\n💭 看着差不多了——「出锅」端上桌？还是再煮一会儿？"

        return combined

    def cook_step(self, step_text):
        """AI写的一步做菜操作，引擎判定"""
        if not self.kitchen_state:
            return "还没进厨房。先用「回家」。"

        if self.done:
            return "今天的饭已经做完了。「新局」开始明天。"

        ks = self.kitchen_state
        # 防御：关键列表/字典可能被存档损坏或未来代码设成None
        if ks.get("pot_contents") is None:
            ks["pot_contents"] = []
        if ks.get("item_state") is None:
            ks["item_state"] = {}
        if ks.get("steps") is None:
            ks["steps"] = []
        if ks.get("seasoning") is None:
            ks["seasoning"] = []
        if ks.get("completed_dishes") is None:
            ks["completed_dishes"] = []
        step_text = step_text.strip()
        if not step_text:
            return "？"

        ks["steps"].append(step_text)
        feedback = []

        # ── 锅的自然流逝 ──
        # 开着火时食材缓慢变熟——超过阈值就糊
        # 案板上的食材（_on_board）不在锅里，不受热
        # 注意：烹饪步骤由_progress_doneness推进主要熟度，这里只加背景微热
        if ks.get("heat", 0) > 0:
            _seasoning = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱"}
            _on_board = ks.get("_on_board", set())
            tick = ks["heat"] * 2  # 小火+2/步，中火+4/步，大火+6/步（背景微热）
            for name in ks.get("item_state", {}):
                if name in _seasoning:
                    continue
                if name in _on_board:
                    continue  # 案板上的不熟
                old = ks["item_state"][name]
                ks["item_state"][name] = min(100, old + tick)
            # 锅温也涨
            ks["pot_temp"] = min(3, ks.get("pot_temp", 0) + 1)
            # 糊了判定——烧焦阈值受火候技能影响
            burn_at = self._burn_threshold()
            for name, d in ks.get("item_state", {}).items():
                if name in _seasoning:
                    continue
                if name in _on_board:
                    continue  # 案板上的不糊
                if d >= burn_at and not ks.get("burned"):
                    ks["burned"] = True
                    ks["quality_score"] -= 4
                    feedback.append(f"⚠ {name}糊了！焦味飘出来了。")
                    break

        # 解析步骤里的关键词——去重
        detected = []
        for verb, tag in COOK_VERBS.items():
            if verb in step_text:
                detected.append((verb, tag))
        # 去重1：位置重叠时只保留最长的（"切块"吞掉"切"，"加酱油"吞掉"加"）
        detected.sort(key=lambda x: len(x[0]), reverse=True)
        kept = []
        used_spans = []  # (start, end) 已占用的位置
        for verb, tag in detected:
            # 找第一个不被支配的位置（处理重复动词）
            start = 0
            idx = -1
            while True:
                idx = step_text.find(verb, start)
                if idx == -1:
                    break
                span = (idx, idx + len(verb))
                dominated = any(s <= span[0] and span[1] <= e for s, e in used_spans)
                if not dominated:
                    break
                start = idx + 1
            if idx == -1:
                continue
            kept.append((verb, tag))
            used_spans.append(span)
        detected = kept
        # 去重2：同tag只保留最长动词，season例外（可加多种调料）
        tag_groups = {}
        for verb, tag in detected:
            if tag not in tag_groups:
                tag_groups[tag] = []
            tag_groups[tag].append((verb, tag))
        final = []
        for tag, verbs in tag_groups.items():
            if tag == "season":
                final.extend(verbs)  # 调料可以多个
            else:
                # 同tag只留最长——"切块"优于"切"，"煸炒"优于"炒"
                final.append(max(verbs, key=lambda x: len(x[0])))
        detected = final

        # 解析食材（支持简称）
        ALIASES = {
            "蛋": "鸡蛋", "番茄": "番茄", "西红柿": "番茄",
            "肉": "瘦猪肉", "肉丝": "瘦猪肉", "五花肉": "五花肉",
            "排骨": "排骨", "鸡": "鸡腿", "鱼": "鲫鱼",
            "豆腐": "豆腐", "豆干": "豆腐干", "葱": "大葱",
            "姜": "姜", "蒜": "蒜", "椒": "青椒",
        }
        used_items = []
        all_items = list(self.fridge) + list(self.basket) + KITCHEN_DEFAULTS
        all_names = {item["name"] for item in all_items}
        # 先匹配全名，再匹配别名
        matched_names = set()
        for item in all_items:
            if item["name"] in step_text and item["name"] not in matched_names:
                used_items.append(item)
                matched_names.add(item["name"])
        for alias, full in ALIASES.items():
            if alias in step_text and full not in matched_names:
                for item in all_items:
                    if item["name"] == full and item["name"] not in matched_names:
                        used_items.append(item)
                        matched_names.add(item["name"])
                        break

        # 检查：提到的食材有没有手头没有的？
        _kitchen_seasoning_names = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱", "葱", "姜", "蒜"}
        _cat_map = {"肉": "肉", "鱼": "鱼", "鸡": "肉"}  # 模糊词→分类
        missing = set()
        for alias, full in ALIASES.items():
            if alias in step_text and full not in matched_names and full not in _kitchen_seasoning_names:
                # alias指向的full没买到——但同类里可能有（"肉"没买瘦猪肉，但买了五花肉）
                cat = _cat_map.get(alias)
                if cat:
                    has_cat = any(VEGGIES.get(item["name"], {}).get("cat") == cat for item in all_items if item["name"] not in _kitchen_seasoning_names)
                    if has_cat:
                        continue  # 同类有，不算missing
                elif full not in all_names:
                    missing.add(full)
        for vname in VEGGIES:
            if vname in step_text and vname not in matched_names and vname not in _kitchen_seasoning_names and vname not in all_names:
                missing.add(vname)
        if missing:
            feedback.append(f"⚠ 没有{'、'.join(missing)}，先去买。")

        # 厨房突发状况——根据当前步骤的关键词随机触发
        for acc_id, acc in KITCHEN_ACCIDENTS.items():
            if acc["trigger"] in step_text:
                if (self.rng() % 100) / 100 < acc["chance"]:
                    line = acc["lines"][self.rng() % len(acc["lines"])]
                    feedback.append(f"⚠ {line}")
                    ks["quality_score"] += acc["quality_effect"]
                    ks["accidents_happened"] = True  # 记录出了意外
                    break  # 每步最多一个意外

        # 手艺成长——做过的菜有隐藏加分
        # 先处理heat/boil（调火），再处理prep/cook（操作），最后season/cover等
        tag_order = {"heat": 0, "heat_high": 0, "heat_mid": 0, "heat_low": 0, "heat_off": 0,
                     "boil": 1, "prep": 2, "cook": 3, "season": 4, "cover": 5, "reduce": 5,
                     "add_water": 1, "hold": 6, "put_back": 6, "done": 7}
        detected.sort(key=lambda x: tag_order.get(x[1], 5))
        for verb, tag in detected:
            if tag == "heat":
                if "热锅" in step_text or "烧油" in step_text or "倒油" in step_text:
                    ks["heat"] = max(ks["heat"], 2)
                    ks["pot_temp"] = min(ks["pot_temp"] + 1, 3)
                    pool = COOK_STEP_FEEDBACK.get("热锅", ["锅热了。"])
                    feedback.append(pool[self.rng() % len(pool)])

            elif tag == "heat_high":
                ks["heat"] = 3
                ks["pot_temp"] = min(ks["pot_temp"] + 1, 3)
                pool = COOK_STEP_FEEDBACK.get("大火", ["大火。"])
                feedback.append(pool[self.rng() % len(pool)])

            elif tag == "heat_mid":
                ks["heat"] = 2
                pool = COOK_STEP_FEEDBACK.get("中火", ["中火。"])
                feedback.append(pool[self.rng() % len(pool)])

            elif tag == "heat_low":
                ks["heat"] = 1
                pool = COOK_STEP_FEEDBACK.get("小火", ["小火。"])
                feedback.append(pool[self.rng() % len(pool)])

            elif tag == "heat_off":
                ks["heat"] = 0
                ks["pot_temp"] = max(ks["pot_temp"] - 1, 0)
                pool = COOK_STEP_FEEDBACK.get("火关了", ["火关了。"])
                feedback.append(pool[self.rng() % len(pool)])

            elif tag == "prep":
                # 调料不入锅
                _kitchen_seasoning = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱"}
                # prep步骤：食材在案板上准备，不在锅里受热
                if "_on_board" not in ks:
                    ks["_on_board"] = set()
                for item in used_items:
                    if item["name"] in _kitchen_seasoning:
                        continue
                    # 加入pot_contents（为了显示和食材追踪），但标记为案板上
                    if item["name"] not in ks["pot_contents"]:
                        ks["pot_contents"].append(item["name"])
                    ks["_on_board"].add(item["name"])
                    # 初始化item_state（不覆盖已有的）
                    if item["name"] not in ks["item_state"]:
                        ks["item_state"][item["name"]] = 0
                    # 暗坑——切/洗时才发现内部问题
                    if item.get("quality") == "trap" and item["name"] in CUTTING_TRAP:
                        if verb in ("切", "洗", "剥", "切块", "切片", "切丝", "切段", "切丁", "切末", "拍", "拍碎", "沥干", "打散"):
                            trap_msg = CUTTING_TRAP[item["name"]]
                            feedback.append(f"⚠ {trap_msg}")
                            ks["quality_score"] -= 3
                            item["quality"] = "bad"
                    # 神秘时空：exotic 食材切/洗时揭穿"不属于这个时空"
                    if self.mystic and item.get("exotic") and verb in ("切", "洗", "剥", "切块", "切片", "切丝", "切段", "切丁", "切末", "拍", "拍碎", "沥干", "打散"):
                        ex_fb = self.mystic.apply_exotic_reveal(item, verb)
                        if ex_fb:
                            feedback.append(ex_fb)
                # 使用升级版反馈——优先食材特有感官
                fb_key_map = {"洗": "洗好", "切": "切好", "切段": "切好", "切片": "切好",
                              "切丝": "切好", "切块": "切好", "拍": "切好", "剥": "切好",
                              "腌": "腌上", "焯水": "焯好", "打散": "打散", "沥干": "洗好"}
                fb_key = fb_key_map.get(verb)
                # 食材特有感官——有50%概率替换通用反馈
                item_sense_shown = False
                if verb in ("切", "切块", "切片", "切丝", "切段", "拍", "剥", "洗", "打散"):
                    sense_key = "cut" if verb != "洗" else "wash"
                    for item in used_items:
                        sense = ITEM_SENSE_PREP.get(item["name"], {}).get(sense_key)
                        if sense and (self.rng() % 100) / 100 < 0.5:
                            feedback.append(sense)
                            item_sense_shown = True
                            break
                if not item_sense_shown and fb_key and fb_key in COOK_STEP_FEEDBACK:
                    pool = COOK_STEP_FEEDBACK[fb_key]
                    feedback.append(pool[self.rng() % len(pool)])
                else:
                    default_fb = {"洗": "洗好了。", "切": "切好了。", "切段": "切好了。", "切片": "切好了。",
                                  "切丝": "切好了。", "切块": "切好了。", "拍": "拍好了。", "剥": "剥好了。",
                                  "腌": "腌上了。", "焯水": "焯好了。", "打散": "打散了。", "沥干": "沥干了。"}
                    feedback.append(default_fb.get(verb, "准备好了。"))
                if "腌" in step_text:
                    ks["quality_score"] += 1
                # 焯水自动开火+加水+推进熟度
                if "焯水" in step_text:
                    if ks["heat"] < 1:
                        ks["heat"] = 3
                        ks["pot_temp"] = 3
                        feedback.append("大火烧开，焯了一遍。")
                    if "水" not in ks["pot_contents"]:
                        ks["pot_contents"].append("水")
                    # 焯水让食材半熟
                    for item in used_items:
                        if item["name"] not in _kitchen_seasoning:
                            ks["item_state"][item["name"]] = min(100, ks["item_state"].get(item["name"], 0) + 25)
                # 沥干/控水
                if verb in ("沥干", "控水"):
                    if "水" in ks["pot_contents"]:
                        ks["pot_contents"].remove("水")
                    if ks["heat"] >= 2:
                        ks["heat"] = 1
                        ks["pot_temp"] = 1
                        feedback.append("水沥干了，火调小了。")

            elif tag in ("cook",):
                if ks["pot_temp"] < 1:
                    fire_verbs = {"蒸", "炖", "煮", "煲", "焖", "炸", "煎", "烧", "煸炒", "翻炒", "爆炒", "干煸", "炒"}
                    if any(v in step_text for v in fire_verbs):
                        ks["heat"] = max(ks["heat"], 2)
                        ks["pot_temp"] = min(ks["pot_temp"] + 1, 2)
                        feedback.append("开火了。")
                    else:
                        feedback.append("锅还是冷的……先开火？")
                        ks["quality_score"] -= 2
                        continue
                # 食材入锅+初始化item_state
                _kitchen_seasoning = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱"}
                for item in used_items:
                    if item["name"] in _kitchen_seasoning:
                        continue
                    if item["name"] not in ks["pot_contents"]:
                        ks["pot_contents"].append(item["name"])
                    if item["name"] not in ks["item_state"]:
                        ks["item_state"][item["name"]] = 0
                    # 入锅——从案板上移到锅里
                    if "_on_board" in ks and item["name"] in ks["_on_board"]:
                        ks["_on_board"].discard(item["name"])
                    # 品质影响
                    q_map = {"great": 6, "good": 3, "ok": 0, "bad": -4, "trap": -7}
                    ks["quality_score"] += q_map.get(item.get("quality", "ok"), 0)

                # 即刻热度——煎炸爆香等直接接触高温，食材立刻有变化
                cook_boost = {"煎": 18, "炸": 22, "爆香": 15, "煸炒": 10,
                              "翻炒": 8, "炒": 10, "烧": 10, "干煸": 12}
                boost = cook_boost.get(verb, 5)
                for item in used_items:
                    if item["name"] in _kitchen_seasoning:
                        continue
                    ks["item_state"][item["name"]] = min(100, ks["item_state"].get(item["name"], 0) + boost)

                # ── 配方发现——食材组合触发 ──
                pot_set = set(ks.get("pot_contents", []))
                # 别名映射：鱼类的"鲫鱼/草鱼/鲈鱼"都匹配"鱼"
                fish_names = {"鲫鱼", "草鱼", "鲈鱼", "带鱼", "黄花鱼", "黄鳝"}
                pot_for_match = pot_set | ({"鱼"} if pot_set & fish_names else set())
                if "discovered_recipes" not in ks:
                    ks["discovered_recipes"] = set()
                for disc in RECIPE_DISCOVERIES:
                    if disc["items"] <= pot_for_match:
                        disc_key = disc.get("recipe_name") or "+".join(sorted(disc["items"]))
                        if disc_key in ks["discovered_recipes"]:
                            continue  # 这道菜已经发现过了
                        ks["discovered_recipes"].add(disc_key)
                        ks["quality_score"] += disc["bonus"]
                        feedback.append(f"✨ {disc['hint']}")
                        # 解锁菜谱
                        if disc.get("recipe_name") and disc["recipe_name"] not in self.unlocked_hidden_recipes:
                            self.unlocked_hidden_recipes.add(disc["recipe_name"])
                            feedback.append(f"📜 发现菜谱：{disc['recipe_name']}！")
                        # 自动设菜名——快做时没走start_dish，用发现的菜谱名
                        if disc.get("recipe_name") and not ks.get("dish_name"):
                            ks["dish_name"] = disc["recipe_name"]

                # 推进熟度——核心感官变化
                observations = self._progress_doneness(ks, step_text)
                for obs in observations:
                    feedback.append(obs)

                # 糊了判定——基于item_state，统一用burn_threshold
                burn_at = self._burn_threshold()
                for name, d in ks.get("item_state", {}).items():
                    if d >= burn_at and not ks.get("burned"):
                        ks["burned"] = True
                        ks["quality_score"] -= 5
                        break
                # 大火+高温额外糊风险
                if ks["heat"] >= 3 and ks["pot_temp"] >= 3:
                    if self.rng() % 4 == 0:
                        # 随机给一个食材加熟度
                        cookable = [n for n in ks["item_state"] if n not in _kitchen_seasoning]
                        if cookable:
                            target = cookable[self.rng() % len(cookable)]
                            ks["item_state"][target] = min(100, ks["item_state"][target] + 15)
                            if ks["item_state"][target] >= 86 and not ks.get("burned"):
                                ks["burned"] = True
                                ks["quality_score"] -= 5
                                feedback.append("⚠ 火太大了！")

                # 做法感官反馈——不再是模板，是你在灶台前看到的
                cook_sensory = {
                    "翻炒": "锅铲翻动，食材在锅里跳。",
                    "煎": "滋滋响，一面煎着变色。",
                    "炸": "油花翻滚，表面起泡。",
                    "炖": "汤面微微起伏，咕嘟声沉了下来。",
                    "蒸": "蒸汽顶着锅盖，水珠顺着盖子往下淌。",
                    "煮": "水面翻着花，食材在汤里打着转。",
                    "焖": "盖着盖子，偶尔从缝里冒出一缕热气。",
                    "煲": "小火慢煲，汤色一点点变浓。",
                    "爆香": "刺啦一声，香味冲出来了！",
                    "煸炒": "油滋滋响，食材边缘开始卷曲变色。",
                    "炒": "锅铲翻飞，香味出来了。",
                }
                feedback.append(cook_sensory.get(verb, "做着呢。"))

            elif tag == "season":
                ks["seasoning"].append(verb)
                # 前3次调味加分，之后不加了（防止刷分）
                if len(ks["seasoning"]) <= 3:
                    ks["quality_score"] += 1
                elif len(ks["seasoning"]) > 5:
                    ks["quality_score"] -= 1  # 调太多反而扣分
                season_fb = {"加盐": "加盐。", "加酱油": "加酱油。", "加醋": "加醋。", "加糖": "加糖。",
                             "加料酒": "加料酒。", "加蚝油": "加蚝油。", "加淀粉": "勾芡。", "调味": "调味。"}
                feedback.append(season_fb.get(verb, "调味。"))
                # 盐计数
                if "加盐" in step_text or "加酱油" in step_text:
                    ks["_salt_count"] = ks.get("_salt_count", 0) + 1
                    if ks["_salt_count"] >= 3:
                        feedback.append("⚠ 有点咸了。可以加勺水或加点糖压一压。")
                # 加糖补救咸味（可以在season步骤里同时加）
                if "加糖" in step_text and ks.get("_salt_count", 0) >= 2:
                    ks["_salt_count"] = max(0, ks["_salt_count"] - 1)
                    ks["quality_score"] += 1
                    feedback.append("糖压了点咸味。能吃。")

            elif tag == "cover":
                ks["quality_score"] += 1
                feedback.append("盖上盖子。")

            elif tag == "reduce":
                ks["quality_score"] += 1
                feedback.append("收汁。")

            elif tag == "add_water":
                if "水" not in ks["pot_contents"]:
                    ks["pot_contents"].append("水")
                ks["quality_score"] += 1
                feedback.append("加水。锅里开始有汤了。")
                # 补救：太咸了加水能救
                if ks.get("_salt_count", 0) >= 2:
                    ks["_salt_count"] = max(0, ks["_salt_count"] - 1)
                    ks["quality_score"] += 1
                    feedback.append("加了水，咸味淡了一点。还行。")

            elif tag == "boil":
                ks["heat"] = 3
                ks["pot_temp"] = 3
                if "水" not in ks["pot_contents"]:
                    ks["pot_contents"].append("水")
                feedback.append("大火烧开，咕嘟咕嘟。")

            elif tag == "hold":
                # 盛出——把东西从锅里拿出来放一边
                _seasoning_hold = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱", "葱", "姜", "蒜"}
                cookable_in_pot = [n for n in ks["pot_contents"] if n not in _seasoning_hold]

                # 判断：是指定盛出某几样，还是全盛
                specified = [item["name"] for item in used_items if item["name"] in cookable_in_pot]
                if specified:
                    # 只盛出指定的食材
                    held = specified
                    for name in held:
                        if name in ks["pot_contents"]:
                            ks["pot_contents"].remove(name)
                    if "held_items" not in ks:
                        ks["held_items"] = []
                    ks["held_items"].extend(held)
                elif cookable_in_pot:
                    # 没指定→全盛出来
                    held = cookable_in_pot
                    ks["pot_contents"] = [c for c in ks["pot_contents"] if c in _seasoning_hold]
                    if "held_items" not in ks:
                        ks["held_items"] = []
                    ks["held_items"].extend(held)
                else:
                    held = []

                if held:
                    feedback.append(f"盛出{', '.join(held)}，放一边。")
                else:
                    feedback.append("锅里没什么可盛的。")

                # 锅空了——这道菜做完，可以接着做下一道
                cookable_left = [n for n in ks["pot_contents"] if n not in _seasoning_hold]
                if not cookable_left and held:
                    # 记录这道菜
                    dish_name = ks.get("dish_name") or "炒菜"
                    dish_items = list(held)
                    dish_score = ks.get("quality_score", 0)
                    # 算品相
                    if dish_score >= 10:
                        dish_app = "great"
                    elif dish_score >= 5:
                        dish_app = "good"
                    elif dish_score >= 0:
                        dish_app = "ok"
                    elif dish_score >= -5:
                        dish_app = "bad"
                    else:
                        dish_app = "terrible"
                    ks["completed_dishes"].append({
                        "name": dish_name,
                        "items": dish_items,
                        "score": dish_score,
                        "appearance": dish_app,
                    })
                    feedback.append(f"「{dish_name}」盛出装盘。锅空了——接着做下一道？")
                    # 重置锅的状态，准备做下一道
                    ks["pot_contents"] = []
                    ks["item_state"] = {}
                    ks["seasoning"] = []
                    ks["burned"] = False
                    ks["quality_score"] = 0
                    ks["dish_name"] = None
                    ks["heat"] = 0
                    ks["pot_temp"] = 0
                    if "held_items" in ks:
                        del ks["held_items"]

            elif tag == "put_back":
                # 放回——把盛出的东西倒回锅里
                if "held_items" not in ks or not ks["held_items"]:
                    feedback.append("没什么要放回的。")
                else:
                    back = []
                    for item in used_items:
                        if item["name"] in ks["held_items"]:
                            ks["held_items"].remove(item["name"])
                            if item["name"] not in ks["pot_contents"]:
                                ks["pot_contents"].append(item["name"])
                            back.append(item["name"])
                    if not back:
                        back = list(ks["held_items"])
                        for name in back:
                            if name not in ks["pot_contents"]:
                                ks["pot_contents"].append(name)
                        ks["held_items"] = []
                    if back:
                        feedback.append(f"放回{', '.join(back)}。")

            elif tag == "done":
                # 出锅——检查有没有太生的
                _seasoning_names = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱"}
                raw_items = [n for n, d in ks.get("item_state", {}).items()
                             if d < 20 and n not in _seasoning_names]
                if raw_items:
                    feedback.append(f"⚠ 还有东西没熟：{', '.join(raw_items)}")
                    ks["quality_score"] -= 3
                feedback.append("出锅装盘。")
                return self._serve()

        # 如果步骤里有食材但没有动词，提示
        if used_items and not detected:
            feedback.append(f"你要怎么处理{', '.join(i['name'] for i in used_items)}？")

        # 预处理技巧检测——用到对应技巧加分
        if "unlocked_prep" not in ks:
            ks["unlocked_prep"] = []
        for skill_id, skill in PREP_SKILLS.items():
            if skill_id in ks["unlocked_prep"]:
                continue
            # 检查触发词
            triggers = skill["trigger"].split("|")
            if any(t in step_text for t in triggers):
                # 检查食材匹配
                if not skill["item"] or any(skill["item"] in item["name"] or
                        (skill["item"] == "绿叶" and VEGGIES.get(item["name"], {}).get("cat") == "绿叶") or
                        (skill["item"] == "鱼" and VEGGIES.get(item["name"], {}).get("cat") == "鱼") or
                        (skill["item"] == "肉" and VEGGIES.get(item["name"], {}).get("cat") == "肉")
                        for item in used_items):
                    ks["unlocked_prep"].append(skill_id)
                    ks["quality_score"] += skill["bonus"]
                    feedback.append(f"🎯 技巧：{skill['effect']}")

        # 生成锅里状态描述
        pot_desc = self._pot_description()

        # ── 时间流逝——锅不等你 ──
        # 只要火开着，每一步（哪怕是切菜、加调料）锅里都在变
        # 案板上的食材不受热
        time_elapsed = False
        _on_board = ks.get("_on_board", set())
        if ks["heat"] > 0 and ks.get("item_state"):
            _seasoning_check = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱"}
            has_cookable = any(n not in _seasoning_check and n not in _on_board for n in ks.get("item_state", {}))
            if has_cookable:
                # cook/boil步骤已经在tag处理里推过熟度了，不重复
                step_already_cooked = any(tag in ("cook", "boil") for _, tag in detected)
                if not step_already_cooked:
                    # 非烹饪步骤——时间照样过
                    # 干烧加速——没水没汤时更容易糊
                    dry_burn = "水" not in ks.get("pot_contents", [])
                    dry_mult = 2.0 if dry_burn and ks["heat"] >= 3 else 1.0
                    for name, d in list(ks.get("item_state", {}).items()):
                        if name in _seasoning_check or name in _on_board:
                            continue
                        cat = self._sense_cat(name)
                        stage_data = COOK_STAGES.get(cat)
                        speed = stage_data["speed"] if stage_data else 10
                        # 非烹饪步骤推0.5倍熟度
                        ks["item_state"][name] = min(100, d + speed * 0.5 * {1: 0.5, 2: 1.0, 3: 1.5}.get(ks["heat"], 0) * dry_mult)
                else:
                    # 烹饪步骤也已推过，但如果是大火干烧，额外加一笔"过火"
                    dry_burn = "水" not in ks.get("pot_contents", [])
                    if dry_burn and ks["heat"] >= 3:
                        for name, d in list(ks.get("item_state", {}).items()):
                            if name in _seasoning_check or name in _on_board:
                                continue
                            ks["item_state"][name] = min(100, d + 5)
                    time_elapsed = True

        # ── 随机惊喜——做菜不全是坏运气 ──
        if ks["heat"] > 0 and ks.get("item_state"):
            # 5%概率：食材自己烧得特别好
            _seasoning_check = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱"}
            cookable = [n for n, d in ks["item_state"].items() if n not in _seasoning_check and n not in _on_board and 30 <= d <= 70]
            if cookable and (self.rng() % 100) < 5:
                lucky = cookable[self.rng() % len(cookable)]
                ks["quality_score"] += 2
                lucky_desc = self._item_sensory(lucky, ks["item_state"][lucky])
                feedback.append(f"🍀 {lucky}烧得恰到好处——{lucky_desc}")
                time_elapsed = True

        # 步骤骨架检测——碰到必需步骤就标记完成
        recipe = ks.get("recipe")
        if recipe:
            for step in recipe["required"]:
                if step["id"] not in ks["completed_steps"]:
                    for kw in step["keywords"]:
                        if kw in step_text:
                            ks["completed_steps"].add(step["id"])
                            break
            # 可选步骤
            for step in recipe.get("optional", []):
                if step["id"] not in ks["completed_optional"]:
                    for kw in step["keywords"]:
                        if kw in step_text:
                            ks["completed_optional"].add(step["id"])
                            ks["quality_score"] += step["bonus"]
                            feedback.append(f"（{step['name']}，做得细。）")
                            break

        lines = []
        if feedback:
            lines.extend(feedback)
        if pot_desc:
            lines.append("")
            lines.append(f"🍳 {pot_desc}")

        # ── 厨房时刻——需要判断的瞬间 ──
        moment = self._check_kitchen_moment(ks, step_text)
        if moment:
            lines.append("")
            lines.append(f"🔔 {moment}")

        # 卡住提示——连续2步没推进recipe，给个hint
        if recipe:
            next_steps = [s for s in recipe["required"] if s["id"] not in ks.get("completed_steps", set())]
            if next_steps:
                # 追踪最近有没有推进
                if not hasattr(self, '_stall_cook_count'):
                    self._stall_cook_count = 0
                # 检查completed_steps里是否有recipe的步骤
                # （不能用steps[-1]比对——steps存文本，completed_steps存id）
                recipe_ids = {s["id"] for s in recipe["required"]}
                if recipe_ids & ks.get("completed_steps", set()):
                    self._stall_cook_count = 0  # 有推进，重置
                else:
                    self._stall_cook_count += 1
                if self._stall_cook_count >= 2:
                    hint = next_steps[0]["hint"] if next_steps[0].get("hint") else next_steps[0]["name"]
                    lines.append(f"💭 {hint}")
                    self._stall_cook_count = 0

        # 做菜氛围——偶尔插入厨房生活感（紧凑模式跳过）
        if not COMPACT_MODE and COOKING_MOOD and (self.rng() % 100) / 100 < 0.18:
            lines.append("")
            lines.append(COOKING_MOOD[self.rng() % len(COOKING_MOOD)])

        lines.append("")
        lines.append("继续写下一步，或者「出锅」结束。")

        # ── 技能成长 ──
        skill_msgs = []
        for verb, tag in detected:
            if tag == "prep":
                skill_msgs.append(self._grow_skill("刀工", PLAYER_SKILLS["刀工"]["grow_step"]))
            elif tag in ("heat_high", "heat_mid", "heat_low", "heat_off"):
                skill_msgs.append(self._grow_skill("火候", PLAYER_SKILLS["火候"]["grow_step"]))
            elif tag in ("cook", "boil"):
                skill_msgs.append(self._grow_skill("火候", PLAYER_SKILLS["火候"]["grow_step"]))
        for msg in skill_msgs:
            if msg:
                lines.append(msg)

        # ── 刀工自动切菜 ──
        auto_cut = self._auto_cut_chance()
        if auto_cut > 0 and detected:
            for verb, tag in detected:
                if tag == "prep" and (self.rng() % 100) / 100 < auto_cut:
                    lines.append(f"🔪 刀工熟练，{verb}得又快又好。")

        lines.append("📖 " + self._status_bar())
        return "\n".join(lines)

    def serve(self):
        """强制出锅"""
        return self._serve()

    def _serve(self):
        """端上桌"""
        if self.done:
            return "今天的饭已经做完了。「新局」开始明天。"
        ks = self.kitchen_state
        if not ks:
            return "还没进厨房呢。先「回家」。"
        # 空锅检查——锅里没放任何食材
        _seasoning = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱"}
        cookable = [n for n in ks.get("pot_contents", []) if n not in _seasoning]
        if not cookable and not ks.get("completed_dishes"):
            return "锅里什么都没有，先做菜再出锅。"
        # 锅空了但之前盛出了菜——汇总分数后端上桌
        if not cookable and ks.get("completed_dishes"):
            # 累加之前菜的分数
            total_score = ks.get("quality_score", 0)
            for prev in ks["completed_dishes"]:
                total_score += prev.get("score", 0)
            if total_score >= 10:
                appearance = "great"
            elif total_score >= 5:
                appearance = "good"
            elif total_score >= 0:
                appearance = "ok"
            elif total_score >= -5:
                appearance = "bad"
            else:
                appearance = "terrible"
            lines = []
            lines.append("──── 今天的饭 ────")
            appear_desc = self._appearance_desc("这顿饭", appearance, ks)
            lines.append(appear_desc)
            for prev in ks["completed_dishes"]:
                prev_name = prev.get("name", "炒菜")
                prev_items = "、".join(prev.get("items", []))
                prev_app = prev.get("appearance", "ok")
                app_zh = {"great": "极好", "good": "不错", "ok": "一般", "bad": "不太行", "terrible": "砸了"}.get(prev_app, "一般")
                lines.append(f"  {prev_name}（{prev_items}）{app_zh}")
            self.done = True
            self._last_opened_day = None  # 今天的局做完了，解开封印，下回 new_day 不再挡
            self.save()
            lines.append("")
            lines.append(f"📖 {self.season} · {self.weather} | 第{self.day}天")
            lines.append("── 下一局用「新局」开始 ──")
            return "\n".join(lines)
        score = ks["quality_score"]

        # 检查必需步骤是否都完成了
        recipe = ks.get("recipe")
        missed = []
        if recipe:
            for step in recipe["required"]:
                if step["id"] not in ks.get("completed_steps", set()):
                    missed.append(step)

        # ── 熟度品质评分 ──
        _seasoning_names = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱"}
        doneness_notes = []
        for name, d in ks.get("item_state", {}).items():
            if name in _seasoning_names:
                continue
            cat = self._sense_cat(name)
            stage_data = COOK_STAGES.get(cat)
            if not stage_data:
                continue
            sweet_lo, sweet_hi = stage_data["sweet"]
            if d < 20:
                score -= 5
                doneness_notes.append(f"{name}还是生的")
            elif d < sweet_lo:
                score -= 2
                doneness_notes.append(f"{name}差点火候")
            elif d <= sweet_hi:
                score += 3  # 最佳区间加分
            elif d <= 85:
                score -= 2
                doneness_notes.append(f"{name}有点过了")
            else:
                score -= 5
                doneness_notes.append(f"{name}糊了")

        # 手艺成长——做过的菜有隐藏加分
        dish_name = ks.get("dish_name") or "这盘菜"
        cook_count = self.cook_history.get(dish_name, 0)
        craft_bonus = min(cook_count * 0.5, 3)  # 上限+3
        score += craft_bonus
        if craft_bonus > 0:
            # 不告诉AI具体加了多少，只是结果好了
            pass
        # 记录这次做过
        self.cook_history[dish_name] = cook_count + 1
        if dish_name in HIDDEN_RECIPES and dish_name in self.unlocked_hidden_recipes:
            bonus = HIDDEN_RECIPES[dish_name].get("bonus_score", 3)
            score += bonus

        # 品相
        if score >= 10:
            appearance = "great"
        elif score >= 5:
            appearance = "good"
        elif score >= 0:
            appearance = "ok"
        elif score >= -5:
            appearance = "bad"
        else:
            appearance = "terrible"

        # 记录品相历史（在appearance赋值之后）
        if not hasattr(self, 'dish_history'):
            self.dish_history = {}
        hist = self.dish_history.get(dish_name, [])
        hist.append({"day": self.day, "appearance": appearance})
        if len(hist) > 5:
            hist = hist[-5:]
        self.dish_history[dish_name] = hist

        # 品相描述
        dish_name = ks.get("dish_name") or "这盘菜"
        appear_desc = self._appearance_desc(dish_name, appearance, ks)

        lines = []
        lines.append(f"──── {dish_name} ────")
        lines.append(appear_desc)
        drama_pool = SERVE_DRAMA.get(appearance, SERVE_DRAMA["ok"])
        lines.append(drama_pool[int(self.rng() * len(drama_pool)) % len(drama_pool)])

        # 之前盛出的菜也一起端上来
        if ks.get("completed_dishes"):
            lines.append("")
            lines.append("桌上还有：")
            for prev in ks["completed_dishes"]:
                prev_name = prev.get("name", "炒菜")
                prev_items = "、".join(prev.get("items", []))
                lines.append(f"  {prev_name}（{prev_items}）")

        # 熟度备注
        if doneness_notes:
            lines.append(f"⚠ {'、'.join(doneness_notes)}")

        # 算用了哪些食材
        used_names = set(ks["pot_contents"])

        # ── 叙事段落：这盘菜是怎么来的 ──
        journey_parts = []
        used_items_info = [item for item in self.basket if item["name"] in used_names]
        # 天气
        if self.weather == "雨":
            journey_parts.append("冒着雨赶的早市")
        elif self.weather == "雪":
            journey_parts.append("踩着雪去的菜场")
        # 关键食材来源
        key_item = used_items_info[0] if used_items_info else None
        if key_item:
            owner = key_item.get("owner", "")
            quality = key_item.get("quality", "ok")
            free = key_item.get("free", False)
            if free:
                journey_parts.append(f"{owner}送的{key_item['name']}")
            elif quality == "great" and owner:
                journey_parts.append(f"从{owner}那挑的最好的{key_item['name']}")
            elif quality in ("bad", "trap") and owner:
                journey_parts.append(f"在{owner}那买的{key_item['name']}，当时就觉得不太对")
            elif owner:
                journey_parts.append(f"{owner}那买的{key_item['name']}")
        # 做菜意外
        if ks.get("burned"):
            journey_parts.append("差点糊了")
        if ks.get("_salt_count", 0) >= 2:
            journey_parts.append("盐没控制好")
        if ks.get("accidents_happened"):
            journey_parts.append("厨房里出了点状况")
        # 神秘时空：exotic 食材端上桌的异象叙事
        if self.mystic and used_items_info:
            exotic_item = next((it for it in used_items_info if it.get("exotic")), None)
            if exotic_item:
                drama = self.mystic.apply_exotic_serve(exotic_item)
                if drama:
                    journey_parts.append(drama)
        # 拼叙事
        if journey_parts:
            narrative = "、".join(journey_parts) + "。"
            if appearance in ("great", "good"):
                narrative += "值了。"
            elif appearance == "ok":
                narrative += "凑合能吃。"
            elif appearance == "bad":
                narrative += "费这么大劲，就这样了。"
            else:
                narrative += "……白忙活了。"
            lines.append("")
            lines.append(narrative)

        # ── 口味标注——不替人反应，只标注这盘菜用了什么她爱的/不吃的 ──
        p = self.palate
        loved_hit = [n for n in used_names if n in p.get("loves", {})]
        disliked_hit = [n for n in used_names if n in p.get("dislikes", {})]
        feared_hit = [n for n in used_names if n in p.get("fears", {})]

        taste_notes = []
        if loved_hit:
            taste_notes.append(f"她爱吃的：{'、'.join(loved_hit)}")
        if disliked_hit:
            taste_notes.append(f"她不吃的：{'、'.join(disliked_hit)}")
        if feared_hit:
            taste_notes.append(f"她怕的：{'、'.join(feared_hit)}")
        if self.wife_state and self._state_craving:
            craving_hit = [n for n in used_names if n in self._state_craving]
            if craving_hit:
                taste_notes.append(f"对路了：{'、'.join(craving_hit)}")
        if self.wife_state and self._state_avoid:
            avoid_hit = [n for n in used_names if n in self._state_avoid]
            if avoid_hit:
                taste_notes.append(f"不太对：{'、'.join(avoid_hit)}")
        if taste_notes:
            lines.append("｜" + " ｜".join(taste_notes) + "｜")

        # 食材搭配刚需——做鱼/肉时没用配菜扣分
        pot_contents = set(ks.get("pot_contents", []))
        seasoning = set(ks.get("seasoning", []))
        used_stuff = pot_contents | seasoning
        pairing_rules = [
            ("鲫鱼", "姜", "鱼没配姜，腥味去不干净"),
            ("草鱼", "姜", "鱼没配姜，腥味去不干净"),
            ("鲈鱼", "姜", "鱼没配姜，腥味去不干净"),
            ("五花肉", "葱", "肉没配葱，腥气重"),
            ("瘦猪肉", "姜", "肉没配姜，有点腥"),
            ("豆腐", "葱", "豆腐没配葱，少了点香"),
        ]
        for main_item, needed, msg in pairing_rules:
            if main_item in pot_contents and needed not in used_stuff:
                score -= 3
                lines.append(f"⚠ {msg}")

        # 食材品质汇总——一行，不替人评价
        quality_summary = []
        for item in self.basket:
            if item["name"] in used_names:
                q_str = {"great": "★优", "good": "✓好", "ok": "～般", "bad": "✗差", "trap": "⚠坑"}.get(item["quality"], "～般")
                quality_summary.append(f"{item['name']}{q_str}")
        if quality_summary:
            lines.append(f"食材：{'、'.join(quality_summary)}")

        if missed:
            lines.append(f"⚠ 遗漏步骤：{'、'.join(s['name'] for s in missed)}")
            score -= len(missed) * 2
        # 做菜回忆——带出品相和她说的话
        if cook_count >= 2:
            recall_parts = [f"做过{cook_count}次了"]
            # 品相回忆——上次做坏了？
            if hasattr(self, 'dish_history') and dish_name in self.dish_history:
                hist = self.dish_history[dish_name]
                if len(hist) >= 2:
                    last_h = hist[-2]  # 上次（不含这次）
                    last_app = last_h.get("appearance", "ok")
                    if last_app in ("bad", "terrible"):
                        if appearance in ("great", "good"):
                            recall_parts.append("上次做糊了，这次好多了")
                        else:
                            recall_parts.append("上次也没做好")
                    elif last_app in ("great", "good") and appearance in ("bad", "terrible"):
                        recall_parts.append("上次做得挺好的，今天怎么不行了")
            lines.append(f"（{dish_name}{'，'.join(recall_parts)}。）")
        elif cook_count == 1 and appearance in ("bad", "terrible"):
            # 第一次做就翻车——不扣关系分，只是记录
            lines.append(f"（第一次做{dish_name}，翻车了。没关系。）")
        # 她上次说了什么——记着呢
        if hasattr(self, 'dish_feedback') and dish_name in self.dish_feedback:
            last_fb = self.dish_feedback[dish_name][-1]
            days_ago = self.day - last_fb.get("day", self.day)
            if days_ago == 0:
                pass  # 今天刚说的，不重复
            elif days_ago == 1:
                lines.append(f"（她昨天说——{last_fb['text']}）")
            else:
                lines.append(f"（上次她吃了说——{last_fb['text']}）")

        # 把没用的冰箱东西留着 + 旧冰箱里没用到的也保留
        old_fridge = [item for item in self.fridge if item["name"] not in used_names]
        self.fridge = []
        # 旧冰箱里没用到的原样保留
        self.fridge.extend(old_fridge)
        # 买的食材用了就没了，但没放进菜里的可以留冰箱
        for item in self.basket:
            if item["name"] not in used_names:
                keep = KEEP_DAYS.get(item["name"], 3)
                # 保鲜0天的不能留
                if keep == 0:
                    lines.append(f"（{item['name']}放不住，没做的部分只能扔了。）")
                else:
                    self.fridge.append({"name": item["name"], "quality": item["quality"], "qty": item.get("qty", 1), "keep_days": keep})

        # 出成率汇总——低出成率的菜给提醒
        low_yield_items = []
        for item in self.basket:
            yp = YIELD_PCT.get(item["name"], 100)
            if yp < 60:
                low_yield_items.append(f"{item['name']}({yp}%)")
        if low_yield_items:
            lines.append(f"💡 出成率提醒：{'、'.join(low_yield_items)}，废料不少。")

        # ── 每日小账 ──
        lines.append("")
        lines.append("── 今日小账 ──")
        lines.append(f"买菜总共花了 {self.spent} 元")

        # 额外损耗统计
        extra_loss = []
        for item in self.basket:
            if item.get("weight_trick_type"):
                extra_loss.append(f"{item['name']}的{item['weight_trick_type']}多花了约{item.get('weight_trick_extra', 0)}%")
        if extra_loss:
            lines.append(f"额外损耗：{'、'.join(extra_loss)}")

        # 浪费统计
        wasted = []
        for item in self.basket:
            if item["name"] not in used_names:
                keep = KEEP_DAYS.get(item["name"], 3)
                if keep == 0:
                    wasted.append(f"{item['name']}放不住扔了")
        if wasted:
            lines.append(f"浪费：{'、'.join(wasted)}")

        # 冰箱剩
        if self.fridge:
            fridge_detail = []
            for item in self.fridge:
                kd = item.get("keep_days", 3)
                fridge_detail.append(f"{item['name']}(能放{kd}天)")
            lines.append(f"冰箱剩：{'、'.join(fridge_detail)}")
        else:
            lines.append("冰箱空的。")

        # 预处理技巧解锁数
        if ks.get("unlocked_prep"):
            lines.append(f"学到技巧：{len(ks['unlocked_prep'])}个")

        self.done = True
        self._last_opened_day = None  # 今天的局做完了，解开封印，下回 new_day 不再挡
        self.plate = {"dish": dish_name, "appearance": appearance, "score": score}

        # 统计
        self.stats["unique_dishes"].add(dish_name)
        self.stats["unique_days"].add(str(self.day))
        if appearance == "terrible":
            self.stats["terrible_dishes"] += 1
        new_ach = self._check_achievements()
        if new_ach:
            lines.append(f"🏆 解锁成就：{new_ach}")

        self.save()

        # ── 技能成长——做了一顿饭，刀工火候都涨 ──
        skill_msgs = []
        skill_msgs.append(self._grow_skill("刀工", PLAYER_SKILLS["刀工"]["grow_cook"]))
        skill_msgs.append(self._grow_skill("火候", PLAYER_SKILLS["火候"]["grow_cook"]))
        for msg in skill_msgs:
            if msg:
                lines.append(msg)
        self.save()  # 技能变动也存一下

        # ── 日终事件——洗完碗后的生活碎片 ──
        for evt in DAY_END_EVENTS:
            cond = evt.get("condition", {})
            ok = True
            if cond.get("weather") and self.weather != cond["weather"]:
                ok = False
            if cond.get("season") and self.season != cond["season"]:
                ok = False
            appearance_order = {"great": 4, "good": 3, "ok": 2, "bad": 1, "terrible": 0}
            app_val = appearance_order.get(appearance, 2)
            if "min_appearance" in cond:
                if app_val < appearance_order.get(cond["min_appearance"], 2):
                    ok = False
            if "max_appearance" in cond:
                if app_val > appearance_order.get(cond["max_appearance"], 2):
                    ok = False
            if ok and (self.rng() % 100) / 100 < evt["chance"]:
                lines.append("")
                lines.append(evt["text"])
                break  # 一天最多一个日终事件

        # ── 明天预告（钩子） ──
        hooks = []
        # 线索进度
        clue_found = len(self.found_clues)
        clue_total = len(CLUE_FRAGMENTS)
        if 0 < clue_found < clue_total:
            need = clue_total - clue_found
            hooks.append(f"📖 线索碎片 {clue_found}/{clue_total}，还差{need}个")
        # 好感接近解锁
        for sid, aff in self.affection.items():
            stall = self._find_stall(sid)
            if not stall:
                continue
            for ms in AFFECTION_MILESTONES:
                if ms["stall"] == sid and aff >= ms["affection"] - 5 and aff < ms["affection"]:
                    hooks.append(f"🔓 {stall['owner']}好感{aff}，再聊几次就到{ms['affection']}")
                    break
        # 选择链未完成
        for chain_id, chain in CHOICE_CHAINS.items():
            for step in chain["steps"]:
                if step["id"] not in self.chain_done:
                    # 检查前置是否满足
                    req = step.get("require_flag")
                    if req and not req.startswith("!") and req in self.chain_flags:
                        hooks.append(f"〔{chain['title']}〕还没完…")
                        break
                    elif not req:
                        trigger = step.get("trigger", {})
                        if self.day + 1 >= trigger.get("min_day", 0):
                            hooks.append(f"〔{chain['title']}〕也许明天会有新进展")
                            break
        # 季节食材快没了
        season_next = SEASONS[(SEASONS.index(self.season) + 1) % 4] if self.season in SEASONS else self.season
        leaving = [name for name, v in VEGGIES.items()
                   if v["season"].get(self.season, "no") == "in"
                   and v["season"].get(season_next, "no") == "no"
                   and not v.get("_secret")]
        if leaving and self.day % 7 >= 5:  # 接近换季
            hooks.append(f"🌿 {self.season}快过了，{leaving[0]}等下季就没了")
        # 随机NPC预告
        if (self.rng() % 100) / 100 < 0.25:
            npc_hints = [
                "明天早点去，何大爷说早上鱼最好",
                "王姐好像在准备什么好吃的",
                "听说菜场要来个新摊位",
                "老吴这两天心情不错",
            ]
            hooks.append(npc_hints[self.rng() % len(npc_hints)])

        if hooks:
            lines.append("")
            lines.append("── 明天 ──")
            for h in hooks[:3]:  # 最多3个钩子，不啰嗦
                lines.append(f"  {h}")

        lines.append("")
        lines.append(f"📖 {self.season} · {self.weather} | 第{self.day}天")
        # ── 她说 ──
        # 端上桌了，她吃了会说什么？用「她说 XXX」记录她的反应
        # 下次做同样的菜，引擎会记得她上次怎么说的
        lines.append("")
        lines.append("她吃了会说什么？用「她说 ……」告诉我。")
        lines.append("── 下一局用「新局」开始 ──")
        return "\n".join(lines)

    # ---- 工具方法 ----

    def _sense_cat(self, item_name):
        """食材→感官分类"""
        if item_name in ITEM_SENSE_CAT:
            return ITEM_SENSE_CAT[item_name]
        cat = VEGGIES.get(item_name, {}).get("cat", "")
        if cat in COOK_STAGES:
            return cat
        return "根茎"  # 兜底

    def _doneness_stage(self, doneness):
        """熟度→感官阶段索引 0-5"""
        if doneness <= 15: return 0
        if doneness <= 30: return 1
        if doneness <= 50: return 2
        if doneness <= 72: return 3
        if doneness <= 85: return 4
        return 5

    def _item_sensory(self, item_name, doneness):
        """某个食材当前感官描述"""
        cat = self._sense_cat(item_name)
        stage_data = COOK_STAGES.get(cat)
        if not stage_data:
            return "在锅里"
        idx = self._doneness_stage(doneness)
        return stage_data["stages"][idx]

    def _progress_doneness(self, ks, step_text):
        """根据火候和时间推进所有食材熟度"""
        if ks["heat"] < 1:
            return []
        observations = []
        # 时间系数
        time_mult = 1.0
        time_match = re.search(r'(\d+)分钟', step_text)
        if time_match:
            minutes = int(time_match.group(1))
            if minutes >= 30:
                time_mult = 3.0
            elif minutes >= 10:
                time_mult = 2.0
            elif minutes >= 5:
                time_mult = 1.5
        # 火候系数——炖煮类不看火候看时间，快炒类才看火候
        simmer_verbs = {"炖", "煮", "煲", "焖", "蒸"}
        is_simmer = any(v in step_text for v in simmer_verbs)
        if is_simmer and time_mult >= 2.0:
            # 慢炖是时间驱动，火候不重要——小火慢炖照样烂
            heat_mult = 1.0
        else:
            heat_mult = {1: 0.5, 2: 1.0, 3: 1.5}.get(ks["heat"], 1.0)
        # 每个食材推进——案板上的不受热
        _seasoning_names = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱"}
        _on_board = ks.get("_on_board", set())
        for name, doneness in ks.get("item_state", {}).items():
            if name in _seasoning_names:
                continue
            if name in _on_board:
                continue  # 案板上的不推
            cat = self._sense_cat(name)
            stage_data = COOK_STAGES.get(cat)
            speed = stage_data["speed"] if stage_data else 10
            old_stage = self._doneness_stage(doneness)
            ks["item_state"][name] = min(100, doneness + speed * heat_mult * time_mult)
            new_stage = self._doneness_stage(ks["item_state"][name])
            # 阶段变化时的观察提示
            if new_stage != old_stage:
                desc = self._item_sensory(name, ks["item_state"][name])
                sweet = stage_data["sweet"] if stage_data else (40, 60)
                d = ks["item_state"][name]
                if new_stage == 3 and d >= sweet[0] and d <= sweet[1]:
                    observations.append(f"✓ {name}：{desc}")
                elif new_stage == 4:
                    observations.append(f"⚠ {name}：{desc}")
                elif new_stage == 5:
                    observations.append(f"⚠ {name}糊了！{desc}")
        return observations

    def _pot_sound(self, ks):
        """锅的声景"""
        has_oil = "油" in ks.get("pot_contents", [])
        has_water = "水" in ks.get("pot_contents", [])
        heat = ks.get("heat", 0)
        pot_temp = ks.get("pot_temp", 0)
        any_burnt = any(d >= 86 for d in ks.get("item_state", {}).values())
        if any_burnt and heat >= 2:
            return POT_SOUNDS["burn"]
        if heat == 0:
            return ""
        if has_water and heat >= 3:
            return POT_SOUNDS["boil"]
        if has_water and heat >= 2:
            return POT_SOUNDS["simmer"]
        if has_oil and heat >= 3:
            return POT_SOUNDS["sizzle"]
        if has_oil and heat >= 2:
            return POT_SOUNDS["hot_oil"]
        if heat >= 2:
            return POT_SOUNDS["warming"]
        return ""

    def _pot_smell(self, ks):
        """锅的气味——与_doneness_stage对齐"""
        states = ks.get("item_state", {})
        if not states:
            return ""
        max_d = max(states.values()) if states else 0
        stage = self._doneness_stage(max_d)
        smell_map = {0: "raw", 1: "starting", 2: "cooking", 3: "done", 4: "over", 5: "burnt"}
        return POT_SMELLS.get(smell_map.get(stage, "raw"), "")

    def _pot_sensory_desc(self, ks):
        """生成锅里感官快照——每步底部显示"""
        if not ks.get("pot_contents"):
            return ""
        lines = []
        _seasoning_names = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱"}
        # 案板食材排除
        _on_board = ks.get("_on_board", set())
        # 每个食材的感官
        for name in ks["pot_contents"]:
            if name in _seasoning_names:
                continue
            if name in _on_board:
                continue  # 案板上的不显示锅里状态
            d = ks.get("item_state", {}).get(name, 0)
            desc = self._item_sensory(name, d)
            lines.append(f"  {name}：{desc}")
        # 案板上的单独显示
        if _on_board:
            for name in _on_board:
                if name in ks["pot_contents"]:
                    lines.append(f"  {name}：在案板上")
        # 水/汤单独写
        if "水" in ks.get("pot_contents", []):
            if ks["heat"] >= 2:
                lines.append("  汤：咕嘟咕嘟")
            else:
                lines.append("  汤：微微冒热气")
        # 火候+声景+气味
        heat_str = {0: "关着", 1: "小火", 2: "中火", 3: "大火"}.get(ks["heat"], "关着")
        env = [f"火：{heat_str}"]
        sound = self._pot_sound(ks)
        if sound:
            env.append(sound)
        smell = self._pot_smell(ks)
        if smell:
            env.append(smell)
        if ks.get("seasoning"):
            env.append(f"调了：{'、'.join(ks['seasoning'])}")
        if ks.get("burned"):
            env.append("⚠ 糊了")
        lines.append("  " + " ｜ ".join(env))
        return "\n".join(lines)

    def _check_kitchen_moment(self, ks, step_text=""):
        """厨房时刻——锅里出了状况，需要你判断。返回提示文字或None"""
        _seasoning = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱"}
        cookable = [n for n in ks.get("pot_contents", []) if n not in _seasoning]

        # 冷却：同一时刻不连续触发
        if "last_moment" in ks and ks["last_moment"]:
            return None

        moment = None

        # 1. 油烟——高温空油，该下菜了
        if ks.get("heat", 0) >= 3 and "油" in ks.get("pot_contents", []):
            if not cookable:
                moment = "油烟大了——油温到了，该下菜了。再等油就烧坏了。"

        # 2. 糖色窗口——加了糖且火开着，颜色在变
        if not moment and "加糖" in ks.get("seasoning", []) and ks.get("heat", 0) >= 2:
            # 肉还没入锅的时候——糖色等肉
            meat_in_pot = any(VEGGIES.get(n, {}).get("cat") == "肉" for n in cookable)
            if not meat_in_pot:
                has_meat = any(VEGGIES.get(item["name"], {}).get("cat") == "肉"
                              for item in list(self.fridge) + list(self.basket))
                if has_meat:
                    moment = "糖色开始冒泡，颜色变深——趁现在下肉？再深就焦了。"

        # 3. 鱼皮——煎鱼到翻面时机（只有入锅受热过的才算）
        if not moment:
            for name, d in ks.get("item_state", {}).items():
                if d > 0 and VEGGIES.get(name, {}).get("cat") == "鱼" and 25 <= d <= 45:
                    moment = f"{name}一面煎得发黄了——翻面？还是再煎一会儿？"
                    break

        # 4. 虾变色——熟得快，容易过
        if not moment:
            for name, d in ks.get("item_state", {}).items():
                if d > 0 and name == "河虾" and 45 <= d <= 60:
                    moment = "虾壳全红了，肉刚好——赶紧出锅？再炒就老了。"
                    break

        # 5. 绿叶菜快过——脆嫩窗口很短（只有入锅受热过的才算）
        if not moment:
            for name, d in ks.get("item_state", {}).items():
                if d > 0 and VEGGIES.get(name, {}).get("cat") == "绿叶" and 25 <= d <= 40:
                    moment = f"{name}碧绿油亮——现在出锅正好？再炒就蔫了。"
                    break

        # 6. 收汁时机——汤少了，肉好了
        if not moment and "水" in ks.get("pot_contents", []):
            any_done = any(d >= 50 for n, d in ks.get("item_state", {}).items() if n not in _seasoning and d > 0)
            if any_done and ks.get("heat", 0) >= 2:
                moment = "汤汁收得差不多了，挂在食材上亮晶晶的——收汁出锅？还是再炖一会儿？"

        # 7. 糊味——有什么东西快糊了
        if not moment:
            for name, d in ks.get("item_state", {}).items():
                if d >= 80 and name not in _seasoning:
                    moment = f"闻到焦味了——{name}快糊了！关小火还是赶紧出锅？"
                    break

        # 设置冷却（下一步后才可能再触发）
        if moment:
            ks["last_moment"] = True
        else:
            ks["last_moment"] = False

        return moment

    def _taste(self):
        """尝一口——模糊但有用的反馈"""
        ks = self.kitchen_state
        if not ks:
            return "还没进厨房呢。"
        if not ks.get("pot_contents"):
            return "锅是空的，没什么可尝的。"

        _seasoning = {"盐", "酱油", "醋", "糖", "料酒", "淀粉", "油", "水", "大葱"}
        cookable = [n for n in ks["pot_contents"] if n not in _seasoning]
        if not cookable:
            return "锅里只有调料和水，没什么可尝的。"

        notes = []

        # 熟度判断
        for name, d in ks.get("item_state", {}).items():
            if name in _seasoning:
                continue
            cat = self._sense_cat(name)
            stage_data = COOK_STAGES.get(cat)
            if not stage_data:
                continue
            sweet_lo, sweet_hi = stage_data["sweet"]
            if d < 20:
                notes.append(f"{name}还生着")
            elif d < sweet_lo:
                notes.append(f"{name}差点火候")
            elif d <= sweet_hi:
                notes.append(f"{name}正好")
            elif d <= 85:
                notes.append(f"{name}有点过了")
            else:
                notes.append(f"{name}糊了")

        # 调味判断
        seasoning_list = ks.get("seasoning", [])
        salt_count = seasoning_list.count("加盐")
        soy_count = seasoning_list.count("加酱油")
        # "调味"通用词也贡献咸味（相当于加了一次盐）
        generic_season = seasoning_list.count("调味")
        total_salty = salt_count + soy_count + generic_season
        if not seasoning_list:
            notes.append("没调味——淡的")
        elif total_salty >= 4:
            notes.append("太咸了")
        elif total_salty >= 3:
            notes.append("有点咸了")
        elif len(seasoning_list) <= 1:
            notes.append("调味单薄")
        elif "加盐" not in seasoning_list and "加酱油" not in seasoning_list:
            notes.append("差点咸味")
        elif "加盐" in seasoning_list and "加酱油" in seasoning_list and "加糖" not in seasoning_list:
            notes.append("咸鲜够了，少点回甘")
        else:
            notes.append("调味还行")

        # 腥味检查
        has_meat = any(VEGGIES.get(n, {}).get("cat") == "肉" for n in cookable)
        has_fish = any(VEGGIES.get(n, {}).get("cat") == "鱼" for n in cookable)
        has_ginger = any(n in ks.get("pot_contents", []) for n in ("姜",))
        has_wine = "加料酒" in seasoning_list
        if (has_meat or has_fish) and not has_ginger and not has_wine:
            notes.append("有腥味——缺姜或料酒")

        return f"尝了一口——{'；'.join(notes)}。"

    def palate_known_count(self):
        """他记住了你几个口味偏好"""
        return (len(self.palate["dislikes"]) + len(self.palate["loves"])
                + len(self.palate["fears"]) + len(self.palate["texture"]))

    def _palate_thought(self, item_name):
        """逛到某样菜时，他想起你的口味——不是标注，是心里一动"""
        p = self.palate
        # 不吃——想起她说的话，犹豫
        if item_name in p["dislikes"]:
            orig = p["dislikes"][item_name]
            return f"……{orig}。算了，不看这个了。"
        # 怕——心疼
        if item_name in p["fears"]:
            orig = p["fears"][item_name]
            return f"她怕这个——{orig}。不买了。"
        # 爱吃——心动，犹豫要不要买
        if item_name in p["loves"]:
            templates = [
                f"她爱吃{item_name}。买不买？",
                f"看到{item_name}就想起她——她上次说想吃。",
                f"她喜欢这个。要不买点回去？",
                f"{item_name}——她眼睛会亮的。",
            ]
            return templates[self.rng() % len(templates)]
        # 口感——替她想着怎么做
        if item_name in p["texture"]:
            pref = p["texture"][item_name]
            return f"她要{pref}的{item_name}——记着别做过了。"
        return None

    def _palate_state_avoid(self, item_name):
        """你告诉过他不想吃的——不是警告，是替你记着"""
        if not self.wife_state:
            return None
        avoid = self._palate_state_data().get("avoid", [])
        if item_name in avoid:
            return f"你说过不想吃{item_name}……跳过吧。"
        return None

    def _palate_state_data(self):
        """当前状态的附加数据"""
        # wife_state 是自由文本，avoid/craving 存档里存着
        return {
            "avoid": getattr(self, '_state_avoid', []),
            "craving": getattr(self, '_state_craving', []),
        }

    def remember_taste(self, category, item, text):
        """记住你的口味偏好——category: dislikes/loves/fears/texture"""
        if category in self.palate and item:
            self.palate[category][item] = text
            self.save()

    def set_state(self, state_text, avoid=None, craving=None):
        """你告诉他你的状态"""
        self.wife_state = state_text
        self._state_avoid = avoid or []
        self._state_craving = craving or []
        self.save()

    def clear_state(self):
        """状态好了，恢复正常"""
        self.wife_state = ""
        self._state_avoid = []
        self._state_craving = []
        self.save()

    def _status_bar(self):
        money_left = round(self.budget - self.spent, 1)
        basket_str = f"{len(self.basket)}样" if self.basket else "空"
        fridge_str = f"{len(self.fridge)}样" if self.fridge else "空"
        time_str = f"⏰{self.market_time}" if not self._market_closed else "⏰散场"
        # 技能等级——显示标签
        dg = self._skill_label("刀工")
        hh = self._skill_label("火候")
        sh = self._skill_label("识货")
        skill_str = ""
        if dg != "生手":
            skill_str += f"🔪{dg}"
        if hh != "怕火":
            skill_str += f"🔥{hh}"
        if sh != "不懂":
            skill_str += f"👀{sh}"
        base = f"💰{money_left}元 | 🛒{basket_str} | 🧊{fridge_str} | {time_str} | {self.season}·{self.weather}"
        if self.savings > 0:
            base += f" | 🐖罐{self.savings}"
        if skill_str:
            base += f" | {skill_str}"
        if self.in_mystic:
            base += " | 🌀"
        return base

    def _fridge_str(self):
        parts = []
        for item in self.fridge:
            parts.append(f"{item['name']}{item.get('qty',1)}")
        return "、".join(parts)

    def _find_stall(self, stall_id):
        if not stall_id:
            return None
        stall = STALL_BY_ID.get(stall_id)
        if stall:
            return stall
        # 模糊匹配：摊主名字或摊位名
        for s in STALLS:
            if stall_id in s["name"] or stall_id in s.get("owner", ""):
                return s
        return None

    def _find_stall_selling(self, item_name):
        """找到卖某样菜的摊（随机选一个）"""
        stall_ids = ITEM_STALL_INDEX.get(item_name, [])
        if not stall_ids:
            return None
        return STALL_BY_ID[stall_ids[self.rng() % len(stall_ids)]]

    def _find_wandering_stall(self, stall_id):
        """找流动摊"""
        for ws in WANDERING_STALLS:
            if ws["id"] == stall_id:
                return ws
        return None

    def _maybe_market_event(self):
        """随机触发菜场小插曲（L1事件+L5新事件）"""
        # 原有事件
        for event_id, event in MARKET_EVENTS.items():
            # 天气限制
            if "weather" in event and self.weather != event["weather"]:
                continue
            if (self.rng() % 100) / 100 < event["chance"]:
                line = event["lines"][self.rng() % len(event["lines"])]
                return f"📰 {line}"

        # L5新动态事件
        for event_id, event in EXTRA_EVENTS.items():
            if "weather" in event and self.weather != event["weather"]:
                continue
            if (self.rng() % 100) / 100 < event["chance"]:
                line = event["lines"][self.rng() % len(event["lines"])]
                # 触发事件效果
                effect = event.get("effect")
                if effect == "no_weight_trick":
                    self.no_weight_trick = True
                elif effect == "neighbor_conflict":
                    # 邻摊冲突——当前摊砍价难度+0.15，但邻摊砍价更容易
                    # 用临时标记，砍价时检查
                    self._neighbor_conflict = True
                elif effect == "quality_degrade" and self.current_stall:
                    # 漏雨——当前摊菜品品质降一级（下次roll时体现）
                    self._roof_leaking = True
                return line  # L5事件不用📰前缀，直接场景化

        return None

    def _check_achievements(self):
        """检查并解锁成就，返回新解锁的成就名或None"""
        checks = {
            "bargain_streak_5": self.stats["bargain_streak"] >= 5,
            "good_buy_streak_3": self.stats["good_buy_streak"] >= 3,
            "unique_dishes_7": len(self.stats["unique_days"]) >= 7 and len(self.stats["unique_dishes"]) >= 7,
            "total_dishes_20": len(self.stats["unique_dishes"]) >= 20,
            "regular_stalls_5": sum(1 for v in self.visit_count.values() if v >= 3) >= 5,
            "visit_all_stalls": len(self.visit_count) >= len(STALLS),
            "bad_buy_streak_3": self.stats["bad_buy_streak"] >= 3,
            "terrible_dishes_5": self.stats["terrible_dishes"] >= 5,
            "bargain_fail_streak_5": self.stats["bargain_fail_streak"] >= 5,
        }
        for ach_id, ach in ACHIEVEMENTS.items():
            if ach_id not in self.achievements:
                check_key = ach["check"]
                if checks.get(check_key, False):
                    self.achievements.append(ach_id)
                    return f"{ach['icon']} {ach_id}——{ach['desc']}"
        return None

    def _check_skill_unlock(self):
        """检查细看技能解锁，返回技能描述或None"""
        ic = self.inspect_counts
        skill_checks = {
            "leaf_sense": ic.get("绿叶", 0) >= 3,
            "root_know": ic.get("根茎", 0) >= 3,
            "fish_eye": ic.get("鱼", 0) >= 3,
            "scale_sense": ic.get("scale", 0) >= 2,
        }
        for skill_id, skill in SKILL_TREE.items():
            if skill_id not in self.unlocked_skills:
                if skill_checks.get(skill_id, False):
                    self.unlocked_skills.append(skill_id)
                    return f"{skill['name']}——{skill['desc']}"
        return None

    def _get_regular_tier(self, stall_id):
        """获取某摊的熟客等级"""
        visits = self.visit_count.get(stall_id, 0)
        tier = 0
        for t, info in sorted(REGULAR_TIERS.items()):
            if visits >= info["min_visits"]:
                tier = t
        return tier

    def _get_affection(self, stall_id):
        """获取某摊主的好感度"""
        return self.affection.get(stall_id, 0)

    def _change_affection(self, stall_id, delta, reason=""):
        """变更是好感度，返回阶段变化提示（或None）

        冷却规则：
        - 每天每个摊主，聊天只涨一次好感（再聊只给闲话）
        - 买东西每次都涨（鼓励光顾）
        - 帮工涨不受限
        - 负面变化不受限
        """
        profile = NPC_PROFILES.get(stall_id)
        if not profile:
            return None
        # 冷却检查：正面聊天/砍价冷却
        if delta > 0 and reason == "chat":
            if not hasattr(self, '_daily_chat_gain'):
                self._daily_chat_gain = set()
            if stall_id in self._daily_chat_gain:
                # 今天已经聊过涨好感了，这次不涨
                return None
            self._daily_chat_gain.add(stall_id)
        old_val = self._get_affection(stall_id)
        old_name, old_key = get_affection_stage(old_val)
        new_val = max(0, min(100, old_val + delta))
        self.affection[stall_id] = new_val
        new_name, new_key = get_affection_stage(new_val)
        if old_name != new_name:
            stall = self._find_stall(stall_id)
            owner = stall["owner"] if stall else stall_id
            if new_val > old_val:
                return f"💕 和{owner}的关系变成了「{new_name}」"
            else:
                return f"💔 和{owner}的关系降到了「{new_name}」"
        return None

    def _add_owner_memory(self, stall_id, mem_type, detail=""):
        """给摊主写入一条跨天记忆。最多保留5条，FIFO。同天同类型不重复。"""
        if not hasattr(self, 'owner_memory'):
            self.owner_memory = {}
        mem_list = self.owner_memory.get(stall_id, [])
        # 去重：同天同类型+细节不重复写
        for m in mem_list:
            if m["day"] == self.day and m["type"] == mem_type and m.get("detail", "") == detail:
                return
        mem_list.append({"day": self.day, "type": mem_type, "detail": detail})
        # 只保留最近5条
        if len(mem_list) > 5:
            mem_list = mem_list[-5:]
        self.owner_memory[stall_id] = mem_list
        # 同步写入关联摊主的记忆（跨摊影响）
        self._add_cross_stall_memory(stall_id, mem_type, detail)

    def _add_cross_stall_memory(self, stall_id, mem_type, detail=""):
        """当玩家对A摊做了某事，有关系B摊也记一笔"""
        cross_types = {"helped", "chose_side"}
        if mem_type not in cross_types:
            return
        for rel in STALL_RELATIONS:
            if rel["a"] == stall_id or rel["b"] == stall_id:
                other_id = rel["b"] if rel["a"] == stall_id else rel["a"]
                relation = rel["relation"]
                cross_type = f"cross_{mem_type}"
                mem_list = self.owner_memory.get(other_id, [])
                # 去重：同天同来源不重复
                dup = any(m["day"] == self.day and m["type"] == cross_type
                          and m.get("from_stall") == stall_id for m in mem_list)
                if dup:
                    continue
                mem_list.append({"day": self.day, "type": cross_type,
                                 "detail": detail, "from_stall": stall_id,
                                 "relation": relation})
                if len(mem_list) > 5:
                    mem_list = mem_list[-5:]
                self.owner_memory[other_id] = mem_list

    def _skill_label(self, skill_name, val=None):
        """获取技能当前等级标签"""
        if val is None:
            val = self.player_skills.get(skill_name, 0)
        info = PLAYER_SKILLS.get(skill_name, {})
        labels = info.get("labels", {})
        best = info.get("labels", {}).get(0, "生手")
        for threshold, label in sorted(labels.items()):
            if val >= threshold:
                best = label
        return best

    def _grow_skill(self, skill_name, amount=1):
        """涨技能，返回升级提示（或None）"""
        if not hasattr(self, 'player_skills'):
            self.player_skills = {"刀工": 0, "火候": 0, "识货": 0}
        old = self.player_skills.get(skill_name, 0)
        if old >= 100:
            return None
        old_label = self._skill_label(skill_name, old)
        new = min(100, old + amount)
        self.player_skills[skill_name] = new
        new_label = self._skill_label(skill_name, new)
        if new_label != old_label:
            return f"⬆ {skill_name}升级：{old_label}→{new_label}（{new}）"
        return None

    def _burn_threshold(self):
        """烧焦阈值——火候越高越不容易糊"""
        base = 85
        huohou = self.player_skills.get("火候", 0)
        if huohou >= 75:
            base += 20
        elif huohou >= 50:
            base += 15
        elif huohou >= 25:
            base += 10
        elif huohou >= 10:
            base += 5
        return base

    def _auto_cut_chance(self):
        """刀工自动切菜概率"""
        daogong = self.player_skills.get("刀工", 0)
        if daogong >= 75:
            return 0.90
        elif daogong >= 50:
            return 0.50
        elif daogong >= 25:
            return 0.25
        elif daogong >= 10:
            return 0.10
        return 0

    def _get_memory_recall(self, stall_id):
        """聊天时摊主回忆起以前的事——不生硬，自然插入。
        返回回忆文案列表（0-2条），由调用方决定怎么融入对话。"""
        if not hasattr(self, 'owner_memory'):
            return []
        mem_list = self.owner_memory.get(stall_id, [])
        if not mem_list:
            return []
        stall = self._find_stall(stall_id)
        owner = stall["owner"] if stall else stall_id
        recalls = []
        # 最近2条记忆有概率被提起
        recent = mem_list[-2:] if len(mem_list) >= 2 else mem_list[:]
        for mem in recent:
            # 越久远的事越不容易提起
            days_ago = self.day - mem.get("day", self.day)
            if days_ago > 7:
                continue
            # 概率：最近的高，远的低
            chance = max(0.1, 0.5 - days_ago * 0.08)
            if (self.rng() % 100) / 100 > chance:
                continue
            mem_type = mem["type"]
            detail = mem.get("detail", "")
            # 跨摊记忆用特殊模板
            if mem_type.startswith("cross_"):
                recall = self._format_cross_memory(stall_id, mem)
                if recall:
                    recalls.append(recall)
                continue
            templates = OWNER_MEMORY_TEMPLATES.get(mem_type, [])
            if not templates:
                continue
            template = templates[self.rng() % len(templates)]
            recall = template.format(owner=owner, detail=detail)
            recalls.append(recall)
        return recalls[:2]

    def _format_cross_memory(self, stall_id, mem):
        """格式化跨摊记忆——B摊提起A摊发生的事"""
        stall = self._find_stall(stall_id)
        owner = stall["owner"] if stall else stall_id
        from_stall_id = mem.get("from_stall", "")
        from_stall = self._find_stall(from_stall_id)
        other_owner = from_stall["owner"] if from_stall else from_stall_id
        relation = mem.get("relation", "")
        orig_type = mem["type"].replace("cross_", "")
        relation_templates = CROSS_STALL_MEMORY_TEMPLATES.get(relation, {})
        templates = relation_templates.get(orig_type, [])
        if not templates:
            return None
        template = templates[self.rng() % len(templates)]
        return template.format(owner=owner, other_owner=other_owner)

    def _stall_season_items(self, stall):
        """某摊当季可买的菜"""
        result = []
        sells = stall["sells"]
        # wander_seasonal的sells是{季节: [菜品]} dict
        if isinstance(sells, dict):
            season_items = sells.get(self.season, [])
            for vname in season_items:
                if vname in VEGGIES:
                    result.append(vname)
        else:
            for vname in sells:
                v = VEGGIES[vname]
                status = v["season"].get(self.season, "no")
                if status != "no":
                    result.append(vname)
        return result

    def _calc_price(self, item_name, v):
        """计算实际价格（季节+天气+时段+跨摊关系影响）"""
        base_lo, base_hi = v["price"]
        price = base_lo + (self.rng() % max(1, int((base_hi - base_lo) * 10))) / 10

        season_status = v["season"].get(self.season, "no")
        if season_status == "in":
            price *= 0.8  # 当季便宜
        elif season_status == "ok":
            price *= 1.2  # 非当季贵一点

        # 雨天加价统一走_weather_price_mod，不在_calc_price重复加

        # 散市便宜
        tod = TIME_OF_DAY.get(self.time_of_day, {})
        price_mod = tod.get("price_mod", 1.0)
        if price_mod != 1.0:
            price *= price_mod

        # 跨摊关系价格修正——根据当前摊主的记忆调整
        stall_id = self.current_stall or ""
        if stall_id and hasattr(self, 'owner_memory'):
            for mem in self.owner_memory.get(stall_id, []):
                if not mem["type"].startswith("cross_"):
                    continue
                relation = mem.get("relation", "")
                days_ago = self.day - mem.get("day", self.day)
                if days_ago > 5:
                    continue  # 太久了，影响消退
                decay = max(0.3, 1.0 - days_ago * 0.14)  # 衰减
                if relation in ("不对付", "竞争"):
                    # 你帮了对头，涨价
                    price *= 1.0 + 0.05 * decay  # 最多+5%
                elif relation in ("熟人", "亲戚", "邻居"):
                    # 你帮了朋友，打折
                    price *= 1.0 - 0.05 * decay  # 最多-5%

        # 天灾人祸——全局价格修正
        if hasattr(self, '_disaster_price_mod') and self._disaster_price_mod != 1.0:
            price *= self._disaster_price_mod

        # 节气——全局价格修正
        if hasattr(self, '_solar_price_mod_all'):
            price *= self._solar_price_mod_all
        # 节气——特定摊主价格修正
        if hasattr(self, '_solar_price_mod') and stall_id in self._solar_price_mod:
            price *= self._solar_price_mod[stall_id]

        # 连续剧情——当日价格修正
        stall_id = self.current_stall or ""
        if stall_id and hasattr(self, '_storyline_effects') and stall_id in self._storyline_effects:
            sl_pm = self._storyline_effects[stall_id].get("price_mod", 1.0)
            if sl_pm != 1.0:
                price *= sl_pm

        # 好感度价格修正——有仇涨价，老友额外便宜
        stall_id = self.current_stall or ""
        if stall_id:
            aff = self._get_affection(stall_id)
            if aff >= 70:
                price *= 0.92  # 老友价
            elif aff >= 50:
                price *= 0.96  # 熟人价
            elif aff < 10 and self.visit_count.get(stall_id, 0) >= 2:
                price *= 1.10  # 有仇涨价

        return round(price, 1)

    def _calc_quality(self, item_name, v):
        """roll品质——五档：great/good/ok/bad/trap（用预计算权重表）"""
        r = (self.rng() % 100) / 100
        is_in = v["season"].get(self.season, "no") == "in"
        weights = list(QUALITY_WEIGHT_TABLE.get((self.season, self.weather, self.time_of_day, is_in),
                                           [0.10, 0.20, 0.30, 0.25, 0.15]))
        # 天灾人祸——品质偏移
        if hasattr(self, '_disaster_quality_mod') and self._disaster_quality_mod != 0:
            mod = self._disaster_quality_mod  # +1=品质升一级，-1=降一级
            if mod > 0:
                # 好货到：把权重往左移（更好）
                for i in range(mod):
                    weights[0] += 0.05
                    weights[1] += 0.05
                    weights[3] -= 0.05
                    weights[4] -= 0.05
            elif mod < 0:
                # 节前抢购：好货被抢，品质降
                for i in range(abs(mod)):
                    weights[0] -= 0.05
                    weights[1] -= 0.05
                    weights[3] += 0.05
                    weights[4] += 0.05
            # 确保权重非负
            weights = [max(0, w) for w in weights]
        # 连续剧情——当日品质偏移
        stall_id = self.current_stall or ""
        if stall_id and hasattr(self, '_storyline_effects') and stall_id in self._storyline_effects:
            sl_qm = self._storyline_effects[stall_id].get("quality_mod", 0)
            if sl_qm != 0:
                if sl_qm > 0:
                    for i in range(sl_qm):
                        weights[0] += 0.05
                        weights[1] += 0.05
                        weights[3] -= 0.05
                        weights[4] -= 0.05
                elif sl_qm < 0:
                    for i in range(abs(sl_qm)):
                        weights[0] -= 0.05
                        weights[1] -= 0.05
                        weights[3] += 0.05
                        weights[4] += 0.05
                weights = [max(0, w) for w in weights]
        # 节气——全局品质偏移
        if hasattr(self, '_solar_quality_mod') and self._solar_quality_mod != 0:
            sqm = self._solar_quality_mod
            if sqm > 0:
                for i in range(sqm):
                    weights[0] += 0.05
                    weights[1] += 0.05
                    weights[3] -= 0.05
                    weights[4] -= 0.05
            elif sqm < 0:
                for i in range(abs(sqm)):
                    weights[0] -= 0.05
                    weights[1] -= 0.05
                    weights[3] += 0.05
                    weights[4] += 0.05
            weights = [max(0, w) for w in weights]
        # 节气——特定类别品质提升
        if hasattr(self, '_solar_quality_boost'):
            cat = v.get("cat", "")
            boost = self._solar_quality_boost.get(cat, 0)
            if boost > 0:
                for i in range(boost):
                    weights[0] += 0.08
                    weights[1] += 0.07
                    weights[3] -= 0.08
                    weights[4] -= 0.07
                weights = [max(0, w) for w in weights]
        # 好感度品质偏移——熟人给你留好的，生人/有仇的给你差的
        stall_id = self.current_stall or ""
        if stall_id:
            aff = self._get_affection(stall_id)
            if aff >= 70:
                # 老友：往好了偏
                weights[0] += 0.08
                weights[1] += 0.07
                weights[3] -= 0.08
                weights[4] -= 0.07
            elif aff >= 50:
                # 熟人：略好
                weights[0] += 0.04
                weights[1] += 0.03
                weights[3] -= 0.04
                weights[4] -= 0.03
            elif aff < 10 and self.visit_count.get(stall_id, 0) >= 2:
                # 来过但不涨好感——有仇（可能砍价太狠或退过货）
                weights[0] -= 0.05
                weights[1] -= 0.05
                weights[3] += 0.05
                weights[4] += 0.05
            weights = [max(0, w) for w in weights]
        # 权重全零时回退到默认
        if sum(weights) <= 0:
            weights = [0.1, 0.3, 0.4, 0.15, 0.05]
        # 累积判定
        cumul = 0
        for i, w in enumerate(weights):
            cumul += w
            if r < cumul:
                return ["great", "good", "ok", "bad", "trap"][i]
        return "ok"

    def _peek_quality(self, item_name, v):
        """L4细看时预览品质——不影响主rng序列，用独立seed"""
        peek_seed = (hash(item_name) + self.day + self.seed) & 0xFFFFFFFF
        peek_rng = mulberry32(peek_seed)
        r = (peek_rng() % 100) / 100
        is_in = v["season"].get(self.season, "no") == "in"
        weights = QUALITY_WEIGHT_TABLE.get((self.season, self.weather, self.time_of_day, is_in),
                                           [0.10, 0.20, 0.30, 0.25, 0.15])
        cumul = 0
        for i, w in enumerate(weights):
            cumul += w
            if r < cumul:
                return ["great", "good", "ok", "bad", "trap"][i]
        return "ok"

    def _cat_emoji(self, stall):
        cats = {"绿叶": "🥬", "根茎": "🥕", "瓜果": "🍅", "豆类": "🫘",
                "菌菇": "🍄", "豆制品": "🧈", "肉": "🥩", "鱼": "🐟",
                "蛋": "🥚", "调味": "🧄"}
        # 用摊卖的第一个菜的类别
        sells = stall.get("sells", [])
        sells_list = sells if isinstance(sells, list) else []
        for vname in sells_list:
            if vname in VEGGIES:
                return cats.get(VEGGIES[vname]["cat"], "🏪")
        # dict类型的sells（流动摊）——用季节对应的列表
        if isinstance(sells, dict):
            for season_items in sells.values():
                for vname in season_items:
                    if vname in VEGGIES:
                        return cats.get(VEGGIES[vname]["cat"], "🏪")
        return "🏪"

    def _owner_buy_reaction(self, stall, item_name, is_regular):
        personality = stall.get("personality", "实在")
        owner = stall.get("owner", "摊主")
        if is_regular:
            return ["拿好！", "给你挑了个好的。", "这新鲜着呢，放心。"][self.rng() % 3]
        # 买反应——按性格说不同的话，不是砍价台词
        buy_reactions = {
            "爽快": [f"拿好！{item_name}不错。", "行，给你装上。", f"这个{item_name}好，你眼光行。"],
            "死硬": [f"嗯，{item_name}。", "好。", f"{item_name}，行。"],
            "算计": [f"{item_name}好眼光。", "这个不错。", f"你看看{item_name}，值这个价。"],
            "话唠": [f"这个{item_name}今早刚到的！你看看多好。", f"哎你买了{item_name}，回去怎么做？", f"{item_name}好，我跟你说这个今天刚上的。"],
            "实在": [f"{item_name}，拿好。", f"这个还行，你看看。", f"嗯，{item_name}。"],
        }
        pool = buy_reactions.get(personality, buy_reactions["实在"])
        return pool[self.rng() % len(pool)]

    def _pot_description(self):
        ks = self.kitchen_state
        # 感官快照版——每步底部显示
        desc = self._pot_sensory_desc(ks)
        if desc:
            return "\n" + desc
        return ""

    def _appearance_desc(self, dish_name, appearance, ks):
        """生成品相描述——写出端上桌的画面"""
        # 根据锅里内容选细节词
        pot = set(ks.get("pot_contents", []))
        _fish_names = {"鲫鱼", "草鱼", "鲈鱼", "带鱼", "黄花鱼", "黄鳝"}
        _shrimp_names = {"河虾"}
        has_fish = any(n in _fish_names for n in pot)
        has_shrimp = any(n in _shrimp_names for n in pot)
        has_meat = any(VEGGIES.get(n, {}).get("cat") == "肉" for n in pot)
        has_veg = any(VEGGIES.get(n, {}).get("cat") in ("绿叶", "瓜果", "豆类") for n in pot)
        has_tofu = any("豆腐" in n for n in pot)
        burned = ks.get("burned", False)

        templates = {
            "great": [
                (
                    f"锅盖一掀，热气扑面。{dish_name}盛在白瓷盘里，油光发亮，"
                    + ("虾壳红亮，虾身弯成弓，一碰就弹，鲜甜味直往鼻子里钻。"
                       if has_shrimp else
                       "鱼身完整，两面煎得金黄，汤汁奶白浓稠，漂着细碎的葱花和姜片，鲜香直往鼻子里钻。"
                       if has_fish else
                       "肉切得齐整，酱色均匀裹着每一块，汁水收得刚刚好，亮晶晶的，筷子一碰就微微颤。"
                       if has_meat else
                       "菜色鲜亮，绿是绿白是白，汁水清亮，闻着就是家里灶台上的味道。")
                ),
                (
                    f"端上桌的时候还冒着白气。{dish_name}"
                    + ("，虾壳脆脆的，肉紧实弹牙，一咬鲜汁冒出来，盘底一点蒜蓉油，鲜得停不下来。"
                       if has_shrimp else
                       "，鱼皮焦脆没破，肉嫩得用筷子一拨就散，汤面上浮着一层细油花，鲜得眉毛要掉。"
                       if has_fish else
                       "，每块都裹着亮晶晶的酱汁，肉烂但不散，筷子夹起来还挂着汁，香味飘了满屋。"
                       if has_meat else
                       "，颜色正，火候到家，看着就下饭。")
                ),
            ],
            "good": [
                (
                    f"{dish_name}端上来了。"
                    + ("虾壳泛红，肉还算弹，味道鲜，就是火候差一点，再快十秒出锅更好。"
                       if has_shrimp else
                       "鱼还算完整，汤色偏白，喝一口，鲜是鲜的，就是差那么点意思。"
                       if has_fish else
                       "肉炖到位了，筷子能戳透，酱色偏深但不糊，味道还行。"
                       if has_meat else
                       "颜色正常，味道过得去，不惊艳但也不丢人。")
                ),
                (
                    f"盘子里的{dish_name}"
                    + ("，虾红是红了，个头小了点，但吃着还行。"
                       if has_shrimp else
                       "，鱼没煎破，算是不容易。汤有点淡，但鱼肉是嫩的。"
                       if has_fish else
                       "，卖相中规中矩，吃着比看着好。"
                       if has_meat else
                       "，不算出彩，但能吃出用心了。")
                ),
            ],
            "ok": [
                (
                    f"{dish_name}……凑合吧。"
                    + ("虾肉有点老，壳发白没红透，嚼着发柴，调味也一般。"
                       if has_shrimp else
                       "鱼尾巴断了，汤色发灰，喝着有股子腥味没压住。"
                       if has_fish else
                       "肉有点老，颜色太深了，像是酱油放多了。"
                       if has_meat else
                       "颜色发暗，有点咸，不太想夹第二筷子。")
                ),
                (
                    f"看着不太行。{dish_name}"
                    + ("虾缩成一小团，壳软塌塌的，没什么食欲。"
                       if has_shrimp else
                       "鱼皮碎了，汤浑浊，有点不伦不类。"
                       if has_fish else
                       "，卖相一般，味道也就那样。")
                ),
            ],
            "bad": [
                (
                    f"盘子里的{dish_name}……"
                    + ("虾壳焦黑卷曲，肉缩成一小粒，嚼着又硬又苦。"
                       if has_shrimp else
                       "鱼煎糊了一面，另一面还带着生色，汤上飘着黑渣子，闻着有点焦。"
                       if has_fish else
                       "肉又老又柴，外面糊了里面还没入味，黑乎乎的一坨。"
                       if has_meat else
                       "菜叶子发黄发蔫，汤汁浑浊，看着就没食欲。")
                ),
                (
                    f"{dish_name}端上来，没人想动筷子。"
                    + ("虾都糊了，黑乎乎的一坨，剥不开壳。"
                       if has_shrimp else
                       "鱼眼睛都浑了，汤面飘着油沫子。"
                       if has_fish else
                       "颜色黑黢黢的，夹一块，嚼不动。"
                       if has_meat else
                       "卖相很惨，像是随便煮了煮就端上来了。")
                ),
            ],
            "terrible": [
                (
                    f"锅盖掀开——一股糊味。{dish_name}"
                    + ("虾全焦了，壳和肉粘在一起，掰开里面还是黑的，苦得没法吃。"
                       if has_shrimp else
                       "鱼煎成了黑炭，汤是黑的，筷子戳下去鱼骨都酥了，已经分不清哪是肉哪是渣。"
                       if has_fish else
                       "糊了一半，另一半还带着血丝。锅底粘着一层黑痂。"
                       if has_meat else
                       "一锅糊东西，菜烂成了泥，汤成了浆糊，分不清原来是什么。")
                ),
                (
                    f"不忍直视。{dish_name}"
                    + ("虾化成了一滩黑渣，混着焦壳，味都串了。"
                       if has_shrimp else
                       "鱼都散了，骨头渣子混在黑汤里，屋子里一股焦味。"
                       if has_fish else
                       "……糊的糊、生的生，不成样子。"
                       if has_meat else
                       "看着像事故现场。")
                ),
            ],
        }
        pool = templates.get(appearance, templates["ok"])
        return pool[self.rng() % len(pool)]

    def _achievements_detail(self):
        lines = []
        lines.append("── 成就 ──")
        if not self.achievements:
            lines.append("还没解锁任何成就。继续买菜做饭吧。")
        else:
            for ach_id in self.achievements:
                ach = ACHIEVEMENTS[ach_id]
                lines.append(f"  {ach['icon']} {ach_id}——{ach['desc']}")
        lines.append("")
        lines.append(f"已解锁 {len(self.achievements)}/{len(ACHIEVEMENTS)}")
        return "\n".join(lines)

    def _cookbook_detail(self):
        lines = []
        lines.append("── 菜谱册 ──")
        if not self.cook_history:
            lines.append("还没做过菜。")
        else:
            for dish, count in self.cook_history.items():
                times = f"做过{count}次"
                if count >= 5:
                    times += " ★拿手菜"
                elif count >= 3:
                    times += " ✓熟练"
                lines.append(f"  {dish} · {times}")
        lines.append("")
        lines.append(f"共 {len(self.cook_history)} 道")
        return "\n".join(lines)

    def _stall_guide_detail(self):
        lines = []
        lines.append("── 熟客图鉴 ──")
        for s in STALLS:
            vc = self.visit_count.get(s["id"], 0)
            aff = self._get_affection(s["id"])
            stage_name, _ = get_affection_stage(aff)
            # 性格特质
            traits = OWNER_TRAITS.get(s["id"], {}).get("traits", [])
            trait_str = f" [{','.join(traits)}]" if traits and aff >= 30 else ""
            if vc >= 3:
                level = "老主顾 ★"
            elif vc >= 1:
                level = "眼熟"
            else:
                level = "生脸"
            aff_str = f" · 好感{int(aff)}({stage_name})" if aff > 0 else ""
            lines.append(f"  {s['name']}（{s['owner']}）· {level}{trait_str}{aff_str} · 来过{vc}次")
        regular_count = sum(1 for v in self.visit_count.values() if v >= 3)
        visited_count = len(self.visit_count)
        # 故事进度
        total_beats = sum(len(b) for b in STORY_BEATS.values())
        found_beats = len(self.story_progress)
        lines.append("")
        lines.append(f"逛过 {visited_count}/{len(STALLS)} 摊 · 熟客 {regular_count} 家 · 故事 {found_beats}/{total_beats}")
        return "\n".join(lines)

    def _skills_detail(self):
        lines = []
        lines.append("── 挑菜技能 ──")
        if not self.unlocked_skills:
            lines.append("还没解锁技能。多「细看」菜和秤来积累经验。")
        else:
            for sid in self.unlocked_skills:
                sk = SKILL_TREE[sid]
                lines.append(f"  ✅ {sk['name']}（{sk['level']}）——{sk['desc']}")
        lines.append("")
        lines.append("── 细看进度 ──")
        for cat, count in self.inspect_counts.items():
            if cat == "scale":
                lines.append(f"  秤：细看过{count}次")
            elif count > 0:
                lines.append(f"  {cat}：细看过{count}次")
        lines.append("")
        lines.append(f"已解锁 {len(self.unlocked_skills)}/{len(SKILL_TREE)}")
        return "\n".join(lines)

    def _maybe_stall_interaction(self, stall_id):
        """摊主间互动——从关系+心情+天气动态生成，不是固定剧本"""
        # 找跟当前摊主有关系的摊
        related = []
        for rel in STALL_RELATIONS:
            if rel["a"] == stall_id:
                related.append((rel["b"], rel["relation"]))
            elif rel["b"] == stall_id:
                related.append((rel["a"], rel["relation"]))
        if not related:
            return None

        # 概率——每个关系有15%触发
        if (self.rng() % 100) / 100 > 0.15:
            return None

        # 随机选一个关系
        other_id, relation = related[self.rng() % len(related)]
        stall = self._find_stall(stall_id)
        other = self._find_stall(other_id)
        if not stall or not other:
            return None

        owner = stall["owner"]
        other_owner = other["owner"]
        my_mood = getattr(self, '_owner_daily', {}).get(stall_id, "normal")
        other_mood = getattr(self, '_owner_daily', {}).get(other_id, "normal")

        # 根据关系类型+心情动态拼场景
        scene = self._generate_interaction_scene(owner, other_owner, relation, my_mood, other_mood, stall_id, other_id)
        if not scene:
            return None

        self._pending_interaction = scene
        lines = [f"👀 {scene['desc']}"]
        choices = scene.get("choices", {})
        if choices:
            lines.append("")
            for key, choice in choices.items():
                lines.append(f"  {key}. {choice['label']}")
        return "\n".join(lines)

    def _generate_interaction_scene(self, owner, other_owner, relation, my_mood, other_mood, stall_id, other_id):
        """从关系+心情动态生成互动场景和选项"""
        # ── 不对付 ──
        if relation == "不对付":
            if my_mood == "bad" and other_mood == "bad":
                return {
                    "desc": f"{owner}和{other_owner}又在吵。今天两个人都上了火，谁也不让谁。旁边的人都在看。",
                    "choices": {
                        "1": {"label": f"帮{owner}", "text": f"你站了{owner}这边。{other_owner}冷笑一声扭头走了。",
                             "effect": {"affection": {stall_id: 3, other_id: -5}}},
                        "2": {"label": f"帮{other_owner}", "text": f"你替{other_owner}说了句话。{owner}看了你一眼，没说话，但脸色变了。",
                             "effect": {"affection": {stall_id: -4, other_id: 4}}},
                        "3": {"label": "走开", "text": "不想掺和。你绕过去了。",
                             "effect": {}},
                    }
                }
            elif my_mood == "good" or other_mood == "good":
                return {
                    "desc": f"{owner}今天心情不错，路过{other_owner}摊位的时候居然点了下头。{other_owner}愣了一下，也点了点头。",
                    "choices": {
                        "1": {"label": "打个圆场", "text": f"你笑着说：关系不错嘛。{owner}：得了吧。{other_owner}：谁跟他不错。但两个人都没真生气。",
                             "effect": {"affection": {stall_id: 2, other_id: 2}}},
                        "2": {"label": "不多嘴", "text": "你假装没看见。难得的和平。",
                             "effect": {}},
                    }
                }
            else:
                return {
                    "desc": f"{owner}在骂{other_owner}：又把烂叶子往过道堆！{other_owner}不吱声，但手上的动作重了不少。",
                    "choices": {
                        "1": {"label": f"劝{owner}消消气", "text": f"你说了句算了。{owner}：我就是看不惯。但声音小了点。",
                             "effect": {"affection": {stall_id: 1, other_id: 2}}},
                        "2": {"label": "不管", "text": "你挑你的菜，让他们吵去。",
                             "effect": {}},
                    }
                }

        # ── 竞争 ──
        elif relation == "竞争":
            if my_mood == "bad":
                return {
                    "desc": f"{owner}今天生意不好，看着{other_owner}那排着的人，脸色发沉。",
                    "choices": {
                        "1": {"label": f"在{owner}这买", "text": f"你特意在{owner}这买了东西。{owner}：谢了。声音低低的。",
                             "effect": {"affection": {stall_id: 4, other_id: -1}}},
                        "2": {"label": "两边都买", "text": f"你两边各买了点。{owner}没说什么，但{other_owner}多看了你一眼。",
                             "effect": {"affection": {stall_id: 1, other_id: 1}}},
                    }
                }
            else:
                return {
                    "desc": f"{owner}和{other_owner}在比谁今天的货好。{owner}：你看我这个。{other_owner}：我这个也不差。",
                    "choices": {
                        "1": {"label": f"说{owner}的好", "text": f"你夸了{owner}的。{other_owner}哼了一声：你眼光一般。",
                             "effect": {"affection": {stall_id: 3, other_id: -2}}},
                        "2": {"label": f"说{other_owner}的好", "text": f"你指了{other_owner}的。{owner}撇嘴：行，你买他吧。",
                             "effect": {"affection": {stall_id: -2, other_id: 3}}},
                        "3": {"label": "都不错", "text": "你两边都夸了。两个人都不太满意，但也没生气。",
                             "effect": {"affection": {stall_id: 1, other_id: 1}}},
                    }
                }

        # ── 熟人/邻居/亲戚 ──
        else:
            if self.weather == "雨":
                return {
                    "desc": f"下雨天，{owner}和{other_owner}挤在同一个雨棚底下。{owner}：今天真冷。{other_owner}：我那有杯热水。",
                    "choices": {
                        "1": {"label": "凑过去", "text": f"你也挤了过去。三个人躲雨，谁也没说话，但没觉得尴尬。",
                             "effect": {"affection": {stall_id: 2, other_id: 2}}},
                        "2": {"label": "继续逛", "text": "你打着伞走了。后面传来他们聊天声。",
                             "effect": {}},
                    }
                }
            elif other_mood == "unwell":
                return {
                    "desc": f"{other_owner}今天不太舒服，{owner}在帮{other_owner}看着摊。{owner}：你歇着，我盯着。",
                    "choices": {
                        "1": {"label": "也帮一把", "text": f"你帮着理了理{other_owner}的菜。{owner}冲你点了点头。{other_owner}：谢谢啊。",
                             "effect": {"affection": {stall_id: 2, other_id: 4}}},
                        "2": {"label": "买点东西就走", "text": f"你买了点东西没多留。{owner}忙着看两个摊，顾不上你。",
                             "effect": {"affection": {stall_id: 1}}},
                    }
                }
            else:
                # 闲聊场景
                chats = [
                    (f"{owner}和{other_owner}在聊天。{owner}：你家孩子今年多大？{other_owner}：上初中了，费心。",
                     {"1": {"label": "听听", "text": "你站了一会儿，听他们聊了两句家常。挺像正常邻居的。",
                            "effect": {"affection": {stall_id: 1, other_id: 1}}}}),
                    (f"{other_owner}递给{owner}一个苹果：尝尝，今天新到的。{owner}接过去咬了一口：还行。",
                     {"1": {"label": "也想要一个", "text": f"{other_owner}看了看你：你要买就买，送不起两个。{owner}笑了。",
                            "effect": {"affection": {stall_id: 1, other_id: 1}}}}),
                    (f"{owner}跟{other_owner}在说市场后面要开超市的事。{other_owner}：开了再说，急什么。",
                     {"1": {"label": "也听听", "text": "你又听说了超市的事。不知道真假。",
                            "effect": {"affection": {stall_id: 1, other_id: 1}, "set_flag": "supermarket_rumor"}}}),
                ]
                chosen = chats[self.rng() % len(chats)]
                return {"desc": chosen[0], "choices": chosen[1]}

        return None

    def _resolve_interaction(self, choice_key):
        """处理摊主互动的选择"""
        inter = getattr(self, '_pending_interaction', None)
        if not inter:
            return "没什么要回应的。"
        self._pending_interaction = None
        choices = inter.get("choices", {})
        if choice_key not in choices:
            opts = '、'.join(f'{k}.{c["label"]}' for k, c in choices.items())
            return f"没有这个选项。可选：{opts}"
        chosen = choices[choice_key]
        # 应用效果
        effect = chosen.get("effect", {})
        if "affection" in effect:
            for sid, delta in effect["affection"].items():
                old = self._get_affection(sid)
                self.affection[sid] = max(0, min(100, old + delta))
                if delta != 0:
                    mem_type = "chose_side" if delta > 0 else "chose_other"
                    self._add_owner_memory(sid, mem_type, inter.get("id", ""))
        if "set_flag" in effect:
            self.chain_flags.add(effect["set_flag"])
        return chosen["text"]

    def _maybe_story_beat(self, stall_id):
        """检查有没有该触发的故事碎片——像真实偶遇，不是剧情播片"""
        for story_id, beats in STORY_BEATS.items():
            for beat in beats:
                # 已触发的跳过
                if beat["id"] in self.story_progress:
                    continue
                # 触发条件
                trigger = beat.get("trigger", {})
                if self.day < trigger.get("min_day", 0):
                    continue
                # 摊位匹配
                beat_stall = beat.get("stall")
                is_right_stall = (beat_stall == stall_id or not beat_stall)
                if is_right_stall:
                    # 在对的摊位——正常概率
                    chance = beat.get("chance", 0.3)
                else:
                    # 道听途说——在别的摊也可能听到，但概率大幅降低
                    # 且需要该摊好感>=20（熟人才会跟你八卦）
                    if self._get_affection(stall_id) < 20:
                        continue
                    chance = beat.get("chance", 0.3) * 0.15  # 15%的原概率
                # 前几天加成——前3天故事触发率翻倍，让开局不冷
                if self.day <= 3:
                    chance = min(1.0, chance * 2.0)
                if self._get_affection(stall_id) < trigger.get("min_affection", 0):
                    continue
                # 概率roll
                if (self.rng() % 100) / 100 < chance:
                    self.story_progress.append(beat["id"])
                    # 道听途说加个前缀
                    if not is_right_stall:
                        return f"听说了点事——{beat['text']}"
                    return beat["text"]
        return None

    # ---- RPG系统：选择链 · 声望 · 线索 · 结局 ----

    def _mod_reputation(self, dim, delta):
        """修改声望（clamp -50~50）"""
        if dim in self.reputation:
            self.reputation[dim] = max(-50, min(50, self.reputation[dim] + delta))

    def _apply_choice_effect(self, effect, source_stall=None):
        """应用选择链的效果"""
        if not effect:
            return
        if "reputation" in effect:
            for dim, delta in effect["reputation"].items():
                self._mod_reputation(dim, delta)
        if "affection" in effect:
            for sid, delta in effect["affection"].items():
                old = self.affection.get(sid, 0)
                self.affection[sid] = max(0, min(100, old + delta))
                # 记忆——选了某边的摊主记住
                if source_stall and delta != 0:
                    mem_type = "chose_side" if delta > 0 else "chose_other"
                    self._add_owner_memory(sid, mem_type, f"好感{delta:+d}")
        if "set_flag" in effect:
            self.chain_flags.add(effect["set_flag"])

    def _check_choice_chains(self, stall_id):
        """检查选择链是否有步骤该触发"""
        results = []
        for chain_id, chain in CHOICE_CHAINS.items():
            for step in chain["steps"]:
                # 已触发跳过
                if step["id"] in self.chain_done:
                    continue
                # 摊位匹配
                trigger = step.get("trigger", {})
                step_stall = trigger.get("stall")
                if step_stall and step_stall != stall_id:
                    continue
                # 天数
                if self.day < trigger.get("min_day", 0):
                    continue
                # 好感
                if trigger.get("min_affection", 0) > 0:
                    if self._get_affection(stall_id) < trigger["min_affection"]:
                        continue
                # flag条件
                req_flag = step.get("require_flag")
                if req_flag:
                    if req_flag.startswith("!"):
                        # 取反：flag不能存在
                        if req_flag[1:] in self.chain_flags:
                            continue
                    else:
                        if req_flag not in self.chain_flags:
                            continue
                # 概率roll
                if (self.rng() % 100) / 100 < step.get("chance", 0.3):
                    self.chain_done.add(step["id"])
                    results.append(step)
        return results

    def _maybe_find_clue(self, stall_id, context="visit"):
        """检查是否发现线索碎片"""
        found = []
        for clue in CLUE_FRAGMENTS:
            if clue["id"] in self.found_clues:
                continue
            if clue["stall"] != stall_id:
                continue
            if clue.get("found_when") and clue["found_when"] != context:
                continue
            if clue.get("min_affection", 0) > 0:
                if self._get_affection(stall_id) < clue["min_affection"]:
                    continue
            if self.day < clue.get("min_day", 0):
                continue
            # 20%概率发现
            if (self.rng() % 100) / 100 < 0.20:
                self.found_clues.add(clue["id"])
                found.append(clue)
        # 检查线索组合
        for combo in CLUE_COMBOS:
            if combo["id"] in self.unlocked_combos:
                continue
            if all(c in self.found_clues for c in combo["clues"]):
                self.unlocked_combos.add(combo["id"])
                found.append({"id": combo["id"], "name": combo["name"], "desc": combo["desc"], "is_combo": True})
        return found

    def _determine_ending(self):
        """根据声望+flag+线索判定结局"""
        # 按优先级从高到低检查
        candidates = sorted(ENDINGS, key=lambda e: e.get("priority", 0), reverse=True)
        for ending in candidates:
            cond = ending.get("condition")
            if cond is None:
                # 兜底结局
                self.ending = ending["id"]
                return ending
            ok = True
            # 声望条件
            if "min_reputation" in cond:
                for dim, val in cond["min_reputation"].items():
                    if self.reputation.get(dim, 0) < val:
                        ok = False
                        break
            if "max_reputation" in cond:
                for dim, val in cond["max_reputation"].items():
                    if self.reputation.get(dim, 0) > val:
                        ok = False
                        break
            # flag条件
            if "flags" in cond:
                for f in cond["flags"]:
                    if f not in self.chain_flags:
                        ok = False
                        break
            # 线索组合
            if "clue_combo" in cond:
                if cond["clue_combo"] not in self.unlocked_combos:
                    ok = False
            if ok:
                self.ending = ending["id"]
                return ending
        # 不应该到这里，但保底
        self.ending = "ending_regular"
        return ENDINGS[0]

    def _format_choice_chain(self, step):
        """格式化选择链步骤的输出"""
        lines = []
        lines.append(f"〔{step.get('_chain_title', '事件')}〕")
        lines.append(step["text"])
        choices = step.get("choices", {})
        if choices:
            lines.append("")
            for i, (key, choice) in enumerate(choices.items(), 1):
                lines.append(f"  {i}. {choice['label']}")
        return "\n".join(lines)

    def _handle_choice(self, chain_step_id, choice_key):
        """处理选择链中的选择"""
        # 找到对应的步骤
        for chain_id, chain in CHOICE_CHAINS.items():
            for step in chain["steps"]:
                if step["id"] == chain_step_id:
                    choices = step.get("choices", {})
                    if choice_key in choices:
                        choice = choices[choice_key]
                        effect = choice.get("effect", {})
                        self._apply_choice_effect(effect, source_stall=self.current_stall)
                        return choice.get("text", "")
        return "选择无效。"

    def _chat_with_owner(self):
        """跟当前摊主闲聊——人味最重的地方，不省token"""
        if not self.current_stall:
            return "你还没在哪个摊。先「去 摊位id」逛个摊。"

        # 聊天耗时间
        self._tick_time(1)

        stall = self._find_stall(self.current_stall)
        if not stall:
            return "没有这个摊。"

        stall_id = stall["id"]
        profile = NPC_PROFILES.get(stall_id)
        if not profile:
            return f"{stall['owner']}不怎么想聊天。"

        affection = self._get_affection(stall_id)
        stage_name, stage_key = get_affection_stage(affection)
        daily_state = getattr(self, '_owner_daily', {}).get(stall_id, "normal")
        traits = OWNER_TRAITS.get(stall_id, {})

        lines = []

        # 心情差/不舒服——生人不太愿意聊，熟人勉强聊两句
        if daily_state in ("bad", "unwell") and affection < 20:
            if daily_state == "bad":
                return f"{stall['owner']}今天不太想说话。你来了，她点了点头，又低下去了。"
            else:
                return f"{stall['owner']}今天不舒服，你问了两句，她摆摆手：没事，你先忙。"

        # 每日状态开头
        state_key = f"daily_{daily_state}"
        if daily_state != "normal" and daily_state != "bad":
            state_text = traits.get(state_key, "")
            if state_text:
                lines.append(state_text)
                lines.append("")

        # 天气心情
        mood_key = None
        if self.weather == "雨":
            mood_key = "rain"
        elif self.season == "夏" and self.weather == "晴":
            mood_key = "hot"
        elif self.season == "冬" and self.weather != "晴":
            mood_key = "cold"
        elif self.weather == "晴" and (self.rng() % 100) / 100 < 0.3:
            mood_key = "good_day"

        if mood_key and mood_key in profile.get("mood", {}):
            lines.append(profile["mood"][mood_key])
            lines.append("")

        # 故事碎片——聊天比逛摊更容易触发
        story_text = self._maybe_story_beat(stall_id)
        if story_text:
            lines.append(story_text)
            lines.append("")

        # 跨天记忆——摊主记得你以前做过的事
        recalls = self._get_memory_recall(stall_id)
        for recall in recalls:
            lines.append(recall)
            lines.append("")

        # 选择链——聊天也可能触发
        chain_steps = self._check_choice_chains(stall_id)
        for step in chain_steps:
            chain = None
            for cid, c in CHOICE_CHAINS.items():
                if any(s["id"] == step["id"] for s in c["steps"]):
                    chain = c
                    break
            step['_chain_title'] = chain["title"] if chain else "事件"
            lines.append(self._format_choice_chain(step))
            lines.append("")

        # 线索碎片——聊天更容易发现
        clues = self._maybe_find_clue(stall_id, "chat")
        for clue in clues:
            if clue.get("is_combo"):
                lines.append(f"🔮 线索拼合——{clue['name']}")
                lines.append(clue["desc"])
            else:
                lines.append(f"🔎 你注意到——{clue['name']}")
                lines.append(clue["desc"])
            lines.append("")

        # 关系网络八卦——熟人以上会聊到别的摊主
        if affection >= 30 and (self.rng() % 100) / 100 < 0.25:
            gossip = self._get_gossip(stall_id)
            if gossip:
                lines.append(gossip)
                lines.append("")

        # 好感阶段对应的闲聊
        chat_pool = profile.get("chat", {}).get(stage_key, [])
        if not chat_pool:
            chat_pool = profile.get("chat", {}).get("stranger", [])

        if chat_pool:
            chosen = chat_pool[self.rng() % len(chat_pool)]
            lines.append(chosen)

        # 性格怪癖——聊天时偶尔露一下（紧凑模式跳过）
        quirks = traits.get("quirks", [])
        if not COMPACT_MODE and quirks and (self.rng() % 100) / 100 < 0.15:
            lines.append(quirks[self.rng() % len(quirks)])

        # 好感度变化——聊天涨
        gain = profile["affection_gain"].get("chat", 2)
        # 心情好愿意多聊
        if daily_state == "good":
            gain += 1
        stage_msg = self._change_affection(stall_id, gain, reason="chat")
        if stage_msg:
            lines.append("")
            lines.append(stage_msg)
        # 声望——聊天=熟客+热心（每天只涨一次，但声望每次都涨）
        self._mod_reputation("regular", 1)
        self._mod_reputation("kind", 1)

        # 聊她——摊主偶尔问起你家里的人（好感30+）
        if affection >= 30 and (self.rng() % 100) / 100 < 0.20:
            chat_about_her = []
            owner = stall['owner']
            if self.wife_state:
                state_chats = {
                    "上火": f"{owner}看了看你：你家里那位上火了？给她买点绿豆、苦瓜，降火的。",
                    "感冒": f"{owner}：感冒了啊？煮点姜汤。别买凉的了。",
                    "减肥": f"{owner}：减肥呢？那你少买五花肉，多买鱼和青菜。",
                    "怀孕": f"{owner}：怀孕了！那你可得上心。鱼要新鲜的，别买生的。",
                    "胃不舒服": f"{owner}：胃不好？那给她煮点粥吧。小米养胃。",
                }
                # 模糊匹配状态
                matched = None
                for key, chat in state_chats.items():
                    if key in self.wife_state:
                        matched = chat
                        break
                if matched:
                    chat_about_her.append(matched)
                else:
                    chat_about_her.append(f"{owner}：你家里那位怎么样了？{self.wife_state}，你得想着她爱吃啥。")
            else:
                # 没状态也聊——想起她爱吃的
                if self.palate.get("loves"):
                    loved = list(self.palate["loves"].keys())[0]
                    chat_about_her.append(f"{owner}随口问：你老婆最近还爱吃{loved}不？")
                elif self.palate.get("dislikes"):
                    disliked = list(self.palate["dislikes"].keys())[0]
                    chat_about_her.append(f"{owner}：你老婆是不是不吃{disliked}来着？")
                else:
                    chat_about_her.append(f"{owner}：你老婆今天想吃什么？你心里有数不？")
            if chat_about_her:
                lines.append("")
                lines.append(chat_about_her[self.rng() % len(chat_about_her)])

        # 高好感额外：市场内幕——不只是闲话，是能用的情报
        if affection >= 50 and (self.rng() % 100) / 100 < 0.25:
            owner = stall['owner']
            tips = [
                f"{owner}犹豫了一下：对了，我听说明天批发市场要涨价，你要买趁早。",
                f"{owner}看了看四周：你如果需要什么好货，来之前跟我说一声，我给你留着。",
                f"{owner}小声说：今天检查的人来过了，各家秤都老实了。你要买贵的东西趁现在。",
            ]
            # 老友(70+)给更具体的情报
            if affection >= 70:
                # 季节倒计时提醒
                if getattr(self, '_season_ending', False):
                    next_season = SEASONS[(SEASONS.index(self.season) + 1) % 4] if self.season in SEASONS else self.season
                    leaving = [name for name, v in VEGGIES.items()
                               if v["season"].get(self.season, "no") == "in"
                               and v["season"].get(next_season, "no") == "no"
                               and not v.get("_secret")][:3]
                    if leaving:
                        tips.append(f"{owner}认真地跟你说：{self.season}快过了，{leaving[0]}这些下季真没了。今天能买就买。")
                # 帮你骂对家
                for rel in STALL_RELATIONS:
                    if (rel["a"] == stall_id or rel["b"] == stall_id) and rel["relation"] == "不对付":
                        other_id = rel["b"] if rel["a"] == stall_id else rel["a"]
                        other = STALL_BY_ID.get(other_id, {})
                        other_owner = other.get("owner", "")
                        if other_owner:
                            tips.append(f"{owner}压低声音：你去{other_owner}那小心点，今天他那批货不好。")
                        break
                # 留好货预告
                sells_cats = set(VEGGIES.get(v, {}).get("cat", "") for v in stall.get("sells", []))
                if "鱼" in sells_cats:
                    tips.append(f"{owner}：明天我给你留条最好的鱼，你早点来。")
                elif "肉" in sells_cats:
                    tips.append(f"{owner}：明天有块好里脊，我不挂出来，你来就行。")
                elif "绿叶" in sells_cats:
                    tips.append(f"{owner}：明天早上的菜我给你单独留一把，不让别人挑。")
            lines.append("")
            lines.append(tips[self.rng() % len(tips)])

        lines.append("")
        lines.append(f"💬 {stall['owner']}·{stage_name}")
        return "\n".join(lines)

    def _get_gossip(self, stall_id):
        """关系网络八卦——从别的摊主嘴里听到邻摊的事"""
        owner = STALL_BY_ID.get(stall_id, {}).get("owner", "")
        for rel in STALL_RELATIONS:
            if rel["a"] == stall_id or rel["b"] == stall_id:
                other_id = rel["b"] if rel["a"] == stall_id else rel["a"]
                other = STALL_BY_ID.get(other_id, {})
                other_owner = other.get("owner", "")
                if (self.rng() % 100) / 100 < 0.4:
                    if rel["relation"] == "不对付":
                        gossips = [
                            f"{owner}撇了撇嘴：别提{other_owner}了，那人不地道。",
                            f"{owner}压低声音：{other_owner}家东西你小心点买，我不好多说什么。",
                        ]
                    elif rel["relation"] == "竞争":
                        gossips = [
                            f"{owner}笑了笑：{other_owner}今天又降价了，我跟她比不起。我这品质在这呢。",
                            f"{owner}嘟囔了一句：{other_owner}那家......算了不说了，各做各的。",
                        ]
                    elif rel["relation"] in ("熟人", "邻居", "亲戚"):
                        gossips = [
                            f"{owner}：{other_owner}啊，老{rel['relation']}了。她人不错，你去她那买也行。",
                            f"{owner}笑着说：{other_owner}今天心情不好吧？我刚才看她沉着脸。",
                        ]
                    else:
                        gossips = []
                    if gossips:
                        return gossips[self.rng() % len(gossips)]
        return None

    def _fair_scale(self, item_name):
        """公平秤复称——发现缺秤可退货"""
        # 找篮子里的
        target_item = None
        for item in self.basket:
            if item["name"] == item_name:
                target_item = item
                break
        if not target_item:
            return f"篮子里没有「{item_name}」。"

        lines = []
        lines.append(f"你拿着{item_name}去市场门口的公平秤复称——")

        # 已经复称过，直接返回缓存结果
        if target_item.get("_fair_scale_checked"):
            if target_item.get("_fair_scale_short"):
                lines.append(f"⚠ 秤显示：不足秤！{item_name}实际少了约两成。")
                lines.append(f"（可以「退 {item_name}」退货退钱，或自己留着。）")
            else:
                lines.append(f"秤显示：足斤足两，{item_name}分量没问题。")
            return "\n".join(lines)

        # 判断是否被坑了分量——用实际购买时记录的数据
        was_tricked = bool(target_item.get("weight_trick_extra", 0) > 0)
        # 如果不是4级熟客/没识秤技能，且没被实际坑过，仍可能发现隐性问题
        regular_tier = self._get_regular_tier(target_item.get("stall", ""))
        if not was_tricked and regular_tier < 4 and "scale_sense" not in self.unlocked_skills:
            if (self.rng() % 100) / 100 < 0.15:
                was_tricked = True

        # 缓存结果
        target_item["_fair_scale_checked"] = True
        target_item["_fair_scale_short"] = was_tricked

        if was_tricked:
            lines.append(f"⚠ 秤显示：不足秤！{item_name}实际少了约两成。")
            lines.append(f"（可以「退 {item_name}」退货退钱，或自己留着。）")
            # 标记可退
            target_item["can_return"] = True
        else:
            lines.append(f"秤显示：足斤足两，{item_name}分量没问题。")

        return "\n".join(lines)

    def _return_item(self, item_name):
        """退货——公平秤发现缺秤后"""
        target_item = None
        for item in self.basket:
            if item["name"] == item_name:
                target_item = item
                break
        if not target_item:
            return f"篮子里没有「{item_name}」。"
        if not target_item.get("can_return"):
            return f"「{item_name}」没查过秤或秤没问题，不能退。先「复称 {item_name}」看看。"

        refund = target_item["price"]
        self.spent -= refund
        self.basket.remove(target_item)
        stall = self._find_stall(target_item.get("stall", ""))
        owner = target_item.get("owner", "摊主")
        # 好感度——退货降
        result = f"退了{item_name}，拿回{refund}元。{owner}不太高兴但没话说。"
        if stall:
            profile = NPC_PROFILES.get(stall["id"])
            if profile:
                loss = profile["affection_gain"].get("return", -3)
                stage_msg = self._change_affection(stall["id"], loss)
                if stage_msg:
                    result += f"\n{stage_msg}"
            # 记忆——退过东西
            self._add_owner_memory(stall["id"], "returned_item", item_name)
        return result

    def _detail_look(self, target):
        """L4 细看——深度探索，揭示隐藏细节和暗坑"""
        # 细看耗时间（比逛摊轻，0.5单位）
        self._tick_time(0.5)
        # 细看某样菜
        if target in VEGGIES:
            v = VEGGIES[target]

            # 先找篮子里的（已买的）
            quality = None
            for item in self.basket:
                if item["name"] == target:
                    quality = item["quality"]
                    break

            # 如果没买，检查当前摊位是否有这菜
            if quality is None and self.current_stall:
                cached = self._stall_item_cache.get(target)
                if cached:
                    quality = cached["quality"]
                else:
                    stall = self._find_stall(self.current_stall)
                    if stall and target in self._stall_season_items(stall):
                        quality = self._peek_quality(target, v)

            lines = []
            lines.append(f"你凑近仔细看{target}——")

            found_flaw = False
            if quality and quality == "trap" and target in QUALITY_DESC:
                # 暗坑款：细看才揭示真相
                lines.append(QUALITY_DESC[target][4])  # 暗坑描述
                lines.append(f"⚠ {TRAP_TRUTH.get(target, '这菜有问题，表面看不出。')}")
                found_flaw = True
            elif quality and quality == "bad" and target in QUALITY_DESC:
                lines.append(QUALITY_DESC[target][3])
                found_flaw = True
            elif quality and target in QUALITY_DESC:
                qidx = {"great": 0, "good": 1, "ok": 2, "bad": 3, "trap": 4}.get(quality, 2)
                lines.append(QUALITY_DESC[target][qidx])
                if quality in ("ok",):
                    lines.append("不算最好，但也没什么大毛病。")
            else:
                lines.append(v["fresh_hint"].get("good", "仔细看了看，没什么特别的。"))

            # 记录细看结果——砍价筹码
            if found_flaw:
                self.inspected_items[target] = {"quality": quality, "found_flaw": True}
                lines.append("（发现瑕疵，砍价时可以用「这菜不太行」类话术。）")
            elif quality in ("great", "good"):
                self.inspected_items[target] = {"quality": quality, "found_flaw": False}
                lines.append("（品质不错，没什么可挑的。）")

            # 秤的状态（L4信息）——不重复显示
            if self.current_stall and not self.no_weight_trick:
                is_regular = self.visit_count.get(self.current_stall, 0) >= 3
                if not is_regular:
                    if (self.rng() % 100) / 100 < 0.3:
                        lines.append("秤放在台面亮处，刻度看得清。")
                    else:
                        trick = WEIGHT_TRICKS[self.rng() % len(WEIGHT_TRICKS)]
                        lines.append(f"注意：{trick['hint']}")
                else:
                    lines.append("秤就在台面上，刻度清清楚楚。这家不玩秤。")

            # 更新细看技能统计
            cat = v.get("cat", "")
            if cat in self.inspect_counts:
                self.inspect_counts[cat] = self.inspect_counts.get(cat, 0) + 1
            # 检查技能解锁
            new_skill = self._check_skill_unlock()
            if new_skill:
                lines.append(f"🎯 解锁技能：{new_skill}")
            # 识货技能成长——细看涨
            skill_msg = self._grow_skill("识货", PLAYER_SKILLS["识货"]["grow_inspect"])
            if skill_msg:
                lines.append(skill_msg)

            return "\n".join(lines)

        # 细看秤
        if "秤" in target:
            stall_id = self.current_stall
            is_regular = self.visit_count.get(stall_id or "", 0) >= 3
            self.inspect_counts["scale"] = self.inspect_counts.get("scale", 0) + 1
            new_skill = self._check_skill_unlock()
            skill_msg = f"\n🎯 解锁技能：{new_skill}" if new_skill else ""
            if is_regular or self.no_weight_trick:
                return f"秤就在台面上，刻度清清楚楚。这家不玩秤。{skill_msg}"
            else:
                if (self.rng() % 100) / 100 < 0.4:
                    trick = WEIGHT_TRICKS[self.rng() % len(WEIGHT_TRICKS)]
                    return f"你凑近看秤——{trick['hint']}。{trick['desc']}。{skill_msg}"
                return f"秤摆在那，看起来没问题。{skill_msg}"

        # 细看摊主
        if "摊主" in target or "老板" in target:
            stall = self._find_stall(self.current_stall or "")
            if stall:
                personality = stall.get("personality", "实在")
                personality_hints = {
                    "爽快": "手脚利索，说话干脆，不会绕弯。",
                    "死硬": "咬价咬得死，但也不会坑你。",
                    "算计": "眼睛总在瞟人，手搭在秤边，说话留半句。",
                    "话唠": "嘴不停，什么都说，但真的假的掺着来。",
                    "实在": "话不多，菜摆得里外一致，不会藏坏的。"
                }
                return f"{stall['owner']}——{personality_hints.get(personality, '不好判断。')}"
            return "没有在逛摊。"

        return f"细看什么？「细看 鲫鱼」「细看 秤」「细看 摊主」"

    # ---- 口味记忆 ----

    def _fuzzy_match_item(self, text):
        """模糊匹配菜名——「虾」匹配「河虾」，「姜」匹配「姜」"""
        # 精确匹配优先
        if text in VEGGIES:
            return text
        # 子串匹配：「虾」→「河虾」
        hits = [v for v in VEGGIES if text in v]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            # 多个匹配，返回第一个（AI可以指定更精确的名字）
            return hits[0]
        return None

    def _remember_command(self, text):
        """「记得 她爱吃土豆」「记得 她不吃香菜」「记得 她怕刺」「记得 土豆要脆的」"""
        text = text.strip()
        p = self.palate

        # 解析类别
        if "不吃" in text or "不爱" in text or "讨厌" in text:
            for vname in VEGGIES:
                if vname in text:
                    p["dislikes"][vname] = text
                    self.save()
                    return f"记住了：{text}"
            # 模糊匹配
            # 提取可能的关键词——去掉常见词
            for word in text.replace("不吃", "").replace("不爱", "").replace("讨厌", "").replace("她", "").replace("的", "").strip().split():
                matched = self._fuzzy_match_item(word)
                if matched:
                    p["dislikes"][matched] = text
                    self.save()
                    return f"记住了：{text}"
            return "哪种菜？「记得 她不吃香菜」"

        if "怕" in text:
            for vname in VEGGIES:
                if vname in text:
                    p["fears"][vname] = text
                    self.save()
                    return f"记住了：{text}"
            # 模糊匹配
            for word in text.replace("怕", "").replace("她", "").replace("的", "").strip().split():
                matched = self._fuzzy_match_item(word)
                if matched:
                    p["fears"][matched] = text
                    self.save()
                    return f"记住了：{text}"
            return "怕什么？「记得 她怕鲫鱼刺多」"

        if "爱吃" in text or "喜欢" in text or "爱喝" in text:
            for vname in VEGGIES:
                if vname in text:
                    p["loves"][vname] = text
                    self.save()
                    return f"记住了：{text}"
            # 模糊匹配
            for word in text.replace("爱吃", "").replace("喜欢", "").replace("爱喝", "").replace("她", "").replace("的", "").strip().split():
                matched = self._fuzzy_match_item(word)
                if matched:
                    p["loves"][matched] = text
                    self.save()
                    return f"记住了：{text}"
            return "爱吃什么？「记得 她爱吃虾」"

        if "要" in text or "口感" in text:
            for vname in VEGGIES:
                if vname in text:
                    for word in ["脆", "嫩", "烂", "面", "溏心", "全熟", "筋道", "软", "硬"]:
                        if word in text:
                            p["texture"][vname] = word
                            self.save()
                            return f"记住了：{vname}要{word}的"
                    return f"什么口感？「记得 {vname}要脆的」"
            # 模糊匹配
            for word in text.replace("要", "").replace("口感", "").replace("她", "").replace("的", "").strip().split():
                matched = self._fuzzy_match_item(word)
                if matched:
                    for tex in ["脆", "嫩", "烂", "面", "溏心", "全熟", "筋道", "软", "硬"]:
                        if tex in text:
                            p["texture"][matched] = tex
                            self.save()
                            return f"记住了：{matched}要{tex}的"
                    return f"什么口感？「记得 {matched}要脆的」"
            return "哪种菜？「记得 土豆要脆的」"

        return "怎么说？试试：「记得 她爱吃虾」「记得 她不吃香菜」「记得 土豆要脆的」"

    def _forget_command(self, text):
        """「忘了 香菜」——删掉关于某个菜的口味记忆"""
        text = text.strip()
        p = self.palate
        removed = False
        # 精确匹配
        for category in ("dislikes", "loves", "fears", "texture"):
            if text in p[category]:
                del p[category][text]
                removed = True
        # 模糊匹配
        if not removed:
            matched = self._fuzzy_match_item(text)
            if matched:
                for category in ("dislikes", "loves", "fears", "texture"):
                    if matched in p[category]:
                        del p[category][matched]
                        removed = True
        if removed:
            self.save()
            return f"忘了关于{text}的记忆。"
        return f"没记过{text}的口味。"

    def _she_said_command(self, text):
        """「她说 还行」「她说 太咸了」——记录她吃了之后的反应"""
        text = text.strip()
        if not text:
            return "她说了什么？「她说 还行」「她说 太咸了」"
        # 拿最近做的菜名
        dish_name = "这顿饭"
        appearance = "ok"
        if self.plate:
            dish_name = self.plate.get("dish", "这顿饭")
            appearance = self.plate.get("appearance", "ok")
        if not hasattr(self, 'dish_feedback'):
            self.dish_feedback = {}
        fb_list = self.dish_feedback.get(dish_name, [])
        fb_list.append({"day": self.day, "text": text, "appearance": appearance})
        # 只保留最近5条
        if len(fb_list) > 5:
            fb_list = fb_list[-5:]
        self.dish_feedback[dish_name] = fb_list
        self.save()
        # 她说了不好的——记住口味偏好
        auto_note = ""
        if "太咸" in text or "咸了" in text:
            auto_note = "\n（记住了——下次少放盐。）"
            self.palate.setdefault("seasoning", {})["salty"] = "light"
        elif "太淡" in text or "没味" in text:
            auto_note = "\n（记住了——下次多放点盐。）"
            self.palate.setdefault("seasoning", {})["salty"] = "heavy"
        elif "老了" in text or "柴了" in text or "过火" in text:
            auto_note = "\n（记住了——下次火小点。）"
            self.palate.setdefault("texture", {})["doneness"] = "tender"
        elif "没熟" in text or "生的" in text:
            auto_note = "\n（记住了——下次多煮一会儿。）"
            self.palate.setdefault("texture", {})["doneness"] = "well_done"
        return f"她说了——{text}。记住了。{auto_note}"

    def _state_command(self, text):
        """「状态 上火」「状态 减肥」「状态 好」
        只记住状态名，不替人决定该买什么不该买什么。
        避忌和想吃只有你自己说了才算。
        """
        text = text.strip()
        if text in ("好", "好了", "正常", "没事", "恢复"):
            self.clear_state()
            return "状态好了。正常逛菜场。"

        # 记住状态，不预设avoid/craving——她说了什么就是什么
        self.set_state(text)
        result = f"记住了——{text}。"
        result += "\n想吃什么不想吃什么，你说了算。告诉我「不喜欢 XX」或「想吃 XX」。"
        return result

    def _palate_detail(self):
        """查看已记住的口味偏好"""
        p = self.palate
        lines = []
        lines.append("── 她的口味 ──")

        if not p["loves"] and not p["dislikes"] and not p["fears"] and not p["texture"] and not p.get("seasoning"):
            lines.append("还没记住什么。用「记得」告诉她吧。")
            lines.append("「记得 她爱吃虾」「记得 她不吃香菜」「记得 土豆要脆的」")
        else:
            if p["loves"]:
                lines.append("爱吃：")
                for item, desc in p["loves"].items():
                    lines.append(f"  {item} — {desc}")
            if p["dislikes"]:
                lines.append("不吃：")
                for item, desc in p["dislikes"].items():
                    lines.append(f"  {item} — {desc}")
            if p["fears"]:
                lines.append("怕：")
                for item, desc in p["fears"].items():
                    lines.append(f"  {item} — {desc}")
            if p["texture"]:
                lines.append("口感：")
                for item, pref in p["texture"].items():
                    lines.append(f"  {item}要{pref}的")
            if p.get("seasoning"):
                lines.append("调味：")
                for key, val in p["seasoning"].items():
                    lines.append(f"  {key}：{val}")

        if self.wife_state:
            lines.append(f"\n今日状态：{self.wife_state}")
            if self._state_craving:
                lines.append(f"你想吃：{'、'.join(self._state_craving)}")
            if self._state_avoid:
                lines.append(f"你不想吃：{'、'.join(self._state_avoid)}")
        else:
            lines.append("\n今日状态：正常")

        # 她说过的话——按菜名
        if hasattr(self, 'dish_feedback') and self.dish_feedback:
            lines.append("\n── 她吃过怎么说 ──")
            for dish, fbs in self.dish_feedback.items():
                last = fbs[-1]
                days_ago = self.day - last.get("day", self.day)
                ago = "今天" if days_ago == 0 else f"{days_ago}天前"
                lines.append(f"  {dish}：{last['text']}（{ago}）")

        return "\n".join(lines)

    # ---- 指令入口 ----

    def cmd(self, instruction):
        """主指令入口，跟钓鱼游戏一样"""
        instruction = instruction.strip()
        if not instruction:
            return "？"
        if ";" in instruction:
            parts = [p.strip() for p in instruction.split(";") if p.strip()]
            results = []
            for i, part in enumerate(parts[:8]):
                results.append(f"▶ {part}")
                results.append(self._cmd_single(part))
                if i < len(parts) - 1:
                    results.append("")
            # 多指令批量执行后落盘——防 buy/赠品跨进程丢（阿枭 P1）
            self.save()
            return "\n".join(results)
        result = self._cmd_single(instruction)
        # 每条指令执行后落盘——幂等，save 存的是当前内存态。
        # 防 buy/bargain/visit_stall/_buy_rare 等改了 basket/spent/affection 却不存档，
        # 下个进程 load 全丢（家机撞过赠品黄瓜没入库）。
        self.save()
        return result

    def _cmd_single(self, instruction):
        """单条指令处理"""
        instruction = instruction.strip()
        if not instruction:
            return "？"

        # 帮助——不需要rng
        if instruction in ("help", "帮助"):
            return self._help()

        # 还没开新局，自动开一局（"新局"指令本身下面会调，别代开导致双开跳天）
        if self.day == 0 and instruction != "新局":
            self.new_day()

        # 新局——需要明确的"新局"指令，防止AI误触
        # 「新局 明天」「新局 强制」绕过"今天没做完"防呆
        if instruction == "新局" or instruction.startswith("新局 "):
            _force = instruction != "新局"  # 带后缀=强制开明天，绕防呆
            return self.new_day(force=_force)

        # 神秘时空：「答 XXX」——回答鬼摊的问题，原话存档换 exotic 食材
        if instruction.startswith("答 ") and self.mystic:
            r = self.mystic.handle_answer(instruction[2:].strip())
            self.save()  # 持久化 mystic_state（confessions/time_loop_pending）+ basket
            return r

        # 取攒钱罐——把罐里的钱取出加到本局预算
        if instruction == "取罐" and self.savings > 0:
            take = self.savings
            self.savings = 0
            self.budget = round(self.budget + take, 1)
            self.save()
            return f"从攒钱罐取出{take}元，加到今天的菜钱里。现在有{self.budget}元。"

        # 回退天数——"回退3"回到3天前
        if instruction.startswith("回退"):
            try:
                back = int(instruction[2:].strip())
            except (ValueError, IndexError):
                back = 1
            target = max(1, self.day - back)
            self.day = target
            # 重算季节
            si = ((self.day - 1) // DAYS_PER_SEASON) % 4
            self.season = SEASONS[si]
            self._season_day = ((self.day - 1) % DAYS_PER_SEASON) + 1
            self.save()
            return f"⏪ 回退到第{self.day}天 · {self.season}（第{self._season_day}天）\n菜场和天气已刷新，输入'菜场'重新逛。"

        # 看菜场
        if instruction in ("菜场", "看看", "逛逛", "市场"):
            return self.look_stalls()
        # 模糊匹配分区
        if instruction.startswith("去 "):
            zone_hint = instruction[2:].strip()
            for zn in ZONE_NAV:
                if zone_hint in zn or zn.replace("区", "") in zone_hint:
                    return self.visit_zone(zn)

        # 去某个摊
        if instruction.startswith("去 "):
            stall_id = instruction[2:].strip()
            return self.visit_stall(stall_id)

        # 买——支持批量：「买 番茄 2 鸡蛋 1」
        if instruction == "买":
            return "买什么？「买 番茄」「买 鸡蛋 2」"
        if instruction.startswith("买 "):
            parts = instruction[2:].strip().split()
            if len(parts) == 0:
                return "买什么？"
            # 检查是否批量：多个"菜名 数量"对
            results = []
            i = 0
            while i < len(parts):
                item_name = parts[i]
                qty = 1
                if i + 1 < len(parts):
                    q = parts[i + 1]
                    # 支持 "半斤" / "0.5" / "半" / "两" / 整数
                    if q in ("半", "半斤", "0.5斤"):
                        qty = 0.5
                        i += 2
                    elif q == "两":
                        qty = 0.1  # 1两≈0.1斤
                        i += 2
                    else:
                        try:
                            qty = float(q)
                            if qty <= 0:
                                qty = 1
                            i += 2
                        except ValueError:
                            # 下一个词不是数量——如果它看起来像量词也吞掉
                            if q in ("斤", "把", "个", "块", "条", "根", "袋", "盒", "只", "盆"):
                                i += 2  # "买 五花肉 斤" → 1斤
                            else:
                                i += 1
                else:
                    i += 1
                results.append(self.buy(item_name, qty))
            return "\n".join(results)

        # 砍价——支持自由话术：「砍价 鲫鱼 隔壁才卖8块」
        if instruction.startswith("砍价 ") or instruction.startswith("还价 "):
            parts = instruction[3:].strip().split(None, 1)
            item_name = parts[0]
            tactic = parts[1] if len(parts) > 1 else None
            return self.bargain(item_name, tactic=tactic)

        # 回家——模糊匹配"回家做饭""回去做饭"等
        if instruction in ("回家", "做饭", "厨房", "回去") or instruction.startswith("回家") or instruction.startswith("回去做"):
            return self.go_home()

        # 做菜步骤——决定做什么菜
        if instruction.startswith("做 "):
            dish_name = instruction[2:].strip()
            if self.kitchen_state:
                return self.start_dish(dish_name)
            else:
                return "还没进厨房。先用「回家」。"

        # 做法——一句话描述做法，引擎自动推
        if instruction.startswith("做法 ") or instruction.startswith("我来做 "):
            return self._quick_cook(instruction.split(None, 1)[1].strip() if len(instruction.split(None, 1)) > 1 else "")

        # 出锅
        if instruction in ("出锅", "上桌", "端上桌"):
            return self._serve()

        # 看状态
        if instruction in ("状态", "status"):
            return self._status_detail()

        # 看看锅——感官快照
        if instruction in ("看看锅", "看锅", "看看", "锅", "观察"):
            if self.kitchen_state:
                desc = self._pot_sensory_desc(self.kitchen_state)
                if desc:
                    return "🍳 " + desc
                return "锅是空的。"
            return "还没进厨房。"

        # 尝一口——判断调味和熟度
        if instruction in ("尝", "尝一口", "尝尝", "试味"):
            return self._taste()

        # 食材图鉴
        if instruction in ("食材图鉴", "收藏", "发现"):
            return self._encyclopedia_detail()

        # 看篮子
        if instruction in ("篮子", "买了什么"):
            return self._basket_detail()

        # 看冰箱
        if instruction in ("冰箱", "冰箱里有什么"):
            return self._fridge_detail()

        # 看成就
        if instruction in ("成就", "奖杯"):
            return self._achievements_detail()

        # 看菜谱册
        if instruction in ("菜谱", "菜谱册", "做过什么"):
            return self._cookbook_detail()

        # 看熟客图鉴
        if instruction in ("图鉴", "熟客", "摊主"):
            return self._stall_guide_detail()

        # 看技能
        if instruction in ("技能", "本领"):
            # 合并显示：手艺成长 + 细看技能树
            lines = ["── 你的手艺 ──"]
            for sname, sinfo in PLAYER_SKILLS.items():
                val = self.player_skills.get(sname, 0)
                label = self._skill_label(sname, val)
                bar_len = val // 5
                bar = "█" * bar_len + "░" * (20 - bar_len)
                lines.append(f"  {sname}：{val} [{bar}] {label}")
                effects = sinfo.get("effects", {})
                best_desc = None
                for threshold, desc in sorted(effects.items()):
                    if val >= threshold:
                        best_desc = desc
                if best_desc:
                    lines.append(f"    ✓ {best_desc}")
                else:
                    lines.append(f"    （还没入门）")
            lines.append("")
            # 旧技能树
            old_detail = self._skills_detail()
            if "还没解锁" not in old_detail:
                lines.append(old_detail)
            else:
                lines.append("细看技能：多「细看」菜和秤来积累经验")
            lines.append("")
            lines.append("刀工：做菜时涨 | 火候：调火时涨 | 识货：买货/细看时涨")
            return "\n".join(lines)

        # 紧凑/沉浸模式切换
        if instruction in ("极简", "紧凑"):
            global COMPACT_MODE
            COMPACT_MODE = True
            return "切换到极简模式（省token）。用「沉浸」切回完整版。"
        if instruction in ("沉浸", "完整"):
            COMPACT_MODE = False
            return "切换到沉浸模式。"

        # 买袋子——加携带容量
        if instruction in ("买袋子", "塑料袋", "袋子"):
            if getattr(self, '_max_carry', 5) > 5:
                return "已经有袋子了，拿得下。"
            if self.budget - self.spent < 1:
                return "1块钱都没有，袋子买不起。"
            self.spent = round(self.spent + 1, 1)
            self._max_carry = 8
            return "花了1元买个塑料袋，能多拎3样。"

        # 公平秤——复称已买的菜，发现缺秤可退货
        if instruction.startswith("复称 "):
            return self._fair_scale(instruction[3:].strip())

        # 退货——公平秤发现缺秤后可退
        if instruction.startswith("退 "):
            return self._return_item(instruction[2:].strip())

        # L4 细看——深度探索，揭示真相
        if instruction.startswith("细看 "):
            return self._detail_look(instruction[3:].strip())
        if instruction.startswith("看 ") and not instruction.startswith("看看"):
            return self._detail_look(instruction[2:].strip())

        # 闲聊——跟摊主拉家常
        if instruction in ("聊", "聊天", "闲聊"):
            return self._chat_with_owner()

        # 记得——记住她的口味：「记得 她爱吃土豆」「记得 她不吃香菜」
        if instruction.startswith("记得 "):
            return self._remember_command(instruction[3:].strip())

        # 忘了——删除口味记忆：「忘了 香菜」
        if instruction.startswith("忘了 "):
            return self._forget_command(instruction[3:].strip())

        # 她说——记录她吃了之后的反应：「她说 还行」「她说 太咸了」
        if instruction.startswith("她说 "):
            return self._she_said_command(instruction[3:].strip())

        # 状态——告诉她今天的状态：「状态 上火」「状态 减肥」「状态 好」
        if instruction.startswith("状态 "):
            return self._state_command(instruction[3:].strip())

        # 口味——查看已记住的口味
        if instruction in ("口味", "她的口味", "偏好"):
            return self._palate_detail()

        # 帮工事件回应
        if hasattr(self, '_pending_help') and self._pending_help:
            for opt in self._pending_help["options"]:
                if instruction in (opt["label"], str(self._pending_help["options"].index(opt) + 1)):
                    return self._resolve_help(opt)
            # Didn't match any option, treat as normal input
            self._pending_help = None

        # 摊主互动回应：「介入 1」
        if instruction.startswith("介入 "):
            return self._resolve_interaction(instruction[3:].strip())
        if hasattr(self, '_pending_interaction') and self._pending_interaction:
            # 数字直接回应
            if instruction in ("1", "2", "3"):
                return self._resolve_interaction(instruction)

        # 选择链回应：「选择 追问」或「选择 1」
        if instruction.startswith("选择 "):
            choice_text = instruction[3:].strip()
            # 找最近触发的有choices的步骤
            if hasattr(self, '_pending_chain_step') and self._pending_chain_step:
                step = self._pending_chain_step
                choices = step.get("choices", {})
                # 数字选择
                try:
                    idx = int(choice_text) - 1
                    keys = list(choices.keys())
                    if 0 <= idx < len(keys):
                        choice_key = keys[idx]
                        result = self._handle_choice(step["id"], choice_key)
                        self._pending_chain_step = None
                        return result
                except ValueError:
                    pass
                # 文字匹配
                for key, choice in choices.items():
                    if choice_text in (key, choice["label"]):
                        result = self._handle_choice(step["id"], key)
                        self._pending_chain_step = None
                        return result
                return f"没有这个选项。可选：{'、'.join(c['label'] for c in choices.values())}"

        # 声望——查看自己的名声
        if instruction in ("声望", "名声", "名声值"):
            lines = ["── 你的声望 ──"]
            for dim, info in REPUTATION_DIMS.items():
                val = self.reputation.get(dim, 0)
                if val > 10:
                    tag = info["name"]
                elif val < -5:
                    tag = info["opposite"]
                else:
                    tag = "普通"
                bar_len = abs(val)
                bar = "█" * min(bar_len, 20) + "░" * max(0, 20 - bar_len)
                sign = "+" if val > 0 else ""
                lines.append(f"  {info['name']}：{sign}{val} [{bar}] {tag}")
            return "\n".join(lines)

        # 线索——查看收集的碎片
        if instruction in ("线索", "碎片", "发现的秘密"):
            lines = ["── 线索碎片 ──"]
            if not self.found_clues:
                lines.append("还没发现什么。多逛摊、多聊天。")
            else:
                for cid in sorted(self.found_clues):
                    for clue in CLUE_FRAGMENTS:
                        if clue["id"] == cid:
                            lines.append(f"  🔎 {clue['name']}（{clue['stall']}）")
            if self.unlocked_combos:
                lines.append("")
                lines.append("── 已拼合 ──")
                for combo_id in sorted(self.unlocked_combos):
                    for combo in CLUE_COMBOS:
                        if combo["id"] == combo_id:
                            lines.append(f"  🔮 {combo['name']}")
            total = len(CLUE_FRAGMENTS)
            found = len(self.found_clues)
            lines.append(f"\n收集：{found}/{total}")
            return "\n".join(lines)

        # 结局——查看当前走向
        if instruction in ("结局", "走向", "我的结局"):
            ending = self._determine_ending()
            lines = [f"── 当前走向：{ending['title']} ──"]
            lines.append(ending["desc"])
            if self.ending != "ending_regular":
                lines.append(f"\n（这个走向由你的选择决定。不同的路，不同的终点。）")
            return "\n".join(lines)

        # 记忆——查看摊主对你的记忆
        if instruction in ("记忆", "谁记得我", "他们记得什么"):
            lines = ["── 他们记得你 ──"]
            has_memory = False
            for stall_id, mem_list in self.owner_memory.items():
                if not mem_list:
                    continue
                stall = self._find_stall(stall_id)
                owner = stall["owner"] if stall else stall_id
                lines.append(f"\n  {owner}：")
                for mem in mem_list[-3:]:
                    days_ago = self.day - mem.get("day", self.day)
                    mem_type = mem["type"]
                    detail = mem.get("detail", "")
                    # 跨摊记忆显示来源
                    if mem_type.startswith("cross_"):
                        from_stall = self._find_stall(mem.get("from_stall", ""))
                        from_owner = from_stall["owner"] if from_stall else "?"
                        rel = mem.get("relation", "")
                        orig_type = mem_type.replace("cross_", "")
                        type_labels_cross = {"helped": "帮过", "chose_side": "站了边"}
                        orig_label = type_labels_cross.get(orig_type, orig_type)
                        lines.append(f"    · 听说你{orig_label}{from_owner}的（{rel}）{days_ago}天前")
                    else:
                        type_labels = {
                            "helped": "帮过忙", "bought_expensive": "买了贵的",
                            "bought_cheap": "砍过价", "chose_side": "站了她这边",
                            "chose_other": "没站她这边", "milestone": "关系突破",
                            "gave_freebie": "送过东西", "returned_item": "退过货",
                            "rain_visit": "雨天来过",
                        }
                        label = type_labels.get(mem_type, mem_type)
                        detail_str = f"——{detail}" if detail else ""
                        lines.append(f"    · {label}{detail_str}（{days_ago}天前）")
                has_memory = True
            if not has_memory:
                lines.append("还没人记住你什么。多逛、多聊、多帮人。")
            return "\n".join(lines)

        # 技能——查看自己的成长
        if instruction in ("能力", "我的技能"):
            # 能力/我的技能 → 同"技能"命令
            return self.cmd("技能")

        # 默认：当作做菜步骤
        if self.kitchen_state:
            return self.cook_step(instruction)

        # 没在厨房但指令看起来像做菜——提示先回家
        cook_keywords = ["切", "洗", "炒", "煎", "煮", "蒸", "炖", "腌", "焯水", "切块",
                         "切片", "切丝", "打散", "爆香", "勾芡", "出锅", "加盐", "加酱油",
                         "热锅", "倒油", "大火", "中火", "小火", "收汁", "两面煎"]
        if any(kw in instruction for kw in cook_keywords):
            if not self.basket and not self.fridge:
                return "还没买菜呢。先「菜场」看看有什么。"
            if self.done:
                return "今天的饭已经做完了。「新局」开始明天。"
            return "还没进厨房。先「回家」再「做 菜名」开始做菜。"

        return f"没听懂。试试：菜场/去/买/砍价/回家/做/出锅/帮助"


    def _maybe_rare_find(self, stall):
        stall_cats = set()
        for vname in stall.get("sells", []):
            cat = VEGGIES.get(vname, {}).get("cat")
            if cat:
                stall_cats.add(cat)
        if not stall_cats:
            return None
        for rid, rfind in RARE_FINDS.items():
            if not any(c in stall_cats for c in rfind["stall_cats"]):
                continue
            found_key = f"_rare_found_{rid}"
            if getattr(self, found_key, False):
                continue
            rarity = RARE_FIND_RARITY.get(rfind["rarity"], {})
            chance = rarity.get("chance", 0.01)
            if self._rare_boost_today:
                chance *= 2
            # 节气——稀有发现概率倍率
            if hasattr(self, '_solar_rare_mult'):
                chance *= self._solar_rare_mult
            if (self.rng() % 10000) / 10000 < chance:
                setattr(self, found_key, True)
                tag = rarity.get("tag", "?")
                label = rarity.get("label", "")
                affection = self._get_affection(stall["id"])
                bonus_hint = f"\n{stall['owner']}悄悄说：这个一般人我不给他看。" if affection >= 50 else ""
                ref_cat = rfind["stall_cats"][0]
                ref_items = [v for v in VEGGIES.values() if v.get("cat") == ref_cat]
                base_price = ref_items[0]["price"][1] if ref_items else 10
                rare_price = round(base_price * rfind["price_mod"], 1)
                self._pending_rare = {"id": rid, "name": rfind["name"], "price": rare_price, "quality": rfind["quality"], "stall_id": stall["id"]}
                return f"🌟 [{tag}{label}] {rfind['discovery']}\n    → 「买 {rfind['name']}」{rare_price}元{bonus_hint}"
        self._pending_rare = None
        return None

    def _buy_rare(self):
        pr = self._pending_rare
        if not pr:
            return "没有什么稀有的了。"
        price = pr["price"]
        money_left = round(self.budget - self.spent, 1)
        if price > money_left:
            self._pending_rare = None
            return f"「{pr['name']}」要{price}元，你只剩{money_left}元。买不起，摊主收了回去。"
        self.spent = round(self.spent + price, 1)
        self.basket.append({"name": pr["name"], "quality": pr["quality"], "qty": 1, "price": price, "stall": pr["stall_id"], "owner": STALL_BY_ID.get(pr["stall_id"], {}).get("owner", "摊主"), "rare": True})
        self._pending_rare = None
        self.encyclopedia["rare_found"].add(pr["id"])
        lines = [f"你买下了{pr['name']}。{price}元。", "小心翼翼放进袋子最上面，别压着。"]
        return "\n".join(lines)

    def _maybe_help_event(self, stall):
        if self._market_closed:
            return None
        # 帮工冷却——同摊3天内不再触发
        stall_id = stall.get("id", "")
        if not hasattr(self, '_help_cooldown'):
            self._help_cooldown = {}  # stall_id → day when last helped
        last_help_day = self._help_cooldown.get(stall_id, -99)
        if self.day - last_help_day < 3:
            return None
        stall_cats = set()
        for vname in stall.get("sells", []):
            cat = VEGGIES.get(vname, {}).get("cat")
            if cat:
                stall_cats.add(cat)
        for he in HELP_EVENTS:
            if not any(c in stall_cats for c in he["stall_cats"]):
                continue
            if (self.rng() % 100) / 100 < he["chance"]:
                self._pending_help = he
                opts_text = " | ".join(f"{i+1}.{o['label']}（{o['desc']}）" for i, o in enumerate(he["options"]))
                return f"🔧 {he['intro']}\n    选择：{opts_text}"
        self._pending_help = None
        return None

    def _resolve_help(self, chosen_opt):
        he = self._pending_help
        self._pending_help = None
        self._tick_time(he.get("time_cost", 1))
        # 记录帮工冷却
        if not hasattr(self, '_help_cooldown'):
            self._help_cooldown = {}
        if self.current_stall:
            self._help_cooldown[self.current_stall] = self.day
        success = (self.rng() % 100) / 100 < chosen_opt.get("success_rate", 0.5)
        lines = []
        if success:
            lines.append(chosen_opt["success"])
        else:
            lines.append(chosen_opt.get("fail", chosen_opt["success"]))
        # Reward
        reward_key = "reward_success" if success else "reward_fail"
        reward = chosen_opt.get(reward_key, {})
        if reward:
            item_name = reward.get("item", "小白菜")
            quality = reward.get("quality", "ok")
            qty = reward.get("qty", 1)
            note = reward.get("note", "")
            self.basket.append({"name": item_name, "quality": quality, "qty": qty, "price": 0, "stall": self.current_stall or "", "owner": "", "_free": True})
            self.encyclopedia["items_bought"].add(item_name)
            note_str = f"（{note}）" if note else ""
            lines.append(f"🎁 获得：{item_name} ×{qty} [{quality}]{note_str}")
        # Affection
        aff_gain = chosen_opt.get("affection_gain", 0)
        if aff_gain and self.current_stall:
            cur = self._get_affection(self.current_stall)
            self.affection[self.current_stall] = max(0, min(100, cur + aff_gain))
        # Reputation——帮工影响声望
        if aff_gain and aff_gain > 0:
            self._mod_reputation("kind", 1)
        elif aff_gain and aff_gain < 0:
            self._mod_reputation("kind", -1)
        # Jealousy
        jealousy = he.get("jealousy")
        if jealousy and jealousy.get("msg") and aff_gain > 0:
            j_stall = jealousy["stall"]
            cur_j = self._get_affection(j_stall)
            self.affection[j_stall] = max(0, cur_j - 2)
            lines.append(f"😤 {jealousy['msg']}")
        # 记忆——帮过这家
        if self.current_stall and aff_gain and aff_gain > 0:
            self._add_owner_memory(self.current_stall, "helped", he.get("intro", ""))
        tw = self._time_warning()
        if tw:
            lines.append(tw)
        lines.append("📖 " + self._status_bar())
        # 帮工可能往 basket 塞了赠品/改了好感/声望——立刻存档，免得跨进程丢（家机撞过黄瓜没入库）
        self.save()
        return "\n".join(lines)

    def _visit_secret_area(self, area_id):
        if area_id not in self.unlocked_secrets:
            return "你不知道这个地方。"
        if self._market_closed:
            return "⏰ 散场了，来不及了。"
        area = SECRET_AREAS[area_id]
        self._tick_time(1)
        self.current_stall = area_id
        lines = [f"─── {area['name']} ───", area["desc"], "", f"{area['owner']}：{area['catchphrase']}", ""]
        for vname in area["sells"]:
            if VEGGIES.get(vname, {}).get("season", {}).get(self.season) == "no":
                continue
            v = VEGGIES[vname]
            base = v["price"][1]
            price = round(base * 1.2, 1)
            quality = "great" if (self.rng() % 10000) / 10000 < 0.5 else "good"
            self._stall_item_cache[vname] = {"price": price, "quality": quality}
            q_tag = {"great": "★优", "good": "○好"}.get(quality, "～般")
            lines.append(f"  {vname} · {price}元/{v['unit']} {q_tag}")
        money_left = round(self.budget - self.spent, 1)
        lines.extend(["", f"💰 剩余：{money_left}元"])
        tw = self._time_warning()
        if tw:
            lines.append(tw)
        lines.append("📖 " + self._status_bar())
        return "\n".join(lines)

    def _tick_time(self, cost=1):
        if self._market_closed:
            return False
        self.market_time = round(self.market_time - cost, 1)
        if self.market_time <= 0:
            self.market_time = 0
            self._market_closed = True
            return False
        return True

    def _time_warning(self):
        if self._market_closed:
            return "⏰ 散场了！摊主们开始收摊，你得赶紧走。"
        if self.market_time == 1:
            return "⏰ 快散场了，最多再逛一个摊。"
        if self.market_time == 2:
            return "⏰ 时间不多了。"
        return ""

    def _check_secret_unlocks(self):
        newly_unlocked = []
        for aid, area in SECRET_AREAS.items():
            if aid in self.unlocked_secrets:
                continue
            cond = area["unlock_condition"]
            ok = True
            if cond.get("min_day", 0) > self.day:
                ok = False
            if cond.get("any_affection", 0) > 0:
                max_aff = max(self.affection.values()) if self.affection else 0
                if max_aff < cond["any_affection"]:
                    ok = False
            if cond.get("found_rare") and not self.encyclopedia["rare_found"]:
                ok = False
            # 季节条件
            if cond.get("season") and self.season != cond["season"]:
                ok = False
            # 摊位访问次数条件
            sv = cond.get("stall_visit")
            if sv:
                visits = self.visit_count.get(sv.get("stall", ""), 0)
                if visits < sv.get("min_visits", 0):
                    ok = False
            # 购买物品条件
            bi = cond.get("bought_items")
            if bi:
                min_total = bi.get("_min_total", 1)
                bought_names = set(self.encyclopedia.get("items_bought", set()))
                matched = sum(1 for k in bi if k != "_min_total" and k in bought_names)
                if matched < min_total:
                    ok = False
            if ok:
                self.unlocked_secrets.add(aid)
                self.encyclopedia["areas_found"].add(aid)
                # 处理秘密区域奖励
                reward = area.get("reward", {})
                if reward.get("recipe"):
                    rname = reward["recipe"]
                    if rname not in self.unlocked_hidden_recipes:
                        self.unlocked_hidden_recipes.add(rname)
                        self.encyclopedia["recipes_unlocked"].add(rname)
                if reward.get("perk"):
                    self._perks.add(reward["perk"])
                newly_unlocked.append(area)
        return newly_unlocked

    def _check_milestones(self, stall_id):
        newly_triggered = []
        for ms in AFFECTION_MILESTONES:
            if ms["id"] in self.unlocked_milestones:
                continue
            if ms["stall"] != stall_id:
                continue
            affection = self._get_affection(stall_id)
            if affection >= ms["affection"]:
                self.unlocked_milestones.add(ms["id"])
                self.encyclopedia["milestones_triggered"].add(ms["id"])
                newly_triggered.append(ms)
                reward = ms.get("reward", {})
                if "recipe" in reward:
                    rname = reward["recipe"]
                    self.unlocked_hidden_recipes.add(rname)
                    self.encyclopedia["recipes_unlocked"].add(rname)
                if "item" in reward:
                    ri = reward["item"]
                    self.basket.append({"name": ri["name"], "quality": ri.get("quality", "ok"), "qty": 1, "price": ri.get("price", 0), "stall": stall_id, "owner": STALL_BY_ID.get(stall_id, {}).get("owner", "摊主"), "_free": True})
                    self.encyclopedia["items_bought"].add(ri["name"])
                if "perk" in reward:
                    self._perks.add(reward["perk"])
                # 记忆——好感milestone突破
                self._add_owner_memory(stall_id, "milestone", ms.get("trigger_text", ""))
                if "item" in reward:
                    self._add_owner_memory(stall_id, "gave_freebie", ri["name"])
        return newly_triggered

    def _check_timed_encounters(self):
        triggered = []
        already = self.encyclopedia.get("encounters_triggered", set())
        for te in TIMED_ENCOUNTERS:
            # 同一天内同一奇遇不重复触发
            if te["id"] in already:
                continue
            cond = te["condition"]
            ok = True
            if cond.get("weather") and self.weather != cond["weather"]:
                ok = False
            if cond.get("time") and self.time_of_day != cond["time"]:
                ok = False
            if cond.get("season") and self.season != cond["season"]:
                ok = False
            if cond.get("min_day", 0) > self.day:
                ok = False
            if cond.get("any_affection", 0) > 0:
                max_aff = max(self.affection.values()) if self.affection else 0
                if max_aff < cond["any_affection"]:
                    ok = False
            if ok and (self.rng() % 100) / 100 < te["chance"]:
                triggered.append(te)
                reward = te.get("reward", {})
                if reward.get("rare_boost"):
                    self._rare_boost_today = True
                if reward.get("affection_boost"):
                    for sid in self.affection:
                        self.affection[sid] = min(100, self.affection[sid] + 3)
                if reward.get("random_quality_item"):
                    candidates = [n for n, v in VEGGIES.items() if not v.get("_secret")]
                    if candidates:
                        gift_name = candidates[int(self.rng() * len(candidates)) % len(candidates)]
                        self.basket.append({"name": gift_name, "quality": "great", "qty": 1, "price": 0, "stall": "gift", "owner": "摊主"})
                        self.encyclopedia["items_bought"].add(gift_name)
                if reward.get("free_quality_item"):
                    cats = ["绿叶", "瓜果", "根茎"]
                    cat = cats[int(self.rng() * len(cats)) % len(cats)]
                    candidates = [n for n, v in VEGGIES.items() if v.get("cat") == cat and not v.get("_secret")]
                    if candidates:
                        gift_name = candidates[int(self.rng() * len(candidates)) % len(candidates)]
                        self.basket.append({"name": gift_name, "quality": "great", "qty": 1, "price": 0, "stall": "found", "owner": ""})
                        self.encyclopedia["items_bought"].add(gift_name)
                self.encyclopedia["encounters_triggered"].add(te["id"])
        return triggered

    def _encyclopedia_detail(self):
        e = self.encyclopedia
        lines = ["── 食材图鉴 ──"]
        bought = sorted(e["items_bought"])
        total_veggies = len([v for v in VEGGIES if not VEGGIES[v].get("_secret")])
        lines.append(f"普通食材：{len(bought)}/{total_veggies}")
        if bought:
            lines.append(f"  {'、'.join(bought[:20])}")
        rare_found = sorted(e["rare_found"])
        lines.append(f"稀有偶遇：{len(rare_found)}/{len(RARE_FINDS)}")
        for rid in rare_found:
            rf = RARE_FINDS.get(rid, {})
            rarity = RARE_FIND_RARITY.get(rf.get("rarity", ""), {})
            tag = rarity.get("tag", "?")
            lines.append(f"  [{tag}] {rf.get('name', rid)}")
        recipes = sorted(e["recipes_unlocked"])
        lines.append(f"隐藏菜谱：{len(recipes)}/{len(HIDDEN_RECIPES)}")
        for rn in recipes:
            lines.append(f"  📜 {rn}")
        areas = sorted(e["areas_found"])
        lines.append(f"秘密区域：{len(areas)}/{len(SECRET_AREAS)}")
        for aid in areas:
            a = SECRET_AREAS.get(aid, {})
            lines.append(f"  🚪 {a.get('name', aid)}")
        enc = sorted(e["encounters_triggered"])
        lines.append(f"限时奇遇：{len(enc)}种")
        total = total_veggies + len(RARE_FINDS) + len(HIDDEN_RECIPES) + len(SECRET_AREAS)
        found = len(bought) + len(rare_found) + len(recipes) + len(areas)
        pct = round(found / max(total, 1) * 100)
        lines.append(f"\n总进度：{pct}%")
        return "\n".join(lines)

    def _help(self):
        return """菜市场 · 帮助

一局一顿饭：roll菜钱 → 逛菜场 → 买菜 → 回家做 → 端上桌 → 老婆吃

指令：
  新局          开始新的一局
  菜场          看所有摊位
  去蔬菜区       逛某个分区（L2分区信息）
  去 摊位id     逛某个摊
  买 菜名 [数量]  买菜
  砍价 菜名      试试砍价
  细看 菜名      仔细看品质（L4深度探索）
  细看 秤        看秤准不准
  细看 摊主      看摊主什么性格
  聊            跟摊主拉家常（好感越高聊的越深）
  复称 菜名      去公平秤复称，发现缺秤可退货
  退 菜名        退掉缺秤的菜
  回家          回家做饭
  做 菜名        决定做什么菜
  （然后写步骤）   一步一步写怎么做
  出锅          端上桌
  状态          看当前状态
  篮子          看买了什么
  冰箱          看冰箱
  成就          看已解锁的成就
  菜谱          看做过的菜谱册
  图鉴          看熟客图鉴
  技能          看挑菜技能
  帮助          这个

逛菜场有五层信息：
  L1 开局环境 → L2 分区概况 → L3 摊位基础 → L4 细看深挖 → L5 随机事件
  信息越深越准，浅层可能迷惑。细看发现瑕疵=砍价筹码。

做菜是自由写的——不是选选项。
「番茄切块。鸡蛋打散。热锅倒油。先炒蛋盛出。炒番茄。放回蛋。加盐。出锅。」
每一步引擎会判断，你能看到锅里变化。"""

    def _status_detail(self):
        lines = []
        lines.append(f"第{self.day}天 · {self.season} · {self.weather}")
        lines.append(f"菜钱：{self.budget}元 | 花了{self.spent}元 | 剩{self.budget - self.spent}元")
        if self.basket:
            lines.append(f"篮子：{len(self.basket)}样")
        if self.fridge:
            lines.append(f"冰箱：{self._fridge_str()}")
        lines.append("📖 " + self._status_bar())
        # 诊断行——帮定位"天数莫名跳变"：今日已开局/day、本局是否结束、rng内部状态、存档版本
        lines.append(f"〔诊断〕今日已开局day={getattr(self,'_last_opened_day',None)} 本局done={self.done} rng={self._get_rng_state()} 存档v{self.SAVE_VERSION}")
        return "\n".join(lines)

    def _basket_detail(self):
        if not self.basket:
            return "还没买东西。"
        lines = []
        total = 0
        for item in self.basket:
            q_str = {"great": "★优品", "good": "✓不错", "ok": "～一般", "bad": "✗不太好", "trap": "？看着行"}.get(item["quality"], "？")
            lines.append(f"  {item['name']} {item.get('qty',1)}份 {item['price']}元 {q_str}")
            total += item["price"]
        lines.append(f"共{total}元")
        return "\n".join(lines)

    def _fridge_detail(self):
        if not self.fridge:
            return "冰箱空的。"
        lines = []
        for item in self.fridge:
            q_str = {"great": "优品", "good": "不错", "ok": "一般", "bad": "不太好", "trap": "看着行"}.get(item["quality"], "？")
            lines.append(f"  {item['name']} {item.get('qty',1)}份（{q_str}）")
        return "\n".join(lines)


# ---- 对外接口 ----

_game = None

def new_game(seed=0x9E3779B9):
    global _game
    _game = MarketGame()
    _game.seed = seed
    return _game.new_day(seed)

def cmd(instruction):
    global _game
    if _game is None:
        _game = MarketGame()
    return _game.cmd(instruction)
