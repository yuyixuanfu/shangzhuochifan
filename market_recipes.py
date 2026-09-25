"""
菜谱步骤骨架
每道菜有必需步骤，AI写法自由但必须碰到
"""

# 菜谱定义
# required_steps: 必需步骤，按顺序
# 每个步骤: {
#   id: 步骤标识
#   name: 步骤名称
#   keywords: 触发关键词（任一匹配即算碰到）
#   hint: 没碰到时的提示
#   optional: 可选步骤（做了加分）
# }
#
# P0-8：required 的关键词一律用多字、有区分度的词组——引擎是子串匹配
# （kw in normalized），"洗"/"切"/"蒸" 这类单字会被无关文本误点亮。
# P1-23：optional 关键词必须与 required 相区分，避免同一句文本双计分。

RECIPES = {
    "番茄炒蛋": {
        "ingredients": ["番茄", "鸡蛋"],
        "required": [
            {"id": "prep_egg", "name": "处理鸡蛋", "keywords": ["打散", "打蛋", "搅蛋", "磕蛋", "蛋液"], "hint": "鸡蛋还没打散。"},
            {"id": "prep_tomato", "name": "处理番茄", "keywords": ["切块", "切片", "切丁", "切番茄", "番茄切"], "hint": "番茄还没切。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油", "起油锅"], "hint": "锅还没热，先开火。"},
            {"id": "cook_egg", "name": "炒蛋", "keywords": ["炒蛋", "煎蛋", "蛋液倒", "先炒蛋"], "hint": "鸡蛋还没下锅。"},
            {"id": "cook_tomato", "name": "炒番茄", "keywords": ["炒番茄", "番茄下锅", "翻炒番茄"], "hint": "番茄还没炒。"},
            {"id": "combine", "name": "合炒", "keywords": ["放回", "倒回", "混合", "一起炒", "翻匀"], "hint": "蛋和番茄还没合到一起。"},
            {"id": "season", "name": "调味", "keywords": ["加盐", "加糖", "调味", "放盐"], "hint": "还没调味。"},
        ],
        "optional": [
            {"id": "save_egg", "name": "蛋先盛出", "keywords": ["盛出", "盛出来", "先盛"], "bonus": 1},
            {"id": "garnish", "name": "撒葱花", "keywords": ["葱花", "撒葱", "葱末"], "bonus": 1},
        ],
    },
    "红烧鲫鱼": {
        "ingredients": ["鲫鱼"],
        "required": [
            {"id": "prep_fish", "name": "处理鱼", "keywords": ["划刀", "切花刀", "划几刀", "抹盐", "腌鱼", "去腥"], "hint": "鱼还没处理，要划刀去腥。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "fry", "name": "煎鱼", "keywords": ["煎鱼", "煎黄", "煎至金黄", "两面煎"], "hint": "鱼还没煎。"},
            {"id": "aromatics", "name": "爆香料", "keywords": ["爆香", "姜片", "葱段", "蒜末", "干辣椒"], "hint": "还没放葱姜蒜爆香。"},
            {"id": "braise", "name": "炖煮", "keywords": ["加水", "加水炖", "炖鱼", "焖煮", "收汁"], "hint": "还没加水炖。"},
            {"id": "season", "name": "调味", "keywords": ["加酱油", "加料酒", "加醋", "加盐", "加糖", "调味"], "hint": "还没调味。"},
        ],
        "optional": [
            {"id": "fry_careful", "name": "煎鱼不破皮", "keywords": ["拍淀粉", "不急着翻", "定型"], "bonus": 2},
            {"id": "slow_braise", "name": "小火慢炖", "keywords": ["小火", "慢炖", "炖二十", "炖半"], "bonus": 1},
        ],
    },
    "鲫鱼豆腐汤": {
        "ingredients": ["鲫鱼", "豆腐"],
        "required": [
            {"id": "prep_fish", "name": "处理鱼", "keywords": ["划刀", "抹盐", "腌鱼", "去腥"], "hint": "鱼还没处理去腥。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "fry", "name": "煎鱼", "keywords": ["煎鱼", "煎黄", "两面煎"], "hint": "鱼还没煎。"},
            {"id": "add_water", "name": "加水", "keywords": ["加水", "加汤"], "hint": "还没加水，做汤要加水。"},
            {"id": "boil", "name": "烧开", "keywords": ["烧开", "煮开", "大火烧", "咕嘟"], "hint": "水还没烧开。"},
            {"id": "add_tofu", "name": "放豆腐", "keywords": ["放豆腐", "豆腐下", "加豆腐"], "hint": "豆腐还没放。"},
            {"id": "simmer", "name": "炖煮", "keywords": ["小火", "小火炖", "炖到汤白"], "hint": "还没炖，要小火炖到汤白。"},
            {"id": "season", "name": "调味", "keywords": ["加盐", "调味", "胡椒粉"], "hint": "还没调味。"},
        ],
        "optional": [
            {"id": "hot_water", "name": "加热水（汤更白）", "keywords": ["热水", "沸水", "滚水"], "bonus": 2},
            {"id": "ginger", "name": "放姜去腥", "keywords": ["姜片", "姜丝"], "bonus": 1},
        ],
    },
    "豇豆炒肉": {
        "ingredients": ["豇豆", "瘦猪肉"],
        "required": [
            {"id": "prep_bean", "name": "处理豇豆", "keywords": ["切段", "掐段", "切豇豆"], "hint": "豇豆还没切段。"},
            {"id": "prep_meat", "name": "处理肉", "keywords": ["切丝", "切片", "腌肉", "腌一下"], "hint": "肉还没切/腌。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "cook_meat", "name": "炒肉", "keywords": ["炒肉", "肉丝下锅", "滑炒", "先炒肉"], "hint": "肉还没炒。"},
            {"id": "cook_bean", "name": "炒豇豆", "keywords": ["炒豇豆", "豇豆下锅", "下豇豆"], "hint": "豇豆还没炒。"},
            {"id": "combine", "name": "合炒", "keywords": ["一起炒", "翻匀", "放回", "混合"], "hint": "肉和豇豆还没合到一起。"},
            {"id": "season", "name": "调味", "keywords": ["加盐", "加酱油", "调味"], "hint": "还没调味。"},
        ],
        "optional": [
            {"id": "blanch_bean", "name": "豇豆焯水", "keywords": ["先焯水再炒", "焯过水", "过冷水"], "bonus": 2},
            {"id": "marinate", "name": "腌肉", "keywords": ["料酒腌", "淀粉抓", "抓匀腌制"], "bonus": 1},
        ],
    },
    "酸辣土豆丝": {
        "ingredients": ["土豆"],
        "required": [
            {"id": "prep", "name": "切丝泡水", "keywords": ["切丝", "切土豆"], "hint": "土豆还没切丝。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "aromatics", "name": "爆香料", "keywords": ["爆香", "干辣椒", "花椒", "蒜末"], "hint": "还没放辣椒花椒爆香。"},
            {"id": "stir_fry", "name": "炒土豆丝", "keywords": ["下土豆", "翻炒", "炒土豆丝"], "hint": "土豆丝还没下锅。"},
            {"id": "season", "name": "调味", "keywords": ["加醋", "加盐", "调味"], "hint": "还没调味。醋是灵魂。"},
        ],
        "optional": [
            {"id": "wash_starch", "name": "洗去淀粉", "keywords": ["过水", "冲洗", "换水冲"], "bonus": 2},
            {"id": "vinegar_first", "name": "醋溜（先加醋）", "keywords": ["先加醋", "醋溜", "沿锅边淋醋"], "bonus": 1},
        ],
    },
    "麻婆豆腐": {
        "ingredients": ["豆腐", "肉末"],
        "required": [
            {"id": "prep_tofu", "name": "处理豆腐", "keywords": ["切块", "切丁", "豆腐切"], "hint": "豆腐还没切块。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "cook_meat", "name": "炒肉末", "keywords": ["炒肉末", "肉末下锅", "煸肉"], "hint": "肉末还没炒。"},
            {"id": "douban", "name": "加豆瓣酱", "keywords": ["豆瓣酱", "豆瓣", "辣酱"], "hint": "还没加豆瓣酱，这是麻婆豆腐的底味。"},
            {"id": "add_tofu", "name": "放豆腐", "keywords": ["豆腐下锅", "放豆腐", "加豆腐"], "hint": "豆腐还没下锅。"},
            {"id": "season", "name": "调味勾芡", "keywords": ["勾芡", "淀粉", "加花椒", "调味"], "hint": "还没调味/勾芡。"},
        ],
        "optional": [
            {"id": "blanch_tofu", "name": "豆腐焯水", "keywords": ["先焯水", "焯过水", "烫过"], "bonus": 2},
            {"id": "hua_jiao", "name": "撒花椒粉", "keywords": ["花椒面", "花椒粉"], "bonus": 1},
        ],
    },
    "可乐鸡翅": {
        "ingredients": ["鸡翅"],
        "required": [
            {"id": "prep", "name": "处理鸡翅", "keywords": ["划刀", "切花刀", "划几刀"], "hint": "鸡翅还没处理。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "fry", "name": "煎鸡翅", "keywords": ["炒鸡翅", "鸡翅下锅", "煎鸡翅", "煎黄"], "hint": "鸡翅还没煎。"},
            {"id": "cola", "name": "加可乐", "keywords": ["可乐", "倒可乐", "加可乐"], "hint": "还没加可乐。"},
            {"id": "braise", "name": "炖煮收汁", "keywords": ["炖煮", "收汁", "焖煮"], "hint": "还没炖/收汁。"},
        ],
        "optional": [
            {"id": "blanch", "name": "焯水去腥", "keywords": ["先焯水", "焯过水"], "bonus": 2},
            {"id": "ginger", "name": "放姜", "keywords": ["姜片", "姜块"], "bonus": 1},
        ],
    },
    "清炒时蔬": {
        "ingredients": [],  # 任意蔬菜
        "required": [
            {"id": "prep", "name": "洗菜切菜", "keywords": ["洗菜", "切段", "切菜", "择菜", "掰段"], "hint": "菜还没处理。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "aromatics", "name": "爆香料", "keywords": ["爆香", "蒜末", "姜末", "蒜片"], "hint": "还没放蒜/姜爆香。"},
            {"id": "stir_fry", "name": "大火翻炒", "keywords": ["下锅", "翻炒"], "hint": "菜还没下锅。"},
            {"id": "season", "name": "调味", "keywords": ["加盐", "调味"], "hint": "还没调味。"},
        ],
        "optional": [
            {"id": "high_heat", "name": "大火快炒", "keywords": ["大火快炒", "猛火", "快炒"], "bonus": 1},
        ],
    },
    "蛋炒饭": {
        "ingredients": ["鸡蛋"],
        "required": [
            {"id": "prep_egg", "name": "打散鸡蛋", "keywords": ["打散", "打蛋", "搅蛋"], "hint": "鸡蛋还没打散。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "cook_egg", "name": "炒蛋", "keywords": ["炒蛋", "蛋液倒", "煎蛋"], "hint": "鸡蛋还没下锅。"},
            {"id": "add_rice", "name": "加米饭", "keywords": ["米饭", "剩饭", "隔夜饭", "倒饭"], "hint": "还没加米饭。"},
            {"id": "stir_fry", "name": "翻炒", "keywords": ["翻炒", "炒散", "翻匀", "炒饭"], "hint": "还没翻炒。"},
            {"id": "season", "name": "调味", "keywords": ["加盐", "调味", "酱油"], "hint": "还没调味。"},
        ],
        "optional": [
            {"id": "day_old_rice", "name": "用隔夜饭", "keywords": ["冷饭", "隔夜冷饭"], "bonus": 2},
            {"id": "garnish", "name": "撒葱花", "keywords": ["葱花", "撒葱"], "bonus": 1},
        ],
    },
    "蒜蓉炒时蔬": {
        "ingredients": [],
        "required": [
            {"id": "prep_veg", "name": "洗菜切菜", "keywords": ["洗菜", "切段", "切菜", "择菜"], "hint": "菜还没处理。"},
            {"id": "prep_garlic", "name": "拍蒜切蒜", "keywords": ["拍蒜", "切蒜", "蒜末", "蒜蓉", "剁蒜"], "hint": "蒜还没处理。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "fry_garlic", "name": "爆香蒜蓉", "keywords": ["爆香", "蒜蓉下锅", "炒蒜", "煸蒜"], "hint": "蒜蓉还没爆香。"},
            {"id": "stir_fry", "name": "下菜翻炒", "keywords": ["下锅", "翻炒", "炒菜"], "hint": "菜还没下锅。"},
            {"id": "season", "name": "调味", "keywords": ["加盐", "调味"], "hint": "还没调味。"},
        ],
        "optional": [
            {"id": "high_heat", "name": "大火快炒", "keywords": ["大火快炒", "猛火", "快炒"], "bonus": 1},
            {"id": "oyster_sauce", "name": "加蚝油提鲜", "keywords": ["蚝油提鲜", "淋蚝油"], "bonus": 1},
        ],
    },
    "红烧排骨": {
        "ingredients": ["排骨"],
        "required": [
            {"id": "prep", "name": "处理排骨", "keywords": ["焯水", "焯排骨", "洗排骨", "剁段"], "hint": "排骨还没焯水去血沫。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "fry", "name": "煎排骨", "keywords": ["煎排骨", "炒排骨", "排骨下锅", "煸排骨"], "hint": "排骨还没下锅煎。"},
            {"id": "aromatics", "name": "爆香料", "keywords": ["爆香", "姜片", "葱段", "八角", "桂皮"], "hint": "还没放姜葱香料爆香。"},
            {"id": "color", "name": "上色", "keywords": ["加酱油", "老抽", "上色"], "hint": "排骨还没上色。"},
            {"id": "braise", "name": "炖煮", "keywords": ["加水", "加水炖", "焖煮", "煮排骨"], "hint": "还没加水炖。"},
            {"id": "reduce", "name": "收汁", "keywords": ["收汁", "大火收", "汤汁浓"], "hint": "还没收汁。"},
        ],
        "optional": [
            {"id": "sugar_color", "name": "炒糖色", "keywords": ["冰糖", "白糖炒"], "bonus": 2},
            {"id": "slow_braise", "name": "小火慢炖", "keywords": ["小火", "慢炖", "炖四十", "炖一小"], "bonus": 1},
        ],
    },
    "排骨炖土豆": {
        "ingredients": ["排骨", "土豆"],
        "required": [
            {"id": "prep_ribs", "name": "处理排骨", "keywords": ["焯水", "焯排骨", "洗排骨"], "hint": "排骨还没焯水。"},
            {"id": "prep_potato", "name": "处理土豆", "keywords": ["切土豆", "切块", "削皮", "土豆切"], "hint": "土豆还没切块。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "fry_ribs", "name": "炒排骨", "keywords": ["炒排骨", "排骨下锅", "煎排骨", "煸排骨"], "hint": "排骨还没炒。"},
            {"id": "aromatics", "name": "爆香料", "keywords": ["爆香", "姜片", "葱段", "八角"], "hint": "还没放香料。"},
            {"id": "braise", "name": "炖排骨", "keywords": ["加水", "加水炖", "焖煮"], "hint": "还没加水炖。"},
            {"id": "add_potato", "name": "放土豆", "keywords": ["放土豆", "土豆下锅", "加土豆"], "hint": "土豆还没放，要等排骨半熟再放。"},
            {"id": "season", "name": "调味", "keywords": ["加盐", "加酱油", "调味"], "hint": "还没调味。"},
        ],
        "optional": [
            {"id": "blanch_ribs", "name": "排骨焯水去血沫", "keywords": ["去血沫", "焯出血沫", "撇沫"], "bonus": 2},
            {"id": "late_potato", "name": "土豆后放（不烂）", "keywords": ["后放", "半熟再放", "晚点放"], "bonus": 1},
        ],
    },
    "清蒸鲈鱼": {
        "ingredients": ["鲈鱼"],
        "required": [
            {"id": "prep_fish", "name": "处理鱼", "keywords": ["划刀", "抹盐", "腌鱼", "去腥", "去内脏"], "hint": "鱼还没处理。"},
            {"id": "plate", "name": "摆盘", "keywords": ["摆盘", "放盘", "铺姜", "姜片垫", "葱段垫"], "hint": "鱼还没摆盘上锅。"},
            {"id": "steam", "name": "上锅蒸", "keywords": ["上锅", "大火蒸", "入锅蒸", "水开后蒸"], "hint": "鱼还没上锅蒸。"},
            {"id": "time", "name": "蒸够时间", "keywords": ["蒸八分", "蒸十分钟", "蒸到眼白", "蒸透", "蒸8", "蒸9", "蒸10分钟", "蒸6分钟"], "hint": "蒸鱼时间不够，鱼还没熟。"},
            {"id": "sauce", "name": "浇蒸鱼豉油", "keywords": ["蒸鱼豉油", "豉油", "酱油", "浇汁"], "hint": "还没浇蒸鱼豉油。"},
            {"id": "hot_oil", "name": "浇热油", "keywords": ["热油", "浇油", "淋油"], "hint": "还没浇热油，这道灵魂。"},
        ],
        "optional": [
            {"id": "fresh_ginger", "name": "姜去腥", "keywords": ["姜丝", "姜片去腥"], "bonus": 1},
            {"id": "scallion_shred", "name": "葱丝点缀", "keywords": ["切葱丝", "摆葱丝", "葱丝垫底"], "bonus": 1},
        ],
    },
    "葱烧鲫鱼": {
        "ingredients": ["鲫鱼", "大葱"],
        "required": [
            {"id": "prep_fish", "name": "处理鱼", "keywords": ["划刀", "抹盐", "腌鱼", "去腥"], "hint": "鱼还没处理。"},
            {"id": "prep_onion", "name": "切大葱", "keywords": ["切葱", "葱段", "大葱切", "切大葱"], "hint": "大葱还没切段。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "fry_fish", "name": "煎鱼", "keywords": ["煎鱼", "煎黄", "两面煎"], "hint": "鱼还没煎。"},
            {"id": "fry_onion", "name": "煎大葱", "keywords": ["煎葱", "炒葱", "葱下锅", "煸葱"], "hint": "大葱还没煎出香味。"},
            {"id": "braise", "name": "炖煮", "keywords": ["加水", "加水炖", "焖煮"], "hint": "还没加水炖。"},
            {"id": "season", "name": "调味收汁", "keywords": ["加酱油", "收汁", "调味", "加料酒"], "hint": "还没调味收汁。"},
        ],
        "optional": [
            {"id": "fry_careful", "name": "煎鱼不破皮", "keywords": ["拍淀粉", "不急着翻", "定型"], "bonus": 2},
            {"id": "slow_braise", "name": "小火慢炖入味", "keywords": ["小火", "慢炖", "炖二十"], "bonus": 1},
        ],
    },
    "韭菜炒蛋": {
        "ingredients": ["韭菜", "鸡蛋"],
        "required": [
            {"id": "prep_leek", "name": "处理韭菜", "keywords": ["洗韭菜", "切韭菜", "切段", "韭菜切"], "hint": "韭菜还没洗切。"},
            {"id": "prep_egg", "name": "打散鸡蛋", "keywords": ["打散", "打蛋", "搅蛋", "磕蛋", "蛋液"], "hint": "鸡蛋还没打散。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "cook_egg", "name": "炒蛋", "keywords": ["炒蛋", "蛋液倒", "先炒蛋"], "hint": "鸡蛋还没下锅。"},
            {"id": "add_leek", "name": "放韭菜", "keywords": ["韭菜下锅", "放韭菜", "加韭菜", "下韭菜"], "hint": "韭菜还没下锅。"},
            {"id": "combine", "name": "合炒", "keywords": ["一起炒", "翻匀", "放回", "混合"], "hint": "蛋和韭菜还没合到一起。"},
            {"id": "season", "name": "调味", "keywords": ["加盐", "调味"], "hint": "还没调味。"},
        ],
        "optional": [
            {"id": "save_egg", "name": "蛋先盛出", "keywords": ["盛出", "盛出来", "先盛"], "bonus": 1},
            {"id": "quick_fry", "name": "韭菜快炒别过火", "keywords": ["快炒", "大火", "别炒老"], "bonus": 1},
        ],
    },
    "肉末豆腐": {
        "ingredients": ["肉末", "豆腐"],
        "required": [
            {"id": "prep_tofu", "name": "处理豆腐", "keywords": ["切块", "切丁", "豆腐切"], "hint": "豆腐还没切块。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "cook_meat", "name": "炒肉末", "keywords": ["炒肉末", "肉末下锅", "煸肉", "炒散"], "hint": "肉末还没炒。"},
            {"id": "aromatics", "name": "加酱料", "keywords": ["豆瓣酱", "酱油", "加酱", "蒜末", "姜末"], "hint": "还没加酱料调味底。"},
            {"id": "add_tofu", "name": "放豆腐", "keywords": ["豆腐下锅", "放豆腐", "加豆腐"], "hint": "豆腐还没下锅。"},
            {"id": "simmer", "name": "炖煮入味", "keywords": ["炖煮", "焖煮", "加水"], "hint": "还没炖让豆腐入味。"},
            {"id": "thicken", "name": "勾芡", "keywords": ["勾芡", "淀粉", "水淀粉", "收汁"], "hint": "还没勾芡。"},
        ],
        "optional": [
            {"id": "blanch_tofu", "name": "豆腐焯水", "keywords": ["先焯水", "焯过水", "烫过"], "bonus": 2},
            {"id": "garnish", "name": "撒葱花", "keywords": ["葱花", "撒葱", "葱末"], "bonus": 1},
        ],
    },
    "炒豆芽": {
        "ingredients": ["豆芽"],
        "required": [
            {"id": "prep", "name": "洗豆芽", "keywords": ["洗豆芽", "择洗", "去根"], "hint": "豆芽还没洗。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "aromatics", "name": "爆香料", "keywords": ["爆香", "干辣椒", "花椒", "蒜末", "葱段"], "hint": "还没放辣椒花椒爆香。"},
            {"id": "stir_fry", "name": "下豆芽翻炒", "keywords": ["下豆芽", "豆芽下锅", "翻炒", "炒豆芽"], "hint": "豆芽还没下锅。"},
            {"id": "season", "name": "调味", "keywords": ["加醋", "加盐", "调味"], "hint": "还没调味。"},
        ],
        "optional": [
            {"id": "vinegar_first", "name": "沿锅边淋醋", "keywords": ["沿锅边", "淋醋", "醋溜", "先加醋"], "bonus": 2},
            {"id": "high_heat", "name": "大火快炒", "keywords": ["大火快炒", "猛火", "快炒"], "bonus": 1},
        ],
    },
    "腐竹烧肉": {
        "ingredients": ["腐竹", "五花肉"],
        "required": [
            {"id": "prep_fuzhu", "name": "泡腐竹", "keywords": ["泡发", "泡腐竹", "泡软"], "hint": "腐竹还没泡发。"},
            {"id": "prep_meat", "name": "切肉", "keywords": ["切肉", "切片", "切块", "五花肉切"], "hint": "五花肉还没切。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "fry_meat", "name": "炒五花肉", "keywords": ["炒肉", "五花肉下锅", "煸肉", "煎肉"], "hint": "五花肉还没炒。"},
            {"id": "aromatics", "name": "爆香料", "keywords": ["爆香", "姜片", "葱段", "八角", "桂皮"], "hint": "还没放香料。"},
            {"id": "add_fuzhu", "name": "放腐竹", "keywords": ["腐竹下锅", "放腐竹", "加腐竹"], "hint": "腐竹还没放。"},
            {"id": "braise", "name": "炖煮", "keywords": ["加水", "加水炖", "焖煮"], "hint": "还没加水炖。"},
            {"id": "season", "name": "调味收汁", "keywords": ["加酱油", "加盐", "调味", "收汁"], "hint": "还没调味收汁。"},
        ],
        "optional": [
            {"id": "warm_soak", "name": "温水泡腐竹（更快更透）", "keywords": ["热水泡", "泡透"], "bonus": 1},
            {"id": "sugar_color", "name": "炒糖色", "keywords": ["冰糖", "白糖炒"], "bonus": 1},
        ],
    },
    "香菇炒青菜": {
        "ingredients": ["香菇"],
        "required": [
            {"id": "prep_mushroom", "name": "处理香菇", "keywords": ["洗香菇", "切香菇", "切片", "去根"], "hint": "香菇还没处理。"},
            {"id": "prep_veg", "name": "洗菜切菜", "keywords": ["洗菜", "切段", "切菜", "择菜"], "hint": "青菜还没处理。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "cook_mushroom", "name": "炒香菇", "keywords": ["香菇下锅", "炒香菇", "先炒香菇", "煸香菇"], "hint": "香菇还没炒。"},
            {"id": "add_veg", "name": "下青菜", "keywords": ["青菜下锅", "下青菜", "加青菜", "放菜"], "hint": "青菜还没下锅。"},
            {"id": "combine", "name": "合炒", "keywords": ["一起炒", "翻匀", "混合"], "hint": "香菇和青菜还没合到一起。"},
            {"id": "season", "name": "调味", "keywords": ["加盐", "调味"], "hint": "还没调味。"},
        ],
        "optional": [
            {"id": "oyster_sauce", "name": "加蚝油提鲜", "keywords": ["蚝油提鲜", "淋蚝油"], "bonus": 1},
            {"id": "blanch_veg", "name": "青菜先焯水", "keywords": ["先焯水", "焯过青菜", "过水焯"], "bonus": 1},
        ],
    },
    "蒜苗回锅肉": {
        "ingredients": ["蒜苗", "五花肉"],
        "required": [
            {"id": "boil_meat", "name": "煮五花肉", "keywords": ["煮肉", "焯水", "整块煮", "白煮"], "hint": "五花肉还没煮，回锅肉要先煮后炒。"},
            {"id": "prep_meat", "name": "切肉片", "keywords": ["切片", "切肉", "切薄片", "肉片"], "hint": "煮好的肉还没切片。"},
            {"id": "prep_leek", "name": "切蒜苗", "keywords": ["切蒜苗", "切段", "蒜苗切", "斜切"], "hint": "蒜苗还没切段。"},
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "fry_meat", "name": "煸炒肉片", "keywords": ["炒肉", "肉片下锅", "煸肉"], "hint": "肉片还没下锅煸炒。"},
            {"id": "douban", "name": "加豆瓣酱", "keywords": ["豆瓣酱", "豆瓣", "辣酱", "豆豉"], "hint": "还没加豆瓣酱，回锅肉没有豆瓣没有灵魂。"},
            {"id": "add_leek", "name": "下蒜苗", "keywords": ["蒜苗下锅", "下蒜苗", "放蒜苗", "加蒜苗"], "hint": "蒜苗还没下锅。"},
            {"id": "season", "name": "调味", "keywords": ["加酱油", "调味", "加糖"], "hint": "还没调味。"},
        ],
        "optional": [
            {"id": "cry_meat", "name": "肉片炒到灯盏窝（卷曲出油）", "keywords": ["灯盏窝", "煸透", "卷成窝"], "bonus": 2},
            {"id": "sweet_paste", "name": "加甜面酱", "keywords": ["甜面酱", "面酱"], "bonus": 1},
        ],
    },
    "虾皮紫菜汤": {
        "ingredients": ["虾皮", "紫菜"],
        "required": [
            {"id": "heat", "name": "热锅", "keywords": ["热锅", "倒油", "烧油"], "hint": "锅还没热。"},
            {"id": "fry_shrimp", "name": "煸炒虾皮", "keywords": ["炒虾皮", "虾皮下锅", "煸虾皮", "炒香"], "hint": "虾皮还没炒香。"},
            {"id": "add_water", "name": "加水", "keywords": ["加水", "加汤"], "hint": "还没加水，做汤要加水。"},
            {"id": "boil", "name": "烧开", "keywords": ["烧开", "煮开", "大火烧", "咕嘟"], "hint": "水还没烧开。"},
            {"id": "add_seaweed", "name": "放紫菜", "keywords": ["放紫菜", "紫菜下锅", "加紫菜", "撕紫菜"], "hint": "紫菜还没放。"},
            {"id": "season", "name": "调味", "keywords": ["加盐", "调味", "胡椒粉"], "hint": "还没调味。"},
        ],
        "optional": [
            {"id": "egg_drop", "name": "打蛋花", "keywords": ["蛋花", "打蛋花", "淋蛋液"], "bonus": 1},
            {"id": "sesame_oil", "name": "加香油", "keywords": ["香油", "淋香油", "芝麻油"], "bonus": 1},
        ],
    },
    "凉拌黄瓜": {
        "ingredients": ["黄瓜"],
        "required": [
            {"id": "prep", "name": "处理黄瓜", "keywords": ["拍黄瓜", "拍碎", "切条", "切块", "切黄瓜"], "hint": "黄瓜还没处理。拍黄瓜得先拍。"},
            {"id": "salt", "name": "杀水", "keywords": ["加盐", "杀水", "腌一下", "拌盐", "出水"], "hint": "黄瓜还没杀水，拌了盐出水才脆。"},
            {"id": "drain", "name": "沥干水分", "keywords": ["沥干", "倒水", "挤水", "控水"], "hint": "杀出来的水还没倒掉。"},
            {"id": "garlic", "name": "加蒜", "keywords": ["蒜末", "蒜蓉", "加蒜", "拍蒜", "剁蒜"], "hint": "还没加蒜，凉拌黄瓜蒜是灵魂。"},
            {"id": "season", "name": "调味", "keywords": ["加醋", "加酱油", "加糖", "调味", "加香油"], "hint": "还没调味。"},
            {"id": "toss", "name": "拌匀", "keywords": ["拌匀", "搅拌", "翻拌"], "hint": "还没拌匀。"},
        ],
        "optional": [
            {"id": "chili_oil", "name": "加辣椒油", "keywords": ["辣油", "红油", "现泼辣子"], "bonus": 1},
            {"id": "peel", "name": "去皮（口感更嫩）", "keywords": ["去皮", "削皮", "剥皮"], "bonus": 1},
        ],
    },
}
