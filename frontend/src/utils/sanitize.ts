/**
 * 将 Markdown-ish HTML 片段过滤为安全标签白名单。
 *
 * 允许: br, p, strong, b, em, i, h1-h6, ul, ol, li, hr, span
 * 剥离: script, style, iframe, img, a, 以及所有事件属性。
 * 用于 v-html 渲染 LLM 生成的内容。
 */
const SAFE_TAGS = new Set([
  'br', 'p', 'strong', 'b', 'em', 'i',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'ul', 'ol', 'li', 'hr', 'span',
])

const EVENT_ATTR_RE = /\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi
const TAG_RE = /<\/?([a-z][a-z0-9]*)(?:\s[^>]*)?\/?>/gi

export function sanitizeHtml(raw: string): string {
  // 先移除所有事件属性（防嵌套绕过）
  let safe = raw.replace(EVENT_ATTR_RE, '')

  const tokens: string[] = []
  let last = 0
  let m: RegExpExecArray | null

  while ((m = TAG_RE.exec(safe)) !== null) {
    if (m.index > last) {
      tokens.push(safe.slice(last, m.index))
    }
    const tagName = m[1].toLowerCase()
    if (SAFE_TAGS.has(tagName)) {
      // 二次清理标签内残余事件属性
      tokens.push(m[0].replace(EVENT_ATTR_RE, ''))
    }
    // 非白名单标签不加入 tokens（被剥离）
    last = m.index + m[0].length
  }

  if (last < safe.length) {
    tokens.push(safe.slice(last))
  }

  return tokens.join('')
}