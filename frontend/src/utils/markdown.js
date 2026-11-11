// 文件路径: frontend/src/utils/markdown.js
import DOMPurify from 'dompurify'
import { marked } from 'marked'

// GFM 支持表格 / 任务列表；breaks 让单个换行也渲染成 <br>，更符合聊天场景的直觉
marked.use({
  gfm: true,
  breaks: true,
})

/**
 * 把 Markdown 文本渲染成安全 HTML。
 * 大模型的输出属于"不可信内容"，必须过一遍 DOMPurify，
 * 否则一旦模型吐出 <img onerror=...> 这种字符串，就是现成的 XSS 漏洞。
 */
export function renderMarkdown(text) {
  if (!text) return ''
  try {
    const html = marked.parse(String(text))
    return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } })
  } catch (err) {
    console.warn('[markdown] 渲染失败，降级为纯文本', err)
    return DOMPurify.sanitize(
      String(text).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' })[c])
    )
  }
}
