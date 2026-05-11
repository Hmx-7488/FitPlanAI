<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="home">
    <el-card class="hero-card">
      <h2>减脂 Agent</h2>
      <p>基于 Agentic RAG 的个性化减脂教练，为你量身定制饮食和运动计划，并根据每日打卡动态调整。</p>
      <el-button type="primary" size="large" @click="router.push('/profile')">
        开始建档
      </el-button>
      <el-button size="large" @click="router.push('/checkin')">
        每日打卡
      </el-button>
    </el-card>

    <el-row :gutter="20" class="features">
      <el-col :span="6">
        <el-card>
          <h3>信息录入</h3>
          <p>填写身体数据、目标体重、饮食偏好和忌口信息，建立个人档案。</p>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card>
          <h3>智能计划</h3>
          <p>基于 RAG 知识库和 LangGraph 工作流，生成个性化饮食和运动方案。</p>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card>
          <h3>每日打卡</h3>
          <p>记录每天的饮食和运动，追踪体重变化，养成健康习惯。</p>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card>
          <h3>AI 复盘</h3>
          <p>根据打卡记录进行智能复盘分析，给出次日调整建议。</p>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.home {
  text-align: center;
}

.hero-card {
  margin-bottom: 40px;
}

.hero-card h2 {
  font-size: 28px;
  color: #303133;
  margin-bottom: 12px;
}

.hero-card p {
  font-size: 16px;
  color: #606266;
  margin-bottom: 24px;
}

.hero-card .el-button {
  margin: 0 8px;
}

.features {
  margin-top: 20px;
}

.features h3 {
  font-size: 18px;
  color: #303133;
  margin-bottom: 8px;
}

.features p {
  color: #606266;
  font-size: 14px;
}
</style>
