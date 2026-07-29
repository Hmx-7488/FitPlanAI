# SlimAgent（FitPlanAI）

基于 LLM + LangGraph + RAG 的个性化减脂/增肌 AI Agent，支持用户建档、营养计算、训练计划生成、食材图片识别、轻食菜谱生成（含 AI 成品图）、餐食热量识别、身材照片分析、AI 动作分析（MediaPipe 关键点 + Vision 解释）、每日打卡、AI 复盘和带来源引用的上下文聊天助手。知识检索为带来源治理、混合检索和质量评估的统一知识层。

## 技术栈

**后端**
- Python 3.11+
- FastAPI + Pydantic
- LangChain + LangGraph
- Chroma（RAG 向量库 + 语义检索）
- SQLite + SQLAlchemy（aiosqlite）
- Vision Model（多模态食材识别、餐食识别）

**前端**
- Vue 3 + TypeScript + Vite
- Element Plus
- Axios

## 项目结构

```
SlimAgent/
├─ backend/
│  ├─ app/
│  │  ├─ main.py              # FastAPI 入口（v0.6.0）
│  │  ├─ api/
│  │  │  ├─ profile.py        # 用户档案接口
│  │  │  ├─ plan.py           # 计划生成接口
│  │  │  ├─ checkin.py        # 每日打卡 + AI 复盘接口
│  │  │  ├─ vision.py         # 食材识别 + 菜谱生成接口
│  │  │  ├─ body.py           # 身材照片分析（Vision Model）
│  │  │  ├─ pose.py           # AI 动作分析（Vision Model）
│  │  │  ├─ meal.py           # 餐食热量识别接口
│  │  │  ├─ dashboard.py      # Dashboard 聚合接口
│  │  │  ├─ knowledge.py      # 知识库检索与管理接口
│  │  │  └─ chat.py           # 上下文聊天 Agent 接口
│  │  ├─ core/                # 配置与数据库
│  │  ├─ models/              # SQLAlchemy 数据模型
│  │  ├─ schemas/             # Pydantic schemas
│  │  ├─ services/            # 业务逻辑层
│  │  ├─ rag/                 # RAG 检索（Chroma 向量检索 + 降级方案）
│  │  ├─ tools/               # 营养计算工具
│  │  └─ graph/               # LangGraph 工作流（计划 + 复盘）
│  ├─ data/
│  │  ├─ knowledge_docs/      # RAG 知识文档（13 篇生效 + 1 篇废弃，含来源/证据元数据）
│  │  ├─ vectorstore/         # Chroma 持久化向量库
│  │  └─ uploads/             # 上传文件存储
│  ├─ requirements.txt
│  └─ .env
├─ frontend/
│  ├─ src/
│  │  ├─ views/
│  │  │  ├─ HomeView.vue      # 首页
│  │  │  ├─ ProfileView.vue   # 建档（含训练条件 + 饮食习惯）
│  │  │  ├─ AnalysisView.vue  # 身体画像分析
│  │  │  ├─ PlanView.vue      # 计划展示
│  │  │  ├─ FoodView.vue      # 食材识别 + 菜谱生成（含替代食材）
│  │  │  ├─ MealView.vue      # 餐食热量识别
│  │  │  ├─ BodyPhotoView.vue # 多角度身材照片分析
│  │  │  ├─ PoseView.vue      # 图片/视频动作分析
│  │  │  ├─ CheckinView.vue   # 每日打卡
│  │  │  └─ HistoryView.vue   # 打卡历史 + AI 复盘
│  │  ├─ api/                 # API 封装
│  │  ├─ router/              # 路由
│  │  ├─ types/               # TypeScript 类型
│  │  └─ utils/               # 工具函数（BMR/TDEE 计算）
│  ├─ public/
│  └─ vite.config.ts
├─ docs/
├─ README.md
└─ DESIGN.md
```

## 快速开始

### 1. 后端

```bash
cd backend
# 编辑 .env 填入 LLM_API_KEY、LLM_BASE_URL、LLM_MODEL、VISION_MODEL

pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

访问 http://127.0.0.1:8000/docs 查看 API 文档。

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:3000 打开应用。

## 核心功能

### 用户建档
- 支持减脂和增肌两种训练目标
- 身体数据：性别、年龄、身高、体重、体脂率
- 运动偏好：活动水平、饮食偏好
- 健康限制：伤病部位、过敏食材、忌口食物
- 训练条件：每周训练天数、每次时长、训练地点、可用器械、训练经验、偏好时间
- 饮食习惯：地域口味、饮食场景（自己做饭/外卖/食堂/便利店）、备餐时间限制
- Agent 自动检测缺失字段并追问

### 营养计算
- BMR（Mifflin-St Jeor 公式）→ TDEE → 目标热量
- 减脂：TDEE 减少 10%-25%，蛋白质 1.6-2.2g/kg
- 增肌：TDEE 增加 5%-15%，蛋白质 1.8-2.4g/kg
- 输出蛋白质、碳水、脂肪克数

### 训练计划
- 根据减脂/增肌目标生成不同训练计划
- 根据训练条件（每周天数、时长、地点、器械、经验）个性化定制
- 减脂：力量训练保肌 + 有氧增加消耗
- 增肌：渐进超负荷 + 肌肥大训练为主
- 避让伤病禁忌动作
- 支持家里/健身房/户外不同场景

### 饮食计划
- 根据饮食偏好和中国地域口味生成
- 支持自己做饭、外卖、食堂、便利店等场景
- 根据备餐时间限制推荐快手菜或点餐建议

### 食材识别 + 菜谱生成
- 上传食材照片，Vision Model 识别食材和重量
- 用户确认食材后生成 2-3 个轻食方案
- 每个菜谱包含热量、蛋白质、碳水、脂肪、烹饪步骤
- 每个菜谱包含图片 URL 和 generation_prompt
- 自动检测缺少的食材并给出替代建议和购物清单

### 餐食热量识别
- 上传已吃的餐食照片，Vision Model 识别菜品和份量
- 估算本餐热量和三大营养素
- 计算每日热量缺口和剩余配额
- 根据缺口状态给出饮食调整建议

### 身材照片分析
- 支持上传正面、侧面和背面照片，上传数量可选
- 使用 Vision Model 综合估算体脂率范围、身材特征和训练重点
- Vision Model 不可用时提供基于档案数据的明确降级结果
- 结果属于辅助估算，不替代医学测量或专业评估

### AI 动作分析
- 上传训练动作照片或短视频，视频按关键帧进行分析
- 输出综合评分、风险等级、结构化问题项和纠正建议
- 支持深蹲、硬拉、卧推、引体向上、俯卧撑等动作
- 根据用户伤病信息给出风险提示
- 当前使用 Vision Model 分析，后续可增加 MediaPipe Pose 或 MoveNet 提供可计算的关键点与关节角度

### 每日打卡
- 记录饮食、运动、体重、备注

### AI 复盘
- 分析打卡记录，评估执行情况
- 减脂关注体重趋势和热量缺口
- 增肌关注力量增长和蛋白质达标
- 生成次日调整建议

## LangGraph 工作流

### 计划生成工作流（9 节点，含条件分支）
```
解析用户信息 → 检查档案完整性
  ├─ 不完整 → 生成追问问题 → END
  └─ 完整 → RAG 检索 → 热量计算 → 饮食计划 → 运动计划 → 风险校验 → 总结输出 → END
```

### 复盘工作流（3 节点）
```
RAG 检索 → 分析打卡记录 → 次日调整建议
```

## RAG 知识库

知识层位于 `backend/data/knowledge_docs/`，当前 14 篇文档（13 篇生效 + 1 篇废弃保留）。每个知识块带来源、证据等级、适用目标（减脂/增肌/通用）、训练水平、禁忌、安全替代和风险标签等元数据。

| 类别 | 代表文档 | 内容 |
|------|----------|------|
| 减脂标准 | fat_loss_core_principles.md、fat_loss_protein_intake.md | 热量缺口原则、蛋白质摄入标准 |
| 增肌营养 | muscle_gain_nutrition.md | 增肌期热量盈余与营养分配 |
| 饮食规划 | meal_planning_guide.md、chinese_meal_guide.md | 餐次规划、中式饮食场景 |
| 动作技术 | squat/deadlift/bench_press/pull_up/push_up_technique.md | 五大动作标准、常见错误与纠正 |
| 风险规则 | exercise_risk_rules.md、health_risk_rules.md | 伤病禁忌、特殊人群风险 |

检索链路：Chroma 语义检索 + 关键词检索 → 元数据过滤（目标类型、训练水平、伤病禁忌、饮食限制别名）→ 去重重排 → 证据充分性评估（证据不足时明确拒答而非编造）。内置固定查询集评测（`/api/knowledge/evaluate`），索引导入失败自动回滚旧版本。

## 上下文聊天 Agent

聊天助手（`/chat` 页）已实现第一阶段能力：

- 自动注入用户档案、最新计划和页面上下文，不是空白聊天机器人。
- 流式输出（SSE），支持停止生成、会话归档和多会话管理。
- 检索知识层并返回真实引用来源；证据不足时明确说明，不编造。
- 风险拦截：极端节食等高风险提问会触发安全提示与就医建议。
- 工具全部为只读，不能修改档案、计划或打卡（遵循"人在回路"原则）。

后续迭代：计划调整草案、差异预览和用户确认后写入。

## API 接口

| 方法 | 路径 | 说明 | 状态 |
|------|------|------|------|
| GET  | `/api/dashboard/{id}` | Dashboard 聚合数据（首页） | ✅ 已实现 |
| POST | `/api/profile/create` | 创建用户档案（含训练条件+饮食习惯） | ✅ 已实现 |
| GET  | `/api/profile/{id}` | 获取用户档案 | ✅ 已实现 |
| PATCH | `/api/profile/{id}` | 部分更新用户档案 | ✅ 已实现 |
| POST | `/api/profile/{id}/estimate-body-fat` | 身材照片估算体脂率并回填 | ✅ 已实现 |
| POST | `/api/plan/generate` | 生成训练计划（使用新字段） | ✅ 已实现 |
| GET  | `/api/plan/latest/{id}` | 获取最新计划 | ✅ 已实现 |
| POST | `/api/checkin/create` | 创建/更新每日打卡 | ✅ 已实现 |
| GET  | `/api/checkin/history/{id}` | 获取打卡历史 | ✅ 已实现 |
| GET  | `/api/checkin/review/{id}` | AI 复盘与次日建议 | ✅ 已实现 |
| POST | `/api/vision/recognize` | 上传食材图片识别 | ✅ 已实现 |
| POST | `/api/vision/confirm` | 确认食材 | ✅ 已实现 |
| POST | `/api/vision/recipes` | 生成轻食菜谱（含替代食材+购物清单） | ✅ 已实现 |
| GET  | `/api/vision/recipes/latest/{id}` | 获取最新菜谱 | ✅ 已实现 |
| POST | `/api/body/analyze` | 身材照片分析（Vision Model + BMI 降级） | ✅ 已实现 |
| POST | `/api/pose/analyze` | AI 动作分析（Vision Model + 模板降级） | ✅ 已实现 |
| POST | `/api/meal/analyze` | 餐食热量识别（一步完成） | ✅ 已实现 |
| POST | `/api/meal/recognize` | 餐食识别第一步：识别食材 | ✅ 已实现 |
| POST | `/api/meal/calculate` | 餐食识别第二步：确认后计算营养 | ✅ 已实现 |
| GET  | `/api/meal/daily-summary/{id}` | 每日热量汇总 | ✅ 已实现 |
| GET  | `/api/body/history/{id}` | 身材分析历史 | ✅ 已实现 |
| POST | `/api/knowledge/search` | 知识库混合检索（公开） | ✅ 已实现 |
| GET  | `/api/knowledge/status` | 知识索引状态 | ✅ 已实现 |
| POST | `/api/knowledge/rebuild` | 重建索引（需管理员密钥） | ✅ 已实现 |
| POST | `/api/knowledge/evaluate` | 检索质量评测（需管理员密钥） | ✅ 已实现 |
| POST | `/api/chat/conversations` | 创建聊天会话 | ✅ 已实现 |
| GET  | `/api/chat/conversations` | 会话列表 | ✅ 已实现 |
| POST | `/api/chat/conversations/{id}/messages/stream` | 流式发送消息（SSE） | ✅ 已实现 |
| DELETE | `/api/chat/conversations/{id}` | 归档会话 | ✅ 已实现 |

## 功能实现状态

| 功能 | 状态 | 说明 |
|------|------|------|
| Dashboard 首页 | ✅ 已实现 | 热量进度、打卡连续天数、快捷入口 |
| 用户建档（基础字段） | ✅ 已实现 | 性别、年龄、身高、体重、体脂率等 |
| 目标类型（减脂/增肌） | ✅ 已实现 | 影响营养计算、训练计划、复盘 |
| 训练条件字段 | ✅ 已实现 | 每周天数、时长、地点、器械、经验 |
| 中国饮食习惯字段 | ✅ 已实现 | 地域口味、饮食场景、备餐时间 |
| 营养计算（BMR/TDEE/宏量） | ✅ 已实现 | Mifflin-St Jeor 公式 |
| 训练计划生成 | ✅ 已实现 | 使用新训练条件字段 |
| 饮食计划生成 | ✅ 已实现 | 使用新饮食习惯字段 |
| RAG 知识检索 | ✅ 已实现 | 7 篇知识文档，Chroma 向量库 |
| 风险校验 | ✅ 已实现 | 热量安全、伤病禁忌、过敏食材 |
| 食材识别 | ✅ 已实现 | Vision Model 多模态识别 |
| 轻食菜谱生成 | ✅ 已实现 | 含替代食材和购物清单 |
| 菜谱图片字段 | ✅ 已实现 | 占位图 + generation_prompt |
| 每日打卡 | ✅ 已实现 | 饮食、运动、体重、备注 |
| AI 复盘 | ✅ 已实现 | 目标类型分支、复盘总结+次日建议 |
| 身材照片分析 | ✅ 已实现 | Vision Model 体脂率估算 + BMI 降级，自动回填档案 |
| AI 动作分析 | ✅ 已实现 | Vision Model 动作质量评分 + 模板降级，伤病风险提示 |
| 餐食热量识别 | ✅ 已实现 | Vision Model 识别+每日缺口计算，失败明确报错不写假数据 |
| 每日热量汇总 | ✅ 已实现 | 当日摄入、剩余配额、缺口状态 |
| 上下文聊天 Agent | ✅ 已实现 | 档案/计划上下文注入、流式输出、引用、风险拦截 |
| 知识库混合检索 | ✅ 已实现 | 语义+关键词+元数据过滤+证据评估+评测套件 |

## 后续迭代（规划中）

- ~~接入真实体态分析模型替代身材照片 Mock~~ ✅ 已接入 Vision Model
- ~~接入姿态估计模型替代动作分析 Mock~~ ✅ MediaPipe 关键点 + Vision 解释
- ~~RAG 知识来源、证据等级、适用条件和版本治理~~ ✅ 已实现
- ~~混合检索、元数据过滤、重排和检索评估~~ ✅ 已实现
- ~~全局聊天 Agent 与受控工具调用~~ ✅ 已实现（只读工具）
- ~~菜谱成品图自动生成~~ ✅ 已接入 DashScope 文生图
- 计划调整草案、差异预览和用户确认后写入
- 计划、动作、身材和复盘页面内嵌上下文问答
- 中国菜品热量库和地域饮食库扩充
- 打卡围度记录与身材照片对比
- 体重趋势图表和打卡历史可视化
