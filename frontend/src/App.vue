<script setup lang="ts">
</script>

<template>
  <el-container class="app-container">
    <el-header class="app-header">
      <h1 class="app-title">减脂 Agent</h1>
      <el-menu mode="horizontal" router :default-active="$route.path" class="app-menu">
        <el-menu-item index="/">首页</el-menu-item>
        <el-menu-item index="/profile">信息录入</el-menu-item>
        <el-menu-item index="/plan">减脂计划</el-menu-item>
        <el-menu-item index="/checkin">每日打卡</el-menu-item>
        <el-menu-item index="/history">历史复盘</el-menu-item>
      </el-menu>
    </el-header>
    <el-main class="app-main">
      <router-view />
    </el-main>
  </el-container>
</template>

<style scoped>
.app-container {
  min-height: 100vh;
}

.app-header {
  display: flex;
  align-items: center;
  border-bottom: 1px solid #e4e7ed;
  padding: 0 20px;
}

.app-title {
  font-size: 20px;
  color: #409eff;
  margin-right: 40px;
  white-space: nowrap;
}

.app-menu {
  flex: 1;
  border-bottom: none;
}

.app-main {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
}
</style>
