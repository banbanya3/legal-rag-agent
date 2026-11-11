<!-- 文件路径: frontend/src/components/MessageList.vue -->
<template>
  <div ref="scrollRef" class="scroll-area" @scroll="onScroll">
    <div class="inner">
      <!-- 空状态：欢迎页 -->
      <div v-if="!messages.length && !loading" class="welcome">
        <div class="welcome-badge">
          <Icon name="scale" :size="26" :stroke-width="1.7" />
        </div>
        <h1>
          你好，我是<span class="grad">法眼</span>
        </h1>
        <p class="welcome-desc">
          我读过 {{ docCount }} 份中国现行法律与司法解释，覆盖民事、劳动、刑事、商事、数字与知产、程序救济六大领域。
          提问时我会先判断问题属于哪个法律部门，检索对应法条，再依据条文回答，并标注出处。
        </p>

        <div class="stats-row">
          <div class="stat-chip">
            <span class="stat-num">{{ stats.sessions ?? '—' }}</span>
            <span class="stat-label">历史咨询</span>
          </div>
          <div class="stat-chip">
            <span class="stat-num">{{ stats.messages ?? '—' }}</span>
            <span class="stat-label">问答轮次</span>
          </div>
          <div class="stat-chip">
            <span class="stat-num">{{ stats.knowledge?.articles ?? '—' }}</span>
            <span class="stat-label">收录法条</span>
          </div>
          <div class="stat-chip">
            <span class="stat-num">{{ modelName }}</span>
            <span class="stat-label">当前模型</span>
          </div>
        </div>

        <div class="suggestions">
          <button
            v-for="item in suggestions"
            :key="item.text"
            class="suggestion"
            @click="$emit('pick', item.text)"
          >
            <div class="suggestion-icon" :class="item.tone">
              <Icon :name="item.icon" :size="16" />
            </div>
            <div class="suggestion-text">
              <div class="suggestion-title">{{ item.title }}</div>
              <div class="suggestion-body">{{ item.text }}</div>
            </div>
            <Icon name="chevronRight" :size="15" class="suggestion-arrow" />
          </button>
        </div>
      </div>

      <!-- 历史加载中 -->
      <div v-if="loading" class="history-loading">
        <span class="spinner" />
        正在加载历史记录…
      </div>

      <!-- 消息流 -->
      <MessageItem
        v-for="(message, index) in visibleMessages"
        :key="message.id"
        :message="message"
        :is-last="index === visibleMessages.length - 1 && message.role === 'assistant'"
        @regenerate="onRegenerate"
      />

      <!-- 思考过程 -->
      <div v-if="thinking.active" class="thinking">
        <div class="thinking-avatar">
          <Icon name="scale" :size="15" />
        </div>
        <div class="thinking-body">
          <div class="thinking-line">
            <span class="thinking-stage">{{ thinking.stage || '思考中…' }}</span>
            <span class="thinking-elapsed">{{ seconds }}s</span>
          </div>
          <div v-if="steps.length" class="thinking-tools">
            <span v-for="(step, i) in steps" :key="i" class="thinking-tool">
              <Icon name="check" :size="11" :stroke-width="3" />
              {{ step }}
            </span>
          </div>
          <div class="thinking-track"><span /></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import Icon from '@/components/Icon.vue'
import MessageItem from '@/components/MessageItem.vue'
import { state } from '@/stores/app'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  thinking: {
    type: Object,
    default: () => ({ active: false, stage: '', steps: [] }),
  },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['pick', 'regenerate'])

const scrollRef = ref(null)
const stickToBottom = ref(true)
const seconds = ref(0)
let timer = null

const stats = computed(() => state.stats || {})
const docCount = computed(() => stats.value.knowledge?.docs ?? 32)
const steps = computed(() => props.thinking?.steps || [])
const modelName = computed(() => {
  const name = state.settings?.model_name || '—'
  return name.length > 14 ? `${name.slice(0, 14)}…` : name
})

/**
 * 思考阶段隐藏"占位空气泡"，否则会出现两个 AI 头像：
 * 一个显示"正在生成…"，另一个显示检索进度，看着像两条回复。
 */
const visibleMessages = computed(() => {
  const list = props.messages
  const last = list[list.length - 1]
  if (
    props.thinking.active &&
    last &&
    last.role === 'assistant' &&
    !last.content
  ) {
    return list.slice(0, -1)
  }
  return list
})

const suggestions = [
  {
    icon: 'briefcase',
    tone: 'rag',
    title: '劳动纠纷',
    text: '试用期最长可以约定多久？公司延长试用期合法吗？',
  },
  {
    icon: 'heart',
    tone: 'doc',
    title: '婚姻家庭',
    text: '协议离婚有三十天冷静期，期间一方反悔怎么办？',
  },
  {
    icon: 'shield',
    tone: 'sql',
    title: '消费维权',
    text: '网购的商品拆封后还能七天无理由退货吗？',
  },
  {
    icon: 'alert',
    tone: 'direct',
    title: '刑事风险',
    text: '血液酒精含量 90mg/100ml 开车，会怎么处理？',
  },
]

function onScroll() {
  const el = scrollRef.value
  if (!el) return
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight
  stickToBottom.value = distance < 120
}

async function scrollToBottom() {
  if (!stickToBottom.value) return
  await nextTick()
  const el = scrollRef.value
  if (el) el.scrollTop = el.scrollHeight
}

function onRegenerate() {
  const lastUser = [...props.messages].reverse().find((m) => m.role === 'user')
  if (lastUser) emit('regenerate', lastUser.content)
}

watch(
  () => props.messages.length,
  () => {
    stickToBottom.value = true
    scrollToBottom()
  }
)

watch(
  () => state.scrollSignal,
  () => scrollToBottom()
)

watch(
  () => props.loading,
  (value) => {
    if (!value) scrollToBottom()
  }
)

watch(
  () => props.thinking.active,
  (active) => {
    clearInterval(timer)
    if (active) {
      seconds.value = 0
      const started = Date.now()
      timer = setInterval(() => {
        seconds.value = Math.floor((Date.now() - started) / 1000)
      }, 500)
      stickToBottom.value = true
      scrollToBottom()
    }
  },
  { immediate: true }
)

onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.scroll-area {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  scroll-behavior: smooth;
}
.inner {
  max-width: 880px;
  margin: 0 auto;
  padding: 28px 28px 20px;
}

/* ---------- 欢迎页 ---------- */
.welcome {
  padding: 42px 8px 20px;
  animation: fade-up 0.4s ease both;
}
@keyframes fade-up {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
}
.welcome-badge {
  width: 52px;
  height: 52px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #8b5cf6 55%, #0ea5e9);
  box-shadow: 0 14px 30px -14px rgba(99, 102, 241, 0.9);
  margin-bottom: 20px;
}
.welcome h1 {
  font-size: 27px;
  line-height: 1.35;
  margin: 0 0 10px;
  letter-spacing: -0.4px;
  font-weight: 650;
}
.grad {
  background: linear-gradient(100deg, #4f46e5, #7c3aed 45%, #0ea5e9);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.welcome-desc {
  margin: 0 0 24px;
  color: var(--text-3);
  font-size: 13.8px;
  max-width: 600px;
  line-height: 1.75;
}

.stats-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 30px;
}
.stat-chip {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 10px 16px;
  border-radius: 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
  min-width: 92px;
}
.stat-num {
  font-size: 17px;
  font-weight: 650;
  letter-spacing: -0.2px;
  font-variant-numeric: tabular-nums;
}
.stat-label {
  font-size: 11px;
  color: var(--text-3);
}

/* ---------- 建议卡 ---------- */
.suggestions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.suggestion {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px 14px;
  border-radius: 13px;
  border: 1px solid var(--border);
  background: var(--surface);
  text-align: left;
  transition: border-color 0.16s, box-shadow 0.16s, transform 0.16s;
}
.suggestion:hover {
  border-color: #cfd4ee;
  box-shadow: var(--shadow);
  transform: translateY(-1px);
}
.suggestion-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  flex: none;
  background: var(--primary-soft);
  color: var(--primary);
}
.suggestion-icon.sql {
  background: var(--success-soft);
  color: var(--success);
}
.suggestion-icon.doc {
  background: var(--warn-soft);
  color: var(--warn);
}
.suggestion-icon.direct {
  background: #e8f4fe;
  color: #0284c7;
}
.suggestion-text {
  min-width: 0;
  flex: 1;
}
.suggestion-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-3);
  margin-bottom: 1px;
}
.suggestion-body {
  font-size: 13.2px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.suggestion-arrow {
  color: var(--text-3);
  opacity: 0;
  transition: opacity 0.16s, transform 0.16s;
  flex: none;
}
.suggestion:hover .suggestion-arrow {
  opacity: 1;
  transform: translateX(2px);
}

/* ---------- 思考中 ---------- */
.thinking {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
  animation: fade-up 0.2s ease both;
}
.thinking-avatar {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #6366f1, #8b5cf6 60%, #0ea5e9);
  color: #fff;
  flex: none;
  margin-top: 2px;
  box-shadow: 0 6px 14px -7px rgba(99, 102, 241, 0.9);
}
.thinking-body {
  flex: 1;
  min-width: 0;
  max-width: min(78%, 760px);
  padding: 10px 16px 11px;
  border-radius: 14px;
  border-top-left-radius: 5px;
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
}
.thinking-line {
  display: flex;
  align-items: center;
  gap: 10px;
}
.thinking-stage {
  font-size: 13px;
  color: var(--text-2);
}
.thinking-elapsed {
  margin-left: auto;
  font-size: 11.5px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.thinking-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 7px;
}
.thinking-tool {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  padding: 1.5px 7px;
  border-radius: 5px;
  background: var(--success-soft);
  color: var(--success);
}
.thinking-track {
  margin-top: 9px;
  height: 2px;
  border-radius: 999px;
  background: var(--bg-soft);
  overflow: hidden;
}
.thinking-track span {
  display: block;
  width: 32%;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #6366f1, #0ea5e9);
  animation: slide 1.4s ease-in-out infinite;
}
@keyframes slide {
  0% {
    transform: translateX(-110%);
  }
  100% {
    transform: translateX(340%);
  }
}

.history-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  padding: 40px 0;
  color: var(--text-3);
  font-size: 13px;
}
.spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid var(--border-strong);
  border-top-color: var(--primary);
  animation: spin 0.8s linear infinite;
}

@media (max-width: 760px) {
  .suggestions {
    grid-template-columns: 1fr;
  }
  .inner {
    padding: 20px 16px;
  }
  .welcome h1 {
    font-size: 22px;
  }
}
</style>
