// 文件路径: frontend/src/api/http.js
import axios from 'axios'

/**
 * 后端基地址。
 * 开发环境走 Vite 代理（/api -> http://127.0.0.1:5000），所以这里用相对路径，
 * 既没有 CORS 预检，代码里也不会出现硬编码 IP。
 * 要直连后端时，在 .env.local 里设 VITE_API_BASE=http://127.0.0.1:5000/api
 */
export const API_BASE = import.meta.env.VITE_API_BASE || '/api'

const http = axios.create({
  baseURL: API_BASE,
  // 法律问答要跑「路由 + 检索 + 生成」三段，给足超时
  timeout: 180000,
  headers: { 'Content-Type': 'application/json' },
})

http.interceptors.request.use((config) => {
  config.metadata = { start: Date.now() }
  return config
})

/**
 * 响应拦截器做两件事：
 * 1. 把 { code, message, data } 拆包，业务代码只拿 data；
 * 2. 把各种错误压平成一句人话，组件里 err.message 直接能弹提示。
 */
http.interceptors.response.use(
  (response) => {
    const body = response.data
    // 非标准结构（比如导出文件）直接放行
    if (!body || typeof body !== 'object' || !('code' in body)) return body

    if (body.code !== 0) {
      const err = new Error(body.message || '请求失败')
      err.code = body.code
      return Promise.reject(err)
    }
    return body.data
  },
  (error) => {
    let message = '网络异常，请确认 FastAPI 后端已启动（127.0.0.1:5000）'
    const status = error?.response?.status

    if (error?.response) {
      const body = error.response.data
      if (typeof body?.message === 'string') {
        message = body.message
      } else if (typeof body?.detail === 'string') {
        message = body.detail
      } else {
        message = `请求失败（HTTP ${status}）`
      }
    } else if (error?.code === 'ECONNABORTED') {
      message = '请求超时：推理时间过长，请稍后重试或换更快的模型'
    }

    const normalized = new Error(message)
    normalized.status = status
    normalized.raw = error
    return Promise.reject(normalized)
  }
)

export default http
