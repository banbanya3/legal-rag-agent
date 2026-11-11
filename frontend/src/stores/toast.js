// 文件路径: frontend/src/stores/toast.js
import { ref } from 'vue'

export const toasts = ref([])
let seq = 0

/**
 * 轻提示。type: info | success | error | warn
 */
export function toast(message, type = 'info', duration = 3200) {
  const id = ++seq
  toasts.value.push({ id, message, type })
  window.setTimeout(() => dismiss(id), duration)
  return id
}

export function dismiss(id) {
  toasts.value = toasts.value.filter((item) => item.id !== id)
}

export const toastSuccess = (msg) => toast(msg, 'success')
export const toastError = (msg) => toast(msg, 'error', 5000)
