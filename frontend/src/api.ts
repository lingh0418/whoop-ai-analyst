/* eslint-disable @typescript-eslint/no-explicit-any */
export type Json = any

async function request<T = Json>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    const msg = data?.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : res.statusText
    throw new Error(msg)
  }
  return data as T
}

export const api = {
  get: <T = Json>(path: string) => request<T>('GET', path),
  post: <T = Json>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T = Json>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
  del: <T = Json>(path: string) => request<T>('DELETE', path),
}

// ---------------------------------------------------------------- 格式化

export function fmtMinutes(min?: number | null): string {
  if (min === null || min === undefined || Number.isNaN(min)) return '—'
  const sign = min < 0 ? '-' : ''
  const total = Math.round(Math.abs(min))
  const h = Math.floor(total / 60)
  const m = total % 60
  return h ? `${sign}${h}h ${String(m).padStart(2, '0')}m` : `${sign}${m}m`
}

export function fmtPct(x?: number | null, digits = 1, signed = true): string {
  if (x === null || x === undefined || Number.isNaN(x)) return '—'
  const v = x * 100
  return `${signed && v > 0 ? '+' : ''}${v.toFixed(digits)}%`
}

export function fmtNum(x?: number | null, digits = 1): string {
  if (x === null || x === undefined || Number.isNaN(x)) return '—'
  return x.toFixed(digits)
}

export function fmtBedtime(hoursSinceNoon?: number | null): string {
  if (hoursSinceNoon === null || hoursSinceNoon === undefined) return '—'
  const h = (12 + hoursSinceNoon) % 24
  const hh = Math.floor(h)
  const mm = Math.round((h - hh) * 60) % 60
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
}

export function fmtMetric(metric: string, v?: number | null, unit = ''): string {
  if (v === null || v === undefined) return '—'
  if (['sleep_duration', 'deep_sleep', 'rem_sleep', 'sleep_debt', 'sleep_need', 'workout_minutes', 'awake_time'].includes(metric)) return fmtMinutes(v)
  if (metric === 'bedtime') return fmtBedtime(v)
  if (unit === '%') return `${Math.round(v)}%`
  const digits = ['rhr', 'recovery'].includes(metric) ? 0 : metric === 'skin_temp' ? 2 : 1
  return `${v.toFixed(digits)}${unit ? ' ' + unit : ''}`
}

export const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export const CONFIDENCE_LABEL: Record<string, string> = { high: '高', medium: '中', low: '低' }
export const SEVERITY_LABEL: Record<string, string> = { high: '高', medium: '中', low: '低' }

/** 指标变化对用户是好是坏：direction=+1 越高越好；-1 越低越好；0 中性 */
export function deltaTone(direction: number, delta?: number | null, z?: number | null): 'good' | 'bad' | 'neutral' {
  if (delta === null || delta === undefined || direction === 0) return 'neutral'
  const signed = Math.sign(delta) * direction
  const strong = z === null || z === undefined ? Math.abs(delta) > 0 : Math.abs(z) >= 0.5
  if (!strong) return 'neutral'
  return signed > 0 ? 'good' : 'bad'
}

export function recoveryColor(v?: number | null): string {
  if (v === null || v === undefined) return 'var(--muted)'
  if (v >= 67) return 'var(--good)'
  if (v >= 34) return 'var(--warning)'
  return 'var(--critical)'
}

export function levelColor(level?: string | null): string {
  switch (level) {
    case 'good':
      return 'var(--good)'
    case 'normal':
      return 'var(--series-1)'
    case 'low':
      return 'var(--warning)'
    case 'very_low':
      return 'var(--critical)'
    default:
      return 'var(--muted)'
  }
}

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

export function fmtP(p?: number | null): string {
  if (p === null || p === undefined) return 'p=—'
  return p < 0.001 ? 'p<0.001' : `p=${p.toFixed(3)}`
}
