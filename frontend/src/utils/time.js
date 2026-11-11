// 文件路径: frontend/src/utils/time.js

/** 后端返回的是 "2026-10-17 15:50" 这种本地时间字符串，Safari 不认带空格的格式，先补个 T */
function parseDate(value) {
  if (!value) return null
  if (value instanceof Date) return value
  const normalized = String(value).replace(' ', 'T')
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatClock(value) {
  const date = parseDate(value)
  if (!date) return ''
  return `${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes()
  ).padStart(2, '0')}`
}

export function formatDate(value) {
  const date = parseDate(value)
  if (!date) return ''
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(
    date.getDate()
  ).padStart(2, '0')}`
}

const DAY = 86400000

function startOfDay(date) {
  const copy = new Date(date)
  copy.setHours(0, 0, 0, 0)
  return copy
}

/** 按"今天 / 昨天 / 近 7 天 / 更早"把会话分组，渲染成带小标题的列表 */
export function groupSessions(sessions) {
  const today = startOfDay(new Date())
  const groups = [
    { key: 'today', label: '今天', items: [] },
    { key: 'yesterday', label: '昨天', items: [] },
    { key: 'week', label: '近 7 天', items: [] },
    { key: 'older', label: '更早', items: [] },
  ]

  sessions.forEach((session) => {
    const date = parseDate(session.last_message_at || session.created_at)
    if (!date) {
      groups[3].items.push(session)
      return
    }
    const diff = Math.floor((today - startOfDay(date)) / DAY)
    if (diff <= 0) groups[0].items.push(session)
    else if (diff === 1) groups[1].items.push(session)
    else if (diff <= 6) groups[2].items.push(session)
    else groups[3].items.push(session)
  })

  return groups.filter((group) => group.items.length > 0)
}

/** 毫秒 -> "1.2s" / "42s" */
export function formatDuration(ms) {
  if (!ms && ms !== 0) return ''
  if (ms < 1000) return `${ms}ms`
  const seconds = ms / 1000
  if (seconds < 10) return `${seconds.toFixed(1)}s`
  return `${Math.round(seconds)}s`
}

/** 会话列表用的短时间：今天显示 HH:mm，昨天显示"昨天 HH:mm"，更早显示 M/D */
export function shortStamp(value) {
  const date = parseDate(value)
  if (!date) return ''
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  const diff = Math.round((startOfDay(new Date()) - startOfDay(date)) / DAY)
  if (diff <= 0) return `${hh}:${mm}`
  if (diff === 1) return `昨天 ${hh}:${mm}`
  return `${date.getMonth() + 1}/${date.getDate()}`
}
