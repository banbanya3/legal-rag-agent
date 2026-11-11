<!-- 文件路径: frontend/src/components/ChatComposer.vue -->
<template>
  <div class="composer-wrap">
    <div class="composer" :class="{ focused, busy: state.streaming }">
      <textarea
        ref="textareaRef"
        v-model="text"
        class="composer-input"
        :placeholder="placeholder"
        rows="1"
        @focus="focused = true"
        @blur="focused = false"
        @keydown="onKeydown"
        @input="autoResize"
      />

      <div class="composer-bar">
        <div class="bar-left">
          <span class="mode-chip" :class="state.mode">
            <Icon :name="state.mode === 'agent' ? 'scale' : 'zap'" :size="12" :stroke-width="2" />
            {{ state.mode === 'agent' ? '法律检索' : '直聊模式' }}
          </span>
          <span class="bar-hint">
            {{ state.mode === 'agent' ? '先查法条再回答，附出处' : '跳过检索，响应更快' }}
          </span>
        </div>

        <div class="bar-right">
          <span class="counter" :class="{ over: text.length > MAX }">
            {{ text.length }}/{{ MAX }}
          </span>
          <span class="key-hint">Enter 发送 · Shift+Enter 换行</span>

          <button
            v-if="state.streaming"
            class="send-btn stop"
            title="停止生成"
            @click="stop"
          >
            <Icon name="stop" :size="15" />
          </button>
          <button
            v-else
            class="send-btn"
            :disabled="!canSend"
            title="发送"
            @click="submit"
          >
            <Icon name="send" :size="15" :stroke-width="2" />
          </button>
        </div>
      </div>
    </div>

    <div class="disclaimer">
      回答基于已收录法条生成，仅供参考，不构成正式法律意见 · 涉及重大权益请咨询执业律师
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'

import Icon from '@/components/Icon.vue'
import { sendMessage, state, stopStreaming } from '@/stores/app'

const MAX = 4000
const text = ref('')
const focused = ref(false)
const textareaRef = ref(null)

const canSend = computed(
  () => text.value.trim().length > 0 && text.value.length <= MAX
)

const placeholder = computed(() =>
  state.mode === 'agent'
    ? '描述你遇到的情况，或直接问某部法律的第几条…'
    : '直接和模型对话，比如：帮我解释一个法律概念'
)

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 190)}px`
}

function onKeydown(event) {
  // 输入法组合输入期间按回车是在选词，不能当成发送
  if (event.isComposing) return
  if (event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.altKey) {
    event.preventDefault()
    submit()
  }
}

async function submit() {
  if (!canSend.value || state.streaming) return
  const content = text.value.trim()
  text.value = ''
  await nextTick()
  autoResize()
  sendMessage(content)
}

function stop() {
  stopStreaming()
}

/** 供父组件（建议卡）把一句话塞进来并直接发送 */
function sendExternal(content) {
  if (state.streaming) return
  sendMessage(content)
}

defineExpose({ sendExternal, focus: () => textareaRef.value?.focus() })

onMounted(() => {
  autoResize()
  textareaRef.value?.focus()
})
</script>

<style scoped>
.composer-wrap {
  padding: 0 28px 14px;
  background: linear-gradient(to bottom, rgba(244, 245, 249, 0), var(--bg) 42%);
}
.composer {
  max-width: 880px;
  margin: 0 auto;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface);
  box-shadow: 0 1px 2px rgba(17, 24, 39, 0.04);
  transition: border-color 0.18s, box-shadow 0.18s;
  padding: 10px 12px 8px;
}
.composer.focused {
  border-color: #c7cbf0;
  box-shadow: 0 0 0 4px rgba(79, 70, 229, 0.07),
    0 10px 26px -18px rgba(17, 24, 39, 0.4);
}
.composer.busy {
  border-color: #d9dcf3;
}

.composer-input {
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  background: none;
  font-size: 14.2px;
  line-height: 1.65;
  padding: 4px 4px 6px;
  max-height: 190px;
  overflow-y: auto;
  font-family: var(--font);
}
.composer-input::placeholder {
  color: var(--text-3);
}

.composer-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 2px;
}
.bar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  overflow: hidden;
}
.mode-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 8px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 600;
  background: var(--primary-soft);
  color: var(--primary-600);
  flex: none;
}
.mode-chip.direct {
  background: #e8f4fe;
  color: #0369a1;
}
.bar-hint {
  font-size: 11.5px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bar-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
  flex: none;
}
.counter {
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.counter.over {
  color: var(--danger);
  font-weight: 600;
}
.key-hint {
  font-size: 11px;
  color: var(--text-3);
  opacity: 0.8;
}

.send-btn {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: var(--primary);
  color: #fff;
  transition: background 0.16s, transform 0.1s, opacity 0.16s;
  box-shadow: 0 6px 14px -8px rgba(79, 70, 229, 0.95);
}
.send-btn:hover:not(:disabled) {
  background: var(--primary-600);
}
.send-btn:active:not(:disabled) {
  transform: scale(0.96);
}
.send-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
  box-shadow: none;
}
.send-btn.stop {
  background: var(--danger);
  box-shadow: 0 6px 14px -8px rgba(229, 72, 77, 0.9);
}
.send-btn.stop:hover {
  background: #cf3d42;
}

.disclaimer {
  max-width: 880px;
  margin: 7px auto 0;
  text-align: center;
  font-size: 11px;
  color: var(--text-3);
  opacity: 0.85;
}

@media (max-width: 760px) {
  .composer-wrap {
    padding: 0 12px 10px;
  }
  .bar-hint,
  .key-hint {
    display: none;
  }
}
</style>
