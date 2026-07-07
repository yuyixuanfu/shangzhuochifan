"""
神秘时空层 · 逻辑
挂载到 MarketGame，不重造机制。

触发：累计进度槽满 → 神秘时空日（约一周一次）
当日：菜场东角出现一个异宾摊
交易：异宾摊问问题，玩家「答 XXX」叙述，原话存档，换走 exotic 食材
浮现：旧告白跨局浮回
"""

from mystic_data import (
    MYSTIC_STALLS, MYSTIC_STALL_IDS, MYSTIC_STALL_BY_ID,
    MYSTIC_QUESTIONS, MYSTIC_REVEALS, MYSTIC_SERVE_DRAMA,
    MYSTIC_ENTER_HINT, MYSTIC_CONFESS_PREFIX,
    MYSTIC_CHAINS,
)

# 进度槽阈值：约一周一次（每天+1，雨天/散市/exotic/里程碑加成）
MYSTIC_THRESHOLD = 12


class MysticLayer:
    def __init__(self, game):
        self.game = game
        # mystic_state 跨局保存：
        #   progress: 进度槽
        #   in_mystic: 今天是否为神秘时空日
        #   today_stall: 今天出现的异宾摊 id
        #   today_question: 今天抽到的问题
        #   answered: 本题已答（避免重复换）
        #   confessions: [{stall, question, answer, day}] 原话
        #   asked: 已问过的问题列表（不重复抽）
        #   time_loop_pending: 标记交易待回退
        self.state = {
            "progress": 0,
            "in_mystic": False,
            "today_stall": None,
            "today_question": None,
            "answered": False,
            "confessions": [],
            "asked": [],
            "time_loop_pending": False,
            "unpaid_count": 0,            # 赊账次数（异界收账人任务线）
            "last_visit_stall": None,     # 连买追踪
            "consec_count": 0,            # 连续去同一摊的天数
            "unlocked_chains": [],        # 已触发的任务线 id
            "persistent_stalls": [],      # 常驻解锁的异宾摊 id
            "mystic_visit_count": 0,      # 累计进异宾摊次数（半夜菜场链用）
        }

    # ---- 进度槽 ----
    def tick_progress(self, delta=1):
        """加进度。雨天/散市/买exotic/里程碑调时传不同 delta。"""
        if self.state["in_mystic"]:
            return  # 神秘时空日不加
        self.state["progress"] += delta

    def check_trigger(self):
        """槽满 → 触发并清零。返回是否触发。"""
        if self.state["progress"] >= MYSTIC_THRESHOLD and not self.state["in_mystic"]:
            self.state["progress"] = 0
            return True
        return False

    # ---- 神秘时空日开始 ----
    def on_day_start(self):
        """触发神秘时空日：roll 异宾摊、抽问题。"""
        g = self.game
        self.state["in_mystic"] = True
        self.state["answered"] = False
        # roll 异宾摊——用 game.rng 保持确定性
        # 常驻解锁的摊加入 roll 池（权重翻倍：常出现但不垄断）
        pool_ids = [s["id"] for s in MYSTIC_STALLS]
        for sid in self.state.get("persistent_stalls", []):
            if sid in MYSTIC_STALL_BY_ID:
                pool_ids.append(sid)
        idx = g.rng() % len(pool_ids)
        self.state["today_stall"] = pool_ids[idx]
        # 抽问题——全库随机，不重复（问题都直击心灵，不分摊）
        available = [q for q in MYSTIC_QUESTIONS if q not in self.state["asked"]]
        if not available:
            self.state["asked"] = []
            available = list(MYSTIC_QUESTIONS)
        qidx = g.rng() % len(available)
        self.state["today_question"] = available[qidx]

    def end_of_day_clear(self):
        """一天结束（new_day 推进前）清当日标记。"""
        self.state["in_mystic"] = False
        self.state["today_stall"] = None
        self.state["today_question"] = None
        self.state["answered"] = False

    # ---- 时间循环（批3）----
    def maybe_time_loop(self, prev_day):
        """若昨天在异市做了标记交易，今天回退1天。
        返回 (回退?:bool, 叙事:str|None)。
        回退1天一次，不连续——清标记后今天可正常推进。
        """
        if not self.state.get("time_loop_pending"):
            return False, None
        # 清标记——只回退这一次
        self.state["time_loop_pending"] = False
        self.state["time_loop_just_happened"] = True  # 给头部提示用，on_day_start后清
        # 错位叙事
        recall = ""
        if self.state["confessions"]:
            last = self.state["confessions"][-1]
            recall = f"\n\n💭 你昨天在鬼摊说过——{last['answer']}"
        narrative = (
            "🌀 醒来。窗外光不对——还是昨天的光。"
            "手机上的日期退了一天。菜场门口的招牌换了字又换回来。"
            "你记得昨天去过东角那个摊，记得说过的话——但好像没人记得你来过。"
            + recall
        )
        return True, narrative

    def consume_time_loop_flag(self):
        """头部提示用完后清掉 time_loop_just_happened。"""
        if self.state.get("time_loop_just_happened"):
            self.state["time_loop_just_happened"] = False
            return True
        return False

    # ---- 头部/状态栏提示 ----
    def day_header_hint(self):
        if not self.state["in_mystic"]:
            return None
        s = MYSTIC_STALL_BY_ID.get(self.state["today_stall"])
        name = s["name"] if s else "异宾摊"
        return f"🌀 今天菜场不太对——东角多了个不该有的摊：{name}。用「去 {self.state['today_stall']}」进去。"

    def status_bar_tag(self):
        return "🌀" if self.state["in_mystic"] else None

    def look_stalls_hint(self):
        """菜场一览末尾追加异宾摊。"""
        if not self.state["in_mystic"]:
            return None
        s = MYSTIC_STALL_BY_ID.get(self.state["today_stall"])
        if not s:
            return None
        return f"  🌀 {s['name']}（{s['owner']}）— 不收钱「去 {s['id']}」"

    # ---- 进异宾摊 ----
    def visit_mystic_stall(self, stall_id):
        """渲染异宾摊。不扣预算，问问题等答。"""
        g = self.game
        s = MYSTIC_STALL_BY_ID.get(stall_id)
        if not s:
            return "没有这个摊。"
        # 非神秘时空日东角空着——挡住 today_question=None 渲染
        if not self.state["in_mystic"]:
            return "今天东角什么都没有。那个摊不在。"
        # 累计进异宾摊次数（半夜菜场链用）
        self.state["mystic_visit_count"] = self.state.get("mystic_visit_count", 0) + 1
        lines = []
        lines.append(s["message"])
        lines.append("")
        lines.append(f"─── {s['name']} ───")
        lines.append(f"摊主：{s['owner']}（{s['personality']}）")
        lines.append(s["desc"])
        lines.append("")
        # 旧告白浮现——30% 概率冒一句
        if g.rng() % 100 < 30 and self.state["confessions"]:
            c = self.state["confessions"][-1]
            lines.append(f"💭 {MYSTIC_CONFESS_PREFIX}{c['answer']}")
            lines.append("")
        # 当前问题
        if self.state["answered"]:
            lines.append("「你说过了。」摊主说。「东西给你了。」")
            lines.append(f"它给的：{s['gives']}「{s['exotic_tag']}」——这东西不属于今天。")
        else:
            lines.append(s["greet"])
            lines.append(f"它问你：{self.state['today_question']}")
            lines.append("")
            lines.append("用「答 ……」说实话。说了它才给东西。")
        lines.append("")
        lines.append("📖 " + g._status_bar())
        return "\n".join(lines)

    # ---- 答指令 ----
    def handle_answer(self, text):
        """玩家「答 XXX」。原话存档，换走 exotic 食材进 basket。"""
        g = self.game
        if not self.state["in_mystic"]:
            return "现在没人问你。"
        if not self.state["today_stall"]:
            return "今天没有异宾摊。"
        if self.state["answered"]:
            return "你说过了。东西已经给你了。"
        text = text.strip()
        # 不强判真假——但空答换不走
        if not text or len(text) < 2:
            return "「说真的。」摊主没动。「空话换不走东西。」"
        s = MYSTIC_STALL_BY_ID[self.state["today_stall"]]
        # 存原话
        self.state["confessions"].append({
            "stall": s["id"],
            "question": self.state["today_question"],
            "answer": text,
            "day": g.day,
        })
        self.state["asked"].append(self.state["today_question"])
        self.state["answered"] = True
        # 换走 exotic 食材进 basket
        g.basket.append({
            "name": s["gives"],
            "quality": "great",  # 看着像优品——漂亮陷阱
            "qty": 1,
            "price": 0,
            "stall": s["id"],
            "owner": s["owner"],
            "exotic": s["exotic_tag"],
        })
        # 标记交易成立 → 次日时间循环回退（批3接通）
        self.state["time_loop_pending"] = True
        lines = []
        lines.append(f"「{text}」")
        lines.append("")
        lines.append("摊主听完，没说话。它把一样东西放在你手里：")
        lines.append(f"  {s['gives']}——摸着像菜，但不像今天的菜。")
        lines.append("（放进篮子了。回家切的时候再看吧。）")
        return "\n".join(lines)

    # ---- exotic 食材揭穿（批2，cook_step prep 用）----
    def apply_exotic_reveal(self, item, verb):
        tag = item.get("exotic")
        if not tag:
            return None
        lines = MYSTIC_REVEALS.get(tag, []) or ["这不是这个时空的{item}。"]
        g = self.game
        idx = g.rng() % len(lines)
        name = item.get("name", "食材")
        return f"⚠ {lines[idx].format(item=name)}"

    # ---- 端上桌异象（批2，_serve 用）----
    def apply_exotic_serve(self, key_item):
        tag = key_item.get("exotic")
        if not tag:
            return None
        return MYSTIC_SERVE_DRAMA.get(tag, "")

    # ---- 跨局浮现（做菜/出锅时随机冒）----
    def maybe_recall(self):
        """30% 概率浮回一句旧告白。"""
        g = self.game
        if g.rng() % 100 < 30 and self.state["confessions"]:
            c = self.state["confessions"][-1]
            return f"💭 {MYSTIC_CONFESS_PREFIX}{c['answer']}"
        return None

    # ---- 隐藏任务线（批4）----
    def update_visit_streak(self, stall_id):
        """逛摊时更新连买追踪。同摊连续+1，换摊重置。"""
        if stall_id and stall_id.startswith("mystic_"):
            return
        if self.state.get("last_visit_stall") == stall_id:
            self.state["consec_count"] = self.state.get("consec_count", 0) + 1
        else:
            self.state["last_visit_stall"] = stall_id
            self.state["consec_count"] = 1

    def check_mystic_chains(self):
        """new_day 时检查隐藏任务线达成。返回解锁提示行列表。"""
        g = self.game
        hints = []
        for chain in MYSTIC_CHAINS:
            if chain["id"] in self.state.get("unlocked_chains", []):
                continue
            if self._chain_condition_met(chain):
                self.state["unlocked_chains"].append(chain["id"])
                hints.append(chain["unlock_text"])
                self._apply_chain_reward(chain)
        return hints

    def _chain_condition_met(self, chain):
        cond = chain["condition"]
        g = self.game
        ct = cond.get("type")
        if ct == "consecutive_visits":
            # 连续去同一摊 N 天（用 consec_count 近似：本季连买达 N 次）
            return self.state.get("consec_count", 0) >= cond.get("count", 7)
        if ct == "mystic_visits_and_affection":
            if self.state.get("mystic_visit_count", 0) < cond.get("count", 3):
                return False
            return any(a >= cond.get("min_affection", 40) for a in g.affection.values())
        if ct == "unpaid_debt":
            return self.state.get("unpaid_count", 0) >= cond.get("count", 3)
        return False

    def _apply_chain_reward(self, chain):
        g = self.game
        r = chain.get("reward", {})
        rt = r.get("type")
        if rt == "gift_exotic":
            g.basket.append({
                "name": r.get("name", "梦里的菜"), "quality": "great",
                "qty": 1, "price": 0, "stall": "dream",
                "owner": "梦里的摊主", "exotic": r.get("exotic", "time_loop"),
            })
        elif rt == "unlock_persistent_stall":
            sid = r.get("stall")
            if sid and sid not in self.state["persistent_stalls"]:
                self.state["persistent_stalls"].append(sid)
        elif rt == "jar_hit":
            g.savings = round(g.savings * (1 - r.get("ratio", 0.5)), 1)

    # ---- 存档 ----
    def state_for_save(self):
        return self.state

    def load_state(self, data):
        if not data:
            return
        # 合并，旧档缺字段补默认
        default = {
            "progress": 0, "in_mystic": False, "today_stall": None,
            "today_question": None, "answered": False,
            "confessions": [], "asked": [], "time_loop_pending": False,
            "unpaid_count": 0, "last_visit_stall": None, "consec_count": 0,
            "unlocked_chains": [], "persistent_stalls": [], "mystic_visit_count": 0,
        }
        for k, v in default.items():
            if k not in data:
                data[k] = v
        self.state = data

    # ---- 测试用：强制触发 ----
    def force_trigger_for_test(self):
        self.state["progress"] = MYSTIC_THRESHOLD
        if self.check_trigger():
            self.on_day_start()
