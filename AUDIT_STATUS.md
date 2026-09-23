# 上下文压缩前的状态记录

> 时间：2026-07-25
> 目的：记录当前审计状态，供压缩上下文后继续修复使用

---

## 一、项目概况

- **路径**: `C:\Users\84989\Desktop\chat\出门买菜上桌吃饭`
- **类型**: 文字菜市场模拟游戏（给 AI 玩的）
- **核心文件**:
  - `market_engine.py` (~6600行) — 游戏引擎核心
  - `market_data.py` (~4100行) — 食材/摊位/事件数据
  - `mystic_engine.py` (~350行) — 神秘时空子系统
  - `mystic_data.py` (~160行) — 神秘时空数据
  - `market_recipes.py` (~500行) — 菜谱数据
  - `engine.py` (~250行) — CLI/HTTP 入口 shim
  - `market_mcp_server.py` (~250行) — MCP 服务器
  - `build_blind.py` (~100行) — base64 打包构建
  - `validate_data.py` (~200行) — 数据校验
  - `_testutil.py` (~30行) — 测试工具（临时 save 路径）
  - `上桌/` 子目录 — 另一份分叉的 market_data.py + engine.py

- **git 状态**: main 分支，已推送到 `https://github.com/yuyixuanfu/shangzhuochifan.git`
- **最新 commit**: `8ad3d20` (fix: 按 engineering-constraints-unified 扫描修复 IOE-08)

---

## 二、已完成的修复（本 session 共 8 轮 commit）

| commit | 内容 |
|---|---|
| `fdf72cc` | 初始扫 6 处（RNG 错位/visit_stall mid-visit 等） |
| `6346182` | mystic H1 maybe_recall + 3 MEDIUM |
| `5aac241` | 饺子馅补数据 + wandering stall 灾难 + 价格舍入 |
| `2d5cb5b` | 接 48 milestones + _perks 系统 |
| `dcc9705` | LOW mystic + engine 杂项 |
| `1aac190` | 最后 LOW + mystic 边界 |
| `9c3af0a` | route fallback bug + 测试 |
| `9989f5a` | from_dict(None) + stress_aggressive |
| `425b7a9` | regression test 加固 |
| `647f100` | mystic + secret area 真 bug |
| `28b361c` | cook_step 空格 + load JSON + mulberry32 |
| `ecbddff` | bargain/endtoend/state_machine 测试 |
| `e6edff5` | corner_cases 测试 |
| `76091d4` | free_item + cooking_log |
| `93e286e` | fuzzing 测试 |
| `7c7239e` | CODE-05 + FLOW-04 |
| `8ad3d20` | IOE-08 allow_nan |

---

## 三、测试矩阵（13 个测试文件，全部通过）

| 文件 | 断言/场景 |
|---|---|
| test_regression.py | 37 断言 |
| test_save_load.py | 7 断言 |
| test_mystic.py | 9 断言 |
| test_secret_ending.py | 10 断言 |
| test_cooking.py | 11 断言（有 RNG flaky） |
| test_bargain.py | 10 断言 |
| test_bargain_full.py | 10 断言 |
| test_endtoend.py | 7 断言 |
| test_state_machine.py | 11 断言 |
| test_corner_cases.py | 8 断言 |
| test_fuzzing.py | 10 断言 |
| stress_test.py | 30 轮 0 异常 |
| stress_aggressive.py | 5 场景 0 失败 |

---

## 四、逐行规范审查结果（4 路并行，101 个发现）

规范来源：
- `C:\Users\84989\Desktop\架构\ds\33_我们的纪律与约束_ds_20260920.md`（23 条纪律）
- `C:\Users\84989\Desktop\参考架构扒取\汇总\22_编码规范_分层详版_ds_20260919.md`（45 条编码规范）
- `C:\Users\84989\Desktop\opus5\docs\engineering-constraints-code-patterns.md`（错误模式手册）
- `C:\Users\84989\Desktop\opus5\docs\engineering-constraints-unified.md`（186 条统一规范）

### 4.1 market_engine.py（29 个发现：10 HIGH / 14 MEDIUM / 5 LOW）

#### HIGH

1. **[FLOW-01]** `market_engine.py:737` 等 6 处
   `int(self.rng() * len(pool)) % len(pool)` 恒为 0（rng() 返回 int，int(int*n)%n 恒 0）
   → 旅程文案/出锅旁白/保底放货/奇遇赠品全取第一个
   → 修：改 `self.rng() % len(pool)`

2. **[CODE-01]** `market_engine.py:3938`
   `_find_stall_selling` 直接下标 `STALL_BY_ID[id]`，但 ITEM_STALL_INDEX 含 SECRET_AREAS id
   → 买秘密区域食材（薄荷等）时 KeyError 崩溃
   → 修：改 `.get()` 或给 SECRET_AREAS 也建条目

3. **[FLOW-02]** `market_engine.py:1638` 等 5 处（1380/5213/6106/6167）
   流动摊 sells 是 dict（按季节）但代码按 list 做 `in` 判断
   → 流动摊买菜/捆绑/稀有/帮工全部不可达
   → 修：抽 `_stall_sells()` 统一处理 dict/list

4. **[ERR-02/ERR-05]** `market_engine.py:382-398`
   存档解析失败直接 `os.remove(SAVE_FILE)` + 当新档继续
   → 数据丢失链：写一半断电→损坏→被删
   → 修：区分三态（不存在/损坏/IO错误），损坏改名 .corrupt 保留

5. **[DATA-02]** `market_engine.py:287-374`（to_dict 字段闭合缺失）
   `_pending_chain_steps`/`_pending_help`/`_pending_interaction`/`_pending_rare`/`_per_stall_ms_triggered`/`_help_cooldown` 不序列化
   → 选择链/帮工/里程碑跨进程丢失；`_per_stall_ms_triggered` 不持久化→重复发免费菜
   → 修：to_dict/from_dict 补字段

6. **[DATA-02]** `market_engine.py:3211`
   `used_names` 只取 `pot_contents`，不含 `held_items`/`completed_dishes`
   → 做两道菜时第一道的食材被复制回冰箱
   → 修：补 `used_names.update(ks.get("held_items"))` + completed_dishes

7. **[FLOW-01]** `market_engine.py:3693`
   `last_moment` 冷却标志永不复位（True 时 return，走不到 3751 行的重置）
   → 厨房时刻每会话最多触发 1 次
   → 修：`if ks.pop("last_moment", False): return None`

8. **[FLOW-02]** `market_engine.py:3167`
   `appearance` 在 pairing/missed 扣分之前就算死
   → plate 里 appearance 与 score 矛盾
   → 修：扣分移到 appearance 判定之前

9. **[NUM-03]** `market_engine.py:668`
   `round(leftover * 10 / 2) / 10` 注释说修了 banker's rounding 但 Python round() 仍是 banker's
   → leftover=0.1 时 carry=0.0 原样复现
   → 修：`int(leftover * 10 / 2 + 0.5) / 10`

10. **[FLOW-01/04]** `market_engine.py:6397`
    `hasattr(stall, "_discount")` 对 dict 恒 False → 每次覆盖而非取最大
    且写入模块级 STALL_BY_ID → 跨局泄漏
    → 修：折扣记到 self 侧，判断用 `"_discount" not in stall`

#### MEDIUM（14 个）

- `__init__` 漏 8 个属性（player_skills/unlocked_secrets/unlocked_milestones/unlocked_hidden_recipes/owner_memory/dish_feedback/dish_history）
- NaN/Inf qty 放行（`float("nan") <= 0` 为 False）
- `_tick_time` 返回值 5 处忽略（1551/1976/5031/5335/6188/6248）
- 菜谱匹配阈值量纲错配（best_score 百分制 vs len(ingredients)-1 计数）
- `;` 批量静默截断到 8 条
- `KITCHEN_DEFAULTS` 引用污染（cook_step 原地写 item["quality"]）
- 缺料检测 if/elif 挂错层（2528-2534）
- 出锅 feedback 被 `return self._serve()` 丢弃
- `_serve` 早退路径不写 plate/不结转食材
- 选择链 3 处状态错配（chain_done 过早写入/队列清空/chat 不入队）
- `_state_command` 提示的指令没有解析分支
- `_yield_cache` 写入但无消费者
- `from_dict` 不做类型校验
- 金额 float 精确比较

#### LOW（5 个）

- 回退文案说"已刷新"但实际没刷新 weather/sold_out 等
- palate["texture"] 里塞 "doneness"/"seasoning" 键
- `remember_taste` 死代码 + 静默 return None
- `_find_stall` 子串匹配可误命中
- season 公式两处复制

---

### 4.2 mystic_engine.py + mystic_data.py + market_recipes.py（29 个：6 HIGH / 19 MEDIUM / 4 LOW）

#### HIGH

1. **[C05-DATA-02]** `mystic_engine.py:232-240`
   `exotic` 字段结转 fridge 时丢失（market_engine.py:622 也丢）
   → 修：结转时保留 exotic 字段

2. **[C05-DATA-02]** `mystic_engine.py:356-363`
   `load_state` 缺 `time_loop_pending_day`，哨兵 -1 绕过校验
   → 脏档任意天触发时间回退
   → 修：补默认值 + 校验逻辑

3. **[C23-CODE-05]** `market_recipes.py:138/111/295`
   ingredients 漏必需食材
   → 修：补全

4. **[C25-DATA-07]** `mystic_engine.py:300-303`
   链奖励失败静默吞掉（进 `_bad_chain_rewards` 死字段）
   → 修：返回可查询状态

5. **[C24-ERR-06]** `mystic_engine.py:267-271`
   `apply_exotic_serve` 空串混未知
   → 修：区分成功/失败/未知

6. **[C35-NUM-01]** 全文
   金额用 float 精确比较

#### MEDIUM（19 个，摘要）

- CODE-05 ×4：None/空/零混用多处
- CODE-03：枚举漂移
- DATA-03：空结果/失败/未知不区分
- DATA-01 ×2：契约不匹配
- DATA-02 ×2：只写不读字段
- DATA-06：时间语义
- FLOW-01：恒真条件
- FLOW-04：隐式修改输入
- DOC-02 ×2：过期注释
- MIG-04：旧字段兼容
- BND-10 ×2：前缀匹配

---

### 4.3 market_data.py（21 个：8 HIGH / 9 MEDIUM / 4 LOW）

#### HIGH

1. **[BND-07/CODE-02]** `market_data.py:257-278`
   FRAGILE_LEVEL 11 个 key 重复定义（粘贴错误），值互相覆盖
   → 花生米 2→14（KEEP_DAYS 的值串进来了）
   → 修：删重复块 + import 后断言无重复键

2. **[CODE-05]** `market_data.py:264-266`
   FRAGILE_LEVEL 值 0 越界（声明 1-3），虾/鱼杂/咸鱼永不损耗
   → 修：改入 1-3 值域（虾应为 3）

3. **[ARCH-01/CODE-02]** `market_data.py:4093-4103`
   SOLAR_TERM_EVENTS 尾部混入 11 条非节气条目（FRAGILE_LEVEL 片段错误粘贴）
   → 修：整段删除

4. **[DATA-01/CODE-02]** `market_data.py:507-511` 等
   milestone reward 键名不匹配：数据写 `{"type":"recipe","recipe":...}` 但消费者读 `reward.get("value")`
   → 3 条菜谱 + 1 个 perk 永远解不开
   → 修：统一 reward 契约

5. **[ARCH-01]** `market_data.py:3340`
   AFFECTION_MILESTONES 与 STALLS[*].milestones 重复定义，双路径各发一次奖励
   → 修：只保留一处权威

6. **[DATA-01/CODE-02]** `market_data.py:3343` 等
   4 个发放物名不在 VEGGIES（何大爷私藏鱼/菜价app/自制酱/西瓜）
   → 修：补 VEGGIES 或改走 perk/flag

7. **[CODE-03]** `market_data.py:7-10`
   season 枚举三重漂移（注释 in_season/available vs 数据 in/ok/no vs 额外 rare/great）
   → 修：收敛为统一枚举

8. **[DATA-02/MIG-03]** `market_data.py:3353`
   HIDDEN_RECIPES `unlock_stall` 只写不读——3 条菜谱不可达
   → 修：接线或删除

#### MEDIUM（9 个）

- SECRET_AREAS bought_items 数量约束忽略
- TIMED_ENCOUNTERS item_cat/qty 只写不读
- ITEM_SENSE_PREP 键名不匹配（鱼/青菜/辣椒/蘑菇 vs 实名）
- COOK_STAGES 缺"调味"分类
- SKILL_TREE trigger 死代码 + 阈值撒谎
- CHOICE_CHAINS 7 个 orphan flag + 注释错误
- tofu_1 milestone 注释基于错误事实
- WIFE_TASTE 死数据
- **两份 market_data.py 分叉**（root vs 上桌/）

---

### 4.4 engine.py + infra 5 文件（22 个：9 HIGH / 8 MEDIUM / 5 LOW）

#### HIGH

1. **[ERR-02]** `engine.py:124-133`
   `load_game` 把"损坏"和"无存档"折叠成 None → 调用方覆盖坏档
   → 修：三态返回

2. **[ERR-06]** `engine.py:136-142`
   `save_game` 非原子写 + 只捕获 OSError
   → 修：临时文件+os.replace + 补异常类型

3. **[ARCH-01]** `engine.py:42` vs `market_engine.py:78`
   存档路径两个权威实现，engine.py 不读 MARKET_SAVE_FILE
   → 修：统一到 market_engine.SAVE_FILE

4. **[CFG-02]** `engine.py:243`
   `int(os.environ.get("MARKET_PORT", 8877))` 类型转换陷阱
   → 修：集中解析函数

5. **[SEC-01]** `engine.py:245`
   HTTP API bind 0.0.0.0 无认证
   → 修：默认 127.0.0.1

6. **[CODE-02]** `market_mcp_server.py:180-184`
   读 `quality_label`/`unit` 字段不存在——菜篮展示恒空
   → 修：读真实字段 `quality`，unit 从 VEGGIES 取

7. **[IOE-11]** `build_blind.py:58-64`
   base64 exec 零完整性校验
   → 修：SHA-256 校验 + b64decode(validate=True)

8. **[DATA-07]** `validate_data.py:73-121`
   校验器缺字段直接 KeyError 崩溃
   → 修：收集错误继续

9. **[CFG-06]** `_testutil.py:11-12`
   测试隔离不保证生效（先 import market_engine 则 env var 无效）
   → 修：import 后断言 SAVE_FILE == 临时路径

#### MEDIUM（8 个）

- DATA-05：批量指令静默截断
- CFG-02：Flask seed type coercion
- REL-04：session 竞态
- FLOW-05：stdout 重包装资源风险
- LOG-02：print/logging 混用
- CODE-05：None/缺失/零混用（market_mcp_server）
- CODE-04：MCP arguments 类型校验
- BND-05：validate_data .get() 折叠缺失/空

---

## 五、修复优先级建议

按规范 1.3 规则适用顺序（安全 > 契约 > 故障 > 架构 > 风格）：

### P0：数据丢失/崩溃（必须先修）
1. `market_engine.py:382-398` — 存档删除链（ERR-02/05）
2. `engine.py:124-142` — load_game/save_game 三态 + 原子写
3. `market_engine.py:3938` — SECRET_AREAS KeyError
4. `market_data.py:257-278` — FRAGILE_LEVEL 重复键
5. `market_data.py:4093-4103` — SOLAR_TERM_EVENTS 错误粘贴

### P1：功能静默失效
6. `market_engine.py:737` 等 6 处 — rng 恒为 0
7. `market_engine.py:1638` 等 5 处 — 流动摊 sells dict/list
8. `market_engine.py:287-374` — to_dict 字段闭合
9. `market_engine.py:3211` — used_names 食材复制
10. `market_data.py:507-511` — milestone reward 键名不匹配

### P2：契约不闭合
11. `market_engine.py:6397` — _discount hasattr/全局写入
12. `market_engine.py:668` — banker's rounding
13. `market_engine.py:3693` — last_moment 永不复位
14. `market_engine.py:3167` — appearance 扣分顺序
15. `market_data.py:3340` — 重复 milestone 定义

### P3：安全/质量
16. `build_blind.py` — SHA-256 校验
17. `engine.py:245` — bind 127.0.0.1
18. `validate_data.py` — 错误收集
19. `_testutil.py` — 隔离断言
20. 其余 MEDIUM/LOW

---

## 六、注意事项

- `上桌/` 子目录有另一份分叉的 market_data.py + engine.py（ARCH-01 违规），修复时注意同步或指定唯一权威
- 测试用 `_testutil.py` 的临时 save 路径，但 engine.py 的 load_game/save_game 不走这个路径
- `market_blind.py` 在 .gitignore 里（构建产物），改源码后需跑 `python build_blind.py` 重建
- 所有测试用 `PYTHONIOENCODING=utf-8 python -X utf8 <test>.py` 运行
- cooking test 有 RNG flaky（3 次中 1-2 次失败），是预先存在的问题
