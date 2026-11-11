<!-- 文件路径: frontend/src/components/ChatView.vue -->
<template>
  <div class="chat-view">
    <!-- 顶部栏 -->
    <header class="chat-header">
      <div class="header-left">
        <div class="title-wrap">
          <input
            v-if="editing"
            ref="titleInput"
            v-model="titleDraft"
            class="title-input"
            maxlength="60"
            @keyup.enter="commitTitle"
            @keyup.esc="editing = false"
            @blur="commitTitle"
          />
          <h2 v-else class="title" @dblclick="startEdit">
            {{ title }}
            <button
              v-if="state.currentSessionId"
              class="title-edit"
              title="重命名"
              @click="startEdit"
            >
              <Icon name="pencil" :size="13" />
            </button>
          </h2>

          <div class="subtitle">
            <span>{{ state.messages.length }} 条消息</span>
            <span class="dot">·</span>
            <span class="model">
              <Icon name="cpu" :size="11" />
              {{ state.settings?.model_name || '加载中' }}
            </span>
            <span v-if="state.historyLoading" class="dot">· 加载中…</span>
          </div>
        </div>
      </div>

      <div class="header-right">
        <!-- 模式切换 -->
        <div class="segmented" role="tablist">
          <button
            class="seg-btn"
            :class="{ active: state.mode === 'agent' }"
            title="先检索法条，再依据条文回答并标注出处"
            @click="setMode('agent')"
          >
            <Icon name="scale" :size="13" />
            法律检索
          </button>
          <button
            class="seg-btn"
            :class="{ active: state.mode === 'direct' }"
            title="跳过检索，直接用模型回答（更快，但可能没有出处）"
            @click="setMode('direct')"
          >
            <Icon name="zap" :size="13" />
            直聊
          </button>
        </div>

        <!-- 精排开关 -->
        <label class="switch rerank" title="关闭后只用向量粗排，更快但精度略低">
          <input type="checkbox" v-model="rerank" />
          <span class="switch-track" />
          <span class="switch-label">精排</span>
        </label>

        <div class="divider" />

        <button class="icon-btn" title="导出当前会话为 Markdown" @click="exportCurrentSession">
          <Icon name="download" :size="17" />
        </button>
        <button
          class="icon-btn"
          title="清空当前会话消息"
          :disabled="!state.messages.length"
          @click="onClear"
        >
          <Icon name="broom" :size="17" />
        </button>
        <button class="icon-btn" title="系统设置" @click="switchView('settings')">
          <Icon name="settings" :size="17" />
        </button>
      </div>
    </header>

    <!-- 消息区 -->
    <MessageList
      :messages="state.messages"
      :thinking="state.thinking"
      :loading="state.historyLoading"
      @pick="onPick"
      @regenerate="onRegenerate"
    />

    <!-- 输入区 -->
    <ChatComposer ref="composerRef" />
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'

import ChatComposer from '@/components/ChatComposer.vue'
import Icon from '@/components/Icon.vue'
import MessageList from '@/components/MessageList.vue'
import {
  clearCurrentMessages,
  exportCurrentSession,
  switchView,
  regenerate,
  renameSession,
  state,
} from '@/stores/app'
import { askConfirm } from '@/stores/confirm'
import { toastError } from '@/stores/toast'

const composerRef = ref(null)
const titleInput = ref(null)
const editing = ref(false)
const titleDraft = ref('')

const title = computed(() => {
  const session = state.sessions.find(
    (item) => item.session_id === state.currentSessionId
  )
  return session?.title || '新对话'
})

const rerank = computed({
  get: () => state.useReranker,
  set: (value) => {
    state.useReranker = value
    localStorage.setItem('legal_reranker', String(value))
  },
})

function setMode(mode) {
  if (state.streaming) {
    toastError('正在生成回答，请先停止再切换模式')
    return
  }
  state.mode = mode
  localStorage.setItem('legal_mode', mode)
}

async function startEdit() {
  if (!state.currentSessionId) return
  editing.value = true
  titleDraft.value = title.value
  await nextTick()
  titleInput.value?.focus()
  titleInput.value?.select()
}

async function commitTitle() {
  if (!editing.value) return
  editing.value = false
  const next = titleDraft.value.trim()
  if (!next || next === title.value) return
  await renameSession(state.currentSessionId, next)
}

function onPick(text) {
  composerRef.value?.sendExternal(text)
}

function onRegenerate(text) {
  regenerate(text)
}

async function onClear() {
  const ok = await askConfirm({
    title: '清空聊天记录？',
    message: '当前会话的所有消息都会被删除，会话本身会保留。',
    detail: '清空后 Agent 也会失去这段对话的记忆。',
    confirmText: '清空记录',
  })
  if (ok) await clearCurrentMessages()
}

// 切换会话时退出标题编辑态，避免输入框带着旧标题串场
watch(
  () => state.currentSessionId,
  () => {
    editing.value = false
  }
)
</script>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  background: var(--bg);
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 24px;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  flex: none;
  z-index: 5;
}

.header-left {
  min-width: 0;
  flex: 1;
}
.title-wrap {
  min-width: 0;
}
.title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 15px;
  font-weight: 650;
  letter-spacing: -0.1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
}
.title-edit {
  display: none;
  color: var(--text-3);
  padding: 2px;
  border-radius: 5px;
}
.title:hover .title-edit {
  display: inline-grid;
}
.title-edit:hover {
  background: var(--bg-soft);
  color: var(--text-2);
}
.title-input {
  width: 100%;
  max-width: 420px;
  height: 28px;
  padding: 0 8px;
  border-radius: 7px;
  border: 1px solid var(--primary);
  outline: none;
  font-size: 15px;
  font-weight: 650;
  background: var(--surface);
  box-shadow: 0 0 0 3px var(--primary-ring);
}
.subtitle {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
  font-size: 11.5px;
  color: var(--text-3);
}
.subtitle .dot {
  opacity: 0.6;
}
.model {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
}
.divider {
  width: 1px;
  height: 20px;
  background: var(--border);
  margin: 0 3px;
}

/* ---------- 分段控件 ---------- */
.segmented {
  display: flex;
  padding: 2px;
  border-radius: 9px;
  background: var(--bg-soft);
  gap: 2px;
}
.seg-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 26px;
  padding: 0 10px;
  border-radius: 7px;
  font-size: 12.2px;
  color: var(--text-3);
  font-weight: 500;
  transition: background 0.16s, color 0.16s, box-shadow 0.16s;
}
.seg-btn:hover {
  color: var(--text-2);
}
.seg-btn.active {
  background: var(--surface);
  color: var(--primary-600);
  box-shadow: var(--shadow-sm);
  font-weight: 600;
}

.rerank {
  margin-left: 4px;
}
.rerank .switch-label {
  font-size: 12.2px;
}

.icon-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

@media (max-width: 860px) {
  .chat-header {
    padding: 10px 14px;
    gap: 8px;
  }
  .rerank,
  .divider {
    display: none;
  }
}
</style>
