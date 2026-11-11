<!-- 文件路径: frontend/src/components/ConfirmDialog.vue -->
<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="confirmState.open" class="overlay" @click.self="settle(false)">
        <div class="dialog" role="dialog" aria-modal="true">
          <div class="dialog-icon" :class="{ danger: confirmState.danger }">
            <Icon :name="confirmState.danger ? 'trash' : 'alert'" :size="19" />
          </div>

          <h3>{{ confirmState.title }}</h3>
          <p class="message">{{ confirmState.message }}</p>
          <p v-if="confirmState.detail" class="detail">{{ confirmState.detail }}</p>

          <div class="dialog-actions">
            <button class="btn" @click="settle(false)">{{ confirmState.cancelText }}</button>
            <button
              class="btn"
              :class="confirmState.danger ? 'btn-danger-solid' : 'btn-primary'"
              @click="settle(true)"
            >
              {{ confirmState.confirmText }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { onBeforeUnmount, onMounted } from 'vue'

import Icon from '@/components/Icon.vue'
import { confirmState, settleConfirm } from '@/stores/confirm'

function settle(result) {
  settleConfirm(result)
}

function onKeydown(event) {
  if (!confirmState.open) return
  if (event.key === 'Escape') settle(false)
  if (event.key === 'Enter') settle(true)
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  background: rgba(17, 24, 39, 0.34);
  padding: 20px;
}
.dialog {
  width: min(400px, 100%);
  padding: 22px 22px 18px;
  border-radius: 16px;
  background: var(--surface);
  box-shadow: var(--shadow-lg);
  animation: pop 0.2s cubic-bezier(0.32, 0.72, 0, 1) both;
}
@keyframes pop {
  from {
    opacity: 0;
    transform: scale(0.96) translateY(6px);
  }
}
.dialog-icon {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  background: var(--primary-soft);
  color: var(--primary);
  margin-bottom: 14px;
}
.dialog-icon.danger {
  background: var(--danger-soft);
  color: var(--danger);
}
.dialog h3 {
  margin: 0 0 7px;
  font-size: 16px;
  font-weight: 650;
  letter-spacing: -0.2px;
}
.message {
  margin: 0;
  font-size: 13.2px;
  color: var(--text-2);
  line-height: 1.65;
}
.detail {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.6;
  padding: 8px 10px;
  background: var(--surface-2);
  border-radius: 8px;
  border: 1px solid var(--border);
}
.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}
.dialog-actions .btn {
  min-width: 84px;
}
.btn-danger-solid {
  background: var(--danger);
  color: #fff;
}
.btn-danger-solid:hover {
  background: #cf3d42;
  color: #fff;
}
</style>
