// 文件路径: frontend/src/api/index.js
//
// 后端统一返回 { code, message, data }，http 拦截器已经解包成 data，
// 所以每个方法拿到的就是业务数据本身，组件里不用再 .data.data。
import http from './http'

/* ==================== 会话管理 ==================== */
export const sessionApi = {
  list: (keyword = '') => http.get('/sessions', { params: { keyword } }),
  messages: (sessionId) => http.get(`/sessions/${sessionId}/messages`),
  rename: (sessionId, title) => http.patch(`/sessions/${sessionId}`, { title }),
  remove: (sessionId) => http.delete(`/sessions/${sessionId}`),
  clear: (sessionId) => http.delete(`/sessions/${sessionId}/messages`),
  create: () => http.post('/sessions'),
}

/* ==================== 对话 ==================== */
export const chatApi = {
  /** 非流式（一次性返回完整答案 + 法条来源） */
  send: (payload) => http.post('/chat', payload),
}

/* ==================== 法条检索 ==================== */
export const statuteApi = {
  /** 分页检索，支持关键词 / 法律名 / 领域过滤 */
  search: (params) => http.get('/statutes', { params }),
  /** 已收录的法律清单 */
  laws: (domain = '') => http.get('/statutes/laws', { params: { domain } }),
  /** 法条库总览 */
  overview: () => http.get('/statutes/overview'),
}

/* ==================== 系统设置 ==================== */
export const settingsApi = {
  get: () => http.get('/settings'),
  save: (payload) => http.post('/settings', payload),
  test: (payload) => http.post('/settings/test', payload),
  models: () => http.get('/models'),
}

/* ==================== 知识库 ==================== */
export const knowledgeApi = {
  /** 六大法律领域的文档数 / 切片数 / 法条数 */
  domains: () => http.get('/knowledge/domains'),
  /** 用户上传的文档 */
  documents: () => http.get('/knowledge/documents'),
  rebuild: (payload) => http.post('/knowledge/rebuild', payload, { timeout: 600000 }),
  remove: (filename) =>
    http.delete(`/knowledge/documents/${encodeURIComponent(filename)}`, {
      timeout: 600000,
    }),
  upload: (file, onProgress) => {
    const form = new FormData()
    form.append('file', file)
    return http.post('/knowledge/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
      onUploadProgress: (event) => {
        if (onProgress && event.total) {
          onProgress(Math.round((event.loaded / event.total) * 100))
        }
      },
    })
  },
}

/* ==================== 系统 / 统计 ==================== */
export const systemApi = {
  health: () => http.get('/health'),
  stats: () => http.get('/stats'),
}
