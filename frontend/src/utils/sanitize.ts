import DOMPurify from 'dompurify'

/**
 * 将 LLM 生成的 Markdown-ish HTML 片段过滤为安全标签白名单。
 *
 * 基于 DOMPurify（成熟 Anti-XSS 库），替代原先的手写正则实现——
 * 正则无法可靠解析畸形标签（如 <span/style=...> 可绕过白名单）。
 *
 * 允许: br, p, strong, b, em, i, h1-h6, ul, ol, li, hr, span
 * 剥离: script, style, iframe, img, a 及全部属性（含事件属性）。
 */
const ALLOWED_TAGS = [
  'br', 'p', 'strong', 'b', 'em', 'i',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'ul', 'ol', 'li', 'hr', 'span',
]

export function sanitizeHtml(raw: string): string {
  return DOMPurify.sanitize(raw, {
    ALLOWED_TAGS,
    ALLOWED_ATTR: [],
    KEEP_CONTENT: true,
  })
}
