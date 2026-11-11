<!-- 文件路径: frontend/src/App.vue -->
<template>
  <div class="app">
    <AppSidebar />

    <main class="main">
      <!-- 后端离线提示 -->
      <div v-if="offline" class="offline-bar">
        <Icon name="alert" :size="15" />
        <span>无法连接后端服务，请确认 FastAPI 已在 127.0.0.1:5000 启动</span>
        <button @click="retry">重试</button>
      </div>

      <!-- 对话视图常驻，切走再切回来输入框内容还在 -->
      <ChatView v-show="state.view === 'chat'" />
      <StatuteView v-if="state.view === 'statute'" />
      <KnowledgeView v-if="state.view === 'knowledge'" />
      <StatsView v-if="state.view === 'stats'" />
      <SettingsView v-if="state.view === 'settings'" />
    </main>

    <ConfirmDialog />
    <ToastHost />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import AppSidebar from '@/components/AppSidebar.vue'
import ChatView from '@/components/ChatView.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import Icon from '@/components/Icon.vue'
import KnowledgeView from '@/components/KnowledgeView.vue'
import SettingsView from '@/components/SettingsView.vue'
import StatuteView from '@/components/StatuteView.vue'
import StatsView from '@/components/StatsView.vue'
import ToastHost from '@/components/ToastHost.vue'
import { bootstrap, loadHealth, state } from '@/stores/app'

const offline = computed(() => state.health?.status === 'offline')
const timer = ref(null)

async function retry() {
  await loadHealth()
  if (!offline.value) window.location.reload()
}

onMounted(async () => {
  await bootstrap()
  // 每 60 秒探活一次，后端挂了能在界面上立刻看出来
  timer.value = window.setInterval(loadHealth, 60000)
})

onBeforeUnmount(() => {
  if (timer.value) window.clearInterval(timer.value)
})
</script>

<style scoped>
.app {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--bg);
}

.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  position: relative;
}

.offline-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 18px;
  background: var(--danger-soft);
  color: #a12a2e;
  font-size: 12.5px;
  border-bottom: 1px solid #f6cbcc;
  flex: none;
}
.offline-bar button {
  margin-left: auto;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 6px;
  background: #fff;
  color: #a12a2e;
  border: 1px solid #f0b6b8;
}
.offline-bar button:hover {
  background: #fff5f5;
}
</style>
