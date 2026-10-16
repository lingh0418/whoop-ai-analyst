import { useState } from 'react'
import { api, WEEKDAYS, type Json } from '../api'
import { useApi } from '../components/useApi'

function Memories() {
  const { data, reload } = useApi<Json[]>('/api/memories')
  const [content, setContent] = useState('')
  const [date, setDate] = useState('')
  const [busy, setBusy] = useState(false)
  const add = async () => {
    if (!content.trim()) return
    setBusy(true)
    try {
      await api.post('/api/memories', { content, event_date: date || null })
      setContent('')
      setDate('')
      reload()
    } finally {
      setBusy(false)
    }
  }
  const quick = ['昨晚喝了酒', '昨晚熬夜到很晚', '这几天考试压力大', '感冒了，嗓子疼', '今天出差坐飞机', '这周是 Deload 周', '开始减脂']
  return (
    <div className="card">
      <div className="card-title">长期记忆 <span className="hint">帮助解释 WHOOP 数据：之后分析恢复时会把这些作为“可能的相关因素之一”</span></div>
      <div className="stack" style={{ gap: 10 }}>
        <textarea className="input" rows={2} placeholder="例如：昨晚和朋友聚餐喝了 3 杯啤酒" value={content} onChange={(e) => setContent(e.target.value)} />
        <div className="row">
          {quick.map((q) => <span key={q} className="chip suggest" onClick={() => setContent(q)}>{q}</span>)}
        </div>
        <div className="row">
          <label className="field" style={{ width: 180 }}>事件日期（留空自动识别“昨晚/前天”）
            <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </label>
          <span className="spacer" />
          <button className="btn btn-primary" onClick={add} disabled={busy || !content.trim()}>记录</button>
        </div>
      </div>
      <table className="tbl" style={{ marginTop: 14 }}>
        <thead><tr><th>日期</th><th>内容</th><th>标签</th><th>来源</th><th /></tr></thead>
        <tbody>
          {(data ?? []).slice(0, 60).map((m) => (
            <tr key={m.id}>
              <td style={{ whiteSpace: 'nowrap' }}>{m.date}{m.category === 'state' ? <span className="chip small" style={{ marginLeft: 6 }}>状态</span> : null}</td>
              <td>{m.content}</td>
              <td>{m.tag_labels.map((t: string) => <span key={t} className="chip small" style={{ marginRight: 4 }}>{t}</span>)}</td>
              <td className="muted small">{{ manual: '手动', chat: '对话', demo: 'Demo' }[m.source as string] ?? m.source}</td>
              <td><button className="btn btn-sm btn-danger" onClick={async () => { await api.del(`/api/memories/${m.id}`); reload() }}>删除</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function parseExercises(text: string): Json[] {
  return text.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => {
    const [name, sets, reps, rpe] = l.split('|').map((x) => x.trim())
    return { name, sets: sets ? Number(sets) : null, reps: reps || null, rpe: rpe ? Number(rpe) : null }
  })
}

function exercisesText(ex: Json[]): string {
  return ex.map((e) => [e.name, e.sets ?? '', e.reps ?? '', e.rpe ?? ''].join(' | ')).join('\n')
}

function TrainingTemplate() {
  const { data, reload } = useApi<Json[]>('/api/training-plans')
  const [editing, setEditing] = useState<number | null>(null)
  const [form, setForm] = useState({ title: '', intensity: 'moderate', exercises: '' })
  const byDay = new Map<number, Json>((data ?? []).filter((p) => p.date === null).map((p) => [p.weekday, p]))
  const startEdit = (wd: number) => {
    const p = byDay.get(wd)
    setForm({ title: p?.title ?? '', intensity: p?.intensity ?? 'moderate', exercises: exercisesText(p?.exercises ?? []) })
    setEditing(wd)
  }
  const save = async () => {
    if (editing === null) return
    await api.post('/api/training-plans', { weekday: editing, title: form.title || '训练', focus: form.title, intensity: form.intensity, exercises: parseExercises(form.exercises) })
    setEditing(null)
    reload()
  }
  return (
    <div className="card">
      <div className="card-title">每周训练模板 <span className="hint">Dashboard 会根据当天身体状态自动给出调整方案</span></div>
      <table className="tbl">
        <thead><tr><th>星期</th><th>训练</th><th>强度</th><th>动作</th><th /></tr></thead>
        <tbody>
          {WEEKDAYS.map((name, wd) => {
            const p = byDay.get(wd)
            return (
              <tr key={wd}>
                <td>{name}</td>
                <td>{p?.title ?? <span className="muted">未设置</span>}</td>
                <td>{p ? { low: '低', moderate: '中', high: '高' }[p.intensity as string] : ''}</td>
                <td className="small text-2">{(p?.exercises ?? []).map((e: Json) => `${e.name} ${e.sets ?? ''}×${e.reps ?? ''}${e.rpe ? ` @RPE${e.rpe}` : ''}`).join('；')}</td>
                <td><button className="btn btn-sm" onClick={() => startEdit(wd)}>编辑</button></td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {editing !== null && (
        <div className="stack" style={{ gap: 10, marginTop: 14, padding: 14, background: 'var(--surface-2)', borderRadius: 10 }}>
          <strong>编辑{WEEKDAYS[editing]}</strong>
          <div className="row">
            <label className="field" style={{ flex: 1 }}>训练名称<input className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="胸 + 三头 / 休息日" /></label>
            <label className="field" style={{ width: 140 }}>强度
              <select className="input" value={form.intensity} onChange={(e) => setForm({ ...form, intensity: e.target.value })}>
                <option value="low">低</option><option value="moderate">中</option><option value="high">高</option>
              </select>
            </label>
          </div>
          <label className="field">动作（每行：名称 | 组数 | 次数 | RPE）
            <textarea className="input" rows={5} value={form.exercises} onChange={(e) => setForm({ ...form, exercises: e.target.value })} placeholder={'Bench Press | 4 | 6 | 8\nCable Fly | 3 | 12 | 8'} />
          </label>
          <div className="row"><span className="spacer" /><button className="btn" onClick={() => setEditing(null)}>取消</button><button className="btn btn-primary" onClick={save}>保存</button></div>
        </div>
      )}
    </div>
  )
}

function NutritionTemplate() {
  const { data, reload } = useApi<Json[]>('/api/nutrition-plans')
  const byDay = new Map<number, Json>((data ?? []).filter((p) => p.date === null).map((p) => [p.weekday, p]))
  const [draft, setDraft] = useState<Record<number, Json>>({})
  const val = (wd: number, k: string) => draft[wd]?.[k] ?? byDay.get(wd)?.[k] ?? ''
  const set = (wd: number, k: string, v: string) => setDraft({ ...draft, [wd]: { ...(draft[wd] ?? {}), [k]: v } })
  const save = async (wd: number) => {
    const base = byDay.get(wd) ?? {}
    const merged = { ...base, ...(draft[wd] ?? {}) }
    const num = (x: Json) => (x === '' || x === null || x === undefined ? null : Number(x))
    await api.post('/api/nutrition-plans', {
      weekday: wd, day_type: merged.day_type || 'normal', goal: merged.goal || 'maintain',
      calories: num(merged.calories), protein: num(merged.protein), carbs: num(merged.carbs), fat: num(merged.fat),
    })
    setDraft({ ...draft, [wd]: undefined })
    reload()
  }
  return (
    <div className="card">
      <div className="card-title">饮食计划 <span className="hint">只需宏量营养素，不做食物记录</span></div>
      <table className="tbl">
        <thead><tr><th>星期</th><th>目标</th><th>类型</th><th>热量</th><th>蛋白质</th><th>碳水</th><th>脂肪</th><th /></tr></thead>
        <tbody>
          {WEEKDAYS.map((name, wd) => (
            <tr key={wd}>
              <td>{name}</td>
              <td>
                <select className="input" value={val(wd, 'goal') || 'maintain'} onChange={(e) => set(wd, 'goal', e.target.value)}>
                  <option value="cut">减脂</option><option value="maintain">维持</option><option value="bulk">增肌</option>
                </select>
              </td>
              <td>
                <select className="input" value={val(wd, 'day_type') || 'normal'} onChange={(e) => set(wd, 'day_type', e.target.value)}>
                  <option value="high_carb">高碳日</option><option value="normal">常规</option><option value="low_carb">低碳日</option>
                </select>
              </td>
              {['calories', 'protein', 'carbs', 'fat'].map((k) => (
                <td key={k}><input className="input" style={{ width: 80 }} type="number" value={val(wd, k)} onChange={(e) => set(wd, k, e.target.value)} /></td>
              ))}
              <td>{draft[wd] && <button className="btn btn-sm btn-primary" onClick={() => save(wd)}>保存</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Weight() {
  const today = new Date().toISOString().slice(0, 10)
  const [date, setDate] = useState(today)
  const [kg, setKg] = useState('')
  const [msg, setMsg] = useState('')
  const save = async () => {
    await api.post('/api/body/weight', { date, weight_kg: Number(kg) })
    setMsg('已保存')
    setKg('')
  }
  return (
    <div className="card">
      <div className="card-title">记录体重</div>
      <div className="row">
        <input className="input" style={{ width: 170 }} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <input className="input" style={{ width: 120 }} type="number" step="0.1" placeholder="kg" value={kg} onChange={(e) => setKg(e.target.value)} />
        <button className="btn btn-primary" disabled={!kg} onClick={save}>保存</button>
        {msg && <span className="muted small">{msg}</span>}
      </div>
    </div>
  )
}

export default function Journal() {
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="page-title">记录与计划</div>
          <div className="page-sub">长期记忆、训练与饮食计划 —— 都是为了让 WHOOP 分析更个性化</div>
        </div>
      </div>
      <Memories />
      <TrainingTemplate />
      <NutritionTemplate />
      <Weight />
    </div>
  )
}
