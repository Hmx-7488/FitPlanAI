# 减脂 Agent

基于 Agentic RAG 的个性化减脂教练，支持根据用户身体信息、饮食偏好生成个性化饮食与运动计划，并通过每日打卡和 AI 复盘实现动态调整。

## 技术栈

**后端**
- Python 3.11+
- FastAPI
- LangChain + LangGraph
- Chroma（RAG 向量库 + 语义检索）
- SQLite + SQLAlchemy
- LLM API（DeepSeek / 通义千问等兼容接口）

**前端**
- Vue 3 + TypeScript
- Vite
- Element Plus
- Axios

## 项目结构

```
SlimAgent/
├─ backend/
│  ├─ app/
│  │  ├─ main.py              # FastAPI 入口
│  │  ├─ api/                 # 接口层
│  │  │  ├─ profile.py        # 用户档案接口
│  │  │  ├─ plan.py           # 计划生成接口
│  │  │  └─ checkin.py        # 每日打卡接口 (V2)
│  │  ├─ core/                # 配置与数据库
│  │  ├─ models/              # 数据模型
│  │  ├─ schemas/             # Pydantic schemas
│  │  ├─ services/            # 业务逻辑
│  │  ├─ rag/                 # RAG 检索（Chroma 向量检索）
│  │  ├─ tools/               # 工具函数
│  │  └─ graph/               # LangGraph 工作流（计划 + 复盘）
│  ├─ data/
│  │  ├─ docs/                # RAG 知识文档（5 篇）
│  │  └─ vectorstore/         # Chroma 持久化向量库
│  ├─ requirements.txt
│  └─ .env.example
├─ frontend/
│  ├─ src/
│  │  ├─ views/               # 页面组件
│  │  │  ├─ HomeView.vue      # 首页
│  │  │  ├─ ProfileView.vue   # 信息录入
│  │  │  ├─ PlanView.vue      # 计划展示
│  │  │  ├─ CheckinView.vue   # 每日打卡 (V2)
│  │  │  └─ HistoryView.vue   # 历史复盘 (V2)
│  │  ├─ api/                 # API 封装
│  │  ├─ router/              # 路由
│  │  └─ types/               # TypeScript 类型
│  ├─ package.json
│  └─ vite.config.ts
├─ README.md
└─ docs/
```

## 快速开始

### 1. 后端

```bash
cd backend
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY

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

### V1 — 基础减脂计划
1. **信息录入** — 用户填写身体数据、目标体重、饮食偏好
2. **RAG 检索** — 从 Chroma 向量库检索食材热量、运动消耗、减脂原则
3. **热量计算** — 计算 BMR、TDEE、热量缺口、三大营养素分配
4. **饮食建议** — LLM 生成一周饮食计划
5. **运动建议** — LLM 生成一周训练计划
6. **总结输出** — 汇总执行建议和风险提醒

### V2 — 每日打卡与 AI 复盘
7. **每日打卡** — 记录饮食、运动、体重、状态
8. **历史查看** — 时间线展示打卡历史
9. **AI 复盘** — 分析打卡记录，评估执行情况
10. **次日调整** — 根据复盘结果生成次日饮食和运动调整建议

## LangGraph 工作流

### 计划生成工作流（6 节点）
```
用户信息 → 检索知识 → 热量计算 → 饮食建议 → 运动建议 → 总结输出
```

### 复盘工作流（3 节点）
```
检索知识 → 分析打卡 → 次日调整建议
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/profile/create` | 创建用户档案 |
| GET  | `/api/profile/{id}` | 获取用户档案 |
| POST | `/api/plan/generate` | 生成减脂计划 |
| POST | `/api/checkin/create` | 创建/更新每日打卡 |
| GET  | `/api/checkin/history/{id}` | 获取打卡历史 |
| GET  | `/api/checkin/review/{id}` | AI 复盘与次日建议 |
