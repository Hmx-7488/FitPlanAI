<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

const steps = [
  { num: '01', title: '建档', desc: '录入身体数据、目标和饮食偏好', route: '/profile' },
  { num: '02', title: '生成计划', desc: 'AI 计算热量缺口，生成饮食和运动方案', route: '/plan' },
  { num: '03', title: '食材识别', desc: '拍照识别食材，生成轻食菜谱', route: '/food' },
  { num: '04', title: '打卡复盘', desc: '记录饮食运动，AI 分析调整', route: '/checkin' },
]
</script>

<template>
  <div class="home">
    <!-- Hero -->
    <section class="hero">
      <p class="hero-eyebrow">基于 Agentic RAG 的智能减脂教练</p>
      <h1 class="hero-title">吃对了，练对了，<br>脂肪自然就掉了。</h1>
      <p class="hero-sub">
        输入身体数据，AI 生成饮食和运动计划。<br>
        每天打卡，自动复盘并调整方案。
      </p>
      <div class="hero-actions">
        <button class="btn btn-primary" @click="router.push('/profile')">开始建档</button>
        <button class="btn btn-ghost" @click="router.push('/checkin')">每日打卡</button>
      </div>
    </section>

    <!-- Flow -->
    <section class="flow">
      <h2 class="section-title">四步闭环</h2>
      <div class="flow-grid">
        <div
          v-for="step in steps"
          :key="step.num"
          class="flow-step"
          @click="router.push(step.route)"
        >
          <span class="step-num">{{ step.num }}</span>
          <h3 class="step-title">{{ step.title }}</h3>
          <p class="step-desc">{{ step.desc }}</p>
        </div>
      </div>
    </section>

    <!-- Tech -->
    <section class="tech">
      <h2 class="section-title">技术亮点</h2>
      <div class="tech-grid">
        <div class="tech-item">
          <h3>LangGraph 工作流</h3>
          <p>6 节点状态流：用户信息解析 → 知识检索 → 热量计算 → 饮食建议 → 运动建议 → 总结输出。每个节点职责清晰，结果可解释。</p>
        </div>
        <div class="tech-item">
          <h3>Chroma RAG 检索</h3>
          <p>5 篇减脂知识文档构建向量库，语义检索食材热量、运动消耗、减脂原则。回答有据可依，不是纯模型发挥。</p>
        </div>
        <div class="tech-item">
          <h3>工具调用</h3>
          <p>BMR（Mifflin-St Jeor）、TDEE、三大营养素分配，全部用 Python 函数精确计算，不依赖 LLM 估算。</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.home {
  max-width: 900px;
  margin: 0 auto;
}

/* Hero */
.hero {
  padding: var(--space-12) 0 var(--space-10);
  text-align: center;
}

.hero-eyebrow {
  font-size: var(--text-sm);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--color-accent);
  margin-bottom: var(--space-4);
}

.hero-title {
  font-size: clamp(28px, 5vw, 42px);
  font-weight: 800;
  line-height: var(--leading-tight);
  color: var(--color-text-primary);
  margin-bottom: var(--space-5);
  letter-spacing: -0.02em;
}

.hero-sub {
  font-size: var(--text-md);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin-bottom: var(--space-8);
  max-width: 480px;
  margin-left: auto;
  margin-right: auto;
}

.hero-actions {
  display: flex;
  justify-content: center;
  gap: var(--space-3);
}

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 44px;
  padding: 0 var(--space-6);
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  font-weight: 600;
  font-family: var(--font-family);
  border: none;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.btn-primary {
  background-color: var(--color-accent);
  color: white;
}

.btn-primary:hover {
  background-color: var(--color-accent-hover);
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

.btn-ghost {
  background-color: transparent;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
}

.btn-ghost:hover {
  color: var(--color-text-primary);
  border-color: var(--color-text-tertiary);
}

/* Flow */
.flow {
  padding: var(--space-10) 0;
}

.section-title {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: var(--space-6);
  letter-spacing: -0.01em;
}

.flow-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-4);
}

.flow-step {
  padding: var(--space-6) var(--space-5);
  background: var(--color-surface);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease-out);
}

.flow-step:hover {
  border-color: var(--color-accent);
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.step-num {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  font-weight: 700;
  color: var(--color-accent);
  display: block;
  margin-bottom: var(--space-3);
}

.step-title {
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: var(--space-2);
}

.step-desc {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-normal);
}

/* Tech */
.tech {
  padding: var(--space-10) 0;
  border-top: 1px solid var(--color-border-subtle);
}

.tech-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-5);
}

.tech-item {
  padding: var(--space-5);
}

.tech-item h3 {
  font-size: var(--text-base);
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: var(--space-2);
}

.tech-item p {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
}

/* Responsive */
@media (max-width: 768px) {
  .flow-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .tech-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 480px) {
  .flow-grid {
    grid-template-columns: 1fr;
  }
  .hero-actions {
    flex-direction: column;
    align-items: center;
  }
}
</style>
