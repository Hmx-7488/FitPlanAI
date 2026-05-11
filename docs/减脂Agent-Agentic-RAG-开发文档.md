# 减脂 Agent（Agentic RAG）开发文档

适用对象：Claude Code、Cursor、GPT、其他代码 Agent  
目标：在尽量短的时间内，完成一个**可演示、可写进简历、面试好讲**的 AI 应用项目。  
项目定位：**基于 Agentic RAG 的个性化减脂教练**，支持基础信息录入、饮食建议、运动建议、每日打卡、复盘调整。

---

## 1. 项目目标

做一个面向减脂场景的 AI 应用，而不是单纯聊天机器人。

用户输入：
- 性别、年龄、身高、体重、目标体重
- 活动量、饮食偏好、禁忌食物
- 每日饮食与运动打卡

系统输出：
- 每日饮食建议
- 每日运动建议
- 热量与宏量营养估算
- 每周减脂计划
- 根据打卡记录做复盘和调整

项目亮点：
- 垂直场景明确
- 有状态流和连续交互
- 有 RAG 检索增强
- 有工具调用
- 有产品闭环，适合实习/毕设展示

---

## 2. 开发原则

1. **先做最小可用版，再做 Agent 增强版**
2. **先做能演示的主链路，不先做高级反思和复杂多 Agent**
3. **先保证结果可解释、可展示，再追求智能程度**
4. **前端轻量即可，重点放在 Agent、RAG、状态流和工具调用**

---

## 3. 技术栈（推荐定版）

### 3.1 后端主栈
- Python 3.11+
- FastAPI
- LangChain
- LangGraph
- Chroma（或 FAISS，二选一，优先 Chroma）
- SQLite（第一版够用）
- Pydantic

### 3.2 模型层
优先选一个即可：
- DeepSeek
- 通义千问
- Claude

要求：
- 支持文本生成
- 支持结构化输出更好
- 开发阶段成本低

### 3.3 前端
- Vue3 + TypeScript
- Vite
- Axios
- 简单 UI 组件库可选：Element Plus / Naive UI

### 3.4 知识库内容
RAG 文档建议放 Markdown/JSON：
- 常见食材热量表
- 常见运动消耗表
- 减脂饮食原则
- 减脂禁忌和误区
- 常见减脂食谱

---

## 4. 项目架构

### 4.1 核心架构
用户输入 -> LangGraph 工作流 -> 工具调用 / RAG 检索 -> 模型生成 -> 结构化输出 -> 前端展示 / 数据库存储

### 4.2 模块划分

#### A. 用户信息模块
- 基础信息录入
- 目标与偏好设置
- 历史记录查询

#### B. RAG 知识库模块
- 食材热量知识库
- 运动消耗知识库
- 减脂知识库
- 检索增强回答

#### C. 工具调用模块
至少实现以下工具：
1. `calc_bmr_tool`：基础代谢计算
2. `calc_daily_calorie_tool`：每日推荐热量计算
3. `food_calorie_lookup_tool`：食材热量查询
4. `exercise_calorie_lookup_tool`：运动消耗查询
5. `generate_meal_plan_tool`：生成饮食建议
6. `generate_workout_plan_tool`：生成运动建议

#### D. LangGraph 工作流模块
第一版建议节点：
1. 用户信息解析节点
2. 检索知识节点
3. 热量计算节点
4. 饮食建议节点
5. 运动建议节点
6. 总结输出节点

第二版可增加：
7. 每日打卡分析节点
8. 次日调整建议节点

#### E. 前端模块
- 首页 / 项目介绍
- 基础信息录入页
- 生成减脂计划页
- 每日打卡页
- 历史记录页
- 聊天/追问页（可选）

#### F. 数据持久化模块
建议最少存以下表：
- users
- plans
- checkins
- chat_messages（可选）
- knowledge_docs（可选，仅管理用途）

---

## 5. 阶段性开发安排（最适合 Agent 执行）

## 阶段 1：项目初始化与最小主链路
### 目标
跑通“输入信息 -> 生成减脂计划”的最小版本。

### 要做的事
1. 初始化 Python 后端项目（FastAPI）
2. 初始化 Vue3 前端项目
3. 建立基础目录结构
4. 完成基础信息录入接口
5. 完成一个最简单的 LangChain 调用 demo
6. 完成“生成减脂计划”接口
7. 前端展示生成结果

### 阶段验收
- 用户输入基础信息后，能得到一份饮食 + 运动建议
- 前后端能联通
- 项目能本地跑起来

---

## 阶段 2：RAG 接入
### 目标
让回答有知识依据，而不是纯模型发挥。

### 要做的事
1. 整理 20-50 条减脂知识文档
2. 做文本切分
3. 建立向量库
4. 实现检索接口
5. 在“生成减脂计划”前先检索知识
6. 把检索结果作为上下文输入模型

### 阶段验收
- 回答中能明显体现知识库内容
- 可以根据“低碳饮食”“乳糖不耐受”“跑步减脂”等关键词给出更有依据的建议

---

## 阶段 3：LangGraph 工作流
### 目标
把单次模型调用升级成可解释的工作流。

### 要做的事
1. 定义 State
2. 定义节点：
   - parse_user_profile
   - retrieve_knowledge
   - calc_calorie
   - generate_meal_plan
   - generate_workout_plan
   - summarize_plan
3. 按顺序连接节点
4. 输出结构化结果
5. 保存计划到数据库

### 阶段验收
- 不是单个 prompt 完成全部任务，而是节点化执行
- 能在面试里讲清楚各节点职责

---

## 阶段 4：每日打卡与复盘
### 目标
让项目具备连续交互和状态价值。

### 要做的事
1. 新增每日打卡接口
2. 存储饮食与运动记录
3. 新增“今日复盘”节点
4. 根据历史记录输出次日调整建议
5. 前端展示历史记录与复盘结果

### 阶段验收
- 用户至少可以连续 2-3 天打卡
- 系统能根据历史记录调整建议

---

## 阶段 5：展示优化与求职包装
### 目标
让项目可演示、可投递、可面试。

### 要做的事
1. 补 README
2. 补架构图和流程图
3. 补项目截图
4. 准备 1 分钟项目介绍
5. 准备 3 分钟技术版项目介绍
6. 整理高频追问答案
7. 如有时间，部署前后端

### 阶段验收
- GitHub 打开能看懂项目
- 能完整演示一遍主链路
- 能回答为什么用 LangGraph / RAG / 工具调用

---

## 6. 推荐目录结构

```bash
fat-loss-agent/
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ api/
│  │  ├─ core/
│  │  ├─ models/
│  │  ├─ schemas/
│  │  ├─ services/
│  │  ├─ rag/
│  │  ├─ tools/
│  │  ├─ graph/
│  │  └─ db/
│  ├─ data/
│  │  ├─ docs/
│  │  └─ vectorstore/
│  ├─ requirements.txt
│  └─ .env.example
├─ frontend/
│  ├─ src/
│  │  ├─ views/
│  │  ├─ components/
│  │  ├─ api/
│  │  ├─ stores/
│  │  └─ router/
│  ├─ package.json
│  └─ vite.config.ts
├─ README.md
└─ docs/
   ├─ architecture.md
   └─ demo-script.md
```

---

## 7. 最小可用接口设计

### 7.1 用户信息
- `POST /api/profile/create`
- `GET /api/profile/:id`

### 7.2 生成减脂计划
- `POST /api/plan/generate`

请求体示例：
```json
{
  "gender": "male",
  "age": 22,
  "height": 175,
  "weight": 82,
  "target_weight": 72,
  "activity_level": "medium",
  "diet_preference": "high_protein",
  "forbidden_foods": ["milk"]
}
```

### 7.3 每日打卡
- `POST /api/checkin/create`
- `GET /api/checkin/history/:userId`

### 7.4 聊天追问（可选）
- `POST /api/chat/send`

---

## 8. 数据库最小表设计

### users
- id
- gender
- age
- height
- weight
- target_weight
- activity_level
- diet_preference
- forbidden_foods
- created_at

### plans
- id
- user_id
- daily_calorie_target
- meal_plan
- workout_plan
- summary
- created_at

### checkins
- id
- user_id
- date
- foods
- exercises
- weight
- note
- created_at

### chat_messages（可选）
- id
- user_id
- role
- content
- created_at

---

## 9. 适合 Agent 执行的任务拆解

把下面这段直接丢给 Claude Code / 其他 Agent 执行。

### 任务拆解指令
1. 先初始化一个 Python FastAPI 项目和一个 Vue3 + TypeScript 前端项目。
2. 后端先实现最小接口：用户信息录入、生成减脂计划。
3. 使用 LangChain 完成一个最小 prompt + model + parser 链路。
4. 接入基础减脂知识库，使用 Chroma 做最小 RAG 检索。
5. 用 LangGraph 把“用户信息解析 -> 检索知识 -> 热量计算 -> 饮食建议 -> 运动建议 -> 总结输出”串成状态流。
6. 前端完成基础录入页和结果展示页。
7. 保存用户信息和生成结果到 SQLite。
8. 完成 README，包含项目介绍、功能流程、技术栈、启动方式、截图占位。
9. 所有代码要有清晰目录结构，不要把逻辑全堆在一个文件里。
10. 每完成一个阶段，都输出：已完成内容、待完成内容、下一步建议。

---

## 10. 面试时怎么讲

### 项目一句话介绍
这是一个基于 Agentic RAG 的个性化减脂教练应用，支持根据用户身体信息、饮食偏好和每日打卡记录，动态生成饮食与运动建议，并通过 LangGraph 工作流实现状态管理和连续调整。

### 项目亮点
1. 垂直场景明确：减脂教练
2. 不只是聊天：有计划生成、有打卡、有复盘
3. 有 RAG：减少纯模型幻觉
4. 有工具调用：热量和运动消耗计算
5. 有状态流：适合讲 Agent / Workflow

### 可讲技术点
- 为什么用 LangGraph 而不是简单 prompt
- RAG 解决了什么问题
- 工具调用怎么做
- 如何做每日打卡和状态调整
- 前后端如何联动

---

## 11. 开发优先级（必须遵守）

### P0（必须先做）
- 基础信息录入
- 生成减脂计划
- 最小 RAG
- LangGraph 基础工作流
- 前后端联通
- 数据库存储

### P1（建议做）
- 每日打卡
- 复盘调整
- 历史记录页
- 聊天追问

### P2（有时间再做）
- 复杂自我反思
- 多 Agent 协作
- LangSmith 深度评估
- 流式输出
- 多端适配

---

## 12. 不要做的事

1. 不要第一版就做复杂多 Agent
2. 不要第一版就追求 UI 很精致
3. 不要为了技术名词堆满项目
4. 不要一开始就做复杂营养学专家系统
5. 不要把重点放在模型选择上，先把工作流和产品闭环做出来

---

## 13. 最终交付标准

### 最低标准
- 能录入用户信息
- 能生成饮食和运动建议
- 能从知识库检索相关内容
- 能讲清楚 LangGraph + RAG 的作用

### 较好标准
- 有每日打卡和历史记录
- 能根据打卡做次日调整
- 有清晰 README 和截图
- 有可演示前端

### 最佳标准
- 有部署地址
- 有完整演示视频
- 有 1 分钟 / 3 分钟项目介绍
- 能作为 AI 应用开发 / 大模型应用开发实习项目直接写进简历

