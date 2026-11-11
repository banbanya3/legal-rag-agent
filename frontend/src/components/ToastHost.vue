<!-- 文件路径: frontend/src/components/ToastHost.vue -->
<template>
  <Teleport to="body">
    <div class="toast-stack">
      <TransitionGroup name="toast">
        <div
          v-for="item in toasts"
          :key="item.id"
          class="toast"
          :class="item.type"
          @click="dismissToast(item.id)"
        >
          <span class="toast-icon">
            <Icon :name="iconOf(item.type)" :size="15" :stroke-width="2" />
          </span>
          <span class="toast-text">{{ item.message }}</span>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import Icon from '@/components/Icon.vue'
import { dismiss as dismissToast, toasts } from '@/stores/toast'

function iconOf(type) {
  if (type === 'success') return 'check'
  if (type === 'error') return 'alert'
  if (type === 'warn') return 'alert'
  return 'message'
}
</script>

<style scoped>
.toast-stack {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 90;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}
.toast {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  max-width: 360px;
  padding: 10px 14px 10px 11px;
  border-radius: 11px;
  background: #1f2330;
  color: #f3f4f8;
  font-size: 12.8px;
  line-height: 1.55;
  box-shadow: 0 18px 40px -18px rgba(15, 20, 35, 0.7);
  pointer-events: auto;
  cursor: pointer;
}
.toast-icon {
  width: 20px;
  height: 20px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  flex: none;
  margin-top: 1px;
  background: rgba(255, 255, 255, 0.12);
}
.toast.success .toast-icon {
  background: rgba(16, 185, 129, 0.28);
  color: #6ee7b7;
}
.toast.error .toast-icon {
  background: rgba(239, 68, 68, 0.28);
  color: #fca5a5;
}
.toast.warn .toast-icon {
  background: rgba(245, 158, 11, 0.28);
  color: #fcd34d;
}
.toast-text {
  word-break: break-word;
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.24s, transform 0.24s;
}
.toast-enter-from {
  opacity: 0;
  transform: translateY(8px) scale(0.97);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(16px);
}
</style>
