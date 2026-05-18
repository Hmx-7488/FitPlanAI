# SlimAgent（FitPlanAI）

基于 LLM + LangGraph + RAG 的个性化减脂/增肌 AI Agent，支持用户建档、营养计算、训练计划生成、食材图片识别、轻食菜谱生成、每日打卡和 AI 复盘。

## 技术栈

**后端**
- Python 3.11+
- FastAPI + Pydantic
- LangChain + LangGraph
- Chroma（RAG 向量库 + 语义检索）
- SQLite + SQLAlchemy（aiosqlite）
- Vision Model（多模态食材识别）

**前端**
- Vue 3 + TypeScript + Vite
- Element Plus
- Axios

## 项目结构

```
SlimAgent/
├─ backend/
│  ├─ app/
│  │  ├─ main.py              # FastAPI 入口（含静态文件服务）
│  │  ├─ api/
│  │  │  ├─ profile.py        # 用户档案接口
│  │  │  ├─ plan.py           # 计划生成接口
│  │  │  ├─ checkin.py        # 每日打卡 + AI 复盘接口
│  │  │  └─ vision.py         # 食材识别 + 菜谱生成接口
│  │  ├─ core/                # 配置与数据库
│  │  ├─ models/              # SQLAlchemy 数据模型
│  │  ├─ schemas/             # Pydantic schemas
│  │  ├─ services/            # 业务逻辑层
│  │  ├─ rag/                 # RAG 检索（Chroma 向量检索 + 降级方案）
│  │  ├─ tools/               # 营养计算工具
│  │  └─ graph/               # LangGraph 工作流（计划 + 复盘）
│  ├─ data/
│  │  ├─ docs/                # RAG 知识文档（7 篇）
│  │  ├─ vectorstore/         # Chroma 持久化向量库
│  │  └─ uploads/             # 上传文件存储
│  ├─ requirements.txt
│  └─ .env
├─ frontend/
│  ├─ src/
│  │  ├─ views/
│  │  │  ├─ HomeView.vue      # 首页
│  │  │  ├─ ProfileView.vue   # 建档（含目标选择）
│  │  │  ├─ AnalysisView.vue  # 身体画像分析
│  │  │  ├─ PlanView.vue      # 计划展示
│  │  │  ├─ FoodView.vue      # 食材识别 + 菜谱生成
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
- Agent 自动检测缺失字段并追问

### 营养计算
- BMR（Mifflin-St Jeor 公式）→ TDEE → 目标热量
- 减脂：TDEE 减少 10%-25%，蛋白质 1.6-2.2g/kg
- 增肌：TDEE 增加 5%-15%，蛋白质 1.8-2.4g/kg
- 输出蛋白质、碳水、脂肪克数

### 训练计划
- 根据减脂/增肌目标生成不同训练计划
- 减脂：力量训练保肌 + 有氧增加消耗
- 增肌：渐进超负荷 + 肌肥大训练为主
- 避让伤病禁忌动作

### 食材识别 + 菜谱生成
- 上传食材照片，Vision Model 识别食材和重量
- 用户确认食材后生成 2-3 个轻食方案
- 每个菜谱包含热量、蛋白质、碳水、脂肪、烹饪步骤
- 每个菜谱包含图片 URL 和 generation_prompt

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

| 知识库 | 文件 | 内容 |
|--------|------|------|
| 食物热量 | food_calories.md | 60+ 食材热量和营养素 |
| 运动消耗 | exercise_calories.md | 40+ 运动消耗数据 |
| 减脂原则 | fat_loss_principles.md | 饮食和运动原则 |
| 训练动作 | training_exercises.md | 按肌群分类的动作库 |
| 常见食谱 | common_recipes.md | 轻食食谱参考 |
| 风险规则 | risk_rules.md | 健康风险规则 |
| 饮食误区 | dietary_myths.md | 常见饮食误区 |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/profile/create` | 创建用户档案 |
| GET  | `/api/profile/{id}` | 获取用户档案 |
| POST | `/api/plan/generate` | 生成训练计划 |
| GET  | `/api/plan/latest/{id}` | 获取最新计划 |
| POST | `/api/checkin/create` | 创建/更新每日打卡 |
| GET  | `/api/checkin/history/{id}` | 获取打卡历史 |
| GET  | `/api/checkin/review/{id}` | AI 复盘与次日建议 |
| POST | `/api/vision/recognize` | 上传食材图片识别 |
| POST | `/api/vision/confirm` | 确认食材 |
| POST | `/api/vision/recipes` | 生成轻食菜谱 |
| GET  | `/api/vision/recipes/latest/{id}` | 获取最新菜谱 |

## 后续迭代（规划中）

以下功能已在需求文档中规划，尚未实现：

- 身材照片上传分析（体脂率估算、体态分析）
- 餐食图片识别与每日热量缺口计算
- AI 动作姿态分析（关键点检测、关节角度、纠错建议）
- 中国地域饮食习惯与省时计划
- 打卡围度记录与身材照片对比
- 训练地点/器械条件/训练经验等高级建档字段
