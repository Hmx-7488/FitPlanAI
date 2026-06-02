# FitPlanAI Agentic RAG 开发文档

适用对象：AI 应用开发、AI Agent 开发、Python 后端、大模型应用开发项目实现。

项目定位：基于 LLM、LangGraph、RAG、身材照片分析、多模态识别、AI 动作分析和工具调用的减脂训练与轻食规划 AI Agent。

## 1. 开发目标

FitPlanAI 的开发目标是做出一个可演示、可部署、可写进简历、可在面试中讲清楚技术链路的 AI Agent 项目。

第一版必须跑通：

```text
用户建档
-> Agent 追问缺失信息
-> 可选上传身材照片并辅助估算体脂率
-> 营养计算工具
-> 训练计划生成
-> AI 动作分析和纠错
-> 食材图片识别
-> 用户确认食材重量
-> 确认可用食材，不足时给出替代食材或购物清单
-> 轻食菜谱生成
-> 菜谱成品图或图片生成提示词
-> 结构化展示和保存
```

第二版增强：

```text
RAG 知识库
-> 每日打卡
-> 周复盘
-> 动态调整
-> 教练端摘要
```

## 2. 技术栈

### 2.1 推荐主栈

- 前端：Vue3 + Vite + Element Plus
- 后端：Python、FastAPI、Pydantic
- Agent 编排：LangGraph
- LLM：OpenAI API 或兼容 DeepSeek、通义千问等模型
- 多模态：Vision Model
- RAG：Chroma 或 FAISS
- 数据库：PostgreSQL，MVP 可先用 SQLite
- 缓存和任务状态：Redis，MVP 可暂缓
- 部署：Docker、Vercel、Railway/Render/云服务器

### 2.2 为什么这样选

| 技术 | 作用 | 面试表达 |
| --- | --- | --- |
| FastAPI | 提供 AI 后端接口 | Python 后端工程化能力 |
| Pydantic | 定义结构化输入输出 | 解决大模型输出不可控 |
| LangGraph | Agent 工作流编排 | 支持多步执行和状态管理 |
| RAG | 检索食材、动作和风险规则 | 降低幻觉，增强可解释性 |
| Vision Model | 食材图片识别 | 多模态 AI 应用能力 |
| PostgreSQL | 用户、计划、打卡持久化 | 真实业务数据建模 |
| Docker | 部署和交付 | 工程化落地能力 |

## 3. 系统架构

```text
Vue3 + Vite Frontend
  ├─ 建档表单
  ├─ 身材照片分析
  ├─ Agent 对话
  ├─ 营养计划
  ├─ 训练计划
  ├─ 动作分析
  ├─ 食材拍照
  └─ 打卡复盘

FastAPI Backend
  ├─ Profile API
  ├─ Body Photo API
  ├─ Plan API
  ├─ Vision API
  ├─ Pose Analysis API
  ├─ Recipe API
  ├─ Recipe Image API
  ├─ Check-in API
  └─ Agent API

LangGraph Agent
  ├─ parse_intent
  ├─ complete_profile
  ├─ analyze_body_photo
  ├─ calculate_macros
  ├─ retrieve_knowledge
  ├─ generate_workout
  ├─ analyze_pose
  ├─ recognize_ingredients
  ├─ confirm_ingredients
  ├─ generate_recipe
  ├─ generate_recipe_image
  ├─ risk_guardrail
  └─ summarize_response

Knowledge & Tools
  ├─ 食材营养库
  ├─ 训练动作库
  ├─ 动作标准库
  ├─ 姿态风险规则库
  ├─ 健康风险规则库
  ├─ 营养计算工具
  ├─ 身材照片分析工具
  └─ 多模态识别工具

Database
  ├─ users
  ├─ user_profiles
  ├─ body_photo_analyses
  ├─ nutrition_targets
  ├─ workout_plans
  ├─ pose_analyses
  ├─ ingredient_recognitions
  ├─ recipes
  ├─ checkins
  └─ agent_runs
```

## 4. Agent 工作流设计

### 4.1 主 Agent State

```python
class AgentState(TypedDict):
    user_id: str | None
    user_message: str | None
    image_url: str | None
    intent: str | None
    profile: dict
    missing_fields: list[str]
    body_photo_analysis: dict | None
    nutrition_target: dict | None
    retrieved_context: list[dict]
    workout_plan: dict | None
    pose_analysis: dict | None
    ingredient_result: dict | None
    confirmed_ingredients: list[dict]
    recipe_options: list[dict]
    risk_warnings: list[dict]
    final_response: dict | None
```

### 4.2 意图分类

| 意图 | 触发场景 | 后续节点 |
| --- | --- | --- |
| `create_profile` | 用户首次建档 | complete_profile |
| `analyze_body_photo` | 用户上传身材照片 | analyze_body_photo -> update_profile_assumption |
| `generate_plan` | 用户要求生成减脂计划 | calculate_macros -> retrieve_knowledge -> generate_workout |
| `analyze_pose` | 用户上传动作图片或视频 | analyze_pose -> assess_movement -> risk_guardrail |
| `recognize_food` | 用户上传食材图片 | recognize_ingredients -> confirm_ingredients |
| `generate_recipe` | 用户确认食材 | nutrition_lookup -> generate_recipe |
| `checkin` | 用户打卡 | analyze_checkin -> weekly_review |
| `qa` | 用户追问为什么 | retrieve_knowledge -> summarize_response |

### 4.3 LangGraph 节点

1. `parse_intent_node`：识别用户意图和输入类型。
2. `profile_completion_node`：检查身体数据、目标、健康限制是否完整。
3. `analyze_body_photo_node`：分析建档或打卡身材照片，辅助估算体脂率和体态特征。
4. `ask_followup_node`：生成追问问题。
5. `calculate_macros_node`：调用营养计算工具。
6. `retrieve_knowledge_node`：检索食材、训练、风险知识。
7. `generate_workout_node`：生成训练计划。
8. `analyze_pose_node`：提取人体关键点和动作基础信息。
9. `assess_movement_node`：计算关节角度、对称性、稳定性和错误项。
10. `recognize_ingredients_node`：调用多模态模型识别食材。
11. `confirm_ingredients_node`：等待用户确认重量和可用性。
12. `ingredient_gap_node`：判断现有食材是否能满足菜谱和营养目标。
13. `generate_recipe_node`：基于可用食材生成轻食方案，不足时输出替代或购物清单。
14. `generate_recipe_image_node`：为每个菜谱生成成品图 URL 或图片生成提示词。
15. `risk_guardrail_node`：检查极低热量、伤病动作、过敏食材和姿态风险。
16. `summarize_response_node`：统一输出给前端。

### 4.4 条件流

```text
parse_intent
  -> profile_completion
    -> missing_fields ? ask_followup : calculate_macros
  -> retrieve_knowledge
  -> generate_workout
  -> risk_guardrail
  -> summarize_response

recognize_ingredients
  -> confirm_ingredients
    -> user_confirmed ? ingredient_gap : ask_followup
  -> generate_recipe
  -> generate_recipe_image
  -> risk_guardrail
  -> summarize_response

analyze_body_photo
  -> update_profile_assumption
  -> summarize_response

analyze_pose
  -> assess_movement
  -> risk_guardrail
  -> summarize_response
```

## 5. 工具调用设计

### 5.1 营养计算工具

`bmr_calculator_tool`

输入：

```json
{
  "gender": "female",
  "age": 28,
  "height_cm": 165,
  "weight_kg": 62
}
```

输出：

```json
{
  "bmr_kcal": 1350,
  "formula": "mifflin_st_jeor"
}
```

`macro_planner_tool`

输入：

```json
{
  "weight_kg": 62,
  "body_fat_rate": 0.28,
  "training_days_per_week": 4,
  "tdee_kcal": 2050,
  "goal": "fat_loss"
}
```

输出：

```json
{
  "daily_calories_kcal": 1650,
  "protein_g": 112,
  "carbs_g": 150,
  "fat_g": 46
}
```

### 5.2 多模态食材识别工具

`ingredient_vision_tool`

输入：图片 URL 或图片文件。

输出：

```json
{
  "ingredients": [
    {
      "name": "chicken_breast",
      "display_name": "鸡胸肉",
      "estimated_weight_g": 150,
      "confidence": 0.92,
      "need_confirm": true
    }
  ],
  "question_to_user": "请确认鸡胸肉是否约 150g。"
}
```

### 5.3 身材照片分析工具

`body_photo_analysis_tool`

输入：用户建档或打卡时上传的正面、侧面、背面身材照片，以及身高、体重、年龄、性别等基础数据。

输出：

```json
{
  "photo_type": "profile_checkin",
  "quality_check": {
    "is_usable": true,
    "lighting": "good",
    "pose": "standard",
    "occlusion": "none"
  },
  "body_fat_estimate": {
    "estimated_range": "22%-26%",
    "confidence": 0.72,
    "note": "照片估算只能作为辅助，建议结合体脂秤、围度和体重趋势判断。"
  },
  "body_shape_analysis": {
    "fat_distribution": ["腰腹脂肪较明显", "下肢脂肪中等"],
    "muscle_base": "上肢和背部基础一般，建议增加力量训练",
    "posture_notes": ["轻微圆肩趋势"]
  },
  "training_focus": ["背部训练", "臀腿力量", "核心稳定"],
  "nutrition_suggestion": "保持中等热量缺口，优先保证蛋白质摄入和训练日碳水。"
}
```

拍摄示例要求：

- 正面、侧面、背面各一张。
- 全身入镜，摄像头与腰腹高度接近。
- 光线充足，背景干净。
- 穿着贴身运动服，避免宽松衣物遮挡轮廓。
- 保持自然站立，不刻意吸腹或摆姿势。
- 页面必须展示示例图或示意图，并提示隐私保护。

`ingredient_gap_tool`

输入：用户确认拥有的食材、营养目标、忌口、过敏源、候选菜谱。

输出：

```json
{
  "can_generate_with_available_ingredients": true,
  "missing_ingredients": [],
  "substitutions": [
    {
      "missing": "西兰花",
      "alternatives": ["菠菜", "生菜", "黄瓜"],
      "reason": "同属低热量蔬菜，可补充膳食纤维。"
    }
  ],
  "shopping_list": []
}
```

规则：

- 优先只用用户确认拥有的食材生成菜谱。
- 缺少非必要食材时，给出替代食材。
- 缺少关键蛋白质或主食时，给出最小购物清单。
- 不要直接生成依赖大量新食材的菜谱。

`recipe_image_tool`

输入：菜名、食材、烹饪方式、摆盘风格。

输出：

```json
{
  "image_url": "/uploads/recipes/grilled_chicken_broccoli_bowl.png",
  "alt": "香煎鸡胸肉西兰花能量碗成品图",
  "generation_prompt": "一份清爽的减脂轻食碗，香煎鸡胸肉切片，西兰花、玉米、番茄和水煮蛋摆盘，白色餐盘，自然光，真实食物摄影风格",
  "status": "generated"
}
```

实现策略：

- MVP 没有图片生成模型时，可以先返回 `generation_prompt` 和占位图。
- 有图片生成模型时，调用图片生成接口生成菜谱成品图。
- 图片保存到 `backend/data/uploads/recipes/`，前端通过静态资源或 API 展示。
- 每个菜谱都必须有 `image.url` 或 `image.generation_prompt`，不能只返回文字。
- 图片仅作为成品示意图，不保证与用户实际烹饪结果完全一致。

### 5.4 AI 动作分析工具

`pose_estimation_tool`

输入：动作图片、短视频或抽帧图片。

输出：

```json
{
  "media_type": "video",
  "movement_name": "wide_grip_pull_up",
  "keypoints": [
    {"name": "left_shoulder", "x": 0.42, "y": 0.31, "confidence": 0.93},
    {"name": "left_elbow", "x": 0.36, "y": 0.44, "confidence": 0.91},
    {"name": "left_wrist", "x": 0.31, "y": 0.24, "confidence": 0.89}
  ],
  "overall_confidence": 0.88
}
```

`joint_angle_tool`

输入：人体关键点。

输出：

```json
{
  "angles": [
    {"joint": "left_elbow", "angle_degree": 150},
    {"joint": "right_shoulder", "angle_degree": 141}
  ],
  "symmetry": {
    "shoulder_line_diff_degree": 4,
    "elbow_angle_diff_degree": 6,
    "symmetry_score": 97
  }
}
```

`movement_assessment_tool`

输入：动作类型、关键点、角度、动作标准规则。

输出：

```json
{
  "movement_name": "宽握引体向上",
  "score": 87,
  "standard_points": [
    "双手握距大于肩宽",
    "身体自然悬挂，核心收紧"
  ],
  "issues": [
    {
      "type": "range_of_motion",
      "severity": "medium",
      "description": "下放阶段手肘未完全伸展，动作幅度略不足。",
      "suggestion": "下放时保持控制，手臂接近伸直后再开始下一次。"
    }
  ],
  "coach_cues": ["核心收紧", "肩胛先下沉再拉", "避免身体大幅摆动"]
}
```

### 5.5 RAG 检索工具

`knowledge_retriever_tool`

输入：

```json
{
  "query": "膝盖不适 新手 减脂 下肢训练",
  "collections": ["workout_actions", "risk_rules"]
}
```

输出：

```json
{
  "documents": [
    {
      "title": "膝盖不适人群下肢训练注意事项",
      "content": "避免高冲击跳跃和大重量深蹲，优先选择臀桥、坐姿腿弯举等动作。",
      "source": "risk_rules"
    }
  ]
}
```

## 6. RAG 知识库设计

### 6.1 食材营养库

字段：

- `id`
- `name`
- `category`
- `calories_per_100g`
- `protein_per_100g`
- `carbs_per_100g`
- `fat_per_100g`
- `fiber_per_100g`
- `common_portion`
- `tags`

MVP 至少录入 50-100 个常见中国食材：鸡胸肉、鸡蛋、牛肉、虾仁、豆腐、米饭、红薯、燕麦、西兰花、菠菜、番茄、玉米等。

### 6.2 训练动作库

字段：

- `id`
- `name`
- `target_muscles`
- `equipment`
- `difficulty`
- `sets_reps_suggestion`
- `contraindications`
- `tips`

### 6.3 动作标准库

字段：

- `id`
- `movement_name`
- `target_muscles`
- `view_requirements`
- `key_joint_angles`
- `standard_points`
- `common_mistakes`
- `coach_cues`
- `risk_rules`

示例动作：

- 深蹲。
- 硬拉。
- 卧推。
- 俯卧撑。
- 引体向上。
- 划船。
- 弓步蹲。
- 平板支撑。

### 6.4 姿态风险规则库

字段：

- `id`
- `movement_name`
- `risk_type`
- `condition`
- `warning`
- `suggestion`

示例风险：

- 深蹲膝内扣。
- 硬拉腰椎过度弯曲。
- 卧推肩胛不稳定。
- 引体向上耸肩代偿。
- 俯卧撑塌腰。

### 6.5 健康风险规则库

字段：

- `id`
- `risk_type`
- `condition`
- `warning`
- `action`

示例：

```json
{
  "risk_type": "low_calorie",
  "condition": "daily_calories_kcal < 1200",
  "warning": "当前热量目标过低，可能影响基础代谢和训练状态。",
  "action": "建议提高热量或缩短热量缺口持续时间。"
}
```

## 7. API 设计

### 7.1 用户建档

`POST /api/profiles`

```json
{
  "gender": "female",
  "age": 28,
  "height_cm": 165,
  "weight_kg": 62,
  "body_fat_rate": 0.28,
  "muscle_mass_kg": 38,
  "goal": "fat_loss",
  "target_weight_kg": 55,
  "target_weeks": 12,
  "injuries": ["knee_pain"],
  "allergies": ["shrimp"]
}
```

### 7.2 生成计划

`POST /api/agent/generate-plan`

```json
{
  "user_id": "u_001",
  "training_days_per_week": 4,
  "training_location": "gym",
  "equipment": ["dumbbell", "treadmill"],
  "diet_preference": "high_protein"
}
```

### 7.3 身材照片分析

`POST /api/agent/analyze-body-photo`

请求：`multipart/form-data`，支持上传正面、侧面、背面照片。

字段：

- `user_id`
- `front_image`
- `side_image`
- `back_image`
- `scenario`：`profile` 或 `checkin`

响应：

```json
{
  "analysis_id": "body_001",
  "quality_check": {
    "is_usable": true,
    "lighting": "good",
    "pose": "standard"
  },
  "body_fat_estimate": {
    "estimated_range": "22%-26%",
    "confidence": 0.72
  },
  "training_focus": ["背部训练", "臀腿力量", "核心稳定"],
  "nutrition_suggestion": "保持中等热量缺口，优先保证蛋白质摄入。"
}
```

### 7.4 食材识别

`POST /api/agent/recognize-ingredients`

请求：`multipart/form-data` 图片文件。

响应：

```json
{
  "recognition_id": "rec_001",
  "ingredients": [
    {
      "display_name": "鸡胸肉",
      "estimated_weight_g": 150,
      "confidence": 0.92,
      "need_confirm": true
    }
  ]
}
```

### 7.5 确认食材并生成菜谱

`POST /api/agent/generate-recipes`

```json
{
  "user_id": "u_001",
  "recognition_id": "rec_001",
  "confirmed_ingredients": [
    {"name": "鸡胸肉", "weight_g": 150, "available": true},
    {"name": "西兰花", "weight_g": 200, "available": false}
  ]
}
```

响应中每个菜谱必须包含图片字段：

```json
{
  "recipes": [
    {
      "name": "香煎鸡胸肉西兰花能量碗",
      "image": {
        "url": "/uploads/recipes/grilled_chicken_broccoli_bowl.png",
        "alt": "香煎鸡胸肉西兰花能量碗成品图",
        "generation_prompt": "一份清爽的减脂轻食碗，香煎鸡胸肉切片，西兰花、玉米、番茄和水煮蛋摆盘，白色餐盘，自然光，真实食物摄影风格"
      },
      "ingredients": [],
      "steps": [],
      "nutrition": {},
      "substitutions": [],
      "shopping_list": []
    }
  ]
}
```

### 7.6 AI 动作分析

`POST /api/agent/analyze-pose`

请求：`multipart/form-data` 图片或视频文件。

可选字段：

- `movement_name`：用户选择的动作名称，如 `pull_up`、`squat`。
- `view_angle`：拍摄角度，如 `front`、`side`、`back`。

响应：

```json
{
  "analysis_id": "pose_001",
  "movement_name": "宽握引体向上",
  "score": 87,
  "pose_quality": {
    "symmetry_score": 97,
    "stability_score": 85,
    "range_of_motion_score": 82
  },
  "key_angles": [
    {
      "joint": "left_elbow",
      "angle_degree": 150,
      "status": "standard"
    }
  ],
  "issues": [
    {
      "type": "range_of_motion",
      "severity": "medium",
      "description": "下放阶段手肘未完全伸展，动作幅度略不足。",
      "suggestion": "下放时保持控制，手臂接近伸直后再开始下一次。"
    }
  ],
  "coach_cues": ["核心收紧", "肩胛先下沉再拉", "避免身体大幅摆动"],
  "risk_warnings": []
}
```

### 7.7 打卡复盘

`POST /api/checkins`

```json
{
  "user_id": "u_001",
  "date": "2026-05-18",
  "weight_kg": 61.5,
  "diet_adherence": 0.8,
  "workout_completed": true,
  "hunger_level": 3,
  "fatigue_level": 2,
  "notes": "晚上有点饿"
}
```

## 8. 数据库表设计

### 8.1 `users`

- `id`
- `nickname`
- `created_at`
- `updated_at`

### 8.2 `user_profiles`

- `id`
- `user_id`
- `gender`
- `age`
- `height_cm`
- `weight_kg`
- `body_fat_rate`
- `muscle_mass_kg`
- `bmr_kcal`
- `activity_level`
- `goal`
- `target_weight_kg`
- `target_body_fat_rate`
- `target_weeks`
- `injuries`
- `allergies`
- `diet_restrictions`
- `created_at`

### 8.3 `body_photo_analyses`

- `id`
- `user_id`
- `scenario`
- `front_image_url`
- `side_image_url`
- `back_image_url`
- `quality_json`
- `body_fat_estimate_json`
- `body_shape_analysis_json`
- `training_focus_json`
- `nutrition_suggestion`
- `created_at`

### 8.4 `nutrition_targets`

- `id`
- `user_id`
- `daily_calories_kcal`
- `protein_g`
- `carbs_g`
- `fat_g`
- `fiber_g`
- `water_ml`
- `explanation`
- `created_at`

### 8.5 `workout_plans`

- `id`
- `user_id`
- `weekly_plan_json`
- `risk_warnings_json`
- `created_at`

### 8.6 `pose_analyses`

- `id`
- `user_id`
- `movement_name`
- `media_url`
- `view_angle`
- `keypoints_json`
- `angles_json`
- `score`
- `issues_json`
- `risk_warnings_json`
- `created_at`

### 8.7 `ingredient_recognitions`

- `id`
- `user_id`
- `image_url`
- `ingredients_json`
- `confirmed_ingredients_json`
- `available_ingredients_json`
- `missing_ingredients_json`
- `status`
- `created_at`

### 8.8 `recipes`

- `id`
- `user_id`
- `recognition_id`
- `recipe_json`
- `nutrition_json`
- `image_json`
- `substitutions_json`
- `shopping_list_json`
- `created_at`

### 8.9 `checkins`

- `id`
- `user_id`
- `date`
- `weight_kg`
- `diet_adherence`
- `workout_completed`
- `hunger_level`
- `fatigue_level`
- `notes`
- `body_photo_analysis_id`
- `created_at`

### 8.10 `agent_runs`

- `id`
- `user_id`
- `intent`
- `input_json`
- `state_json`
- `output_json`
- `status`
- `error_message`
- `created_at`

## 9. 推荐目录结构

```bash
FitPlanAI/
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ api/
│  │  │  ├─ profiles.py
│  │  │  ├─ agent.py
│  │  │  ├─ checkins.py
│  │  │  └─ knowledge.py
│  │  ├─ core/
│  │  ├─ schemas/
│  │  ├─ models/
│  │  ├─ services/
│  │  ├─ tools/
│  │  ├─ graph/
│  │  ├─ rag/
│  │  └─ db/
│  ├─ data/
│  │  ├─ knowledge/
│  │  └─ vectorstore/
│  ├─ tests/
│  ├─ requirements.txt
│  └─ .env.example
├─ frontend/
│  ├─ app/
│  ├─ components/
│  ├─ lib/
│  ├─ types/
│  └─ package.json
├─ docs/
│  ├─ 减脂Agent项目需求文档.md
│  ├─ 减脂Agent-Agentic-RAG-开发文档.md
│  └─ Boss直聘AI岗位调研与FitPlanAI简历项目包装.md
├─ docker-compose.yml
└─ README.md
```

## 10. 开发里程碑

### 阶段 1：MVP 主链路

目标：跑通用户建档、可选身材照片分析、营养计算、训练计划生成。

任务：

1. 初始化 FastAPI 后端。
2. 定义 Pydantic Schema。
3. 实现用户建档接口。
4. 实现身材照片上传示例和 mock 分析接口。
5. 实现 BMR、TDEE、宏量营养素计算工具。
6. 实现基础 Agent 工作流。
7. 实现计划生成接口。
8. 前端展示营养目标和训练计划。

验收：

- 用户输入身体数据后能得到结构化营养目标和训练计划。
- 用户上传身材照片后能得到质量检查、体脂估算区间和训练重点。
- Agent 能对缺失字段进行追问。

### 阶段 2：AI 动作分析链路

目标：跑通上传动作图片/短视频并返回动作评分、关键角度、错误项和纠正建议。

任务：

1. 实现动作图片/视频上传接口。
2. 支持 mock 姿态识别结果，保证没有模型时也能演示。
3. 后续可接入 MediaPipe Pose、MoveNet 或其他姿态估计模型。
4. 实现关节角度计算工具。
5. 整理动作标准库和姿态风险规则库。
6. 生成结构化动作分析结果。
7. 保存动作分析记录。

验收：

- 用户上传动作图片或视频后，系统能返回动作评分、关键角度、错误项和纠正建议。
- 当关键点置信度不足时，系统能提示重新拍摄。

### 阶段 3：多模态轻食链路

目标：跑通拍照识别食材并生成菜谱。

任务：

1. 实现图片上传接口。
2. 接入 Vision Model。
3. 输出食材识别结构化结果。
4. 实现用户确认重量流程。
5. 实现可用食材确认。
6. 实现缺失食材判断、替代食材和购物清单。
7. 实现轻食菜谱生成工具。
8. 为每个菜谱生成图片字段：优先图片 URL，MVP 可用占位图和生成提示词。
9. 保存识别记录、菜谱结果和图片信息。

验收：

- 用户上传食材照片后，系统能返回食材、置信度和确认问题。
- 用户确认可用食材后，系统能基于已有食材生成 1-3 个轻食方案。
- 如果缺少关键食材，系统能给出替代食材或最小购物清单。
- 每个轻食方案必须包含成品图 URL 或图片生成提示词。

### 阶段 4：RAG 知识库

目标：让计划生成有知识依据。

任务：

1. 整理食材营养库。
2. 整理训练动作库。
3. 整理动作标准库。
4. 整理姿态风险规则库。
5. 整理健康风险规则库。
6. 建立向量库。
7. 在 Agent 节点中接入检索。
8. 输出引用来源或依据摘要。

验收：

- 训练计划能根据器械、伤病、目标肌群检索动作。
- 饮食建议能基于食材营养数据生成。
- 风险提醒能基于规则库触发。

### 阶段 5：打卡复盘

目标：形成连续交互闭环。

任务：

1. 实现每日打卡接口。
2. 保存饮食执行率、训练完成率、体重变化。
3. 实现周复盘 Agent。
4. 根据反馈调整热量和训练建议。
5. 前端展示趋势和调整建议。

验收：

- 用户连续打卡后，系统能输出周复盘。
- Agent 能给出下一周调整建议。

### 阶段 6：求职包装与部署

目标：项目可展示、可面试、可写简历。

任务：

1. 完成 README。
2. 增加架构图和流程图。
3. 增加接口示例。
4. 增加项目截图。
5. Docker 化部署。
6. 准备 1 分钟和 3 分钟项目介绍。

验收：

- GitHub 首页能看懂项目价值。
- 本地一条命令启动主要服务。
- 面试中能讲清 Agent、RAG、工具调用和多模态链路。

## 11. 测试与评估

### 11.1 单元测试

- BMR 计算。
- TDEE 计算。
- 宏量营养素分配。
- 风险规则触发。
- 食材营养换算。

### 11.2 Agent 测试用例

1. 用户缺失体脂率，Agent 应追问或给出可选估算方式。
2. 用户膝盖不适，训练计划不应包含跳跃类高冲击动作。
3. 用户对虾过敏，菜谱不应推荐虾仁。
4. 用户上传动作图片或视频，系统应返回动作评分、关键角度和纠正建议。
5. 用户上传身材照片，系统应提示体脂率为估算值，并给出训练重点。
6. 用户上传食材图片，系统应要求确认重量和是否可用。
7. 用户没有某些食材时，系统应给出替代食材或购物清单。
8. 用户目标热量过低，系统应提示风险。

### 11.3 输出质量评估

- 结构化字段完整率。
- Agent 追问准确率。
- 食材识别确认率。
- 计划可执行性。
- 风险提醒召回率。

## 12. 面试表达重点

### 12.1 一句话介绍

FitPlanAI 是一个基于 LLM 和 LangGraph 的减脂训练、动作分析与轻食规划 AI Agent，支持用户建档、营养计算、训练计划生成、AI 动作分析、食材图片识别、轻食菜谱生成和打卡复盘。

### 12.2 技术亮点

1. 用 LangGraph 将单次问答拆成多节点 Agent 工作流，实现多步执行和状态管理。
2. 将营养计算、食材识别、菜谱生成、动作检索和风险校验封装为工具，提升系统可维护性。
3. 使用结构化输出约束模型返回结果，保证前端展示和数据库持久化稳定。
4. 引入 RAG 知识库，检索食材营养、训练动作、动作标准和健康风险规则，降低模型幻觉。
5. 接入多模态模型识别食材图片和训练动作图片/视频，并通过用户确认和置信度机制降低识别误差。

### 12.3 可讲难点

- 如何处理用户输入不完整。
- 如何防止大模型直接生成错误营养数值。
- 如何让图片识别结果进入后续业务流程。
- 如何对训练动作进行关键点检测、角度计算和规则化纠错。
- 如何做健康风险边界。
- 如何让 Agent 输出可存储、可追踪、可复盘。

## 13. 不做事项

1. 第一版不做复杂多 Agent 协作。
2. 第一版不做疾病治疗方案。
3. 第一版不接可穿戴设备。
4. 第一版不做教练端 CRM。
5. 第一版不追求复杂 UI，优先保证主链路可演示。

## 14. 最终交付标准

最低标准：

- 能建档。
- 能生成营养目标。
- 能生成训练计划。
- 能识别食材图片。
- 能生成轻食菜谱。
- 能讲清 Agent 工作流。

较好标准：

- 有 RAG 知识库。
- 有每日打卡和周复盘。
- 有风险规则。
- 有 README、架构图和截图。

最佳标准：

- 有在线部署地址。
- 有 Docker 启动方式。
- 有自动化测试。
- 能作为 AI Agent 项目直接写进简历并演示。

---

## 15. 新增饮食需求补充：餐食识别与中国饮食计划

### 15.1 两个相似需求的区别

新增需求分为两个模块，它们都属于饮食 Agent，但用户场景不同，不能混成一个功能。

| 模块 | 用户拍的是什么 | 解决的问题 | 输出 |
| --- | --- | --- | --- |
| 餐食热量识别 | 已经吃了或准备吃的成品餐 | 记录每餐摄入，计算每日热量缺口 | 本餐热量、三大营养素、当日剩余额度、热量缺口 |
| 食材轻食生成 | 家里现有的未烹饪或半成品食材 | 不知道这些食材怎么做成减脂餐 | 轻食菜谱、烹饪步骤、营养估算 |
| 中国饮食计划 | 不一定拍照，用户选择地域/口味/场景/时间 | 饮食计划不贴近中国饮食，备餐太费时间 | 家常/外卖/食堂/便利店方案 |

### 15.2 餐食热量识别 Agent

目标：用户上传每餐照片后，系统识别菜品、主食、饮品和大致份量，估算本餐摄入，并结合当天营养目标计算每日热量缺口。

流程：

```text
用户上传已吃餐食照片
-> meal_vision_tool 识别菜品、份量、烹饪方式
-> 返回热量、蛋白质、碳水、脂肪估算
-> 用户确认或修正菜品和份量
-> 保存 meal_log
-> 汇总当日摄入
-> daily_deficit_tool 计算剩余可摄入和热量缺口
-> 返回当天饮食建议
```

新增工具：

| 工具名 | 输入 | 输出 | 说明 |
| --- | --- | --- | --- |
| `meal_vision_tool` | 餐食图片 | 菜品、份量、热量、宏量营养素、置信度 | 识别已经吃了什么 |
| `confirm_meal_tool` | 用户修正后的菜品和份量 | 确认后的本餐摄入 | 降低图片识别误差 |
| `daily_deficit_tool` | TDEE、目标热量、运动消耗、当日摄入 | 剩余热量、当前缺口、状态、建议 | 计算每日热量缺口 |

结构化输出示例：

```json
{
  "meal_type": "lunch",
  "items": [
    {
      "dish_name": "番茄炒蛋",
      "estimated_portion_g": 220,
      "calories_kcal": 260,
      "protein_g": 14,
      "carbs_g": 12,
      "fat_g": 18,
      "confidence": 0.82,
      "need_confirm": true
    },
    {
      "dish_name": "米饭",
      "estimated_portion_g": 180,
      "calories_kcal": 210,
      "protein_g": 4,
      "carbs_g": 47,
      "fat_g": 1,
      "confidence": 0.9,
      "need_confirm": true
    }
  ],
  "meal_total": {
    "calories_kcal": 470,
    "protein_g": 18,
    "carbs_g": 59,
    "fat_g": 19
  },
  "daily_summary": {
    "daily_target_kcal": 1650,
    "estimated_tdee_kcal": 2050,
    "exercise_burn_kcal": 250,
    "consumed_kcal": 1380,
    "remaining_target_kcal": 270,
    "current_deficit_kcal": 920,
    "status": "deficit_too_large",
    "suggestion": "今天缺口偏大，建议晚餐或加餐补充 250-350 kcal，优先选择高蛋白和适量碳水。"
  },
  "question_to_user": "请确认米饭约为一小碗，番茄炒蛋是否为普通家常做法。"
}
```

新增 API：

- `POST /api/agent/recognize-meal`：上传餐食图片，返回识别结果。
- `POST /api/agent/confirm-meal`：用户确认菜品和份量后，保存本餐记录并更新当日热量缺口。
- `GET /api/meals/{user_id}/daily-summary?date=YYYY-MM-DD`：查询当天摄入和缺口。

新增数据库表：

```text
meal_logs
- id
- user_id
- date
- meal_type
- image_url
- recognized_items_json
- confirmed_items_json
- meal_total_json
- created_at

daily_calorie_summaries
- id
- user_id
- date
- target_kcal
- tdee_kcal
- exercise_burn_kcal
- consumed_kcal
- remaining_target_kcal
- current_deficit_kcal
- status
- suggestion
- created_at
```

### 15.3 中国饮食习惯省时计划 Agent

目标：饮食计划不能只推荐鸡胸肉、西兰花、燕麦这类单一轻食，要结合中国地域、口味、外卖、食堂、家常菜和备餐时间，生成更容易执行的方案。

流程：

```text
用户选择地域、口味、饮食场景和备餐时间
-> 检索中国菜品热量库和地域饮食库
-> 结合用户每日热量与三大营养素目标
-> 生成家常版、外卖版、食堂版、便利店版方案
-> 输出每餐热量估算、蛋白质、碳水、脂肪和点餐/备餐建议
```

新增知识库：

| 知识库 | 内容 | 用途 |
| --- | --- | --- |
| `chinese_dishes` | 常见家常菜、外卖、食堂菜、便利店组合的热量和营养估算 | 生成贴近中国饮食的餐单 |
| `chinese_regions` | 南方、北方、川湘、粤式、江浙、西北等地域饮食习惯 | 根据地域和口味做替换 |
| `quick_meals` | 5 分钟、15 分钟、30 分钟内可完成的餐食组合 | 降低备餐时间 |

新增工具：

| 工具名 | 输入 | 输出 | 说明 |
| --- | --- | --- | --- |
| `chinese_meal_retriever_tool` | 地域、场景、口味、热量目标 | 相关菜品和替换建议 | RAG 检索 |
| `chinese_meal_planner_tool` | 用户目标、地域、备餐时间、饮食场景 | 中式省时饮食计划 | 生成计划 |

结构化输出示例：

```json
{
  "region_preference": "south_china",
  "scenario": "workday",
  "prep_time_limit_minutes": 15,
  "meals": [
    {
      "meal_type": "breakfast",
      "option": "无糖豆浆 + 茶叶蛋 + 全麦馒头半个",
      "scenario": "convenience_store",
      "prep_time_minutes": 5,
      "nutrition": {
        "calories_kcal": 360,
        "protein_g": 24,
        "carbs_g": 42,
        "fat_g": 10
      }
    },
    {
      "meal_type": "lunch",
      "option": "食堂两荤一素：米饭半碗 + 清蒸鱼/鸡胸肉 + 青菜，少油少汁",
      "scenario": "canteen",
      "prep_time_minutes": 0,
      "nutrition": {
        "calories_kcal": 560,
        "protein_g": 42,
        "carbs_g": 55,
        "fat_g": 18
      }
    }
  ],
  "shopping_or_ordering_tips": [
    "优先选择清蒸、白灼、炖煮",
    "盖饭类让商家米饭减半、酱汁分开",
    "麻辣烫选择清汤，少丸子，多瘦肉、豆制品和蔬菜"
  ]
}
```

新增 API：

- `POST /api/agent/generate-chinese-meal-plan`：生成中式省时饮食计划。
- `POST /api/knowledge/search-chinese-meals`：检索中国菜品和地域饮食知识。

### 15.4 开发优先级调整

新的饮食模块建议按以下优先级实现：

1. P0：餐食图片识别、用户确认、本餐摄入估算、每日热量缺口计算。
2. P0：现有食材图片识别、用户确认、轻食菜谱生成。
3. P1：中国菜品热量库和省时饮食计划。
4. P1：中国地域饮食库、外卖/食堂/便利店替代方案。
5. P2：更细的钠、糖、油脂估算和餐食图片历史分析。

### 15.5 面试表达

这两个模块可以这样讲：

```text
饮食部分拆成两个多模态链路：一个是“餐食识别”，用于识别用户已经吃了什么，估算每餐摄入并计算每日热量缺口；另一个是“食材识别”，用于识别用户现有食材，生成轻食菜谱。为了提升中国用户的可执行性，我又设计了中国菜品热量库和地域饮食库，让 Agent 能根据外卖、食堂、家常菜和备餐时间生成更贴近中国饮食习惯的减脂计划。
```

---

## 16. 新增开发要求：减脂/增肌目标与菜谱图片

### 16.1 目标类型字段

用户档案、计划生成、营养计算、训练计划和复盘都需要增加目标类型：

```json
{
  "goal_type": "fat_loss"
}
```

支持枚举：

- `fat_loss`：减脂。
- `muscle_gain`：增肌。

后端 Schema 建议：

```python
class GoalType(str, Enum):
    fat_loss = "fat_loss"
    muscle_gain = "muscle_gain"
```

### 16.2 营养计算差异

`macro_planner_tool` 需要根据 `goal_type` 使用不同策略：

减脂：

- `target_calories = TDEE * 0.75-0.90`
- 蛋白质 `1.6-2.2g/kg`
- 脂肪不低于总热量 `20%`
- 碳水使用剩余热量计算

增肌：

- `target_calories = TDEE * 1.05-1.15`
- 蛋白质 `1.8-2.4g/kg`
- 脂肪约总热量 `20%-30%`
- 碳水优先保障训练表现

输出需要包含：

```json
{
  "goal_type": "muscle_gain",
  "daily_calories_kcal": 2600,
  "protein_g": 150,
  "carbs_g": 330,
  "fat_g": 72,
  "strategy": "lean_bulk",
  "explanation": "增肌期在 TDEE 基础上设置轻度热量盈余。"
}
```

### 16.3 训练计划差异

训练计划生成节点需要根据 `goal_type` 切换 Prompt 和规则。

减脂训练：

- 力量训练保肌。
- 有氧增加消耗。
- 控制训练容量，避免恢复不足。

增肌训练：

- 以渐进超负荷为核心。
- 增加肌群训练容量。
- 优先输出训练动作、组数、次数、RPE、进阶方式。
- 有氧只作为辅助。

### 16.4 复盘差异

减脂复盘：

- 关注热量缺口是否过大或过小。
- 关注体重下降速度。
- 关注围度和体脂变化。

增肌复盘：

- 关注热量盈余是否足够。
- 关注蛋白质是否达标。
- 关注体重增长速度是否过快。
- 关注力量表现和训练恢复。

### 16.5 菜谱图片字段

`RecipeItem` 需要增加图片字段：

```json
{
  "image": {
    "url": "/uploads/recipes/example.png",
    "alt": "菜谱成品图",
    "generation_prompt": "真实食物摄影风格的高蛋白轻食餐，白色餐盘，自然光"
  }
}
```

MVP 实现策略：

1. 先为所有菜谱返回默认占位图 URL。
2. 同时生成 `generation_prompt`。
3. 后续如接入图片生成模型，再替换为真实生成图。
4. 前端菜谱卡片必须展示图片或占位图。

### 16.6 验收标准

1. 用户选择减脂时，系统生成热量缺口、保肌力量训练和适量有氧计划。
2. 用户选择增肌时，系统生成热量盈余、渐进超负荷训练和高蛋白高碳水计划。
3. 同一个用户数据在不同目标下，饮食计划和训练计划明显不同。
4. 每个菜谱卡片都有图片 URL 或占位图，并包含图片生成提示词。

---

## 17. 实现状态总览（v0.5.0）

### 17.1 已完整实现

| 模块 | 功能 | 说明 |
| --- | --- | --- |
| 用户建档 | 基础身体数据 | 性别、年龄、身高、体重、体脂率、活动水平、饮食偏好 |
| 用户建档 | 目标类型 | 减脂/增肌选择，影响全链路 |
| 用户建档 | 训练条件 | 每周训练天数、每次时长、训练地点、可用器械、训练经验、偏好时间 |
| 用户建档 | 中国饮食习惯 | 地域口味、饮食场景（自己做饭/外卖/食堂/便利店）、备餐时间限制 |
| 计划生成 | LangGraph 工作流 | 9 节点含条件分支，使用训练条件和饮食习惯字段 |
| 营养计算 | BMR/TDEE/宏量 | Mifflin-St Jeor 公式，目标类型分支 |
| 训练计划 | 个性化生成 | 根据训练地点、器械、经验、时长、每周天数定制 |
| 饮食计划 | 场景化生成 | 根据地域口味、饮食场景、备餐时间生成 |
| 风险校验 | 5 项检查 | 热量安全、伤病禁忌、过敏食材、减重速度、LLM 审计 |
| 食材识别 | Vision Model | 多模态识别食材和重量 |
| 菜谱生成 | 轻食方案 | 2-3 个方案，含热量、宏量营养素、做法 |
| 菜谱结构 | 替代食材+购物清单 | 自动检测缺少食材，给出替代建议 |
| 菜谱图片 | 占位图+生成提示词 | 每个菜谱有 generation_prompt |
| 餐食识别 | 热量估算 | Vision Model 识别已吃菜品，估算热量 |
| 每日缺口 | 热量汇总 | 当日摄入、剩余配额、缺口状态、调整建议 |
| RAG 检索 | 7 篇知识文档 | Chroma 向量库，语义检索+降级关键词匹配 |
| 每日打卡 | 饮食运动记录 | 日期、饮食、运动、体重、备注 |
| AI 复盘 | 分析+建议 | 目标类型分支，复盘总结+次日调整建议 |
| 前端 | 10 个页面 | 首页、建档、分析、计划、食材、餐食、身材、动作、打卡、复盘 |

### 17.2 Mock 实现（后续替换）

| 模块 | 当前实现 | 计划替换为 |
| --- | --- | --- |
| 身材照片分析 | 返回基于 BMI 粗略估算的体脂率范围 | 接入真实体态分析模型（如体脂率估算 CNN） |
| AI 动作分析 | 返回预设的动作评分和问题项 | 接入 MediaPipe Pose / MoveNet 姿态估计模型 |

### 17.3 规划中未实现

| 模块 | 说明 | 优先级 |
| --- | --- | --- |
| 中国菜品热量库 | 常见家常菜、外卖、食堂菜的热量数据 | P1 |
| 地域饮食库 | 南方/北方/川湘/粤式饮食习惯知识 | P1 |
| 菜谱成品图生成 | 接入图片生成模型生成真实菜品图 | P2 |
| 打卡围度记录 | 腰围、臀围等围度数据追踪 | P2 |
| 身材照片对比 | 前后身材照片对比展示 | P2 |
| 食材缺口智能分析 | ingredient_gap_tool，基于营养目标判断食材是否充足 | P2 |
