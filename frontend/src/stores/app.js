// 文件路径: frontend/src/stores/app.js
//
// 全局状态用 reactive 单例，不引 Pinia：
// 这个应用的状态边界很清楚（会话 / 对话 / 知识库 / 设置），
// 一个 reactive 对象 + 一组导出函数就够了，还少一个依赖。
import { reactive } from 'vue'

import { knowledgeApi, sessionApi, settingsApi, statuteApi, systemApi } from '@/api'
import { streamPost } from '@/api/stream'
import { toastError, toastSuccess } from '@/stores/toast'
import { formatClock } from '@/utils/time'

/* ==================== 工具函数 ==================== */
const uid = () =>
  `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`

const newSessionId = () =>
  `s_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`

const readBool = (key, fallback) => {
  const raw = localStorage.getItem(key)
  return raw === null ? fallback : raw === 'true'
}

/* ==================== 全局状态 ==================== */
export const state = reactive({
  // 视图：chat | statute | knowledge | stats
  view: 'chat',

  // 会话
  sessions: [],
  sessionsLoading: false,
  keyword: '',
  currentSessionId: '',
  messages: [],
  historyLoading: false,

  // 对话
  mode: localStorage.getItem('legal_mode') || 'agent', // agent | direct
  useReranker: readBool('legal_reranker', true),
  streaming: false,
  abortController: null,
  scrollSignal: 0,

  // 思考过程
  thinking: {
    active: false,
    stage: '',
    steps: [],
    intent: '',
    domain: '',
    startedAt: 0,
    elapsed: 0,
  },

  // 设置
  settings: null,
  models: [],
  settingsLoading: false,
  savingSettings: false,

  // 系统
  health: null,
  stats: null,

  // 知识库
  domains: [],
  documents: [],
  knowledgeLoading: false,
  uploading: false,
  uploadProgress: 0,

  // 法条检索
  statuteQuery: '',
  statuteLaw: '',
  statuteDomain: '',
  statutePage: 1,
  statuteResult: { total: 0, items: [] },
  statuteLaws: [],
  statuteLoading: false,
})

/* ==================== 会话 ==================== */
export async function loadSessions() {
  state.sessionsLoading = true
  try {
    state.sessions = await sessionApi.list(state.keyword)
  } catch (err) {
    toastError(err.message)
  } finally {
    state.sessionsLoading = false
  }
}

export function currentSession() {
  return state.sessions.find((item) => item.session_id === state.currentSessionId)
}

export function currentTitle() {
  return currentSession()?.title || '新对话'
}

export function selectSession(sessionId) {
  if (state.streaming) stopStreaming()
  state.view = 'chat'
  state.currentSessionId = sessionId
  state.messages = []
  loadMessages(sessionId)
}

export async function loadMessages(sessionId) {
  state.historyLoading = true
  try {
    const list = await sessionApi.messages(sessionId)
    // 后端把 sources 一起存了，历史消息回看也能展开法条依据
    state.messages = list.map((item) => ({
      id: `h_${item.id}`,
      role: item.role,
      content: item.content,
      sources: item.sources || [],
      elapsed_ms: item.elapsed_ms || 0,
      created_at: item.created_at,
      pending: false,
      error: false,
    }))
    bumpScroll()
  } catch (err) {
    toastError(err.message)
  } finally {
    state.historyLoading = false
  }
}

export function newSession() {
  if (state.streaming) stopStreaming()
  state.view = 'chat'
  state.currentSessionId = ''
  state.messages = []
}

export async function renameSession(sessionId, title) {
  const trimmed = (title || '').trim()
  if (!trimmed) return false
  try {
    await sessionApi.rename(sessionId, trimmed)
    const target = state.sessions.find((s) => s.session_id === sessionId)
    if (target) target.title = trimmed
    toastSuccess('标题已更新')
    return true
  } catch (err) {
    toastError(err.message)
    return false
  }
}

export async function deleteSession(sessionId) {
  try {
    await sessionApi.remove(sessionId)
    state.sessions = state.sessions.filter((s) => s.session_id !== sessionId)
    if (state.currentSessionId === sessionId) {
      state.currentSessionId = ''
      state.messages = []
    }
    toastSuccess('会话已删除')
  } catch (err) {
    toastError(err.message)
  }
}

export async function clearCurrentMessages() {
  if (!state.currentSessionId) {
    state.messages = []
    return
  }
  try {
    await sessionApi.clear(state.currentSessionId)
    state.messages = []
    await loadSessions()
    toastSuccess('聊天记录已清空')
  } catch (err) {
    toastError(err.message)
  }
}

/* ==================== 发送消息 ==================== */
function bumpScroll() {
  state.scrollSignal += 1
}

export async function sendMessage(text) {
  const query = (text || '').trim()
  if (!query || state.streaming) return

  if (!state.currentSessionId) {
    state.currentSessionId = newSessionId()
  }

  state.messages.push({
    id: uid(),
    role: 'user',
    content: query,
    sources: [],
    created_at: formatClock(new Date()),
    pending: false,
    error: false,
  })

  const assistant = reactive({
    id: uid(),
    role: 'assistant',
    content: '',
    sources: [],
    created_at: formatClock(new Date()),
    pending: true,
    error: false,
    elapsed_ms: null,
  })
  state.messages.push(assistant)
  bumpScroll()

  state.streaming = true
  state.thinking = {
    active: true,
    stage: '正在连接…',
    steps: [],
    intent: '',
    domain: '',
    startedAt: Date.now(),
    elapsed: 0,
  }

  const controller = new AbortController()
  state.abortController = controller

  const payload = {
    session_id: state.currentSessionId,
    query,
    use_rerank: state.useReranker,
  }

  const path = state.mode === 'direct' ? '/chat/direct/stream' : '/chat/stream'

  try {
    await streamPost(
      path,
      payload,
      {
        onEvent(event) {
          switch (event.type) {
            case 'status':
              state.thinking.stage = event.message || ''
              if (event.message) state.thinking.steps.push(event.message)
              if (event.intent) state.thinking.intent = event.intent
              if (event.domain) state.thinking.domain = event.domain
              break
            case 'sources':
              // 检索完先把法条依据推给前端，用户不用等生成完才知道查到了什么
              assistant.sources = event.sources || []
              bumpScroll()
              break
            case 'delta':
              assistant.content += event.text || ''
              bumpScroll()
              break
            case 'answer':
              assistant.content = event.answer || assistant.content
              if (event.sources?.length) assistant.sources = event.sources
              assistant.elapsed_ms = event.elapsed_ms || null
              assistant.pending = false
              state.thinking.active = false
              bumpScroll()
              break
            case 'error':
              assistant.error = true
              assistant.content = event.message || '未知错误'
              assistant.pending = false
              toastError(event.message || '生成失败')
              break
            default:
              break
          }
        },
      },
      controller.signal
    )
  } catch (err) {
    if (err.name === 'AbortError') {
      assistant.content += assistant.content
        ? '\n\n_（已停止生成）_'
        : '_（已停止生成）_'
    } else {
      assistant.error = true
      assistant.content = err.message
      toastError(err.message)
    }
  } finally {
    assistant.pending = false
    state.streaming = false
    state.thinking.active = false
    state.abortController = null
    bumpScroll()
    await loadSessions()
  }
}

export function stopStreaming() {
  state.abortController?.abort()
  state.abortController = null
}

export function regenerate(lastUserText) {
  if (state.streaming) return
  // 不做"删掉上一条再重发"：那样本地界面和数据库会对不上，刷新后历史就变了。
  // 直接把同一个问题再问一遍，前后端始终一致。
  sendMessage(lastUserText)
}

/* ==================== 设置 ==================== */
export async function loadSettings(force = false) {
  if (state.settings && !force) return
  state.settingsLoading = true
  try {
    const [settings, models] = await Promise.all([
      settingsApi.get(),
      state.models.length ? Promise.resolve(state.models) : settingsApi.models(),
    ])
    state.settings = settings
    state.models = models
  } catch (err) {
    toastError(err.message)
  } finally {
    state.settingsLoading = false
  }
}

export async function saveSettings(payload) {
  state.savingSettings = true
  try {
    const result = await settingsApi.save(payload)
    state.settings = result.settings
    state.useReranker = result.settings.use_rerank
    localStorage.setItem('legal_reranker', String(state.useReranker))
    toastSuccess(result.message || '设置已保存')
    await loadHealth()
    return true
  } catch (err) {
    toastError(err.message)
    return false
  } finally {
    state.savingSettings = false
  }
}

export async function testConnection(payload) {
  return await settingsApi.test(payload)
}

/* ==================== 知识库 ==================== */
export async function loadKnowledge() {
  state.knowledgeLoading = true
  try {
    const [domains, documents] = await Promise.all([
      knowledgeApi.domains(),
      knowledgeApi.documents(),
    ])
    state.domains = domains
    state.documents = documents
  } catch (err) {
    toastError(err.message)
  } finally {
    state.knowledgeLoading = false
  }
}

export async function uploadDocument(file) {
  if (!file) return
  state.uploading = true
  state.uploadProgress = 0
  try {
    const result = await knowledgeApi.upload(file, (percent) => {
      state.uploadProgress = percent
    })
    toastSuccess(`已上传并切分为 ${result.chunks} 条可检索片段`)
    await Promise.all([loadKnowledge(), loadStats()])
  } catch (err) {
    toastError(err.message)
  } finally {
    state.uploading = false
    state.uploadProgress = 0
  }
}

export async function removeDocument(filename) {
  try {
    await knowledgeApi.remove(filename)
    toastSuccess('文档已删除')
    await Promise.all([loadKnowledge(), loadStats()])
  } catch (err) {
    toastError(err.message)
  }
}

export async function rebuildKnowledge(payload) {
  state.knowledgeLoading = true
  try {
    const result = await knowledgeApi.rebuild(payload)
    toastSuccess(result.message)
    await Promise.all([loadKnowledge(), loadStats()])
  } catch (err) {
    toastError(err.message)
  } finally {
    state.knowledgeLoading = false
  }
}

/* ==================== 法条检索 ==================== */
export async function loadStatutes(reset = false) {
  if (reset) state.statutePage = 1
  state.statuteLoading = true
  try {
    state.statuteResult = await statuteApi.search({
      keyword: state.statuteQuery,
      law_name: state.statuteLaw,
      domain: state.statuteDomain,
      page: state.statutePage,
      page_size: 15,
    })
  } catch (err) {
    toastError(err.message)
  } finally {
    state.statuteLoading = false
  }
}

export async function loadStatuteLaws() {
  if (state.statuteLaws.length) return
  try {
    state.statuteLaws = await statuteApi.laws()
  } catch {
    state.statuteLaws = []
  }
}

export function changeStatutePage(delta) {
  const next = state.statutePage + delta
  const max = Math.max(1, Math.ceil(state.statuteResult.total / 15))
  if (next < 1 || next > max) return
  state.statutePage = next
  loadStatutes()
}

/* ==================== 系统 ==================== */
export async function loadHealth() {
  try {
    state.health = await systemApi.health()
  } catch {
    state.health = { status: 'offline' }
  }
}

export async function loadStats() {
  try {
    state.stats = await systemApi.stats()
    if (state.stats.domains?.length) state.domains = state.stats.domains
  } catch (err) {
    toastError(err.message)
  }
}

/* ==================== 视图切换 ==================== */
export async function switchView(view) {
  state.view = view
  if (view === 'knowledge') await loadKnowledge()
  if (view === 'stats') {
    // 概览页要显示当前模型和精排开关状态，settings 没加载过就先拉一次
    await Promise.all([loadStats(), state.settings ? Promise.resolve() : loadSettings()])
  }
  if (view === 'settings') await loadSettings()   // 设置页每次进来都拉最新配置
  if (view === 'statute') {
    // 法条检索页的"领域"下拉依赖 domains，直接从知识库接口取；
    // 首次进入时如果知识库还没加载过，这里顺手带上，避免下拉框是空的
    await Promise.all([
      loadStatuteLaws(),
      state.domains.length ? Promise.resolve() : loadKnowledge(),
    ])
    if (!state.statuteResult.items.length) await loadStatutes(true)
  }
}

/* ==================== 导出对话 ==================== */
export function exportCurrentSession() {
  if (!state.messages.length) {
    toastError('当前会话还没有任何消息')
    return
  }
  const title = currentTitle()
  const lines = [
    `# ${title}`,
    '',
    `> 导出时间：${new Date().toLocaleString('zh-CN')}`,
    '',
  ]
  state.messages.forEach((msg) => {
    lines.push(
      `## ${msg.role === 'user' ? '咨询人' : '法律助手'}  ${msg.created_at || ''}`
    )
    lines.push('')
    lines.push(msg.content || '')
    if (msg.sources?.length) {
      lines.push('')
      lines.push('<details><summary>参考法条</summary>')
      lines.push('')
      msg.sources.forEach((src) => {
        const score = src.score != null ? `（相关度 ${src.score}）` : ''
        lines.push(`- **${src.title || '资料'}** ${score}`)
        lines.push(`  ${src.text}`)
      })
      lines.push('')
      lines.push('</details>')
    }
    lines.push('')
    lines.push('---')
    lines.push('')
  })

  const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${title.replace(/[\\/:*?"<>|]/g, '_')}.md`
  a.click()
  URL.revokeObjectURL(url)
  toastSuccess('已导出为 Markdown')
}

/* ==================== 初始化 ==================== */
export async function bootstrap() {
  await Promise.all([loadSessions(), loadHealth(), loadSettings(), loadStats()])
  if (state.sessions.length) {
    selectSession(state.sessions[0].session_id)
  }
}
