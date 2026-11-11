<!-- 文件路径: frontend/src/components/MessageItem.vue -->
<template>
  <div class="row" :class="message.role">
    <!-- 头像 -->
    <div class="avatar" :class="message.role">
      <template v-if="message.role === 'user'">我</template>
      <Icon v-else name="scale" :size="17" :stroke-width="1.9" />
    </div>

    <div class="body">
      <div class="bubble" :class="{ error: message.error }">
        <!-- 等待首个字时的思考态 -->
        <div v-if="message.pending && !message.content" class="waiting">
          <span class="dots"><i /><i /><i /></span>
          <span class="waiting-text">正在检索法条并组织回答…</span>
        </div>

        <div v-else-if="message.role === 'user'" class="user-text">{{ message.content }}</div>

        <div v-else class="md" v-html="rendered" />

        <!-- 法条依据面板 -->
        <div v-if="message.sources && message.sources.length" class="sources">
          <button class="sources-toggle" @click="showSources = !showSources">
            <Icon
              :name="showSources ? 'chevron' : 'chevronRight'"
              :size="14"
              :stroke-width="2.2"
            />
            <Icon name="book" :size="14" />
            <span>引用的法条</span>
            <span class="count">{{ message.sources.length }}</span>
            <span class="hint">{{ kindSummary }}</span>
          </button>

          <div v-if="showSources" class="sources-list">
            <div v-for="(src, index) in message.sources" :key="index" class="source-card">
              <div class="source-head">
                <span class="law-chip">{{ src.domain_label || '法律' }}</span>
                <span class="law-title">{{ src.title || '相关资料' }}</span>
                <span v-if="src.score != null" class="score">
                  <span class="score-bar">
                    <span class="score-fill" :style="{ width: scorePercent(src.score) }" />
                  </span>
                  {{ (src.score * 100).toFixed(1) }}%
                </span>
              </div>
              <pre class="source-text">{{ src.text }}</pre>
            </div>
          </div>
        </div>
      </div>

      <!-- 气泡下方操作条 -->
      <div class="meta">
        <span class="time">{{ message.created_at }}</span>
        <span v-if="message.elapsed_ms" class="elapsed">
          <Icon name="zap" :size="11" /> {{ formatDuration(message.elapsed_ms) }}
        </span>
        <span v-if="message.pending && message.content" class="generating">
          <i class="pulse" /> 生成中
        </span>

        <template v-if="!message.pending">
          <button class="meta-btn" title="复制内容" @click="copy">
            <Icon :name="copied ? 'check' : 'copy'" :size="13" />
            <span>{{ copied ? '已复制' : '复制' }}</span>
          </button>
          <button
            v-if="message.role === 'assistant' && isLast"
            class="meta-btn"
            title="重新生成"
            @click="$emit('regenerate')"
          >
            <Icon name="refresh" :size="13" />
            <span>重试</span>
          </button>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

import Icon from '@/components/Icon.vue'
import { toastSuccess } from '@/stores/toast'
import { renderMarkdown } from '@/utils/markdown'
import { formatDuration } from '@/utils/time'

const props = defineProps({
  message: { type: Object, required: true },
  isLast: { type: Boolean, default: false },
})

defineEmits(['regenerate'])

const showSources = ref(false)
const copied = ref(false)

const rendered = computed(() => renderMarkdown(props.message.content))

/**
 * 依据来源的一句话概括。
 * 不写"向量检索"这种技术词 —— 用户不关心怎么召回的，只关心查了几部法。
 */
const kindSummary = computed(() => {
  const list = props.message.sources || []
  const laws = new Set(list.map((s) => s.law_name).filter(Boolean))
  const hasRerank = list.some((s) => s.reranked)
  const base = laws.size > 1 ? `${laws.size} 部法律` : '法条原文'
  return hasRerank ? `${base} · 已精排` : base
})

function scorePercent(score) {
  const value = Math.max(0, Math.min(1, Number(score) || 0))
  return `${(value * 100).toFixed(1)}%`
}

async function copy() {
  try {
    await navigator.clipboard.writeText(props.message.content || '')
    copied.value = true
    toastSuccess('已复制到剪贴板')
    setTimeout(() => (copied.value = false), 1600)
  } catch {
    // 非 https 环境下 clipboard 不可用，降级用 textarea
    const textarea = document.createElement('textarea')
    textarea.value = props.message.content || ''
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    copied.value = true
    setTimeout(() => (copied.value = false), 1600)
  }
}
</script>

<style scoped>
.row {
  display: flex;
  gap: 12px;
  margin-bottom: 26px;
  animation: rise 0.24s ease both;
}
.row.user {
  flex-direction: row-reverse;
}
@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  flex: none;
  margin-top: 2px;
  font-size: 12.5px;
  font-weight: 600;
}
.avatar.user {
  background: var(--bg-soft);
  color: var(--text-2);
  border: 1px solid var(--border);
}
.avatar.assistant {
  background: linear-gradient(135deg, #1e3a8a, #274b9f 55%, #a97b2f);
  color: #fff;
  box-shadow: 0 6px 14px -7px rgba(30, 58, 138, 0.9);
}

.body {
  min-width: 0;
  max-width: min(78%, 760px);
  display: flex;
  flex-direction: column;
}
.row.user .body {
  align-items: flex-end;
}

.bubble {
  padding: 12px 16px;
  border-radius: 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
  min-width: 60px;
}
.row.assistant .bubble {
  border-top-left-radius: 5px;
}
.row.user .bubble {
  background: linear-gradient(135deg, #26428f, #1e3a8a 70%);
  border-color: transparent;
  color: #fff;
  border-top-right-radius: 5px;
  box-shadow: 0 10px 22px -14px rgba(30, 58, 138, 0.95);
}
.bubble.error {
  background: var(--danger-soft);
  border-color: #f2cdc9;
}
.bubble.error .md {
  color: #8f1d17;
}

.user-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 14.5px;
  line-height: 1.7;
}

.waiting {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 3px 0;
}
.waiting-text {
  font-size: 13px;
  color: var(--text-3);
}
.dots {
  display: inline-flex;
  gap: 4px;
}
.dots i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary);
  opacity: 0.35;
  animation: blink 1.25s infinite;
}
.dots i:nth-child(2) {
  animation-delay: 0.16s;
}
.dots i:nth-child(3) {
  animation-delay: 0.32s;
}
@keyframes blink {
  0%,
  70%,
  100% {
    opacity: 0.25;
    transform: scale(0.85);
  }
  35% {
    opacity: 1;
    transform: scale(1);
  }
}

.pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary);
  display: inline-block;
  animation: blink 1.2s infinite;
}

/* ---------- 法条依据 ---------- */
.sources {
  margin-top: 12px;
}
.sources-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 9px;
  border-radius: 7px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  font-size: 12px;
  color: var(--text-2);
  transition: background 0.15s, border-color 0.15s;
}
.sources-toggle:hover {
  background: var(--primary-soft);
  border-color: #ccd4ec;
  color: var(--primary-600);
}
.sources-toggle .count {
  min-width: 17px;
  height: 17px;
  padding: 0 4px;
  border-radius: 5px;
  background: var(--primary);
  color: #fff;
  font-size: 10.5px;
  display: grid;
  place-items: center;
  font-weight: 600;
}
.sources-toggle .hint {
  color: var(--text-3);
  font-size: 11.5px;
}

.sources-list {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.source-card {
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface-2);
  padding: 9px 11px;
  border-left: 3px solid var(--gold);
}
.source-head {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 5px;
}
.law-chip {
  font-size: 10.5px;
  font-weight: 600;
  padding: 1.5px 7px;
  border-radius: 5px;
  background: var(--gold-soft);
  color: var(--gold);
  flex: none;
}
.law-title {
  font-size: 12.2px;
  font-weight: 600;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.score {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  flex: none;
}
.score-bar {
  width: 42px;
  height: 4px;
  border-radius: 999px;
  background: #e4e2db;
  overflow: hidden;
}
.score-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #1e3a8a, #a97b2f);
}

.source-text {
  margin: 0;
  font-family: var(--font);
  font-size: 12.4px;
  line-height: 1.7;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 180px;
  overflow-y: auto;
}

/* ---------- 元信息 ---------- */
.meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  padding: 0 4px;
  min-height: 20px;
  font-size: 11px;
  color: var(--text-3);
  opacity: 0.85;
}
.row.user .meta {
  flex-direction: row-reverse;
}
.time {
  font-variant-numeric: tabular-nums;
}
.elapsed {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--text-3);
}
.generating {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--primary);
}
.meta-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 6px;
  border-radius: 6px;
  color: var(--text-3);
  font-size: 11px;
  transition: background 0.15s, color 0.15s;
}
.meta-btn:hover {
  background: var(--bg-soft);
  color: var(--text-2);
}
</style>
