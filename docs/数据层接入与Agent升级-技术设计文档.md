# 数据层接入与 Agent 升级技术设计文档

> 版本：v0.7.1 | 状态：定版待开发 | 日期：2026-08-06

## 1. 背景与目标

### 1.1 当前痛点

| 痛点 | 根因 |
|------|------|
| 训练计划是纯文本，无法点击看动作演示 | LLM 自由生成动作名，无结构化动作库 |
| 动作名称不固定，无法与数据源关联 | 缺少标准动作 ID |
| 用户不知道动作怎么做 | 无动图演示和分步说明 |
| 器械匹配靠 prompt 提示，不可靠 | 无后端硬过滤 |
| 伤病排除靠规则表穷举，覆盖不全 | 无 LLM 语义判断 |
| 餐食热量 100% 靠 LLM 现编 | 食物营养库丢失（知识层升级时退役） |
| 计划生成是线性管线，不是真 Agent | 工具硬编码在节点里，LLM 无法自主选择 |
| 闭环只有热量一条腿 | 训练计划和饮食计划静态，无法结构化调整 |
| 补剂完全缺失 | PRD 未覆盖，用户高频需求未承接 |

### 1.2 本次目标

1. 接入 1,324 个动作的结构化数据集（含中文说明 + 动图）
2. 接入自建食物热量库（200-300 种常见中餐）
3. 接入补剂推荐能力（结构化映射 + RAG 知识）
4. 训练计划和饮食计划从"LLM 文本"升级为"结构化 JSON"
5. 伤病过滤采用"后端粗筛 + LLM 精筛"混合方案
6. 工具注册为 LangGraph ToolNode，LLM 自主调用，从"半 Agent"升级为"真 Agent"
7. 为训练调整闭环打基础（结构化计划是调整的前提）

### 1.3 不做

- 不换数据库（SQLite 足够，数据访问层已是 SQLAlchemy ORM）
- 不做动作专用评分模型（沿用现有 MediaPipe + Vision）
- 不做教练端 / 多用户
- 不做可穿戴设备同步

---

## 2. 数据源

### 2.1 动作数据集

- 来源：https://github.com/Hmx-7488/exercises-dataset
- 规模：1,324 个动作，含 180×180 GIF 动图 + 缩略图
- 许可证：数据 MIT，媒体 © Gym visual（个人免费项目保留署名即可用）
- 裁剪策略：只保留 `zh` + `en` 语言，丢弃其余 8 种语言，体积减约 80%
- 中文名：数据集无独立中文名字段，导入时一次性 LLM 翻译 1,324 个英文名存库

### 2.2 食物热量库

- 来源：自建，手动整理 200-300 种常见中餐食材
- 依据：中国食物成分表 + 薄荷健康公开数据参考
- 覆盖：主食、蛋白质、蔬菜、水果、油脂、乳制品、饮品 7 类
- 每条含：中文名、别名、每 100g 五大营养素、常见份量、饮食标签、关联菜名

### 2.3 补剂数据

- 结构化映射：30-50 种补剂，含触发条件（triggers）、目标类型、剂量、时机、禁忌
- 知识文档：`supplements_guide.md` 进 knowledge_docs，RAG 可检索
- 许可证：自建，无第三方依赖

---

## 3. 数据库设计

### 3.1 新增表

#### exercises（动作库）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(4) PK | 数据集原始 ID，如 "0025" |
| name | String | 英文名，如 "barbell bench press" |
| name_zh | String | 中文名，导入时 LLM 翻译 |
| body_part | String | 部位：chest/back/upper arms/upper legs/waist/shoulders/... |
| equipment | String | 器械：barbell/dumbbell/body weight/cable/kettlebell/... |
| target | String | 目标肌：biceps/pectoralis major/glutes/... |
| muscle_group | String | 主协同肌 |
| secondary_muscles | Text(JSON) | 次协同肌数组 |
| difficulty | String | 后端推断：beginner/intermediate/advanced |
| instructions_zh | Text | 中文完整说明 |
| instruction_steps_zh | Text(JSON) | 中文分步数组 |
| image_path | String | 缩略图文件名 |
| gif_path | String | 动图文件名 |

#### foods（食物热量库）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增 |
| name_zh | String | 中文名，如 "鸡胸肉" |
| aliases | Text(JSON) | 别名数组，如 ["鸡胸", "鸡里脊"] |
| category | String | protein/carb/vegetable/fruit/fat/dairy/beverage |
| calories_kcal | Float | 每 100g 热量 |
| protein_g | Float | 每 100g 蛋白质 |
| carbs_g | Float | 每 100g 碳水 |
| fat_g | Float | 每 100g 脂肪 |
| fiber_g | Float | 每 100g 纤维 |
| sodium_mg | Float | 每 100g 钠 |
| default_portion_g | Float | 常见份量克数 |
| default_portion_name | String | 份量描述，如 "一块" |
| diet_tags | Text(JSON) | 标签：high_protein/low_carb/low_fat/... |
| common_dishes | Text(JSON) | 关联常见菜名数组 |

### 3.2 不建表的

- **补剂映射**：存 `backend/data/supplements/supplements_map.json`，30-50 条，读多写少，启动时加载到内存
- **补剂知识**：存 `backend/data/knowledge_docs/supplements_guide.md`，进 RAG 向量库

### 3.3 已有表改动

#### plans 表新增字段

| 字段 | 类型 | 说明 |
|------|------|------|
| workout_plan_json | Text | 结构化训练计划 JSON（新增，workout_plan 文本字段保留兼容） |
| meal_plan_json | Text | 结构化饮食计划 JSON（新增，meal_plan 文本字段保留兼容） |
| supplements_json | Text | 补剂推荐 JSON |

### 3.4 迁移策略

沿用已有增量迁移机制（`_ensure_additive_columns`）：
- `plans` 表加 3 个 Text 列（均可空，老数据无损）
- `exercises` / `foods` 表由 `create_all` 自动创建
- 数据导入在 `init_db` 后执行，检查表空则导入

---

## 4. 文件结构

```
backend/data/
├── knowledge_docs/                  # 已有 13 篇 + 新增
│   └── supplements_guide.md         # 新增：补剂详细知识
├── exercises/                       # 新增
│   ├── exercises_zh.json            # 裁剪后 1,324 条（只留 zh+en）
│   └── exercise_media/              # 1,324 GIF + 1,324 JPG（© Gym visual）
├── foods/                           # 新增
│   └── foods_zh.json                # 自建 200-300 条
└── supplements/                     # 新增
    └── supplements_map.json         # 30-50 条补剂映射
```

媒体文件不进 git 主仓库（体积约 50-100MB），用 `.gitignore` 排除，首次启动时从 GitHub Release 下载或手动放置。

---

## 5. 伤病过滤方案：后端粗筛 + LLM 精筛

### 5.1 为什么混合

- 纯规则表：穷举不完，用户伤病是开放自然语言
- 纯 LLM：可能绕过硬约束（如把杠铃动作推荐给只有哑铃的用户）
- 混合：后端保证硬约束，LLM 处理语义判断

### 5.2 流程

```
第一道：后端粗筛（SQL + 代码规则，确定性）
    WHERE equipment IN (用户可用器械)
    AND body_part IN (当日训练部位)
    AND difficulty <= 用户经验等级
    -> 候选池 A（如 50 个动作）

第二道：LLM 精筛 + 编排（一次调用）
    prompt 携带：候选池 A + 用户伤病 + 经验 + 目标
    LLM 任务：
      1. 排除对伤病不安全的动作，输出排除原因
      2. 从剩余安全动作中编排周计划
      3. 输出结构化 JSON
    -> 安全池 B + 结构化计划
```

### 5.3 LLM 精筛 prompt 设计

```
你是健身教练。根据用户伤病信息，从候选动作池中排除不安全的动作，
并用剩余动作编排一周训练计划。

用户信息：
- 目标：{goal_type}
- 经验：{training_experience}
- 伤病：{injuries}
- 每周训练天数：{training_days_per_week}
- 每次时长：{session_duration_minutes} 分钟

候选动作池（仅可从中选择）：
[0025] barbell bench press (chest, barbell, target: pectoralis major)
[0043] barbell full squat (upper legs, barbell, target: glutes)
[0294] dumbbell biceps curl (upper arms, dumbbell, target: biceps)
...

输出 JSON：
{
  "excluded": [
    {"exercise_id": "0043", "reason": "用户有膝盖伤病，深蹲加重膝关节负荷"}
  ],
  "weekly_plan": [
    {
      "day": 1,
      "theme": "胸+三头",
      "exercises": [
        {"exercise_id": "0025", "sets": 4, "reps": "8-12", "rest_seconds": 75}
      ]
    }
  ]
}

规则：
1. 只能从候选池里选 exercise_id，不能发明动作
2. 排除所有对用户伤病不安全的动作，并说明原因
3. 每天选 4-6 个动作，控制总时长在用户可训练时间内
```

### 5.4 后端校验

LLM 输出后，后端逐条校验：
- 每个 `exercise_id` 在候选池 A 中存在
- 排除的动作确实从 weekly_plan 中消失
- 每天动作数和总组数在合理范围
- 校验通过 -> 存入 `Plan.workout_plan_json`

---

## 6. 饮食计划结构化

### 6.1 流程

```
后端查 foods 表（目标热量 + 饮食偏好 + 忌口过滤）
    -> 候选食材池（按 category 均衡分配：蛋白质/主食/蔬菜/水果/油脂）
    -> LLM 编排每日餐次（结构化 JSON）
    -> 存入 Plan.meal_plan_json
```

### 6.2 食物查询逻辑

```sql
-- 按用户饮食偏好过滤
SELECT * FROM foods
WHERE diet_tags ?| ARRAY['high_protein']  -- 高蛋白偏好
AND id NOT IN (
    SELECT food_id FROM food_allergy_map
    WHERE allergy_key IN (用户过敏源)
)
-- 每类取 top N
```

忌口过滤：用户的 `forbidden_foods` 和 `allergies` 与 foods 的 `name_zh` / `aliases` 做匹配。

### 6.3 结构化输出

```json
{
  "daily_targets": {
    "calories_kcal": 1850,
    "protein_g": 150,
    "carbs_g": 180,
    "fat_g": 55
  },
  "meals": [
    {
      "meal_type": "breakfast",
      "items": [
        {"food_id": 42, "name_zh": "鸡蛋", "portion_g": 100, "calories_kcal": 144},
        {"food_id": 78, "name_zh": "燕麦", "portion_g": 40, "calories_kcal": 152}
      ],
      "meal_total": {"calories_kcal": 296, "protein_g": 20, "carbs_g": 28, "fat_g": 8}
    }
  ]
}
```

### 6.4 餐食识别锚定

```
照片 -> LLM 识别菜名
    -> 后端查 foods 表（按 name_zh / aliases / common_dishes 匹配）
    ├─ 命中：返回数据库热量（标注"数据库参考值"）
    └─ 未命中：LLM 估算（标注"估算值，未在数据库中"）
```

---

## 7. 补剂推荐方案

### 7.1 数据结构

`supplements_map.json`（结构化映射，后端按条件匹配）：

```json
[
  {
    "name": "肌酸",
    "name_en": "creatine monohydrate",
    "category": "performance",
    "triggers": ["strength", "muscle_gain", "power"],
    "goal_type": ["muscle_gain"],
    "dosage": "每天 5g",
    "timing": "任何时候，建议随餐",
    "contraindications": ["肾功能异常"]
  },
  {
    "name": "鱼油",
    "name_en": "omega-3 fish oil",
    "category": "anti_inflammatory",
    "triggers": ["anti_inflammatory", "recovery", "joint_health"],
    "goal_type": ["fat_loss", "muscle_gain"],
    "dosage": "每天 2-3g EPA+DHA",
    "timing": "随餐",
    "contraindications": ["抗凝血药物使用者"]
  }
]
```

`supplements_guide.md`（详细知识，进 RAG）：
- 每种补剂的机制、证据等级、适用人群、注意事项、与药物相互作用

### 7.2 推荐流程

```
用户档案 + 目标 + 伤病
    ↓
后端按 goal_type + 伤病关键词匹配 supplements_map.json
    -> 候选补剂列表（如：增肌 -> 肌酸、乳清蛋白；关节问题 -> 鱼油）
    ↓
LLM + RAG 检索 supplements_guide.md
    -> 生成个性化推荐文案
    -> 输出结构化 JSON：[{name, reason, dosage, timing}]
    ↓
存入 Plan.supplements_json，随计划展示
```

**结构化表负责"匹配什么"（确定性），RAG 文档负责"解释为什么"（LLM 组织语言）。**

---

## 8. Agent 升级：从管线到真 Agent

### 8.1 现状

LangGraph 工作流 9 个节点，流程是代码写死的线性管线：
```
parse -> check -> retrieve -> calc -> meal -> workout -> risk -> summarize
```
工具是硬编码在节点里的，LLM 无法自主选择调什么工具。

### 8.2 升级方向

将数据查询封装为 LangGraph Tool，注册给 LLM，让 LLM 自主决定调用顺序：

```python
@tool
def search_exercises(body_part: str, equipment: list[str], difficulty: str) -> list[dict]:
    """按部位、器械、难度搜索动作库"""
    ...

@tool
def search_foods(category: str, diet_tags: list[str]) -> list[dict]:
    """按分类和标签搜索食物库"""
    ...

@tool
def calc_calorie_tool(gender, weight, height, age, activity_level, goal_type) -> dict:
    """计算 BMR/TDEE/目标热量"""
    ...

@tool
def retrieve_knowledge_tool(query: str) -> list[str]:
    """检索专业知识库"""
    ...
```

### 8.3 升级后的计划生成流程

```
LLM（ReAct 推理）:
    "我需要先了解用户档案" -> 调用 get_user_profile
    "用户有膝盖伤病，需要查安全的腿部动作" -> 调用 search_exercises(body_part=upper legs)
    "用户只有哑铃" -> 调用 search_exercises(equipment=[dumbbell])
    "需要计算热量" -> 调用 calc_calorie_tool
    "需要查饮食原则" -> 调用 retrieve_knowledge_tool
    "现在生成计划" -> 输出结构化 JSON
```

### 8.4 分阶段实施

| 阶段 | Agent 程度 | 说明 |
|------|-----------|------|
| 当前 | 半 Agent | 线性管线，工具硬编码在节点 |
| 第一步 | Agent + 工具 | 数据查询封装为 Tool，但计划生成仍用现有管线 |
| 第二步 | 真 Agent | LLM 自主选择工具调用顺序（ReAct 循环） |

本次先做第一步（工具封装），第二步作为后续迭代。

---

## 9. API 设计

### 9.1 动作库

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/exercises` | 查询动作列表，支持 body_part/equipment/difficulty/q 过滤 |
| GET | `/api/exercises/{id}` | 获取单个动作详情（含中文说明、分步、GIF 路径） |
| GET | `/api/exercises/{id}/media/{type}` | 动图或缩略图（type=gif/image） |

### 9.2 食物库

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/foods` | 查询食物列表，支持 category/diet_tags/q 过滤 |
| GET | `/api/foods/{id}` | 获取单个食物详情 |
| GET | `/api/foods/search?dish={菜名}` | 按菜名匹配食物（用于餐食识别锚定） |

### 9.3 计划生成（改造现有）

`POST /api/plan/generate` 响应新增：
- `workout_plan_json`：结构化训练计划（含 exercise_id）
- `meal_plan_json`：结构化饮食计划（含 food_id）
- `supplements_json`：补剂推荐

`POST /api/plan/adjust-workout`（新增，后续阶段）：
- 用户确认训练调整草案后写入 `workout_plan_json`

---

## 10. 前端改造点

### 10.1 计划页（PlanView）

- 训练计划：从纯文本渲染改为结构化卡片
  - 每个动作卡片：名称 + GIF 动图 + 中文分步说明 + 组数次数休息
  - 动图可点击放大
  - 被伤病排除的动作显示灰色 + 排除原因
- 饮食计划：从纯文本渲染改为结构化卡片
  - 每餐：食材列表 + 份量 + 热量 + 营养素
  - 数据库命中的食材标注"参考值"，估算的标注"估算值"
- 补剂推荐：新增区块
  - 每种补剂：名称 + 推荐理由 + 剂量 + 时机 + 注意事项

### 10.2 建档页（ProfileView）

- 可用器械：从自由文本标签改为从数据集 12 种器械里多选
- 与 exercises 表的 equipment 枚举对齐

### 10.3 新增类型

```typescript
interface StructuredWorkoutPlan {
  excluded: { exercise_id: string; reason: string }[]
  weekly_plan: {
    day: number
    theme: string
    exercises: {
      exercise_id: string
      name_zh: string
      sets: number
      reps: string
      rest_seconds: number
      gif_url: string
      instruction_steps_zh: string[]
    }[]
  }[]
}

interface StructuredMealPlan {
  daily_targets: { calories_kcal, protein_g, carbs_g, fat_g }
  meals: {
    meal_type: string
    items: {
      food_id: number
      name_zh: string
      portion_g: number
      calories_kcal: number
      is_from_database: boolean
    }[]
    meal_total: { calories_kcal, protein_g, carbs_g, fat_g }
  }[]
}

interface SupplementRecommendation {
  name: string
  reason: string
  dosage: string
  timing: string
  contraindications: string[]
}
```

---

## 11. 媒体许可与署名

- 数据集数据（名称/部位/器械/说明文本）：MIT 许可，自由使用
- 媒体（GIF/JPG）：© Gym visual，仅 180×180 分发，必须保留署名
- 项目 `NOTICE` 文件保留署名
- 每个动作详情页底部显示 `© Gym visual`
- 个人免费项目，非商用

---

## 12. 开发里程碑

| 阶段 | 内容 | 依赖 | 预估 |
|------|------|------|------|
| 阶段 0 | 动作数据集导入 + 裁剪 + Exercise 模型 + 检索接口 + 难度推断 + 中文名翻译 | 无 | 1 天 |
| 阶段 1 | 训练计划结构化（后端粗筛 + LLM 精筛编排 + 结构化 JSON + 前端卡片渲染） | 阶段 0 | 1-2 天 |
| 阶段 2 | 食物热量库数据整理 + 导入 + Food 模型 + 检索接口 | 无（可并行） | 1-2 天 |
| 阶段 3 | 饮食计划结构化 + 餐食识别锚定 + 前端卡片渲染 | 阶段 2 | 1-2 天 |
| 阶段 4 | 补剂映射 + 知识文档 + 推荐流程 + 前端展示 | 无（可并行） | 半天 |
| 阶段 5 | 工具封装为 LangGraph Tool（第一步 Agent 升级） | 阶段 0-2 | 1 天 |
| 阶段 6 | 训练调整闭环（复用结构化计划，复盘产出调整草案 -> 确认写入） | 阶段 1 | 1-2 天 |

### 关键路径

```
阶段 0 ──> 阶段 1 ──> 阶段 6
              │
阶段 2 ──> 阶段 3
              │
阶段 4（独立）
              │
阶段 5（依赖 0-2）
```

阶段 0+1 是关键路径，做完训练侧质变；阶段 2+3 做完饮食侧质变；阶段 4 补剂补齐；阶段 5 Agent 升级；阶段 6 接上闭环第二条腿。

---

## 13. 验收标准

1. `exercises` 表有 1,324 条记录，含中文名、中文说明、GIF 路径
2. `GET /api/exercises?equipment=dumbbell&body_part=chest` 返回正确的过滤结果
3. 计划生成返回的 `workout_plan_json` 中每个 `exercise_id` 在 exercises 表中存在
4. 计划生成返回的 `excluded` 列表正确排除了用户伤病相关动作
5. 前端计划页点击动作可展开 GIF 动图 + 中文分步说明
6. `foods` 表有 200+ 条记录，含五大营养素和常见份量
7. 餐食识别命中的菜名返回数据库热量，未命中的标注"估算值"
8. 补剂推荐根据用户目标匹配，增肌推荐肌酸/乳清蛋白，关节问题推荐鱼油
9. 所有测试通过，前端构建通过
10. NOTICE 文件保留 Gym visual 署名
