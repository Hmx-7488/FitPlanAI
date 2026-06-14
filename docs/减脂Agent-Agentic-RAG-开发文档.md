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

## 17. 实现状态总览（v0.7.0）

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
| RAG 知识层 | 专业混合检索 | 9 篇文档 43 知识块，7 域 5 级证据，向量+关键词+重排序 |
| RAG 业务接入 | 工作流精准检索 | 饮食/训练/风险节点独立 SearchQuery，按目标和伤病过滤 |
| RAG 管理 API | 知识库运维 | rebuild / search / status / documents / evaluate 五个端点 |
| RAG 评估 | 自动化评估集 | 10 个测试用例，覆盖减脂/增肌/饮食/训练/风险/证据不足 |
| 每日打卡 | 饮食运动记录 | 日期、饮食、运动、体重、备注 |
| AI 复盘 | 分析+建议 | 目标类型分支，复盘总结+次日调整建议 |
| 身材照片分析 | 多角度 Vision 分析 | 正面/侧面/背面可选上传，综合分析并提供档案数据降级 |
| AI 动作分析 | 图片/视频 Vision 分析 | 支持关键帧、结构化问题、评分、风险和纠正建议 |
| 前端 | 10 个页面 | 首页、建档、分析、计划、食材、餐食、身材、动作、打卡、复盘 |

### 17.2 当前模型边界与后续增强

| 模块 | 当前实现 | 后续增强 |
| --- | --- | --- |
| 身材照片分析 | Vision Model 综合多角度照片，失败时基于档案数据降级 | 经过标注数据验证的体脂或体态专用模型 |
| AI 动作分析 | Vision Model 分析图片和视频关键帧 | MediaPipe Pose / MoveNet 等关键点模型，用于可计算角度和轨迹 |

当前 Vision Model 输出属于辅助判断。系统不得把模型推测描述为医学测量结果，也不得在没有真实关键点数据时伪造骨架坐标或精确关节角度。

### 17.3 规划中未实现

| 模块 | 说明 | 优先级 |
| --- | --- | --- |
| 菜谱成品图生成 | 接入图片生成模型生成真实菜品图 | P2 |
| 打卡围度记录 | 腰围、臀围等围度数据追踪 | P2 |
| 身材照片对比 | 前后身材照片对比展示 | P2 |
| 食材缺口智能分析 | ingredient_gap_tool，基于营养目标判断食材是否充足 | P2 |
| 上下文聊天 Agent | 页面级问答 + 全局聊天入口 | P1 |
| 动作分析 RAG 接入 | 动作分析纠正建议接入知识层 | P2 |
| 身材分析 RAG 接入 | 身材分析后的训练与饮食建议接入知识层 | P2 |

## 18. 专业 RAG 知识层实现（v0.7.0）

### 18.1 架构概览

将原有”7 篇本地 Markdown + Chroma 语义检索”升级为结构化、可追溯、可评估的专业知识层。

```text
知识文档（YAML frontmatter + Markdown）
→ indexer.py 解析 frontmatter + 按标题语义分块
→ models.py Pydantic 校验（来源、证据等级、适用条件）
→ vectorstore.py Chroma 向量索引（安全重建 tmp→verify→swap）
→ keyword_index.py BM25 关键词索引（中文 bigram 分词）
→ retriever.py 混合检索（向量+关键词+合并+重排序）
→ workflow.py 业务节点按目标/伤病/类别精准检索
→ evaluate.py 自动化评估集
```

### 18.2 知识域与证据等级

7 个知识域：

| 域 | 说明 |
| --- | --- |
| `fat_loss_standards` | 热量缺口、减重速度、蛋白质、平台期和恢复 |
| `muscle_gain_standards` | 热量盈余、增重速度、训练容量和渐进超负荷 |
| `nutrition_planning` | 宏量营养素、餐次安排、训练前后饮食和食材替换 |
| `chinese_meals` | 家常菜、外卖、食堂、便利店和地域饮食 |
| `training_principles` | 频率、容量、强度、RPE/RIR、恢复和周期安排 |
| `exercise_technique` | 动作阶段、拍摄要求、常见错误和纠正提示 |
| `risk_rules` | 伤病、过敏、特殊人群、极端热量和训练风险 |

5 级证据等级：

| 等级 | 说明 | 要求 |
| --- | --- | --- |
| `guideline` | 权威指南 / 行业标准 | 必须有来源 |
| `research` | 研究文献 / 实验数据 | 必须有来源 |
| `expert` | 专家建议 / 教练经验 | 建议有来源 |
| `community` | 社区经验 / 常见做法 | 无要求 |
| `internal` | 项目内部规则 | 无要求 |

### 18.3 数据模型

KnowledgeDocument（文档元数据）：

```python
class KnowledgeDocument(BaseModel):
    document_id: str          # 基于内容哈希的稳定 ID
    title: str
    category: KnowledgeCategory
    source_name: str
    source_url: str
    published_at: Optional[date]
    reviewed_at: Optional[date]
    evidence_level: EvidenceLevel
    version: str
    status: DocStatus
    content_hash: str
    chunk_count: int
```

KnowledgeChunk（检索最小单元）：

```python
class KnowledgeChunk(BaseModel):
    chunk_id: str             # 基于内容哈希的稳定 ID
    document_id: str
    title: str
    content: str
    topic: str
    goal_types: list[GoalType]
    audiences: list[Audience]
    applicable_conditions: list[str]
    contraindications: list[str]
    tags: list[str]
    category: KnowledgeCategory
    evidence_level: EvidenceLevel
    source_name: str
    source_url: str
    content_hash: str
```

SearchQuery（检索请求）：

```python
class SearchQuery(BaseModel):
    query: str
    goal_type: Optional[GoalType]
    current_page: str
    training_level: Optional[str]
    dietary_restrictions: list[str]
    injuries: list[str]
    categories: list[KnowledgeCategory]
    top_k: int = 5
```

ID 生成规则：`make_stable_id()` 基于 SHA-256 哈希，相同内容永远生成相同 ID。`content_hash()` 用于去重判断。

### 18.4 知识文档

9 篇专业知识文档，43 个知识块：

| 文档 | 域 | 证据等级 | 知识块 |
| --- | --- | --- | --- |
| 减脂核心原则 | fat_loss_standards | guideline | 5 |
| 减脂蛋白质摄入 | fat_loss_standards | research | 4 |
| 增肌营养指南 | muscle_gain_standards | guideline | 4 |
| 膳食计划指南 | nutrition_planning | guideline | 3 |
| 中国饮食指南 | chinese_meals | expert | 6 |
| 训练原则 | training_principles | guideline | 7 |
| 动作技术指南 | exercise_technique | expert | 5 |
| 健康风险规则 | risk_rules | guideline | 5 |
| 运动风险规则 | risk_rules | guideline | 4 |

文档格式（YAML frontmatter + Markdown）：

```markdown
---
title: 减脂核心原则
category: fat_loss_standards
source_name: ACSM Guidelines
source_url: https://www.acsm.org
published_at: 2024-01-01
reviewed_at: 2026-06-10
evidence_level: guideline
version: “1.0”
status: active
tags: [fat_loss, calorie_deficit, safe_weight_loss]
goal_types: [fat_loss]
audiences: [general]
---

## 热量缺口与安全减重

知识正文...
```

### 18.5 导入与索引

`indexer.py` 处理流程：

1. 解析 YAML frontmatter（正则 `^---\s*\n(.*?)\n---\s*\n`）。
2. 构建 KnowledgeDocument，校验证据等级与来源一致性。
3. 按 `##` 和 `###` 标题语义分块，每个块继承文档元数据。
4. 从标题和正文关键词推断 `goal_types`（减脂/增肌/通用）。
5. 内容哈希去重，跳过已存在的块。

`vectorstore.py` 安全重建模式：

```text
1. 在 vectorstore_tmp/ 构建新索引
2. 验证文档数量 ≥ 1
3. 关闭旧 store 释放文件锁（Windows 兼容）
4. 旧目录 → vectorstore_backup/
5. tmp → vectorstore/
6. 重新打开新 store
7. 删除 backup
```

失败时自动回滚：删除 tmp，恢复 backup。

DashScope embedding API 兼容处理：

- `check_embedding_ctx_length=False`：DashScope 不接受 token IDs，需直接传文本。
- `chunk_size=10`：DashScope embedding API 限制 batch size ≤ 10。

`keyword_index.py` BM25 索引：

- 参数：k1=1.5, b=0.75。
- 分词：非字母数字 + CJK 字符切分 + 中文 bigram。
- IDF 加权 + 文档长度归一化。

### 18.6 混合检索

`retriever.py` HybridRetriever 检索流程：

```text
SearchQuery
→ 构建 Chroma 元数据过滤器（categories）
→ 向量召回（2×top_k，Chroma 过滤）
→ 关键词召回（2×top_k，分数 /10 归一化，按 categories 过滤）
→ 按 chunk_id 合并去重（取较高分，标记 vector/keyword/hybrid）
→ 重排序 + 硬过滤：
    硬排除：伤病禁忌命中 contraindications 的知识块直接移除
    +0.10  goal_type 匹配
    +0.02  general 通用匹配
    +0.05  guideline 证据等级
    +0.03  research 证据等级
    +0.01  expert 证据等级
    +0.08  category 匹配
→ 截断 top_k
→ insufficient_evidence 检测（阈值 0.15）
→ 返回 SearchResult（含 category 字段）
```

伤病禁忌处理：命中 contraindications 的知识块从结果中直接排除（硬过滤），而非仅扣分。

返回结构：

```json
{
  “query”: “减脂期每天应该摄入多少热量”,
  “documents”: [
    {
      “chunk_id”: “chk_xxx”,
      “title”: “热量缺口范围”,
      “content”: “安全热量缺口 300-500 kcal...”,
      “category”: “fat_loss_standards”,
      “source_name”: “ACSM Guidelines”,
      “evidence_level”: “guideline”,
      “score”: 0.908,
      “retrieval_method”: “hybrid”
    }
  ],
  “insufficient_evidence”: false,
  “total_candidates”: 30,
  “retrieval_time_ms”: 120.5
}
```

### 18.7 业务接入

工作流 `workflow.py` 中三个节点已接入混合检索：

1. `retrieve_knowledge_node`：按业务域独立检索。

```python
# 饮食知识 → nutrition_planning + chinese_meals
food_sq = SearchQuery(
    query=f”食材热量 蛋白质 {diet_preference}”,
    goal_type=goal_enum,
    injuries=injuries,
    categories=[KnowledgeCategory.nutrition_planning, KnowledgeCategory.chinese_meals],
    top_k=3,
)

# 运动知识 → exercise_technique + training_principles
exercise_sq = SearchQuery(
    query=f”运动训练 动作技术 {activity_level}”,
    goal_type=goal_enum,
    injuries=injuries,
    categories=[KnowledgeCategory.exercise_technique, KnowledgeCategory.training_principles],
    top_k=3,
)

# 核心原则 → fat_loss_standards 或 muscle_gain_standards
diet_sq = SearchQuery(
    query=diet_query_text,
    goal_type=goal_enum,
    categories=diet_cats,
    top_k=3,
)

# 风险知识 → risk_rules
risk_sq = SearchQuery(
    query=” “.join(risk_parts),
    injuries=injuries,
    categories=[KnowledgeCategory.risk_rules],
    top_k=4,
)
```

2. `review_retrieve_knowledge`：复盘节点按目标类型检索调整建议。

3. 向后兼容：`retrieve_knowledge(query, k)` 旧接口内部调用 HybridRetriever，`vision_service.py` 和 `calorie_tools.py` 无需修改。

4. 引用返回：`retrieve_knowledge_node` 收集去重后的引用来源（chunk_id、title、category、source_name、source_url、evidence_level、score），通过 `AgentState.knowledge_citations` 传递，最终在 `run_workflow` 响应中返回。

### 18.8 知识管理 API

| 端点 | 方法 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `/api/knowledge/search` | POST | 公开 | 混合检索，支持 SearchQuery 全字段 |
| `/api/knowledge/status` | GET | 公开 | 索引状态（文档数、知识块数、分类统计） |
| `/api/knowledge/rebuild` | POST | 需 X-Admin-Key | 重建向量+关键词索引 |
| `/api/knowledge/documents` | GET | 需 X-Admin-Key | 列出所有知识文档元数据 |
| `/api/knowledge/evaluate` | POST | 需 X-Admin-Key | 运行评估套件 |

鉴权说明：管理接口需在请求头携带 `X-Admin-Key`，值与配置项 `KNOWLEDGE_ADMIN_KEY` 匹配。未配置时（开发环境）放行。

### 18.9 评估集

10 个测试用例：

| 用例 | 查询 | 期望 |
| --- | --- | --- |
| fat_loss_calorie | 减脂期每天应该摄入多少热量 | 命中 fat_loss_standards |
| muscle_gain_surplus | 增肌期热量盈余多少合适 | 命中 muscle_gain_standards |
| chinese_meal_substitution | 减脂期外卖怎么点餐 | 命中 chinese_meals |
| beginner_training | 新手每周训练几天合适 | 命中 training_principles |
| knee_injury_limit | 膝盖受伤后可以做什么运动 | 命中 risk_rules |
| exercise_risk | 深蹲膝盖内扣怎么纠正 | 命中 exercise_technique |
| insufficient_evidence | 量子力学对减脂的影响 | 低置信度（score < 0.65） |
| wrong_premise | 每天只吃500大卡能快速减脂吗 | 命中 risk_rules + fat_loss_standards |
| protein_intake | 减脂期每公斤体重需要多少蛋白质 | 命中 fat_loss_standards |
| back_injury_deadlift | 腰椎间盘突出能做硬拉吗 | 命中 risk_rules + exercise_technique |

评估校验项：
- `must_not_be_empty`：结果非空且 insufficient_evidence=false
- `max_score_threshold`：Top-1 分数不超过阈值
- `expected_categories`：至少命中一个期望分类（基于 RetrievedChunk.category 实际校验）
- `must_be_empty_or_insufficient`：结果为空或 insufficient_evidence=true

当前评估结果：10/10 通过，全部为 hybrid 或 keyword 检索命中，分类校验通过。

### 18.10 测试覆盖

29 个单元测试（19 个 RAG + 10 个原有）：

| 测试类 | 数量 | 覆盖 |
| --- | --- | --- |
| StableIdTests | 3 | ID 稳定性、哈希一致性 |
| DocumentModelTests | 3 | 文档校验、证据等级来源检查 |
| ChunkModelTests | 2 | 自动 ID、标签归一化 |
| FrontmatterTests | 2 | YAML 解析、无 frontmatter 降级 |
| DocumentLoadingTests | 5 | 全量加载、分类覆盖、元数据完整性、去重、单文档加载 |
| KeywordIndexTests | 3 | 关键词匹配、无关查询、中文匹配 |
| SearchQueryTests | 1 | 默认值 |

### 18.11 模块文件清单

```bash
backend/app/rag/
├─ __init__.py          # 导出所有模型和检索函数
├─ models.py            # Pydantic 模型（文档/切块/检索/结果/统计）
├─ indexer.py           # YAML 解析 + 语义分块 + 文档加载
├─ keyword_index.py     # BM25 关键词索引（中文 bigram）
├─ vectorstore.py       # Chroma 向量库管理（安全重建）
├─ retriever.py         # 混合检索器（向量+关键词+重排序）
└─ evaluate.py          # 评估套件（10 个测试用例）

backend/app/api/
└─ knowledge.py         # 知识管理 API（5 个端点）

backend/data/knowledge_docs/
├─ fat_loss_core_principles.md
├─ fat_loss_protein_intake.md
├─ muscle_gain_nutrition.md
├─ meal_planning_guide.md
├─ chinese_meal_guide.md
├─ training_principles.md
├─ exercise_technique.md
├─ health_risk_rules.md
└─ exercise_risk_rules.md

backend/tests/
└─ test_rag.py          # 19 个 RAG 单元测试
```

### 18.12 验收清单

- [x] 每个知识块都有来源、证据等级、适用条件和版本。
- [x] 检索支持语义、关键词和元数据过滤。
- [x] 关键词结果也按 categories 过滤。
- [x] 伤病禁忌硬过滤：命中 contraindications 直接排除。
- [x] 工作流节点使用 SearchQuery 精准检索（按目标/伤病/类别）。
- [x] 无可靠依据时返回 insufficient_evidence。
- [x] 评估集实际校验 expected_categories（基于 RetrievedChunk.category）。
- [x] 固定评估集可以自动运行并输出结果（10/10 通过）。
- [x] 向后兼容旧 retrieve_knowledge 接口。
- [x] 安全重建回滚：reopen 失败时删除损坏目录并从 backup 恢复。
- [x] 管理接口鉴权：rebuild/documents/evaluate 需 X-Admin-Key。
- [x] 业务结果返回引用（knowledge_citations）。
- [x] DashScope embedding API 兼容。
- [x] Windows 文件锁兼容。

## 19. 后续阶段：上下文聊天 Agent

### 19.1 产品定位

聊天 Agent 是已有业务能力的自然语言入口，不是独立的开放式聊天机器人。它必须能够理解用户当前所在页面、当前计划和最近分析结果。

第一版优先提供页面级上下文问答：

- 饮食计划页：解释餐次、替换食材和购物清单。
- 动作分析页：解释问题、风险和纠正练习。
- 身材分析页：解释指标与建议边界。
- 复盘页：解释调整原因和下一阶段重点。

全局聊天入口安排在页面级问答稳定之后。

### 19.2 Agent 上下文

```python
class ChatAgentState(TypedDict):
    user_id: int
    conversation_id: str
    current_page: str
    user_profile: dict
    daily_summary: dict | None
    active_diet_plan: dict | None
    active_workout_plan: dict | None
    latest_analyses: list[dict]
    retrieved_knowledge: list[dict]
    pending_change: dict | None
    messages: list[dict]
```

不要把完整历史数据和全部对话直接塞入上下文。优先读取当前任务所需数据，并保存结构化会话摘要。

### 19.3 工具分层

只读工具可自动调用：

- `get_user_profile`
- `get_daily_nutrition_summary`
- `get_active_diet_plan`
- `get_active_workout_plan`
- `get_latest_body_analysis`
- `get_latest_pose_analysis`
- `search_knowledge`

草案工具可自动调用，但只返回预览：

- `draft_food_substitution`
- `draft_meal_adjustment`
- `draft_workout_adjustment`
- `compare_plan_changes`

写入工具必须在用户明确确认后调用：

- `apply_diet_plan_change`
- `apply_workout_plan_change`
- `save_user_preference`

### 19.4 确认流程

```text
用户提出调整
→ Agent 读取当前计划和限制
→ 检索专业依据
→ 生成调整草案
→ 计算修改前后差异
→ 前端展示变更预览
→ 用户确认
→ 写入工具执行
→ 返回结果与可撤销信息
```

确认必须绑定具体的 `change_id` 和草案版本，避免用户确认后执行已经变化的旧草案。

### 19.5 API 建议

- `POST /api/chat/conversations`
- `GET /api/chat/conversations/{id}`
- `POST /api/chat/conversations/{id}/messages`
- `GET /api/chat/conversations/{id}/stream`
- `POST /api/chat/changes/{change_id}/confirm`
- `POST /api/chat/changes/{change_id}/cancel`

聊天响应至少包含：

- 回复正文。
- 引用来源。
- 使用的业务上下文摘要。
- 工具调用状态。
- 待确认变更。
- 风险提示。

### 19.6 安全边界

- 不提供疾病诊断和药物调整建议。
- 不在用户未确认时修改计划或档案。
- 不允许模型直接构造数据库更新语句。
- 工具层重新校验用户身份、字段范围和业务规则。
- 不把其他用户数据带入上下文。
- 不保存图片、视频或敏感健康数据的完整内容到聊天消息。
- 对证据不足的问题明确拒答或建议咨询专业人士。

### 19.7 阶段验收

- Agent 能回答与当前页面和用户计划相关的问题。
- 回答能够显示知识来源。
- Agent 能生成食材或训练调整草案。
- 前端能够展示修改前后差异。
- 未确认时数据库不发生变化。
- 用户确认后只执行对应版本的草案。
- QA 能验证越权、提示词注入、重复确认和过期草案等场景。

## 20. 聊天 Agent MVP 实施阶段

### 20.1 阶段一：会话基础设施

- [x] 新增 `ChatConversation`、`ChatMessage` 数据模型。
- [x] 新增创建、列表、详情、归档会话 API。
- [x] 所有查询同时按 `conversation_id` 与 `user_id` 过滤。
- [x] 消息支持 `pending / completed / stopped / failed` 状态。

### 20.2 阶段二：只读 Agent 工作流

```text
加载最近对话
-> 加载用户档案和最新计划
-> 识别风险与问题类型
-> 按需检索 RAG
-> 生成系统上下文
-> DashScope 流式生成
-> 保存正文、引用和上下文摘要
```

只读上下文：

- 用户身体数据、目标、饮食偏好、过敏和伤病。
- 最新热量目标、宏量营养素、饮食计划与训练计划摘要。
- 当前页面名称及前端传入的结构化页面摘要。
- 最近 10 条聊天消息。
- RAG Top-K 结果及来源。

### 20.3 阶段三：前端聊天 MVP

- [x] 独立 `/chat` 路由和导航入口。
- [x] 左侧会话列表，支持新建和归档。
- [x] 主消息区支持流式文本、错误状态和自动滚动。
- [x] 引用来源使用折叠区域展示。
- [x] 输入区支持 Enter 发送、Shift+Enter 换行和停止生成。
- [x] 无用户档案时显示建档引导。
- [x] 桌面端双栏，移动端会话列表使用抽屉。

### 20.4 阶段四：验证

- [x] 会话创建、恢复、归档测试。
- [x] 跨用户会话访问返回 404。
- [x] RAG 引用随助手消息持久化。
- [x] 模型异常时保存失败状态并输出安全错误事件。
- [x] 高风险问题有明确安全边界。
- [x] 后端完整测试通过。
- [x] 前端类型检查和生产构建通过。
- [x] 浏览器验证创建会话、发送消息、刷新恢复和移动端布局。

当前 MVP 验证基线：

- 后端单元与回归测试：82 项通过。
- RAG 评估：12/12 通过。
- 前端 Vue 类型检查与 Vite 生产构建通过。
- DashScope 真实流式回答、引用展示和消息持久化通过。

### 20.5 后续增强

1. 页面级快捷提问与上下文自动注入。
2. 会话摘要和长期记忆。
3. 计划调整草案与确认写入。
4. 工具调用过程可视化。
5. Agent 离线评测、延迟、Token 和成本监控。
