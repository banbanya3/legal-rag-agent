// 文件路径: frontend/src/api/stream.js
import { API_BASE } from './http'

/**
 * SSE 流式请求（专门给 /chat/stream 用）
 *
 * 为什么不用 axios？—— 浏览器里的 axios 基于 XHR，拿不到"边下边读"的增量数据，
 * 只有 fetch + ReadableStream 才能真正一帧一帧读 SSE。这也是业界标准做法。
 *
 * @param {string} path    相对路径，如 '/chat/stream'
 * @param {object} body    请求体
 * @param {object} handlers { onEvent(payload), onError(err), onDone() }
 * @param {AbortSignal} signal 用于"停止生成"
 */
export async function streamPost(path, body, handlers = {}, signal) {
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (err) {
    if (err.name === 'AbortError') throw err
    throw new Error('无法连接后端，请确认 FastAPI 已启动（127.0.0.1:5000）')
  }

  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`
    try {
      const data = await response.json()
      if (typeof data.message === 'string') detail = data.message
      else if (typeof data.detail === 'string') detail = data.detail
    } catch {
      /* 响应体不是 JSON 就保留默认文案 */
    }
    throw new Error(detail)
  }

  if (!response.body) {
    throw new Error('当前浏览器不支持流式响应，请更换 Chrome / Edge')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      // 统一换行符，避免 Windows 下的 \r\n 让分帧解析错位
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')

      let index
      while ((index = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, index)
        buffer = buffer.slice(index + 2)

        const dataLine = frame
          .split('\n')
          .find((line) => line.startsWith('data:'))
        if (!dataLine) continue

        const json = dataLine.slice(5).trim()
        if (!json) continue

        try {
          handlers.onEvent?.(JSON.parse(json))
        } catch (err) {
          console.warn('[SSE] 无法解析的数据帧:', json, err)
        }
      }
    }
  } finally {
    reader.releaseLock?.()
  }

  handlers.onDone?.()
}
