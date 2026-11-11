<!-- 文件路径: frontend/src/components/AppSidebar.vue -->
<template>
  <aside class="sidebar">
    <!-- 品牌 -->
    <div class="brand">
      <div class="brand-logo">
        <Icon name="scale" :size="19" :stroke-width="1.8" />
      </div>
      <div class="brand-text">
        <div class="brand-name">法律</div>
        <div class="brand-sub">法律知识库 · RAG 智能问答</div>
      </div>
    </div>

    <!-- 新建 -->
    <button class="new-btn" @click="newSession">
      <Icon name="plus" :size="16" :stroke-width="2.4" />
      <span>新建对话</span>
      <kbd>Ctrl K</kbd>
    </button>

    <!-- 搜索 -->
    <div class="search">
      <Icon name="search" :size="15" />
      <input
        v-model="keyword"
        type="text"
        placeholder="搜索历史会话"
        @input="onSearchInput"
      />
      <button v-if="keyword" class="search-clear" @click="clearSearch">
        <Icon name="close" :size="13" :stroke-width="2.4" />
      </button>
    </div>

    <!-- 会话列表 -->
    <div class="session-scroll">
      <div v-if="state.sessionsLoading && !state.sessions.length" class="loading-list">
        <div v-for="i in 4" :key="i" class="skeleton" />
      </div>

      <template v-else>
        <!-- 草稿会话 -->
        <div
          v-if="!state.currentSessionId"
          class="session-item active draft"
          @click="newSession"
        >
          <div class="session-main">
            <div class="session-title">新对话</div>
            <div class="session-meta">尚未发送消息</div>
          </div>
          <span class="draft-dot" />
        </div>

        <div v-for="group in groups" :key="group.key" class="group">
          <div class="group-label">
            <span>{{ group.label }}</span>
            <span class="group-count">{{ group.items.length }}</span>
          </div>

          <div
            v-for="session in group.items"
            :key="session.session_id"
            class="session-item"
            :class="{ active: session.session_id === state.currentSessionId }"
            @click="onSelect(session.session_id)"
          >
            <div v-if="editingId !== session.session_id" class="session-main">
              <div class="session-title" :title="session.title">{{ session.title }}</div>
              <div class="session-meta">
                {{ shortStamp(session.last_message_at || session.created_at) }} ·
                {{ session.message_count }} 条
              </div>
            </div>

            <!-- 行内重命名 -->
            <input
              v-else
              ref="renameInput"
              v-model="editingTitle"
              class="rename-input"
              @click.stop
              @keyup.enter="commitRename(session)"
              @keyup.esc="cancelRename"
              @blur="commitRename(session)"
            />

            <div v-if="editingId !== session.session_id" class="session-actions">
              <button class="mini" title="重命名" @click.stop="startRename(session)">
                <Icon name="pencil" :size="14" />
              </button>
              <button class="mini danger" title="删除" @click.stop="onDelete(session)">
                <Icon name="trash" :size="14" />
              </button>
            </div>
          </div>
        </div>

        <div v-if="!groups.length && state.currentSessionId" class="empty-list">
          <Icon name="message" :size="26" />
          <p>{{ keyword ? '没有匹配的会话' : '还没有咨询记录' }}</p>
          <span>发送第一个问题后会自动保存到数据库</span>
        </div>
      </template>
    </div>

    <!-- 底部导航 -->
    <div class="sidebar-foot">
      <button
        v-for="item in navs"
        :key="item.key"
        class="nav-item"
        :class="{ active: state.view === item.key }"
        @click="onNav(item)"
      >
        <Icon :name="item.icon" :size="16" />
        <span>{{ item.label }}</span>
      </button>

      <div class="status-row">
        <span class="status-dot" :class="statusClass" />
        <span class="status-text">{{ statusText }}</span>
        <span class="status-ver">v1.0</span>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref } from 'vue'

import Icon from '@/components/Icon.vue'
import {
  deleteSession,
  loadSessions,
  newSession,
  renameSession,
  selectSession,
  state,
  switchView,
} from '@/stores/app'
import { askConfirm } from '@/stores/confirm'
import { groupSessions, shortStamp } from '@/utils/time'

const keyword = ref(state.keyword)
const editingId = ref('')
const editingTitle = ref('')
const renameInput = ref(null)

const navs = [
  { key: 'chat', label: '法律咨询', icon: 'message' },
  { key: 'statute', label: '法条检索', icon: 'book' },
  { key: 'knowledge', label: '知识库', icon: 'database' },
  { key: 'stats', label: '数据概览', icon: 'chart' },
  { key: 'settings', label: '系统设置', icon: 'settings' },
]

const groups = computed(() => groupSessions(state.sessions))

const statusClass = computed(() => {
  const status = state.health?.status
  if (status === 'ok') return 'ok'
  if (status === 'degraded') return 'warn'
  return 'bad'
})

const statusText = computed(() => {
  const status = state.health?.status
  if (status === 'ok') return '服务正常'
  if (status === 'degraded') return '部分服务异常'
  return '服务未连接'
})

let searchTimer = null
function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    state.keyword = keyword.value.trim()
    loadSessions()
  }, 260)
}

function clearSearch() {
  keyword.value = ''
  state.keyword = ''
  loadSessions()
}

function onSelect(sessionId) {
  if (sessionId === state.currentSessionId) return
  selectSession(sessionId)
}

function onNav(item) {
  // 设置页和其他模块一样是独立视图，不再弹抽屉
  switchView(item.key)
}

async function startRename(session) {
  editingId.value = session.session_id
  editingTitle.value = session.title
  await nextTick()
  const input = Array.isArray(renameInput.value)
    ? renameInput.value[0]
    : renameInput.value
  input?.focus()
  input?.select()
}

function cancelRename() {
  editingId.value = ''
  editingTitle.value = ''
}

async function commitRename(session) {
  if (editingId.value !== session.session_id) return
  const next = editingTitle.value.trim()
  editingId.value = ''
  if (!next || next === session.title) return
  await renameSession(session.session_id, next)
}

async function onDelete(session) {
  const ok = await askConfirm({
    title: '删除这个会话？',
    message: `「${session.title}」及其 ${session.message_count} 条聊天记录将被永久删除。`,
    detail: '此操作不可撤销，数据库中的记录会一并清除。',
    confirmText: '删除会话',
  })
  if (ok) await deleteSession(session.session_id)
}

function onKeydown(event) {
  // Ctrl/Cmd + K 新建对话
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    newSession()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  if (!state.sessions.length) loadSessions()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  clearTimeout(searchTimer)
})
</script>

<style scoped>
.sidebar {
  width: var(--sidebar-w);
  flex: none;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--sidebar);
  border-right: 1px solid var(--border);
  padding: 16px 12px 10px;
}

/* ---------- 品牌 ---------- */
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 2px 6px 16px;
}
.brand-logo {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  color: #fff;
  background: linear-gradient(135deg, #1e3a8a, #274b9f 55%, #a97b2f);
  box-shadow: 0 6px 14px -6px rgba(30, 58, 138, 0.55);
  flex: none;
}
.brand-name {
  font-size: 14.5px;
  font-weight: 650;
  letter-spacing: 0.2px;
}
.brand-sub {
  font-size: 11px;
  color: var(--text-3);
  letter-spacing: 0.3px;
  margin-top: 1px;
}

/* ---------- 新建按钮 ---------- */
.new-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 40px;
  padding: 0 12px;
  border-radius: 11px;
  background: var(--primary);
  color: #fff;
  font-weight: 550;
  font-size: 13.5px;
  box-shadow: 0 8px 18px -10px rgba(30, 58, 138, 0.95);
  transition: background 0.16s, transform 0.08s;
}
.new-btn:hover {
  background: var(--primary-600);
}
.new-btn:active {
  transform: translateY(1px);
}
.new-btn kbd {
  margin-left: auto;
  font-family: var(--font);
  font-size: 10.5px;
  padding: 2px 6px;
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.18);
  color: rgba(255, 255, 255, 0.9);
  letter-spacing: 0.4px;
}

/* ---------- 搜索 ---------- */
.search {
  position: relative;
  display: flex;
  align-items: center;
  gap: 7px;
  height: 34px;
  margin: 14px 0 6px;
  padding: 0 10px;
  border-radius: 9px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-3);
  transition: border-color 0.16s, box-shadow 0.16s;
}
.search:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-ring);
}
.search input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: none;
  font-size: 13px;
  color: var(--text);
}
.search input::placeholder {
  color: var(--text-3);
}
.search-clear {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--bg-soft);
  color: var(--text-3);
}
.search-clear:hover {
  background: var(--border-strong);
  color: var(--text);
}

/* ---------- 会话列表 ---------- */
.session-scroll {
  flex: 1;
  overflow-y: auto;
  margin: 2px -4px 0;
  padding: 0 4px 8px;
}
.group {
  margin-top: 12px;
}
.group-label {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 8px 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0.6px;
}
.group-count {
  font-weight: 500;
  opacity: 0.7;
}

.session-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 9px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s;
  margin-bottom: 2px;
}
.session-item:hover {
  background: var(--bg-soft);
}
.session-item.active {
  background: var(--primary-soft);
}
.session-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 18px;
  border-radius: 0 3px 3px 0;
  background: var(--primary);
}
.session-item.active .session-title {
  color: var(--primary-600);
  font-weight: 600;
}

.session-main {
  min-width: 0;
  flex: 1;
}
.session-title {
  font-size: 13.2px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.45;
}
.session-meta {
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 1px;
}

.session-actions {
  display: flex;
  gap: 1px;
  opacity: 0;
  transition: opacity 0.15s;
  flex: none;
}
.session-item:hover .session-actions {
  opacity: 1;
}
.mini {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 7px;
  color: var(--text-3);
}
.mini:hover {
  background: var(--surface);
  color: var(--text);
  box-shadow: var(--shadow-sm);
}
.mini.danger:hover {
  background: var(--danger-soft);
  color: var(--danger);
}

.rename-input {
  flex: 1;
  min-width: 0;
  height: 28px;
  padding: 0 7px;
  border-radius: 7px;
  border: 1px solid var(--primary);
  outline: none;
  font-size: 13px;
  background: var(--surface);
  box-shadow: 0 0 0 3px var(--primary-ring);
}

.draft {
  margin-top: 10px;
  border: 1px dashed var(--border-strong);
  background: transparent;
}
.draft.active {
  border-color: transparent;
}
.draft-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--primary);
  flex: none;
}

.empty-list {
  margin-top: 40px;
  text-align: center;
  color: var(--text-3);
  font-size: 12.5px;
}
.empty-list svg {
  opacity: 0.5;
}
.empty-list p {
  margin: 8px 0 2px;
  color: var(--text-2);
  font-size: 13px;
}
.empty-list span {
  font-size: 11.5px;
}

.skeleton {
  height: 34px;
  border-radius: 10px;
  margin-bottom: 6px;
  background: linear-gradient(90deg, #eef0f6 25%, #f6f7fb 37%, #eef0f6 63%);
  background-size: 400% 100%;
  animation: shimmer 1.3s ease infinite;
}
@keyframes shimmer {
  0% {
    background-position: 100% 50%;
  }
  100% {
    background-position: 0 50%;
  }
}

/* ---------- 底部 ---------- */
.sidebar-foot {
  border-top: 1px solid var(--border);
  padding-top: 8px;
  margin-top: 2px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  height: 34px;
  padding: 0 10px;
  border-radius: 9px;
  font-size: 13px;
  color: var(--text-2);
  transition: background 0.15s, color 0.15s;
}
.nav-item:hover {
  background: var(--bg-soft);
  color: var(--text);
}
.nav-item.active {
  background: var(--primary-soft);
  color: var(--primary-600);
  font-weight: 550;
}

.status-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 10px 4px;
  font-size: 11px;
  color: var(--text-3);
}
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-3);
  flex: none;
}
.status-dot.ok {
  background: var(--success);
  box-shadow: 0 0 0 3px rgba(15, 157, 118, 0.14);
}
.status-dot.warn {
  background: var(--warn);
  box-shadow: 0 0 0 3px rgba(217, 119, 6, 0.14);
}
.status-dot.bad {
  background: var(--danger);
  box-shadow: 0 0 0 3px rgba(229, 72, 77, 0.14);
}
.status-ver {
  margin-left: auto;
  opacity: 0.6;
}
</style>
