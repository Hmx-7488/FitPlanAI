/**
 * 本地日期工具。
 *
 * 业务日期一律使用用户本地时区，禁止使用 toISOString()（它会转成 UTC，
 * 导致北京时间 0:00-8:00 的记录被归到"昨天"）。
 */

/** 返回本地日期字符串 YYYY-MM-DD */
export function localDateStr(d: Date = new Date()): string {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
