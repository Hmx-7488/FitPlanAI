# FitPlanAI 分阶段实现指令

适用工具：Claude Code、Cursor Agent、Codex、其他代码 Agent。


项目目标：实现一个可演示、可部署、可写入简历的减脂训练与轻食规划 AI Agent 项目。项目需要体现 AI Agent、多轮对话、工具调用、多模态食材识别、结构化输出、RAG 知识库和后端工程化能力。

## 0. 总体要求

请按阶段逐步实现，不要一次性堆完整复杂系统。
每完成一个阶段，需要保证项目可以本地运行，并更新 README 或对应文档。
优先级：

1. 先跑通主链路。
2. 再接入 Agent 工作流。
3. 再接入食材图片识别。
4. 再补 RAG 知识库。
5. 最后做打卡复盘、部署和求职包装。

技术栈建议：

- 前端：Next.js、TypeScript、Tailwind CSS、shadcn/ui
- 后端：Python、FastAPI、Pydantic
- Agent 编排：LangGraph
- LLM：OpenAI API 或兼容模型
- 多模态：Vision Model
- RAG：Chroma 或 FAISS
- 数据库：SQLite 起步，后续可切 PostgreSQL
- 部署：Docker

如果项目当前为空，请从零初始化。如果已有代码，请在不破坏现有文件的前提下增量实现。

## 1. 推荐目录结构

请最终整理为以下结构：

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
│  │  │  ├─ config.py
│  │  │  └─ llm.py
│  │  ├─ schemas/
│  │  │  ├─ profile.py
│  │  │  ├─ nutrition.py
│  │  │  ├─ workout.py
│  │  │  ├─ ingredient.py
│  │  │  └─ agent.py
│  │  ├─ models/
│  │  ├─ services/
│  │  │  ├─ nutrition_service.py
│  │  │  ├─ workout_service.py
│  │  │  ├─ recipe_service.py
│  │  │  └─ risk_service.py
│  │  ├─ tools/
│  │  │  ├─ nutrition_tools.py
│  │  │  ├─ vision_tools.py
│  │  │  ├─ recipe_tools.py
│  │  │  ├─ workout_tools.py
│  │  │  └─ risk_tools.py
│  │  ├─ graph/
│  │  │  ├─ state.py
│  │  │  ├─ nodes.py
│  │  │  └─ workflow.py
│  │  ├─ rag/
│  │  │  ├─ loader.py
│  │  │  ├─ retriever.py
│  │  │  └─ vectorstore.py
│  │  └─ db/
│  │     ├─ database.py
│  │     └─ repositories.py
│  ├─ data/
│  │  ├─ knowledge/
│  │  │  ├─ foods.json
│  │  │  ├─ workouts.json
│  │  │  └─ risk_rules.json
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
├─ docker-compose.yml
└─ README.md
```

## 2. 阶段 1：项目初始化与后端基础

目标：搭建基础后端，跑通 FastAPI 服务和健康检查接口。

任务：


1. 创建 `backend/` 目录。
2. 初始化 Python 虚拟环境依赖文件 `requirements.txt`。
3. 安装并使用：
   - `fastapi`
   - `uvicorn`
   - `pydantic`
   - `pydantic-settings`
   - `python-dotenv`
4. 创建 `backend/app/main.py`。
5. 创建 `/health` 接口。
6. 创建 `.env.example`。
7. 编写后端启动说明。

验收标准：

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

访问：

```text
GET http://localhost:8000/health
```

返回：

```json
{"status":"ok","service":"FitPlanAI API"}
```

## 3. 阶段 2：用户建档与营养计算工具

目标：实现用户身体数据录入，并通过确定性工具计算 BMR、TDEE、热量缺口和三大营养素。

任务：

1. 创建用户档案 Schema：
   - 性别
   - 年龄
   - 身高
   - 体重
   - 体脂率
   - 肌肉量
   - 活动水平
   - 目标体重
   - 目标周期
   - 训练频率
   - 伤病
   - 过敏源
   - 忌口
2. 创建营养目标 Schema：
   - 每日热量
   - 蛋白质 g
   - 碳水 g
   - 脂肪 g
   - 膳食纤维 g
   - 饮水量 ml
   - 解释说明
3. 实现工具：
   - `calculate_bmr`
   - `calculate_tdee`
   - `calculate_calorie_target`
   - `calculate_macros`
4. 创建接口：
   - `POST /api/profiles`
   - `POST /api/nutrition/target`
5. 增加单元测试。

计算规则：

- BMR 使用 Mifflin-St Jeor 公式。
- TDEE = BMR * 活动系数。
- 减脂热量缺口默认为 15%-20%。
- 蛋白质按每公斤体重 1.6-2.2g。
- 脂肪不低于总热量 20%。
- 碳水由剩余热量计算。
- 如果热量过低，需要返回风险提醒。

验收标准：

输入：

```json
{
  "gender": "female",
  "age": 28,
  "height_cm": 165,
  "weight_kg": 62,
  "body_fat_rate": 0.28,
  "muscle_mass_kg": 38,
  "activity_level": "moderate",
  "goal": "fat_loss",
  "target_weight_kg": 55,
  "target_weeks": 12,
  "training_days_per_week": 4,
  "injuries": ["knee_pain"],
  "allergies": ["shrimp"],
  "diet_restrictions": ["no_spicy"]
}
```

输出必须包含：

```json
{
  "daily_calories_kcal": 1600,
  "protein_g": 100,
  "carbs_g": 130,
  "fat_g": 45,
  "fiber_g": 25,
  "water_ml": 2200,
  "explanation": "...",
  "risk_warnings": []
}
```

数值可以不同，但字段必须完整。

## 4. 阶段 3：训练计划生成

目标：根据用户身体数据、训练条件和伤病限制生成结构化一周训练计划。

任务：

1. 创建训练计划 Schema：
   - 周几
   - 训练主题
   - 动作列表
   - 每个动作的组数、次数、间歇、目标肌群
   - 有氧建议
   - 热身和拉伸
   - 风险提醒
2. 创建基础训练动作库 `data/knowledge/workouts.json`。
3. 至少包含 30 个动作：
   - 徒手动作
   - 哑铃动作
   - 健身房器械动作
   - 有氧动作
4. 每个动作包含：
   - 动作名
   - 目标肌群
   - 器械
   - 难度
   - 禁忌或注意事项
5. 实现 `generate_workout_plan` 服务。
6. 创建接口：
   - `POST /api/agent/generate-workout`

要求：

- 新手不要给过大训练容量。
- 膝盖不适用户避免跳跃、高冲击、大量深蹲。
- 腰痛用户避免大重量硬拉。
- 肩部不适用户避免高风险推举。

验收标准：

接口能返回一周训练计划，结构示例：

```json
{
  "weekly_plan": [
    {
      "day": "Monday",
      "theme": "下肢力量 + 中低强度有氧",
      "exercises": [
        {
          "name": "臀桥",
          "sets": 4,
          "reps": "12",
          "rest_seconds": 60,
          "target_muscles": ["glutes"],
          "notes": "膝盖不适时优先选择该动作"
        }
      ],
      "cardio": {
        "type": "椭圆机",
        "duration_minutes": 25,
        "intensity": "中低强度"
      }
    }
  ],
  "risk_warnings": []
}
```

## 5. 阶段 4：Agent 工作流基础版

目标：用 LangGraph 把“建档检查 -> 营养计算 -> 训练计划 -> 风险校验 -> 总结输出”串成可解释的工作流。

任务：

1. 安装：
   - `langgraph`
   - `langchain`
2. 定义 `AgentState`。
3. 实现节点：
   - `parse_intent_node`
   - `profile_completion_node`
   - `ask_followup_node`
   - `calculate_macros_node`
   - `generate_workout_node`
   - `risk_guardrail_node`
   - `summarize_response_node`
4. 实现条件分支：
   - 如果档案缺失关键字段，返回追问问题。
   - 如果档案完整，继续生成计划。
5. 创建接口：
   - `POST /api/agent/chat`
   - `POST /api/agent/generate-plan`

AgentState 示例：

```python
class AgentState(TypedDict):
    user_id: str | None
    user_message: str | None
    intent: str | None
    profile: dict
    missing_fields: list[str]
    nutrition_target: dict | None
    workout_plan: dict | None
    risk_warnings: list[dict]
    final_response: dict | None
```

验收标准：

当用户缺少体重或目标周期时，Agent 返回追问：

```json
{
  "type": "followup",
  "questions": ["请补充当前体重", "请补充目标周期"]
}
```

当用户资料完整时，Agent 返回：

```json
{
  "type": "plan",
  "nutrition_target": {},
  "workout_plan": {},
  "risk_warnings": [],
  "explanation": "..."
}
```

## 6. 阶段 5：多模态食材识别与轻食生成

目标：实现用户上传食材照片，系统识别食材，用户确认重量后生成轻食菜谱。

任务：

1. 创建食材识别 Schema：
   - 食材名
   - 中文显示名
   - 预估重量
   - 置信度
   - 是否需要确认
2. 创建食材营养库 `data/knowledge/foods.json`。
3. 至少包含 50 个常见食材：
   - 鸡胸肉、鸡蛋、牛肉、虾仁、豆腐
   - 米饭、红薯、燕麦、玉米、土豆
   - 西兰花、菠菜、番茄、黄瓜、生菜
   - 牛奶、酸奶、坚果等
4. 实现图片上传接口。
5. 封装 `ingredient_vision_tool`。
6. 如果没有真实模型 Key，先做 mock 模式，保证流程可跑。
7. 实现用户确认食材接口。
8. 实现 `generate_recipe` 服务。
9. 创建接口：
   - `POST /api/agent/recognize-ingredients`
   - `POST /api/agent/generate-recipes`

要求：

- 图片识别结果不能直接当最终事实，必须要求用户确认。
- 菜谱需要结合用户营养目标。
- 菜谱必须输出热量、蛋白质、碳水、脂肪估算。
- 如果用户有过敏源，必须避开相关食材。

验收标准：

识别接口返回：

```json
{
  "recognition_id": "rec_001",
  "ingredients": [
    {
      "name": "chicken_breast",
      "display_name": "鸡胸肉",
      "estimated_weight_g": 150,
      "confidence": 0.92,
      "need_confirm": true
    }
  ],
  "question_to_user": "请确认以上食材和重量是否准确。"
}
```

确认后生成菜谱：

```json
{
  "recipes": [
    {
      "name": "香煎鸡胸肉西兰花能量碗",
      "ingredients": [],
      "steps": [],
      "nutrition": {
        "calories_kcal": 520,
        "protein_g": 48,
        "carbs_g": 42,
        "fat_g": 14
      },
      "risk_notes": []
    }
  ]
}
```

## 7. 阶段 6：RAG 知识库

目标：把食材营养、训练动作、健康风险规则接入检索增强流程，让 Agent 输出更稳定。

任务：

1. 安装并配置 Chroma 或 FAISS。
2. 实现知识文档加载器。
3. 实现文本切分和向量化。
4. 建立三个 collection：
   - `foods`
   - `workouts`
   - `risk_rules`
5. 实现 `knowledge_retriever_tool`。
6. 在训练计划生成前检索动作库。
7. 在菜谱生成前检索食材营养库。
8. 在最终输出前检索风险规则库。
9. 创建接口：
   - `POST /api/knowledge/rebuild`
   - `POST /api/knowledge/search`

验收标准：

搜索：

```json
{
  "query": "膝盖不适 减脂 下肢训练",
  "collections": ["workouts", "risk_rules"]
}
```

返回：

```json
{
  "documents": [
    {
      "title": "膝盖不适下肢训练建议",
      "content": "...",
      "source": "risk_rules"
    }
  ]
}
```

Agent 生成训练计划时能使用检索结果避开高风险动作。

## 8. 阶段 7：数据持久化

目标：保存用户、计划、识别结果、菜谱和打卡记录。

任务：

1. MVP 可使用 SQLite。
2. 使用 SQLAlchemy 或 SQLModel。
3. 建表：
   - `users`
   - `user_profiles`
   - `nutrition_targets`
   - `workout_plans`
   - `ingredient_recognitions`
   - `recipes`
   - `checkins`
   - `agent_runs`
4. 每次 Agent 执行保存：
   - 输入
   - 中间 State
   - 输出
   - 状态
   - 错误信息
5. 增加历史查询接口：
   - `GET /api/profiles/{user_id}`
   - `GET /api/plans/{user_id}`
   - `GET /api/recipes/{user_id}`
   - `GET /api/agent/runs/{user_id}`

验收标准：

- 生成计划后可查询历史计划。
- 识别食材后可查询识别记录。
- Agent 执行失败时能保存错误信息。

## 9. 阶段 8：每日打卡与周复盘

目标：形成“计划 -> 执行 -> 反馈 -> 调整”的 Agent 闭环。

任务：

1. 创建打卡 Schema：
   - 日期
   - 体重
   - 饮食执行率
   - 训练是否完成
   - 饥饿感
   - 疲劳感
   - 备注
2. 创建接口：
   - `POST /api/checkins`
   - `GET /api/checkins/{user_id}`
   - `POST /api/agent/weekly-review`
3. 实现周复盘逻辑：
   - 体重趋势
   - 训练完成率
   - 饮食执行率
   - 饥饿和疲劳变化
4. 输出调整建议：
   - 热量是否调整
   - 碳水是否调整
   - 有氧是否调整
   - 是否需要降低训练强度

验收标准：

连续 3-7 天打卡后，系统返回：

```json
{
  "summary": "本周体重下降 0.6kg，饮食执行率较好，训练完成率 75%。",
  "adjustments": [
    "保持当前热量目标",
    "训练日碳水可增加 20g",
    "膝盖不适时减少跑步，改为椭圆机"
  ],
  "next_week_focus": ["提高睡眠质量", "保持蛋白质摄入"]
}
```

## 10. 阶段 9：前端 MVP

目标：做一个能演示主链路的前端，不追求复杂 UI。

页面：

1. 首页 Dashboard
   - 今日热量目标
   - 今日训练
   - 最近计划
2. 建档页
   - 身体数据表单
   - 目标设置
   - 健康限制
3. Agent 计划页
   - 生成营养目标
   - 展示一周训练计划
   - 展示风险提醒
4. 轻食拍照页
   - 上传食材图片
   - 展示识别结果
   - 修改确认重量
   - 生成菜谱
5. 打卡复盘页
   - 每日打卡
   - 周复盘展示

要求：

- 使用 TypeScript 类型定义接口返回。
- API 请求统一封装。
- 加载中、错误、空状态要有基础处理。
- 移动端和桌面端都能基本使用。

验收标准：

用户可以从前端完成：

```text
建档 -> 生成计划 -> 上传食材 -> 确认食材 -> 生成菜谱 -> 打卡 -> 周复盘
```

## 11. 阶段 10：测试、README、部署

目标：让项目能投 GitHub、能演示、能进简历。

任务：

1. 后端补充单元测试。
2. 写 README：
   - 项目介绍
   - 技术栈
   - 功能列表
   - Agent 工作流图
   - API 示例
   - 启动方式
   - 截图占位
   - 简历描述
3. 增加 Dockerfile。
4. 增加 docker-compose。
5. 提供 `.env.example`。
6. 准备 mock 模式，避免没有模型 Key 时无法演示。
7. 增加 `docs/demo-script.md`，写 1 分钟和 3 分钟项目介绍。

验收标准：

```bash
docker compose up
```

可以启动主要服务。

README 中必须包含这段项目描述：

```text
FitPlanAI 是一个基于 LLM 和 LangGraph 的减脂训练与轻食规划 AI Agent，支持用户建档、营养计算、训练计划生成、食材图片识别、轻食菜谱生成和打卡复盘。项目通过工具调用、结构化输出和 RAG 知识库，将大模型能力落地到健身减脂垂直场景。
```

## 12. Agent 开发注意事项

1. 不要让 LLM 直接随意编造关键营养数值，热量和宏量营养素必须优先由工具计算。
2. LLM 负责解释、组织语言、生成可读建议，确定性计算交给工具。
3. 食材图片识别结果必须让用户确认重量。
4. 所有核心输出必须结构化，不能只返回自然语言。
5. 健康建议必须包含风险边界。
6. 没有模型 Key 时，必须支持 mock 数据演示。
7. 每个阶段完成后，确保服务能启动，不留下明显报错。
8. 不要第一版做复杂多 Agent，先完成单 Agent 工作流。
9. 不要过度追求 UI，先保证业务链路完整。
10. 代码要模块化，不要把所有逻辑写在一个文件里。

## 13. 最终简历可写内容

项目名称：

```text
FitPlanAI：基于大模型的减脂训练与轻食规划 AI Agent
```

项目描述：

```text
基于 LLM 与 LangGraph 设计并实现面向减脂场景的任务型 AI Agent，支持用户通过多轮对话完成身体数据建档，自动计算每日热量和蛋白质、碳水、脂肪摄入目标，并生成个性化训练计划。项目接入多模态食材识别能力，用户上传现有食材照片后，Agent 可识别食材、请求用户确认重量，并结合当日营养目标生成轻食菜谱。系统通过工具调用、结构化输出和 RAG 知识库提升大模型输出稳定性和业务可解释性。
```

技术关键词：

```text
Python, FastAPI, LangGraph, LLM, AI Agent, RAG, Vision Model, Pydantic, SQLite/PostgreSQL, Next.js, TypeScript, Docker
```

项目亮点：

```text
1. 将减脂规划拆解为建档追问、营养计算、训练生成、食材识别、菜谱生成和复盘调整等 Agent 多步执行链路。
2. 将 BMR/TDEE/宏量营养素计算封装为工具，避免大模型直接生成不可控数值。
3. 接入多模态食材识别，并通过用户确认机制降低图片识别和重量估算误差。
4. 使用 Pydantic Schema 约束结构化输出，便于前端展示、数据库持久化和后续评估。
5. 设计食材营养库、训练动作库和健康风险规则库，通过 RAG 增强计划生成和风险提醒。
```

## 14. 后续阶段 11：RAG 知识治理与模型扩充

目标：把现有 7 篇本地文档升级为可追溯、可版本化、可评估的专业知识层。

任务：

1. 盘点现有 `backend/data/docs` 和 RAG 代码，记录当前 collection、切分方式、Embedding、缓存和降级检索。
2. 定义知识文档和知识块 Schema，包含：
   - 来源名称和 URL
   - 发布日期和复核日期
   - 证据等级
   - 适用目标和人群
   - 适用条件和禁忌
   - 文档版本和知识块版本
3. 扩充知识域：
   - 减脂标准
   - 增肌标准
   - 饮食规划
   - 中国饮食
   - 训练原则
   - 动作标准
   - 风险规则
4. 实现文档清洗、结构化切分、哈希去重、元数据校验和版本化索引。
5. 保留现有 Chroma 方案，不在没有明确性能问题时更换向量数据库。
6. 提供知识导入、重建、状态和搜索接口。
7. 重建时保留旧索引，验证新索引成功后再切换。

验收：

- 每个知识块都能追溯到来源。
- 相同文档重复导入不会产生重复知识块。
- 无效元数据会被拒绝并记录具体原因。
- 索引切换失败时可以继续使用旧版本。

## 15. 后续阶段 12：混合检索与 RAG 评估

目标：提高检索相关性，避免“接入向量库但实际召回不可靠”。

任务：

1. 为检索请求增加：
   - 用户目标
   - 当前页面
   - 训练水平
   - 饮食限制
   - 伤病与风险条件
2. 实现向量检索和关键词检索的混合召回。
3. 实现元数据过滤、合并去重和重排。
4. 返回来源、证据等级、适用条件、相关度和依据摘要。
5. 当结果低于阈值时返回 `insufficient_evidence=true`。
6. 建立固定查询评估集，覆盖减脂、增肌、饮食替换、训练安排、动作风险和特殊限制。
7. 输出 Recall@K、Top-K 相关性、引用正确率、回答忠实度和证据不足识别结果。

验收：

- 相同问题在不同用户目标下能命中不同知识。
- 伤病和过敏条件能正确过滤不适用内容。
- 回答中的引用可以定位到具体知识块。
- 没有可靠依据时不会生成虚假来源。
- 评估脚本可以重复运行并输出稳定报告。

## 16. 后续阶段 13：现有业务接入统一知识层

目标：让 RAG 真正参与业务决策，而不是只提供独立搜索接口。

按以下顺序接入：

1. 饮食计划生成。
2. 训练计划生成。
3. 风险审查。
4. 动作分析纠正建议。
5. 身材分析后的训练和饮食建议。
6. 周复盘。

要求：

- 确定性营养计算仍由工具完成，不能交给 RAG 或 LLM。
- 每个业务节点只检索当前任务需要的知识。
- LLM 必须区分“用户数据”“工具计算结果”和“知识依据”。
- 结构化输出中保存使用的 `chunk_id` 和来源摘要。
- 保持现有 API 兼容，新增字段使用可选字段或同步更新前后端。

验收：

- 饮食和训练计划包含可追溯依据。
- 动作纠正建议结合动作标准库和风险规则库。
- 不同目标、器械、伤病和饮食限制能影响检索结果。
- 原有测试继续通过，并增加 RAG 业务回归测试。

## 17. 后续阶段 14：页面级上下文问答

目标：先验证聊天价值，不立即建设空白全局聊天页。

首批入口：

- 饮食计划页。
- 动作分析结果页。
- 身材分析结果页。
- 复盘页。

任务：

1. 前端发起提问时携带 `current_page`、当前记录 ID 和必要上下文标识。
2. 后端根据用户身份读取对应业务数据，不信任前端直接传入的完整计划内容。
3. Agent 调用知识检索和只读业务工具。
4. 回复展示引用来源和证据不足提示。
5. 支持流式输出、中止、错误重试和会话摘要。
6. 不允许在本阶段修改计划或档案。

验收：

- 用户可以针对当前计划或分析结果继续提问。
- Agent 能正确引用当前页面数据，不混淆其他记录。
- 回复包含来源。
- 切换页面后上下文不会错误串联。
- 提示词注入不能绕过数据权限和工具限制。

## 18. 后续阶段 15：受控聊天 Agent 与计划调整

目标：在页面级问答稳定后增加全局聊天入口和计划调整能力。

任务：

1. 建立聊天会话、消息摘要和待确认变更数据结构。
2. 提供只读工具：
   - 用户档案
   - 今日摄入
   - 饮食计划
   - 训练计划
   - 身材分析
   - 动作分析
   - 知识检索
3. 提供草案工具：
   - 食材替换
   - 餐次调整
   - 训练调整
   - 修改前后差异计算
4. 提供写入工具，但只有确认接口可以调用。
5. 变更预览必须展示热量、营养素、训练量和风险变化。
6. 使用 `change_id`、草案版本和过期时间避免重复执行或确认旧草案。
7. 保存操作日志，但不记录 API Key、完整图片、视频或无关敏感数据。

验收：

- Agent 能结合用户档案和当前计划回答问题。
- Agent 能生成调整草案，但未确认时数据库无变化。
- 用户确认后只执行指定版本的草案。
- 重复确认不会重复写入。
- 过期草案必须重新生成。
- 全局聊天不影响现有页面级功能。

## 19. 后续阶段统一执行要求

每个阶段开始前：

1. 检查 `git status`，保留无关修改。
2. 阅读现有 RAG、LangGraph、数据库和前端接口实现。
3. 先补测试和评估基线，再替换核心链路。
4. 数据库 schema 和共享类型由 Lead 指定唯一负责人。

每个阶段结束前：

1. 运行后端编译和完整测试。
2. 运行前端类型检查和生产构建。
3. 对新增页面执行桌面端和移动端浏览器回归。
4. 验证引用来源、无依据拒答、权限隔离和确认后写入。
5. QA 独立审查检索质量、安全边界和回归风险。
6. Lead 审查后才允许创建本地提交。
7. 禁止自动 push、创建 PR 或 merge。
