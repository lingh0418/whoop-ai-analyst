import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, fmtPct, type Json } from '../api'
import { useApi } from '../components/useApi'

function WhoopCard({ status, onChange }: { status: Json; onChange: () => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [params] = useSearchParams()
  const w = status.whoop
  const run = async (key: string, fn: () => Promise<Json>, ok: (r: Json) => string) => {
    setBusy(key)
    setMsg(null)
    try {
      const r = await fn()
      setMsg(ok(r))
      onChange()
    } catch (e) {
      setMsg(`失败：${(e as Error).message}`)
    } finally {
      setBusy(null)
    }
  }
  return (
    <div className="card">
      <div className="card-title">WHOOP 连接</div>
      {params.get('whoop') === 'error' && <div className="banner warn" style={{ marginBottom: 10 }}>WHOOP 授权失败：{params.get('reason')}</div>}
      {params.get('whoop') === 'connected' && <div className="banner" style={{ marginBottom: 10 }}>WHOOP 已连接{params.get('sync') === 'failed' ? '，但首次同步失败，请点击“立即同步”重试' : ''}</div>}
      <div className="stack" style={{ gap: 10 }}>
        <div className="row">
          <span className={`chip ${w.connected ? 'good' : ''}`}>{w.connected ? '● 已连接' : '○ 未连接'}</span>
          {w.last_sync_at && <span className="muted small">上次同步：{w.last_sync_at.replace('T', ' ').slice(0, 16)} UTC · {w.last_sync_status}</span>}
        </div>
        {!w.configured && (
          <div className="banner warn">
            尚未配置 WHOOP 开发者应用。请在 <a href="https://developer-dashboard.whoop.com" target="_blank" rel="noreferrer">WHOOP Developer Dashboard</a> 创建应用，
            把 Redirect URL 设为 <code>http://localhost:8000/api/whoop/auth/callback</code>，然后在 .env 中填写 WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET 并重启后端。
          </div>
        )}
        <div className="row">
          <a className={`btn btn-primary ${!w.configured ? 'disabled' : ''}`} href={w.configured ? '/api/whoop/auth/login' : undefined} aria-disabled={!w.configured}
            style={!w.configured ? { opacity: 0.5, pointerEvents: 'none' } : undefined}>
            {w.connected ? '重新授权 WHOOP' : '连接 WHOOP'}
          </a>
          <button className="btn" disabled={!w.connected || !!busy} onClick={() => run('sync', () => api.post('/api/whoop/sync'), (r) => `同步完成：${r.fetched.cycles} 个周期，${r.fetched.workouts} 次训练`)}>
            {busy === 'sync' ? '同步中…' : '立即同步'}
          </button>
          <button className="btn" disabled={!w.connected || !!busy} onClick={() => run('full', () => api.post('/api/whoop/sync?full=true'), () => '全量同步完成')}>
            {busy === 'full' ? '同步中…' : '全量重新同步'}
          </button>
          {w.connected && <button className="btn btn-danger" onClick={() => run('disc', () => api.del('/api/whoop/connection'), () => '已断开')}>断开</button>}
        </div>
        <hr style={{ border: 0, borderTop: '1px solid var(--border)', width: '100%' }} />
        <div className="row">
          <div style={{ flex: 1 }}>
            <strong>Demo 数据</strong>
            <div className="muted small">没有 WHOOP 也可以体验：生成 200 天模拟数据（包含睡眠不足、饮酒、连续高负荷、生病等情景）。会覆盖当前数据。</div>
          </div>
          <button className="btn" disabled={!!busy} onClick={() => confirm('生成 Demo 数据会覆盖当前所有数据，确定吗？') && run('demo', () => api.post('/api/demo/seed', { days: 200 }), (r) => `已生成 ${r.demo.days} 天 Demo 数据，发现 ${r.analysis.patterns} 条规律`)}>
            {busy === 'demo' ? '生成中…' : '生成 Demo 数据'}
          </button>
          <button className="btn" disabled={!!busy || !status.data.days} onClick={() => run('re', () => api.post('/api/recompute'), (r) => `已重算 ${r.days} 天（${r.seconds}s）`)}>
            {busy === 're' ? '重算中…' : '重算分析'}
          </button>
        </div>
        {msg && <div className="banner">{msg}</div>}
      </div>
    </div>
  )
}

function LLMCard({ status }: { status: Json }) {
  const l = status.llm
  return (
    <div className="card">
      <div className="card-title">AI 模型</div>
      <div className="row" style={{ marginBottom: 8 }}>
        <span className={`chip ${l.enabled ? 'good' : ''}`}>{l.enabled ? `● ${l.provider} · ${l.model}` : '○ 规则引擎模式'}</span>
      </div>
      <p className="text-2 small" style={{ margin: 0 }}>
        {l.enabled ? '大模型只负责理解、联合判断和中文解释；所有统计由 Python 分析层完成。' : l.note}
      </p>
      <pre className="tool-detail" style={{ marginTop: 10 }}>{`# .env 示例（任选其一）
# DeepSeek
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_API_KEY=sk-...

# 通义千问：LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1  LLM_MODEL=qwen-plus
# Claude：LLM_PROVIDER=anthropic  ANTHROPIC_API_KEY=...`}</pre>
    </div>
  )
}

const RULE_ORDER = ['hrv_drop', 'rhr_rise', 'sleep_short', 'recovery_drop', 'strain_spike', 'resp_rate_rise']

function ThresholdCard() {
  const { data, reload } = useApi('/api/settings')
  const sug = useApi('/api/settings/threshold-suggestions')
  const [mode, setMode] = useState('adaptive')
  const [pcts, setPcts] = useState<Record<string, number>>({})
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  useEffect(() => {
    if (!data) return
    setMode(data.anomaly_rules.mode)
    const p: Record<string, number> = {}
    for (const k of RULE_ORDER) if (data.anomaly_rules.rules[k]) p[k] = data.anomaly_rules.rules[k].pct
    setPcts(p)
  }, [data])

  if (!data) return null
  const rules = data.anomaly_rules.rules
  const save = async (override?: Record<string, number>) => {
    setBusy(true)
    setMsg(null)
    const values = override ?? pcts
    const ruleOverrides: Record<string, Json> = {}
    for (const k of Object.keys(values)) ruleOverrides[k] = { pct: values[k] }
    try {
      const r = await api.put('/api/settings', { anomaly_rules: { mode, rules: ruleOverrides } })
      setMsg(`已保存，并重新检测了 ${r.recomputed?.days ?? 0} 天的数据（${r.recomputed?.anomalies ?? 0} 条异常）`)
      reload()
      sug.reload()
    } catch (e) {
      setMsg(`保存失败：${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }
  const applySuggestions = () => {
    const next = { ...pcts }
    for (const k of Object.keys(sug.data ?? {})) next[k] = sug.data[k].suggested_pct
    setPcts(next)
    save(next)
  }
  return (
    <div className="card">
      <div className="card-title">异常检测阈值 <span className="hint">相对个人 28 日基线的偏差</span></div>
      <div className="row" style={{ marginBottom: 12 }}>
        <span className="small text-2">模式：</span>
        <div className="seg">
          <button className={mode === 'adaptive' ? 'on' : ''} onClick={() => setMode('adaptive')}>自适应（参考个人波动）</button>
          <button className={mode === 'fixed' ? 'on' : ''} onClick={() => setMode('fixed')}>固定百分比</button>
        </div>
      </div>
      <table className="tbl">
        <thead><tr><th>规则</th><th>阈值</th><th>按你的数据建议</th><th>当前触发率</th></tr></thead>
        <tbody>
          {RULE_ORDER.filter((k) => rules[k]).map((k) => {
            const s = sug.data?.[k]
            return (
              <tr key={k}>
                <td>{rules[k].label}</td>
                <td>
                  <div className="row" style={{ flexWrap: 'nowrap' }}>
                    <input className="input" style={{ width: 80 }} type="number" step="1" min="1" max="80"
                      value={pcts[k] !== undefined ? Math.round(pcts[k] * 1000) / 10 : ''}
                      onChange={(e) => setPcts({ ...pcts, [k]: Number(e.target.value) / 100 })} />
                    <span className="muted">%</span>
                  </div>
                </td>
                <td>{s ? `${fmtPct(s.suggested_pct, 1, false)}（约 ${fmtPct(s.suggested_trigger_rate, 0, false)} 的日子）` : '—'}</td>
                <td>{s ? fmtPct(s.current_trigger_rate, 0, false) : '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 12 }}>
        <span className="muted small">建议值让大约 7% 的日子触发提醒，可按需要调整。</span>
        <span className="spacer" />
        <button className="btn" disabled={busy || !sug.data} onClick={applySuggestions}>采用建议值</button>
        <button className="btn btn-primary" disabled={busy} onClick={() => save()}>{busy ? '保存中…' : '保存并重新检测'}</button>
      </div>
      {msg && <div className="banner" style={{ marginTop: 10 }}>{msg}</div>}
    </div>
  )
}

function ProfileCard() {
  const { data, reload } = useApi('/api/settings')
  const [name, setName] = useState('')
  const [goal, setGoal] = useState('maintain')
  const [note, setNote] = useState('')
  useEffect(() => {
    if (!data) return
    setName(data.name)
    setGoal(data.profile.goal ?? 'maintain')
    setNote(data.profile.note ?? '')
  }, [data])
  if (!data) return null
  return (
    <div className="card">
      <div className="card-title">个人背景 <span className="hint">会提供给 AI 作为上下文</span></div>
      <div className="row">
        <label className="field" style={{ width: 160 }}>称呼<input className="input" value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="field" style={{ width: 140 }}>当前目标
          <select className="input" value={goal} onChange={(e) => setGoal(e.target.value)}>
            <option value="cut">减脂</option><option value="maintain">维持</option><option value="bulk">增肌</option><option value="performance">提升表现</option>
          </select>
        </label>
        <label className="field" style={{ flex: 1, minWidth: 200 }}>补充说明<input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="训练年限、项目、作息等" /></label>
        <button className="btn btn-primary" style={{ alignSelf: 'flex-end' }} onClick={async () => { await api.put('/api/settings', { name, profile: { ...data.profile, goal, note } }); reload() }}>保存</button>
      </div>
    </div>
  )
}

export default function Settings({ status, refresh }: { status: Json; refresh: () => void }) {
  if (!status) return <div className="loading">加载中…</div>
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="page-title">设置</div>
          <div className="page-sub">数据来源、AI 模型、异常检测阈值</div>
        </div>
      </div>
      <WhoopCard status={status} onChange={refresh} />
      <div className="grid grid-2">
        <LLMCard status={status} />
        <ProfileCard />
      </div>
      <ThresholdCard />
    </div>
  )
}
