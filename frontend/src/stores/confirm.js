// 文件路径: frontend/src/stores/confirm.js
import { reactive } from 'vue'

export const confirmState = reactive({
  open: false,
  title: '',
  message: '',
  detail: '',
  confirmText: '确定',
  cancelText: '取消',
  danger: true,
  resolve: null,
})

/**
 * 通用二次确认弹窗（Promise 版）
 * 用法：if (await askConfirm({ title: '删除会话', message: '...' })) { ... }
 */
export function askConfirm(options = {}) {
  confirmState.open = true
  confirmState.title = options.title || '请确认'
  confirmState.message = options.message || ''
  confirmState.detail = options.detail || ''
  confirmState.confirmText = options.confirmText || '确定'
  confirmState.cancelText = options.cancelText || '取消'
  confirmState.danger = options.danger !== false

  return new Promise((resolve) => {
    confirmState.resolve = resolve
  })
}

export function settleConfirm(result) {
  confirmState.open = false
  confirmState.resolve?.(result)
  confirmState.resolve = null
}
