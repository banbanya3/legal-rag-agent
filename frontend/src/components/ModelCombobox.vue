<!-- 文件路径: frontend/src/components/ModelCombobox.vue -->
<template>
  <div ref="rootRef" class="combo">
    <input
      class="combo-input"
      :value="modelValue"
      :placeholder="placeholder"
      autocomplete="off"
      @input="onInput"
      @focus="onFocus"
      @keydown.down.prevent="move(1)"
      @keydown.up.prevent="move(-1)"
      @keydown.enter.prevent="confirmActive"
      @keydown.esc="close"
    />

    <button
      type="button"
      class="combo-arrow"
      :class="{ open }"
      :aria-expanded="open"
      @click="toggle"
    >
      <Icon name="chevron" :size="16" />
    </button>

    <Transition name="combo">
      <div v-if="open" class="combo-menu">
        <button
          v-for="(item, index) in visible"
          :key="item.name"
          type="button"
          class="combo-item"
          :class="{ active: index === activeIndex, selected: item.name === modelValue }"
          @mouseenter="activeIndex = index"
          @click="pick(item)"
        >
          <span class="item-main">
            <span class="item-name">{{ item.name }}</span>
            <span class="item-label">{{ item.label }}</span>
          </span>
          <span v-if="item.name === modelValue" class="item-check">当前</span>
        </button>

        <p v-if="!visible.length" class="combo-empty">
          没有匹配的模型，可以直接输入自定义名称
        </p>

        <p v-else class="combo-tip">
          共 {{ visible.length }} 个可选，也可以直接输入自定义模型名
        </p>
      </div>
    </Transition>
  </div>
</template>

<script setup>
/**
 * 模型选择下拉。
 *
 * 为什么不用原生 <datalist>：
 *
 *   最初用的是 <input list="xxx"> + <datalist>，结果出现一个很烦的问题 ——
 *   输入框里已经有值时（比如"glm-4-flash"），点箭头只会显示这一个选项，
 *   因为浏览器的 datalist 会拿输入内容去过滤候选。用户想换模型，
 *   必须先把输入框清空才看得到其他选项。
 *
 *   而且 datalist 的浮层样式完全由浏览器控制，和页面的暖色调设计不搭。
 *
 * 这个组件的规则很明确：
 *   - 点箭头 / 聚焦 → **显示全部**（filtering = false）
 *   - 手动输入      → 按输入内容过滤（filtering = true）
 *
 *   这样"想换模型"和"想搜模型"两种意图就分开了。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import Icon from '@/components/Icon.vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue'])

const rootRef = ref(null)
const open = ref(false)
const filtering = ref(false)   // 当前是否处于"按输入过滤"模式
const activeIndex = ref(0)

const visible = computed(() => {
  // 关键：只有手动输入时才过滤。点箭头进来时 filtering 是 false，显示全部。
  if (!filtering.value) return props.options

  const keyword = (props.modelValue || '').trim().toLowerCase()
  if (!keyword) return props.options

  return props.options.filter(
    (item) =>
      item.name.toLowerCase().includes(keyword) ||
      (item.label || '').toLowerCase().includes(keyword)
  )
})

watch(visible, (list) => {
  // 列表变化后把高亮项收回有效范围，避免上下键越界
  if (activeIndex.value >= list.length) activeIndex.value = 0
})

function onInput(event) {
  emit('update:modelValue', event.target.value)
  filtering.value = true
  open.value = true
  activeIndex.value = 0
}

function onFocus() {
  // 聚焦不算"主动搜索"，展示全部，方便一眼看到所有可选模型
  if (!open.value) {
    filtering.value = false
    activeIndex.value = 0
    open.value = true
  }
}

function toggle() {
  if (open.value) {
    open.value = false
    return
  }
  // 点箭头：一定显示全部，不受输入框内容影响 —— 这是修掉的那个 bug
  filtering.value = false
  activeIndex.value = 0
  open.value = true
}

function close() {
  open.value = false
  filtering.value = false
}

function pick(item) {
  emit('update:modelValue', item.name)
  close()
}

function move(step) {
  if (!open.value) {
    filtering.value = false
    open.value = true
    return
  }
  const total = visible.value.length
  if (!total) return
  activeIndex.value = (activeIndex.value + step + total) % total
}

function confirmActive() {
  if (!open.value) return
  const item = visible.value[activeIndex.value]
  if (item) pick(item)
}

function onClickOutside(event) {
  if (rootRef.value && !rootRef.value.contains(event.target)) close()
}

onMounted(() => document.addEventListener('mousedown', onClickOutside))
onBeforeUnmount(() => document.removeEventListener('mousedown', onClickOutside))
</script>

<style scoped>
.combo {
  position: relative;
}

.combo-input {
  width: 100%;
  height: 38px;
  padding: 0 38px 0 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  font-family: var(--mono);
  transition: border-color 0.16s, box-shadow 0.16s;
}
.combo-input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.combo-arrow {
  position: absolute;
  top: 1px;
  right: 1px;
  width: 34px;
  height: 36px;
  display: grid;
  place-items: center;
  border: none;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.combo-arrow:hover {
  color: var(--text);
  background: var(--surface-2);
}
.combo-arrow.open Icon {
  transform: rotate(180deg);
}
.combo-arrow :deep(svg) {
  transition: transform 0.16s;
}

.combo-menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  z-index: 20;
  max-height: 268px;
  overflow-y: auto;
  padding: 5px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-lg);
}

.combo-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.combo-item.active {
  background: var(--surface-2);
}
.combo-item.selected .item-name {
  color: var(--accent);
  font-weight: 600;
}

.item-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.item-name {
  font-family: var(--mono);
  font-size: 12.5px;
  color: var(--text);
}
.item-label {
  font-size: 11.5px;
  color: var(--text-3);
}
.item-check {
  flex: none;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 10.5px;
}

.combo-empty,
.combo-tip {
  margin: 0;
  padding: 8px 10px 6px;
  font-size: 11.3px;
  color: var(--text-3);
}
.combo-empty {
  text-align: center;
  padding: 16px 10px;
}

.combo-enter-active,
.combo-leave-active {
  transition: opacity 0.14s ease, transform 0.14s ease;
}
.combo-enter-from,
.combo-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
