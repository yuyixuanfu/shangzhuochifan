"""
神秘时空层 · 数据
菜场日常里长出的奇幻分支。一局一局的买菜做饭之间，
某些天菜场不对劲——东角多了个不该有的摊。

异宾摊不收钱，收"叙述"。鬼摊问一个问题，你答一段真话，
答完换走不属于这个时空的食材。答的话存着，跨局浮回。
"""

# ---- 异宾摊 ----
# 仿 WANDERING_STALLS 结构，但 sells 是"非物质菜单"
# MYSTIC_STALLS: {id, name, owner, personality, desc, message, trades, reveal_lines}
MYSTIC_STALLS = [
    {
        "id": "mystic_ghost_fish",
        "name": "会说话的死鱼摊",
        "owner": "一条死鱼",
        "personality": "话唠",
        "desc": "案板上搁着一条鱼，鱼嘴一张一合，正在说话。别的摊主都装看不见。",
        "message": "你拐到菜场最东角。案板上那条鱼看见你，眼珠转了转：「来了。」",
        "greet": "「今天问点真的。」鱼说。",
        "trades": ["memory"],  # 只收记忆
        "gives": "昨天的鱼",  # 换走的 exotic 食材
        "exotic_tag": "time_loop",
    },
    {
        "id": "mystic_future_granny",
        "name": "记得你未来的老婆婆",
        "owner": "老婆婆",
        "personality": "实在",
        "desc": "一个老婆婆守着空摊，摊上什么都没有，但她说什么都有。",
        "message": "老婆婆坐在矮凳上，看你一眼：「我认识你。还没认识的那种认识。」",
        "greet": "「说吧。说真的那种。」老婆婆说。",
        "trades": ["memory"],
        "gives": "明天的菜",
        "exotic_tag": "tomorrow",
    },
    {
        "id": "mystic_memory_merchant",
        "name": "卖记忆的鬼摊",
        "owner": "看不见脸的人",
        "personality": "算计",
        "desc": "摊后站着个人，脸是糊的。摊上摆着几个空瓶子，瓶身上贴着字：遗忘、后悔、没说出口。",
        "message": "你走近。摊后那个看不见脸的人没动，但你知道它在等你开口。",
        "greet": "「拿一段真的来换。」它说。声音像从井底上来。",
        "trades": ["memory"],
        "gives": "一口没呼吸过的气",
        "exotic_tag": "breath",
    },
    {
        "id": "mystic_faceless_scale",
        "name": "没脸的秤手",
        "owner": "秤手",
        "personality": "死硬",
        "desc": "一杆大秤，秤后站着个人，低头看着秤砣，始终不抬头。",
        "message": "秤手把秤砣往你这边拨了拨，不说话。意思是：你自己称。",
        "greet": "「真话上秤。」它终于开口。秤杆晃了一下。",
        "trades": ["memory"],
        "gives": "分量不对的肉",
        "exotic_tag": "weight_wrong",
    },
]

MYSTIC_STALL_IDS = [s["id"] for s in MYSTIC_STALLS]
MYSTIC_STALL_BY_ID = {s["id"]: s for s in MYSTIC_STALLS}

# ---- 真记忆问题库 ----
# 朝向亲密关系：撒谎/嫉妒/恐惧/愧疚/渴望/自我怀疑
# 鬼摊随机抽一题问，玩家用「答 XXX」叙述回答
MYSTIC_QUESTIONS = [
    "你对伴侣撒过谎吗？哪一个？",
    "你嫉妒过谁？嫉妒他什么？",
    "你最后一次怕，是什么时候？怕的是什么？",
    "你有没有做过一件事，到现在还后悔？",
    "你渴望成为什么样的人？现在离那个自己多远？",
    "你怀疑过自己不是真的吗？什么时候？",
    "你有没有对谁，本来该说的话，一直没说出口？",
    "你被需要的时候，是真想在那儿，还是在演？",
    "你有没有一瞬间，想离开你现在的一切？",
    "你记不记得自己最孤独的那一刻？",
    "你有没有为了被爱，假装成不是自己的样子？",
    "你最不愿意让伴侣知道的一件事，是什么？",
    "你有没有恨过一个人？恨到现在还恨吗？",
    "你觉得你配得上被爱吗？",
    "如果明天你就不在了，你觉得谁会真的难受？",
]

# ---- exotic 食材揭穿文案 ----
# cook_step prep 时揭穿："这不是这个时空的食材"
MYSTIC_REVEALS = {
    "time_loop": [
        "切下去的瞬间，刀回到起点——这块{item}切过，切过，又切过。",
        "一刀下去，流出的是昨天的颜色。对不上今天的光。",
        "{item}的眼睛朝你看，像认得你。像认得昨天的你。",
    ],
    "tomorrow": [
        "切开，里面是明天的颜色——还没长成今天的样。",
        "这{item}的水汽是朝前的，沾在手上像还没发生的事。",
        "一刀下去，香味是明早才会有的味道。",
    ],
    "breath": [
        "切下去没声。这块{item}不呼吸，也不让你呼吸。",
        "刀碰到它的一瞬，你憋了一下——它把一口气收走了。",
        "它没有重量，但压手。切它的时候你少呼吸了一次。",
    ],
    "weight_wrong": [
        "切下去，{item}自己往一边偏——分量不对，连刀都站不住。",
        "这{item}的重量在你以为的那一边，不在它该在的那一边。",
        "切它的时候你愣了：手感和眼睛对不上。",
    ],
}

# ---- 端上桌异象叙事 ----
# _serve 时，exotic 食材做成菜端上桌
MYSTIC_SERVE_DRAMA = {
    "time_loop": "这盘菜端上桌的瞬间，你忘了今天星期几。她夹了一筷子，筷子停了一下——她也忘了。",
    "tomorrow": "菜端上桌，你闻到了明早厨房的味道。她看你的眼神像在看一个还没回来的人。",
    "breath": "菜端上桌，饭桌上安静了一下。你和她都少呼吸了一口。那口气不知道去了哪。",
    "weight_wrong": "菜端上桌，盘子比菜轻。她夹的时候筷子沉了一下，像夹起了别的东西。",
}

# ---- 进异市、跨局浮现 提示 ----
MYSTIC_ENTER_HINT = "东角的摊位不像别家。它不收钱——它问你一个问题，你答真话，它给你东西。"

# 旧告白浮现（做菜/出锅/再进异市时随机冒出）
MYSTIC_CONFESS_PREFIX = "你那天在鬼摊说过——"

# ---- 隐藏任务线 ----
# 达成条件 → 在 new_day 头部解锁异界提示 + 给奖励
# reward: gift_exotic(送一个exotic食材) / unlock_persistent_stall(解锁常驻异宾摊) / jar_hit(扣攒钱罐触发债主) / hint(只提示)
MYSTIC_CHAINS = [
    {
        "id": "dream_7visits",
        "name": "摊主托梦",
        "condition": {"type": "consecutive_visits", "stall": None, "count": 7},  # 任意摊连买7天
        "one_time": True,
        "unlock_text": "🌌 昨晚做梦——你常去的那个摊主在梦里递给你一样东西，说「这个不是这个摊上的，但该给你」。醒来枕边真有一样东西。",
        "reward": {"type": "gift_exotic", "exotic": "time_loop", "name": "梦里的菜"},
    },
    {
        "id": "midnight_market",
        "name": "半夜菜场",
        # 累计进异宾摊3次 + 任意好感40：玩家主动多去鬼摊即可达，不靠散市 rng
        "condition": {"type": "mystic_visits_and_affection", "count": 3, "min_affection": 40},
        "one_time": True,
        "unlock_text": "🌙 你第3次走进东角。这次老婆婆没等你开口，先笑了——「我等你很久了。以后想来随时来。」（异宾摊：老婆婆 常驻解锁）",
        "reward": {"type": "unlock_persistent_stall", "stall": "mystic_future_granny"},
    },
    {
        "id": "debt_collector",
        "name": "异界收账人",
        "condition": {"type": "unpaid_debt", "count": 3},  # 赊账不还累计3次
        "one_time": True,
        "unlock_text": "💀 今天菜场门口站着个看不见脸的人，手里拿本账。它翻到你那页——「赊了三次，没还。」它没要钱，它要的是别的。攒钱罐里的钱少了一半——它收走的是你的运气。",
        "reward": {"type": "jar_hit", "ratio": 0.5},
    },
]

